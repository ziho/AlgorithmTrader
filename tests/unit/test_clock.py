"""
交易时钟模块测试
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.clock import (
    BacktestClock,
    ClockMode,
    LiveClock,
    create_clock,
)
from src.core.timeframes import Timeframe


class TestLiveClock:
    """LiveClock 测试"""

    def test_now_returns_utc_time(self):
        """测试 now() 返回 UTC 时间"""
        clock = LiveClock()
        now = clock.now()

        assert now.tzinfo is not None
        assert now.tzinfo == UTC

    def test_current_bar_time_15m(self):
        """测试 15 分钟 bar 时间计算"""
        _clock = LiveClock()  # Verify construction works

        # 模拟一个时间点
        test_time = datetime(2024, 1, 15, 10, 23, 45, tzinfo=UTC)

        # 使用 Timeframe.floor 直接测试
        bar_time = Timeframe.M15.floor(test_time)
        assert bar_time == datetime(2024, 1, 15, 10, 15, 0, tzinfo=UTC)

    def test_current_bar_time_1h(self):
        """测试 1 小时 bar 时间计算"""
        test_time = datetime(2024, 1, 15, 10, 23, 45, tzinfo=UTC)

        bar_time = Timeframe.H1.floor(test_time)
        assert bar_time == datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

    def test_next_bar_time(self):
        """测试下一个 bar 时间计算"""
        clock = LiveClock()
        current = clock.current_bar_time(Timeframe.M15)
        next_bar = clock.next_bar_time(Timeframe.M15)

        assert next_bar - current == timedelta(minutes=15)

    def test_time_to_next_bar(self):
        """测试距离下一个 bar 的时间"""
        clock = LiveClock()
        time_to_next = clock.time_to_next_bar(Timeframe.M15)

        # 应该在 0 到 15 分钟之间
        assert timedelta(0) < time_to_next <= timedelta(minutes=15)

    def test_time_to_bar_close_trigger(self):
        """测试包含延迟的触发时间"""
        delay = 10
        clock = LiveClock(bar_close_delay=delay)

        time_to_trigger = clock.time_to_bar_close_trigger(Timeframe.M15)
        time_to_next = clock.time_to_next_bar(Timeframe.M15)

        # 触发时间应该比 bar 结束时间多 delay 秒
        expected = time_to_next + timedelta(seconds=delay)
        assert abs((time_to_trigger - expected).total_seconds()) < 1


class TestBacktestClock:
    """BacktestClock 测试"""

    def test_default_start_time(self):
        """测试默认起始时间"""
        clock = BacktestClock()
        assert clock.now() == datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_custom_start_time(self):
        """测试自定义起始时间"""
        start = datetime(2023, 6, 15, 12, 30, 0, tzinfo=UTC)
        clock = BacktestClock(start_time=start)
        assert clock.now() == start

    def test_set_time(self):
        """测试设置时间"""
        clock = BacktestClock()
        new_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        clock.set_time(new_time)
        assert clock.now() == new_time

    def test_set_time_adds_timezone(self):
        """测试设置时间时自动添加时区"""
        clock = BacktestClock()
        naive_time = datetime(2024, 1, 1, 0, 0, 0)

        clock.set_time(naive_time)
        assert clock.now().tzinfo == UTC

    def test_advance(self):
        """测试时间推进"""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        clock = BacktestClock(start_time=start)

        result = clock.advance(timedelta(hours=1))

        assert result == datetime(2024, 1, 1, 1, 0, 0, tzinfo=UTC)
        assert clock.now() == result

    def test_advance_to(self):
        """测试推进到指定时间"""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        clock = BacktestClock(start_time=start)
        target = datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)

        result = clock.advance_to(target)

        assert result == target
        assert clock.now() == target

    def test_advance_to_backwards_raises(self):
        """测试向后推进抛出异常"""
        start = datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)
        clock = BacktestClock(start_time=start)
        target = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        with pytest.raises(ValueError, match="Cannot advance backwards"):
            clock.advance_to(target)

    def test_current_bar_time(self):
        """测试当前 bar 时间"""
        start = datetime(2024, 1, 1, 10, 23, 45, tzinfo=UTC)
        clock = BacktestClock(start_time=start)

        bar_time = clock.current_bar_time(Timeframe.M15)
        assert bar_time == datetime(2024, 1, 1, 10, 15, 0, tzinfo=UTC)

    def test_next_bar_time(self):
        """测试下一个 bar 时间"""
        start = datetime(2024, 1, 1, 10, 23, 45, tzinfo=UTC)
        clock = BacktestClock(start_time=start)

        next_bar = clock.next_bar_time(Timeframe.M15)
        assert next_bar == datetime(2024, 1, 1, 10, 30, 0, tzinfo=UTC)

    def test_advance_to_next_bar(self):
        """测试推进到下一个 bar"""
        start = datetime(2024, 1, 1, 10, 23, 45, tzinfo=UTC)
        clock = BacktestClock(start_time=start)

        result = clock.advance_to_next_bar(Timeframe.M15)

        assert result == datetime(2024, 1, 1, 10, 30, 0, tzinfo=UTC)
        assert clock.now() == result


class TestCreateClock:
    """create_clock 工厂函数测试"""

    def test_create_live_clock(self):
        """测试创建实盘时钟"""
        clock = create_clock(mode=ClockMode.LIVE)
        assert isinstance(clock, LiveClock)

    def test_create_backtest_clock(self):
        """测试创建回测时钟"""
        clock = create_clock(mode=ClockMode.BACKTEST)
        assert isinstance(clock, BacktestClock)

    def test_create_backtest_clock_with_start_time(self):
        """测试创建回测时钟并指定起始时间"""
        start = datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC)
        clock = create_clock(mode=ClockMode.BACKTEST, start_time=start)

        assert isinstance(clock, BacktestClock)
        assert clock.now() == start

    def test_default_mode_is_live(self):
        """测试默认模式是实盘"""
        clock = create_clock()
        assert isinstance(clock, LiveClock)

    def test_live_clock_with_delay(self):
        """测试创建带延迟的实盘时钟"""
        clock = create_clock(mode=ClockMode.LIVE, bar_close_delay=30)
        assert isinstance(clock, LiveClock)
        assert clock._bar_close_delay == 30
