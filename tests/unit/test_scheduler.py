"""
调度器测试
"""

from datetime import UTC, datetime

from src.ops.scheduler import (
    ScheduledTask,
    TaskResult,
    TaskType,
    TradingScheduler,
    calculate_next_bar_time,
)


class TestScheduledTask:
    """ScheduledTask 测试"""

    def test_task_creation(self) -> None:
        """测试任务创建"""
        task = ScheduledTask(
            task_id="test_task",
            task_type=TaskType.HEALTH_CHECK,
            func=lambda: None,
            interval_seconds=60,
        )

        assert task.task_id == "test_task"
        assert task.task_type == TaskType.HEALTH_CHECK
        assert task.interval_seconds == 60
        assert task.enabled is True
        assert task.run_count == 0


class TestTaskResult:
    """TaskResult 测试"""

    def test_duration_calculation(self) -> None:
        """测试执行时间计算"""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 1, 500000, tzinfo=UTC)  # 1.5秒后

        result = TaskResult(
            task_id="test",
            success=True,
            start_time=start,
            end_time=end,
        )

        assert result.duration_ms == 1500.0


class TestTradingScheduler:
    """TradingScheduler 测试"""

    def test_scheduler_creation(self) -> None:
        """测试调度器创建"""
        scheduler = TradingScheduler()
        assert scheduler.is_running is False

    def test_add_task(self) -> None:
        """测试添加任务"""
        scheduler = TradingScheduler()
        called = []

        task = ScheduledTask(
            task_id="test_task",
            task_type=TaskType.CUSTOM,
            func=lambda: called.append(1),
            interval_seconds=60,
        )

        result = scheduler.add_task(task)
        assert result is True
        assert scheduler.get_task("test_task") is not None

    def test_add_duplicate_task(self) -> None:
        """测试添加重复任务"""
        scheduler = TradingScheduler()

        task1 = ScheduledTask(
            task_id="same_id",
            task_type=TaskType.CUSTOM,
            func=lambda: None,
            interval_seconds=60,
        )
        task2 = ScheduledTask(
            task_id="same_id",
            task_type=TaskType.CUSTOM,
            func=lambda: None,
            interval_seconds=120,
        )

        assert scheduler.add_task(task1) is True
        assert scheduler.add_task(task2) is False  # 重复ID

    def test_remove_task(self) -> None:
        """测试移除任务"""
        scheduler = TradingScheduler()

        task = ScheduledTask(
            task_id="to_remove",
            task_type=TaskType.CUSTOM,
            func=lambda: None,
            interval_seconds=60,
        )
        scheduler.add_task(task)

        assert scheduler.remove_task("to_remove") is True
        assert scheduler.get_task("to_remove") is None
        assert scheduler.remove_task("nonexistent") is False

    def test_get_all_tasks(self) -> None:
        """测试获取所有任务"""
        scheduler = TradingScheduler()

        for i in range(3):
            task = ScheduledTask(
                task_id=f"task_{i}",
                task_type=TaskType.CUSTOM,
                func=lambda: None,
                interval_seconds=60,
            )
            scheduler.add_task(task)

        tasks = scheduler.get_all_tasks()
        assert len(tasks) == 3

    def test_pause_resume_task(self) -> None:
        """测试暂停和恢复任务"""
        scheduler = TradingScheduler()

        task = ScheduledTask(
            task_id="pausable",
            task_type=TaskType.CUSTOM,
            func=lambda: None,
            interval_seconds=60,
        )
        scheduler.add_task(task)

        assert scheduler.pause_task("pausable") is True
        assert scheduler.get_task("pausable").enabled is False

        assert scheduler.resume_task("pausable") is True
        assert scheduler.get_task("pausable").enabled is True


class TestCalculateNextBarTime:
    """calculate_next_bar_time 测试"""

    def test_15m_next_bar(self) -> None:
        """测试 15 分钟时间框架"""
        # 12:07 -> 12:15
        current = datetime(2024, 1, 1, 12, 7, 30, tzinfo=UTC)
        next_bar = calculate_next_bar_time("15m", current)
        assert next_bar == datetime(2024, 1, 1, 12, 15, 0, tzinfo=UTC)

        # 12:15 -> 12:30
        current = datetime(2024, 1, 1, 12, 15, 0, tzinfo=UTC)
        next_bar = calculate_next_bar_time("15m", current)
        assert next_bar == datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC)

        # 12:45 -> 13:00
        current = datetime(2024, 1, 1, 12, 45, 1, tzinfo=UTC)
        next_bar = calculate_next_bar_time("15m", current)
        assert next_bar == datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)

    def test_1h_next_bar(self) -> None:
        """测试 1 小时时间框架"""
        # 12:30 -> 13:00
        current = datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC)
        next_bar = calculate_next_bar_time("1h", current)
        assert next_bar == datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)

        # 23:59 -> 次日 00:00
        current = datetime(2024, 1, 1, 23, 59, 0, tzinfo=UTC)
        next_bar = calculate_next_bar_time("1h", current)
        assert next_bar == datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)

    def test_4h_next_bar(self) -> None:
        """测试 4 小时时间框架"""
        # 02:30 -> 04:00
        current = datetime(2024, 1, 1, 2, 30, 0, tzinfo=UTC)
        next_bar = calculate_next_bar_time("4h", current)
        assert next_bar == datetime(2024, 1, 1, 4, 0, 0, tzinfo=UTC)

        # 20:30 -> 次日 00:00
        current = datetime(2024, 1, 1, 20, 30, 0, tzinfo=UTC)
        next_bar = calculate_next_bar_time("4h", current)
        assert next_bar == datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)

    def test_1d_next_bar(self) -> None:
        """测试日线时间框架"""
        # 任何时间 -> 次日 00:00 UTC
        current = datetime(2024, 1, 1, 15, 30, 0, tzinfo=UTC)
        next_bar = calculate_next_bar_time("1d", current)
        assert next_bar == datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)

    def test_unknown_timeframe_defaults_to_15m(self) -> None:
        """测试未知时间框架默认为 15m"""
        current = datetime(2024, 1, 1, 12, 7, 0, tzinfo=UTC)
        next_bar = calculate_next_bar_time("unknown", current)
        assert next_bar == datetime(2024, 1, 1, 12, 15, 0, tzinfo=UTC)
