"""
Broker 基类测试
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
    Position,
)


class TestOrder:
    """Order 数据类测试"""

    def test_order_creation(self) -> None:
        """测试订单创建"""
        order = Order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        assert order.symbol == "BTC/USDT"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == Decimal("0.1")
        assert order.status == OrderStatus.NEW
        assert order.client_order_id  # 自动生成

    def test_order_is_open(self) -> None:
        """测试订单是否挂单中"""
        order = Order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            status=OrderStatus.NEW,
        )
        assert order.is_open is True

        order.status = OrderStatus.SUBMITTED
        assert order.is_open is True

        order.status = OrderStatus.PARTIAL
        assert order.is_open is True

        order.status = OrderStatus.FILLED
        assert order.is_open is False

        order.status = OrderStatus.CANCELLED
        assert order.is_open is False

    def test_order_is_filled(self) -> None:
        """测试订单是否已成交"""
        order = Order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
        assert order.is_filled is False

        order.status = OrderStatus.FILLED
        assert order.is_filled is True

    def test_order_remaining_quantity(self) -> None:
        """测试剩余数量"""
        order = Order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            filled_quantity=Decimal("3"),
        )
        assert order.remaining_quantity == Decimal("7")

    def test_order_filled_value(self) -> None:
        """测试成交金额"""
        order = Order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            filled_quantity=Decimal("0.5"),
            filled_avg_price=Decimal("50000"),
        )
        assert order.filled_value == Decimal("25000")

    def test_order_to_dict(self) -> None:
        """测试转换为字典"""
        order = Order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )
        d = order.to_dict()

        assert d["symbol"] == "BTC/USDT"
        assert d["side"] == "buy"
        assert d["order_type"] == "market"
        assert d["quantity"] == "0.1"


class TestBalance:
    """Balance 数据类测试"""

    def test_balance_total(self) -> None:
        """测试总余额"""
        balance = Balance(
            asset="USDT",
            free=Decimal("1000"),
            locked=Decimal("500"),
        )
        assert balance.total == Decimal("1500")

    def test_balance_to_dict(self) -> None:
        """测试转换为字典"""
        balance = Balance(asset="BTC", free=Decimal("1.5"), locked=Decimal("0.5"))
        d = balance.to_dict()

        assert d["asset"] == "BTC"
        assert d["free"] == "1.5"
        assert d["locked"] == "0.5"
        # Decimal("1.5") + Decimal("0.5") = Decimal("2.0") -> "2.0"
        assert Decimal(d["total"]) == Decimal("2")


class TestPosition:
    """Position 数据类测试"""

    def test_position_value(self) -> None:
        """测试持仓价值"""
        position = Position(
            symbol="BTC/USDT",
            quantity=Decimal("0.5"),
            avg_price=Decimal("50000"),
        )
        assert position.value == Decimal("25000")

    def test_position_to_dict(self) -> None:
        """测试转换为字典"""
        position = Position(
            symbol="ETH/USDT",
            side="long",
            quantity=Decimal("10"),
            avg_price=Decimal("3000"),
        )
        d = position.to_dict()

        assert d["symbol"] == "ETH/USDT"
        assert d["side"] == "long"
        assert d["quantity"] == "10"
        assert d["value"] == "30000"


class TestBrokerResult:
    """BrokerResult 测试"""

    def test_result_ok(self) -> None:
        """测试成功结果"""
        result = BrokerResult.ok(data={"test": "value"})
        assert result.success is True
        assert result.data == {"test": "value"}
        assert result.error_code == ""

    def test_result_fail(self) -> None:
        """测试失败结果"""
        result = BrokerResult.fail("ERR_CODE", "Error message")
        assert result.success is False
        assert result.error_code == "ERR_CODE"
        assert result.error_message == "Error message"


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


class TestBrokerBase:
    """BrokerBase 测试"""

    def test_broker_connect_disconnect(self) -> None:
        """测试连接和断开"""
        broker = MockBroker()
        assert broker.is_connected is False

        result = broker.connect()
        assert result.success is True
        assert broker.is_connected is True

        result = broker.disconnect()
        assert result.success is True
        assert broker.is_connected is False

    def test_broker_create_market_order(self) -> None:
        """测试创建市价单"""
        broker = MockBroker()
        order = broker.create_market_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            strategy_name="test",
        )

        assert order.symbol == "BTC/USDT"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == Decimal("0.1")
        assert order.strategy_name == "test"

    def test_broker_create_limit_order(self) -> None:
        """测试创建限价单"""
        broker = MockBroker()
        order = broker.create_limit_order(
            symbol="ETH/USDT",
            side=OrderSide.SELL,
            quantity=Decimal("1"),
            price=Decimal("3500"),
        )

        assert order.symbol == "ETH/USDT"
        assert order.side == OrderSide.SELL
        assert order.order_type == OrderType.LIMIT
        assert order.price == Decimal("3500")

    def test_broker_place_order(self) -> None:
        """测试下单"""
        broker = MockBroker()
        broker.connect()

        order = broker.create_market_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
        )

        result = broker.place_order(order)
        assert result.success is True
        assert result.data.status == OrderStatus.SUBMITTED
        assert result.data.exchange_order_id.startswith("mock_")

    def test_broker_place_order_not_connected(self) -> None:
        """测试未连接时下单"""
        broker = MockBroker()

        order = broker.create_market_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
        )

        result = broker.place_order(order)
        assert result.success is False
        assert result.error_code == "NOT_CONNECTED"

    def test_broker_get_balance(self) -> None:
        """测试查询余额"""
        broker = MockBroker()
        broker.connect()

        result = broker.get_balance("USDT")
        assert result.success is True
        assert result.data.asset == "USDT"
        assert result.data.free == Decimal("10000")
