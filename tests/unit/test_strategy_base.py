"""
策略基类单元测试
"""

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from src.core.events import FillEvent, OrderSide
from src.core.typing import BarFrame, OrderIntent, PositionSide, TargetPosition
from src.strategy.base import StrategyBase, StrategyConfig, StrategyState


class DummyStrategy(StrategyBase):
    """测试用策略"""

    def on_bar(self, bar_frame: BarFrame) -> TargetPosition | None:
        """简单的多头策略：价格上涨则做多"""
        close = bar_frame.close_price
        threshold = self.get_param("threshold", 50000)

        if close > threshold:
            return self.target_long(
                symbol=bar_frame.symbol,
                quantity=Decimal("0.1"),
                reason=f"Price {close} > threshold {threshold}",
            )
        return None


class TestStrategyConfig:
    """策略配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = StrategyConfig()
        assert config.name == "unnamed"
        assert config.symbols == []
        assert config.timeframes == ["15m"]
        assert config.params == {}

    def test_custom_config(self):
        """测试自定义配置"""
        config = StrategyConfig(
            name="test_strategy",
            symbols=["OKX:BTC/USDT", "OKX:ETH/USDT"],
            timeframes=["15m", "1h"],
            params={"fast_period": 10, "slow_period": 20},
            max_position_size=Decimal("1.0"),
            stop_loss_pct=0.02,
        )
        assert config.name == "test_strategy"
        assert len(config.symbols) == 2
        assert config.params["fast_period"] == 10
        assert config.max_position_size == Decimal("1.0")
        assert config.stop_loss_pct == 0.02

    def test_config_to_dict(self):
        """测试配置序列化"""
        config = StrategyConfig(
            name="test",
            params={"key": "value"},
        )
        d = config.to_dict()
        assert d["name"] == "test"
        assert d["params"]["key"] == "value"


class TestStrategyState:
    """策略状态测试"""

    def test_position_management(self):
        """测试持仓管理"""
        state = StrategyState()

        # 初始无持仓
        assert state.get_position("BTC") == Decimal("0")

        # 更新持仓
        state.update_position("BTC", Decimal("1.5"))
        assert state.get_position("BTC") == Decimal("1.5")

        # 清除持仓
        state.update_position("BTC", Decimal("0"))
        assert state.get_position("BTC") == Decimal("0")
        assert "BTC" not in state.positions

    def test_custom_state(self):
        """测试自定义状态"""
        state = StrategyState()
        state.custom["my_indicator"] = 123.45
        assert state.custom["my_indicator"] == 123.45


class TestBarFrame:
    """BarFrame 数据结构测试"""

    def test_basic_bar_frame(self):
        """测试基本 BarFrame"""
        bar = BarFrame(
            symbol="OKX:BTC/USDT",
            timeframe="15m",
            timestamp=datetime.now(UTC),
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
        )
        assert bar.symbol == "OKX:BTC/USDT"
        assert bar.close_price == 50500.0
        assert bar.ohlcv == (50000.0, 51000.0, 49000.0, 50500.0, 100.0)

    def test_bar_frame_with_history(self):
        """测试带历史数据的 BarFrame"""
        history = pd.DataFrame(
            {
                "open": [49000, 49500, 50000],
                "high": [50000, 50500, 51000],
                "low": [48500, 49000, 49500],
                "close": [49500, 50000, 50500],
                "volume": [90, 95, 100],
            }
        )
        bar = BarFrame(
            symbol="OKX:BTC/USDT",
            timeframe="15m",
            timestamp=datetime.now(UTC),
            open=Decimal("50500"),
            high=Decimal("51500"),
            low=Decimal("50000"),
            close=Decimal("51000"),
            volume=Decimal("110"),
            history=history,
        )
        assert len(bar.history_close) == 3
        assert bar.history_close[-1] == 50500.0

    def test_bar_frame_features(self):
        """测试带特征的 BarFrame"""
        features = pd.DataFrame(
            {
                "ma20": [49500, 49750, 50000],
                "rsi": [55, 60, 65],
            }
        )
        bar = BarFrame(
            symbol="OKX:BTC/USDT",
            timeframe="15m",
            timestamp=datetime.now(UTC),
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
            features=features,
        )
        ma20 = bar.get_feature("ma20")
        assert ma20 is not None
        assert len(ma20) == 3
        assert bar.get_feature("nonexistent") is None


class TestTargetPosition:
    """目标持仓测试"""

    def test_long_position(self):
        """测试多头持仓"""
        pos = TargetPosition(
            symbol="OKX:BTC/USDT",
            side=PositionSide.LONG,
            quantity=Decimal("0.5"),
            strategy_name="test",
            reason="bullish signal",
        )
        assert pos.side == PositionSide.LONG
        assert not pos.is_flat
        assert pos.quantity == Decimal("0.5")

    def test_flat_position(self):
        """测试平仓"""
        pos = TargetPosition(
            symbol="OKX:BTC/USDT",
            side=PositionSide.FLAT,
            quantity=Decimal("0"),
        )
        assert pos.is_flat

    def test_position_to_dict(self):
        """测试序列化"""
        pos = TargetPosition(
            symbol="OKX:BTC/USDT",
            side=PositionSide.LONG,
            quantity=Decimal("1.0"),
        )
        d = pos.to_dict()
        assert d["symbol"] == "OKX:BTC/USDT"
        assert d["side"] == "long"
        assert d["quantity"] == "1.0"


class TestOrderIntent:
    """下单意图测试"""

    def test_market_order(self):
        """测试市价单"""
        intent = OrderIntent(
            symbol="OKX:BTC/USDT",
            side=PositionSide.LONG,
            quantity=Decimal("0.1"),
        )
        assert intent.is_market_order
        assert intent.limit_price is None

    def test_limit_order(self):
        """测试限价单"""
        intent = OrderIntent(
            symbol="OKX:BTC/USDT",
            side=PositionSide.LONG,
            quantity=Decimal("0.1"),
            order_type="limit",
            limit_price=Decimal("50000"),
        )
        assert not intent.is_market_order
        assert intent.limit_price == Decimal("50000")


class TestStrategyBase:
    """策略基类测试"""

    def test_strategy_initialization(self):
        """测试策略初始化"""
        config = StrategyConfig(
            name="dummy",
            symbols=["OKX:BTC/USDT"],
            params={"threshold": 50000},
        )
        strategy = DummyStrategy(config)

        assert strategy.name == "dummy"
        assert strategy.symbols == ["OKX:BTC/USDT"]
        assert strategy.get_param("threshold") == 50000

    def test_on_bar_returns_target(self):
        """测试 on_bar 返回目标持仓"""
        config = StrategyConfig(
            name="dummy",
            params={"threshold": 50000},
        )
        strategy = DummyStrategy(config)

        # 价格高于阈值，应返回多头
        bar = BarFrame(
            symbol="OKX:BTC/USDT",
            timeframe="15m",
            timestamp=datetime.now(UTC),
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("51000"),
            volume=Decimal("100"),
        )
        result = strategy.on_bar(bar)
        assert result is not None
        assert isinstance(result, TargetPosition)
        assert result.side == PositionSide.LONG

    def test_on_bar_returns_none(self):
        """测试 on_bar 返回 None"""
        config = StrategyConfig(
            name="dummy",
            params={"threshold": 60000},
        )
        strategy = DummyStrategy(config)

        # 价格低于阈值，应返回 None
        bar = BarFrame(
            symbol="OKX:BTC/USDT",
            timeframe="15m",
            timestamp=datetime.now(UTC),
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
        )
        result = strategy.on_bar(bar)
        assert result is None

    def test_helper_methods(self):
        """测试辅助方法"""
        strategy = DummyStrategy(StrategyConfig(name="test"))

        # target_long
        pos = strategy.target_long("BTC", Decimal("1.0"), reason="test")
        assert pos.side == PositionSide.LONG
        assert pos.strategy_name == "test"

        # target_short
        pos = strategy.target_short("BTC", Decimal("1.0"))
        assert pos.side == PositionSide.SHORT

        # target_flat
        pos = strategy.target_flat("BTC")
        assert pos.is_flat

        # intent_buy
        intent = strategy.intent_buy("BTC", Decimal("0.5"))
        assert intent.side == PositionSide.LONG
        assert intent.is_market_order

        # intent_sell with limit
        intent = strategy.intent_sell("BTC", Decimal("0.5"), limit_price=Decimal("60000"))
        assert intent.side == PositionSide.SHORT
        assert not intent.is_market_order

    def test_on_fill_updates_stats(self):
        """测试成交事件更新统计"""
        strategy = DummyStrategy(StrategyConfig(name="test"))

        assert strategy.state.total_trades == 0

        fill = FillEvent(
            symbol="OKX:BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("50000"),
        )
        strategy.on_fill(fill)

        assert strategy.state.total_trades == 1
        assert strategy.state.last_trade_time is not None

    def test_custom_state(self):
        """测试自定义状态管理"""
        strategy = DummyStrategy(StrategyConfig(name="test"))

        strategy.set_state("my_indicator", 42)
        assert strategy.get_state("my_indicator") == 42
        assert strategy.get_state("nonexistent", "default") == "default"
