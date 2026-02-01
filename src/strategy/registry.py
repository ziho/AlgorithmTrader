"""
策略注册中心

职责:
- 策略注册
- 策略加载
- 策略实例化
"""

from typing import TypeVar

import structlog

from src.strategy.base import StrategyBase

logger = structlog.get_logger(__name__)

# 策略类型变量
T = TypeVar("T", bound=StrategyBase)

# 策略注册表
_registry: dict[str, type[StrategyBase]] = {}


def register_strategy(name: str | None = None) -> type[T]:
    """
    策略注册装饰器

    使用方式:
        @register_strategy("my_strategy")
        class MyStrategy(StrategyBase):
            ...

    或者:
        @register_strategy()
        class MyStrategy(StrategyBase):
            ...  # 使用类名作为策略名
    """

    def decorator(cls: type[T]) -> type[T]:
        strategy_name = name or cls.__name__
        _registry[strategy_name] = cls
        logger.debug("strategy_registered", name=strategy_name)
        return cls

    return decorator


def get_strategy(name: str) -> type[StrategyBase] | None:
    """
    获取策略类

    Args:
        name: 策略名称

    Returns:
        策略类或 None
    """
    return _registry.get(name)


def list_strategies() -> list[str]:
    """列出所有已注册的策略"""
    return list(_registry.keys())


def clear_registry() -> None:
    """清空注册表 (用于测试)"""
    _registry.clear()


# 导出
__all__ = [
    "register_strategy",
    "get_strategy",
    "list_strategies",
    "clear_registry",
]
