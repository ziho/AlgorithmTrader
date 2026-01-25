"""
事件模型定义

事件驱动架构的核心事件类型:
- BarEvent: K线事件
- SignalEvent: 策略信号事件
- OrderEvent: 订单事件
- FillEvent: 成交事件

设计原则:
- 事件不可变 (frozen dataclass)
- 包含时间戳与来源标识
- 支持序列化
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class EventType(str, Enum):
    """事件类型枚举"""

    BAR = "bar"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"


class OrderSide(str, Enum):
    """订单方向"""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """订单类型"""

    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    """订单状态"""

    NEW = "new"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class SignalDirection(str, Enum):
    """信号方向"""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"  # 平仓


@dataclass(frozen=True)
class Event:
    """事件基类"""

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": str(self.event_id),
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.__class__.__name__,
        }


@dataclass(frozen=True)
class BarEvent(Event):
    """
    K线事件

    当新的 K 线完成时触发
    """

    symbol: str = ""  # 交易对，如 "OKX:BTC/USDT"
    timeframe: str = ""  # 时间框架，如 "15m", "1h"
    open: Decimal = Decimal("0")
    high: Decimal = Decimal("0")
    low: Decimal = Decimal("0")
    close: Decimal = Decimal("0")
    volume: Decimal = Decimal("0")
    bar_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        base = super().to_dict()
        base.update(
            {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "open": str(self.open),
                "high": str(self.high),
                "low": str(self.low),
                "close": str(self.close),
                "volume": str(self.volume),
                "bar_time": self.bar_time.isoformat(),
            }
        )
        return base


@dataclass(frozen=True)
class SignalEvent(Event):
    """
    策略信号事件

    由策略生成，表示交易意图
    """

    symbol: str = ""
    direction: SignalDirection = SignalDirection.FLAT
    strength: float = 0.0  # 信号强度 [0, 1]
    strategy_name: str = ""
    target_position: Decimal = Decimal("0")  # 目标持仓量
    reason: str = ""  # 信号原因说明

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        base = super().to_dict()
        base.update(
            {
                "symbol": self.symbol,
                "direction": self.direction.value,
                "strength": self.strength,
                "strategy_name": self.strategy_name,
                "target_position": str(self.target_position),
                "reason": self.reason,
            }
        )
        return base


@dataclass(frozen=True)
class OrderEvent(Event):
    """
    订单事件

    表示一个交易订单
    """

    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal = Decimal("0")
    price: Decimal | None = None  # 限价单价格
    status: OrderStatus = OrderStatus.NEW
    client_order_id: str = ""
    exchange_order_id: str = ""
    strategy_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        base = super().to_dict()
        base.update(
            {
                "symbol": self.symbol,
                "side": self.side.value,
                "order_type": self.order_type.value,
                "quantity": str(self.quantity),
                "price": str(self.price) if self.price else None,
                "status": self.status.value,
                "client_order_id": self.client_order_id,
                "exchange_order_id": self.exchange_order_id,
                "strategy_name": self.strategy_name,
            }
        )
        return base


@dataclass(frozen=True)
class FillEvent(Event):
    """
    成交事件

    订单成交后触发
    """

    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    quantity: Decimal = Decimal("0")  # 成交数量
    price: Decimal = Decimal("0")  # 成交价格
    commission: Decimal = Decimal("0")  # 手续费
    commission_asset: str = ""  # 手续费币种
    client_order_id: str = ""
    exchange_order_id: str = ""
    exchange_trade_id: str = ""

    @property
    def value(self) -> Decimal:
        """成交金额"""
        return self.quantity * self.price

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        base = super().to_dict()
        base.update(
            {
                "symbol": self.symbol,
                "side": self.side.value,
                "quantity": str(self.quantity),
                "price": str(self.price),
                "value": str(self.value),
                "commission": str(self.commission),
                "commission_asset": self.commission_asset,
                "client_order_id": self.client_order_id,
                "exchange_order_id": self.exchange_order_id,
                "exchange_trade_id": self.exchange_trade_id,
            }
        )
        return base


# 导出
__all__ = [
    "EventType",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "SignalDirection",
    "Event",
    "BarEvent",
    "SignalEvent",
    "OrderEvent",
    "FillEvent",
]
