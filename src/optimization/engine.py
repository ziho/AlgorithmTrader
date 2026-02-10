"""
优化引擎

核心优化逻辑
"""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.metrics import PerformanceMetrics
from src.optimization.methods import GridSearch, ParameterSpace, SearchMethod
from src.optimization.objectives import MaximizeSharpe, Objective
from src.strategy.base import StrategyBase as Strategy


@dataclass
class OptimizationConfig:
    """优化配置"""

    # 策略
    strategy_class: type[Strategy] = None
    strategy_name: str = ""  # 从注册表获取时使用

    # 参数空间
    param_space: ParameterSpace = field(default_factory=ParameterSpace)

    # 目标和方法
    objective: Objective = field(default_factory=MaximizeSharpe)
    search_method: SearchMethod = field(default_factory=GridSearch)

    # 执行设置
    n_jobs: int = 1  # 并行数（-1 = 全部 CPU）
    timeout_seconds: float = 0  # 超时（0 = 无限制）

    # 过滤条件
    min_trades: int = 5  # 最小交易数
    min_sharpe: float = -999  # 最小夏普比率

    def validate(self):
        """验证配置"""
        if self.strategy_class is None and not self.strategy_name:
            raise ValueError("必须指定 strategy_class 或 strategy_name")


@dataclass
class TrialResult:
    """单次试验结果"""

    trial_id: int
    params: dict[str, Any]
    metrics: PerformanceMetrics | None = None
    objective_value: float = float("-inf")
    error: str | None = None
    duration_ms: float = 0


@dataclass
class OptimizationResult:
    """优化结果"""

    config: OptimizationConfig = None

    # 最佳结果
    best_params: dict[str, Any] = field(default_factory=dict)
    best_metrics: PerformanceMetrics | None = None
    best_objective_value: float = float("-inf")

    # 所有试验
    trials: list[TrialResult] = field(default_factory=list)

    # 统计
    total_trials: int = 0
    successful_trials: int = 0
    failed_trials: int = 0

    # 时间
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_duration_seconds: float = 0

    def add_trial(self, trial: TrialResult):
        """添加试验结果"""
        self.trials.append(trial)
        self.total_trials += 1

        if trial.error:
            self.failed_trials += 1
            return

        self.successful_trials += 1

        # 更新最佳结果
        if self.config and self.config.objective.is_better(
            trial.objective_value, self.best_objective_value
        ):
            self.best_objective_value = trial.objective_value
            self.best_params = trial.params.copy()
            self.best_metrics = trial.metrics

    def get_top_n(self, n: int = 10) -> list[TrialResult]:
        """获取前 N 个最佳结果"""
        valid_trials = [t for t in self.trials if t.error is None]
        sorted_trials = sorted(
            valid_trials,
            key=lambda t: t.objective_value,
            reverse=not self.config.objective.minimize if self.config else True,
        )
        return sorted_trials[:n]

    def to_dataframe(self) -> pd.DataFrame:
        """转换为 DataFrame"""
        records = []
        for trial in self.trials:
            record = {
                "trial_id": trial.trial_id,
                "objective_value": trial.objective_value,
                "duration_ms": trial.duration_ms,
                "error": trial.error,
            }
            record.update(trial.params)

            if trial.metrics:
                record["sharpe_ratio"] = trial.metrics.sharpe_ratio
                record["total_return"] = trial.metrics.total_return
                record["max_drawdown"] = trial.metrics.max_drawdown
                record["win_rate"] = trial.metrics.trade_stats.win_rate
                record["total_trades"] = trial.metrics.trade_stats.total_trades

            records.append(record)

        return pd.DataFrame(records)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "best_params": self.best_params,
            "best_objective_value": self.best_objective_value,
            "best_metrics": self.best_metrics.to_dict() if self.best_metrics else None,
            "total_trials": self.total_trials,
            "successful_trials": self.successful_trials,
            "failed_trials": self.failed_trials,
            "total_duration_seconds": self.total_duration_seconds,
        }


class OptimizationEngine:
    """
    参数优化引擎

    支持:
    - 多种搜索方法（网格、随机、LHS）
    - 多种目标函数
    - 并行执行
    - 进度回调
    """

    def __init__(self, config: OptimizationConfig):
        self.config = config
        self.config.validate()
        self._progress_callback: Callable[[int, int], None] | None = None
        self._stop_requested = False

    def on_progress(self, callback: Callable[[int, int], None]):
        """设置进度回调"""
        self._progress_callback = callback

    def stop(self):
        """请求停止优化"""
        self._stop_requested = True

    def run(
        self,
        data: dict[str, pd.DataFrame],
        backtest_config: BacktestConfig | None = None,
    ) -> OptimizationResult:
        """
        执行优化

        Args:
            data: 回测数据字典 {symbol: DataFrame}
            backtest_config: 回测配置

        Returns:
            OptimizationResult
        """
        self._stop_requested = False
        result = OptimizationResult(config=self.config)
        result.started_at = datetime.now()

        bt_config = backtest_config or BacktestConfig()
        total_combinations = self.config.search_method.estimate_total(
            self.config.param_space
        )

        trial_id = 0
        for params in self.config.search_method.generate(self.config.param_space):
            if self._stop_requested:
                break

            trial = self._run_single_trial(trial_id, params, data, bt_config)
            result.add_trial(trial)

            trial_id += 1
            if self._progress_callback:
                self._progress_callback(trial_id, total_combinations)

        result.finished_at = datetime.now()
        result.total_duration_seconds = (
            result.finished_at - result.started_at
        ).total_seconds()

        return result

    def _run_single_trial(
        self,
        trial_id: int,
        params: dict[str, Any],
        data: dict[str, pd.DataFrame],
        bt_config: BacktestConfig,
    ) -> TrialResult:
        """执行单次试验"""
        start_time = time.time()
        trial = TrialResult(trial_id=trial_id, params=params.copy())

        try:
            # 创建策略实例
            from src.strategy.base import StrategyConfig

            strategy_config = StrategyConfig(
                name=f"{self.config.strategy_name or 'opt'}_{trial_id}",
                params=params,
            )
            strategy = self.config.strategy_class(config=strategy_config)

            # 运行回测
            engine = BacktestEngine(config=bt_config)
            bt_result = engine.run_with_data(
                strategy=strategy,
                data=data,
                timeframe="15m",  # 默认时间框架
            )

            # 使用 BacktestResult.summary 获取指标
            summary = bt_result.summary

            # 创建 PerformanceMetrics 对象
            from src.backtest.metrics import TradeStats

            metrics = PerformanceMetrics(
                sharpe_ratio=summary.sharpe_ratio,
                sortino_ratio=summary.sortino_ratio,
                calmar_ratio=summary.calmar_ratio,
                total_return=summary.total_return,
                annualized_return=summary.annualized_return,
                max_drawdown=summary.max_drawdown,
                trade_stats=TradeStats(
                    total_trades=summary.total_trades,
                ),
            )

            # 检查过滤条件
            if metrics.trade_stats.total_trades < self.config.min_trades:
                trial.error = f"交易数不足: {metrics.trade_stats.total_trades} < {self.config.min_trades}"
            elif metrics.sharpe_ratio < self.config.min_sharpe:
                trial.error = f"夏普比率过低: {metrics.sharpe_ratio:.2f} < {self.config.min_sharpe}"
            else:
                trial.metrics = metrics
                trial.objective_value = self.config.objective.evaluate(metrics)

        except Exception as e:
            trial.error = str(e)

        trial.duration_ms = (time.time() - start_time) * 1000
        return trial

    async def run_async(
        self,
        data: dict[str, pd.DataFrame],
        backtest_config: BacktestConfig | None = None,
    ) -> OptimizationResult:
        """
        异步执行优化（支持并行）

        Args:
            data: 回测数据字典 {symbol: DataFrame}
            backtest_config: 回测配置

        Returns:
            OptimizationResult
        """
        self._stop_requested = False
        result = OptimizationResult(config=self.config)
        result.started_at = datetime.now()

        bt_config = backtest_config or BacktestConfig()
        total_combinations = self.config.search_method.estimate_total(
            self.config.param_space
        )

        # 收集所有参数组合
        all_params = list(self.config.search_method.generate(self.config.param_space))

        if self.config.n_jobs == 1:
            # 串行执行
            for trial_id, params in enumerate(all_params):
                if self._stop_requested:
                    break

                trial = self._run_single_trial(trial_id, params, data, bt_config)
                result.add_trial(trial)

                if self._progress_callback:
                    self._progress_callback(trial_id + 1, total_combinations)
        else:
            # 并行执行
            n_jobs = self.config.n_jobs if self.config.n_jobs > 0 else None

            with ThreadPoolExecutor(max_workers=n_jobs) as executor:
                futures = []
                for trial_id, params in enumerate(all_params):
                    future = executor.submit(
                        self._run_single_trial, trial_id, params, data, bt_config
                    )
                    futures.append(future)

                for i, future in enumerate(futures):
                    if self._stop_requested:
                        break

                    trial = future.result()
                    result.add_trial(trial)

                    if self._progress_callback:
                        self._progress_callback(i + 1, total_combinations)

        result.finished_at = datetime.now()
        result.total_duration_seconds = (
            result.finished_at - result.started_at
        ).total_seconds()

        return result
