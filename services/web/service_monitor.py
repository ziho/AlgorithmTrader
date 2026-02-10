"""
服务状态监控

提供实时服务健康状态检查

支持多种检测方式:
1. HTTP 健康端点 (InfluxDB, Grafana, Web)
2. 心跳文件检查 (Collector, Trader, Scheduler, Notifier)
3. Docker 容器状态检查 (备用)
4. 进程文件检查 (.pid 文件, 备用)
"""

import asyncio
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from services.web.utils import candidate_urls
from src.core.config import get_settings
from src.ops.heartbeat import is_heartbeat_stale, read_all_heartbeats


@dataclass
class ServiceStatus:
    """服务状态"""

    name: str
    status: str  # healthy, unhealthy, unknown
    message: str
    last_check: datetime = field(default_factory=datetime.now)
    details: dict = field(default_factory=dict)
    url: str | None = None  # 可访问的 URL


class ServiceMonitor:
    """
    服务状态监控器

    监控以下服务:
    - InfluxDB: 数据库 (HTTP 端点)
    - Grafana: 可视化 (HTTP 端点)
    - Collector: 数据采集服务 (容器状态)
    - Trader: 交易服务 (容器状态)
    - Scheduler: 调度服务 (容器状态)
    - Notifier: 通知服务 (容器状态)
    """

    # 容器名称与服务名称映射
    CONTAINER_SERVICES = {
        "algorithmtrader-collector": "Collector",
        "algorithmtrader-trader": "Trader",
        "algorithmtrader-scheduler": "Scheduler",
        "algorithmtrader-notifier": "Notifier",
        "algorithmtrader-collector-1": "Collector",
        "algorithmtrader-trader-1": "Trader",
        "algorithmtrader-scheduler-1": "Scheduler",
        "algorithmtrader-notifier-1": "Notifier",
        "algorithmtrader_collector_1": "Collector",
        "algorithmtrader_trader_1": "Trader",
        "algorithmtrader_scheduler_1": "Scheduler",
        "algorithmtrader_notifier_1": "Notifier",
        # Compose V2 命名
        "collector": "Collector",
        "trader": "Trader",
        "scheduler": "Scheduler",
        "notifier": "Notifier",
    }

    def __init__(self):
        self._statuses: dict[str, ServiceStatus] = {}
        self._callbacks: list[Callable] = []
        self._data_dir = Path("/app/data")
        settings = get_settings()
        self._influx_url = settings.influxdb.url
        self._grafana_url = os.getenv("GRAFANA_URL", "http://grafana:3000")

    def get_all_statuses(self) -> list[ServiceStatus]:
        """获取所有服务状态"""
        return list(self._statuses.values())

    def get_status(self, service_name: str) -> ServiceStatus | None:
        """获取指定服务状态"""
        return self._statuses.get(service_name)

    async def check_all(self) -> list[ServiceStatus]:
        """检查所有服务状态"""
        # HTTP 端点检查
        http_tasks = [
            self._check_influxdb(),
            self._check_grafana(),
        ]

        http_results = await asyncio.gather(*http_tasks, return_exceptions=True)

        for result in http_results:
            if isinstance(result, ServiceStatus):
                self._statuses[result.name] = result

        # 容器状态检查
        container_statuses = await self._check_docker_containers()
        for status in container_statuses:
            self._statuses[status.name] = status

        # 触发回调
        for callback in self._callbacks:
            try:
                callback(self._statuses)
            except Exception:
                pass

        return self.get_all_statuses()

    async def _check_influxdb(self) -> ServiceStatus:
        """检查 InfluxDB 连接"""
        last_error: str | None = None
        for url in candidate_urls(self._influx_url, service_host="influxdb"):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{url.rstrip('/')}/health")

                    if response.status_code == 200:
                        data = response.json()
                        version = data.get("version", "unknown")
                        # 版本号可能已经包含 'v' 前缀
                        version_str = (
                            version if version.startswith("v") else f"v{version}"
                        )
                        return ServiceStatus(
                            name="InfluxDB",
                            status="healthy",
                            message=version_str,
                            url="http://localhost:8086",
                            details=data,
                        )
                    return ServiceStatus(
                        name="InfluxDB",
                        status="unhealthy",
                        message=f"HTTP {response.status_code}",
                        url="http://localhost:8086",
                    )
            except httpx.ConnectError as e:
                last_error = str(e)
                continue
            except Exception as e:
                return ServiceStatus(
                    name="InfluxDB",
                    status="unhealthy",
                    message=str(e)[:50],
                )
        return ServiceStatus(
            name="InfluxDB",
            status="unknown",
            message="无法连接" if last_error is None else last_error[:50],
        )

    async def _check_grafana(self) -> ServiceStatus:
        """检查 Grafana 连接"""
        last_error: str | None = None
        for url in candidate_urls(self._grafana_url, service_host="grafana"):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{url.rstrip('/')}/api/health")

                    if response.status_code == 200:
                        data = response.json()
                        return ServiceStatus(
                            name="Grafana",
                            status="healthy",
                            message=f"v{data.get('version', 'unknown')}",
                            url="http://localhost:3000",
                            details=data,
                        )
                    return ServiceStatus(
                        name="Grafana",
                        status="unhealthy",
                        message=f"HTTP {response.status_code}",
                        url="http://localhost:3000",
                    )
            except httpx.ConnectError as e:
                last_error = str(e)
                continue
            except Exception as e:
                return ServiceStatus(
                    name="Grafana",
                    status="unhealthy",
                    message=str(e)[:50],
                )
        return ServiceStatus(
            name="Grafana",
            status="unknown",
            message="无法连接" if last_error is None else last_error[:50],
        )

    async def _check_docker_containers(self) -> list[ServiceStatus]:
        """检查服务容器状态（优先心跳文件，Docker 命令备用）"""
        # 先尝试心跳文件（跨容器共享 logs 目录）
        statuses = self._check_heartbeats()
        if statuses:
            return statuses

        # 备用: Docker CLI
        statuses = self._check_via_docker()
        if statuses:
            return statuses

        # 最终备用: PID 文件
        return await self._check_pid_files()

    # ------------------------------------------------------------------
    # 心跳文件检查 (首选)
    # ------------------------------------------------------------------

    def _check_heartbeats(self) -> list[ServiceStatus]:
        """通过心跳文件检查服务状态"""
        heartbeats = read_all_heartbeats()

        # 没有任何心跳文件 → 回退到其他方法
        if not heartbeats:
            return []

        statuses: list[ServiceStatus] = []
        services = ["collector", "trader", "scheduler", "notifier"]

        for svc in services:
            display_name = svc.capitalize()
            hb = heartbeats.get(svc)

            if hb is None:
                statuses.append(
                    ServiceStatus(
                        name=display_name,
                        status="unknown",
                        message="服务未启用",
                    )
                )
                continue

            if is_heartbeat_stale(hb):
                statuses.append(
                    ServiceStatus(
                        name=display_name,
                        status="unhealthy",
                        message="心跳超时",
                        details=hb.details,
                    )
                )
                continue

            if hb.status in ("running", "starting"):
                uptime_str = self._format_uptime(hb.uptime_seconds)
                statuses.append(
                    ServiceStatus(
                        name=display_name,
                        status="healthy",
                        message=f"运行 {uptime_str}",
                        details=hb.details,
                    )
                )
            elif hb.status == "error":
                statuses.append(
                    ServiceStatus(
                        name=display_name,
                        status="unhealthy",
                        message=hb.details.get("error", "异常")[:50],
                        details=hb.details,
                    )
                )
            else:
                statuses.append(
                    ServiceStatus(
                        name=display_name,
                        status="unknown",
                        message=hb.status,
                        details=hb.details,
                    )
                )

        return statuses

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """格式化运行时长"""
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds // 60)}m"
        if seconds < 86400:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h{minutes}m"
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}d{hours}h"

    # ------------------------------------------------------------------
    # Docker CLI 检查 (备用)
    # ------------------------------------------------------------------

    def _check_via_docker(self) -> list[ServiceStatus]:
        """通过 Docker CLI 检查容器状态（备用方案）"""
        statuses: list[ServiceStatus] = []
        service_found: dict[str, bool] = {
            "Collector": False,
            "Trader": False,
            "Scheduler": False,
            "Notifier": False,
        }

        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--format",
                    "{{.Names}}\t{{.Status}}\t{{.State}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return []

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 3:
                    continue

                container_name, status_text, state = parts[0], parts[1], parts[2]
                service_name = None
                for pattern, svc_name in self.CONTAINER_SERVICES.items():
                    if pattern in container_name:
                        service_name = svc_name
                        break

                if service_name and service_name in service_found:
                    service_found[service_name] = True
                    if state == "running":
                        statuses.append(
                            ServiceStatus(
                                name=service_name,
                                status="healthy",
                                message=self._parse_uptime(status_text),
                            )
                        )
                    elif state == "exited":
                        statuses.append(
                            ServiceStatus(
                                name=service_name,
                                status="unhealthy",
                                message="已停止",
                            )
                        )
                    else:
                        statuses.append(
                            ServiceStatus(
                                name=service_name,
                                status="unknown",
                                message=status_text[:30],
                            )
                        )

        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return []

        for service_name, found in service_found.items():
            if not found:
                statuses.append(
                    ServiceStatus(
                        name=service_name,
                        status="unknown",
                        message="服务未部署",
                    )
                )

        return statuses

    @staticmethod
    def _parse_uptime(status_text: str) -> str:
        """解析 Docker 状态文本中的运行时长"""
        if "up" in status_text.lower():
            parts = status_text.split()
            if len(parts) >= 2:
                return f"运行 {' '.join(parts[1:])}"
        return status_text[:30]

    # ------------------------------------------------------------------
    # PID 文件检查 (最终备用)
    # ------------------------------------------------------------------

    async def _check_pid_files(self) -> list[ServiceStatus]:
        """通过 PID 文件检查服务状态（最终备用方案）"""
        statuses: list[ServiceStatus] = []
        pid_dir = self._data_dir / ".pids"
        services = ["collector", "trader", "scheduler", "notifier"]

        for service in services:
            pid_file = pid_dir / f"{service}.pid"
            service_name = service.capitalize()

            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                    statuses.append(
                        ServiceStatus(
                            name=service_name,
                            status="healthy",
                            message=f"PID {pid}",
                        )
                    )
                except (ProcessLookupError, ValueError):
                    statuses.append(
                        ServiceStatus(
                            name=service_name,
                            status="unhealthy",
                            message="进程不存在",
                        )
                    )
                except PermissionError:
                    statuses.append(
                        ServiceStatus(
                            name=service_name,
                            status="healthy",
                            message="运行中",
                        )
                    )
            else:
                statuses.append(
                    ServiceStatus(
                        name=service_name,
                        status="unknown",
                        message="服务未启用",
                    )
                )

        return statuses

    def on_status_change(self, callback: Callable):
        """注册状态变化回调"""
        self._callbacks.append(callback)

    def get_mock_statuses(self) -> list[ServiceStatus]:
        """
        获取模拟状态（开发/演示用）

        当无法连接到真实服务时使用
        """
        return [
            ServiceStatus(
                name="InfluxDB",
                status="healthy",
                message="v2.7.0",
                url="http://localhost:8086",
            ),
            ServiceStatus(
                name="Grafana",
                status="healthy",
                message="v10.0.0",
                url="http://localhost:3000",
            ),
            ServiceStatus(
                name="Collector",
                status="healthy",
                message="运行 2 hours",
            ),
            ServiceStatus(
                name="Trader",
                status="unknown",
                message="服务未部署",
            ),
            ServiceStatus(
                name="Scheduler",
                status="healthy",
                message="运行 2 hours",
            ),
            ServiceStatus(
                name="Notifier",
                status="healthy",
                message="运行 2 hours",
            ),
        ]


# 全局实例
_monitor: ServiceMonitor | None = None


def get_monitor() -> ServiceMonitor:
    """获取全局监控器实例"""
    global _monitor
    if _monitor is None:
        _monitor = ServiceMonitor()
    return _monitor
