"""
仓位分配器

职责:
- 从信号到目标持仓转换
- 权重计算
- 仓位调整生成
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from src.portfolio.position import OrderSide, Position, PositionSide


class AllocationMethod(Enum):
    """分配方法"""

    EQUAL_WEIGHT = "equal_weight"  # 等权重
    SIGNAL_WEIGHT = "signal_weight"  # 按信号强度
    RISK_PARITY = "risk_parity"  # 风险平价
    FIXED_AMOUNT = "fixed_amount"  # 固定金额


@dataclass
class TargetPosition:
    """目标持仓"""

    symbol: str
    side: PositionSide
    quantity: Decimal
    weight: Decimal = Decimal("0")  # 目标权重（相对于总权益）
    price: Decimal = Decimal("0")  # 参考价格
    reason: str = ""

    def __post_init__(self) -> None:
        """确保数值类型正确"""
        if not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))
        if not isinstance(self.weight, Decimal):
            self.weight = Decimal(str(self.weight))
        if not isinstance(self.price, Decimal):
            self.price = Decimal(str(self.price))

    @property
    def signed_quantity(self) -> Decimal:
        """带符号的数量"""
        if self.side == PositionSide.LONG:
            return self.quantity
        elif self.side == PositionSide.SHORT:
            return -self.quantity
        else:
            return Decimal("0")

    @property
    def notional(self) -> Decimal:
        """名义价值"""
        return self.quantity * self.price

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "weight": str(self.weight),
            "price": str(self.price),
            "reason": self.reason,
        }


@dataclass
class OrderIntent:
    """订单意图（从目标持仓差分计算得出）"""

    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal = Decimal("0")  # 参考价格
    reason: str = ""
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        """确保数值类型正确"""
        if not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))
        if not isinstance(self.price, Decimal):
            self.price = Decimal(str(self.price))

    @property
    def notional(self) -> Decimal:
        """名义价值"""
        return self.quantity * self.price

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class AllocationConfig:
    """分配器配置"""

    method: AllocationMethod = AllocationMethod.EQUAL_WEIGHT
    max_position_weight: Decimal = Decimal("0.2")  # 单品种最大权重
    min_trade_notional: Decimal = Decimal("10")  # 最小交易金额
    round_lot: Decimal = Decimal("0.0001")  # 最小交易单位

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "max_position_weight": str(self.max_position_weight),
            "min_trade_notional": str(self.min_trade_notional),
            "round_lot": str(self.round_lot),
        }


@dataclass
class Signal:
    """交易信号"""

    symbol: str
    value: Decimal  # 信号值：正数做多，负数做空，0平仓
    strength: Decimal = Decimal("1")  # 信号强度（用于加权分配）
    timestamp: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            self.value = Decimal(str(self.value))
        if not isinstance(self.strength, Decimal):
            self.strength = Decimal(str(self.strength))

    @property
    def side(self) -> PositionSide:
        """信号方向"""
        if self.value > 0:
            return PositionSide.LONG
        elif self.value < 0:
            return PositionSide.SHORT
        else:
            return PositionSide.FLAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "value": str(self.value),
            "strength": str(self.strength),
            "side": self.side.value,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metadata": self.metadata,
        }


class PositionAllocator:
    """
    仓位分配器

    将信号转换为目标持仓或订单意图
    """

    def __init__(self, config: AllocationConfig | None = None):
        self.config = config or AllocationConfig()

    def signals_to_targets(
        self,
        signals: list[Signal],
        prices: dict[str, Decimal],
        equity: Decimal,
    ) -> list[TargetPosition]:
        """
        将信号转换为目标持仓

        Args:
            signals: 信号列表
            prices: 各品种当前价格
            equity: 当前总权益

        Returns:
            目标持仓列表
        """
        if not signals or equity <= 0:
            return []

        targets: list[TargetPosition] = []

        if self.config.method == AllocationMethod.EQUAL_WEIGHT:
            targets = self._allocate_equal_weight(signals, prices, equity)
        elif self.config.method == AllocationMethod.SIGNAL_WEIGHT:
            targets = self._allocate_signal_weight(signals, prices, equity)
        elif self.config.method == AllocationMethod.FIXED_AMOUNT:
            targets = self._allocate_fixed_amount(signals, prices, equity)
        else:
            # 默认等权重
            targets = self._allocate_equal_weight(signals, prices, equity)

        return targets

    def _allocate_equal_weight(
        self,
        signals: list[Signal],
        prices: dict[str, Decimal],
        equity: Decimal,
    ) -> list[TargetPosition]:
        """等权重分配"""
        active_signals = [s for s in signals if s.side != PositionSide.FLAT]

        if not active_signals:
            # 所有信号都是平仓
            return [
                TargetPosition(
                    symbol=s.symbol,
                    side=PositionSide.FLAT,
                    quantity=Decimal("0"),
                    weight=Decimal("0"),
                    price=prices.get(s.symbol, Decimal("0")),
                    reason="signal_flat",
                )
                for s in signals
            ]

        # 计算每个品种的权重
        weight_per_symbol = min(
            Decimal("1") / len(active_signals),
            self.config.max_position_weight,
        )

        targets = []
        for signal in signals:
            price = prices.get(signal.symbol, Decimal("0"))
            if price <= 0:
                continue

            if signal.side == PositionSide.FLAT:
                targets.append(
                    TargetPosition(
                        symbol=signal.symbol,
                        side=PositionSide.FLAT,
                        quantity=Decimal("0"),
                        weight=Decimal("0"),
                        price=price,
                        reason="signal_flat",
                    )
                )
            else:
                notional = equity * weight_per_symbol
                quantity = self._round_quantity(notional / price)

                targets.append(
                    TargetPosition(
                        symbol=signal.symbol,
                        side=signal.side,
                        quantity=quantity,
                        weight=weight_per_symbol,
                        price=price,
                        reason=f"equal_weight_{signal.side.value}",
                    )
                )

        return targets

    def _allocate_signal_weight(
        self,
        signals: list[Signal],
        prices: dict[str, Decimal],
        equity: Decimal,
    ) -> list[TargetPosition]:
        """按信号强度分配"""
        active_signals = [s for s in signals if s.side != PositionSide.FLAT]

        if not active_signals:
            return [
                TargetPosition(
                    symbol=s.symbol,
                    side=PositionSide.FLAT,
                    quantity=Decimal("0"),
                    weight=Decimal("0"),
                    price=prices.get(s.symbol, Decimal("0")),
                    reason="signal_flat",
                )
                for s in signals
            ]

        # 计算总信号强度
        total_strength = sum(
            (abs(s.value) * s.strength for s in active_signals),
            start=Decimal("0"),
        )

        if total_strength <= 0:
            total_strength = Decimal("1")

        targets = []
        for signal in signals:
            price = prices.get(signal.symbol, Decimal("0"))
            if price <= 0:
                continue

            if signal.side == PositionSide.FLAT:
                targets.append(
                    TargetPosition(
                        symbol=signal.symbol,
                        side=PositionSide.FLAT,
                        quantity=Decimal("0"),
                        weight=Decimal("0"),
                        price=price,
                        reason="signal_flat",
                    )
                )
            else:
                # 按信号强度分配权重
                raw_weight = (abs(signal.value) * signal.strength) / total_strength
                weight = min(raw_weight, self.config.max_position_weight)

                notional = equity * weight
                quantity = self._round_quantity(notional / price)

                targets.append(
                    TargetPosition(
                        symbol=signal.symbol,
                        side=signal.side,
                        quantity=quantity,
                        weight=weight,
                        price=price,
                        reason=f"signal_weight_{signal.side.value}",
                    )
                )

        return targets

    def _allocate_fixed_amount(
        self,
        signals: list[Signal],
        prices: dict[str, Decimal],
        equity: Decimal,  # noqa: ARG002
    ) -> list[TargetPosition]:
        """固定金额分配（使用信号值作为金额）"""
        targets = []

        for signal in signals:
            price = prices.get(signal.symbol, Decimal("0"))
            if price <= 0:
                continue

            if signal.side == PositionSide.FLAT:
                targets.append(
                    TargetPosition(
                        symbol=signal.symbol,
                        side=PositionSide.FLAT,
                        quantity=Decimal("0"),
                        weight=Decimal("0"),
                        price=price,
                        reason="signal_flat",
                    )
                )
            else:
                notional = abs(signal.value)
                quantity = self._round_quantity(notional / price)

                targets.append(
                    TargetPosition(
                        symbol=signal.symbol,
                        side=signal.side,
                        quantity=quantity,
                        weight=Decimal("0"),  # 固定金额模式不计算权重
                        price=price,
                        reason=f"fixed_amount_{signal.side.value}",
                    )
                )

        return targets

    def targets_to_orders(
        self,
        targets: list[TargetPosition],
        current_positions: dict[str, Position],
        timestamp: datetime | None = None,
    ) -> list[OrderIntent]:
        """
        将目标持仓转换为订单意图

        Args:
            targets: 目标持仓列表
            current_positions: 当前持仓
            timestamp: 时间戳

        Returns:
            订单意图列表
        """
        orders = []

        for target in targets:
            current = current_positions.get(target.symbol)
            current_qty = current.quantity if current else Decimal("0")

            target_qty = target.signed_quantity
            diff = target_qty - current_qty

            if abs(diff) < self.config.round_lot:
                continue

            # 检查最小交易金额
            if target.price > 0:
                trade_notional = abs(diff) * target.price
                if trade_notional < self.config.min_trade_notional:
                    continue

            side = OrderSide.BUY if diff > 0 else OrderSide.SELL
            quantity = self._round_quantity(abs(diff))

            if quantity > 0:
                orders.append(
                    OrderIntent(
                        symbol=target.symbol,
                        side=side,
                        quantity=quantity,
                        price=target.price,
                        reason=target.reason,
                        timestamp=timestamp,
                    )
                )

        return orders

    def _round_quantity(self, quantity: Decimal) -> Decimal:
        """按最小交易单位取整"""
        if self.config.round_lot <= 0:
            return quantity
        return (quantity // self.config.round_lot) * self.config.round_lot


class WeightCalculator:
    """
    权重计算器

    提供各种权重计算方法
    """

    @staticmethod
    def equal_weight(n: int) -> list[Decimal]:
        """等权重"""
        if n <= 0:
            return []
        weight = Decimal("1") / n
        return [weight] * n

    @staticmethod
    def signal_weight(signals: list[Decimal]) -> list[Decimal]:
        """按信号值分配权重"""
        if not signals:
            return []

        total = sum((abs(s) for s in signals), start=Decimal("0"))
        if total <= 0:
            return WeightCalculator.equal_weight(len(signals))

        return [abs(s) / total for s in signals]

    @staticmethod
    def normalize_weights(
        weights: list[Decimal],
        max_weight: Decimal = Decimal("1"),
    ) -> list[Decimal]:
        """归一化权重"""
        if not weights:
            return []

        total = sum(weights, start=Decimal("0"))
        if total <= 0:
            return WeightCalculator.equal_weight(len(weights))

        normalized = [w / total for w in weights]

        # 限制最大权重
        if max_weight < Decimal("1"):
            capped = [min(w, max_weight) for w in normalized]
            # 重新归一化
            capped_total = sum(capped, start=Decimal("0"))
            if capped_total > 0:
                normalized = [w / capped_total for w in capped]

        return normalized

    @staticmethod
    def rebalance_weights(
        current_weights: dict[str, Decimal],
        target_weights: dict[str, Decimal],
        threshold: Decimal = Decimal("0.05"),
    ) -> dict[str, Decimal]:
        """
        计算需要调整的权重

        只有当偏差超过阈值时才调整

        Args:
            current_weights: 当前权重
            target_weights: 目标权重
            threshold: 调整阈值

        Returns:
            需要调整的权重差
        """
        adjustments: dict[str, Decimal] = {}

        # 所有涉及的品种
        all_symbols = set(current_weights.keys()) | set(target_weights.keys())

        for symbol in all_symbols:
            current = current_weights.get(symbol, Decimal("0"))
            target = target_weights.get(symbol, Decimal("0"))
            diff = target - current

            if abs(diff) >= threshold:
                adjustments[symbol] = diff

        return adjustments
