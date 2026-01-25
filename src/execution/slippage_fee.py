"""
滑点与手续费模型

滑点模型:
- 固定点数
- 百分比

手续费模型:
- Maker/Taker 费率
- 按交易所配置
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class SlippageType(str, Enum):
    """滑点类型"""

    FIXED = "fixed"  # 固定点数
    PERCENT = "percent"  # 百分比
    VOLUME_IMPACT = "volume_impact"  # 成交量冲击（高级）


class OrderSide(str, Enum):
    """订单方向"""

    BUY = "buy"
    SELL = "sell"


@dataclass
class SlippageConfig:
    """滑点配置"""

    slippage_type: SlippageType = SlippageType.PERCENT
    value: Decimal = Decimal("0.0005")  # 默认 0.05%

    # 高级配置
    volume_impact_factor: Decimal = Decimal("0.1")  # 成交量冲击因子

    def to_dict(self) -> dict[str, Any]:
        return {
            "slippage_type": self.slippage_type.value,
            "value": str(self.value),
            "volume_impact_factor": str(self.volume_impact_factor),
        }


@dataclass
class FeeConfig:
    """手续费配置"""

    maker_rate: Decimal = Decimal("0.001")  # Maker 费率 0.1%
    taker_rate: Decimal = Decimal("0.001")  # Taker 费率 0.1%
    min_fee: Decimal = Decimal("0")  # 最小手续费

    def to_dict(self) -> dict[str, Any]:
        return {
            "maker_rate": str(self.maker_rate),
            "taker_rate": str(self.taker_rate),
            "min_fee": str(self.min_fee),
        }


# 预定义的交易所费率配置
EXCHANGE_FEE_CONFIGS: dict[str, FeeConfig] = {
    "okx": FeeConfig(
        maker_rate=Decimal("0.0008"),  # 0.08%
        taker_rate=Decimal("0.001"),  # 0.1%
    ),
    "okx_vip": FeeConfig(
        maker_rate=Decimal("0.0005"),  # 0.05%
        taker_rate=Decimal("0.0007"),  # 0.07%
    ),
    "binance": FeeConfig(
        maker_rate=Decimal("0.001"),  # 0.1%
        taker_rate=Decimal("0.001"),  # 0.1%
    ),
    "ibkr_stock": FeeConfig(
        maker_rate=Decimal("0.0001"),  # ~$0.005/股简化
        taker_rate=Decimal("0.0001"),
        min_fee=Decimal("1.0"),  # 最低$1
    ),
}


class SlippageModel(ABC):
    """滑点模型基类"""

    @abstractmethod
    def calculate_slippage(
        self,
        price: Decimal,
        quantity: Decimal,
        side: OrderSide,
        bar_volume: Decimal | None = None,
    ) -> Decimal:
        """
        计算滑点

        Args:
            price: 原始价格
            quantity: 成交数量
            side: 订单方向
            bar_volume: 当前 bar 成交量（用于成交量冲击模型）

        Returns:
            滑点后的成交价格
        """
        pass


class FixedSlippage(SlippageModel):
    """固定点数滑点"""

    def __init__(self, slippage_points: Decimal = Decimal("0.01")):
        self.slippage_points = slippage_points

    def calculate_slippage(
        self,
        price: Decimal,
        quantity: Decimal,  # noqa: ARG002
        side: OrderSide,
        bar_volume: Decimal | None = None,  # noqa: ARG002
    ) -> Decimal:
        if side == OrderSide.BUY:
            # 买入时价格向上滑点
            return price + self.slippage_points
        else:
            # 卖出时价格向下滑点
            return price - self.slippage_points


class PercentSlippage(SlippageModel):
    """百分比滑点"""

    def __init__(self, slippage_pct: Decimal = Decimal("0.0005")):
        """
        Args:
            slippage_pct: 滑点百分比，如 0.0005 表示 0.05%
        """
        self.slippage_pct = slippage_pct

    def calculate_slippage(
        self,
        price: Decimal,
        quantity: Decimal,  # noqa: ARG002
        side: OrderSide,
        bar_volume: Decimal | None = None,  # noqa: ARG002
    ) -> Decimal:
        slippage_amount = price * self.slippage_pct
        if side == OrderSide.BUY:
            return price + slippage_amount
        else:
            return price - slippage_amount


class VolumeImpactSlippage(SlippageModel):
    """
    成交量冲击滑点模型

    滑点 = base_slippage + impact_factor * (order_volume / bar_volume)
    """

    def __init__(
        self,
        base_slippage_pct: Decimal = Decimal("0.0001"),
        impact_factor: Decimal = Decimal("0.1"),
    ):
        self.base_slippage_pct = base_slippage_pct
        self.impact_factor = impact_factor

    def calculate_slippage(
        self,
        price: Decimal,
        quantity: Decimal,
        side: OrderSide,
        bar_volume: Decimal | None = None,
    ) -> Decimal:
        # 基础滑点
        slippage_pct = self.base_slippage_pct

        # 如果有成交量信息，添加成交量冲击
        if bar_volume and bar_volume > 0:
            volume_ratio = quantity / bar_volume
            slippage_pct += self.impact_factor * volume_ratio

        slippage_amount = price * slippage_pct
        if side == OrderSide.BUY:
            return price + slippage_amount
        else:
            return price - slippage_amount


class FeeModel:
    """手续费模型"""

    def __init__(self, config: FeeConfig | None = None):
        self.config = config or FeeConfig()

    def calculate_fee(
        self,
        quantity: Decimal,
        price: Decimal,
        is_maker: bool = False,
    ) -> Decimal:
        """
        计算手续费

        Args:
            quantity: 成交数量
            price: 成交价格
            is_maker: 是否为 Maker 单

        Returns:
            手续费金额
        """
        trade_value = quantity * price
        rate = self.config.maker_rate if is_maker else self.config.taker_rate
        fee = trade_value * rate

        # 应用最低手续费
        return max(fee, self.config.min_fee)

    @classmethod
    def from_exchange(cls, exchange: str) -> "FeeModel":
        """根据交易所创建费率模型"""
        config = EXCHANGE_FEE_CONFIGS.get(exchange.lower(), FeeConfig())
        return cls(config)


@dataclass
class ExecutionCost:
    """执行成本汇总"""

    # 原始价格
    original_price: Decimal

    # 滑点后价格
    filled_price: Decimal

    # 成交数量
    quantity: Decimal

    # 手续费
    commission: Decimal

    # 订单方向
    side: OrderSide

    @property
    def slippage_cost(self) -> Decimal:
        """滑点成本"""
        diff = self.filled_price - self.original_price
        if self.side == OrderSide.SELL:
            diff = -diff
        return diff * self.quantity

    @property
    def total_cost(self) -> Decimal:
        """总交易成本（滑点 + 手续费）"""
        return self.slippage_cost + self.commission

    @property
    def trade_value(self) -> Decimal:
        """成交金额"""
        return self.quantity * self.filled_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_price": str(self.original_price),
            "filled_price": str(self.filled_price),
            "quantity": str(self.quantity),
            "commission": str(self.commission),
            "side": self.side.value,
            "slippage_cost": str(self.slippage_cost),
            "total_cost": str(self.total_cost),
            "trade_value": str(self.trade_value),
        }


@dataclass
class CostCalculator:
    """
    交易成本计算器

    整合滑点模型和手续费模型
    """

    slippage_model: SlippageModel = field(
        default_factory=lambda: PercentSlippage(Decimal("0.0005"))
    )
    fee_model: FeeModel = field(default_factory=FeeModel)

    def calculate(
        self,
        price: Decimal,
        quantity: Decimal,
        side: OrderSide,
        is_maker: bool = False,
        bar_volume: Decimal | None = None,
    ) -> ExecutionCost:
        """
        计算完整的交易成本

        Args:
            price: 原始价格（通常是下一根 bar 的 open）
            quantity: 成交数量
            side: 订单方向
            is_maker: 是否为 Maker 单
            bar_volume: 当前 bar 成交量

        Returns:
            执行成本详情
        """
        # 计算滑点后价格
        filled_price = self.slippage_model.calculate_slippage(
            price=price,
            quantity=quantity,
            side=side,
            bar_volume=bar_volume,
        )

        # 计算手续费
        commission = self.fee_model.calculate_fee(
            quantity=quantity,
            price=filled_price,
            is_maker=is_maker,
        )

        return ExecutionCost(
            original_price=price,
            filled_price=filled_price,
            quantity=quantity,
            commission=commission,
            side=side,
        )

    @classmethod
    def for_exchange(
        cls,
        exchange: str,
        slippage_pct: Decimal = Decimal("0.0005"),
    ) -> "CostCalculator":
        """为特定交易所创建成本计算器"""
        return cls(
            slippage_model=PercentSlippage(slippage_pct),
            fee_model=FeeModel.from_exchange(exchange),
        )


# 导出
__all__ = [
    "SlippageType",
    "OrderSide",
    "SlippageConfig",
    "FeeConfig",
    "EXCHANGE_FEE_CONFIGS",
    "SlippageModel",
    "FixedSlippage",
    "PercentSlippage",
    "VolumeImpactSlippage",
    "FeeModel",
    "ExecutionCost",
    "CostCalculator",
]
