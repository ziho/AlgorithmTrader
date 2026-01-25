"""
头寸管理

职责:
- 头寸对象定义
- 持仓跟踪
- 盈亏计算
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class PositionSide(Enum):
    """持仓方向"""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class OrderSide(Enum):
    """订单方向"""

    BUY = "buy"
    SELL = "sell"


@dataclass
class Position:
    """
    头寸对象

    跟踪单个品种的持仓状态，支持:
    - 多空双向持仓
    - 均价计算
    - 实现盈亏跟踪
    - 未实现盈亏计算
    """

    symbol: str
    quantity: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """确保数值类型正确"""
        if not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))
        if not isinstance(self.avg_price, Decimal):
            self.avg_price = Decimal(str(self.avg_price))
        if not isinstance(self.realized_pnl, Decimal):
            self.realized_pnl = Decimal(str(self.realized_pnl))

    @property
    def side(self) -> PositionSide:
        """获取持仓方向"""
        if self.quantity > 0:
            return PositionSide.LONG
        elif self.quantity < 0:
            return PositionSide.SHORT
        else:
            return PositionSide.FLAT

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    @property
    def abs_quantity(self) -> Decimal:
        """持仓数量绝对值"""
        return abs(self.quantity)

    def market_value(self, price: Decimal) -> Decimal:
        """
        计算市值

        Args:
            price: 当前市场价格

        Returns:
            市值（可为负数表示空头）
        """
        return self.quantity * price

    def unrealized_pnl(self, price: Decimal) -> Decimal:
        """
        计算未实现盈亏

        Args:
            price: 当前市场价格

        Returns:
            未实现盈亏
        """
        if self.is_flat:
            return Decimal("0")
        return self.quantity * (price - self.avg_price)

    def total_pnl(self, price: Decimal) -> Decimal:
        """
        计算总盈亏（已实现 + 未实现）

        Args:
            price: 当前市场价格

        Returns:
            总盈亏
        """
        return self.realized_pnl + self.unrealized_pnl(price)

    def update(
        self,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        timestamp: datetime | None = None,
    ) -> Decimal:
        """
        更新持仓

        Args:
            side: 订单方向
            quantity: 成交数量（正数）
            price: 成交价格
            timestamp: 成交时间

        Returns:
            本次成交实现的盈亏
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        realized = Decimal("0")
        signed_qty = quantity if side == OrderSide.BUY else -quantity

        if self.is_flat:
            # 开仓
            self.quantity = signed_qty
            self.avg_price = price
            if timestamp and self.created_at is None:
                self.created_at = timestamp
        elif (self.is_long and side == OrderSide.BUY) or (
            self.is_short and side == OrderSide.SELL
        ):
            # 加仓：更新均价
            total_value = self.quantity * self.avg_price + signed_qty * price
            self.quantity += signed_qty
            if self.quantity != 0:
                self.avg_price = abs(total_value / self.quantity)
        else:
            # 减仓或反向开仓
            if abs(signed_qty) <= abs(self.quantity):
                # 部分/全部平仓
                realized = quantity * (price - self.avg_price)
                if self.is_short:
                    realized = -realized
                self.quantity += signed_qty
                if self.is_flat:
                    self.avg_price = Decimal("0")
            else:
                # 反向开仓
                close_qty = abs(self.quantity)
                realized = close_qty * (price - self.avg_price)
                if self.is_short:
                    realized = -realized
                remain_qty = quantity - close_qty
                self.quantity = remain_qty if side == OrderSide.BUY else -remain_qty
                self.avg_price = price
                if timestamp:
                    self.created_at = timestamp

        self.realized_pnl += realized
        if timestamp:
            self.updated_at = timestamp

        return realized

    def close(self, price: Decimal, timestamp: datetime | None = None) -> Decimal:
        """
        全部平仓

        Args:
            price: 平仓价格
            timestamp: 平仓时间

        Returns:
            实现盈亏
        """
        if self.is_flat:
            return Decimal("0")

        side = OrderSide.SELL if self.is_long else OrderSide.BUY
        return self.update(side, self.abs_quantity, price, timestamp)

    def copy(self) -> "Position":
        """创建持仓副本"""
        return Position(
            symbol=self.symbol,
            quantity=self.quantity,
            avg_price=self.avg_price,
            realized_pnl=self.realized_pnl,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "quantity": str(self.quantity),
            "avg_price": str(self.avg_price),
            "realized_pnl": str(self.realized_pnl),
            "side": self.side.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class PositionSnapshot:
    """持仓快照（用于记录历史状态）"""

    timestamp: datetime
    positions: dict[str, Position] = field(default_factory=dict)
    total_value: Decimal = Decimal("0")
    cash: Decimal = Decimal("0")

    @property
    def equity(self) -> Decimal:
        """总权益"""
        return self.total_value + self.cash

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "total_value": str(self.total_value),
            "cash": str(self.cash),
            "equity": str(self.equity),
        }


class PositionTracker:
    """
    持仓跟踪器

    管理多品种持仓，提供:
    - 持仓状态查询
    - 持仓更新
    - 快照生成
    """

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._snapshots: list[PositionSnapshot] = []

    @property
    def positions(self) -> dict[str, Position]:
        """获取所有持仓"""
        return self._positions.copy()

    @property
    def active_positions(self) -> dict[str, Position]:
        """获取所有非空仓持仓"""
        return {k: v for k, v in self._positions.items() if not v.is_flat}

    def get_position(self, symbol: str) -> Position:
        """获取或创建持仓"""
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol)
        return self._positions[symbol]

    def has_position(self, symbol: str) -> bool:
        """检查是否有持仓"""
        return symbol in self._positions and not self._positions[symbol].is_flat

    def update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        timestamp: datetime | None = None,
    ) -> Decimal:
        """
        更新持仓

        Args:
            symbol: 品种代码
            side: 订单方向
            quantity: 成交数量
            price: 成交价格
            timestamp: 成交时间

        Returns:
            实现盈亏
        """
        position = self.get_position(symbol)
        return position.update(side, quantity, price, timestamp)

    def close_position(
        self,
        symbol: str,
        price: Decimal,
        timestamp: datetime | None = None,
    ) -> Decimal:
        """
        平仓

        Args:
            symbol: 品种代码
            price: 平仓价格
            timestamp: 平仓时间

        Returns:
            实现盈亏
        """
        if symbol not in self._positions:
            return Decimal("0")
        return self._positions[symbol].close(price, timestamp)

    def close_all(
        self,
        prices: dict[str, Decimal],
        timestamp: datetime | None = None,
    ) -> Decimal:
        """
        平掉所有持仓

        Args:
            prices: 各品种价格
            timestamp: 平仓时间

        Returns:
            总实现盈亏
        """
        total_realized = Decimal("0")
        for symbol, position in self._positions.items():
            if symbol in prices and not position.is_flat:
                total_realized += position.close(prices[symbol], timestamp)
        return total_realized

    def calculate_value(self, prices: dict[str, Decimal]) -> Decimal:
        """
        计算持仓总市值

        Args:
            prices: 各品种价格

        Returns:
            总市值
        """
        total = Decimal("0")
        for symbol, position in self._positions.items():
            if symbol in prices:
                total += position.market_value(prices[symbol])
        return total

    def calculate_unrealized_pnl(self, prices: dict[str, Decimal]) -> Decimal:
        """
        计算未实现盈亏

        Args:
            prices: 各品种价格

        Returns:
            总未实现盈亏
        """
        total = Decimal("0")
        for symbol, position in self._positions.items():
            if symbol in prices:
                total += position.unrealized_pnl(prices[symbol])
        return total

    def calculate_realized_pnl(self) -> Decimal:
        """计算已实现盈亏"""
        return sum(
            (p.realized_pnl for p in self._positions.values()),
            start=Decimal("0"),
        )

    def take_snapshot(
        self,
        timestamp: datetime,
        prices: dict[str, Decimal],
        cash: Decimal,
    ) -> PositionSnapshot:
        """
        生成持仓快照

        Args:
            timestamp: 快照时间
            prices: 各品种价格
            cash: 现金余额

        Returns:
            持仓快照
        """
        snapshot = PositionSnapshot(
            timestamp=timestamp,
            positions={k: v.copy() for k, v in self._positions.items()},
            total_value=self.calculate_value(prices),
            cash=cash,
        )
        self._snapshots.append(snapshot)
        return snapshot

    def get_snapshots(self) -> list[PositionSnapshot]:
        """获取所有快照"""
        return self._snapshots.copy()

    def reset(self) -> None:
        """重置跟踪器"""
        self._positions.clear()
        self._snapshots.clear()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "positions": {k: v.to_dict() for k, v in self._positions.items()},
            "active_count": len(self.active_positions),
            "total_realized_pnl": str(self.calculate_realized_pnl()),
        }
