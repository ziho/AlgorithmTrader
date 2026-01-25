"""
绩效指标单元测试
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np

from src.backtest.metrics import MetricsCalculator, PerformanceMetrics, TradeStats


class TestTradeStats:
    """交易统计测试"""

    def test_empty_stats(self):
        """空统计"""
        stats = TradeStats()
        assert stats.win_rate == 0.0
        assert stats.profit_factor == 0.0
        assert stats.expectancy == Decimal("0")

    def test_win_rate(self):
        """胜率计算"""
        stats = TradeStats(
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
        )
        assert stats.win_rate == 0.6

    def test_profit_factor(self):
        """盈亏比计算"""
        stats = TradeStats(
            gross_profit=Decimal("1000"),
            gross_loss=Decimal("-500"),
        )
        assert stats.profit_factor == 2.0

    def test_profit_factor_no_loss(self):
        """无亏损时盈亏比为无穷"""
        stats = TradeStats(
            gross_profit=Decimal("1000"),
            gross_loss=Decimal("0"),
        )
        assert stats.profit_factor == float("inf")

    def test_avg_win_loss(self):
        """平均盈亏"""
        stats = TradeStats(
            winning_trades=4,
            losing_trades=2,
            gross_profit=Decimal("400"),
            gross_loss=Decimal("-100"),
        )
        assert stats.avg_win == Decimal("100")
        assert stats.avg_loss == Decimal("-50")

    def test_expectancy(self):
        """期望收益"""
        stats = TradeStats(
            total_trades=10,
            total_pnl=Decimal("500"),
        )
        assert stats.expectancy == Decimal("50")

    def test_to_dict(self):
        """序列化"""
        stats = TradeStats(total_trades=5)
        d = stats.to_dict()
        assert d["total_trades"] == 5
        assert "win_rate" in d


class TestMetricsCalculator:
    """绩效指标计算器测试"""

    def setup_method(self):
        """测试准备"""
        self.calc = MetricsCalculator()

    def test_calculate_returns(self):
        """计算收益率"""
        equity = np.array([100, 105, 103, 110])
        returns = self.calc.calculate_returns(equity)
        expected = np.array([0.05, -0.019047619, 0.067961165])
        np.testing.assert_array_almost_equal(returns, expected, decimal=4)

    def test_calculate_returns_empty(self):
        """空数据返回空数组"""
        returns = self.calc.calculate_returns(np.array([100]))
        assert len(returns) == 0

    def test_total_return(self):
        """总收益率"""
        equity = np.array([100, 110, 120, 150])
        ret = self.calc.total_return(equity)
        assert ret == 0.5  # (150 - 100) / 100

    def test_annualized_return(self):
        """年化收益率"""
        # 252 天翻倍
        ann_ret = self.calc.annualized_return(1.0, 252)
        assert abs(ann_ret - 1.0) < 0.001  # 约 100% 年化

        # 半年 50% 收益
        ann_ret = self.calc.annualized_return(0.5, 126)
        assert ann_ret > 1.0  # 年化应大于 100%

    def test_volatility(self):
        """波动率计算"""
        # 固定收益率
        returns = np.array([0.01, 0.01, 0.01, 0.01])
        vol = self.calc.volatility(returns, annualize=False)
        assert vol == 0.0  # 无波动

        # 随机收益率
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
        vol = self.calc.volatility(returns, annualize=False)
        assert vol > 0

    def test_downside_volatility(self):
        """下行波动率"""
        returns = np.array([0.05, -0.02, 0.03, -0.04, 0.02])
        down_vol = self.calc.downside_volatility(returns, annualize=False)
        assert down_vol > 0

        # 只有正收益
        returns = np.array([0.01, 0.02, 0.03])
        down_vol = self.calc.downside_volatility(returns)
        assert down_vol == 0.0

    def test_sharpe_ratio(self):
        """夏普比率"""
        # 高收益低波动 = 高夏普
        returns = np.array([0.02, 0.02, 0.02, 0.02, 0.02])
        sharpe = self.calc.sharpe_ratio(returns)
        # 由于波动为 0，这是边界情况
        # 这里用有波动的情况测试
        returns = np.array([0.02, 0.01, 0.03, 0.02, 0.01])
        sharpe = self.calc.sharpe_ratio(returns)
        assert sharpe > 0

    def test_sharpe_ratio_negative(self):
        """负收益夏普比率"""
        returns = np.array([-0.01, -0.02, -0.01, -0.02])
        sharpe = self.calc.sharpe_ratio(returns)
        assert sharpe < 0

    def test_sortino_ratio(self):
        """索提诺比率"""
        returns = np.array([0.02, -0.01, 0.03, -0.02, 0.02])
        sortino = self.calc.sortino_ratio(returns)
        # Sortino 应该大于 0
        assert sortino > 0

    def test_calmar_ratio(self):
        """卡尔玛比率"""
        calmar = self.calc.calmar_ratio(0.2, 0.1)  # 20% 年化，10% 最大回撤
        assert calmar == 2.0

        calmar = self.calc.calmar_ratio(0.2, 0.0)  # 无回撤
        assert calmar == float("inf")

    def test_max_drawdown(self):
        """最大回撤"""
        # 简单回撤场景
        equity = np.array([100, 110, 105, 115, 100, 120])
        max_dd, duration, _, _ = self.calc.max_drawdown(equity)

        # 最大回撤是从 115 跌到 100
        expected_dd = (115 - 100) / 115
        assert abs(max_dd - expected_dd) < 0.001

    def test_max_drawdown_with_timestamps(self):
        """带时间戳的最大回撤"""
        equity = np.array([100, 120, 100, 110])
        base = datetime.now(UTC)
        timestamps = [base + timedelta(days=i) for i in range(4)]

        max_dd, duration, peak_date, valley_date = self.calc.max_drawdown(
            equity, timestamps
        )

        assert abs(max_dd - (120 - 100) / 120) < 0.001  # ~16.67%
        assert peak_date == timestamps[1]
        assert valley_date == timestamps[2]

    def test_calculate_trade_stats(self):
        """交易统计计算"""
        pnl_list = [
            Decimal("100"),
            Decimal("-50"),
            Decimal("200"),
            Decimal("-30"),
            Decimal("150"),
        ]
        commissions = [Decimal("1")] * 5

        stats = self.calc.calculate_trade_stats(pnl_list, commissions)

        assert stats.total_trades == 5
        assert stats.winning_trades == 3
        assert stats.losing_trades == 2
        assert stats.total_pnl == Decimal("370")
        assert stats.gross_profit == Decimal("450")
        assert stats.gross_loss == Decimal("-80")
        assert stats.total_commission == Decimal("5")

    def test_calculate_turnover(self):
        """换手率计算"""
        trade_values = [Decimal("1000"), Decimal("2000"), Decimal("1500")]
        avg_equity = Decimal("10000")
        trading_days = 10

        turnover = self.calc.calculate_turnover(trade_values, avg_equity, trading_days)
        # (4500 / 10000 / 10) * 252 = 11.34
        assert turnover > 0

    def test_calculate_all(self):
        """计算所有指标"""
        equity = np.array([100000, 102000, 101000, 105000, 103000, 108000])
        base = datetime.now(UTC)
        timestamps = [base + timedelta(days=i) for i in range(6)]
        trade_pnl = [Decimal("2000"), Decimal("-1000"), Decimal("4000")]

        metrics = self.calc.calculate_all(
            equity_values=equity,
            timestamps=timestamps,
            trade_pnl=trade_pnl,
        )

        assert metrics.total_return > 0
        assert metrics.max_drawdown > 0
        assert metrics.trade_stats.total_trades == 3

    def test_rolling_sharpe(self):
        """滚动夏普比率"""
        np.random.seed(42)
        returns = np.random.randn(100) * 0.01 + 0.001

        rolling = self.calc.rolling_sharpe(returns, window=20)

        assert len(rolling) == 81  # 100 - 20 + 1
        assert all(np.isfinite(rolling))

    def test_rolling_volatility(self):
        """滚动波动率"""
        np.random.seed(42)
        returns = np.random.randn(50) * 0.02

        rolling = self.calc.rolling_volatility(returns, window=10)

        assert len(rolling) == 41  # 50 - 10 + 1
        assert all(r >= 0 for r in rolling)


class TestPerformanceMetrics:
    """绩效指标数据类测试"""

    def test_to_dict(self):
        """序列化"""
        metrics = PerformanceMetrics(
            total_return=0.15,
            annualized_return=0.30,
            sharpe_ratio=1.5,
            max_drawdown=0.10,
        )
        d = metrics.to_dict()

        assert d["total_return"] == 0.15
        assert d["sharpe_ratio"] == 1.5
        assert "trade_stats" in d
