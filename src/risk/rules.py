"""
风控规则

支持的规则:
- 最大回撤限制
- 单日最大亏损
- 杠杆上限
- 单品种最大仓位
- 强平预警 (合约)

注意: 核心规则已移至 engine.py，本文件保留用于扩展规则
"""

from dataclasses import dataclass
from decimal import Decimal

from src.risk.engine import RiskAction, RiskCheckResult, RiskContext, RiskRule


class DailyTradeCountRule(RiskRule):
    """
    单日交易次数限制
    """

    name = "daily_trade_count"
    description = "检查单日交易次数是否超过限制"

    def __init__(self, max_trades: int = 50):
        """
        Args:
            max_trades: 单日最大交易次数
        """
        self.max_trades = max_trades

    def check(self, context: RiskContext) -> RiskCheckResult:
        """检查交易次数"""
        if context.daily_trades >= self.max_trades:
            return RiskCheckResult(
                action=RiskAction.REJECT,
                rule_name=self.name,
                message=f"单日交易次数 {context.daily_trades} 已达上限 {self.max_trades}",
                details={
                    "daily_trades": context.daily_trades,
                    "max_trades": self.max_trades,
                },
            )

        if context.daily_trades >= self.max_trades * 0.8:
            return RiskCheckResult(
                action=RiskAction.WARN,
                rule_name=self.name,
                message=(
                    f"单日交易次数 {context.daily_trades} 接近上限 {self.max_trades}"
                ),
                details={
                    "daily_trades": context.daily_trades,
                    "max_trades": self.max_trades,
                },
            )

        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


class MinBalanceRule(RiskRule):
    """
    最低余额限制
    """

    name = "min_balance"
    description = "检查可用余额是否足够"

    def __init__(self, min_balance: Decimal = Decimal("100")):
        """
        Args:
            min_balance: 最低可用余额
        """
        self.min_balance = min_balance

    def check(self, context: RiskContext) -> RiskCheckResult:
        """检查余额"""
        if context.available_balance < self.min_balance:
            return RiskCheckResult(
                action=RiskAction.REJECT,
                rule_name=self.name,
                message=(
                    f"可用余额 {context.available_balance} 低于最低要求 "
                    f"{self.min_balance}"
                ),
                details={
                    "available_balance": str(context.available_balance),
                    "min_balance": str(self.min_balance),
                },
            )

        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


@dataclass
class ForceLiquidationConfig:
    """强平预警配置"""

    warn_margin_ratio: float = 0.5  # 预警保证金率
    critical_margin_ratio: float = 0.3  # 临界保证金率


class ForceLiquidationRule(RiskRule):
    """
    强平预警规则 (合约专用)
    """

    name = "force_liquidation"
    description = "检查保证金率是否接近强平线"

    def __init__(self, config: ForceLiquidationConfig | None = None):
        self.config = config or ForceLiquidationConfig()

    def check(self, context: RiskContext) -> RiskCheckResult:
        """检查保证金率"""
        if context.used_margin <= 0:
            return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)

        # 计算保证金率 = 可用余额 / 已用保证金
        margin_ratio = float(context.available_balance / context.used_margin)

        if margin_ratio < self.config.critical_margin_ratio:
            return RiskCheckResult(
                action=RiskAction.REJECT,
                rule_name=self.name,
                message=(
                    f"保证金率 {margin_ratio:.2%} 已低于临界值 "
                    f"{self.config.critical_margin_ratio:.2%}"
                ),
                details={
                    "margin_ratio": margin_ratio,
                    "critical_ratio": self.config.critical_margin_ratio,
                },
            )

        if margin_ratio < self.config.warn_margin_ratio:
            return RiskCheckResult(
                action=RiskAction.WARN,
                rule_name=self.name,
                message=(
                    f"保证金率 {margin_ratio:.2%} 接近预警值 "
                    f"{self.config.warn_margin_ratio:.2%}"
                ),
                details={
                    "margin_ratio": margin_ratio,
                    "warn_ratio": self.config.warn_margin_ratio,
                },
            )

        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


class SymbolBlacklistRule(RiskRule):
    """
    交易对黑名单规则
    """

    name = "symbol_blacklist"
    description = "检查交易对是否在黑名单中"

    def __init__(self, blacklist: list[str] | None = None):
        """
        Args:
            blacklist: 禁止交易的交易对列表
        """
        self.blacklist = set(blacklist) if blacklist else set()

    def add_symbol(self, symbol: str) -> None:
        """添加到黑名单"""
        self.blacklist.add(symbol)

    def remove_symbol(self, symbol: str) -> None:
        """从黑名单移除"""
        self.blacklist.discard(symbol)

    def check(self, context: RiskContext) -> RiskCheckResult:
        """检查交易对"""
        if context.pending_order is None:
            return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)

        symbol = context.pending_order.symbol

        if symbol in self.blacklist:
            return RiskCheckResult(
                action=RiskAction.REJECT,
                rule_name=self.name,
                message=f"交易对 {symbol} 在黑名单中",
                details={"symbol": symbol, "blacklist": list(self.blacklist)},
            )

        return RiskCheckResult(action=RiskAction.PASS, rule_name=self.name)


# 导出
__all__ = [
    "DailyTradeCountRule",
    "MinBalanceRule",
    "ForceLiquidationConfig",
    "ForceLiquidationRule",
    "SymbolBlacklistRule",
]
