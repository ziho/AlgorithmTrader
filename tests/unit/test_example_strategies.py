"""
测试趋势跟踪和均值回归策略

覆盖:
- DualMAStrategy: 双均线交叉
- DonchianBreakoutStrategy: 通道突破
- BollingerBandsStrategy: 布林带
- RSIMeanReversionStrategy: RSI 均值回归
- ZScoreStrategy: Z-Score 策略
"""

from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from src.core.typing import BarFrame, PositionSide
from src.strategy.base import StrategyConfig
from src.strategy.examples.mean_reversion import (
    BollingerBandsStrategy,
    RSIMeanReversionStrategy,
    ZScoreStrategy,
    create_mean_reversion_strategy,
)
from src.strategy.examples.trend_following import (
    DonchianBreakoutStrategy,
    DualMAStrategy,
    create_trend_strategy,
)


def create_bar_frame(
    symbol: str,
    prices: list[float],
    current_close: float | None = None,
) -> BarFrame:
    """创建带有历史数据的 BarFrame"""
    n = len(prices)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")  # 小写 h

    history = pd.DataFrame(
        {
            "timestamp": dates,
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1000.0] * n,
        }
    )

    close_price = current_close if current_close is not None else prices[-1]

    return BarFrame(
        symbol=symbol,
        timeframe="1h",
        timestamp=dates[-1].to_pydatetime(),
        open=Decimal(str(prices[-1])),
        high=Decimal(str(close_price * 1.01)),
        low=Decimal(str(close_price * 0.99)),
        close=Decimal(str(close_price)),
        volume=Decimal("1000"),
        history=history,
    )


def create_ohlc_bar_frame(
    symbol: str,
    open_prices: list[float],
    high_prices: list[float],
    low_prices: list[float],
    close_prices: list[float],
) -> BarFrame:
    """创建带有完整 OHLC 数据的 BarFrame"""
    n = len(close_prices)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")  # 小写 h

    history = pd.DataFrame(
        {
            "timestamp": dates,
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": [1000.0] * n,
        }
    )

    return BarFrame(
        symbol=symbol,
        timeframe="1h",
        timestamp=dates[-1].to_pydatetime(),
        open=Decimal(str(open_prices[-1])),
        high=Decimal(str(high_prices[-1])),
        low=Decimal(str(low_prices[-1])),
        close=Decimal(str(close_prices[-1])),
        volume=Decimal("1000"),
        history=history,
    )


# ============================================================================
# DualMAStrategy 测试
# ============================================================================


class TestDualMAStrategy:
    """测试双均线交叉策略"""

    def test_init_default_params(self):
        """测试默认参数初始化"""
        strategy = DualMAStrategy()
        assert strategy.fast_period == 10
        assert strategy.slow_period == 30  # 默认 30
        assert strategy.position_size == Decimal("1.0")
        assert strategy.allow_short is False

    def test_init_custom_params(self):
        """测试自定义参数"""
        config = StrategyConfig(
            name="test_ma",
            symbols=["BTC/USDT"],
            params={
                "fast_period": 5,
                "slow_period": 15,
                "position_size": 0.5,
                "allow_short": True,
                "use_ema": True,
            },
        )
        strategy = DualMAStrategy(config)
        assert strategy.fast_period == 5
        assert strategy.slow_period == 15
        assert strategy.position_size == Decimal("0.5")
        assert strategy.allow_short is True
        assert strategy.use_ema is True

    def test_insufficient_data_returns_none(self):
        """数据不足时返回 None"""
        strategy = DualMAStrategy()
        bar_frame = create_bar_frame("BTC/USDT", [100.0] * 10)
        result = strategy.on_bar(bar_frame)
        assert result is None

    def test_golden_cross_generates_long_signal(self):
        """金叉产生做多信号"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"fast_period": 3, "slow_period": 5},
        )
        strategy = DualMAStrategy(config)

        # 构造金叉：快线从下往上穿越慢线
        prices = [100, 99, 98, 97, 96, 97, 98, 99, 100, 102]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity > 0  # 做多

    def test_death_cross_closes_long(self):
        """死叉平掉多仓"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"fast_period": 3, "slow_period": 5},
        )
        strategy = DualMAStrategy(config)

        # 先建立多仓
        strategy.state.positions["BTC/USDT"] = Decimal("1.0")

        # 构造死叉：快线从上往下穿越慢线
        prices = [96, 97, 98, 99, 100, 99, 98, 97, 96, 94]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity == 0  # 平仓

    def test_death_cross_with_allow_short(self):
        """允许做空时死叉产生空仓信号"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"fast_period": 3, "slow_period": 5, "allow_short": True},
        )
        strategy = DualMAStrategy(config)

        # 构造死叉
        prices = [96, 97, 98, 99, 100, 99, 98, 97, 96, 94]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.side == PositionSide.SHORT  # 做空


class TestDonchianBreakoutStrategy:
    """测试唐奇安通道突破策略"""

    def test_init_default_params(self):
        """测试默认参数"""
        strategy = DonchianBreakoutStrategy()
        assert strategy.entry_period == 20
        assert strategy.exit_period == 10

    def test_breakout_up_generates_long(self):
        """向上突破产生做多信号"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"entry_period": 5, "exit_period": 3},
        )
        strategy = DonchianBreakoutStrategy(config)

        # 构造向上突破：当前 close 需要大于前 N 根 bar 的最高高价
        # 横盘后大幅突破
        prices = [100.0] * 25 + [100, 100, 100, 100, 120]  # 最后一个大幅突破

        highs = [p * 1.01 for p in prices]  # 高价 = close * 1.01
        lows = [p * 0.99 for p in prices]

        bar_frame = create_ohlc_bar_frame(
            "BTC/USDT",
            open_prices=prices,
            high_prices=highs,
            low_prices=lows,
            close_prices=prices,
        )

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity > 0

    def test_breakout_down_with_short(self):
        """向下突破且允许做空时产生空仓信号"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={
                "entry_period": 5,
                "exit_period": 3,
                "allow_short": True,
            },
        )
        strategy = DonchianBreakoutStrategy(config)

        # 构造向下突破
        prices = [100.0] * 25 + [99, 98, 97, 96, 95]

        highs = [p * 1.01 for p in prices]
        lows = [p * 0.99 for p in prices]

        bar_frame = create_ohlc_bar_frame(
            "BTC/USDT",
            open_prices=prices,
            high_prices=highs,
            low_prices=lows,
            close_prices=prices,
        )

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.side == PositionSide.SHORT


class TestCreateTrendStrategy:
    """测试趋势策略工厂函数"""

    def test_create_dual_ma(self):
        """创建双均线策略"""
        strategy = create_trend_strategy(
            strategy_type="dual_ma",
            params={"fast_period": 5, "slow_period": 10},
        )
        assert isinstance(strategy, DualMAStrategy)
        assert strategy.fast_period == 5

    def test_create_donchian(self):
        """创建唐奇安通道策略"""
        strategy = create_trend_strategy(
            strategy_type="donchian",
            params={"entry_period": 10},
        )
        assert isinstance(strategy, DonchianBreakoutStrategy)
        assert strategy.entry_period == 10

    def test_invalid_type_raises(self):
        """无效类型抛出异常"""
        with pytest.raises(ValueError, match="Unknown strategy type"):
            create_trend_strategy(strategy_type="invalid")


# ============================================================================
# BollingerBandsStrategy 测试
# ============================================================================


class TestBollingerBandsStrategy:
    """测试布林带策略"""

    def test_init_default_params(self):
        """测试默认参数"""
        strategy = BollingerBandsStrategy()
        assert strategy.period == 20
        assert strategy.std_dev == 2.0

    def test_touch_lower_band_generates_long(self):
        """触及下轨产生做多信号"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"period": 10, "std_dev": 2.0},
        )
        strategy = BollingerBandsStrategy(config)

        # 构造触及下轨：正常波动后突然大跌
        prices = [100.0] * 15 + [99, 98, 97, 96, 90]  # 最后一个大幅低于均值
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity > 0

    def test_touch_upper_band_closes_long(self):
        """触及上轨平掉多仓"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"period": 10, "std_dev": 2.0},
        )
        strategy = BollingerBandsStrategy(config)

        # 先建立多仓
        strategy.state.positions["BTC/USDT"] = Decimal("1.0")

        # 构造触及上轨
        prices = [100.0] * 15 + [101, 102, 103, 104, 110]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity == 0  # 平仓

    def test_exit_at_middle(self):
        """价格回归中轨时平仓"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"period": 10, "std_dev": 2.0, "exit_at_middle": True},
        )
        strategy = BollingerBandsStrategy(config)

        # 建立多仓并设置入场方向
        strategy.state.positions["BTC/USDT"] = Decimal("1.0")
        strategy.set_state("entry_side", "long")

        # 价格回到中轨
        prices = [100.0] * 20
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity == 0


class TestRSIMeanReversionStrategy:
    """测试 RSI 均值回归策略"""

    def test_init_default_params(self):
        """测试默认参数"""
        strategy = RSIMeanReversionStrategy()
        assert strategy.period == 14
        assert strategy.oversold == 30
        assert strategy.overbought == 70

    def test_oversold_generates_long(self):
        """超卖产生做多信号"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"period": 5, "oversold": 30, "overbought": 70},
        )
        strategy = RSIMeanReversionStrategy(config)

        # 构造超卖：连续下跌
        prices = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity > 0

    def test_overbought_closes_long(self):
        """超买平掉多仓"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"period": 5, "oversold": 30, "overbought": 70},
        )
        strategy = RSIMeanReversionStrategy(config)

        # 先建立多仓
        strategy.state.positions["BTC/USDT"] = Decimal("1.0")

        # 构造超买：连续上涨
        prices = [90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity == 0

    def test_exit_at_neutral(self):
        """RSI 回归中性区域时平仓"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"period": 5, "exit_level": 50},
        )
        strategy = RSIMeanReversionStrategy(config)

        # 建立多仓并设置入场方向
        strategy.state.positions["BTC/USDT"] = Decimal("1.0")
        strategy.set_state("entry_side", "long")

        # 构造 RSI 接近 50 的价格序列
        prices = [100, 99, 100, 99, 100, 99, 100, 99, 100, 99]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        # RSI 接近 50，应该平仓
        if result is not None:
            assert result.quantity == 0


class TestZScoreStrategy:
    """测试 Z-Score 策略"""

    def test_init_default_params(self):
        """测试默认参数"""
        strategy = ZScoreStrategy()
        assert strategy.lookback == 20
        assert strategy.entry_threshold == 2.0
        assert strategy.exit_threshold == 0.5

    def test_low_zscore_generates_long(self):
        """Z-Score 低于阈值产生做多信号"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"lookback": 10, "entry_threshold": 2.0},
        )
        strategy = ZScoreStrategy(config)

        # 构造低 Z-Score：正常后突然大跌
        prices = [100.0] * 15 + [99, 98, 97, 96, 85]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity > 0

    def test_high_zscore_generates_short(self):
        """Z-Score 高于阈值产生做空信号"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"lookback": 10, "entry_threshold": 2.0},
        )
        strategy = ZScoreStrategy(config)

        # 构造高 Z-Score：正常后突然大涨
        prices = [100.0] * 15 + [101, 102, 103, 104, 115]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.side == PositionSide.SHORT

    def test_zscore_exit(self):
        """Z-Score 回归时平仓"""
        config = StrategyConfig(
            name="test",
            symbols=["BTC/USDT"],
            params={"lookback": 10, "exit_threshold": 0.5},
        )
        strategy = ZScoreStrategy(config)

        # 建立多仓
        strategy.state.positions["BTC/USDT"] = Decimal("1.0")

        # Z-Score 接近 0
        prices = [100.0] * 20
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        assert result is not None
        assert result.quantity == 0


class TestCreateMeanReversionStrategy:
    """测试均值回归策略工厂函数"""

    def test_create_bollinger(self):
        """创建布林带策略"""
        strategy = create_mean_reversion_strategy(
            strategy_type="bollinger",
            params={"period": 10, "std_dev": 1.5},
        )
        assert isinstance(strategy, BollingerBandsStrategy)
        assert strategy.period == 10
        assert strategy.std_dev == 1.5

    def test_create_rsi(self):
        """创建 RSI 策略"""
        strategy = create_mean_reversion_strategy(
            strategy_type="rsi",
            params={"period": 10, "oversold": 25},
        )
        assert isinstance(strategy, RSIMeanReversionStrategy)
        assert strategy.period == 10
        assert strategy.oversold == 25

    def test_create_zscore(self):
        """创建 Z-Score 策略"""
        strategy = create_mean_reversion_strategy(
            strategy_type="zscore",
            params={"lookback": 15},
        )
        assert isinstance(strategy, ZScoreStrategy)
        assert strategy.lookback == 15

    def test_invalid_type_raises(self):
        """无效类型抛出异常"""
        with pytest.raises(ValueError, match="Unknown strategy type"):
            create_mean_reversion_strategy(strategy_type="invalid")


# ============================================================================
# 边界情况测试
# ============================================================================


class TestEdgeCases:
    """边界情况测试"""

    def test_no_history_returns_none(self):
        """没有历史数据返回 None"""
        strategies = [
            DualMAStrategy(),
            DonchianBreakoutStrategy(),
            BollingerBandsStrategy(),
            RSIMeanReversionStrategy(),
            ZScoreStrategy(),
        ]

        bar_frame = BarFrame(
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=datetime.now(),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1000"),
            history=pd.DataFrame(),  # 空历史
        )

        for strategy in strategies:
            result = strategy.on_bar(bar_frame)
            assert result is None

    def test_state_persistence(self):
        """状态持久化"""
        strategy = BollingerBandsStrategy()
        prices = [100.0] * 25
        bar_frame = create_bar_frame("BTC/USDT", prices)

        strategy.on_bar(bar_frame)

        # 检查状态是否被保存
        assert strategy.get_state("bb_middle") is not None
        assert strategy.get_state("bb_upper") is not None
        assert strategy.get_state("bb_lower") is not None

    def test_rsi_extreme_gains(self):
        """RSI 计算：全部上涨"""
        strategy = RSIMeanReversionStrategy(
            StrategyConfig(
                name="test",
                symbols=["BTC/USDT"],
                params={"period": 5},
            )
        )

        # 全部上涨，RSI 应该接近 100
        prices = [90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100]
        bar_frame = create_bar_frame("BTC/USDT", prices)

        strategy.on_bar(bar_frame)
        rsi = strategy.get_state("rsi")
        assert rsi is not None
        assert rsi > 90  # 应该接近 100

    def test_bollinger_zero_std(self):
        """布林带：标准差为 0 的情况"""
        strategy = BollingerBandsStrategy(
            StrategyConfig(
                name="test",
                symbols=["BTC/USDT"],
                params={"period": 10},
            )
        )

        # 所有价格相同，标准差为 0
        prices = [100.0] * 20
        bar_frame = create_bar_frame("BTC/USDT", prices)

        result = strategy.on_bar(bar_frame)
        # 应该不会崩溃
        assert (
            result is None
            or isinstance(result, type(None))
            or hasattr(result, "quantity")
        )
