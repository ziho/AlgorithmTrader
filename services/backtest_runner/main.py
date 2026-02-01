"""
Backtest Runner 服务入口

运行方式:
    python -m services.backtest_runner.main

    # 运行单个回测
    python -m services.backtest_runner.main --strategy dual_ma --symbol BTC/USDT --days 30

    # 从配置文件批量运行
    python -m services.backtest_runner.main --config config/backtests.json

    # 扫描参数
    python -m services.backtest_runner.main --strategy dual_ma --symbol BTC/USDT \
        --scan-params '{"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}'
"""

import argparse
import asyncio
import json
import signal
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.backtest.reports import ReportConfig, ReportGenerator
from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import configure_logging, get_logger
from src.strategy.base import StrategyBase, StrategyConfig
from src.strategy.examples import (
    BollingerBandsStrategy,
    DonchianBreakoutStrategy,
    DualMAStrategy,
    RSIMeanReversionStrategy,
    ZScoreStrategy,
)

logger = get_logger(__name__)

# 策略映射
STRATEGY_MAP: dict[str, type[StrategyBase]] = {
    "dual_ma": DualMAStrategy,
    "donchian": DonchianBreakoutStrategy,
    "bollinger": BollingerBandsStrategy,
    "rsi_mr": RSIMeanReversionStrategy,
    "zscore": ZScoreStrategy,
}


@dataclass
class BacktestTask:
    """回测任务"""

    id: str
    strategy_name: str
    strategy_class: type[StrategyBase]
    symbols: list[str]
    timeframe: str = "15m"
    start_date: datetime | None = None
    end_date: datetime | None = None
    initial_capital: Decimal = Decimal("100000")
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed
    result: BacktestResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


@dataclass
class BacktestRunnerConfig:
    """回测运行器配置"""

    # 输出
    output_dir: Path = field(default_factory=lambda: Path("reports"))
    write_to_influx: bool = False

    # 回测默认配置
    default_capital: Decimal = Decimal("100000")
    default_commission: Decimal = Decimal("0.001")
    default_slippage: Decimal = Decimal("0.0005")

    # 并行
    max_concurrent: int = 4


class BacktestRunner:
    """
    批量回测运行器

    支持:
    - 单策略回测
    - 多参数扫描
    - 批量配置运行
    - 结果报告生成
    """

    def __init__(self, config: BacktestRunnerConfig | None = None):
        self.config = config or BacktestRunnerConfig()
        self._parquet_store = ParquetStore()
        self._tasks: list[BacktestTask] = []
        self._results: list[BacktestResult] = []
        self._shutdown = False

        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "backtest_runner_initialized",
            output_dir=str(self.config.output_dir),
            max_concurrent=self.config.max_concurrent,
        )

    def _load_data(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """加载历史数据"""
        # 解析 symbol
        if "/" in symbol:
            base, quote = symbol.split("/")
        else:
            base = symbol
            quote = "USDT"

        sym = Symbol(exchange=Exchange.OKX, base=base, quote=quote)
        tf = Timeframe(timeframe)

        df = self._parquet_store.read(sym, tf, start=start, end=end)

        if df.empty:
            logger.warning("no_data_found", symbol=symbol, timeframe=timeframe)

        return df

    def add_task(self, task: BacktestTask) -> None:
        """添加回测任务"""
        self._tasks.append(task)
        logger.info(
            "backtest_task_added",
            task_id=task.id,
            strategy=task.strategy_name,
            symbols=task.symbols,
        )

    def create_task(
        self,
        strategy_name: str,
        symbols: list[str],
        days: int = 30,
        params: dict[str, Any] | None = None,
        initial_capital: float = 100000,
    ) -> BacktestTask:
        """创建回测任务"""
        import uuid

        if strategy_name not in STRATEGY_MAP:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        task = BacktestTask(
            id=f"bt_{uuid.uuid4().hex[:8]}",
            strategy_name=strategy_name,
            strategy_class=STRATEGY_MAP[strategy_name],
            symbols=symbols,
            start_date=datetime.now(UTC) - timedelta(days=days),
            end_date=datetime.now(UTC),
            initial_capital=Decimal(str(initial_capital)),
            params=params or {},
        )

        self.add_task(task)
        return task

    def run_task(self, task: BacktestTask) -> BacktestResult | None:
        """运行单个回测任务"""
        task.status = "running"
        logger.info(
            "backtest_task_started",
            task_id=task.id,
            strategy=task.strategy_name,
        )

        try:
            # 加载数据
            data: dict[str, pd.DataFrame] = {}
            for symbol in task.symbols:
                df = self._load_data(
                    symbol,
                    task.timeframe,
                    start=task.start_date,
                    end=task.end_date,
                )
                if not df.empty:
                    data[symbol] = df

            if not data:
                raise ValueError("No data available for backtesting")

            # 创建策略实例
            strategy = task.strategy_class(
                config=StrategyConfig(
                    name=f"{task.strategy_name}_{task.id}",
                    symbols=task.symbols,
                    params=task.params,
                )
            )

            # 配置回测引擎
            backtest_config = BacktestConfig(
                initial_capital=task.initial_capital,
                commission_rate=self.config.default_commission,
                slippage_rate=self.config.default_slippage,
            )

            engine = BacktestEngine(config=backtest_config)

            # 运行回测
            result = engine.run(strategy=strategy, data=data)

            task.result = result
            task.status = "completed"
            task.completed_at = datetime.now(UTC)

            logger.info(
                "backtest_task_completed",
                task_id=task.id,
                total_return=f"{result.summary.total_return:.2%}",
                sharpe=f"{result.summary.sharpe_ratio:.2f}",
                max_dd=f"{result.summary.max_drawdown:.2%}",
            )

            return result

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.completed_at = datetime.now(UTC)
            logger.error(
                "backtest_task_failed",
                task_id=task.id,
                error=str(e),
            )
            return None

    def run_all(self) -> list[BacktestResult]:
        """运行所有任务"""
        results = []

        for task in self._tasks:
            if self._shutdown:
                logger.info("backtest_runner_shutdown")
                break

            result = self.run_task(task)
            if result:
                results.append(result)
                self._results.append(result)

        return results

    async def run_all_async(self) -> list[BacktestResult]:
        """异步运行所有任务（支持并行）"""
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        async def run_with_semaphore(task: BacktestTask) -> BacktestResult | None:
            async with semaphore:
                return await asyncio.to_thread(self.run_task, task)

        tasks = [run_with_semaphore(task) for task in self._tasks]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for r in completed:
            if isinstance(r, BacktestResult):
                results.append(r)
                self._results.append(r)

        return results

    def generate_reports(self) -> list[Path]:
        """为所有结果生成报告"""
        report_paths = []

        report_config = ReportConfig(
            output_dir=self.config.output_dir,
            include_trades=True,
            write_to_influx=self.config.write_to_influx,
        )
        generator = ReportGenerator(report_config)

        for result in self._results:
            try:
                report = generator.generate_report(result)
                if report.html_path:
                    report_paths.append(report.html_path)
                    logger.info("report_generated", path=str(report.html_path))
            except Exception as e:
                logger.error("report_generation_failed", error=str(e))

        return report_paths

    def scan_parameters(
        self,
        strategy_name: str,
        symbols: list[str],
        param_space: dict[str, list[Any]],
        days: int = 30,
    ) -> list[BacktestResult]:
        """
        参数扫描

        Args:
            strategy_name: 策略名称
            symbols: 交易对列表
            param_space: 参数空间，如 {"fast_period": [5, 10, 15], "slow_period": [20, 30]}
            days: 回测天数

        Returns:
            所有组合的回测结果
        """
        # 生成所有参数组合
        keys = list(param_space.keys())
        values = list(param_space.values())
        combinations = list(product(*values))

        logger.info(
            "parameter_scan_started",
            strategy=strategy_name,
            combinations=len(combinations),
        )

        for combo in combinations:
            params = dict(zip(keys, combo, strict=True))
            self.create_task(
                strategy_name=strategy_name,
                symbols=symbols,
                days=days,
                params=params,
            )

        return self.run_all()

    def get_best_result(
        self, metric: str = "sharpe_ratio"
    ) -> tuple[BacktestTask, BacktestResult] | None:
        """获取最佳结果"""
        best_task = None
        best_result = None
        best_value = float("-inf")

        for task in self._tasks:
            if task.result is None:
                continue

            value = getattr(task.result.summary, metric, None)
            if value is not None and value > best_value:
                best_value = value
                best_task = task
                best_result = task.result

        return (best_task, best_result) if best_task else None

    def summary(self) -> dict[str, Any]:
        """获取运行摘要"""
        completed = [t for t in self._tasks if t.status == "completed"]
        failed = [t for t in self._tasks if t.status == "failed"]

        return {
            "total_tasks": len(self._tasks),
            "completed": len(completed),
            "failed": len(failed),
            "pending": len(self._tasks) - len(completed) - len(failed),
            "results": [
                {
                    "task_id": t.id,
                    "strategy": t.strategy_name,
                    "params": t.params,
                    "total_return": (
                        t.result.summary.total_return if t.result else None
                    ),
                    "sharpe_ratio": (
                        t.result.summary.sharpe_ratio if t.result else None
                    ),
                    "max_drawdown": (
                        t.result.summary.max_drawdown if t.result else None
                    ),
                }
                for t in completed
            ],
        }

    def shutdown(self) -> None:
        """停止运行"""
        self._shutdown = True


def load_config_file(config_path: Path) -> list[dict[str, Any]]:
    """从配置文件加载回测任务"""
    with open(config_path) as f:
        data = json.load(f)
    return data.get("backtests", [])


def main():
    """Backtest Runner 服务主入口"""
    configure_logging()

    parser = argparse.ArgumentParser(description="AlgorithmTrader Backtest Runner")
    parser.add_argument("--strategy", type=str, help="Strategy name")
    parser.add_argument("--symbol", type=str, default="BTC/USDT", help="Trading pair")
    parser.add_argument("--days", type=int, default=30, help="Backtest period in days")
    parser.add_argument("--capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument(
        "--scan-params", type=str, help="Parameter space for scanning (JSON)"
    )
    parser.add_argument(
        "--output", type=str, default="reports", help="Output directory"
    )
    parser.add_argument(
        "--influx", action="store_true", help="Write results to InfluxDB"
    )

    args = parser.parse_args()

    # 创建运行器
    runner_config = BacktestRunnerConfig(
        output_dir=Path(args.output),
        write_to_influx=args.influx,
        default_capital=Decimal(str(args.capital)),
    )
    runner = BacktestRunner(runner_config)

    # 信号处理
    def signal_handler(signum, frame):
        logger.info("shutdown_signal_received", signal=signum)
        runner.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if args.config:
            # 从配置文件加载
            config_path = Path(args.config)
            if config_path.exists():
                tasks = load_config_file(config_path)
                for task_config in tasks:
                    strategy = task_config.get("strategy", "dual_ma")
                    symbols = task_config.get("symbols", ["BTC/USDT"])
                    days = task_config.get("days", 30)
                    params = task_config.get("params", {})
                    runner.create_task(
                        strategy_name=strategy,
                        symbols=symbols if isinstance(symbols, list) else [symbols],
                        days=days,
                        params=params,
                    )
            else:
                logger.error("config_file_not_found", path=str(config_path))
                sys.exit(1)

        elif args.scan_params and args.strategy:
            # 参数扫描模式
            param_space = json.loads(args.scan_params)
            symbols = args.symbol.split(",")
            runner.scan_parameters(
                strategy_name=args.strategy,
                symbols=symbols,
                param_space=param_space,
                days=args.days,
            )

        elif args.strategy:
            # 单个回测
            symbols = args.symbol.split(",")
            runner.create_task(
                strategy_name=args.strategy,
                symbols=symbols,
                days=args.days,
            )
            runner.run_all()

        else:
            # 默认：使用 dual_ma 策略
            runner.create_task(
                strategy_name="dual_ma",
                symbols=["BTC/USDT"],
                days=args.days,
            )
            runner.run_all()

        # 生成报告
        runner.generate_reports()

        # 输出摘要
        summary = runner.summary()
        logger.info(
            "backtest_run_complete",
            total=summary["total_tasks"],
            completed=summary["completed"],
            failed=summary["failed"],
        )

        # 输出最佳结果
        best = runner.get_best_result()
        if best:
            task, result = best
            logger.info(
                "best_result",
                strategy=task.strategy_name,
                params=task.params,
                sharpe=f"{result.summary.sharpe_ratio:.2f}",
                return_pct=f"{result.summary.total_return:.2%}",
            )

    except Exception as e:
        logger.exception("backtest_runner_error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
