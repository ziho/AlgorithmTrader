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
    import json
    import re
    from pathlib import Path

    logs = []

    # 1. 尝试从 Loki 获取日志 (如果配置了)
    try:
        import os

        import aiohttp

        loki_url = os.getenv("LOKI_URL", "http://localhost:3100")
        query = f'{{strategy="{name}"}}'

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{loki_url}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "limit": limit,
                },
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get("data", {}).get("result", [])
                    for stream in results:
                        for ts, line in stream.get("values", []):
                            try:
                                log_data = json.loads(line)
                                logs.append(
                                    {
                                        "timestamp": log_data.get("timestamp", ts),
                                        "level": log_data.get("level", "INFO"),
                                        "message": log_data.get("message", line),
                                    }
                                )
                            except json.JSONDecodeError:
                                logs.append(
                                    {
                                        "timestamp": ts,
                                        "level": "INFO",
                                        "message": line,
                                    }
                                )

                    if logs:
                        return logs[:limit]
    except Exception:
        # Loki 不可用，回退到日志文件
        pass

    # 2. 从本地日志文件获取
    try:
        logs_dir = Path("logs")
        if logs_dir.exists():
            log_files = sorted(
                logs_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True
            )

            for log_file in log_files[:5]:  # 检查最近 5 个日志文件
                if len(logs) >= limit:
                    break

                with open(log_file, errors="ignore") as f:
                    lines = f.readlines()

                for line in reversed(lines):
                    if len(logs) >= limit:
                        break

                    # 过滤包含策略名称的日志
                    if name.lower() in line.lower() or "strategy" in line.lower():
                        # 解析日志行
                        level = "INFO"
                        if "error" in line.lower():
                            level = "ERROR"
                        elif "warning" in line.lower():
                            level = "WARNING"
                        elif "debug" in line.lower():
                            level = "DEBUG"

                        # 提取时间戳
                        ts_match = re.search(
                            r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line
                        )
                        timestamp = ts_match.group(1) if ts_match else ""

                        message = line.strip()
                        if len(message) > 300:
                            message = message[:300] + "..."

                        logs.append(
                            {
                                "timestamp": timestamp,
                                "level": level,
                                "message": message,
                            }
                        )

    except Exception as e:
        logger.warning("log_read_failed", error=str(e))

    # 3. 如果没有找到日志，返回默认信息
    if not logs:
        from datetime import datetime

        logs = [
            {
                "timestamp": datetime.now().isoformat(),
                "level": "INFO",
                "message": f"暂无策略 {name} 的运行日志",
            }
        ]

    return logs[:limit]


# 导出
__all__ = [
    "list_strategies",
    "get_strategy",
    "update_strategy",
    "toggle_strategy",
    "get_strategy_logs",
]
