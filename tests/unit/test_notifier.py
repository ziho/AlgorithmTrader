"""
通知模块测试
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ops.notify import (
    Notifier,
    NotifyLevel,
    NotifyMessage,
    NotifyType,
    WebhookNotifier,
)


class TestNotifyMessage:
    """NotifyMessage 测试"""

    def test_message_creation(self) -> None:
        """测试消息创建"""
        message = NotifyMessage(
            notify_type=NotifyType.ORDER,
            level=NotifyLevel.INFO,
            title="Test Order",
            content="Order content",
        )

        assert message.notify_type == NotifyType.ORDER
        assert message.level == NotifyLevel.INFO
        assert message.title == "Test Order"

    def test_to_text(self) -> None:
        """测试转换为文本"""
        message = NotifyMessage(
            notify_type=NotifyType.FILL,
            level=NotifyLevel.INFO,
            title="Order Filled",
            content="BTC/USDT filled",
            details={"price": "50000"},
        )

        text = message.to_text()
        assert "Order Filled" in text
        assert "BTC/USDT filled" in text
        assert "price" in text
        assert "50000" in text

    def test_to_html(self) -> None:
        """测试转换为 HTML"""
        message = NotifyMessage(
            notify_type=NotifyType.RISK,
            level=NotifyLevel.WARNING,
            title="Risk Warning",
            content="Position too large",
        )

        html = message.to_html()
        assert "<b>Risk Warning</b>" in html
        assert "Position too large" in html

    def test_emoji_mapping(self) -> None:
        """测试不同级别的 emoji"""
        messages = [
            (NotifyLevel.INFO, "ℹ️"),
            (NotifyLevel.WARNING, "⚠️"),
            (NotifyLevel.ERROR, "❌"),
            (NotifyLevel.CRITICAL, "🚨"),
        ]

        for level, emoji in messages:
            message = NotifyMessage(
                notify_type=NotifyType.SYSTEM,
                level=level,
                title="Test",
                content="Content",
            )
            assert emoji in message.to_text()


class TestNotifier:
    """Notifier 测试"""

    def test_notifier_creation(self) -> None:
        """测试通知器创建"""
        notifier = Notifier()
        assert notifier.enabled is True

    def test_enable_disable(self) -> None:
        """测试启用禁用"""
        notifier = Notifier()

        notifier.disable()
        assert notifier.enabled is False

        notifier.enable()
        assert notifier.enabled is True

    def test_set_min_level(self) -> None:
        """测试设置最低通知级别"""
        notifier = Notifier()
        notifier.set_min_level(NotifyLevel.WARNING)

        # INFO 级别应该被忽略
        message = NotifyMessage(
            notify_type=NotifyType.SYSTEM,
            level=NotifyLevel.INFO,
            title="Info",
            content="Info content",
        )
        result = notifier.notify(message)
        assert result is False  # 低于最低级别

        # WARNING 级别应该通过
        message = NotifyMessage(
            notify_type=NotifyType.SYSTEM,
            level=NotifyLevel.WARNING,
            title="Warning",
            content="Warning content",
        )
        result = notifier.notify(message)
        assert result is True  # 达到最低级别

    def test_notify_disabled(self) -> None:
        """测试禁用时通知返回 False"""
        notifier = Notifier()
        notifier.disable()

        message = NotifyMessage(
            notify_type=NotifyType.SYSTEM,
            level=NotifyLevel.ERROR,
            title="Error",
            content="Error content",
        )
        result = notifier.notify(message)
        assert result is False

    def test_notify_order(self) -> None:
        """测试下单通知"""
        notifier = Notifier()
        result = notifier.notify_order(
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("50000"),
            strategy="test_strategy",
        )
        assert result is True

    def test_notify_fill(self) -> None:
        """测试成交通知"""
        notifier = Notifier()
        result = notifier.notify_fill(
            symbol="ETH/USDT",
            side="sell",
            quantity=Decimal("1"),
            price=Decimal("3000"),
            commission=Decimal("3"),
        )
        assert result is True

    def test_notify_signal(self) -> None:
        """测试信号通知"""
        notifier = Notifier()
        result = notifier.notify_signal(
            symbol="BTC/USDT",
            direction="long",
            strength=0.8,
            strategy="momentum",
            reason="RSI oversold",
        )
        assert result is True

    def test_notify_risk(self) -> None:
        """测试风控告警"""
        notifier = Notifier()
        result = notifier.notify_risk(
            rule_name="max_daily_loss",
            action="reject",
            reason="Daily loss exceeded 5%",
            details={"loss_pct": 0.06},
        )
        assert result is True

    def test_notify_error(self) -> None:
        """测试错误通知"""
        notifier = Notifier()
        result = notifier.notify_error(
            title="Connection Error",
            error="Failed to connect to exchange",
            details={"exchange": "OKX"},
        )
        assert result is True

    def test_notify_daily_summary(self) -> None:
        """测试日终摘要"""
        notifier = Notifier()
        result = notifier.notify_daily_summary(
            date="2024-01-15",
            total_pnl=Decimal("150.50"),
            total_trades=12,
            win_rate=0.75,
            max_drawdown=0.03,
            positions={"BTC": Decimal("0.5")},
        )
        assert result is True

    def test_notify_system(self) -> None:
        """测试系统通知"""
        notifier = Notifier()
        result = notifier.notify_system(
            title="Trader Started",
            content="Trading system initialized",
            level=NotifyLevel.INFO,
        )
        assert result is True

    def test_setup_webhook(self) -> None:
        """测试配置 Webhook"""
        notifier = Notifier()

        # 配置有效的 URL
        result = notifier.setup_webhook(webhook_url="https://example.com/webhook")
        assert result is True
        assert notifier._webhook is not None
        assert notifier._webhook.enabled is True

    def test_setup_webhook_empty(self) -> None:
        """测试配置空 Webhook"""
        notifier = Notifier()
        result = notifier.setup_webhook(webhook_url="")
        assert result is False


class TestWebhookNotifier:
    """WebhookNotifier 测试"""

    def test_webhook_notifier_creation(self) -> None:
        """测试 Webhook 通知器创建"""
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")
        assert notifier.enabled is True

    def test_webhook_notifier_disabled(self) -> None:
        """测试 Webhook 通知器禁用状态"""
        notifier = WebhookNotifier(webhook_url="")
        assert notifier.enabled is False

    def test_bark_detection(self) -> None:
        """测试 Bark URL 检测"""
        # Bark URL
        bark_notifier = WebhookNotifier(webhook_url="https://api.day.app/abcdefgh")
        assert bark_notifier._is_bark is True

        # 普通 Webhook URL
        normal_notifier = WebhookNotifier(webhook_url="https://example.com/webhook")
        assert normal_notifier._is_bark is False

    def test_build_payload(self) -> None:
        """测试构建通用 Webhook 请求体"""
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")
        message = NotifyMessage(
            notify_type=NotifyType.ORDER,
            level=NotifyLevel.INFO,
            title="Test Order",
            content="Test content",
            details={"symbol": "BTC/USDT"},
        )

        payload = notifier._build_payload(message)
        assert payload["type"] == "order"
        assert payload["level"] == "info"
        assert payload["title"] == "Test Order"
        assert payload["content"] == "Test content"
        assert payload["details"]["symbol"] == "BTC/USDT"

    def test_send_disabled(self) -> None:
        """测试禁用状态下发送"""
        notifier = WebhookNotifier(webhook_url="")
        message = NotifyMessage(
            notify_type=NotifyType.SYSTEM,
            level=NotifyLevel.INFO,
            title="Test",
            content="Content",
        )
        result = notifier.send(message)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_async_success(self) -> None:
        """测试异步发送成功"""
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")
        message = NotifyMessage(
            notify_type=NotifyType.SYSTEM,
            level=NotifyLevel.INFO,
            title="Test",
            content="Content",
        )

        with patch("src.ops.notify.aiohttp.ClientSession") as mock_session_class:
            mock_response = MagicMock()
            mock_response.status = 200

            mock_post_cm = MagicMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_post_cm)

            mock_session_cm = MagicMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session_cm

            result = await notifier.send_async(message)
            assert result is True

    @pytest.mark.asyncio
    async def test_send_async_bark(self) -> None:
        """测试 Bark 推送"""
        notifier = WebhookNotifier(webhook_url="https://api.day.app/test_key")
        message = NotifyMessage(
            notify_type=NotifyType.RISK,
            level=NotifyLevel.CRITICAL,
            title="Risk Alert",
            content="Position too large",
        )

        with patch("src.ops.notify.aiohttp.ClientSession") as mock_session_class:
            mock_response = MagicMock()
            mock_response.status = 200

            mock_post_cm = MagicMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_post_cm)

            mock_session_cm = MagicMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session_cm

            result = await notifier.send_async(message)
            assert result is True
