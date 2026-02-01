"""
交易时钟模块

职责:
- Bar close 事件触发
- 延迟触发（避免交易所数据未落地）
- 支持不同时间框架
- 提供统一的时间管理接口

注意: 核心调度功能已在 src/ops/scheduler.py 实现
本模块提供更轻量级的时间相关工具
"""

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol

from src.core.timeframes import Timeframe


class ClockMode(str, Enum):
    """时钟模式"""

    LIVE = "live"  # 实盘模式，使用真实时间
    BACKTEST = "backtest"  # 回测模式，使用模拟时间


class Clock(Protocol):
    """时钟协议"""

    def now(self) -> datetime:
        """获取当前时间"""
        ...

    def current_bar_time(self, timeframe: Timeframe) -> datetime:
        """获取当前 bar 开始时间"""
        ...

    def next_bar_time(self, timeframe: Timeframe) -> datetime:
        """获取下一个 bar 开始时间"""
        ...


class LiveClock:
    """
    实盘时钟

    使用真实的 UTC 时间
    """

    def __init__(self, bar_close_delay: int = 10):
        """
        初始化实盘时钟

        Args:
            bar_close_delay: Bar close 延迟秒数
        """
        self._bar_close_delay = bar_close_delay

    def now(self) -> datetime:
        """获取当前 UTC 时间"""
        return datetime.now(UTC)

    def current_bar_time(self, timeframe: Timeframe) -> datetime:
        """
        获取当前 bar 开始时间

        Args:
            timeframe: 时间框架

        Returns:
            datetime: 当前 bar 开始时间
        """
        return timeframe.floor(self.now())

    def next_bar_time(self, timeframe: Timeframe) -> datetime:
        """
        获取下一个 bar 开始时间

        Args:
            timeframe: 时间框架

        Returns:
            datetime: 下一个 bar 开始时间
        """
        current = self.current_bar_time(timeframe)
        return current + timeframe.timedelta

    def time_to_next_bar(self, timeframe: Timeframe) -> timedelta:
        """
        计算距离下一个 bar 的时间

        Args:
            timeframe: 时间框架

        Returns:
            timedelta: 距离下一个 bar 的时间
        """
        next_bar = self.next_bar_time(timeframe)
        return next_bar - self.now()

    def time_to_bar_close_trigger(self, timeframe: Timeframe) -> timedelta:
        """
        计算距离 bar close 触发的时间（包含延迟）

        Args:
            timeframe: 时间框架

        Returns:
            timedelta: 距离触发的时间
        """
        time_to_next = self.time_to_next_bar(timeframe)
        delay = timedelta(seconds=self._bar_close_delay)
        return time_to_next + delay


class BacktestClock:
    """
    回测时钟

    使用模拟时间，可以手动推进
    """

    def __init__(self, start_time: datetime | None = None):
        """
        初始化回测时钟

        Args:
            start_time: 起始时间，默认为 2020-01-01 00:00 UTC
        """
        self._current_time = start_time or datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        """获取当前模拟时间"""
        return self._current_time

    def set_time(self, dt: datetime) -> None:
        """
        设置当前时间

        Args:
            dt: 目标时间
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        self._current_time = dt

    def advance(self, delta: timedelta) -> datetime:
        """
        推进时间

        Args:
            delta: 推进量

        Returns:
            datetime: 推进后的时间
        """
        self._current_time = self._current_time + delta
        return self._current_time

    def advance_to(self, dt: datetime) -> datetime:
        """
        推进到指定时间

        Args:
            dt: 目标时间

        Returns:
            datetime: 推进后的时间

        Raises:
            ValueError: 目标时间早于当前时间
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt < self._current_time:
            raise ValueError(
                f"Cannot advance backwards: current={self._current_time}, target={dt}"
            )
        self._current_time = dt
        return self._current_time

    def current_bar_time(self, timeframe: Timeframe) -> datetime:
        """获取当前 bar 开始时间"""
        return timeframe.floor(self._current_time)

    def next_bar_time(self, timeframe: Timeframe) -> datetime:
        """获取下一个 bar 开始时间"""
        current = self.current_bar_time(timeframe)
        return current + timeframe.timedelta

    def advance_to_next_bar(self, timeframe: Timeframe) -> datetime:
        """
        推进到下一个 bar

        Args:
            timeframe: 时间框架

        Returns:
            datetime: 下一个 bar 的时间
        """
        next_bar = self.next_bar_time(timeframe)
        self._current_time = next_bar
        return next_bar


def create_clock(
    mode: ClockMode = ClockMode.LIVE,
    start_time: datetime | None = None,
    bar_close_delay: int = 10,
) -> LiveClock | BacktestClock:
    """
    创建时钟实例

    Args:
        mode: 时钟模式
        start_time: 回测起始时间
        bar_close_delay: Bar close 延迟秒数

    Returns:
        时钟实例
    """
    if mode == ClockMode.BACKTEST:
        return BacktestClock(start_time=start_time)
    return LiveClock(bar_close_delay=bar_close_delay)


# 导出
__all__ = [
    "ClockMode",
    "Clock",
    "LiveClock",
    "BacktestClock",
    "create_clock",
]
