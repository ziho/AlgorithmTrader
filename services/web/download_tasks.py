"""
后台下载任务管理

用于历史数据下载的队列、进度与 ETA 估算。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from src.data.fetcher.history import HistoryFetcher
from src.ops.logging import get_logger

logger = get_logger(__name__)


def format_eta(seconds: int | None) -> str:
    """格式化 ETA 文本"""
    if seconds is None or seconds < 0:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


@dataclass
class DownloadTask:
    id: str
    exchange: str
    symbols: list[str]
    timeframe: str
    start_date: datetime
    end_date: datetime
    status: str = "queued"  # queued, running, completed, failed, cancelled
    progress: float = 0.0
    total_units: int = 0
    completed_units: int = 0
    current_symbol: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    eta_seconds: int | None = None
    message: str = ""


class DownloadTaskManager:
    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir)
        self._tasks: dict[str, DownloadTask] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._cancel_requested: set[str] = set()  # 待取消的任务 ID

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._worker_loop())

    async def enqueue(
        self,
        exchange: str,
        symbols: list[str],
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> DownloadTask:
        task_id = str(uuid4())[:8]
        task = DownloadTask(
            id=task_id,
            exchange=exchange,
            symbols=symbols,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            status="queued",
            message="等待中",
        )
        self._tasks[task_id] = task
        await self._queue.put(task_id)
        logger.info("download_task_enqueued", task_id=task_id)
        return task

    def cancel_task(self, task_id: str) -> bool:
        """取消一个下载任务（排队中立即取消，运行中在下个交易对完成后取消）"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status == "queued":
            task.status = "cancelled"
            task.message = "已取消"
            task.finished_at = datetime.now(UTC)
            return True
        if task.status == "running":
            self._cancel_requested.add(task_id)
            task.message = "正在取消..."
            return True
        return False

    def clear_finished(self) -> int:
        """清除所有已完成/失败/已取消的任务，返回清除数量"""
        to_remove = [
            tid
            for tid, t in self._tasks.items()
            if t.status in ("completed", "failed", "cancelled")
        ]
        for tid in to_remove:
            del self._tasks[tid]
        return len(to_remove)

    def _auto_cleanup_finished(self, max_finished: int = 50) -> None:
        """自动清理超量的已完成任务，防止内存无限增长（24/7 运行保护）"""
        finished = [
            (tid, t)
            for tid, t in self._tasks.items()
            if t.status in ("completed", "failed", "cancelled")
        ]
        if len(finished) > max_finished:
            # 按完成时间排序，删除最旧的
            finished.sort(key=lambda x: x[1].finished_at or x[1].created_at)
            for tid, _ in finished[: len(finished) - max_finished]:
                del self._tasks[tid]

    def list_tasks(self) -> list[DownloadTask]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def get_active_tasks(self) -> list[DownloadTask]:
        return [t for t in self.list_tasks() if t.status in ("queued", "running")]

    def get_task(self, task_id: str) -> DownloadTask | None:
        return self._tasks.get(task_id)

    def _estimate_eta(self, task: DownloadTask) -> None:
        if not task.started_at or task.completed_units <= 0 or task.total_units <= 0:
            task.eta_seconds = None
            return
        elapsed = (datetime.now(UTC) - task.started_at).total_seconds()
        if elapsed <= 0:
            task.eta_seconds = None
            return
        rate = task.completed_units / elapsed
        remaining = max(task.total_units - task.completed_units, 0)
        task.eta_seconds = int(remaining / rate) if rate > 0 else None

    async def _worker_loop(self) -> None:
        while True:
            task_id = await self._queue.get()
            task = self._tasks.get(task_id)
            if not task or task.status == "cancelled":
                continue

            task.status = "running"
            task.started_at = datetime.now(UTC)
            task.message = "开始下载"
            logger.info("download_task_started", task_id=task_id)

            try:
                async with HistoryFetcher(
                    data_dir=self._data_dir,
                    exchange=task.exchange,
                ) as fetcher:
                    # 预估总月份数（只统计未完成的月份）
                    total_units = 0
                    pending_map: dict[str, int] = {}
                    for sym in task.symbols:
                        pending = fetcher.checkpoint.get_pending_periods(
                            task.exchange,
                            sym.replace("/", "").upper(),
                            task.timeframe,
                            task.start_date.year,
                            task.start_date.month,
                            task.end_date.year,
                            task.end_date.month,
                        )
                        pending_count = len(pending)
                        pending_map[sym] = pending_count
                        total_units += pending_count
                    task.total_units = total_units

                    if total_units == 0:
                        task.progress = 100.0
                        task.message = "无待下载数据"
                        task.status = "completed"
                        task.finished_at = datetime.now(UTC)
                        continue

                    completed_units = 0

                    for sym in task.symbols:
                        # 检查是否请求了取消
                        if task.id in self._cancel_requested:
                            self._cancel_requested.discard(task.id)
                            task.status = "cancelled"
                            task.message = "已取消（下载中断）"
                            task.finished_at = datetime.now(UTC)
                            logger.info("download_task_cancelled", task_id=task_id)
                            break

                        task.current_symbol = sym
                        task.message = f"下载中: {sym}"
                        symbol_total = pending_map.get(sym, 0)
                        base_completed = completed_units

                        def on_progress(
                            completed: int,
                            total: int,
                            _stats,
                            task=task,
                            base_completed=base_completed,
                        ) -> None:
                            task.completed_units = base_completed + completed
                            task.progress = min(
                                100.0, task.completed_units / task.total_units * 100.0
                            )
                            self._estimate_eta(task)

                        await fetcher.download_and_save(
                            symbol=sym,
                            timeframe=task.timeframe,
                            start_date=task.start_date,
                            end_date=task.end_date,
                            skip_existing=True,
                            progress_callback=on_progress,
                        )

                        # yield to event loop - 防止下载阻塞 WebSocket 通信
                        await asyncio.sleep(0)

                        # 完成一个交易对后，推进已完成计数
                        completed_units += symbol_total
                        task.completed_units = completed_units
                        task.progress = min(
                            100.0, task.completed_units / task.total_units * 100.0
                        )
                        self._estimate_eta(task)

                    if task.status != "cancelled":
                        task.status = "completed"
                        task.progress = 100.0
                        task.message = "下载完成"
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.message = "下载失败"
                logger.warning("download_task_failed", task_id=task_id, error=str(e))
            finally:
                task.current_symbol = None
                task.finished_at = datetime.now(UTC)
                # 自动清理已完成任务，防止长时间运行内存泄漏
                self._auto_cleanup_finished()


_MANAGER: DownloadTaskManager | None = None


def get_download_manager(data_dir: Path) -> DownloadTaskManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = DownloadTaskManager(data_dir)
        _MANAGER.start()
    return _MANAGER
