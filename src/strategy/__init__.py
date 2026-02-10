"""
Strategy 模块 - 策略管理

包含:
- base: Strategy 基类接口
- registry: 策略注册与加载
- examples: 示例策略
"""

# 导入示例策略以触发 @register_strategy 注册
import src.strategy.examples  # noqa: F401
from src.strategy.base import StrategyBase, StrategyConfig, StrategyState

__all__ = [
    "StrategyBase",
    "StrategyConfig",
    "StrategyState",
]
