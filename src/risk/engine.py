"""
风控引擎

职责:
- 风控规则编排
- 规则链执行
- 拦截与告警

设计原则:
- 可插拔的规则系统
- 规则链顺序执行
- 支持软拦截(警告)和硬拦截(阻止)
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import structlog

from src.core.typing import OrderIntent, TargetPosition

logger = structlog.get_logger(__name__)


class RiskAction(str, Enum):
    """风控动作"""

    PASS = "pass"  # 通过
    WARN = "warn"  # 警告但允许
    REJECT = "reject"  # 拒绝


@dataclass
class RiskCheckResult:
    """
    风控检查结果
    """

    action: RiskAction = RiskAction.PASS
    rule_name: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def passed(self) -> bool:
        """是否通过"""
        return self.action in (RiskAction.PASS, RiskAction.WARN)

    @property
    def rejected(self) -> bool:
        """是否被拒绝"""
        return self.action == RiskAction.REJECT

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "action": self.action.value,
            "rule_name": self.rule_name,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RiskContext:
    """
    风控上下文

    包含风控检查所需的所有信息
    """

    # 账户信息
    total_equity: Decimal = Decimal("0")  # 总权益
    available_balance: Decimal = Decimal("0")  # 可用余额
    used_margin: Decimal = Decimal("0")  # 已用保证金

    # 当日统计
    daily_pnl: Decimal = Decimal("0")  # 当日盈亏
    daily_trades: int = 0  # 当日交易次数
    daily_volume: Decimal = Decimal("0")  # 当日成交量

    # 持仓信息
    positions: dict[str, Decimal] = field(default_factory=dict)  # symbol -> quantity
    position_values: dict[str, Decimal] = field(default_factory=dict)  # symbol -> value

    # 历史最高权益 (用于计算回撤)
    peak_equity: Decimal = Decimal("0")

    # 当前订单/目标
    pending_order: OrderIntent | TargetPosition | None = None

    @property
    def current_drawdown(self) -> Decimal:
        """当前回撤"""
        if self.peak_equity <= 0:
            return Decimal("0")
        return (self.peak_equity - self.total_equity) / self.peak_equity

    @property
    def total_position_value(self) -> Decimal:
        """总持仓价值"""
        return sum(self.position_values.values(), Decimal("0"))


class RiskRule:
    """
    风控规则基类
    """

    name: str = "base_rule"
    description: str = "Base risk rule"

    def check(self, context: RiskContext) -> RiskCheckResult:  # noqa: ARG002
        """
        执行风控检查

        Args:
            context: 风控上下文

        Returns:
            RiskCheckResult: 检查结果
        """
        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


class MaxDailyLossRule(RiskRule):
    """
    单日最大亏损规则
    """

    name = "max_daily_loss"
    description = "检查单日亏损是否超过限制"

    def __init__(self, max_loss_pct: float = 0.05):
        """
        Args:
            max_loss_pct: 最大亏损百分比 (相对于总权益)
        """
        self.max_loss_pct = max_loss_pct

    def check(self, context: RiskContext) -> RiskCheckResult:
        """检查单日亏损"""
        if context.total_equity <= 0:
            return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)

        daily_loss_pct = -float(context.daily_pnl / context.total_equity)

        if daily_loss_pct > self.max_loss_pct:
            return RiskCheckResult(
                action=RiskAction.REJECT,
                rule_name=self.name,
                message=(
                    f"单日亏损 {daily_loss_pct:.2%} 超过限制 {self.max_loss_pct:.2%}"
                ),
                details={
                    "daily_loss_pct": daily_loss_pct,
                    "max_loss_pct": self.max_loss_pct,
                    "daily_pnl": str(context.daily_pnl),
                },
            )

        if daily_loss_pct > self.max_loss_pct * 0.8:
            return RiskCheckResult(
                action=RiskAction.WARN,
                rule_name=self.name,
                message=(
                    f"单日亏损 {daily_loss_pct:.2%} 接近限制 {self.max_loss_pct:.2%}"
                ),
                details={
                    "daily_loss_pct": daily_loss_pct,
                    "max_loss_pct": self.max_loss_pct,
                },
            )

        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


class MaxDrawdownRule(RiskRule):
    """
    最大回撤规则
    """

    name = "max_drawdown"
    description = "检查当前回撤是否超过限制"

    def __init__(self, max_drawdown_pct: float = 0.20):
        """
        Args:
            max_drawdown_pct: 最大回撤百分比
        """
        self.max_drawdown_pct = max_drawdown_pct

    def check(self, context: RiskContext) -> RiskCheckResult:
        """检查回撤"""
        current_dd = float(context.current_drawdown)

        if current_dd > self.max_drawdown_pct:
            return RiskCheckResult(
                action=RiskAction.REJECT,
                rule_name=self.name,
                message=f"当前回撤 {current_dd:.2%} 超过限制 {self.max_drawdown_pct:.2%}",
                details={
                    "current_drawdown": current_dd,
                    "max_drawdown": self.max_drawdown_pct,
                    "peak_equity": str(context.peak_equity),
                    "current_equity": str(context.total_equity),
                },
            )

        if current_dd > self.max_drawdown_pct * 0.8:
            return RiskCheckResult(
                action=RiskAction.WARN,
                rule_name=self.name,
                message=f"当前回撤 {current_dd:.2%} 接近限制 {self.max_drawdown_pct:.2%}",
                details={
                    "current_drawdown": current_dd,
                    "max_drawdown": self.max_drawdown_pct,
                },
            )

        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


class MaxPositionRule(RiskRule):
    """
    最大持仓规则
    """

    name = "max_position"
    description = "检查单品种持仓是否超过限制"

    def __init__(self, max_position_pct: float = 0.30):
        """
        Args:
            max_position_pct: 单品种最大持仓占比 (相对于总权益)
        """
        self.max_position_pct = max_position_pct

    def check(self, context: RiskContext) -> RiskCheckResult:
        """检查持仓"""
        if context.total_equity <= 0:
            return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)

        for symbol, value in context.position_values.items():
            position_pct = float(value / context.total_equity)

            if position_pct > self.max_position_pct:
                return RiskCheckResult(
                    action=RiskAction.REJECT,
                    rule_name=self.name,
                    message=(
                        f"{symbol} 持仓占比 {position_pct:.2%} "
                        f"超过限制 {self.max_position_pct:.2%}"
                    ),
                    details={
                        "symbol": symbol,
                        "position_pct": position_pct,
                        "max_position_pct": self.max_position_pct,
                        "position_value": str(value),
                    },
                )

        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


class MaxLeverageRule(RiskRule):
    """
    最大杠杆规则
    """

    name = "max_leverage"
    description = "检查总杠杆是否超过限制"

    def __init__(self, max_leverage: float = 3.0):
        """
        Args:
            max_leverage: 最大杠杆倍数
        """
        self.max_leverage = max_leverage

    def check(self, context: RiskContext) -> RiskCheckResult:
        """检查杠杆"""
        if context.total_equity <= 0:
            return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)

        current_leverage = float(context.total_position_value / context.total_equity)

        if current_leverage > self.max_leverage:
            return RiskCheckResult(
                action=RiskAction.REJECT,
                rule_name=self.name,
                message=f"当前杠杆 {current_leverage:.2f}x 超过限制 {self.max_leverage}x",
                details={
                    "current_leverage": current_leverage,
                    "max_leverage": self.max_leverage,
                },
            )

        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


class RiskEngine:
    """
    风控引擎

    管理和执行风控规则链
    """

    def __init__(self) -> None:
        self._rules: list[RiskRule] = []
        self._enabled = True

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled

    def enable(self) -> None:
        """启用风控"""
        self._enabled = True
        logger.info("risk_engine_enabled")

    def disable(self) -> None:
        """禁用风控 (仅用于测试)"""
        self._enabled = False
        logger.warning("risk_engine_disabled")

    def add_rule(self, rule: RiskRule) -> None:
        """添加规则"""
        self._rules.append(rule)
        logger.info("risk_rule_added", rule=rule.name)

    def remove_rule(self, rule_name: str) -> bool:
        """移除规则"""
        for i, rule in enumerate(self._rules):
            if rule.name == rule_name:
                self._rules.pop(i)
                logger.info("risk_rule_removed", rule=rule_name)
                return True
        return False

    def clear_rules(self) -> None:
        """清空所有规则"""
        self._rules.clear()

    def get_rules(self) -> list[RiskRule]:
        """获取所有规则"""
        return self._rules.copy()

    def check(self, context: RiskContext) -> list[RiskCheckResult]:
        """
        执行所有规则检查

        Args:
            context: 风控上下文

        Returns:
            list[RiskCheckResult]: 所有检查结果
        """
        if not self._enabled:
            return [RiskCheckResult(action=RiskAction.PASS, rule_name="disabled")]

        results = []

        for rule in self._rules:
            try:
                result = rule.check(context)
                results.append(result)

                if result.action == RiskAction.WARN:
                    logger.warning(
                        "risk_warning",
                        rule=rule.name,
                        message=result.message,
                        details=result.details,
                    )
                elif result.action == RiskAction.REJECT:
                    logger.error(
                        "risk_rejected",
                        rule=rule.name,
                        message=result.message,
                        details=result.details,
                    )

            except Exception as e:
                logger.error("risk_check_error", rule=rule.name, error=str(e))
                results.append(
                    RiskCheckResult(
                        action=RiskAction.REJECT,
                        rule_name=rule.name,
                        message=f"规则执行出错: {e!s}",
                    )
                )

        return results

    def should_proceed(
        self, context: RiskContext
    ) -> tuple[bool, list[RiskCheckResult]]:
        """
        检查是否应该继续执行

        Args:
            context: 风控上下文

        Returns:
            tuple[bool, list[RiskCheckResult]]: (是否继续, 检查结果列表)
        """
        results = self.check(context)

        # 只要有一个 REJECT 就不继续
        for result in results:
            if result.rejected:
                return False, results

        return True, results


def create_default_risk_engine(
    max_daily_loss_pct: float = 0.05,
    max_drawdown_pct: float = 0.20,
    max_position_pct: float = 0.30,
    max_leverage: float = 3.0,
) -> RiskEngine:
    """
    创建默认风控引擎

    Args:
        max_daily_loss_pct: 单日最大亏损
        max_drawdown_pct: 最大回撤
        max_position_pct: 单品种最大持仓
        max_leverage: 最大杠杆

    Returns:
        RiskEngine: 配置好的风控引擎
    """
    engine = RiskEngine()
    engine.add_rule(MaxDailyLossRule(max_daily_loss_pct))
    engine.add_rule(MaxDrawdownRule(max_drawdown_pct))
    engine.add_rule(MaxPositionRule(max_position_pct))
    engine.add_rule(MaxLeverageRule(max_leverage))
    return engine


# 导出
__all__ = [
    "RiskAction",
    "RiskCheckResult",
    "RiskContext",
    "RiskRule",
    "MaxDailyLossRule",
    "MaxDrawdownRule",
    "MaxPositionRule",
    "MaxLeverageRule",
    "RiskEngine",
    "create_default_risk_engine",
]
