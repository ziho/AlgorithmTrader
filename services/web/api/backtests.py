"""
回测结果 API

提供回测历史、详情等接口
"""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nicegui import app

from src.ops.logging import get_logger

logger = get_logger(__name__)

# 回测结果存储路径
BACKTESTS_STORAGE_PATH = Path("config/backtests.json")


def _load_backtests_from_storage() -> list[dict[str, Any]]:
    """从存储文件加载回测记录"""
    if BACKTESTS_STORAGE_PATH.exists():
        try:
            with open(BACKTESTS_STORAGE_PATH) as f:
                data = json.load(f)
                return data.get("backtests", [])
        except Exception as e:
            logger.warning("load_backtests_failed", error=str(e))
    return []


def _save_backtests_to_storage(backtests: list[dict[str, Any]]) -> None:
    """保存回测记录到存储文件"""
    try:
        BACKTESTS_STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BACKTESTS_STORAGE_PATH, "w") as f:
            json.dump(
                {"backtests": backtests, "updated_at": datetime.now().isoformat()},
                f,
                indent=2,
                default=str,
            )
    except Exception as e:
        logger.error("save_backtests_failed", error=str(e))


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
    # 首先从 app state 获取
    if hasattr(app, "state") and app.state:
        backtests = app.state.get_backtests()
        for bt in backtests:
            if bt.id == backtest_id:
                return {
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
                    "trades": getattr(bt, "trades", []),
                    "equity_curve": getattr(bt, "equity_curve", []),
                }

    # 从存储文件获取
    backtests = _load_backtests_from_storage()
    for bt in backtests:
        if bt.get("id") == backtest_id:
            return bt

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
    from datetime import datetime

    from services.backtest_runner.main import (
        STRATEGY_MAP,
        BacktestRunner,
        BacktestRunnerConfig,
    )

    backtest_id = f"bt_{uuid.uuid4().hex[:8]}"

    logger.info(
        "backtest_created",
        id=backtest_id,
        strategy=strategy_name,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )

    # 创建回测任务记录
    task_info = {
        "id": backtest_id,
        "strategy_name": strategy_name,
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "params": params or {},
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }

    # 保存到存储
    backtests = _load_backtests_from_storage()
    backtests.append(task_info)
    _save_backtests_to_storage(backtests)

    # 异步执行回测（在后台运行）
    try:
        if strategy_name in STRATEGY_MAP:
            # 更新状态为 running
            task_info["status"] = "running"

            runner_config = BacktestRunnerConfig(
                default_capital=Decimal(str(initial_capital)),
            )
            runner = BacktestRunner(runner_config)

            # 计算天数
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            days = (end_dt - start_dt).days

            symbols = [symbol] if isinstance(symbol, str) else symbol

            runner.create_task(
                strategy_name=strategy_name,
                symbols=symbols,
                days=days,
                params=params or {},
                initial_capital=initial_capital,
            )

            # 运行回测
            results = runner.run_all()

            if results:
                result = results[0]
                task_info["status"] = "completed"
                task_info["total_return"] = result.summary.total_return
                task_info["sharpe_ratio"] = result.summary.sharpe_ratio
                task_info["max_drawdown"] = result.summary.max_drawdown
                task_info["win_rate"] = result.summary.win_rate
                task_info["total_trades"] = result.summary.total_trades
                task_info["completed_at"] = datetime.now().isoformat()
            else:
                task_info["status"] = "failed"
                task_info["error"] = "No results returned"

            # 更新存储
            backtests = _load_backtests_from_storage()
            for i, bt in enumerate(backtests):
                if bt.get("id") == backtest_id:
                    backtests[i] = task_info
                    break
            _save_backtests_to_storage(backtests)

    except Exception as e:
        logger.error("backtest_execution_failed", error=str(e))
        task_info["status"] = "failed"
        task_info["error"] = str(e)

    return task_info


async def compare_backtests(backtest_ids: list[str]) -> dict[str, Any]:
    """
    对比多个回测结果

    Args:
        backtest_ids: 回测 ID 列表

    Returns:
        对比结果
    """
    results = []
    for backtest_id in backtest_ids:
        bt = await get_backtest(backtest_id)
        if bt:
            results.append(bt)

    if not results:
        return {"backtests": backtest_ids, "comparison": {}}

    # 计算对比指标
    comparison = {
        "metrics": [
            "total_return",
            "sharpe_ratio",
            "max_drawdown",
            "win_rate",
            "total_trades",
        ],
        "data": {},
    }

    for metric in comparison["metrics"]:
        comparison["data"][metric] = {
            bt.get("id", bt.get("strategy_name")): bt.get(metric)
            for bt in results
            if bt.get(metric) is not None
        }

    # 找出最佳结果
    if results:
        best_return = max(results, key=lambda x: x.get("total_return", 0))
        best_sharpe = max(results, key=lambda x: x.get("sharpe_ratio", 0))
        lowest_dd = min(results, key=lambda x: abs(x.get("max_drawdown", 1)))

        comparison["best"] = {
            "highest_return": best_return.get("id"),
            "highest_sharpe": best_sharpe.get("id"),
            "lowest_drawdown": lowest_dd.get("id"),
        }

    return {
        "backtests": [
            {
                "id": bt.get("id"),
                "strategy_name": bt.get("strategy_name"),
                "total_return": bt.get("total_return"),
                "sharpe_ratio": bt.get("sharpe_ratio"),
                "max_drawdown": bt.get("max_drawdown"),
                "win_rate": bt.get("win_rate"),
                "total_trades": bt.get("total_trades"),
            }
            for bt in results
        ],
        "comparison": comparison,
    }


# 导出
__all__ = [
    "list_backtests",
    "get_backtest",
    "create_backtest",
    "compare_backtests",
]
