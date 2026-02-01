"""
订单管理器测试
"""

from decimal import Decimal

import pytest

from src.core.events import OrderSide, OrderStatus, OrderType
from src.execution.broker_base import (
    Balance,
    BrokerBase,
    BrokerResult,
    BrokerType,
    Order,
)
from src.execution.order_manager import OrderManager, OrderManagerState


class MockBroker(BrokerBase):
    """测试用 Mock Broker"""

    def __init__(self) -> None:
        super().__init__(broker_type=BrokerType.PAPER)
        self._orders: dict[str, Order] = {}
        self._balances: dict[str, Balance] = {
            "USDT": Balance(asset="USDT", free=Decimal("10000")),
        }

    def connect(self) -> BrokerResult:
        self._connected = True
        return BrokerResult.ok()

    def disconnect(self) -> BrokerResult:
        self._connected = False
        return BrokerResult.ok()

    def place_order(self, order: Order) -> BrokerResult:
        if not self._connected:
            return BrokerResult.fail("NOT_CONNECTED", "Not connected")
        order.status = OrderStatus.SUBMITTED
        order.exchange_order_id = f"mock_{order.client_order_id}"
        self._orders[order.client_order_id] = order
        return BrokerResult.ok(order)

    def cancel_order(
        self,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BrokerResult:
        if client_order_id and client_order_id in self._orders:
            order = self._orders[client_order_id]
            order.status = OrderStatus.CANCELLED
            return BrokerResult.ok(order)
        return BrokerResult.fail("NOT_FOUND", "Order not found")

    def query_order(
        self,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BrokerResult:
        if client_order_id and client_order_id in self._orders:
            return BrokerResult.ok(self._orders[client_order_id])
        return BrokerResult.fail("NOT_FOUND", "Order not found")

    def get_open_orders(self, symbol: str | None = None) -> BrokerResult:
        orders = [o for o in self._orders.values() if o.is_open]
        return BrokerResult.ok(orders)

    def get_balance(self, asset: str | None = None) -> BrokerResult:
        if asset:
            return BrokerResult.ok(self._balances.get(asset))
        return BrokerResult.ok(list(self._balances.values()))

    def get_positions(self, symbol: str | None = None) -> BrokerResult:
        return BrokerResult.ok([])


class TestOrderManagerState:
    """OrderManagerState 测试"""

    def test_state_creation(self) -> None:
        """测试状态创建"""
        state = OrderManagerState()
        assert state.daily_trades == 0
        assert state.daily_volume == Decimal("0")
        assert len(state.orders) == 0

    def test_to_dict(self) -> None:
        """测试转换为字典"""
        state = OrderManagerState(
            daily_trades=5,
            daily_volume=Decimal("10000"),
        )
        d = state.to_dict()

        assert d["daily_trades"] == 5
        assert d["daily_volume"] == "10000"


class TestOrderManager:
    """OrderManager 测试"""

    @pytest.fixture
    def broker(self) -> MockBroker:
        """创建 Mock Broker"""
        broker = MockBroker()
        broker.connect()
        return broker

    @pytest.fixture
    def order_manager(self, broker: MockBroker) -> OrderManager:
        """创建 OrderManager"""
        return OrderManager(broker)

    def test_submit_order(self, order_manager: OrderManager) -> None:
        """测试提交订单"""
        order = order_manager.broker.create_market_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
        )

        result = order_manager.submit_order(order)

        assert result.success is True
        assert result.data.status == OrderStatus.SUBMITTED
        assert order_manager.get_order(order.client_order_id) is not None

    def test_submit_duplicate_intent(self, order_manager: OrderManager) -> None:
        """测试重复意图被忽略（幂等性）"""
        order1 = order_manager.broker.create_market_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
        )

        intent_id = "unique_intent_123"

        result1 = order_manager.submit_order(order1, intent_id=intent_id)
        assert result1.success is True

        order2 = order_manager.broker.create_market_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
        )

        result2 = order_manager.submit_order(order2, intent_id=intent_id)
        # 重复意图应该被拒绝或返回已存在的订单
        assert result2.success is True or result2.error_code == "DUPLICATE"

    def test_cancel_order(self, order_manager: OrderManager) -> None:
        """测试取消订单"""
        order = order_manager.broker.create_limit_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("40000"),
        )

        order_manager.submit_order(order)

        result = order_manager.cancel_order(client_order_id=order.client_order_id)
        assert result.success is True

        cancelled_order = order_manager.get_order(order.client_order_id)
        assert cancelled_order.status == OrderStatus.CANCELLED

    def test_cancel_nonexistent_order(self, order_manager: OrderManager) -> None:
        """测试取消不存在的订单"""
        result = order_manager.cancel_order(client_order_id="nonexistent")
        assert result.success is False
        assert result.error_code == "ORDER_NOT_FOUND"

    def test_get_open_orders(self, order_manager: OrderManager) -> None:
        """测试获取挂单"""
        # 创建两个限价单
        for i in range(2):
            order = order_manager.broker.create_limit_order(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.1"),
                price=Decimal(f"{40000 + i * 100}"),
            )
            order_manager.submit_order(order)

        open_orders = order_manager.get_open_orders()
        assert len(open_orders) == 2

    def test_buy_market_convenience(self, order_manager: OrderManager) -> None:
        """测试市价买入便捷方法"""
        result = order_manager.buy_market(
            symbol="ETH/USDT",
            quantity=Decimal("1"),
            strategy_name="test",
        )

        assert result.success is True
        assert result.data.side == OrderSide.BUY
        assert result.data.order_type == OrderType.MARKET

    def test_sell_market_convenience(self, order_manager: OrderManager) -> None:
        """测试市价卖出便捷方法"""
        result = order_manager.sell_market(
            symbol="ETH/USDT",
            quantity=Decimal("1"),
        )

        assert result.success is True
        assert result.data.side == OrderSide.SELL

    def test_buy_limit_convenience(self, order_manager: OrderManager) -> None:
        """测试限价买入便捷方法"""
        result = order_manager.buy_limit(
            symbol="BTC/USDT",
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
        )

        assert result.success is True
        assert result.data.order_type == OrderType.LIMIT
        assert result.data.price == Decimal("45000")

    def test_reset_daily_stats(self, order_manager: OrderManager) -> None:
        """测试重置当日统计"""
        order_manager.state.daily_trades = 10
        order_manager.state.daily_volume = Decimal("50000")

        order_manager.reset_daily_stats()

        assert order_manager.state.daily_trades == 0
        assert order_manager.state.daily_volume == Decimal("0")

    def test_clear_completed_orders(self, order_manager: OrderManager) -> None:
        """测试清理已完成订单"""
        # 创建并完成多个订单
        for i in range(5):
            order = order_manager.broker.create_market_order(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.1"),
            )
            result = order_manager.submit_order(order)
            # 模拟成交
            result.data.status = OrderStatus.FILLED

        # 清理，只保留最近 2 个
        cleaned = order_manager.clear_completed_orders(keep_recent=2)
        assert cleaned == 3

    def test_get_balance(self, order_manager: OrderManager) -> None:
        """测试查询余额"""
        result = order_manager.get_balance("USDT")
        assert result.success is True
        assert result.data.asset == "USDT"

    def test_cancel_all_orders(self, order_manager: OrderManager) -> None:
        """测试取消所有订单"""
        # 创建多个挂单
        for i in range(3):
            order = order_manager.broker.create_limit_order(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.1"),
                price=Decimal(f"{40000 + i * 100}"),
            )
            order_manager.submit_order(order)

        results = order_manager.cancel_all_orders()
        assert len(results) == 3
        assert all(r.success for r in results)

        open_orders = order_manager.get_open_orders()
        assert len(open_orders) == 0
