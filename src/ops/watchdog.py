"""
服务看门狗 (Watchdog)

监控 Docker 容器服务健康状态，自动重启失败的服务。
连续失败 N 次后通过 Bark / Telegram 发送告警通知。

用法:
    watchdog = ServiceWatchdog(
        services=["collector", "trader", "scheduler", "notifier"],
        max_failures=3,
        check_interval=60,
    )
    await watchdog.start()
"""

import asyncio
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

from src.ops.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ServiceHealth:
    """单个服务的健康状态"""

    name: str
    consecutive_failures: int = 0
    last_check: datetime | None = None
    last_healthy: datetime | None = None
    last_restart: datetime | None = None
    restart_count: int = 0
    alerted: bool = False  # 已发送过 N 次失败告警
    status: str = "unknown"  # healthy, unhealthy, restarting, alert_sent


class ServiceWatchdog:
    """
    服务看门狗

    - 定期检查 Docker 容器状态
    - 容器不健康时自动 docker compose restart
    - 连续 N 次失败后发送告警通知
    """

    # Docker Compose 项目名 → 容器名映射
    CONTAINER_PREFIX = "algorithmtrader"

    def __init__(
        self,
        services: list[str] | None = None,
        max_failures: int = 3,
        check_interval: float = 60.0,
        compose_file: str | None = None,
    ):
        """
        Args:
            services: 要监控的服务列表 (docker compose service 名称)
            max_failures: 连续失败多少次后告警
            check_interval: 检查间隔（秒）
            compose_file: docker-compose.yml 路径
        """
        self.services = services or ["collector", "trader", "scheduler", "notifier"]
        self.max_failures = max_failures
        self.check_interval = check_interval
        self.compose_file = compose_file

        self._health: dict[str, ServiceHealth] = {
            svc: ServiceHealth(name=svc) for svc in self.services
        }
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def health_status(self) -> dict[str, ServiceHealth]:
        return self._health.copy()

    async def start(self) -> None:
        """启动看门狗"""
        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        logger.info(
            "watchdog_started",
            services=self.services,
            max_failures=self.max_failures,
            interval=self.check_interval,
        )

    async def stop(self) -> None:
        """停止看门狗"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("watchdog_stopped")

    async def _watch_loop(self) -> None:
        """主监控循环"""
        while self._running:
            try:
                await self._check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("watchdog_loop_error", error=str(e))

            await asyncio.sleep(self.check_interval)

    async def _check_all(self) -> None:
        """检查所有服务"""
        for service_name in self.services:
            health = self._health[service_name]
            health.last_check = datetime.now(UTC)

            is_running = await self._is_container_running(service_name)

            if is_running:
                # 服务正常
                health.consecutive_failures = 0
                health.status = "healthy"
                health.last_healthy = datetime.now(UTC)
                health.alerted = False
            else:
                # 服务异常
                health.consecutive_failures += 1
                health.status = "unhealthy"

                logger.warning(
                    "watchdog_service_unhealthy",
                    service=service_name,
                    failures=health.consecutive_failures,
                )

                if health.consecutive_failures >= self.max_failures:
                    # 达到告警阈值
                    if not health.alerted:
                        health.status = "alert_sent"
                        health.alerted = True
                        await self._send_alert(service_name, health)
                else:
                    # 尝试自动重启
                    health.status = "restarting"
                    success = await self._restart_service(service_name)
                    if success:
                        health.restart_count += 1
                        health.last_restart = datetime.now(UTC)
                        logger.info(
                            "watchdog_service_restarted",
                            service=service_name,
                            restart_count=health.restart_count,
                        )
                    else:
                        logger.error(
                            "watchdog_restart_failed",
                            service=service_name,
                        )

    async def _is_container_running(self, service_name: str) -> bool:
        """检查容器是否在运行"""
        container_names = [
            f"{self.CONTAINER_PREFIX}-{service_name}",
            f"{self.CONTAINER_PREFIX}-{service_name}-1",
            f"{self.CONTAINER_PREFIX}_{service_name}_1",
        ]

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "ps", "--format", "{{.Names}}\t{{.State}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return False

            running_containers = {}
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    running_containers[parts[0]] = parts[1]

            for name in container_names:
                if name in running_containers and running_containers[name] == "running":
                    return True

            return False

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug("watchdog_docker_check_error", error=str(e))
            return False

    async def _restart_service(self, service_name: str) -> bool:
        """尝试重启服务"""
        try:
            cmd = ["docker", "compose", "restart", service_name]
            if self.compose_file:
                cmd = [
                    "docker",
                    "compose",
                    "-f",
                    self.compose_file,
                    "restart",
                    service_name,
                ]

            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            return result.returncode == 0

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.error("watchdog_restart_error", service=service_name, error=str(e))
            return False

    async def _send_alert(self, service_name: str, health: ServiceHealth) -> None:
        """发送告警通知 (Bark + Telegram)"""
        title = f"🚨 服务持续异常: {service_name}"
        message = (
            f"服务 {service_name} 已连续 {health.consecutive_failures} 次检测失败。\n"
            f"上次正常: {health.last_healthy.strftime('%Y-%m-%d %H:%M:%S') if health.last_healthy else '从未'}\n"
            f"累计重启: {health.restart_count} 次\n"
            f"请立即检查！"
        )

        logger.error(
            "watchdog_alert_sent",
            service=service_name,
            failures=health.consecutive_failures,
        )

        # 发送 Bark 通知
        await self._send_bark_alert(title, message)

        # 发送 Telegram 通知
        await self._send_telegram_alert(title, message)

    async def _send_bark_alert(self, title: str, body: str) -> None:
        """发送 Bark 告警"""
        import aiohttp

        bark_urls_str = os.getenv("BARK_URLS", "")
        webhook_url = os.getenv("WEBHOOK_URL", "")

        urls: list[str] = []
        if bark_urls_str:
            urls.extend([u.strip() for u in bark_urls_str.split(",") if u.strip()])
        elif webhook_url and "api.day.app" in webhook_url:
            urls.append(webhook_url)

        for url in urls:
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as session:
                    payload = {
                        "title": title,
                        "body": body,
                        "group": "AlgorithmTrader",
                        "level": "timeSensitive",
                    }
                    async with session.post(url.rstrip("/"), json=payload) as resp:
                        if resp.status in (200, 201, 204):
                            logger.info("watchdog_bark_sent", url=url[:30])
                        else:
                            logger.warning("watchdog_bark_failed", status=resp.status)
            except Exception as e:
                logger.warning("watchdog_bark_error", error=str(e))

    async def _send_telegram_alert(self, title: str, body: str) -> None:
        """发送 Telegram 告警"""
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        if not bot_token or not chat_id:
            return

        try:
            import aiohttp

            text = f"<b>{title}</b>\n\n{body}"
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            }

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info("watchdog_telegram_sent")
                    else:
                        data = await resp.text()
                        logger.warning(
                            "watchdog_telegram_failed",
                            status=resp.status,
                            body=data[:200],
                        )
        except Exception as e:
            logger.warning("watchdog_telegram_error", error=str(e))


# 全局单例
_watchdog: ServiceWatchdog | None = None


def get_watchdog() -> ServiceWatchdog:
    """获取全局看门狗实例"""
    global _watchdog
    if _watchdog is None:
        _watchdog = ServiceWatchdog()
    return _watchdog
