"""
回测结果 API

提供回测历史、详情等接口
"""

from typing import Any

from nicegui import app

from src.ops.logging import get_logger

logger = get_logger(__name__)


async def list_backtests(
    strategy: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    获取回测历史列表

    Args:
        strategy: 策略名称筛选
        limit: 最大返回数量

    Returns:
        回测列表
    """
    if hasattr(app, "state") and app.state:
        backtests = app.state.get_backtests(limit=limit)
        result = [
            {
                "id": bt.id,
                "strategy_name": bt.strategy_name,
                "start_date": bt.start_date.isoformat(),
                "end_date": bt.end_date.isoformat(),
                "created_at": bt.created_at.isoformat(),
                "status": bt.status,
                "total_return": bt.total_return,
                "sharpe_ratio": bt.sharpe_ratio,
                "max_drawdown": bt.max_drawdown,
                "win_rate": bt.win_rate,
                "total_trades": bt.total_trades,
            }
            for bt in backtests
        ]

        if strategy and strategy != "全部":
            result = [bt for bt in result if bt["strategy_name"] == strategy]

        return result

    return []


async def get_backtest(backtest_id: str) -> dict[str, Any] | None:
    """
    获取回测详情

    Args:
        backtest_id: 回测 ID

    Returns:
        回测详情或 None
    """
    # TODO: 从存储加载回测详情
    return None


async def create_backtest(
    strategy_name: str,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 100000,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    创建新的回测任务

    Args:
        strategy_name: 策略名称
        symbol: 交易对
        start_date: 开始日期
        end_date: 结束日期
        initial_capital: 初始资金
        params: 策略参数覆盖

    Returns:
        创建的回测任务信息
    """
    import uuid

    backtest_id = f"bt_{uuid.uuid4().hex[:8]}"

    # TODO: 实际创建回测任务
    logger.info(
        "backtest_created",
        id=backtest_id,
        strategy=strategy_name,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )

    return {
        "id": backtest_id,
        "strategy_name": strategy_name,
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "status": "pending",
    }


async def compare_backtests(backtest_ids: list[str]) -> dict[str, Any]:
    """
    对比多个回测结果

    Args:
        backtest_ids: 回测 ID 列表

    Returns:
        对比结果
    """
    # TODO: 实现对比逻辑
    return {
        "backtests": backtest_ids,
        "comparison": {},
    }


# 导出
__all__ = [
    "list_backtests",
    "get_backtest",
    "create_backtest",
    "compare_backtests",
]
