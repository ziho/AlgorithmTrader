"""
策略参数优化模块

提供:
- 网格搜索 (Grid Search)
- 随机搜索 (Random Search)
- 贝叶斯优化 (Bayesian Optimization)
- Walk-Forward 验证
- 多目标优化
"""

from src.optimization.engine import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationResult,
)
from src.optimization.objectives import (
    MaximizeSharpe,
    MaximizeReturn,
    MinimizeDrawdown,
    MultiObjective,
    Objective,
)
from src.optimization.methods import (
    GridSearch,
    ParameterSpace,
    RandomSearch,
    SearchMethod,
)
from src.optimization.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardValidator,
)

__all__ = [
    # Engine
    "OptimizationConfig",
    "OptimizationEngine",
    "OptimizationResult",
    "ParameterSpace",
    # Objectives
    "Objective",
    "MaximizeSharpe",
    "MaximizeReturn",
    "MinimizeDrawdown",
    "MultiObjective",
    # Methods
    "SearchMethod",
    "GridSearch",
    "RandomSearch",
    # Walk-Forward
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardValidator",
]
