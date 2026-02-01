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
    from pathlib import Path

    stats = {
        "running_strategies": 0,
        "today_trades": 0,
        "today_pnl": 0.0,
        "data_delay_seconds": 0.0,
        "last_updated": datetime.now().isoformat(),
    }

    # 从 app state 获取策略状态
    if hasattr(app, "state") and app.state:
        strategies = app.state.get_strategies()
        stats["running_strategies"] = sum(
            1 for s in strategies.values() if s.enabled and s.status == "running"
        )

        # 汇总今日交易统计
        for s in strategies.values():
            stats["today_pnl"] += s.today_pnl or 0

    # 检查数据延迟 (通过检查最新的 parquet 文件时间)
    try:
        parquet_dir = Path("data/parquet")
        if parquet_dir.exists():
            latest_mtime = 0
            for f in parquet_dir.rglob("data.parquet"):
                mtime = f.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime

            if latest_mtime > 0:
                stats["data_delay_seconds"] = datetime.now().timestamp() - latest_mtime
    except Exception:
        pass

    return stats


async def get_recent_alerts(limit: int = 10) -> list[dict[str, Any]]:
    """
    获取最近告警

    Args:
        limit: 最大返回数量

    Returns:
        告警列表
    """
    import re
    from pathlib import Path

    alerts = []

    # 从日志文件读取告警
    try:
        logs_dir = Path("logs")
        if logs_dir.exists():
            log_files = sorted(
                logs_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True
            )

            for log_file in log_files[:3]:  # 只检查最近 3 个日志文件
                if len(alerts) >= limit:
                    break

                with open(log_file, errors="ignore") as f:
                    lines = f.readlines()[-500:]  # 只读最后 500 行

                for line in reversed(lines):
                    if len(alerts) >= limit:
                        break

                    # 匹配 warning 和 error 级别的日志
                    if "warning" in line.lower() or "error" in line.lower():
                        level = "error" if "error" in line.lower() else "warning"

                        # 提取时间戳
                        ts_match = re.search(
                            r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line
                        )
                        timestamp = (
                            ts_match.group(1)
                            if ts_match
                            else datetime.now().isoformat()
                        )

                        # 提取消息
                        message = line.strip()
                        if len(message) > 200:
                            message = message[:200] + "..."

                        alerts.append(
                            {
                                "level": level,
                                "message": message,
                                "timestamp": timestamp,
                            }
                        )

    except Exception:
        # 如果读取日志失败，返回空列表
        pass

    # 如果没有从日志读取到告警，返回一些默认信息
    if not alerts:
        alerts = [
            {
                "level": "info",
                "message": "系统运行正常，无告警",
                "timestamp": datetime.now().isoformat(),
            }
        ]

    return alerts[:limit]


# 导出
__all__ = [
    "get_health",
    "get_services",
    "get_stats",
    "get_recent_alerts",
]
