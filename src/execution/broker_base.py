"""
Broker 抽象基类

接口:
- place_order(): 下单
- cancel_order(): 撤单
- query_order(): 查询订单
- get_balance(): 查询余额
- get_positions(): 查询持仓

设计原则:
- 统一接口，不同交易所/券商实现
- 支持同步和异步调用
- 网络失败重试与限频
- 订单状态一致性
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from src.core.events import OrderEvent, OrderSide, OrderStatus, OrderType


class BrokerType(str, Enum):
    """Broker 类型"""

    OKX_SPOT = "okx_spot"
    OKX_SWAP = "okx_swap"
    IBKR = "ibkr"
    PAPER = "paper"  # 模拟交易


@dataclass
class Order:
    """
    订单数据结构

    统一的订单表示，支持不同交易所
    """

    # 核心字段
    symbol: str  # 交易对，如 "BTC/USDT"
    side: OrderSide  # 买/卖
    order_type: OrderType  # 市价/限价
    quantity: Decimal  # 数量
    price: Decimal | None = None  # 限价单价格

    # 订单标识
    client_order_id: str = field(default_factory=lambda: str(uuid4()))
    exchange_order_id: str = ""

    # 状态
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: Decimal = Decimal("0")
    filled_avg_price: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    commission_asset: str = ""

    # 元信息
    strategy_name: str = ""
    broker_type: BrokerType = BrokerType.PAPER
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # 错误信息
    error_code: str = ""
    error_message: str = ""

    @property
    def is_open(self) -> bool:
        """订单是否还在挂单中"""
        return self.status in (
            OrderStatus.NEW,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIAL,
        )

    @property
    def is_filled(self) -> bool:
        """订单是否已完全成交"""
        return self.status == OrderStatus.FILLED

    @property
    def is_cancelled(self) -> bool:
        """订单是否已撤销"""
        return self.status == OrderStatus.CANCELLED

    @property
    def is_rejected(self) -> bool:
        """订单是否被拒绝"""
        return self.status == OrderStatus.REJECTED

    @property
    def remaining_quantity(self) -> Decimal:
        """剩余未成交数量"""
        return self.quantity - self.filled_quantity

    @property
    def filled_value(self) -> Decimal:
        """已成交金额"""
        return self.filled_quantity * self.filled_avg_price

    def to_order_event(self) -> OrderEvent:
        """转换为 OrderEvent"""
        return OrderEvent(
            symbol=self.symbol,
            side=self.side,
            order_type=self.order_type,
            quantity=self.quantity,
            price=self.price,
            status=self.status,
            client_order_id=self.client_order_id,
            exchange_order_id=self.exchange_order_id,
            strategy_name=self.strategy_name,
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": str(self.quantity),
            "price": str(self.price) if self.price else None,
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "status": self.status.value,
            "filled_quantity": str(self.filled_quantity),
            "filled_avg_price": str(self.filled_avg_price),
            "commission": str(self.commission),
            "commission_asset": self.commission_asset,
            "strategy_name": self.strategy_name,
            "broker_type": self.broker_type.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass
class Balance:
    """
    账户余额

    某一币种/资产的余额
    """

    asset: str  # 币种/资产名称
    free: Decimal = Decimal("0")  # 可用余额
    locked: Decimal = Decimal("0")  # 冻结余额

    @property
    def total(self) -> Decimal:
        """总余额"""
        return self.free + self.locked

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "asset": self.asset,
            "free": str(self.free),
            "locked": str(self.locked),
            "total": str(self.total),
        }


@dataclass
class Position:
    """
    持仓

    某一交易对的持仓信息
    """

    symbol: str  # 交易对
    side: str = "long"  # "long" 或 "short"
    quantity: Decimal = Decimal("0")  # 持仓数量
    avg_price: Decimal = Decimal("0")  # 持仓均价
    unrealized_pnl: Decimal = Decimal("0")  # 未实现盈亏
    leverage: int = 1  # 杠杆倍数 (现货为1)

    @property
    def value(self) -> Decimal:
        """持仓价值"""
        return self.quantity * self.avg_price

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": str(self.quantity),
            "avg_price": str(self.avg_price),
            "value": str(self.value),
            "unrealized_pnl": str(self.unrealized_pnl),
            "leverage": self.leverage,
        }


@dataclass
class BrokerResult:
    """
    Broker 操作结果

    统一的操作结果包装
    """

    success: bool
    data: Any = None
    error_code: str = ""
    error_message: str = ""

    @classmethod
    def ok(cls, data: Any = None) -> "BrokerResult":
        """创建成功结果"""
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error_code: str, error_message: str) -> "BrokerResult":
        """创建失败结果"""
        return cls(
            success=False,
            error_code=error_code,
            error_message=error_message,
        )


class BrokerBase(ABC):
    """
    Broker 抽象基类

    所有交易所/券商适配器必须继承此类

    设计原则:
    - 统一接口
    - 同步方法 (中低频足够)
    - 内置重试与限频
    - 订单状态一致性保证
    """

    def __init__(
        self,
        broker_type: BrokerType = BrokerType.PAPER,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        初始化 Broker

        Args:
            broker_type: Broker 类型
            max_retries: 最大重试次数
            retry_delay: 重试间隔 (秒)
        """
        self.broker_type = broker_type
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected

    # ==================== 连接管理 ====================

    @abstractmethod
    def connect(self) -> BrokerResult:
        """
        连接到交易所/券商

        Returns:
            BrokerResult: 连接结果
        """

    @abstractmethod
    def disconnect(self) -> BrokerResult:
        """
        断开连接

        Returns:
            BrokerResult: 断开结果
        """

    # ==================== 订单操作 ====================

    @abstractmethod
    def place_order(self, order: Order) -> BrokerResult:
        """
        下单

        Args:
            order: 订单对象

        Returns:
            BrokerResult: 下单结果，成功时 data 为更新后的 Order
        """

    @abstractmethod
    def cancel_order(
        self,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BrokerResult:
        """
        撤单

        Args:
            symbol: 交易对
            client_order_id: 客户端订单ID
            exchange_order_id: 交易所订单ID

        Returns:
            BrokerResult: 撤单结果
        """

    @abstractmethod
    def query_order(
        self,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BrokerResult:
        """
        查询订单状态

        Args:
            symbol: 交易对
            client_order_id: 客户端订单ID
            exchange_order_id: 交易所订单ID

        Returns:
            BrokerResult: 查询结果，成功时 data 为 Order
        """

    @abstractmethod
    def get_open_orders(self, symbol: str | None = None) -> BrokerResult:
        """
        获取当前挂单

        Args:
            symbol: 交易对，None 表示所有

        Returns:
            BrokerResult: 成功时 data 为 list[Order]
        """

    # ==================== 账户查询 ====================

    @abstractmethod
    def get_balance(self, asset: str | None = None) -> BrokerResult:
        """
        查询余额

        Args:
            asset: 币种/资产名称，None 表示所有

        Returns:
            BrokerResult: 成功时 data 为 Balance 或 list[Balance]
        """

    @abstractmethod
    def get_positions(self, symbol: str | None = None) -> BrokerResult:
        """
        查询持仓

        Args:
            symbol: 交易对，None 表示所有

        Returns:
            BrokerResult: 成功时 data 为 Position 或 list[Position]
        """

    # ==================== 市场数据 (可选) ====================

    def get_ticker(self, symbol: str) -> BrokerResult:  # noqa: ARG002
        """
        获取当前行情

        Args:
            symbol: 交易对

        Returns:
            BrokerResult: 成功时 data 为行情数据
        """
        return BrokerResult.fail("NOT_IMPLEMENTED", "get_ticker not implemented")

    # ==================== 辅助方法 ====================

    def create_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        strategy_name: str = "",
    ) -> Order:
        """创建市价单"""
        return Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            strategy_name=strategy_name,
            broker_type=self.broker_type,
        )

    def create_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        strategy_name: str = "",
    ) -> Order:
        """创建限价单"""
        return Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            broker_type=self.broker_type,
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(type={self.broker_type.value}, connected={self._connected})"
        )


# 导出
__all__ = [
    "BrokerType",
    "Order",
    "Balance",
    "Position",
    "BrokerResult",
    "BrokerBase",
]
