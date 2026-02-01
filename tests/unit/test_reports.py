"""
回测报告模块单元测试

测试范围:
- ReportGenerator: 报告生成器
- BacktestSummary: 回测摘要
- generate_text_report: 文本报告
- generate_markdown_report: Markdown 报告
"""

import json
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.backtest.engine import BacktestConfig, BacktestResult, EquityPoint, Trade
from src.backtest.metrics import PerformanceMetrics, TradeStats
from src.backtest.reports import (
    BacktestSummary,
    ReportConfig,
    ReportGenerator,
    generate_markdown_report,
    generate_text_report,
)
from src.core.events import OrderSide
from src.strategy.base import StrategyConfig


class TestBacktestSummary:
    """BacktestSummary 回测摘要测试"""

    def test_summary_creation(self) -> None:
        """测试摘要创建"""
        summary = BacktestSummary(
            run_id="20240101_120000",
            strategy_name="TestStrategy",
            symbols=["BTC/USDT"],
            timeframe="15m",
            run_timestamp=datetime(2024, 1, 1, 12, 0, 0),
            initial_capital=Decimal("100000"),
            final_equity=Decimal("110000"),
            total_pnl=Decimal("10000"),
            total_return=0.1,
        )

        assert summary.run_id == "20240101_120000"
        assert summary.strategy_name == "TestStrategy"
        assert summary.total_return == 0.1

    def test_summary_to_dict(self) -> None:
        """测试摘要转字典"""
        summary = BacktestSummary(
            run_id="20240101_120000",
            strategy_name="TestStrategy",
            symbols=["BTC/USDT", "ETH/USDT"],
            timeframe="1h",
            run_timestamp=datetime(2024, 1, 1, 12, 0, 0),
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
        )

        d = summary.to_dict()

        assert d["run_id"] == "20240101_120000"
        assert len(d["symbols"]) == 2
        assert "metrics" in d

    def test_summary_with_metrics(self) -> None:
        """测试带指标的摘要"""
        metrics = PerformanceMetrics(
            sharpe_ratio=1.5,
            sortino_ratio=2.0,
            max_drawdown=0.15,
        )

        summary = BacktestSummary(
            run_id="test",
            strategy_name="TestStrategy",
            symbols=[],
            timeframe="15m",
            run_timestamp=datetime.now(),
            metrics=metrics,
        )

        assert summary.metrics.sharpe_ratio == 1.5
        assert summary.metrics.max_drawdown == 0.15


class TestReportConfig:
    """ReportConfig 配置测试"""

    def test_default_config(self) -> None:
        """测试默认配置"""
        config = ReportConfig()

        assert config.output_dir == "reports"
        assert config.write_to_influx is True
        assert config.save_parquet is True
        assert config.save_json is True

    def test_custom_config(self) -> None:
        """测试自定义配置"""
        config = ReportConfig(
            output_dir="/tmp/reports",
            write_to_influx=False,
            save_parquet=False,
        )

        assert config.output_dir == "/tmp/reports"
        assert config.write_to_influx is False

    def test_config_to_dict(self) -> None:
        """测试配置转字典"""
        config = ReportConfig()
        d = config.to_dict()

        assert "output_dir" in d
        assert "write_to_influx" in d


class TestReportGenerator:
    """ReportGenerator 报告生成器测试"""

    def _create_mock_result(self) -> BacktestResult:
        """创建模拟回测结果"""
        config = BacktestConfig(
            initial_capital=Decimal("100000"),
            slippage_pct=Decimal("0.001"),
        )
        strategy_config = StrategyConfig(
            name="TestStrategy",
            symbols=["BTC/USDT"],
            timeframes=["15m"],
        )

        # 创建权益曲线
        equity_curve = [
            EquityPoint(
                timestamp=datetime(2024, 1, 1, i, 0, 0),
                equity=Decimal(str(100000 + i * 100)),
                cash=Decimal(str(50000 + i * 50)),
                position_value=Decimal(str(50000 + i * 50)),
                drawdown=Decimal("0"),
                drawdown_pct=Decimal("0"),
            )
            for i in range(24)
        ]

        # 创建成交记录
        trades = [
            Trade(
                timestamp=datetime(2024, 1, 1, 10, 0, 0),
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                price=Decimal("50000"),
                commission=Decimal("50"),
            ),
            Trade(
                timestamp=datetime(2024, 1, 1, 15, 0, 0),
                symbol="BTC/USDT",
                side=OrderSide.SELL,
                quantity=Decimal("1"),
                price=Decimal("52000"),
                commission=Decimal("52"),
            ),
        ]

        return BacktestResult(
            config=config,
            strategy_config=strategy_config,
            equity_curve=equity_curve,
            trades=trades,
            final_equity=Decimal("102300"),
            final_cash=Decimal("102300"),
            final_positions={},
            total_trades=2,
            total_commission=Decimal("102"),
            start_time=datetime(2024, 1, 1, 0, 0, 0),
            end_time=datetime(2024, 1, 1, 23, 0, 0),
            run_duration_seconds=0.5,
        )

    def test_generate_summary(self) -> None:
        """测试生成摘要"""
        result = self._create_mock_result()
        generator = ReportGenerator()

        summary = generator.generate_summary(result, run_id="test_run")

        assert summary.run_id == "test_run"
        assert summary.strategy_name == "TestStrategy"
        assert summary.initial_capital == Decimal("100000")
        assert summary.final_equity == Decimal("102300")

    def test_generate_summary_auto_run_id(self) -> None:
        """测试自动生成运行ID"""
        result = self._create_mock_result()
        generator = ReportGenerator()

        summary = generator.generate_summary(result)

        # 应该自动生成 run_id
        assert summary.run_id is not None
        assert len(summary.run_id) > 0

    def test_generate_summary_calculates_metrics(self) -> None:
        """测试摘要计算指标"""
        result = self._create_mock_result()
        generator = ReportGenerator()

        summary = generator.generate_summary(result)

        # 应该有绩效指标
        assert summary.metrics is not None
        assert isinstance(summary.metrics, PerformanceMetrics)

    def test_generate_report_creates_files(self) -> None:
        """测试生成报告创建文件"""
        result = self._create_mock_result()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = ReportConfig(
                output_dir=tmpdir,
                write_to_influx=False,  # 跳过 InfluxDB
                save_parquet=True,
                save_json=True,
            )
            generator = ReportGenerator(config=config)

            report = generator.generate_report(result, run_id="test_files")

            # 检查返回内容
            assert "summary" in report
            assert "saved_files" in report
            assert len(report["saved_files"]) > 0

            # 检查文件存在
            output_path = Path(tmpdir) / "test_files"
            assert output_path.exists()
            assert (output_path / "summary.json").exists()

    def test_generate_report_json_content(self) -> None:
        """测试 JSON 报告内容"""
        result = self._create_mock_result()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = ReportConfig(
                output_dir=tmpdir,
                write_to_influx=False,
                save_parquet=False,
                save_json=True,
            )
            generator = ReportGenerator(config=config)
            generator.generate_report(result, run_id="test_json")

            # 读取并验证 JSON
            json_path = Path(tmpdir) / "test_json" / "summary.json"
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)

            assert data["run_id"] == "test_json"
            assert data["strategy_name"] == "TestStrategy"

    def test_generate_report_parquet_content(self) -> None:
        """测试 Parquet 报告内容"""
        import pandas as pd

        result = self._create_mock_result()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = ReportConfig(
                output_dir=tmpdir,
                write_to_influx=False,
                save_parquet=True,
                save_json=False,
            )
            generator = ReportGenerator(config=config)
            generator.generate_report(result, run_id="test_parquet")

            # 读取并验证 Parquet
            equity_path = Path(tmpdir) / "test_parquet" / "equity_curve.parquet"
            equity_df = pd.read_parquet(equity_path)

            assert len(equity_df) == 24
            assert "equity" in equity_df.columns
            assert "cash" in equity_df.columns

            # 验证交易记录
            trades_path = Path(tmpdir) / "test_parquet" / "trades.parquet"
            trades_df = pd.read_parquet(trades_path)

            assert len(trades_df) == 2

    @patch("src.data.storage.influx_store.InfluxStore")
    def test_generate_report_writes_to_influx(
        self, mock_influx_class: MagicMock
    ) -> None:
        """测试写入 InfluxDB"""
        result = self._create_mock_result()

        # 设置模拟
        mock_store = MagicMock()
        mock_influx_class.return_value = mock_store

        with tempfile.TemporaryDirectory() as tmpdir:
            config = ReportConfig(
                output_dir=tmpdir,
                write_to_influx=True,
                save_parquet=False,
                save_json=False,
            )
            generator = ReportGenerator(config=config)
            generator.generate_report(result, run_id="test_influx")

            # 验证调用
            mock_store.write_backtest_summary.assert_called_once()
            mock_store.write_backtest_equity.assert_called_once()

    def test_generate_report_empty_equity_curve(self) -> None:
        """测试空权益曲线"""
        config = BacktestConfig()
        strategy_config = StrategyConfig(
            name="EmptyTest",
            symbols=[],
            timeframes=["15m"],
        )

        result = BacktestResult(
            config=config,
            strategy_config=strategy_config,
            equity_curve=[],
            trades=[],
            final_equity=Decimal("100000"),
            final_cash=Decimal("100000"),
        )

        generator = ReportGenerator()
        summary = generator.generate_summary(result)

        assert summary.strategy_name == "EmptyTest"
        # 空曲线应该返回默认指标
        assert summary.metrics is not None


class TestTextReport:
    """文本报告测试"""

    def test_generate_text_report(self) -> None:
        """测试生成文本报告"""
        summary = BacktestSummary(
            run_id="test",
            strategy_name="MyStrategy",
            symbols=["BTC/USDT"],
            timeframe="15m",
            run_timestamp=datetime(2024, 1, 1, 12, 0, 0),
            initial_capital=Decimal("100000"),
            final_equity=Decimal("115000"),
            total_pnl=Decimal("15000"),
            total_return=0.15,
            metrics=PerformanceMetrics(
                sharpe_ratio=1.8,
                sortino_ratio=2.5,
                max_drawdown=0.08,
                annualized_return=0.45,
                volatility=0.25,
                trade_stats=TradeStats(
                    total_trades=50,
                    winning_trades=30,
                    losing_trades=20,
                    total_commission=Decimal("500"),
                ),
            ),
        )

        text = generate_text_report(summary)

        assert "MyStrategy" in text
        assert "BTC/USDT" in text
        assert "15,000" in text  # total_pnl
        assert "15.00%" in text  # total_return
        assert "1.8" in text  # sharpe

    def test_text_report_contains_all_sections(self) -> None:
        """测试文本报告包含所有部分"""
        summary = BacktestSummary(
            run_id="test",
            strategy_name="TestStrategy",
            symbols=[],
            timeframe="1h",
            run_timestamp=datetime.now(),
        )

        text = generate_text_report(summary)

        assert "基本信息" in text
        assert "资金情况" in text
        assert "绩效指标" in text
        assert "交易统计" in text


class TestMarkdownReport:
    """Markdown 报告测试"""

    def test_generate_markdown_report(self) -> None:
        """测试生成 Markdown 报告"""
        summary = BacktestSummary(
            run_id="md_test",
            strategy_name="MDStrategy",
            symbols=["ETH/USDT"],
            timeframe="1h",
            run_timestamp=datetime(2024, 1, 1, 12, 0, 0),
            initial_capital=Decimal("50000"),
            final_equity=Decimal("60000"),
            total_pnl=Decimal("10000"),
            total_return=0.2,
        )

        md = generate_markdown_report(summary)

        # 检查 Markdown 格式
        assert "# 回测报告" in md
        assert "## 基本信息" in md
        assert "| 项目 | 值 |" in md
        assert "MDStrategy" in md

    def test_markdown_report_table_format(self) -> None:
        """测试 Markdown 表格格式"""
        summary = BacktestSummary(
            run_id="table_test",
            strategy_name="TableStrategy",
            symbols=["BTC/USDT"],
            timeframe="15m",
            run_timestamp=datetime.now(),
        )

        md = generate_markdown_report(summary)

        # 验证表格结构
        lines = md.split("\n")
        table_headers = [line for line in lines if "|---" in line]
        assert len(table_headers) >= 3  # 至少有3个表格

    def test_markdown_report_contains_metrics(self) -> None:
        """测试 Markdown 报告包含指标"""
        summary = BacktestSummary(
            run_id="metrics_test",
            strategy_name="MetricsStrategy",
            symbols=[],
            timeframe="1h",
            run_timestamp=datetime.now(),
            metrics=PerformanceMetrics(
                sharpe_ratio=2.0,
                max_drawdown=0.1,
            ),
        )

        md = generate_markdown_report(summary)

        assert "夏普比率" in md
        assert "最大回撤" in md


class TestTradeStatsCalculation:
    """交易统计计算测试"""

    def test_trade_stats_from_trades(self) -> None:
        """测试从成交记录计算统计"""
        trades = [
            Trade(
                timestamp=datetime.now(),
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                price=Decimal("50000"),
                commission=Decimal("50"),
            ),
            Trade(
                timestamp=datetime.now(),
                symbol="BTC/USDT",
                side=OrderSide.SELL,
                quantity=Decimal("1"),
                price=Decimal("52000"),
                commission=Decimal("52"),
            ),
        ]

        config = BacktestConfig()
        strategy_config = StrategyConfig(
            name="Test",
            symbols=["BTC/USDT"],
            timeframes=["15m"],
        )

        result = BacktestResult(
            config=config,
            strategy_config=strategy_config,
            equity_curve=[
                EquityPoint(
                    timestamp=datetime.now(),
                    equity=Decimal("100000"),
                    cash=Decimal("100000"),
                    position_value=Decimal("0"),
                )
            ],
            trades=trades,
            final_equity=Decimal("101898"),
            final_cash=Decimal("101898"),
        )

        generator = ReportGenerator()
        summary = generator.generate_summary(result)

        # 验证交易统计
        assert summary.metrics.trade_stats.total_trades == 2
        assert summary.metrics.trade_stats.total_commission == Decimal("102")
