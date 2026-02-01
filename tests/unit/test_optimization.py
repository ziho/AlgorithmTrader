"""
优化模块单元测试
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from src.optimization.objectives import (
    MaximizeSharpe,
    MaximizeReturn,
    MinimizeDrawdown,
    MaximizeCalmar,
    MultiObjective,
    WeightedObjective,
    create_balanced_objective,
)
from src.optimization.methods import (
    ParameterSpec,
    ParameterSpace,
    GridSearch,
    RandomSearch,
    LatinHypercubeSearch,
)
from src.optimization.engine import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationResult,
    TrialResult,
)
from src.optimization.walk_forward import (
    WalkForwardConfig,
    WalkForwardValidator,
    WalkForwardResult,
)
from src.backtest.metrics import PerformanceMetrics, TradeStats
from src.strategy.examples.trend_following import DualMAStrategy


class MockMetrics:
    """模拟回测指标"""
    
    @staticmethod
    def create(
        sharpe: float = 1.5,
        total_return: float = 0.20,
        max_drawdown: float = 0.10,
        win_rate: float = 0.55,
        profit_factor: float = 1.5,
        total_trades: int = 50,
    ) -> PerformanceMetrics:
        # 创建 TradeStats
        winning = int(total_trades * win_rate)
        losing = total_trades - winning
        trade_stats = TradeStats(
            total_trades=total_trades,
            winning_trades=winning,
            losing_trades=losing,
        )
        
        return PerformanceMetrics(
            sharpe_ratio=sharpe,
            sortino_ratio=sharpe * 1.2,
            calmar_ratio=total_return / max_drawdown if max_drawdown > 0 else 0,
            total_return=total_return,
            annualized_return=total_return * 2,
            max_drawdown=max_drawdown,
            trade_stats=trade_stats,
        )


class TestObjectives:
    """目标函数测试"""
    
    def test_maximize_sharpe(self):
        """测试最大化夏普"""
        obj = MaximizeSharpe()
        metrics = MockMetrics.create(sharpe=2.0)
        
        value = obj.evaluate(metrics)
        
        assert value == 2.0
        assert not obj.minimize
    
    def test_maximize_return(self):
        """测试最大化收益"""
        obj = MaximizeReturn()
        metrics = MockMetrics.create(total_return=30.0)
        
        value = obj.evaluate(metrics)
        
        assert value == 30.0
    
    def test_minimize_drawdown(self):
        """测试最小化回撤"""
        obj = MinimizeDrawdown()
        metrics = MockMetrics.create(max_drawdown=15.0)
        
        value = obj.evaluate(metrics)
        
        assert value == 15.0
        assert obj.minimize
    
    def test_is_better_maximize(self):
        """测试最大化比较"""
        obj = MaximizeSharpe()
        
        assert obj.is_better(2.0, 1.0)
        assert not obj.is_better(1.0, 2.0)
    
    def test_is_better_minimize(self):
        """测试最小化比较"""
        obj = MinimizeDrawdown()
        
        assert obj.is_better(5.0, 10.0)
        assert not obj.is_better(10.0, 5.0)


class TestMultiObjective:
    """多目标优化测试"""
    
    def test_create_multi_objective(self):
        """测试创建多目标"""
        obj = MultiObjective([
            WeightedObjective(MaximizeSharpe(), weight=0.5),
            WeightedObjective(MaximizeReturn(), weight=0.5),
        ])
        
        assert len(obj.objectives) == 2
    
    def test_multi_objective_evaluate(self):
        """测试多目标评估"""
        obj = MultiObjective([
            WeightedObjective(MaximizeSharpe(), weight=1.0),
            WeightedObjective(MaximizeReturn(), weight=1.0),
        ])
        
        metrics = MockMetrics.create(sharpe=2.0, total_return=0.20)
        value = obj.evaluate(metrics)
        
        # (2.0 + 0.20) / 2 = 1.1
        assert value == pytest.approx(1.1, rel=0.01)
    
    def test_balanced_objective(self):
        """测试平衡目标"""
        obj = create_balanced_objective()
        
        assert len(obj.objectives) == 3
    
    def test_get_individual_scores(self):
        """测试获取单独评分"""
        obj = MultiObjective([
            WeightedObjective(MaximizeSharpe(), weight=0.5),
            WeightedObjective(MaximizeReturn(), weight=0.5),
        ])
        
        metrics = MockMetrics.create(sharpe=1.5, total_return=0.25)
        scores = obj.get_individual_scores(metrics)
        
        assert scores["sharpe_ratio"] == 1.5
        assert scores["total_return"] == 0.25


class TestParameterSpec:
    """参数规格测试"""
    
    def test_int_param_generate(self):
        """测试整数参数生成"""
        spec = ParameterSpec(
            name="period",
            type="int",
            min_value=5,
            max_value=20,
            step=5,
        )
        
        values = spec.generate_values()
        
        assert values == [5, 10, 15, 20]
    
    def test_float_param_generate_with_step(self):
        """测试带步长的浮点参数"""
        spec = ParameterSpec(
            name="threshold",
            type="float",
            min_value=0.0,
            max_value=1.0,
            step=0.25,
        )
        
        values = spec.generate_values()
        
        assert len(values) == 5
        assert 0.0 in values
        assert 1.0 in values
    
    def test_bool_param_generate(self):
        """测试布尔参数"""
        spec = ParameterSpec(name="flag", type="bool")
        
        values = spec.generate_values()
        
        assert values == [True, False]
    
    def test_choice_param_generate(self):
        """测试选择参数"""
        spec = ParameterSpec(
            name="mode",
            type="choice",
            choices=["a", "b", "c"],
        )
        
        values = spec.generate_values()
        
        assert values == ["a", "b", "c"]
    
    def test_random_int(self):
        """测试随机整数"""
        spec = ParameterSpec(
            name="period",
            type="int",
            min_value=5,
            max_value=20,
        )
        
        value = spec.random_value()
        
        assert 5 <= value <= 20
        assert isinstance(value, int)
    
    def test_random_float(self):
        """测试随机浮点"""
        spec = ParameterSpec(
            name="threshold",
            type="float",
            min_value=0.0,
            max_value=1.0,
        )
        
        value = spec.random_value()
        
        assert 0.0 <= value <= 1.0


class TestParameterSpace:
    """参数空间测试"""
    
    def test_add_int(self):
        """测试添加整数参数"""
        space = ParameterSpace()
        space.add_int("period", min_value=5, max_value=20, step=5)
        
        assert "period" in space.params
        assert space.params["period"].type == "int"
    
    def test_add_float(self):
        """测试添加浮点参数"""
        space = ParameterSpace()
        space.add_float("threshold", min_value=0.0, max_value=1.0)
        
        assert "threshold" in space.params
        assert space.params["threshold"].type == "float"
    
    def test_get_default_params(self):
        """测试获取默认参数"""
        space = ParameterSpace()
        space.add_int("period", min_value=5, max_value=20, default=10)
        space.add_bool("flag", default=True)
        
        defaults = space.get_default_params()
        
        assert defaults["period"] == 10
        assert defaults["flag"] is True
    
    def test_from_dict(self):
        """测试从字典创建"""
        param_dict = {
            "fast_period": {"type": "int", "min": 5, "max": 20, "step": 5, "default": 10},
            "slow_period": {"type": "int", "min": 20, "max": 50, "step": 10, "default": 30},
        }
        
        space = ParameterSpace.from_dict(param_dict)
        
        assert "fast_period" in space.params
        assert "slow_period" in space.params


class TestGridSearch:
    """网格搜索测试"""
    
    def test_generate_combinations(self):
        """测试生成组合"""
        space = ParameterSpace()
        space.add_int("a", min_value=1, max_value=3, step=1)
        space.add_bool("b")
        
        search = GridSearch()
        combinations = list(search.generate(space))
        
        # 3 * 2 = 6 种组合
        assert len(combinations) == 6
    
    def test_estimate_total(self):
        """测试估算总数"""
        space = ParameterSpace()
        space.add_int("a", min_value=1, max_value=3, step=1)
        space.add_bool("b")
        
        search = GridSearch()
        total = search.estimate_total(space)
        
        assert total == 6


class TestRandomSearch:
    """随机搜索测试"""
    
    def test_generate_samples(self):
        """测试生成采样"""
        space = ParameterSpace()
        space.add_int("period", min_value=5, max_value=50)
        space.add_float("threshold", min_value=0.0, max_value=1.0)
        
        search = RandomSearch(n_iter=20, seed=42)
        samples = list(search.generate(space))
        
        assert len(samples) == 20
        for sample in samples:
            assert 5 <= sample["period"] <= 50
            assert 0.0 <= sample["threshold"] <= 1.0
    
    def test_reproducible_with_seed(self):
        """测试种子可复现"""
        space = ParameterSpace()
        space.add_int("period", min_value=5, max_value=50)
        
        search1 = RandomSearch(n_iter=10, seed=42)
        samples1 = list(search1.generate(space))
        
        search2 = RandomSearch(n_iter=10, seed=42)
        samples2 = list(search2.generate(space))
        
        assert samples1 == samples2


class TestLatinHypercubeSearch:
    """拉丁超立方采样测试"""
    
    def test_generate_samples(self):
        """测试生成采样"""
        space = ParameterSpace()
        space.add_int("period", min_value=5, max_value=50)
        space.add_float("threshold", min_value=0.0, max_value=1.0)
        
        search = LatinHypercubeSearch(n_samples=20, seed=42)
        samples = list(search.generate(space))
        
        assert len(samples) == 20


class TestOptimizationResult:
    """优化结果测试"""
    
    def test_add_trial(self):
        """测试添加试验"""
        config = OptimizationConfig(
            strategy_class=DualMAStrategy,
            objective=MaximizeSharpe(),
        )
        result = OptimizationResult(config=config)
        
        trial = TrialResult(
            trial_id=0,
            params={"fast_period": 10, "slow_period": 30},
            metrics=MockMetrics.create(sharpe=1.5),
            objective_value=1.5,
        )
        result.add_trial(trial)
        
        assert result.total_trials == 1
        assert result.successful_trials == 1
        assert result.best_objective_value == 1.5
    
    def test_best_params_updated(self):
        """测试最佳参数更新"""
        config = OptimizationConfig(
            strategy_class=DualMAStrategy,
            objective=MaximizeSharpe(),
        )
        result = OptimizationResult(config=config)
        
        # 添加第一个试验
        result.add_trial(TrialResult(
            trial_id=0,
            params={"fast_period": 10},
            metrics=MockMetrics.create(sharpe=1.0),
            objective_value=1.0,
        ))
        
        # 添加更好的试验
        result.add_trial(TrialResult(
            trial_id=1,
            params={"fast_period": 15},
            metrics=MockMetrics.create(sharpe=2.0),
            objective_value=2.0,
        ))
        
        assert result.best_params["fast_period"] == 15
        assert result.best_objective_value == 2.0
    
    def test_to_dataframe(self):
        """测试转换为 DataFrame"""
        config = OptimizationConfig(
            strategy_class=DualMAStrategy,
            objective=MaximizeSharpe(),
        )
        result = OptimizationResult(config=config)
        
        result.add_trial(TrialResult(
            trial_id=0,
            params={"fast_period": 10},
            metrics=MockMetrics.create(),
            objective_value=1.5,
        ))
        
        df = result.to_dataframe()
        
        assert len(df) == 1
        assert "fast_period" in df.columns
        assert "objective_value" in df.columns


class TestWalkForwardConfig:
    """Walk-Forward 配置测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = WalkForwardConfig()
        
        assert config.train_period_days == 180
        assert config.test_period_days == 30
        assert config.n_splits == 6
    
    def test_validate_invalid_train_period(self):
        """测试无效训练期"""
        config = WalkForwardConfig(train_period_days=0)
        
        with pytest.raises(ValueError):
            config.validate()


class TestWalkForwardValidator:
    """Walk-Forward 验证器测试"""
    
    @pytest.fixture
    def sample_data(self):
        """创建样本数据"""
        dates = pd.date_range("2024-01-01", periods=365, freq="D")
        data = pd.DataFrame({
            "open": np.random.randn(365).cumsum() + 100,
            "high": np.random.randn(365).cumsum() + 102,
            "low": np.random.randn(365).cumsum() + 98,
            "close": np.random.randn(365).cumsum() + 100,
            "volume": np.random.randint(1000, 10000, 365),
        }, index=dates)
        return data
    
    def test_generate_splits(self, sample_data):
        """测试生成分割"""
        config = WalkForwardConfig(
            train_period_days=60,
            test_period_days=30,
            n_splits=3,
        )
        validator = WalkForwardValidator(config)
        
        splits = validator.generate_splits(sample_data)
        
        assert len(splits) >= 1
        for train, test in splits:
            assert len(train) > 0
            assert len(test) > 0


class TestWalkForwardResult:
    """Walk-Forward 结果测试"""
    
    def test_calculate_summary(self):
        """测试计算汇总"""
        from src.optimization.walk_forward import WalkForwardSplit
        
        config = WalkForwardConfig()
        result = WalkForwardResult(config=config)
        
        # 添加模拟分割结果
        for i in range(3):
            split = WalkForwardSplit(
                split_id=i,
                train_start=datetime.now(),
                train_end=datetime.now(),
                test_start=datetime.now(),
                test_end=datetime.now(),
                best_params={"fast_period": 10 + i},
                train_metrics=MockMetrics.create(sharpe=2.0),
                test_metrics=MockMetrics.create(sharpe=1.5),
            )
            result.splits.append(split)
        
        result.calculate_summary()
        
        assert result.avg_train_sharpe == 2.0
        assert result.avg_test_sharpe == 1.5
        assert result.sharpe_decay == 0.25  # (2-1.5)/2
