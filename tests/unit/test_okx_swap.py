"""
OKX 永续合约 Broker 测试
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.core.events import OrderSide, OrderStatus, OrderType
from src.execution.adapters.okx_swap import (
    MarginMode,
    OKXSwapBroker,
    PositionSide,
    SwapPosition,
)
from src.execution.broker_base import BrokerType, Order


class TestOKXSwapBroker:
    """OKXSwapBroker 测试"""

    def test_broker_creation(self) -> None:
        """测试创建 broker"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
            sandbox=True,
        )

        assert broker.broker_type == BrokerType.OKX_SWAP
        assert broker.is_connected is False
        assert broker._default_leverage == 10
        assert broker._margin_mode == MarginMode.CROSS

    def test_broker_with_custom_leverage(self) -> None:
        """测试自定义杠杆"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
            default_leverage=20,
            margin_mode=MarginMode.ISOLATED,
        )

        assert broker._default_leverage == 20
        assert broker._margin_mode == MarginMode.ISOLATED

    def test_convert_symbol(self) -> None:
        """测试交易对转换"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )

        # 基础格式
        assert broker._convert_symbol("BTC/USDT") == "BTC/USDT:USDT"
        assert broker._convert_symbol("ETH/USDT") == "ETH/USDT:USDT"

        # 已经是永续格式
        assert broker._convert_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"

        # 带连字符格式
        assert broker._convert_symbol("BTC-USDT") == "BTC/USDT:USDT"

    def test_parse_order_status(self) -> None:
        """测试订单状态解析"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )

        assert broker._parse_order_status("open") == OrderStatus.SUBMITTED
        assert broker._parse_order_status("closed") == OrderStatus.FILLED
        assert broker._parse_order_status("canceled") == OrderStatus.CANCELLED
        assert broker._parse_order_status("cancelled") == OrderStatus.CANCELLED
        assert broker._parse_order_status("rejected") == OrderStatus.REJECTED
        assert broker._parse_order_status("unknown") == OrderStatus.NEW

    def test_parse_order_side(self) -> None:
        """测试订单方向解析"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )

        assert broker._parse_order_side("buy") == OrderSide.BUY
        assert broker._parse_order_side("BUY") == OrderSide.BUY
        assert broker._parse_order_side("sell") == OrderSide.SELL
        assert broker._parse_order_side("SELL") == OrderSide.SELL

    def test_parse_order_type(self) -> None:
        """测试订单类型解析"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )

        assert broker._parse_order_type("limit") == OrderType.LIMIT
        assert broker._parse_order_type("LIMIT") == OrderType.LIMIT
        assert broker._parse_order_type("market") == OrderType.MARKET
        assert broker._parse_order_type("MARKET") == OrderType.MARKET

    def test_not_connected_operations(self) -> None:
        """测试未连接时的操作"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )

        order = Order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        result = broker.place_order(order)
        assert result.success is False
        assert result.error_code == "NOT_CONNECTED"

        result = broker.cancel_order("BTC/USDT", exchange_order_id="123")
        assert result.success is False
        assert result.error_code == "NOT_CONNECTED"

        result = broker.get_balance()
        assert result.success is False
        assert result.error_code == "NOT_CONNECTED"

        result = broker.set_leverage("BTC/USDT", 20)
        assert result.success is False
        assert result.error_code == "NOT_CONNECTED"

    def test_cancel_order_without_id(self) -> None:
        """测试没有 ID 的撤单"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )
        broker._connected = True
        broker._exchange = MagicMock()

        result = broker.cancel_order("BTC/USDT")
        assert result.success is False
        assert result.error_code == "INVALID_PARAMS"

    def test_disconnect(self) -> None:
        """测试断开连接"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )
        broker._connected = True
        broker._exchange = MagicMock()

        result = broker.disconnect()
        assert result.success is True
        assert broker.is_connected is False
        assert broker._exchange is None


class TestSwapPosition:
    """SwapPosition 测试"""

    def test_position_creation(self) -> None:
        """测试持仓创建"""
        pos = SwapPosition(
            symbol="BTC/USDT:USDT",
            side=PositionSide.LONG,
            quantity=Decimal("10"),
            notional=Decimal("500000"),
            avg_price=Decimal("50000"),
            mark_price=Decimal("51000"),
            unrealized_pnl=Decimal("10000"),
            realized_pnl=Decimal("500"),
            leverage=10,
            margin_mode=MarginMode.CROSS,
            liquidation_price=Decimal("45000"),
            margin=Decimal("50000"),
            margin_ratio=Decimal("0.1"),
        )

        assert pos.symbol == "BTC/USDT:USDT"
        assert pos.side == PositionSide.LONG
        assert pos.quantity == Decimal("10")
        assert pos.leverage == 10

    def test_position_to_dict(self) -> None:
        """测试持仓转换为字典"""
        pos = SwapPosition(
            symbol="BTC/USDT:USDT",
            side=PositionSide.LONG,
            quantity=Decimal("10"),
            notional=Decimal("500000"),
            avg_price=Decimal("50000"),
            mark_price=Decimal("51000"),
            unrealized_pnl=Decimal("10000"),
            realized_pnl=Decimal("500"),
            leverage=10,
            margin_mode=MarginMode.CROSS,
            liquidation_price=Decimal("45000"),
            margin=Decimal("50000"),
            margin_ratio=Decimal("0.1"),
        )

        d = pos.to_dict()
        assert d["symbol"] == "BTC/USDT:USDT"
        assert d["side"] == "long"
        assert d["leverage"] == 10
        assert d["margin_mode"] == "cross"

    def test_position_to_base_position(self) -> None:
        """测试转换为基础 Position"""
        pos = SwapPosition(
            symbol="BTC/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("5"),
            notional=Decimal("250000"),
            avg_price=Decimal("50000"),
            mark_price=Decimal("49000"),
            unrealized_pnl=Decimal("5000"),
            realized_pnl=Decimal("100"),
            leverage=20,
            margin_mode=MarginMode.ISOLATED,
            liquidation_price=Decimal("52000"),
            margin=Decimal("12500"),
            margin_ratio=Decimal("0.05"),
        )

        base_pos = pos.to_position()
        assert base_pos.symbol == "BTC/USDT:USDT"
        assert base_pos.side == "short"
        assert base_pos.quantity == Decimal("5")
        assert base_pos.leverage == 20


class TestMarginModeAndPositionSide:
    """MarginMode 和 PositionSide 枚举测试"""

    def test_margin_mode_values(self) -> None:
        """测试保证金模式值"""
        assert MarginMode.CROSS.value == "cross"
        assert MarginMode.ISOLATED.value == "isolated"

    def test_position_side_values(self) -> None:
        """测试持仓方向值"""
        assert PositionSide.LONG.value == "long"
        assert PositionSide.SHORT.value == "short"
        assert PositionSide.NET.value == "net"


class TestLiquidationPriceCalculation:
    """强平价格计算测试"""

    def test_long_liquidation_price(self) -> None:
        """测试多头强平价格计算"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )

        # 10 倍杠杆，开仓价 50000
        liq_price = broker.calculate_liquidation_price(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            quantity=Decimal("1"),
            leverage=10,
        )

        # 多头强平价格应该低于开仓价
        assert liq_price < Decimal("50000")
        # 大约是 45250 左右 (50000 * (1 - 0.1 + 0.005))
        assert Decimal("45000") < liq_price < Decimal("46000")

    def test_short_liquidation_price(self) -> None:
        """测试空头强平价格计算"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )

        # 10 倍杠杆，开仓价 50000
        liq_price = broker.calculate_liquidation_price(
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            entry_price=Decimal("50000"),
            quantity=Decimal("1"),
            leverage=10,
        )

        # 空头强平价格应该高于开仓价
        assert liq_price > Decimal("50000")
        # 大约是 54750 左右 (50000 * (1 + 0.1 - 0.005))
        assert Decimal("54000") < liq_price < Decimal("55500")

    def test_higher_leverage_lower_margin(self) -> None:
        """测试更高杠杆导致更接近的强平价格"""
        broker = OKXSwapBroker(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_pass",
        )

        liq_10x = broker.calculate_liquidation_price(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            quantity=Decimal("1"),
            leverage=10,
        )

        liq_20x = broker.calculate_liquidation_price(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            quantity=Decimal("1"),
            leverage=20,
        )

        # 20 倍杠杆的强平价格应该更接近开仓价
        assert liq_20x > liq_10x
