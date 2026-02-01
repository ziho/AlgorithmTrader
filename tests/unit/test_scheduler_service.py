"""
Scheduler 服务测试
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from services.scheduler.main import (
    SchedulerConfig,
    SchedulerService,
    SchedulerState,
)
from src.ops.scheduler import TaskResult, TaskType


class TestSchedulerConfig:
    """SchedulerConfig 测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = SchedulerConfig()

        assert config.max_workers == 4
        assert config.bar_close_delay == 10
        assert config.health_check_interval == 60
        assert config.cleanup_interval_hours == 24
        assert config.enable_health_check is True
        assert config.enable_cleanup is True

    def test_custom_config(self):
        """测试自定义配置"""
        config = SchedulerConfig(
            max_workers=8,
            bar_close_delay=15,
            enable_cleanup=False,
        )

        assert config.max_workers == 8
        assert config.bar_close_delay == 15
        assert config.enable_cleanup is False


class TestSchedulerState:
    """SchedulerState 测试"""

    def test_default_state(self):
        """测试默认状态"""
        state = SchedulerState()

        assert state.running is False
        assert state.started_at is None
        assert state.tasks_scheduled == 0
        assert state.tasks_executed == 0
        assert state.tasks_succeeded == 0
        assert state.tasks_failed == 0


class TestSchedulerService:
    """SchedulerService 测试"""

    def test_init(self):
        """测试初始化"""
        service = SchedulerService()

        assert service.config is not None
        assert service.state is not None
        assert service._scheduler is not None
        assert service._notifier is not None

    def test_init_with_config(self):
        """测试带配置初始化"""
        config = SchedulerConfig(
            max_workers=8,
            enable_cleanup=False,
        )
        service = SchedulerService(config)

        assert service.config.max_workers == 8
        assert service.config.enable_cleanup is False

    def test_on_task_complete_success(self):
        """测试任务成功完成回调"""
        service = SchedulerService()
        result = TaskResult(
            task_id="test",
            success=True,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
        )

        service._on_task_complete(result)

        assert service.state.tasks_executed == 1
        assert service.state.tasks_succeeded == 1
        assert service.state.tasks_failed == 0

    def test_on_task_complete_failure(self):
        """测试任务失败回调"""
        service = SchedulerService()
        service._notifier = MagicMock()
        result = TaskResult(
            task_id="test",
            success=False,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            error="Something went wrong",
        )

        service._on_task_complete(result)

        assert service.state.tasks_executed == 1
        assert service.state.tasks_succeeded == 0
        assert service.state.tasks_failed == 1
        service._notifier.notify_error.assert_called_once()

    def test_on_task_error(self):
        """测试任务错误回调"""
        service = SchedulerService()
        service._notifier = MagicMock()

        service._on_task_error("test", Exception("Error"))

        assert service.state.tasks_failed == 1
        service._notifier.notify_error.assert_called_once()

    @patch("services.scheduler.main.check_influxdb_health")
    def test_health_check_task(self, mock_check):
        """测试健康检查任务"""
        mock_check.return_value = True
        service = SchedulerService()
        service._scheduler = MagicMock()
        service._scheduler.is_running = True

        result = service._health_check_task()

        assert result["influxdb"] == "healthy"
        assert result["scheduler"] == "healthy"

    @patch("services.scheduler.main.check_influxdb_health")
    def test_health_check_task_unhealthy(self, mock_check):
        """测试健康检查任务 - 不健康"""
        mock_check.return_value = False
        service = SchedulerService()
        service._scheduler = MagicMock()
        service._scheduler.is_running = False

        result = service._health_check_task()

        assert result["influxdb"] == "unhealthy"
        assert result["scheduler"] == "unhealthy"

    def test_cleanup_task(self):
        """测试清理任务"""
        service = SchedulerService()

        result = service._cleanup_task()

        assert isinstance(result, dict)

    def test_setup_tasks_with_health_check(self):
        """测试设置任务 - 包含健康检查"""
        config = SchedulerConfig(enable_health_check=True, enable_cleanup=False)
        service = SchedulerService(config)
        service._scheduler = MagicMock()
        service._scheduler.add_health_check_task.return_value = True

        service._setup_tasks()

        assert service.state.tasks_scheduled == 1
        service._scheduler.add_health_check_task.assert_called_once()

    def test_setup_tasks_with_cleanup(self):
        """测试设置任务 - 包含清理任务"""
        config = SchedulerConfig(enable_health_check=False, enable_cleanup=True)
        service = SchedulerService(config)
        service._scheduler = MagicMock()
        service._scheduler.add_task.return_value = True

        service._setup_tasks()

        assert service.state.tasks_scheduled == 1
        service._scheduler.add_task.assert_called_once()

    def test_setup_tasks_all(self):
        """测试设置所有任务"""
        config = SchedulerConfig(enable_health_check=True, enable_cleanup=True)
        service = SchedulerService(config)
        service._scheduler = MagicMock()
        service._scheduler.add_health_check_task.return_value = True
        service._scheduler.add_task.return_value = True

        service._setup_tasks()

        assert service.state.tasks_scheduled == 2

    def test_add_custom_task(self):
        """测试添加自定义任务"""
        service = SchedulerService()
        service._scheduler = MagicMock()
        service._scheduler.add_task.return_value = True

        result = service.add_custom_task(
            task_id="custom",
            func=lambda: None,
            interval_seconds=60,
        )

        assert result is True
        assert service.state.tasks_scheduled == 1

    def test_start(self):
        """测试启动服务"""
        service = SchedulerService()
        service._scheduler = MagicMock()
        service._scheduler.add_health_check_task.return_value = True
        service._scheduler.add_task.return_value = True
        service._notifier = MagicMock()

        service.start()

        assert service.state.running is True
        assert service.state.started_at is not None
        service._scheduler.start.assert_called_once()
        service._notifier.notify_system.assert_called_once()

    def test_stop(self):
        """测试停止服务"""
        service = SchedulerService()
        service._scheduler = MagicMock()
        service._notifier = MagicMock()
        service.state.running = True

        service.stop()

        assert service.state.running is False
        service._scheduler.stop.assert_called_once_with(wait=True)
        service._notifier.notify_system.assert_called_once()

    def test_get_status(self):
        """测试获取状态"""
        service = SchedulerService()
        service.state.running = True
        service.state.started_at = datetime.now(UTC)
        service.state.tasks_scheduled = 5
        service.state.tasks_executed = 10
        service.state.tasks_succeeded = 8
        service.state.tasks_failed = 2

        status = service.get_status()

        assert status["running"] is True
        assert status["tasks_scheduled"] == 5
        assert status["tasks_executed"] == 10
        assert status["tasks_succeeded"] == 8
        assert status["tasks_failed"] == 2
        assert "uptime_seconds" in status
        assert "started_at" in status

    def test_get_status_not_running(self):
        """测试获取状态 - 未运行"""
        service = SchedulerService()

        status = service.get_status()

        assert status["running"] is False
        assert status["started_at"] is None
        assert status["uptime_seconds"] == 0
