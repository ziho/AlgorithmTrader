"""
系统状态 API

提供系统健康检查、服务状态等接口
"""

from datetime import datetime
from typing import Any

from nicegui import app

from src.ops.logging import get_logger

logger = get_logger(__name__)


async def get_health() -> dict[str, Any]:
    """
    获取系统健康状态

    Returns:
        健康状态信息
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "0.1.0",
    }


async def get_services() -> list[dict[str, Any]]:
    """
    获取所有服务状态

    Returns:
        服务状态列表
    """
    if hasattr(app, "state") and app.state:
        services = app.state.get_services()
        return [
            {
                "name": s.name,
                "status": s.status,
                "message": s.message,
                "last_check": s.last_check.isoformat() if s.last_check else None,
            }
            for s in services.values()
        ]

    # 默认返回
    return [
        {"name": "collector", "status": "unknown", "message": "", "last_check": None},
        {"name": "trader", "status": "unknown", "message": "", "last_check": None},
        {"name": "scheduler", "status": "unknown", "message": "", "last_check": None},
        {"name": "influxdb", "status": "unknown", "message": "", "last_check": None},
    ]


async def get_stats() -> dict[str, Any]:
    """
    获取系统统计信息

    Returns:
        统计信息
    """
    # TODO: 从实际服务获取统计
    return {
        "running_strategies": 2,
        "today_trades": 5,
        "today_pnl": 234.56,
        "data_delay_seconds": 0.5,
        "last_updated": datetime.now().isoformat(),
    }


async def get_recent_alerts(limit: int = 10) -> list[dict[str, Any]]:
    """
    获取最近告警

    Args:
        limit: 最大返回数量

    Returns:
        告警列表
    """
    # TODO: 从日志或数据库获取
    return [
        {
            "level": "warning",
            "message": "BTC/USDT 持仓接近上限 (90%)",
            "timestamp": datetime.now().isoformat(),
        },
        {
            "level": "info",
            "message": "策略 DualMA 开始运行",
            "timestamp": datetime.now().isoformat(),
        },
    ]


# 导出
__all__ = [
    "get_health",
    "get_services",
    "get_stats",
    "get_recent_alerts",
]
