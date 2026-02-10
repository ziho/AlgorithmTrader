"""
统一调度器

职责:
- 管理定时任务
- 任务: 数据采集/策略运行/健康检查
- Bar close 触发延迟处理
- 协调多策略并发

使用 APScheduler 实现轻量级调度
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.core.config import get_settings

logger = structlog.get_logger(__name__)


class TaskType(StrEnum):
    """任务类型"""

    DATA_COLLECT = "data_collect"  # 数据采集
    STRATEGY_RUN = "strategy_run"  # 策略运行
    HEALTH_CHECK = "health_check"  # 健康检查
    CLEANUP = "cleanup"  # 清理任务
    CUSTOM = "custom"  # 自定义任务


@dataclass
class ScheduledTask:
    """
    调度任务
    """

    task_id: str
    task_type: TaskType
    func: Callable[..., Any]
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)

    # 调度配置
    cron: str | None = None  # cron 表达式
    interval_seconds: int | None = None  # 间隔秒数
    run_immediately: bool = False  # 是否立即执行一次

    # 状态
    enabled: bool = True
    last_run: datetime | None = None
    last_success: bool = True
    run_count: int = 0
    error_count: int = 0

    # 元信息
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class TaskResult:
    """任务执行结果"""

    task_id: str
    success: bool
    start_time: datetime
    end_time: datetime
    result: Any = None
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        """执行时间 (毫秒)"""
        return (self.end_time - self.start_time).total_seconds() * 1000


class TradingScheduler:
    """
    交易调度器

    管理所有定时任务:
    - 数据采集任务
    - 策略运行任务
    - 健康检查任务
    """

    def __init__(
        self,
        max_workers: int = 4,
        bar_close_delay: int | None = None,
    ):
        """
        初始化调度器

        Args:
            max_workers: 最大并发工作线程
            bar_close_delay: Bar close 延迟秒数 (避免交易所数据未落地)
        """
        settings = get_settings()
        self._bar_close_delay = bar_close_delay or settings.bar_close_delay

        # APScheduler 配置
        executors = {"default": ThreadPoolExecutor(max_workers)}
        job_defaults = {
            "coalesce": True,  # 合并错过的执行
            "max_instances": 1,  # 每个任务最多一个实例
            "misfire_grace_time": 60,  # 错过执行的容忍时间
        }

        self._scheduler = BackgroundScheduler(
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

        # 任务注册表
        self._tasks: dict[str, ScheduledTask] = {}

        # 回调
        self._on_task_complete: Callable[[TaskResult], None] | None = None
        self._on_task_error: Callable[[str, Exception], None] | None = None

        self._running = False

    @property
    def is_running(self) -> bool:
        """调度器是否运行中"""
        return self._running

    def set_on_task_complete(self, callback: Callable[[TaskResult], None]) -> None:
        """设置任务完成回调"""
        self._on_task_complete = callback

    def set_on_task_error(self, callback: Callable[[str, Exception], None]) -> None:
        """设置任务错误回调"""
        self._on_task_error = callback

    def _task_wrapper(self, task: ScheduledTask) -> Any:
        """任务包装器，添加日志和错误处理"""
        start_time = datetime.now(UTC)

        try:
            logger.debug(
                "task_started",
                task_id=task.task_id,
                task_type=task.task_type.value,
            )

            result = task.func(*task.args, **task.kwargs)

            end_time = datetime.now(UTC)
            task.last_run = end_time
            task.last_success = True
            task.run_count += 1

            task_result = TaskResult(
                task_id=task.task_id,
                success=True,
                start_time=start_time,
                end_time=end_time,
                result=result,
            )

            logger.info(
                "task_completed",
                task_id=task.task_id,
                duration_ms=task_result.duration_ms,
            )

            if self._on_task_complete:
                self._on_task_complete(task_result)

            return result

        except Exception as e:
            end_time = datetime.now(UTC)
            task.last_run = end_time
            task.last_success = False
            task.run_count += 1
            task.error_count += 1

            logger.error(
                "task_failed",
                task_id=task.task_id,
                error=str(e),
                exc_info=True,
            )

            if self._on_task_error:
                self._on_task_error(task.task_id, e)

            raise

    def add_task(self, task: ScheduledTask) -> bool:
        """
        添加调度任务

        Args:
            task: 任务配置

        Returns:
            bool: 是否添加成功
        """
        if task.task_id in self._tasks:
            logger.warning("task_already_exists", task_id=task.task_id)
            return False

        # 创建触发器
        trigger: CronTrigger | IntervalTrigger | None = None

        if task.cron:
            trigger = CronTrigger.from_crontab(task.cron, timezone="UTC")
        elif task.interval_seconds:
            trigger = IntervalTrigger(seconds=task.interval_seconds)

        if trigger is None:
            logger.error("no_trigger_specified", task_id=task.task_id)
            return False

        # 添加到 APScheduler
        self._scheduler.add_job(
            self._task_wrapper,
            trigger=trigger,
            args=[task],
            id=task.task_id,
            name=task.description or task.task_id,
        )

        self._tasks[task.task_id] = task

        logger.info(
            "task_added",
            task_id=task.task_id,
            task_type=task.task_type.value,
            cron=task.cron,
            interval=task.interval_seconds,
        )

        # 立即执行一次
        if task.run_immediately and self._running:
            self._scheduler.get_job(task.task_id).modify(
                next_run_time=datetime.now(UTC)
            )

        return True

    def remove_task(self, task_id: str) -> bool:
        """移除任务"""
        if task_id not in self._tasks:
            return False

        self._scheduler.remove_job(task_id)
        del self._tasks[task_id]

        logger.info("task_removed", task_id=task_id)
        return True

    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        if task_id not in self._tasks:
            return False

        self._scheduler.pause_job(task_id)
        self._tasks[task_id].enabled = False

        logger.info("task_paused", task_id=task_id)
        return True

    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        if task_id not in self._tasks:
            return False

        self._scheduler.resume_job(task_id)
        self._tasks[task_id].enabled = True

        logger.info("task_resumed", task_id=task_id)
        return True

    def get_task(self, task_id: str) -> ScheduledTask | None:
        """获取任务"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[ScheduledTask]:
        """获取所有任务"""
        return list(self._tasks.values())

    def get_job(self, task_id: str) -> Job | None:
        """获取 APScheduler Job"""
        return self._scheduler.get_job(task_id)

    # ==================== 便捷方法 ====================

    def add_bar_close_task(
        self,
        task_id: str,
        func: Callable[..., Any],
        timeframe: str = "15m",
        symbols: list[str] | None = None,
        description: str = "",
    ) -> bool:
        """
        添加 Bar close 触发任务

        根据 timeframe 自动计算 cron 表达式，并添加延迟

        Args:
            task_id: 任务ID
            func: 任务函数
            timeframe: 时间框架 (15m, 1h, 4h, 1d)
            symbols: 交易对列表
            description: 任务描述

        Returns:
            bool: 是否添加成功
        """
        # 验证 timeframe 支持的值
        valid_timeframes = {"15m", "1h", "4h", "1d"}
        if timeframe not in valid_timeframes:
            logger.error("unsupported_timeframe", timeframe=timeframe)
            return False

        # 使用 cron 触发器时，APScheduler 需要标准 cron 格式
        # 转换为 interval 方式更简单
        interval_map = {
            "15m": 15 * 60,
            "1h": 60 * 60,
            "4h": 4 * 60 * 60,
            "1d": 24 * 60 * 60,
        }

        task = ScheduledTask(
            task_id=task_id,
            task_type=TaskType.STRATEGY_RUN,
            func=func,
            kwargs={"symbols": symbols} if symbols else {},
            interval_seconds=interval_map.get(timeframe, 15 * 60),
            description=description or f"Bar close task ({timeframe})",
        )

        return self.add_task(task)

    def add_health_check_task(
        self,
        func: Callable[..., Any],
        interval_seconds: int = 60,
    ) -> bool:
        """添加健康检查任务"""
        task = ScheduledTask(
            task_id="health_check",
            task_type=TaskType.HEALTH_CHECK,
            func=func,
            interval_seconds=interval_seconds,
            description="Health check",
        )
        return self.add_task(task)

    def add_data_collect_task(
        self,
        task_id: str,
        func: Callable[..., Any],
        interval_seconds: int = 60,
        description: str = "",
    ) -> bool:
        """添加数据采集任务"""
        task = ScheduledTask(
            task_id=task_id,
            task_type=TaskType.DATA_COLLECT,
            func=func,
            interval_seconds=interval_seconds,
            description=description or "Data collection",
        )
        return self.add_task(task)

    # ==================== 生命周期 ====================

    def start(self) -> None:
        """启动调度器"""
        if self._running:
            logger.warning("scheduler_already_running")
            return

        self._scheduler.start()
        self._running = True

        logger.info(
            "scheduler_started",
            tasks_count=len(self._tasks),
        )

    def stop(self, wait: bool = True) -> None:
        """
        停止调度器

        Args:
            wait: 是否等待正在执行的任务完成
        """
        if not self._running:
            return

        self._scheduler.shutdown(wait=wait)
        self._running = False

        logger.info("scheduler_stopped")

    def run_task_now(self, task_id: str) -> bool:
        """立即执行一次任务"""
        job = self._scheduler.get_job(task_id)
        if job is None:
            return False

        job.modify(next_run_time=datetime.now(UTC))
        return True

    def get_next_run_time(self, task_id: str) -> datetime | None:
        """获取任务下次执行时间"""
        job = self._scheduler.get_job(task_id)
        if job is None:
            return None
        return job.next_run_time


def calculate_next_bar_time(
    timeframe: str, current_time: datetime | None = None
) -> datetime:
    """
    计算下一个 bar close 时间

    Args:
        timeframe: 时间框架
        current_time: 当前时间，默认为 UTC 现在

    Returns:
        下一个 bar close 时间
    """
    now = current_time or datetime.now(UTC)

    if timeframe == "15m":
        # 下一个 15 分钟整点
        minute = (now.minute // 15 + 1) * 15
        if minute >= 60:
            next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(
                hours=1
            )
        else:
            next_time = now.replace(minute=minute, second=0, microsecond=0)

    elif timeframe == "1h":
        # 下一个整点
        next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    elif timeframe == "4h":
        # 下一个 4 小时整点
        hour = (now.hour // 4 + 1) * 4
        if hour >= 24:
            next_time = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
        else:
            next_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)

    elif timeframe == "1d":
        # 下一个 UTC 0 点
        next_time = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )

    else:
        # 默认 15 分钟
        return calculate_next_bar_time("15m", now)

    return next_time


# 导出
__all__ = [
    "TaskType",
    "ScheduledTask",
    "TaskResult",
    "TradingScheduler",
    "calculate_next_bar_time",
]
