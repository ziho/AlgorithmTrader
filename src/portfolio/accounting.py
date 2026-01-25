"""
账户核算

职责:
- 费用计算
- 滑点计算
- PNL 计算
- 权益曲线
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.portfolio.position import OrderSide, PositionTracker


@dataclass
class TradeRecord:
    """成交记录"""

    timestamp: datetime
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal  # 成交价格
    commission: Decimal = Decimal("0")  # 手续费
    slippage: Decimal = Decimal("0")  # 滑点成本
    realized_pnl: Decimal = Decimal("0")  # 本笔实现盈亏
    trade_id: str = ""

    @property
    def notional(self) -> Decimal:
        """成交金额"""
        return self.quantity * self.price

    @property
    def total_cost(self) -> Decimal:
        """总交易成本"""
        return self.commission + self.slippage

    @property
    def net_pnl(self) -> Decimal:
        """扣除成本后的净盈亏"""
        return self.realized_pnl - self.total_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "commission": str(self.commission),
            "slippage": str(self.slippage),
            "realized_pnl": str(self.realized_pnl),
            "total_cost": str(self.total_cost),
            "net_pnl": str(self.net_pnl),
            "notional": str(self.notional),
            "trade_id": self.trade_id,
        }


@dataclass
class EquityPoint:
    """权益曲线点"""

    timestamp: datetime
    equity: Decimal  # 总权益
    cash: Decimal  # 现金
    position_value: Decimal  # 持仓市值
    unrealized_pnl: Decimal = Decimal("0")  # 未实现盈亏
    realized_pnl: Decimal = Decimal("0")  # 累计实现盈亏
    drawdown: Decimal = Decimal("0")  # 回撤金额
    drawdown_pct: Decimal = Decimal("0")  # 回撤百分比

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "equity": str(self.equity),
            "cash": str(self.cash),
            "position_value": str(self.position_value),
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl": str(self.realized_pnl),
            "drawdown": str(self.drawdown),
            "drawdown_pct": str(self.drawdown_pct),
        }


@dataclass
class DailySummary:
    """每日汇总"""

    date: datetime
    starting_equity: Decimal
    ending_equity: Decimal
    daily_pnl: Decimal
    daily_return: Decimal
    trade_count: int
    commission_paid: Decimal
    max_drawdown: Decimal
    symbols_traded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "starting_equity": str(self.starting_equity),
            "ending_equity": str(self.ending_equity),
            "daily_pnl": str(self.daily_pnl),
            "daily_return": str(self.daily_return),
            "trade_count": self.trade_count,
            "commission_paid": str(self.commission_paid),
            "max_drawdown": str(self.max_drawdown),
            "symbols_traded": self.symbols_traded,
        }


class AccountingEngine:
    """
    账户核算引擎

    职责:
    - 资金管理
    - 成交记录
    - 权益曲线计算
    - 每日汇总生成
    """

    def __init__(
        self,
        initial_capital: Decimal,
        position_tracker: PositionTracker | None = None,
    ):
        self.initial_capital = initial_capital
        self._cash = initial_capital
        self._position_tracker = position_tracker or PositionTracker()

        # 记录
        self._trades: list[TradeRecord] = []
        self._equity_curve: list[EquityPoint] = []
        self._daily_summaries: list[DailySummary] = []

        # 状态跟踪
        self._peak_equity = initial_capital
        self._total_commission = Decimal("0")
        self._total_slippage = Decimal("0")
        self._total_realized_pnl = Decimal("0")

    @property
    def cash(self) -> Decimal:
        """当前现金"""
        return self._cash

    @property
    def position_tracker(self) -> PositionTracker:
        """持仓跟踪器"""
        return self._position_tracker

    @property
    def trades(self) -> list[TradeRecord]:
        """成交记录"""
        return self._trades.copy()

    @property
    def equity_curve(self) -> list[EquityPoint]:
        """权益曲线"""
        return self._equity_curve.copy()

    def calculate_equity(self, prices: dict[str, Decimal]) -> Decimal:
        """计算当前权益"""
        position_value = self._position_tracker.calculate_value(prices)
        return self._cash + position_value

    def calculate_position_value(self, prices: dict[str, Decimal]) -> Decimal:
        """计算持仓市值"""
        return self._position_tracker.calculate_value(prices)

    def record_trade(
        self,
        timestamp: datetime,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        commission: Decimal = Decimal("0"),
        slippage: Decimal = Decimal("0"),
        trade_id: str = "",
    ) -> TradeRecord:
        """
        记录成交

        Args:
            timestamp: 成交时间
            symbol: 品种代码
            side: 订单方向
            quantity: 成交数量
            price: 成交价格
            commission: 手续费
            slippage: 滑点成本
            trade_id: 成交ID

        Returns:
            成交记录
        """
        # 更新持仓
        realized_pnl = self._position_tracker.update_position(
            symbol, side, quantity, price, timestamp
        )

        # 更新现金
        trade_value = quantity * price
        if side == OrderSide.BUY:
            self._cash -= trade_value + commission
        else:
            self._cash += trade_value - commission

        # 累计统计
        self._total_commission += commission
        self._total_slippage += slippage
        self._total_realized_pnl += realized_pnl

        # 创建成交记录
        record = TradeRecord(
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            commission=commission,
            slippage=slippage,
            realized_pnl=realized_pnl,
            trade_id=trade_id,
        )
        self._trades.append(record)

        return record

    def update_equity_curve(
        self,
        timestamp: datetime,
        prices: dict[str, Decimal],
    ) -> EquityPoint:
        """
        更新权益曲线

        Args:
            timestamp: 时间戳
            prices: 各品种价格

        Returns:
            权益点
        """
        position_value = self._position_tracker.calculate_value(prices)
        unrealized_pnl = self._position_tracker.calculate_unrealized_pnl(prices)
        equity = self._cash + position_value

        # 更新峰值和回撤
        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown = self._peak_equity - equity
        drawdown_pct = (
            drawdown / self._peak_equity if self._peak_equity > 0 else Decimal("0")
        )

        point = EquityPoint(
            timestamp=timestamp,
            equity=equity,
            cash=self._cash,
            position_value=position_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=self._total_realized_pnl,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
        )
        self._equity_curve.append(point)

        return point

    def generate_daily_summary(
        self,
        date: datetime,
        prices: dict[str, Decimal],
    ) -> DailySummary | None:
        """
        生成每日汇总

        Args:
            date: 日期
            prices: 各品种价格

        Returns:
            每日汇总（如果当天没有数据则返回None）
        """
        # 找出当天的权益点和成交
        date_only = date.date()

        day_equity_points = [
            p for p in self._equity_curve if p.timestamp.date() == date_only
        ]
        day_trades = [t for t in self._trades if t.timestamp.date() == date_only]

        if not day_equity_points:
            # 没有当天数据，使用当前计算
            current_equity = self.calculate_equity(prices)

            # 找前一天的结束权益
            prev_equity = self.initial_capital
            if self._daily_summaries:
                prev_equity = self._daily_summaries[-1].ending_equity
            elif self._equity_curve:
                prev_equity = self._equity_curve[-1].equity

            daily_pnl = current_equity - prev_equity
            daily_return = daily_pnl / prev_equity if prev_equity > 0 else Decimal("0")

            summary = DailySummary(
                date=date,
                starting_equity=prev_equity,
                ending_equity=current_equity,
                daily_pnl=daily_pnl,
                daily_return=daily_return,
                trade_count=len(day_trades),
                commission_paid=sum(
                    (t.commission for t in day_trades), start=Decimal("0")
                ),
                max_drawdown=max(
                    (p.drawdown_pct for p in day_equity_points),
                    default=Decimal("0"),
                ),
                symbols_traded=list({t.symbol for t in day_trades}),
            )
        else:
            starting_equity = day_equity_points[0].equity
            ending_equity = day_equity_points[-1].equity

            # 如果有前一天的汇总，使用前一天的结束权益
            if self._daily_summaries:
                starting_equity = self._daily_summaries[-1].ending_equity

            daily_pnl = ending_equity - starting_equity
            daily_return = (
                daily_pnl / starting_equity if starting_equity > 0 else Decimal("0")
            )

            summary = DailySummary(
                date=date,
                starting_equity=starting_equity,
                ending_equity=ending_equity,
                daily_pnl=daily_pnl,
                daily_return=daily_return,
                trade_count=len(day_trades),
                commission_paid=sum(
                    (t.commission for t in day_trades), start=Decimal("0")
                ),
                max_drawdown=max(
                    (p.drawdown_pct for p in day_equity_points),
                    default=Decimal("0"),
                ),
                symbols_traded=list({t.symbol for t in day_trades}),
            )

        self._daily_summaries.append(summary)
        return summary

    def get_statistics(self, prices: dict[str, Decimal]) -> dict[str, Any]:
        """
        获取账户统计

        Args:
            prices: 各品种价格

        Returns:
            统计信息
        """
        equity = self.calculate_equity(prices)
        position_value = self.calculate_position_value(prices)
        unrealized_pnl = self._position_tracker.calculate_unrealized_pnl(prices)

        total_pnl = equity - self.initial_capital
        total_return = (
            total_pnl / self.initial_capital
            if self.initial_capital > 0
            else Decimal("0")
        )

        max_drawdown = max(
            (p.drawdown_pct for p in self._equity_curve),
            default=Decimal("0"),
        )

        return {
            "initial_capital": str(self.initial_capital),
            "current_equity": str(equity),
            "cash": str(self._cash),
            "position_value": str(position_value),
            "unrealized_pnl": str(unrealized_pnl),
            "realized_pnl": str(self._total_realized_pnl),
            "total_pnl": str(total_pnl),
            "total_return": str(total_return),
            "peak_equity": str(self._peak_equity),
            "max_drawdown": str(max_drawdown),
            "total_trades": len(self._trades),
            "total_commission": str(self._total_commission),
            "total_slippage": str(self._total_slippage),
            "active_positions": len(self._position_tracker.active_positions),
        }

    def reset(self) -> None:
        """重置账户"""
        self._cash = self.initial_capital
        self._position_tracker.reset()
        self._trades.clear()
        self._equity_curve.clear()
        self._daily_summaries.clear()
        self._peak_equity = self.initial_capital
        self._total_commission = Decimal("0")
        self._total_slippage = Decimal("0")
        self._total_realized_pnl = Decimal("0")


class PnLCalculator:
    """
    盈亏计算器

    提供静态方法用于盈亏计算
    """

    @staticmethod
    def calculate_trade_pnl(
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: Decimal,
        is_long: bool = True,
    ) -> Decimal:
        """
        计算单笔交易盈亏

        Args:
            entry_price: 入场价格
            exit_price: 出场价格
            quantity: 数量
            is_long: 是否做多

        Returns:
            盈亏金额
        """
        price_diff = exit_price - entry_price
        if not is_long:
            price_diff = -price_diff
        return quantity * price_diff

    @staticmethod
    def calculate_return(
        entry_value: Decimal,
        exit_value: Decimal,
    ) -> Decimal:
        """
        计算收益率

        Args:
            entry_value: 入场价值
            exit_value: 出场价值

        Returns:
            收益率（小数形式）
        """
        if entry_value <= 0:
            return Decimal("0")
        return (exit_value - entry_value) / entry_value

    @staticmethod
    def calculate_drawdown(
        equity_series: list[Decimal],
    ) -> tuple[Decimal, Decimal]:
        """
        计算最大回撤

        Args:
            equity_series: 权益序列

        Returns:
            (最大回撤金额, 最大回撤百分比)
        """
        if not equity_series:
            return Decimal("0"), Decimal("0")

        peak = equity_series[0]
        max_dd = Decimal("0")
        max_dd_pct = Decimal("0")

        for equity in equity_series:
            if equity > peak:
                peak = equity
            dd = peak - equity
            dd_pct = dd / peak if peak > 0 else Decimal("0")
            if dd_pct > max_dd_pct:
                max_dd = dd
                max_dd_pct = dd_pct

        return max_dd, max_dd_pct

    @staticmethod
    def calculate_sharpe_ratio(
        returns: list[Decimal],
        risk_free_rate: Decimal = Decimal("0"),
        annualization_factor: Decimal = Decimal("252"),
    ) -> Decimal:
        """
        计算夏普比率

        Args:
            returns: 收益率序列
            risk_free_rate: 无风险利率（年化）
            annualization_factor: 年化因子

        Returns:
            夏普比率
        """
        if not returns or len(returns) < 2:
            return Decimal("0")

        # 转换为float计算
        float_returns = [float(r) for r in returns]
        mean_return = sum(float_returns) / len(float_returns)
        variance = sum((r - mean_return) ** 2 for r in float_returns) / len(
            float_returns
        )
        std_dev = variance**0.5

        if std_dev == 0:
            return Decimal("0")

        daily_rf = float(risk_free_rate) / float(annualization_factor)
        sharpe = (mean_return - daily_rf) / std_dev * float(annualization_factor) ** 0.5

        return Decimal(str(round(sharpe, 4)))
