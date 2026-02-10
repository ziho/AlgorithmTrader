"""
通知模块

支持:
- Telegram 通知
- Webhook 通知 (Bark / 通用 Webhook)
- 下单/成交/异常/日终摘要

设计原则:
- 异步发送，不阻塞主流程
- 限频保护
- 消息模板化
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import aiohttp
import structlog

from src.core.config import get_settings

logger = structlog.get_logger(__name__)


class NotifyLevel(str, Enum):
    """通知级别"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotifyType(str, Enum):
    """通知类型"""

    ORDER = "order"  # 下单通知
    FILL = "fill"  # 成交通知
    SIGNAL = "signal"  # 信号通知
    RISK = "risk"  # 风控告警
    SYSTEM = "system"  # 系统通知
    DAILY = "daily"  # 日终摘要


@dataclass
class NotifyMessage:
    """
    通知消息
    """

    notify_type: NotifyType
    level: NotifyLevel
    title: str
    content: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_text(self) -> str:
        """转换为文本消息"""
        emoji_map = {
            NotifyLevel.INFO: "ℹ️",
            NotifyLevel.WARNING: "⚠️",
            NotifyLevel.ERROR: "❌",
            NotifyLevel.CRITICAL: "🚨",
        }
        emoji = emoji_map.get(self.level, "📢")

        text = f"{emoji} *{self.title}*\n\n{self.content}"

        if self.details:
            text += "\n\n_Details:_\n"
            for key, value in self.details.items():
                text += f"• {key}: `{value}`\n"

        text += f"\n_{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC_"

        return text

    def to_html(self) -> str:
        """转换为 HTML 消息"""
        emoji_map = {
            NotifyLevel.INFO: "ℹ️",
            NotifyLevel.WARNING: "⚠️",
            NotifyLevel.ERROR: "❌",
            NotifyLevel.CRITICAL: "🚨",
        }
        emoji = emoji_map.get(self.level, "📢")

        html = f"{emoji} <b>{self.title}</b>\n\n{self.content}"

        if self.details:
            html += "\n\n<i>Details:</i>\n"
            for key, value in self.details.items():
                html += f"• {key}: <code>{value}</code>\n"

        html += f"\n<i>{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"

        return html


class TelegramNotifier:
    """
    Telegram 通知服务

    使用 python-telegram-bot 库发送通知
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        rate_limit: float = 1.0,  # 最小发送间隔 (秒)
    ):
        """
        初始化 Telegram 通知器

        Args:
            bot_token: Bot Token，默认从配置读取
            chat_id: Chat ID，默认从配置读取
            rate_limit: 限频间隔
        """
        settings = get_settings()

        self._bot_token = bot_token or settings.telegram.bot_token.get_secret_value()
        self._chat_id = chat_id or settings.telegram.chat_id
        self._rate_limit = rate_limit

        self._last_send_time: float = 0
        self._enabled = bool(self._bot_token and self._chat_id)

        # Bot 实例 (延迟初始化)
        self._bot: Any = None

    @property
    def enabled(self) -> bool:
        """是否已启用"""
        return self._enabled

    def _init_bot(self) -> bool:
        """初始化 Bot"""
        if self._bot is not None:
            return True

        if not self._enabled:
            logger.warning("telegram_not_configured")
            return False

        try:
            from telegram import Bot

            self._bot = Bot(token=self._bot_token)
            return True

        except ImportError:
            logger.error("telegram_library_not_installed")
            return False
        except Exception as e:
            logger.error("telegram_init_failed", error=str(e))
            return False

    async def send_async(self, message: NotifyMessage) -> bool:
        """
        异步发送消息

        Args:
            message: 通知消息

        Returns:
            bool: 是否发送成功
        """
        if not self._init_bot():
            return False

        try:
            # 限频
            import time

            now = time.time()
            elapsed = now - self._last_send_time
            if elapsed < self._rate_limit:
                await asyncio.sleep(self._rate_limit - elapsed)

            # 发送
            text = message.to_html()
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="HTML",
            )

            self._last_send_time = time.time()

            logger.debug(
                "telegram_sent",
                notify_type=message.notify_type.value,
                level=message.level.value,
            )

            return True

        except Exception as e:
            logger.error("telegram_send_failed", error=str(e))
            return False

    def send(self, message: NotifyMessage) -> bool:
        """
        同步发送消息 (内部使用 asyncio)

        Args:
            message: 通知消息

        Returns:
            bool: 是否发送成功
        """
        try:
            # 尝试获取当前事件循环
            try:
                asyncio.get_running_loop()
                # 如果在事件循环中，创建任务
                asyncio.ensure_future(self.send_async(message))
                return True  # 异步发送，不等待结果

            except RuntimeError:
                # 没有事件循环，创建新的
                return asyncio.run(self.send_async(message))

        except Exception as e:
            logger.error("telegram_send_error", error=str(e))
            return False


class WebhookNotifier:
    """
    Webhook 通知服务

    支持:
    - Bark (iOS 推送)
    - 通用 Webhook (POST JSON)

    配置格式:
    - Bark: https://api.day.app/{device_key}
    - 通用: https://your-domain.com/webhook
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        rate_limit: float = 1.0,
        timeout: float = 10.0,
    ):
        """
        初始化 Webhook 通知器

        Args:
            webhook_url: Webhook URL，默认从配置读取
            rate_limit: 限频间隔 (秒)
            timeout: 请求超时 (秒)
        """
        settings = get_settings()

        self._webhook_url = webhook_url or getattr(
            getattr(settings, "webhook", None), "url", ""
        )
        self._rate_limit = rate_limit
        self._timeout = timeout

        self._last_send_time: float = 0
        self._enabled = bool(self._webhook_url)

        # 检测是否是 Bark URL
        self._is_bark = (
            "api.day.app" in self._webhook_url if self._webhook_url else False
        )

    @property
    def enabled(self) -> bool:
        """是否已启用"""
        return self._enabled

    def _build_bark_url(self, message: "NotifyMessage") -> str:
        """构建 Bark 推送 URL"""
        # Bark URL 格式: https://api.day.app/{key}/{title}/{body}
        # 或者使用 POST 请求
        base_url = self._webhook_url.rstrip("/")

        # 获取 emoji 和标题
        emoji_map = {
            NotifyLevel.INFO: "ℹ️",
            NotifyLevel.WARNING: "⚠️",
            NotifyLevel.ERROR: "❌",
            NotifyLevel.CRITICAL: "🚨",
        }
        emoji = emoji_map.get(message.level, "📢")
        title = f"{emoji} {message.title}"

        return base_url, title

    def _build_payload(self, message: "NotifyMessage") -> dict[str, Any]:
        """构建通用 Webhook 请求体"""
        return {
            "type": message.notify_type.value,
            "level": message.level.value,
            "title": message.title,
            "content": message.content,
            "details": message.details,
            "timestamp": message.timestamp.isoformat(),
        }

    async def send_async(self, message: "NotifyMessage") -> bool:
        """
        异步发送消息

        Args:
            message: 通知消息

        Returns:
            bool: 是否发送成功
        """
        if not self._enabled:
            return False

        try:
            import time

            # 限频
            now = time.time()
            elapsed = now - self._last_send_time
            if elapsed < self._rate_limit:
                await asyncio.sleep(self._rate_limit - elapsed)

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout)
            ) as session:
                if self._is_bark:
                    # Bark 推送
                    base_url, title = self._build_bark_url(message)
                    payload = {
                        "title": title,
                        "body": message.content,
                        "group": message.notify_type.value,
                        "level": "timeSensitive"
                        if message.level in (NotifyLevel.ERROR, NotifyLevel.CRITICAL)
                        else "active",
                    }
                    async with session.post(base_url, json=payload) as resp:
                        success = resp.status in (200, 201, 204)
                else:
                    # 通用 Webhook
                    payload = self._build_payload(message)
                    async with session.post(self._webhook_url, json=payload) as resp:
                        success = resp.status in (200, 201, 204)

            self._last_send_time = time.time()

            if success:
                logger.debug(
                    "webhook_sent",
                    notify_type=message.notify_type.value,
                    level=message.level.value,
                    is_bark=self._is_bark,
                )
            else:
                logger.warning(
                    "webhook_failed",
                    status=resp.status,
                    notify_type=message.notify_type.value,
                )

            return success

        except TimeoutError:
            logger.warning("webhook_timeout", url=self._webhook_url)
            return False
        except Exception as e:
            logger.error("webhook_send_failed", error=str(e))
            return False

    def send(self, message: "NotifyMessage") -> bool:
        """
        同步发送消息 (内部使用 asyncio)

        Args:
            message: 通知消息

        Returns:
            bool: 是否发送成功
        """
        try:
            try:
                asyncio.get_running_loop()
                asyncio.ensure_future(self.send_async(message))
                return True
            except RuntimeError:
                return asyncio.run(self.send_async(message))
        except Exception as e:
            logger.error("webhook_send_error", error=str(e))
            return False


class Notifier:
    """
    统一通知管理器

    管理多个通知渠道，提供便捷的消息发送方法
    """

    def __init__(self):
        self._telegram: TelegramNotifier | None = None
        self._webhook: WebhookNotifier | None = None
        self._enabled = True
        self._min_level = NotifyLevel.INFO

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled

    def enable(self) -> None:
        """启用通知"""
        self._enabled = True

    def disable(self) -> None:
        """禁用通知"""
        self._enabled = False

    def set_min_level(self, level: NotifyLevel) -> None:
        """设置最低通知级别"""
        self._min_level = level

    def setup_telegram(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> bool:
        """
        配置 Telegram

        Args:
            bot_token: Bot Token
            chat_id: Chat ID

        Returns:
            bool: 是否配置成功
        """
        self._telegram = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
        return self._telegram.enabled

    def setup_webhook(
        self,
        webhook_url: str | None = None,
    ) -> bool:
        """
        配置 Webhook

        Args:
            webhook_url: Webhook URL (支持 Bark 或通用 Webhook)

        Returns:
            bool: 是否配置成功
        """
        self._webhook = WebhookNotifier(webhook_url=webhook_url)
        return self._webhook.enabled

    def notify(self, message: NotifyMessage) -> bool:
        """
        发送通知

        Args:
            message: 通知消息

        Returns:
            bool: 是否发送成功
        """
        if not self._enabled:
            return False

        # 检查级别
        level_order = [
            NotifyLevel.INFO,
            NotifyLevel.WARNING,
            NotifyLevel.ERROR,
            NotifyLevel.CRITICAL,
        ]
        if level_order.index(message.level) < level_order.index(self._min_level):
            return False

        # 发送到 Telegram
        if self._telegram and self._telegram.enabled:
            return self._telegram.send(message)

        # 发送到 Webhook
        if self._webhook and self._webhook.enabled:
            return self._webhook.send(message)

        # 没有配置任何通知渠道，只记录日志
        logger.info(
            "notification",
            notify_type=message.notify_type.value,
            level=message.level.value,
            title=message.title,
        )

        return True

    # ==================== 便捷方法 ====================

    def notify_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal | None = None,
        order_type: str = "market",
        strategy: str = "",
    ) -> bool:
        """发送下单通知"""
        price_str = f"@ {price}" if price else "@ market"
        message = NotifyMessage(
            notify_type=NotifyType.ORDER,
            level=NotifyLevel.INFO,
            title=f"📤 Order: {side.upper()} {symbol}",
            content=f"{side.upper()} {quantity} {symbol} {price_str}",
            details={
                "symbol": symbol,
                "side": side,
                "quantity": str(quantity),
                "price": str(price) if price else "market",
                "order_type": order_type,
                "strategy": strategy,
            },
        )
        return self.notify(message)

    def notify_fill(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        commission: Decimal = Decimal("0"),
        strategy: str = "",
    ) -> bool:
        """发送成交通知"""
        value = quantity * price
        message = NotifyMessage(
            notify_type=NotifyType.FILL,
            level=NotifyLevel.INFO,
            title=f"✅ Filled: {side.upper()} {symbol}",
            content=f"{side.upper()} {quantity} {symbol} @ {price}\nValue: {value}",
            details={
                "symbol": symbol,
                "side": side,
                "quantity": str(quantity),
                "price": str(price),
                "value": str(value),
                "commission": str(commission),
                "strategy": strategy,
            },
        )
        return self.notify(message)

    def notify_signal(
        self,
        symbol: str,
        direction: str,
        strength: float,
        strategy: str,
        reason: str = "",
    ) -> bool:
        """发送信号通知"""
        emoji = "🟢" if direction == "long" else "🔴" if direction == "short" else "⚪"
        message = NotifyMessage(
            notify_type=NotifyType.SIGNAL,
            level=NotifyLevel.INFO,
            title=f"{emoji} Signal: {direction.upper()} {symbol}",
            content=f"Strategy: {strategy}\nStrength: {strength:.2%}\n{reason}",
            details={
                "symbol": symbol,
                "direction": direction,
                "strength": strength,
                "strategy": strategy,
            },
        )
        return self.notify(message)

    def notify_risk(
        self,
        rule_name: str,
        action: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """发送风控告警"""
        level = NotifyLevel.ERROR if action == "reject" else NotifyLevel.WARNING
        message = NotifyMessage(
            notify_type=NotifyType.RISK,
            level=level,
            title=f"🛡️ Risk Alert: {rule_name}",
            content=f"Action: {action.upper()}\nReason: {reason}",
            details=details or {},
        )
        return self.notify(message)

    def notify_error(
        self,
        title: str,
        error: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """发送错误通知"""
        message = NotifyMessage(
            notify_type=NotifyType.SYSTEM,
            level=NotifyLevel.ERROR,
            title=f"❌ Error: {title}",
            content=error,
            details=details or {},
        )
        return self.notify(message)

    def notify_daily_summary(
        self,
        date: str,
        total_pnl: Decimal,
        total_trades: int,
        win_rate: float,
        max_drawdown: float,
        positions: dict[str, Decimal] | None = None,
    ) -> bool:
        """发送日终摘要"""
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        message = NotifyMessage(
            notify_type=NotifyType.DAILY,
            level=NotifyLevel.INFO,
            title=f"📊 Daily Summary: {date}",
            content=(
                f"{pnl_emoji} PnL: {total_pnl:+.2f} USDT\n"
                f"📊 Trades: {total_trades}\n"
                f"🎯 Win Rate: {win_rate:.1%}\n"
                f"📉 Max DD: {max_drawdown:.2%}"
            ),
            details={
                "date": date,
                "pnl": str(total_pnl),
                "trades": total_trades,
                "win_rate": f"{win_rate:.1%}",
                "max_drawdown": f"{max_drawdown:.2%}",
                **({"positions": str(positions)} if positions else {}),
            },
        )
        return self.notify(message)

    def notify_system(
        self,
        title: str,
        content: str,
        level: NotifyLevel = NotifyLevel.INFO,
    ) -> bool:
        """发送系统通知"""
        message = NotifyMessage(
            notify_type=NotifyType.SYSTEM,
            level=level,
            title=title,
            content=content,
        )
        return self.notify(message)


# 全局单例
_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    """获取全局 Notifier 实例"""
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
        _notifier.setup_telegram()
        _notifier.setup_webhook()
    return _notifier


async def send_notification(
    title: str,
    message: str,
    level: str = "info",
) -> bool:
    """
    发送通知的便捷函数

    Args:
        title: 通知标题
        message: 通知内容
        level: 级别 (info, warning, error, critical)

    Returns:
        bool: 是否发送成功
    """
    import os

    # 直接使用 WebhookNotifier 发送
    webhook_url = os.getenv("WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("send_notification_no_webhook", title=title)
        return False

    level_map = {
        "info": NotifyLevel.INFO,
        "warning": NotifyLevel.WARNING,
        "error": NotifyLevel.ERROR,
        "critical": NotifyLevel.CRITICAL,
    }

    notify_message = NotifyMessage(
        notify_type=NotifyType.SYSTEM,
        level=level_map.get(level, NotifyLevel.INFO),
        title=title,
        content=message,
    )

    notifier = WebhookNotifier(webhook_url=webhook_url)
    return await notifier.send_async(notify_message)


# 导出
__all__ = [
    "NotifyLevel",
    "NotifyType",
    "NotifyMessage",
    "TelegramNotifier",
    "WebhookNotifier",
    "Notifier",
    "get_notifier",
    "send_notification",
]
