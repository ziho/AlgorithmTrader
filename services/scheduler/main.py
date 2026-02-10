"""
Scheduler 服务入口

运行方式:
    python -m services.scheduler.main

职责:
- 统一管理所有定时任务
- 数据采集调度
- 策略运行调度
- 健康检查调度
- 清理任务调度
"""

import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from src.core.config import get_settings
from src.ops.healthcheck import check_influxdb_health
from src.ops.heartbeat import HeartbeatWriter
from src.ops.logging import configure_logging
from src.ops.notify import get_notifier
from src.ops.scheduler import (
    ScheduledTask,
    TaskResult,
    TaskType,
    TradingScheduler,
)

logger = structlog.get_logger(__name__)


@dataclass
class SchedulerConfig:
    """Scheduler 配置"""

    # 工作线程
    max_workers: int = 4

    # Bar close 延迟
    bar_close_delay: int = 10

    # 健康检查间隔 (秒)
    health_check_interval: int = 60

    # 清理任务间隔 (小时)
    cleanup_interval_hours: int = 24

    # 启用的任务类型
    enable_health_check: bool = True
    enable_cleanup: bool = True


@dataclass
class SchedulerState:
    """Scheduler 状态"""

    running: bool = False
    started_at: datetime | None = None

    # 统计
    tasks_scheduled: int = 0
    tasks_executed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0


class SchedulerService:
    """
    调度服务

    管理所有定时任务:
    - 健康检查任务
    - 清理任务
    - 可扩展支持其他任务类型
    """

    def __init__(self, config: SchedulerConfig | None = None):
        """
        初始化调度服务

        Args:
            config: 服务配置
        """
        self.config = config or SchedulerConfig()
        self.state = SchedulerState()

        # 创建调度器
        self._scheduler = TradingScheduler(
            max_workers=self.config.max_workers,
            bar_close_delay=self.config.bar_close_delay,
        )

        # 通知器
        self._notifier = get_notifier()

        # 设置回调
        self._scheduler.set_on_task_complete(self._on_task_complete)
        self._scheduler.set_on_task_error(self._on_task_error)

    def _on_task_complete(self, result: TaskResult) -> None:
        """任务完成回调"""
        self.state.tasks_executed += 1

        if result.success:
            self.state.tasks_succeeded += 1
            logger.debug(
                "task_completed",
                task_id=result.task_id,
                duration_ms=result.duration_ms,
            )
        else:
            self.state.tasks_failed += 1
            logger.warning(
                "task_failed",
                task_id=result.task_id,
                error=result.error,
            )
            # 发送失败通知
            self._notifier.notify_error(
                title=f"Task Failed: {result.task_id}",
                error=result.error or "Unknown error",
            )

    def _on_task_error(self, task_id: str, error: Exception) -> None:
        """任务错误回调"""
        self.state.tasks_failed += 1
        logger.error(
            "task_error",
            task_id=task_id,
            error=str(error),
        )
        self._notifier.notify_error(
            title=f"Task Error: {task_id}",
            error=str(error),
        )

    def _health_check_task(self) -> dict[str, Any]:
        """
        健康检查任务

        检查各服务的健康状态
        """
        results = {}

        # 检查 InfluxDB
        try:
            influx_healthy = check_influxdb_health()
            results["influxdb"] = "healthy" if influx_healthy else "unhealthy"
        except Exception as e:
            results["influxdb"] = f"error: {e}"

        # 检查调度器
        results["scheduler"] = "healthy" if self._scheduler.is_running else "unhealthy"

        # 统计信息
        results["tasks_scheduled"] = self.state.tasks_scheduled
        results["tasks_executed"] = self.state.tasks_executed
        results["tasks_succeeded"] = self.state.tasks_succeeded
        results["tasks_failed"] = self.state.tasks_failed

        logger.info("health_check_result", **results)

        return results

    def _cleanup_task(self) -> dict[str, Any]:
        """
        清理任务

        清理过期数据、日志、临时文件等
        """
        import shutil
        from pathlib import Path

        results = {
            "logs_cleaned": 0,
            "cache_cleaned": 0,
            "temp_files_cleaned": 0,
            "old_reports_cleaned": 0,
        }

        # 1. 清理旧日志文件 (保留最近 7 天) + 确保总大小不超限
        try:
            from src.ops.logging import cleanup_old_logs

            log_result = cleanup_old_logs(max_size_mb=200)
            if log_result.get("cleaned", 0) > 0:
                logger.info("log_size_cleanup", **log_result)
                results["logs_cleaned"] += log_result["cleaned"]

            logs_dir = Path("logs")
            if logs_dir.exists():
                now = datetime.now(UTC)
                max_age_days = 7
                for log_file in logs_dir.glob("*.log*"):
                    if log_file.is_file():
                        mtime = datetime.fromtimestamp(log_file.stat().st_mtime, UTC)
                        age_days = (now - mtime).days
                        if age_days > max_age_days:
                            log_file.unlink()
                            results["logs_cleaned"] += 1
        except Exception as e:
            logger.warning("log_cleanup_failed", error=str(e))

        # 2. 清理 Python 缓存
        try:
            for cache_dir in Path(".").rglob("__pycache__"):
                if cache_dir.is_dir():
                    shutil.rmtree(cache_dir, ignore_errors=True)
                    results["cache_cleaned"] += 1
        except Exception as e:
            logger.warning("cache_cleanup_failed", error=str(e))

        # 3. 清理临时文件
        try:
            temp_patterns = ["*.tmp", "*.temp", ".*.swp"]
            for pattern in temp_patterns:
                for temp_file in Path(".").rglob(pattern):
                    if temp_file.is_file():
                        temp_file.unlink()
                        results["temp_files_cleaned"] += 1
        except Exception as e:
            logger.warning("temp_cleanup_failed", error=str(e))

        # 4. 清理旧的回测报告 (保留最近 30 天)
        try:
            reports_dir = Path("reports")
            if reports_dir.exists():
                now = datetime.now(UTC)
                max_age_days = 30
                for report_file in reports_dir.glob("backtest_report_*"):
                    if report_file.is_file():
                        mtime = datetime.fromtimestamp(report_file.stat().st_mtime, UTC)
                        age_days = (now - mtime).days
                        if age_days > max_age_days:
                            report_file.unlink()
                            results["old_reports_cleaned"] += 1
        except Exception as e:
            logger.warning("reports_cleanup_failed", error=str(e))

        # 5. 清理 ruff 缓存
        try:
            ruff_cache = Path(".ruff_cache")
            if ruff_cache.exists():
                shutil.rmtree(ruff_cache, ignore_errors=True)
                results["cache_cleaned"] += 1
        except Exception as e:
            logger.warning("ruff_cache_cleanup_failed", error=str(e))

        logger.info("cleanup_completed", **results)

        return results

    def _setup_tasks(self) -> None:
        """设置所有任务"""
        # 健康检查任务
        if self.config.enable_health_check:
            self._scheduler.add_health_check_task(
                func=self._health_check_task,
                interval_seconds=self.config.health_check_interval,
            )
            self.state.tasks_scheduled += 1

        # 清理任务
        if self.config.enable_cleanup:
            cleanup_task = ScheduledTask(
                task_id="cleanup",
                task_type=TaskType.CLEANUP,
                func=self._cleanup_task,
                interval_seconds=self.config.cleanup_interval_hours * 3600,
                description="Periodic cleanup task",
            )
            self._scheduler.add_task(cleanup_task)
            self.state.tasks_scheduled += 1

        logger.info(
            "tasks_setup_complete",
            tasks_count=self.state.tasks_scheduled,
        )

    def add_custom_task(
        self,
        task_id: str,
        func: Any,
        interval_seconds: int | None = None,
        cron: str | None = None,
        description: str = "",
    ) -> bool:
        """
        添加自定义任务

        Args:
            task_id: 任务 ID
            func: 任务函数
            interval_seconds: 间隔秒数
            cron: Cron 表达式
            description: 任务描述

        Returns:
            bool: 是否添加成功
        """
        task = ScheduledTask(
            task_id=task_id,
            task_type=TaskType.CUSTOM,
            func=func,
            interval_seconds=interval_seconds,
            cron=cron,
            description=description,
        )

        success = self._scheduler.add_task(task)
        if success:
            self.state.tasks_scheduled += 1

        return success

    def start(self) -> None:
        """启动服务"""
        logger.info("scheduler_service_starting")

        # 设置任务
        self._setup_tasks()

        # 启动调度器
        self._scheduler.start()

        self.state.running = True
        self.state.started_at = datetime.now(UTC)

        # 启动心跳
        self._heartbeat = HeartbeatWriter(
            service="scheduler",
            interval=30.0,
            details_func=lambda: {
                "tasks_scheduled": self.state.tasks_scheduled,
                "tasks_executed": self.state.tasks_executed,
                "tasks_failed": self.state.tasks_failed,
            },
        )
        self._heartbeat.start()

        logger.info(
            "scheduler_service_started",
            tasks_count=self.state.tasks_scheduled,
        )

        # 发送启动通知
        self._notifier.notify_system(
            title="⏰ Scheduler Service Started",
            content=(
                f"Tasks scheduled: {self.state.tasks_scheduled}\n"
                f"Health check: {'enabled' if self.config.enable_health_check else 'disabled'}\n"
                f"Cleanup: {'enabled' if self.config.enable_cleanup else 'disabled'}"
            ),
        )

    def stop(self, wait: bool = True) -> None:
        """
        停止服务

        Args:
            wait: 是否等待正在执行的任务完成
        """
        logger.info("scheduler_service_stopping")

        self.state.running = False

        # 停止心跳
        if hasattr(self, "_heartbeat"):
            self._heartbeat.stop()

        self._scheduler.stop(wait=wait)

        # 发送停止通知
        self._notifier.notify_system(
            title="⏹️ Scheduler Service Stopped",
            content=(
                f"Tasks executed: {self.state.tasks_executed}\n"
                f"Tasks succeeded: {self.state.tasks_succeeded}\n"
                f"Tasks failed: {self.state.tasks_failed}"
            ),
        )

        logger.info("scheduler_service_stopped")

    def run_forever(self) -> None:
        """阻塞运行，直到收到停止信号"""
        while self.state.running:
            time.sleep(1)

    def get_status(self) -> dict[str, Any]:
        """获取服务状态"""
        return {
            "running": self.state.running,
            "started_at": self.state.started_at.isoformat()
            if self.state.started_at
            else None,
            "tasks_scheduled": self.state.tasks_scheduled,
            "tasks_executed": self.state.tasks_executed,
            "tasks_succeeded": self.state.tasks_succeeded,
            "tasks_failed": self.state.tasks_failed,
            "uptime_seconds": (
                (datetime.now(UTC) - self.state.started_at).total_seconds()
                if self.state.started_at
                else 0
            ),
        }


def main() -> None:
    """Scheduler 服务主入口"""
    # 配置日志
    configure_logging(service_name="scheduler")

    settings = get_settings()

    # 创建服务
    config = SchedulerConfig(
        bar_close_delay=settings.bar_close_delay,
    )
    service = SchedulerService(config)

    # 信号处理
    def signal_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        logger.info("received_signal", signal=signum)
        service.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logger.info("scheduler_main_starting")

        # 启动并运行
        service.start()
        service.run_forever()

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
    except Exception as e:
        logger.exception("scheduler_main_error", error=str(e))
    finally:
        if service.state.running:
            service.stop()


if __name__ == "__main__":
    main()
