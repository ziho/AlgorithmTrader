"""
Notifier 服务入口

运行方式:
    python -m services.notifier.main

职责:
- 作为独立进程运行
- 从消息队列/Redis 消费通知消息
- 发送到 Telegram 等通知渠道
- 限频保护和重试机制
"""

import asyncio
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from src.core.config import get_settings
from src.ops.heartbeat import HeartbeatWriter
from src.ops.logging import configure_logging
from src.ops.notify import (
    NotifyLevel,
    NotifyMessage,
    NotifyType,
    get_notifier,
)

logger = structlog.get_logger(__name__)


@dataclass
class NotifierConfig:
    """Notifier 配置"""

    # 限频配置
    rate_limit_per_second: float = 1.0

    # 重试配置
    max_retries: int = 3
    retry_delay: float = 5.0

    # 聚合配置
    aggregate_window: float = 60.0  # 相同类型消息的聚合窗口(秒)

    # 通知渠道
    telegram_enabled: bool = True

    # 健康检查
    health_check_interval: int = 60


@dataclass
class NotifierState:
    """Notifier 状态"""

    running: bool = False
    started_at: datetime | None = None

    # 统计
    messages_received: int = 0
    messages_sent: int = 0
    messages_failed: int = 0

    # 最近消息
    last_message_time: datetime | None = None


class NotifierService:
    """
    通知服务

    作为独立进程运行，负责:
    1. 消费通知消息
    2. 聚合和限频
    3. 发送到各通知渠道
    4. 处理失败重试
    """

    def __init__(self, config: NotifierConfig | None = None):
        """
        初始化 Notifier 服务

        Args:
            config: 服务配置
        """
        self.config = config or NotifierConfig()
        self.state = NotifierState()

        # 通知器
        self._notifier = get_notifier()

        # 消息队列 (简单实现，生产环境可用 Redis)
        self._message_queue: asyncio.Queue[NotifyMessage] = asyncio.Queue()

        # 聚合缓存
        self._aggregate_cache: dict[str, list[NotifyMessage]] = {}
        self._last_aggregate_flush: dict[str, datetime] = {}

        # 停止信号
        self._stop_event = asyncio.Event()

    def queue_message(self, message: NotifyMessage) -> None:
        """
        将消息加入队列

        Args:
            message: 通知消息
        """
        try:
            self._message_queue.put_nowait(message)
            self.state.messages_received += 1
        except asyncio.QueueFull:
            logger.warning("message_queue_full", title=message.title)

    async def _process_messages(self) -> None:
        """处理消息队列"""
        while not self._stop_event.is_set():
            try:
                # 等待消息，带超时以支持优雅退出
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0,
                )

                await self._send_message(message)

            except TimeoutError:
                continue
            except Exception as e:
                logger.error("message_processing_error", error=str(e))

    async def _send_message(self, message: NotifyMessage) -> bool:
        """
        发送消息

        Args:
            message: 通知消息

        Returns:
            bool: 是否发送成功
        """
        for attempt in range(self.config.max_retries):
            try:
                # 限频
                await asyncio.sleep(1.0 / self.config.rate_limit_per_second)

                # 发送
                success = self._notifier.notify(message)

                if success:
                    self.state.messages_sent += 1
                    self.state.last_message_time = datetime.now(UTC)
                    logger.debug(
                        "message_sent",
                        title=message.title,
                        type=message.notify_type.value,
                    )
                    return True

                logger.warning(
                    "message_send_failed",
                    attempt=attempt + 1,
                    title=message.title,
                )

            except Exception as e:
                logger.error(
                    "message_send_error",
                    attempt=attempt + 1,
                    error=str(e),
                )

            # 重试延迟
            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay)

        self.state.messages_failed += 1
        return False

    async def _health_check_loop(self) -> None:
        """健康检查循环"""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.config.health_check_interval)

                logger.info(
                    "notifier_health_check",
                    messages_received=self.state.messages_received,
                    messages_sent=self.state.messages_sent,
                    messages_failed=self.state.messages_failed,
                    queue_size=self._message_queue.qsize(),
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("health_check_error", error=str(e))

    async def start(self) -> None:
        """启动服务"""
        logger.info("notifier_service_starting")

        # 初始化 Telegram
        if self.config.telegram_enabled:
            self._notifier.setup_telegram()

        self.state.running = True
        self.state.started_at = datetime.now(UTC)

        # 启动心跳
        self._heartbeat = HeartbeatWriter(
            service="notifier",
            interval=30.0,
            details_func=lambda: {
                "messages_sent": self.state.messages_sent,
                "messages_failed": self.state.messages_failed,
                "telegram_enabled": self.config.telegram_enabled,
            },
        )
        self._heartbeat.start()

        # 启动处理任务
        tasks = [
            asyncio.create_task(self._process_messages()),
            asyncio.create_task(self._health_check_loop()),
        ]

        logger.info("notifier_service_started")

        # 发送启动通知
        self._notifier.notify_system(
            title="🔔 Notifier Service Started",
            content="Notification service is now running.",
        )

        # 等待停止信号
        await self._stop_event.wait()

        # 取消所有任务
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self) -> None:
        """停止服务"""
        logger.info("notifier_service_stopping")

        self.state.running = False
        self._stop_event.set()

        # 停止心跳
        if hasattr(self, "_heartbeat"):
            self._heartbeat.stop()

        # 发送停止通知
        self._notifier.notify_system(
            title="🔕 Notifier Service Stopped",
            content=(
                f"Messages processed: {self.state.messages_sent}\n"
                f"Messages failed: {self.state.messages_failed}"
            ),
        )

        logger.info("notifier_service_stopped")


# ==================== 便捷函数 ====================


def create_test_message() -> NotifyMessage:
    """创建测试消息"""
    return NotifyMessage(
        notify_type=NotifyType.SYSTEM,
        level=NotifyLevel.INFO,
        title="🧪 Test Notification",
        content="This is a test message from the Notifier service.",
        details={"test": True, "timestamp": datetime.now(UTC).isoformat()},
    )


def main() -> None:
    """Notifier 服务主入口"""
    # 配置日志
    configure_logging(service_name="notifier")

    settings = get_settings()

    # 创建服务
    config = NotifierConfig(
        telegram_enabled=settings.telegram.enabled,
    )
    service = NotifierService(config)

    # 信号处理
    def signal_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        logger.info("received_signal", signal=signum)
        service.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logger.info(
            "notifier_main_starting",
            telegram_enabled=config.telegram_enabled,
        )

        # 运行服务
        asyncio.run(service.start())

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
    except Exception as e:
        logger.exception("notifier_main_error", error=str(e))
    finally:
        if service.state.running:
            service.stop()


if __name__ == "__main__":
    main()
