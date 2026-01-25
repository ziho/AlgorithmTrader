"""
绩效指标

支持:
- Sharpe Ratio
- Maximum Drawdown
- 胜率/盈亏比
- 换手率
- Calmar Ratio
- 年化收益率
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import numpy as np


@dataclass
class TradeStats:
    """交易统计"""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: Decimal = Decimal("0")
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")
    total_commission: Decimal = Decimal("0")

    @property
    def win_rate(self) -> float:
        """胜率"""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def profit_factor(self) -> float:
        """盈亏比（毛利/毛损）"""
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return float(abs(self.gross_profit / self.gross_loss))

    @property
    def avg_win(self) -> Decimal:
        """平均盈利"""
        if self.winning_trades == 0:
            return Decimal("0")
        return self.gross_profit / self.winning_trades

    @property
    def avg_loss(self) -> Decimal:
        """平均亏损"""
        if self.losing_trades == 0:
            return Decimal("0")
        return self.gross_loss / self.losing_trades

    @property
    def expectancy(self) -> Decimal:
        """期望收益（每笔交易平均收益）"""
        if self.total_trades == 0:
            return Decimal("0")
        return self.total_pnl / self.total_trades

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "total_pnl": str(self.total_pnl),
            "gross_profit": str(self.gross_profit),
            "gross_loss": str(self.gross_loss),
            "avg_win": str(self.avg_win),
            "avg_loss": str(self.avg_loss),
            "expectancy": str(self.expectancy),
            "total_commission": str(self.total_commission),
        }


@dataclass
class PerformanceMetrics:
    """绩效指标汇总"""

    # 时间范围
    start_date: datetime | None = None
    end_date: datetime | None = None
    trading_days: int = 0

    # 收益指标
    total_return: float = 0.0  # 总收益率
    annualized_return: float = 0.0  # 年化收益率
    cagr: float = 0.0  # 复合年增长率

    # 风险指标
    volatility: float = 0.0  # 年化波动率
    max_drawdown: float = 0.0  # 最大回撤
    max_drawdown_duration: int = 0  # 最大回撤持续天数
    max_drawdown_peak_date: datetime | None = None
    max_drawdown_valley_date: datetime | None = None

    # 风险调整收益
    sharpe_ratio: float = 0.0  # 夏普比率
    sortino_ratio: float = 0.0  # 索提诺比率
    calmar_ratio: float = 0.0  # 卡尔玛比率

    # 交易统计
    trade_stats: TradeStats = field(default_factory=TradeStats)

    # 换手率
    turnover: float = 0.0  # 平均换手率

    # 其他
    skewness: float = 0.0  # 收益偏度
    kurtosis: float = 0.0  # 收益峰度

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "trading_days": self.trading_days,
            "total_return": round(self.total_return, 6),
            "annualized_return": round(self.annualized_return, 6),
            "cagr": round(self.cagr, 6),
            "volatility": round(self.volatility, 6),
            "max_drawdown": round(self.max_drawdown, 6),
            "max_drawdown_duration": self.max_drawdown_duration,
            "max_drawdown_peak_date": (
                self.max_drawdown_peak_date.isoformat()
                if self.max_drawdown_peak_date
                else None
            ),
            "max_drawdown_valley_date": (
                self.max_drawdown_valley_date.isoformat()
                if self.max_drawdown_valley_date
                else None
            ),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "trade_stats": self.trade_stats.to_dict(),
            "turnover": round(self.turnover, 6),
            "skewness": round(self.skewness, 4),
            "kurtosis": round(self.kurtosis, 4),
        }


class MetricsCalculator:
    """
    绩效指标计算器

    支持:
    - 从权益曲线计算收益指标
    - 从交易记录计算交易统计
    - 滚动窗口计算
    """

    # 年化因子（假设每年 252 个交易日）
    TRADING_DAYS_PER_YEAR = 252

    # 无风险利率（默认 0）
    RISK_FREE_RATE = 0.0

    def __init__(
        self,
        trading_days_per_year: int = 252,
        risk_free_rate: float = 0.0,
    ):
        self.trading_days_per_year = trading_days_per_year
        self.risk_free_rate = risk_free_rate

    def calculate_returns(self, equity_values: np.ndarray) -> np.ndarray:
        """
        计算收益率序列

        Args:
            equity_values: 权益值数组

        Returns:
            收益率数组（简单收益率）
        """
        if len(equity_values) < 2:
            return np.array([])

        returns = np.diff(equity_values) / equity_values[:-1]
        return returns

    def calculate_log_returns(self, equity_values: np.ndarray) -> np.ndarray:
        """计算对数收益率"""
        if len(equity_values) < 2:
            return np.array([])

        # 避免 log(0)
        equity_values = np.maximum(equity_values, 1e-10)
        returns = np.diff(np.log(equity_values))
        return returns

    def total_return(self, equity_values: np.ndarray) -> float:
        """
        计算总收益率

        Args:
            equity_values: 权益值数组

        Returns:
            总收益率
        """
        if len(equity_values) < 2 or equity_values[0] == 0:
            return 0.0
        return float((equity_values[-1] - equity_values[0]) / equity_values[0])

    def annualized_return(
        self,
        total_return: float,
        trading_days: int,
    ) -> float:
        """
        计算年化收益率

        使用公式: (1 + total_return)^(252/days) - 1
        """
        if trading_days <= 0:
            return 0.0

        years = trading_days / self.trading_days_per_year
        if years <= 0:
            return 0.0

        # CAGR 公式
        return (1 + total_return) ** (1 / years) - 1

    def volatility(self, returns: np.ndarray, annualize: bool = True) -> float:
        """
        计算波动率

        Args:
            returns: 收益率数组
            annualize: 是否年化

        Returns:
            波动率
        """
        if len(returns) < 2:
            return 0.0

        std = np.std(returns, ddof=1)

        if annualize:
            return float(std * np.sqrt(self.trading_days_per_year))
        return float(std)

    def downside_volatility(self, returns: np.ndarray, annualize: bool = True) -> float:
        """
        计算下行波动率（用于 Sortino）

        只考虑负收益
        """
        if len(returns) < 2:
            return 0.0

        negative_returns = returns[returns < 0]
        if len(negative_returns) == 0:
            return 0.0

        std = np.std(negative_returns, ddof=1)

        if annualize:
            return float(std * np.sqrt(self.trading_days_per_year))
        return float(std)

    def sharpe_ratio(
        self,
        returns: np.ndarray,
        risk_free_rate: float | None = None,
    ) -> float:
        """
        计算夏普比率

        Sharpe = (年化收益率 - 无风险利率) / 年化波动率
        """
        if len(returns) < 2:
            return 0.0

        rf = risk_free_rate if risk_free_rate is not None else self.risk_free_rate

        # 计算年化收益率
        mean_return = np.mean(returns) * self.trading_days_per_year
        vol = self.volatility(returns, annualize=True)

        if vol == 0:
            return 0.0

        return float((mean_return - rf) / vol)

    def sortino_ratio(
        self,
        returns: np.ndarray,
        risk_free_rate: float | None = None,
    ) -> float:
        """
        计算索提诺比率

        Sortino = (年化收益率 - 无风险利率) / 下行波动率
        """
        if len(returns) < 2:
            return 0.0

        rf = risk_free_rate if risk_free_rate is not None else self.risk_free_rate

        mean_return = np.mean(returns) * self.trading_days_per_year
        down_vol = self.downside_volatility(returns, annualize=True)

        if down_vol == 0:
            return 0.0

        return float((mean_return - rf) / down_vol)

    def calmar_ratio(
        self,
        annualized_return: float,
        max_drawdown: float,
    ) -> float:
        """
        计算卡尔玛比率

        Calmar = 年化收益率 / 最大回撤
        """
        if max_drawdown == 0:
            return 0.0 if annualized_return <= 0 else float("inf")

        return annualized_return / abs(max_drawdown)

    def max_drawdown(
        self,
        equity_values: np.ndarray,
        timestamps: list[datetime] | None = None,
    ) -> tuple[float, int, datetime | None, datetime | None]:
        """
        计算最大回撤

        Returns:
            (最大回撤百分比, 持续天数, 峰值日期, 谷值日期)
        """
        if len(equity_values) < 2:
            return 0.0, 0, None, None

        # 计算滚动最大值
        peak = np.maximum.accumulate(equity_values)

        # 计算回撤
        drawdown = (peak - equity_values) / peak

        # 找到最大回撤
        max_dd = float(np.max(drawdown))
        max_dd_idx = int(np.argmax(drawdown))

        # 找到峰值位置
        peak_idx = 0
        for i in range(max_dd_idx, -1, -1):
            if equity_values[i] == peak[max_dd_idx]:
                peak_idx = i
                break

        # 计算持续天数
        duration = max_dd_idx - peak_idx

        # 日期信息
        peak_date = None
        valley_date = None
        if timestamps:
            peak_date = timestamps[peak_idx]
            valley_date = timestamps[max_dd_idx]

        return max_dd, duration, peak_date, valley_date

    def calculate_trade_stats(
        self,
        pnl_list: list[Decimal],
        commissions: list[Decimal] | None = None,
    ) -> TradeStats:
        """
        从交易盈亏列表计算交易统计

        Args:
            pnl_list: 每笔交易的盈亏
            commissions: 每笔交易的手续费

        Returns:
            交易统计
        """
        stats = TradeStats()
        stats.total_trades = len(pnl_list)

        if not pnl_list:
            return stats

        for pnl in pnl_list:
            stats.total_pnl += pnl
            if pnl > 0:
                stats.winning_trades += 1
                stats.gross_profit += pnl
            elif pnl < 0:
                stats.losing_trades += 1
                stats.gross_loss += pnl

        if commissions:
            stats.total_commission = sum(commissions)

        return stats

    def calculate_turnover(
        self,
        trade_values: list[Decimal],
        avg_equity: Decimal,
        trading_days: int,
    ) -> float:
        """
        计算换手率

        换手率 = 总成交额 / (平均权益 * 交易天数) * 252

        Args:
            trade_values: 每笔交易的成交额
            avg_equity: 平均权益
            trading_days: 交易天数

        Returns:
            年化换手率
        """
        if not trade_values or avg_equity <= 0 or trading_days <= 0:
            return 0.0

        total_value = sum(trade_values)
        daily_turnover = float(total_value / avg_equity / trading_days)

        return daily_turnover * self.trading_days_per_year

    def skewness(self, returns: np.ndarray) -> float:
        """计算收益偏度"""
        if len(returns) < 3:
            return 0.0

        from scipy.stats import skew

        return float(skew(returns))

    def kurtosis(self, returns: np.ndarray) -> float:
        """计算收益峰度（超额峰度）"""
        if len(returns) < 4:
            return 0.0

        from scipy.stats import kurtosis

        return float(kurtosis(returns))

    def calculate_all(
        self,
        equity_values: np.ndarray,
        timestamps: list[datetime] | None = None,
        trade_pnl: list[Decimal] | None = None,
        trade_values: list[Decimal] | None = None,
        trade_commissions: list[Decimal] | None = None,
    ) -> PerformanceMetrics:
        """
        计算所有绩效指标

        Args:
            equity_values: 权益值数组
            timestamps: 时间戳列表
            trade_pnl: 每笔交易盈亏
            trade_values: 每笔交易成交额
            trade_commissions: 每笔交易手续费

        Returns:
            完整的绩效指标
        """
        metrics = PerformanceMetrics()

        if len(equity_values) < 2:
            return metrics

        # 时间范围
        if timestamps:
            metrics.start_date = timestamps[0]
            metrics.end_date = timestamps[-1]
            # 计算交易天数（去重日期）
            unique_dates = {ts.date() for ts in timestamps}
            metrics.trading_days = len(unique_dates)
        else:
            metrics.trading_days = len(equity_values)

        # 收益率
        returns = self.calculate_returns(equity_values)
        metrics.total_return = self.total_return(equity_values)
        metrics.annualized_return = self.annualized_return(
            metrics.total_return, metrics.trading_days
        )
        metrics.cagr = metrics.annualized_return  # 对于简单情况相同

        # 风险指标
        metrics.volatility = self.volatility(returns)
        (
            metrics.max_drawdown,
            metrics.max_drawdown_duration,
            metrics.max_drawdown_peak_date,
            metrics.max_drawdown_valley_date,
        ) = self.max_drawdown(equity_values, timestamps)

        # 风险调整收益
        metrics.sharpe_ratio = self.sharpe_ratio(returns)
        metrics.sortino_ratio = self.sortino_ratio(returns)
        metrics.calmar_ratio = self.calmar_ratio(
            metrics.annualized_return, metrics.max_drawdown
        )

        # 交易统计
        if trade_pnl:
            metrics.trade_stats = self.calculate_trade_stats(
                trade_pnl, trade_commissions
            )

        # 换手率
        if trade_values and metrics.trading_days > 0:
            avg_equity = Decimal(str(np.mean(equity_values)))
            metrics.turnover = self.calculate_turnover(
                trade_values, avg_equity, metrics.trading_days
            )

        # 高阶矩
        if len(returns) >= 3:
            import contextlib

            with contextlib.suppress(ImportError):
                metrics.skewness = self.skewness(returns)
        if len(returns) >= 4:
            import contextlib

            with contextlib.suppress(ImportError):
                metrics.kurtosis = self.kurtosis(returns)

        return metrics

    def rolling_sharpe(
        self,
        returns: np.ndarray,
        window: int = 60,
    ) -> np.ndarray:
        """
        计算滚动夏普比率

        Args:
            returns: 收益率数组
            window: 滚动窗口大小

        Returns:
            滚动夏普比率数组
        """
        if len(returns) < window:
            return np.array([])

        rolling_sharpe = np.empty(len(returns) - window + 1)

        for i in range(len(rolling_sharpe)):
            window_returns = returns[i : i + window]
            rolling_sharpe[i] = self.sharpe_ratio(window_returns)

        return rolling_sharpe

    def rolling_volatility(
        self,
        returns: np.ndarray,
        window: int = 20,
    ) -> np.ndarray:
        """
        计算滚动波动率

        Args:
            returns: 收益率数组
            window: 滚动窗口大小

        Returns:
            滚动波动率数组（年化）
        """
        if len(returns) < window:
            return np.array([])

        rolling_vol = np.empty(len(returns) - window + 1)

        for i in range(len(rolling_vol)):
            window_returns = returns[i : i + window]
            rolling_vol[i] = self.volatility(window_returns, annualize=True)

        return rolling_vol


# 导出
__all__ = [
    "TradeStats",
    "PerformanceMetrics",
    "MetricsCalculator",
]
