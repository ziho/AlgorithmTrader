"""
策略管理 API

提供策略列表、配置、启停等接口
"""

from typing import Any

from nicegui import app

from src.ops.logging import get_logger

logger = get_logger(__name__)


async def list_strategies() -> list[dict[str, Any]]:
    """
    获取所有策略列表

    Returns:
        策略列表
    """
    if hasattr(app, "state") and app.state:
        strategies = app.state.get_strategies()
        return [
            {
                "name": s.name,
                "class_name": s.class_name,
                "enabled": s.enabled,
                "symbols": s.symbols,
                "timeframes": s.timeframes,
                "params": s.params,
                "status": s.status,
                "current_position": s.current_position,
                "today_pnl": s.today_pnl,
            }
            for s in strategies.values()
        ]

    return []


async def get_strategy(name: str) -> dict[str, Any] | None:
    """
    获取单个策略详情

    Args:
        name: 策略名称

    Returns:
        策略详情或 None
    """
    if hasattr(app, "state") and app.state:
        strategy = app.state.get_strategy(name)
        if strategy:
            return {
                "name": strategy.name,
                "class_name": strategy.class_name,
                "enabled": strategy.enabled,
                "symbols": strategy.symbols,
                "timeframes": strategy.timeframes,
                "params": strategy.params,
                "status": strategy.status,
                "current_position": strategy.current_position,
                "today_pnl": strategy.today_pnl,
            }

    return None


async def update_strategy(
    name: str,
    enabled: bool | None = None,
    params: dict[str, Any] | None = None,
    symbols: list[str] | None = None,
) -> bool:
    """
    更新策略配置

    Args:
        name: 策略名称
        enabled: 是否启用
        params: 策略参数
        symbols: 交易对列表

    Returns:
        是否更新成功
    """
    if hasattr(app, "state") and app.state:
        updates = {}
        if enabled is not None:
            updates["enabled"] = enabled
        if params is not None:
            updates["params"] = params
        if symbols is not None:
            updates["symbols"] = symbols

        success = app.state.update_strategy(name, **updates)

        if success:
            logger.info("strategy_updated", name=name, updates=updates)

        return success

    return False


async def toggle_strategy(name: str, enabled: bool) -> bool:
    """
    切换策略启用状态

    Args:
        name: 策略名称
        enabled: 是否启用

    Returns:
        是否操作成功
    """
    return await update_strategy(name, enabled=enabled)


async def get_strategy_logs(name: str, limit: int = 100) -> list[dict[str, Any]]:
    """
    获取策略运行日志

    Args:
        name: 策略名称
        limit: 最大返回数量

    Returns:
        日志列表
    """
    # TODO: 从 Loki 或日志文件获取
    return [
        {
            "timestamp": "2026-02-01T10:30:15",
            "level": "INFO",
            "message": "Bar received - BTC/USDT close=42350.5",
        },
        {
            "timestamp": "2026-02-01T10:30:15",
            "level": "INFO",
            "message": "Signal: HOLD (fast_ma=42100, slow_ma=42200)",
        },
    ]


# 导出
__all__ = [
    "list_strategies",
    "get_strategy",
    "update_strategy",
    "toggle_strategy",
    "get_strategy_logs",
]
