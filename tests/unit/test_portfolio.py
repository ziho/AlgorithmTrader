"""
Portfolio 模块单元测试

测试范围:
- Position: 头寸对象和持仓更新
- PositionTracker: 多品种持仓管理
- PositionAllocator: 信号到目标持仓转换
- AccountingEngine: 账户核算
- PnLCalculator: 盈亏计算工具
"""

from datetime import datetime
from decimal import Decimal

from src.portfolio.accounting import (
    AccountingEngine,
    EquityPoint,
    PnLCalculator,
    TradeRecord,
)
from src.portfolio.allocator import (
    AllocationConfig,
    AllocationMethod,
    OrderIntent,
    PositionAllocator,
    Signal,
    TargetPosition,
    WeightCalculator,
)
from src.portfolio.position import (
    OrderSide,
    Position,
    PositionSide,
    PositionSnapshot,
    PositionTracker,
)


class TestPosition:
    """Position 头寸对象测试"""

    def test_position_initial_state(self) -> None:
        """测试初始状态"""
        pos = Position(symbol="BTC/USDT")
        assert pos.quantity == Decimal("0")
        assert pos.avg_price == Decimal("0")
        assert pos.is_flat
        assert pos.side == PositionSide.FLAT

    def test_position_open_long(self) -> None:
        """测试开多仓"""
        pos = Position(symbol="BTC/USDT")
        ts = datetime(2024, 1, 1, 10, 0, 0)

        realized = pos.update(OrderSide.BUY, Decimal("1"), Decimal("50000"), ts)

        assert pos.quantity == Decimal("1")
        assert pos.avg_price == Decimal("50000")
        assert pos.is_long
        assert pos.side == PositionSide.LONG
        assert realized == Decimal("0")
        assert pos.created_at == ts

    def test_position_open_short(self) -> None:
        """测试开空仓"""
        pos = Position(symbol="BTC/USDT")

        realized = pos.update(OrderSide.SELL, Decimal("1"), Decimal("50000"))

        assert pos.quantity == Decimal("-1")
        assert pos.avg_price == Decimal("50000")
        assert pos.is_short
        assert pos.side == PositionSide.SHORT
        assert realized == Decimal("0")

    def test_position_add_to_long(self) -> None:
        """测试加多仓"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("1"), avg_price=Decimal("50000"))

        pos.update(OrderSide.BUY, Decimal("1"), Decimal("52000"))

        assert pos.quantity == Decimal("2")
        assert pos.avg_price == Decimal("51000")  # (50000 + 52000) / 2

    def test_position_partial_close_long(self) -> None:
        """测试多仓部分平仓"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("2"), avg_price=Decimal("50000"))

        realized = pos.update(OrderSide.SELL, Decimal("1"), Decimal("55000"))

        assert pos.quantity == Decimal("1")
        assert pos.avg_price == Decimal("50000")
        assert realized == Decimal("5000")  # (55000 - 50000) * 1

    def test_position_full_close_long(self) -> None:
        """测试多仓全部平仓"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("1"), avg_price=Decimal("50000"))

        realized = pos.update(OrderSide.SELL, Decimal("1"), Decimal("55000"))

        assert pos.is_flat
        assert pos.avg_price == Decimal("0")
        assert realized == Decimal("5000")

    def test_position_partial_close_short(self) -> None:
        """测试空仓部分平仓"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("-2"), avg_price=Decimal("50000"))

        realized = pos.update(OrderSide.BUY, Decimal("1"), Decimal("48000"))

        assert pos.quantity == Decimal("-1")
        assert realized == Decimal("2000")  # (50000 - 48000) * 1 做空盈利

    def test_position_reverse_long_to_short(self) -> None:
        """测试多翻空"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("1"), avg_price=Decimal("50000"))

        realized = pos.update(OrderSide.SELL, Decimal("2"), Decimal("55000"))

        assert pos.quantity == Decimal("-1")
        assert pos.avg_price == Decimal("55000")
        assert realized == Decimal("5000")  # 平多仓盈利

    def test_position_unrealized_pnl_long(self) -> None:
        """测试多仓未实现盈亏"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("1"), avg_price=Decimal("50000"))

        assert pos.unrealized_pnl(Decimal("55000")) == Decimal("5000")
        assert pos.unrealized_pnl(Decimal("45000")) == Decimal("-5000")

    def test_position_unrealized_pnl_short(self) -> None:
        """测试空仓未实现盈亏"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("-1"), avg_price=Decimal("50000"))

        # 空仓价格下跌盈利
        assert pos.unrealized_pnl(Decimal("45000")) == Decimal("5000")
        assert pos.unrealized_pnl(Decimal("55000")) == Decimal("-5000")

    def test_position_market_value(self) -> None:
        """测试市值计算"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("2"), avg_price=Decimal("50000"))

        assert pos.market_value(Decimal("52000")) == Decimal("104000")

    def test_position_close_method(self) -> None:
        """测试close方法"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("1"), avg_price=Decimal("50000"))

        realized = pos.close(Decimal("55000"))

        assert pos.is_flat
        assert realized == Decimal("5000")

    def test_position_copy(self) -> None:
        """测试复制"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("1"), avg_price=Decimal("50000"))
        pos_copy = pos.copy()

        pos.update(OrderSide.BUY, Decimal("1"), Decimal("52000"))

        assert pos_copy.quantity == Decimal("1")  # 副本不受影响

    def test_position_to_dict(self) -> None:
        """测试转换为字典"""
        pos = Position(symbol="BTC/USDT", quantity=Decimal("1"), avg_price=Decimal("50000"))
        d = pos.to_dict()

        assert d["symbol"] == "BTC/USDT"
        assert d["quantity"] == "1"
        assert d["side"] == "long"


class TestPositionTracker:
    """PositionTracker 持仓跟踪器测试"""

    def test_tracker_initial_state(self) -> None:
        """测试初始状态"""
        tracker = PositionTracker()
        assert len(tracker.positions) == 0
        assert len(tracker.active_positions) == 0

    def test_tracker_get_position(self) -> None:
        """测试获取持仓"""
        tracker = PositionTracker()
        pos = tracker.get_position("BTC/USDT")

        assert pos.symbol == "BTC/USDT"
        assert pos.is_flat

    def test_tracker_update_position(self) -> None:
        """测试更新持仓"""
        tracker = PositionTracker()

        tracker.update_position("BTC/USDT", OrderSide.BUY, Decimal("1"), Decimal("50000"))

        assert tracker.has_position("BTC/USDT")
        pos = tracker.get_position("BTC/USDT")
        assert pos.quantity == Decimal("1")

    def test_tracker_multiple_positions(self) -> None:
        """测试多品种持仓"""
        tracker = PositionTracker()

        tracker.update_position("BTC/USDT", OrderSide.BUY, Decimal("1"), Decimal("50000"))
        tracker.update_position("ETH/USDT", OrderSide.BUY, Decimal("10"), Decimal("3000"))

        assert len(tracker.active_positions) == 2

    def test_tracker_calculate_value(self) -> None:
        """测试计算总市值"""
        tracker = PositionTracker()
        tracker.update_position("BTC/USDT", OrderSide.BUY, Decimal("1"), Decimal("50000"))
        tracker.update_position("ETH/USDT", OrderSide.BUY, Decimal("10"), Decimal("3000"))

        prices = {"BTC/USDT": Decimal("52000"), "ETH/USDT": Decimal("3200")}
        value = tracker.calculate_value(prices)

        assert value == Decimal("84000")  # 52000 + 32000

    def test_tracker_close_position(self) -> None:
        """测试平仓"""
        tracker = PositionTracker()
        tracker.update_position("BTC/USDT", OrderSide.BUY, Decimal("1"), Decimal("50000"))

        realized = tracker.close_position("BTC/USDT", Decimal("55000"))

        assert realized == Decimal("5000")
        assert not tracker.has_position("BTC/USDT")

    def test_tracker_close_all(self) -> None:
        """测试全部平仓"""
        tracker = PositionTracker()
        tracker.update_position("BTC/USDT", OrderSide.BUY, Decimal("1"), Decimal("50000"))
        tracker.update_position("ETH/USDT", OrderSide.BUY, Decimal("10"), Decimal("3000"))

        prices = {"BTC/USDT": Decimal("55000"), "ETH/USDT": Decimal("3200")}
        realized = tracker.close_all(prices)

        assert realized == Decimal("7000")  # 5000 + 2000
        assert len(tracker.active_positions) == 0

    def test_tracker_take_snapshot(self) -> None:
        """测试生成快照"""
        tracker = PositionTracker()
        tracker.update_position("BTC/USDT", OrderSide.BUY, Decimal("1"), Decimal("50000"))

        ts = datetime(2024, 1, 1, 10, 0, 0)
        prices = {"BTC/USDT": Decimal("52000")}
        snapshot = tracker.take_snapshot(ts, prices, Decimal("50000"))

        assert snapshot.timestamp == ts
        assert snapshot.total_value == Decimal("52000")
        assert snapshot.cash == Decimal("50000")
        assert snapshot.equity == Decimal("102000")

    def test_tracker_reset(self) -> None:
        """测试重置"""
        tracker = PositionTracker()
        tracker.update_position("BTC/USDT", OrderSide.BUY, Decimal("1"), Decimal("50000"))
        tracker.reset()

        assert len(tracker.positions) == 0


class TestTargetPosition:
    """TargetPosition 目标持仓测试"""

    def test_target_position_signed_quantity(self) -> None:
        """测试带符号数量"""
        long = TargetPosition(symbol="BTC/USDT", side=PositionSide.LONG, quantity=Decimal("1"))
        short = TargetPosition(symbol="BTC/USDT", side=PositionSide.SHORT, quantity=Decimal("1"))
        flat = TargetPosition(symbol="BTC/USDT", side=PositionSide.FLAT, quantity=Decimal("1"))

        assert long.signed_quantity == Decimal("1")
        assert short.signed_quantity == Decimal("-1")
        assert flat.signed_quantity == Decimal("0")

    def test_target_position_notional(self) -> None:
        """测试名义价值"""
        target = TargetPosition(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=Decimal("1"),
            price=Decimal("50000"),
        )
        assert target.notional == Decimal("50000")


class TestSignal:
    """Signal 信号测试"""

    def test_signal_side(self) -> None:
        """测试信号方向"""
        long = Signal(symbol="BTC/USDT", value=Decimal("1"))
        short = Signal(symbol="BTC/USDT", value=Decimal("-1"))
        flat = Signal(symbol="BTC/USDT", value=Decimal("0"))

        assert long.side == PositionSide.LONG
        assert short.side == PositionSide.SHORT
        assert flat.side == PositionSide.FLAT


class TestPositionAllocator:
    """PositionAllocator 仓位分配器测试"""

    def test_allocator_equal_weight(self) -> None:
        """测试等权重分配"""
        config = AllocationConfig(
            method=AllocationMethod.EQUAL_WEIGHT,
            max_position_weight=Decimal("0.5"),  # 允许每个品种最多50%
        )
        allocator = PositionAllocator(config)

        signals = [
            Signal(symbol="BTC/USDT", value=Decimal("1")),
            Signal(symbol="ETH/USDT", value=Decimal("1")),
        ]
        prices = {"BTC/USDT": Decimal("50000"), "ETH/USDT": Decimal("3000")}
        equity = Decimal("100000")

        targets = allocator.signals_to_targets(signals, prices, equity)

        assert len(targets) == 2
        assert all(t.weight == Decimal("0.5") for t in targets)

    def test_allocator_max_weight_constraint(self) -> None:
        """测试最大权重约束"""
        config = AllocationConfig(
            method=AllocationMethod.EQUAL_WEIGHT,
            max_position_weight=Decimal("0.3"),
        )
        allocator = PositionAllocator(config)

        signals = [Signal(symbol="BTC/USDT", value=Decimal("1"))]
        prices = {"BTC/USDT": Decimal("50000")}
        equity = Decimal("100000")

        targets = allocator.signals_to_targets(signals, prices, equity)

        assert len(targets) == 1
        assert targets[0].weight == Decimal("0.3")

    def test_allocator_signal_weight(self) -> None:
        """测试按信号强度分配"""
        config = AllocationConfig(
            method=AllocationMethod.SIGNAL_WEIGHT,
            max_position_weight=Decimal("1"),  # 不限制权重
        )
        allocator = PositionAllocator(config)

        signals = [
            Signal(symbol="BTC/USDT", value=Decimal("2")),  # 强度2
            Signal(symbol="ETH/USDT", value=Decimal("1")),  # 强度1
        ]
        prices = {"BTC/USDT": Decimal("50000"), "ETH/USDT": Decimal("3000")}
        equity = Decimal("100000")

        targets = allocator.signals_to_targets(signals, prices, equity)

        assert len(targets) == 2
        # BTC权重应该是ETH的2倍
        btc_target = next(t for t in targets if t.symbol == "BTC/USDT")
        eth_target = next(t for t in targets if t.symbol == "ETH/USDT")
        assert btc_target.weight > eth_target.weight

    def test_allocator_flat_signals(self) -> None:
        """测试平仓信号"""
        allocator = PositionAllocator()

        signals = [Signal(symbol="BTC/USDT", value=Decimal("0"))]
        prices = {"BTC/USDT": Decimal("50000")}
        equity = Decimal("100000")

        targets = allocator.signals_to_targets(signals, prices, equity)

        assert len(targets) == 1
        assert targets[0].side == PositionSide.FLAT

    def test_allocator_targets_to_orders(self) -> None:
        """测试目标持仓转订单"""
        allocator = PositionAllocator()

        targets = [
            TargetPosition(
                symbol="BTC/USDT",
                side=PositionSide.LONG,
                quantity=Decimal("1"),
                price=Decimal("50000"),
            )
        ]
        current_positions: dict[str, Position] = {}

        orders = allocator.targets_to_orders(targets, current_positions)

        assert len(orders) == 1
        assert orders[0].side == OrderSide.BUY
        assert orders[0].quantity == Decimal("1")

    def test_allocator_targets_to_orders_with_existing(self) -> None:
        """测试有现有持仓时的订单生成"""
        allocator = PositionAllocator()

        targets = [
            TargetPosition(
                symbol="BTC/USDT",
                side=PositionSide.LONG,
                quantity=Decimal("2"),
                price=Decimal("50000"),
            )
        ]
        current_positions = {
            "BTC/USDT": Position(symbol="BTC/USDT", quantity=Decimal("1"))
        }

        orders = allocator.targets_to_orders(targets, current_positions)

        assert len(orders) == 1
        assert orders[0].side == OrderSide.BUY
        assert orders[0].quantity == Decimal("1")  # 只需买入1个

    def test_allocator_min_trade_notional(self) -> None:
        """测试最小交易金额"""
        config = AllocationConfig(min_trade_notional=Decimal("100"))
        allocator = PositionAllocator(config)

        targets = [
            TargetPosition(
                symbol="BTC/USDT",
                side=PositionSide.LONG,
                quantity=Decimal("0.001"),
                price=Decimal("50000"),
            )
        ]
        current_positions: dict[str, Position] = {}

        orders = allocator.targets_to_orders(targets, current_positions)

        # 50000 * 0.001 = 50 < 100，不生成订单
        assert len(orders) == 0


class TestWeightCalculator:
    """WeightCalculator 权重计算器测试"""

    def test_equal_weight(self) -> None:
        """测试等权重"""
        weights = WeightCalculator.equal_weight(4)
        assert len(weights) == 4
        assert all(w == Decimal("0.25") for w in weights)

    def test_signal_weight(self) -> None:
        """测试信号权重"""
        signals = [Decimal("2"), Decimal("1"), Decimal("1")]
        weights = WeightCalculator.signal_weight(signals)

        assert len(weights) == 3
        assert weights[0] == Decimal("0.5")  # 2/4
        assert weights[1] == Decimal("0.25")  # 1/4
        assert weights[2] == Decimal("0.25")  # 1/4

    def test_normalize_weights(self) -> None:
        """测试归一化权重"""
        weights = [Decimal("1"), Decimal("2"), Decimal("3")]
        normalized = WeightCalculator.normalize_weights(weights)

        total = sum(normalized)
        assert abs(total - Decimal("1")) < Decimal("0.0001")

    def test_rebalance_weights(self) -> None:
        """测试再平衡权重"""
        current = {"BTC": Decimal("0.4"), "ETH": Decimal("0.3")}
        target = {"BTC": Decimal("0.5"), "ETH": Decimal("0.28")}  # ETH差异0.02 < 阈值0.05

        adjustments = WeightCalculator.rebalance_weights(current, target, Decimal("0.05"))

        assert "BTC" in adjustments  # 需要调整，差异0.1
        assert "ETH" not in adjustments  # 差异小于阈值


class TestAccountingEngine:
    """AccountingEngine 账户核算测试"""

    def test_accounting_initial_state(self) -> None:
        """测试初始状态"""
        engine = AccountingEngine(initial_capital=Decimal("100000"))

        assert engine.cash == Decimal("100000")
        assert len(engine.trades) == 0
        assert len(engine.equity_curve) == 0

    def test_accounting_record_trade_buy(self) -> None:
        """测试记录买入"""
        engine = AccountingEngine(initial_capital=Decimal("100000"))

        trade = engine.record_trade(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
        )

        assert engine.cash == Decimal("49950")  # 100000 - 50000 - 50
        assert trade.notional == Decimal("50000")
        assert len(engine.trades) == 1

    def test_accounting_record_trade_sell(self) -> None:
        """测试记录卖出（盈利）"""
        engine = AccountingEngine(initial_capital=Decimal("100000"))

        # 先买入
        engine.record_trade(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
        )

        # 再卖出
        trade = engine.record_trade(
            timestamp=datetime(2024, 1, 1, 11, 0, 0),
            symbol="BTC/USDT",
            side=OrderSide.SELL,
            quantity=Decimal("1"),
            price=Decimal("55000"),
            commission=Decimal("55"),
        )

        assert trade.realized_pnl == Decimal("5000")
        assert engine.cash == Decimal("104895")  # 49950 + 55000 - 55

    def test_accounting_update_equity_curve(self) -> None:
        """测试更新权益曲线"""
        engine = AccountingEngine(initial_capital=Decimal("100000"))

        engine.record_trade(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
        )

        prices = {"BTC/USDT": Decimal("52000")}
        point = engine.update_equity_curve(datetime(2024, 1, 1, 10, 15, 0), prices)

        assert point.equity == Decimal("102000")  # 50000 cash + 52000 position
        assert point.position_value == Decimal("52000")
        assert point.unrealized_pnl == Decimal("2000")

    def test_accounting_drawdown_calculation(self) -> None:
        """测试回撤计算"""
        engine = AccountingEngine(initial_capital=Decimal("100000"))

        # 模拟上涨后下跌
        prices_up = {"BTC/USDT": Decimal("55000")}
        prices_down = {"BTC/USDT": Decimal("45000")}

        engine.record_trade(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
        )

        # 上涨
        engine.update_equity_curve(datetime(2024, 1, 1, 10, 15, 0), prices_up)
        # 下跌
        point = engine.update_equity_curve(datetime(2024, 1, 1, 10, 30, 0), prices_down)

        # 峰值 = 105000, 当前 = 95000
        assert point.drawdown == Decimal("10000")

    def test_accounting_get_statistics(self) -> None:
        """测试获取统计"""
        engine = AccountingEngine(initial_capital=Decimal("100000"))

        engine.record_trade(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
        )

        prices = {"BTC/USDT": Decimal("52000")}
        stats = engine.get_statistics(prices)

        assert stats["total_trades"] == 1
        assert stats["total_commission"] == "50"

    def test_accounting_reset(self) -> None:
        """测试重置"""
        engine = AccountingEngine(initial_capital=Decimal("100000"))

        engine.record_trade(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
        )

        engine.reset()

        assert engine.cash == Decimal("100000")
        assert len(engine.trades) == 0


class TestPnLCalculator:
    """PnLCalculator 盈亏计算器测试"""

    def test_calculate_trade_pnl_long_profit(self) -> None:
        """测试多头盈利"""
        pnl = PnLCalculator.calculate_trade_pnl(
            entry_price=Decimal("50000"),
            exit_price=Decimal("55000"),
            quantity=Decimal("1"),
            is_long=True,
        )
        assert pnl == Decimal("5000")

    def test_calculate_trade_pnl_long_loss(self) -> None:
        """测试多头亏损"""
        pnl = PnLCalculator.calculate_trade_pnl(
            entry_price=Decimal("50000"),
            exit_price=Decimal("45000"),
            quantity=Decimal("1"),
            is_long=True,
        )
        assert pnl == Decimal("-5000")

    def test_calculate_trade_pnl_short_profit(self) -> None:
        """测试空头盈利"""
        pnl = PnLCalculator.calculate_trade_pnl(
            entry_price=Decimal("50000"),
            exit_price=Decimal("45000"),
            quantity=Decimal("1"),
            is_long=False,
        )
        assert pnl == Decimal("5000")

    def test_calculate_return(self) -> None:
        """测试收益率计算"""
        ret = PnLCalculator.calculate_return(
            entry_value=Decimal("100000"),
            exit_value=Decimal("110000"),
        )
        assert ret == Decimal("0.1")

    def test_calculate_drawdown(self) -> None:
        """测试回撤计算"""
        equity = [
            Decimal("100000"),
            Decimal("110000"),
            Decimal("105000"),
            Decimal("120000"),
            Decimal("100000"),
        ]
        max_dd, max_dd_pct = PnLCalculator.calculate_drawdown(equity)

        # 从120000到100000
        assert max_dd == Decimal("20000")

    def test_calculate_sharpe_ratio(self) -> None:
        """测试夏普比率计算"""
        returns = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01"), Decimal("0.015")]
        sharpe = PnLCalculator.calculate_sharpe_ratio(returns)

        # 应该返回一个有效的夏普值
        assert isinstance(sharpe, Decimal)


class TestTradeRecord:
    """TradeRecord 成交记录测试"""

    def test_trade_record_properties(self) -> None:
        """测试成交记录属性"""
        trade = TradeRecord(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            slippage=Decimal("25"),
            realized_pnl=Decimal("0"),
        )

        assert trade.notional == Decimal("50000")
        assert trade.total_cost == Decimal("75")
        assert trade.net_pnl == Decimal("-75")


class TestEquityPoint:
    """EquityPoint 权益点测试"""

    def test_equity_point_to_dict(self) -> None:
        """测试转换为字典"""
        point = EquityPoint(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            equity=Decimal("100000"),
            cash=Decimal("50000"),
            position_value=Decimal("50000"),
        )
        d = point.to_dict()

        assert d["equity"] == "100000"
        assert "timestamp" in d


class TestPositionSnapshot:
    """PositionSnapshot 快照测试"""

    def test_snapshot_equity(self) -> None:
        """测试快照权益"""
        snapshot = PositionSnapshot(
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            total_value=Decimal("50000"),
            cash=Decimal("50000"),
        )

        assert snapshot.equity == Decimal("100000")


class TestOrderIntent:
    """OrderIntent 订单意图测试"""

    def test_order_intent_notional(self) -> None:
        """测试名义价值"""
        intent = OrderIntent(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("50000"),
        )

        assert intent.notional == Decimal("50000")

    def test_order_intent_to_dict(self) -> None:
        """测试转换为字典"""
        intent = OrderIntent(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
        )
        d = intent.to_dict()

        assert d["symbol"] == "BTC/USDT"
        assert d["side"] == "buy"
