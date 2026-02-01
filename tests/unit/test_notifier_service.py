"""
Notifier 服务测试
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from services.notifier.main import (
    NotifierConfig,
    NotifierService,
    NotifierState,
    create_test_message,
)
from src.ops.notify import NotifyLevel, NotifyMessage, NotifyType


class TestNotifierConfig:
    """NotifierConfig 测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = NotifierConfig()

        assert config.rate_limit_per_second == 1.0
        assert config.max_retries == 3
        assert config.retry_delay == 5.0
        assert config.aggregate_window == 60.0
        assert config.telegram_enabled is True
        assert config.health_check_interval == 60

    def test_custom_config(self):
        """测试自定义配置"""
        config = NotifierConfig(
            rate_limit_per_second=2.0,
            max_retries=5,
            telegram_enabled=False,
        )

        assert config.rate_limit_per_second == 2.0
        assert config.max_retries == 5
        assert config.telegram_enabled is False


class TestNotifierState:
    """NotifierState 测试"""

    def test_default_state(self):
        """测试默认状态"""
        state = NotifierState()

        assert state.running is False
        assert state.started_at is None
        assert state.messages_received == 0
        assert state.messages_sent == 0
        assert state.messages_failed == 0
        assert state.last_message_time is None


class TestNotifierService:
    """NotifierService 测试"""

    def test_init(self):
        """测试初始化"""
        service = NotifierService()

        assert service.config is not None
        assert service.state is not None
        assert service._notifier is not None
        assert service._message_queue is not None

    def test_init_with_config(self):
        """测试带配置初始化"""
        config = NotifierConfig(
            max_retries=5,
            telegram_enabled=False,
        )
        service = NotifierService(config)

        assert service.config.max_retries == 5
        assert service.config.telegram_enabled is False

    def test_queue_message(self):
        """测试消息入队"""
        service = NotifierService()
        message = create_test_message()

        service.queue_message(message)

        assert service.state.messages_received == 1
        assert service._message_queue.qsize() == 1

    def test_queue_multiple_messages(self):
        """测试多消息入队"""
        service = NotifierService()

        for i in range(5):
            service.queue_message(create_test_message())

        assert service.state.messages_received == 5
        assert service._message_queue.qsize() == 5

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """测试消息发送成功"""
        service = NotifierService()
        service._notifier = MagicMock()
        service._notifier.notify.return_value = True

        message = create_test_message()
        result = await service._send_message(message)

        assert result is True
        assert service.state.messages_sent == 1
        assert service.state.last_message_time is not None

    @pytest.mark.asyncio
    async def test_send_message_failure(self):
        """测试消息发送失败"""
        config = NotifierConfig(max_retries=2, retry_delay=0.01)
        service = NotifierService(config)
        service._notifier = MagicMock()
        service._notifier.notify.return_value = False

        message = create_test_message()
        result = await service._send_message(message)

        assert result is False
        assert service.state.messages_failed == 1

    @pytest.mark.asyncio
    async def test_send_message_retry(self):
        """测试消息发送重试"""
        config = NotifierConfig(max_retries=3, retry_delay=0.01)
        service = NotifierService(config)
        service._notifier = MagicMock()
        # 前两次失败，第三次成功
        service._notifier.notify.side_effect = [False, False, True]

        message = create_test_message()
        result = await service._send_message(message)

        assert result is True
        assert service._notifier.notify.call_count == 3

    def test_stop(self):
        """测试停止服务"""
        service = NotifierService()
        service.state.running = True
        service._notifier = MagicMock()

        service.stop()

        assert service.state.running is False
        assert service._stop_event.is_set()


class TestCreateTestMessage:
    """create_test_message 测试"""

    def test_creates_valid_message(self):
        """测试创建有效消息"""
        message = create_test_message()

        assert isinstance(message, NotifyMessage)
        assert message.notify_type == NotifyType.SYSTEM
        assert message.level == NotifyLevel.INFO
        assert "Test" in message.title
        assert message.details.get("test") is True
