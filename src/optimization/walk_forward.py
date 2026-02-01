"""
Walk-Forward 验证

防止过拟合的验证方法
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.metrics import MetricsCalculator, PerformanceMetrics
from src.optimization.methods import SearchMethod
from src.optimization.objectives import Objective
from src.strategy.base import StrategyBase as Strategy


@dataclass
class WalkForwardConfig:
    """Walk-Forward 配置"""

    # 时间窗口
    train_period_days: int = 180  # 训练期（天）
    test_period_days: int = 30  # 测试期（天）

    # 滚动设置
    n_splits: int = 6  # 分割数
    gap_days: int = 0  # 训练和测试之间的间隔

    # 验证设置
    min_trades: int = 10  # 最小交易数
    max_parameter_difference: float = 0.3  # 最大参数差异（相对于范围）

    def validate(self):
        """验证配置"""
        if self.train_period_days <= 0:
            raise ValueError("训练期必须大于 0")
        if self.test_period_days <= 0:
            raise ValueError("测试期必须大于 0")
        if self.n_splits <= 0:
            raise ValueError("分割数必须大于 0")


@dataclass
class WalkForwardSplit:
    """单个 Walk-Forward 分割"""

    split_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    best_params: dict[str, Any] = field(default_factory=dict)
    train_metrics: PerformanceMetrics | None = None
    test_metrics: PerformanceMetrics | None = None


@dataclass
class WalkForwardResult:
    """Walk-Forward 验证结果"""

    config: WalkForwardConfig
    splits: list[WalkForwardSplit] = field(default_factory=list)

    # 汇总指标
    avg_train_sharpe: float = 0.0
    avg_test_sharpe: float = 0.0
    sharpe_decay: float = 0.0  # (训练-测试)/训练，衡量过拟合程度

    avg_train_return: float = 0.0
    avg_test_return: float = 0.0
    return_decay: float = 0.0

    parameter_stability: float = 0.0  # 参数稳定性评分 (0-1)

    is_robust: bool = False  # 是否通过稳健性检验

    def calculate_summary(self):
        """计算汇总指标"""
        if not self.splits:
            return

        valid_splits = [s for s in self.splits if s.train_metrics and s.test_metrics]
        if not valid_splits:
            return

        n = len(valid_splits)

        # 平均指标
        self.avg_train_sharpe = (
            sum(s.train_metrics.sharpe_ratio for s in valid_splits) / n
        )
        self.avg_test_sharpe = (
            sum(s.test_metrics.sharpe_ratio for s in valid_splits) / n
        )

        self.avg_train_return = (
            sum(s.train_metrics.total_return for s in valid_splits) / n
        )
        self.avg_test_return = (
            sum(s.test_metrics.total_return for s in valid_splits) / n
        )

        # 衰减率
        if self.avg_train_sharpe != 0:
            self.sharpe_decay = (self.avg_train_sharpe - self.avg_test_sharpe) / abs(
                self.avg_train_sharpe
            )

        if self.avg_train_return != 0:
            self.return_decay = (self.avg_train_return - self.avg_test_return) / abs(
                self.avg_train_return
            )

        # 参数稳定性
        self.parameter_stability = self._calculate_param_stability(valid_splits)

        # 稳健性判断
        self.is_robust = (
            self.sharpe_decay < 0.3  # 夏普衰减 < 30%
            and self.avg_test_sharpe > 0  # 测试期夏普 > 0
            and self.parameter_stability > 0.7  # 参数稳定性 > 70%
        )

    def _calculate_param_stability(self, splits: list[WalkForwardSplit]) -> float:
        """计算参数稳定性"""
        if len(splits) < 2:
            return 1.0

        # 收集所有参数
        all_params = [s.best_params for s in splits]
        if not all_params[0]:
            return 1.0

        param_names = list(all_params[0].keys())
        stabilities = []

        for param in param_names:
            values = [p.get(param) for p in all_params if param in p]
            if not values or not all(isinstance(v, (int, float)) for v in values):
                continue

            # 计算变异系数 (CV)
            mean_val = sum(values) / len(values)
            if mean_val == 0:
                continue

            variance = sum((v - mean_val) ** 2 for v in values) / len(values)
            cv = (variance**0.5) / abs(mean_val)

            # 转换为稳定性评分 (CV 越小越稳定)
            stability = max(0, 1 - cv)
            stabilities.append(stability)

        return sum(stabilities) / len(stabilities) if stabilities else 1.0

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "config": {
                "train_period_days": self.config.train_period_days,
                "test_period_days": self.config.test_period_days,
                "n_splits": self.config.n_splits,
            },
            "n_splits": len(self.splits),
            "avg_train_sharpe": self.avg_train_sharpe,
            "avg_test_sharpe": self.avg_test_sharpe,
            "sharpe_decay": self.sharpe_decay,
            "avg_train_return": self.avg_train_return,
            "avg_test_return": self.avg_test_return,
            "return_decay": self.return_decay,
            "parameter_stability": self.parameter_stability,
            "is_robust": self.is_robust,
        }


class WalkForwardValidator:
    """
    Walk-Forward 验证器

    通过时间序列交叉验证评估策略的稳健性
    """

    def __init__(self, config: WalkForwardConfig | None = None):
        self.config = config or WalkForwardConfig()
        self.config.validate()

    def _ensure_data_dict(
        self, data: pd.DataFrame | dict[str, pd.DataFrame]
    ) -> dict[str, pd.DataFrame]:
        """将输入统一为 {symbol: DataFrame} 形式"""

        if isinstance(data, dict):
            return data
        # 单一 DataFrame 回退为默认符号
        return {"symbol": data}

    def _extract_dates(self, df: pd.DataFrame) -> pd.Series:
        """从 DataFrame 提取 datetime 序列"""

        if isinstance(df.index, pd.DatetimeIndex):
            return df.index.to_series()
        if "datetime" in df.columns:
            return pd.to_datetime(df["datetime"])
        if "timestamp" in df.columns:
            return pd.to_datetime(df["timestamp"])
        raise ValueError("数据必须有 datetime 索引或列")

    def generate_splits(
        self,
        data: pd.DataFrame | dict[str, pd.DataFrame],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]]:
        """
        生成训练/测试数据分割

        Args:
            data: 完整数据集（支持单 DataFrame 或 {symbol: DataFrame}）
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            [(train_data_dict, test_data_dict), ...]
        """
        data_dict = self._ensure_data_dict(data)

        # 以首个品种的时间戳作为分割参考
        ref_df = next(iter(data_dict.values()))
        dates = self._extract_dates(ref_df)

        data_start = start_date or dates.min()
        data_end = end_date or dates.max()

        if isinstance(data_start, pd.Timestamp):
            data_start = data_start.to_pydatetime()
        if isinstance(data_end, pd.Timestamp):
            data_end = data_end.to_pydatetime()

        splits: list[tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]] = []

        # 计算每个分割的起始点
        total_days = (data_end - data_start).days
        step_days = (
            total_days - self.config.train_period_days - self.config.test_period_days
        ) // max(1, self.config.n_splits - 1)

        for i in range(self.config.n_splits):
            train_start = data_start + timedelta(days=i * step_days)
            train_end = train_start + timedelta(days=self.config.train_period_days)
            test_start = train_end + timedelta(days=self.config.gap_days)
            test_end = test_start + timedelta(days=self.config.test_period_days)

            if test_end > data_end:
                break

            train_split: dict[str, pd.DataFrame] = {}
            test_split: dict[str, pd.DataFrame] = {}

            for symbol, df in data_dict.items():
                df_dates = self._extract_dates(df)

                if isinstance(df.index, pd.DatetimeIndex):
                    train_mask = (df.index >= train_start) & (df.index < train_end)
                    test_mask = (df.index >= test_start) & (df.index < test_end)
                else:
                    train_mask = (df_dates >= train_start) & (df_dates < train_end)
                    test_mask = (df_dates >= test_start) & (df_dates < test_end)

                train_df = df[train_mask].copy()
                test_df = df[test_mask].copy()

                if len(train_df) == 0 or len(test_df) == 0:
                    continue

                train_split[symbol] = train_df
                test_split[symbol] = test_df

            if train_split and test_split:
                splits.append((train_split, test_split))

        return splits

    def run(
        self,
        strategy_class: type[Strategy],
        data: pd.DataFrame | dict[str, pd.DataFrame],
        param_space: dict[str, dict],
        objective: "Objective",
        search_method: "SearchMethod",
        backtest_config: BacktestConfig | None = None,
        timeframe: str = "15m",
    ) -> WalkForwardResult:
        """
        执行 Walk-Forward 验证

        Args:
            strategy_class: 策略类
            data: 完整数据
            param_space: 参数空间
            objective: 优化目标
            search_method: 搜索方法
            backtest_config: 回测配置

        Returns:
            WalkForwardResult
        """
        from src.optimization.engine import OptimizationConfig, OptimizationEngine
        from src.optimization.methods import ParameterSpace

        splits_data = self.generate_splits(data)
        result = WalkForwardResult(config=self.config)

        for i, (train_data, test_data) in enumerate(splits_data):
            # 取参考品种用于记录时间范围
            ref_train_df = next(iter(train_data.values()))
            ref_test_df = next(iter(test_data.values()))

            split = WalkForwardSplit(
                split_id=i,
                train_start=self._extract_dates(ref_train_df).min(),
                train_end=self._extract_dates(ref_train_df).max(),
                test_start=self._extract_dates(ref_test_df).min(),
                test_end=self._extract_dates(ref_test_df).max(),
            )

            # 在训练集上优化
            opt_config = OptimizationConfig(
                strategy_class=strategy_class,
                param_space=ParameterSpace.from_dict(param_space),
                objective=objective,
                search_method=search_method,
            )

            engine = OptimizationEngine(opt_config)
            opt_result = engine.run(train_data, backtest_config)

            if opt_result.best_params:
                split.best_params = opt_result.best_params
                split.train_metrics = opt_result.best_metrics

                # 在测试集上验证
                from src.strategy.base import StrategyConfig

                strategy_config = StrategyConfig(
                    name=f"wf_{split.split_id}",
                    params=split.best_params,
                )
                strategy = strategy_class(config=strategy_config)
                bt_config = backtest_config or BacktestConfig()
                bt_engine = BacktestEngine(config=bt_config)
                bt_result = bt_engine.run_with_data(
                    strategy=strategy,
                    data=test_data,
                    timeframe=timeframe,
                )

                split.test_metrics = MetricsCalculator.calculate(bt_result)

            result.splits.append(split)

        result.calculate_summary()
        return result
