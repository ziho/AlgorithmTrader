"""
回测引擎单元测试
"""

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from src.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    EquityPoint,
    Position,
    Trade,
)
from src.core.events import OrderSide
from src.core.typing import BarFrame, PositionSide, TargetPosition
from src.strategy.base import StrategyBase


class SimpleStrategy(StrategyBase):
    """简单测试策略：固定买入"""

    def on_bar(self, bar_frame: BarFrame) -> TargetPosition | None:
        # 在第一个 bar 后买入
        if len(bar_frame.history) > 0:
            return self.target_long(
                symbol=bar_frame.symbol,
                quantity=Decimal("1"),
                reason="test buy",
            )
        return None


class AlternatingStrategy(StrategyBase):
    """交替买卖策略"""

    def on_bar(self, bar_frame: BarFrame) -> TargetPosition | None:
        bar_count = self.get_state("bar_count", 0)
        self.set_state("bar_count", bar_count + 1)

        if bar_count % 2 == 0:
            return self.target_long(
                symbol=bar_frame.symbol,
                quantity=Decimal("1"),
            )
        else:
            return self.target_flat(bar_frame.symbol)


class TestPosition:
    """持仓测试"""

    def test_open_long(self):
        """开多仓"""
        pos = Position(symbol="BTC")
        pos.update(OrderSide.BUY, Decimal("1"), Decimal("50000"))
        assert pos.quantity == Decimal("1")
        assert pos.avg_price == Decimal("50000")
        assert pos.is_long

    def test_add_long(self):
        """加多仓"""
        pos = Position(symbol="BTC")
        pos.update(OrderSide.BUY, Decimal("1"), Decimal("50000"))
        pos.update(OrderSide.BUY, Decimal("1"), Decimal("52000"))
        assert pos.quantity == Decimal("2")
        assert pos.avg_price == Decimal("51000")  # (50000 + 52000) / 2

    def test_close_long(self):
        """平多仓"""
        pos = Position(symbol="BTC")
        pos.update(OrderSide.BUY, Decimal("1"), Decimal("50000"))
        realized = pos.update(OrderSide.SELL, Decimal("1"), Decimal("52000"))
        assert pos.is_flat
        assert realized == Decimal("2000")  # 盈利 2000

    def test_partial_close(self):
        """部分平仓"""
        pos = Position(symbol="BTC")
        pos.update(OrderSide.BUY, Decimal("2"), Decimal("50000"))
        realized = pos.update(OrderSide.SELL, Decimal("1"), Decimal("52000"))
        assert pos.quantity == Decimal("1")
        assert realized == Decimal("2000")

    def test_open_short(self):
        """开空仓"""
        pos = Position(symbol="BTC")
        pos.update(OrderSide.SELL, Decimal("1"), Decimal("50000"))
        assert pos.quantity == Decimal("-1")
        assert pos.is_short


class TestTrade:
    """成交记录测试"""

    def test_trade_value(self):
        """成交金额"""
        trade = Trade(
            timestamp=datetime.now(UTC),
            symbol="BTC",
            side=OrderSide.BUY,
            quantity=Decimal("2"),
            price=Decimal("50000"),
            commission=Decimal("100"),
        )
        assert trade.value == Decimal("100000")

    def test_to_dict(self):
        """序列化"""
        trade = Trade(
            timestamp=datetime.now(UTC),
            symbol="BTC",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            strategy_name="test",
        )
        d = trade.to_dict()
        assert d["symbol"] == "BTC"
        assert d["side"] == "buy"
        assert d["strategy_name"] == "test"


class TestEquityPoint:
    """权益曲线点测试"""

    def test_equity_point(self):
        """权益点"""
        point = EquityPoint(
            timestamp=datetime.now(UTC),
            equity=Decimal("100000"),
            cash=Decimal("50000"),
            position_value=Decimal("50000"),
            drawdown=Decimal("5000"),
            drawdown_pct=Decimal("0.05"),
        )
        assert point.equity == Decimal("100000")
        assert point.drawdown_pct == Decimal("0.05")


class TestBacktestConfig:
    """回测配置测试"""

    def test_default_config(self):
        """默认配置"""
        config = BacktestConfig()
        assert config.initial_capital == Decimal("100000")
        assert config.slippage_pct == Decimal("0.0005")

    def test_to_dict(self):
        """序列化"""
        config = BacktestConfig(
            initial_capital=Decimal("50000"),
            exchange="binance",
        )
        d = config.to_dict()
        assert d["initial_capital"] == "50000"
        assert d["exchange"] == "binance"


class TestBacktestEngine:
    """回测引擎测试"""

    def _create_mock_data(self) -> pd.DataFrame:
        """创建模拟数据"""
        dates = pd.date_range("2025-01-01", periods=10, freq="15min", tz="UTC")
        return pd.DataFrame({
            "timestamp": dates,
            "open": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "high": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
            "low": [99, 100, 101, 102, 103, 104, 105, 106, 107, 108],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5, 108.5, 109.5],
            "volume": [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900],
        })

    def test_calculate_equity(self):
        """计算权益"""
        engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("10000")))
        engine._cash = Decimal("5000")
        engine._positions["BTC"] = Position(
            symbol="BTC",
            quantity=Decimal("1"),
            avg_price=Decimal("50000"),
        )

        equity = engine._calculate_equity({"BTC": Decimal("51000")})
        assert equity == Decimal("56000")  # 5000 + 51000

    def test_get_position(self):
        """获取持仓"""
        engine = BacktestEngine()
        pos = engine._get_position("BTC")
        assert pos.symbol == "BTC"
        assert pos.is_flat

    def test_execute_trade_buy(self):
        """执行买入交易"""
        engine = BacktestEngine(BacktestConfig(
            initial_capital=Decimal("100000"),
            slippage_pct=Decimal("0"),
            commission_rate=Decimal("0.001"),
        ))

        trade = engine._execute_trade(
            symbol="BTC",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
            bar_volume=Decimal("1000"),
            timestamp=datetime.now(UTC),
        )

        assert trade is not None
        assert trade.side == OrderSide.BUY
        assert engine._cash < Decimal("100000")  # 现金减少

    def test_execute_trade_insufficient_funds(self):
        """资金不足时无法交易"""
        engine = BacktestEngine(BacktestConfig(
            initial_capital=Decimal("1000"),
        ))

        trade = engine._execute_trade(
            symbol="BTC",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),  # 需要 ~50050 但只有 1000
            bar_volume=Decimal("1000"),
            timestamp=datetime.now(UTC),
        )

        assert trade is None

    def test_process_target_position_long(self):
        """处理多头目标持仓"""
        engine = BacktestEngine(BacktestConfig(
            initial_capital=Decimal("100000"),
            slippage_pct=Decimal("0"),
        ))

        target = TargetPosition(
            symbol="BTC",
            side=PositionSide.LONG,
            quantity=Decimal("1"),
        )

        trade = engine._process_target_position(
            target=target,
            next_open=Decimal("50000"),
            bar_volume=Decimal("1000"),
            timestamp=datetime.now(UTC),
        )

        assert trade is not None
        assert engine._get_position("BTC").quantity == Decimal("1")

    def test_process_target_position_flat(self):
        """处理平仓目标"""
        engine = BacktestEngine(BacktestConfig(
            initial_capital=Decimal("100000"),
            slippage_pct=Decimal("0"),
        ))

        # 先开仓
        engine._get_position("BTC").update(
            OrderSide.BUY, Decimal("1"), Decimal("50000")
        )
        engine._cash = Decimal("50000")

        target = TargetPosition(
            symbol="BTC",
            side=PositionSide.FLAT,
            quantity=Decimal("0"),
        )

        trade = engine._process_target_position(
            target=target,
            next_open=Decimal("51000"),
            bar_volume=Decimal("1000"),
            timestamp=datetime.now(UTC),
        )

        assert trade is not None
        assert trade.side == OrderSide.SELL

    def test_create_bar_frame(self):
        """创建 BarFrame"""
        engine = BacktestEngine()
        df = self._create_mock_data()
        row = df.iloc[5]
        history = df.iloc[:5]

        bar_frame = engine._create_bar_frame(
            symbol="OKX:BTC/USDT",
            timeframe="15m",
            row=row,
            history_df=history,
        )

        assert bar_frame.symbol == "OKX:BTC/USDT"
        assert bar_frame.timeframe == "15m"
        assert bar_frame.close == Decimal("105.5")
        assert len(bar_frame.history) == 5
