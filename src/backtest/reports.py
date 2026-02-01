"""
回测报告

职责:
- 生成回测摘要
- 写入 InfluxDB (便于 Grafana 对比)
- 详细结果落盘 (Parquet/JSON)
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from src.backtest.metrics import MetricsCalculator, PerformanceMetrics, TradeStats
from src.ops.logging import get_logger

if TYPE_CHECKING:
    from src.backtest.engine import BacktestResult

logger = get_logger(__name__)


@dataclass
class ReportConfig:
    """报告配置"""

    # 输出目录
    output_dir: str = "reports"

    # 是否写入 InfluxDB
    write_to_influx: bool = True

    # 是否保存 Parquet 格式
    save_parquet: bool = True

    # 是否保存 JSON 格式
    save_json: bool = True

    # 是否生成 HTML 报告（预留）
    generate_html: bool = False

    # 报告名称前缀
    name_prefix: str = "backtest"

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "write_to_influx": self.write_to_influx,
            "save_parquet": self.save_parquet,
            "save_json": self.save_json,
            "generate_html": self.generate_html,
            "name_prefix": self.name_prefix,
        }


@dataclass
class BacktestSummary:
    """回测摘要"""

    # 基本信息
    run_id: str
    strategy_name: str
    symbols: list[str]
    timeframe: str
    run_timestamp: datetime

    # 时间范围
    start_date: datetime | None = None
    end_date: datetime | None = None
    run_duration_seconds: float = 0.0

    # 资金信息
    initial_capital: Decimal = Decimal("100000")
    final_equity: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    total_return: float = 0.0

    # 绩效指标
    metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)

    # 配置信息
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "symbols": self.symbols,
            "timeframe": self.timeframe,
            "run_timestamp": self.run_timestamp.isoformat(),
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "run_duration_seconds": self.run_duration_seconds,
            "initial_capital": str(self.initial_capital),
            "final_equity": str(self.final_equity),
            "total_pnl": str(self.total_pnl),
            "total_return": round(self.total_return, 6),
            "metrics": self.metrics.to_dict(),
            "config": self.config,
        }


class ReportGenerator:
    """
    回测报告生成器

    功能:
    - 从 BacktestResult 生成摘要
    - 导出权益曲线到 Parquet/CSV
    - 导出成交记录到 Parquet/CSV
    - 写入 InfluxDB 用于 Grafana 展示
    """

    def __init__(
        self,
        config: ReportConfig | None = None,
        metrics_calculator: MetricsCalculator | None = None,
    ):
        self.config = config or ReportConfig()
        self.metrics_calculator = metrics_calculator or MetricsCalculator()

    def generate_summary(
        self,
        result: "BacktestResult",
        run_id: str | None = None,
    ) -> BacktestSummary:
        """
        从回测结果生成摘要

        Args:
            result: 回测结果对象
            run_id: 运行ID（如不提供则自动生成）

        Returns:
            回测摘要
        """
        # 生成 run_id
        if run_id is None:
            run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

        # 提取符号列表
        symbols = list(result.final_positions.keys()) if result.final_positions else []
        if not symbols and result.trades:
            symbols = list({t.symbol for t in result.trades})

        # 计算绩效指标
        metrics = self._calculate_metrics(result)

        # 计算总收益
        initial_capital = result.config.initial_capital
        total_pnl = result.final_equity - initial_capital
        total_return = (
            float(total_pnl / initial_capital) if initial_capital > 0 else 0.0
        )

        summary = BacktestSummary(
            run_id=run_id,
            strategy_name=result.strategy_config.name,
            symbols=symbols,
            timeframe=result.strategy_config.timeframe,
            run_timestamp=datetime.now(UTC),
            start_date=result.start_time,
            end_date=result.end_time,
            run_duration_seconds=result.run_duration_seconds,
            initial_capital=initial_capital,
            final_equity=result.final_equity,
            total_pnl=total_pnl,
            total_return=total_return,
            metrics=metrics,
            config={
                "backtest": result.config.to_dict(),
                "strategy": result.strategy_config.to_dict(),
            },
        )

        return summary

    def _calculate_metrics(self, result: "BacktestResult") -> PerformanceMetrics:
        """计算绩效指标"""
        import numpy as np

        # 提取权益序列
        if not result.equity_curve:
            return PerformanceMetrics()

        equity_values = np.array(
            [float(ep.equity) for ep in result.equity_curve],
            dtype=np.float64,
        )
        timestamps = [ep.timestamp for ep in result.equity_curve]

        # 使用 MetricsCalculator 计算
        metrics = self.metrics_calculator.calculate_all(
            equity_values=equity_values,
            timestamps=timestamps,
        )

        # 计算交易统计
        if result.trades:
            trade_stats = self._calculate_trade_stats(result.trades)
            metrics.trade_stats = trade_stats

        return metrics

    def _calculate_trade_stats(self, trades: list[Any]) -> TradeStats:
        """计算交易统计"""
        total_trades = len(trades)
        winning_trades = 0
        losing_trades = 0
        gross_profit = Decimal("0")
        gross_loss = Decimal("0")
        total_commission = Decimal("0")

        # 需要计算每笔交易的盈亏
        # 由于 Trade 对象本身不包含盈亏信息，这里只统计手续费
        for trade in trades:
            total_commission += trade.commission

        # 返回基础统计（完整的交易盈亏需要配合持仓信息）
        return TradeStats(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=Decimal("0"),
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            total_commission=total_commission,
        )

    def generate_report(
        self,
        result: "BacktestResult",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """
        生成完整报告

        Args:
            result: 回测结果
            run_id: 运行ID

        Returns:
            报告内容字典
        """
        # 生成摘要
        summary = self.generate_summary(result, run_id)

        # 确保输出目录存在
        output_dir = Path(self.config.output_dir) / summary.run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # 保存各类数据
        saved_files: list[str] = []

        if self.config.save_json:
            json_path = self._save_json(summary, result, output_dir)
            saved_files.append(str(json_path))

        if self.config.save_parquet:
            parquet_paths = self._save_parquet(result, output_dir)
            saved_files.extend([str(p) for p in parquet_paths])

        if self.config.write_to_influx:
            self._write_to_influx(summary, result)

        logger.info(
            "backtest_report_generated",
            run_id=summary.run_id,
            strategy=summary.strategy_name,
            total_return=summary.total_return,
            sharpe=summary.metrics.sharpe_ratio,
            saved_files=saved_files,
        )

        return {
            "summary": summary.to_dict(),
            "saved_files": saved_files,
        }

    def _save_json(
        self,
        summary: BacktestSummary,
        result: "BacktestResult",  # noqa: ARG002
        output_dir: Path,
    ) -> Path:
        """保存 JSON 摘要"""
        json_path = output_dir / "summary.json"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2, ensure_ascii=False)

        logger.debug("saved_json_report", path=str(json_path))
        return json_path

    def _save_parquet(
        self,
        result: "BacktestResult",
        output_dir: Path,
    ) -> list[Path]:
        """保存 Parquet 数据"""
        saved_paths: list[Path] = []

        # 保存权益曲线
        if result.equity_curve:
            equity_df = pd.DataFrame(
                [
                    {
                        "timestamp": ep.timestamp,
                        "equity": float(ep.equity),
                        "cash": float(ep.cash),
                        "position_value": float(ep.position_value),
                        "drawdown": float(ep.drawdown),
                        "drawdown_pct": float(ep.drawdown_pct),
                    }
                    for ep in result.equity_curve
                ]
            )
            equity_path = output_dir / "equity_curve.parquet"
            equity_df.to_parquet(equity_path, engine="pyarrow")
            saved_paths.append(equity_path)
            logger.debug("saved_equity_parquet", path=str(equity_path))

        # 保存成交记录
        if result.trades:
            trades_df = pd.DataFrame([t.to_dict() for t in result.trades])
            trades_path = output_dir / "trades.parquet"
            trades_df.to_parquet(trades_path, engine="pyarrow")
            saved_paths.append(trades_path)
            logger.debug("saved_trades_parquet", path=str(trades_path))

        return saved_paths

    def _write_to_influx(
        self,
        summary: BacktestSummary,
        result: "BacktestResult",
    ) -> None:
        """写入 InfluxDB"""
        try:
            from src.data.storage.influx_store import InfluxStore

            store = InfluxStore(async_write=False)

            # 写入回测摘要
            store.write_backtest_summary(summary)

            # 写入权益曲线（采样以减少数据量）
            if result.equity_curve:
                store.write_backtest_equity(summary.run_id, result.equity_curve)

            logger.debug(
                "written_to_influx",
                run_id=summary.run_id,
                equity_points=len(result.equity_curve),
            )
        except Exception as e:
            logger.warning("failed_to_write_influx", error=str(e))


class DecimalEncoder(json.JSONEncoder):
    """支持 Decimal 的 JSON 编码器"""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def generate_text_report(summary: BacktestSummary) -> str:
    """
    生成文本格式报告

    Args:
        summary: 回测摘要

    Returns:
        格式化的文本报告
    """
    lines = [
        "=" * 60,
        f"回测报告: {summary.strategy_name}",
        "=" * 60,
        "",
        "基本信息",
        "-" * 40,
        f"运行ID: {summary.run_id}",
        f"交易对: {', '.join(summary.symbols)}",
        f"时间框架: {summary.timeframe}",
        f"回测时间: {summary.start_date} ~ {summary.end_date}",
        f"运行耗时: {summary.run_duration_seconds:.2f} 秒",
        "",
        "资金情况",
        "-" * 40,
        f"初始资金: {summary.initial_capital:,.2f}",
        f"最终权益: {summary.final_equity:,.2f}",
        f"总盈亏: {summary.total_pnl:+,.2f}",
        f"总收益率: {summary.total_return * 100:+.2f}%",
        "",
        "绩效指标",
        "-" * 40,
        f"年化收益: {summary.metrics.annualized_return * 100:.2f}%",
        f"年化波动: {summary.metrics.volatility * 100:.2f}%",
        f"最大回撤: {summary.metrics.max_drawdown * 100:.2f}%",
        f"夏普比率: {summary.metrics.sharpe_ratio:.2f}",
        f"索提诺比率: {summary.metrics.sortino_ratio:.2f}",
        f"卡尔玛比率: {summary.metrics.calmar_ratio:.2f}",
        "",
        "交易统计",
        "-" * 40,
        f"总交易次数: {summary.metrics.trade_stats.total_trades}",
        f"胜率: {summary.metrics.trade_stats.win_rate * 100:.2f}%",
        f"盈亏比: {summary.metrics.trade_stats.profit_factor:.2f}",
        f"总手续费: {summary.metrics.trade_stats.total_commission:,.2f}",
        "",
        "=" * 60,
    ]

    return "\n".join(lines)


def generate_markdown_report(summary: BacktestSummary) -> str:
    """
    生成 Markdown 格式报告

    Args:
        summary: 回测摘要

    Returns:
        Markdown 格式报告
    """
    md = f"""# 回测报告: {summary.strategy_name}

## 基本信息

| 项目 | 值 |
|------|-----|
| 运行ID | {summary.run_id} |
| 交易对 | {", ".join(summary.symbols)} |
| 时间框架 | {summary.timeframe} |
| 回测区间 | {summary.start_date} ~ {summary.end_date} |
| 运行耗时 | {summary.run_duration_seconds:.2f} 秒 |

## 资金情况

| 指标 | 值 |
|------|-----|
| 初始资金 | {summary.initial_capital:,.2f} |
| 最终权益 | {summary.final_equity:,.2f} |
| 总盈亏 | {summary.total_pnl:+,.2f} |
| 总收益率 | {summary.total_return * 100:+.2f}% |

## 绩效指标

| 指标 | 值 |
|------|-----|
| 年化收益 | {summary.metrics.annualized_return * 100:.2f}% |
| 年化波动 | {summary.metrics.volatility * 100:.2f}% |
| 最大回撤 | {summary.metrics.max_drawdown * 100:.2f}% |
| 夏普比率 | {summary.metrics.sharpe_ratio:.2f} |
| 索提诺比率 | {summary.metrics.sortino_ratio:.2f} |
| 卡尔玛比率 | {summary.metrics.calmar_ratio:.2f} |

## 交易统计

| 指标 | 值 |
|------|-----|
| 总交易次数 | {summary.metrics.trade_stats.total_trades} |
| 胜率 | {summary.metrics.trade_stats.win_rate * 100:.2f}% |
| 盈亏比 | {summary.metrics.trade_stats.profit_factor:.2f} |
| 总手续费 | {summary.metrics.trade_stats.total_commission:,.2f} |

---
*生成时间: {summary.run_timestamp}*
"""
    return md
