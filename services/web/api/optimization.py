"""
参数优化 API

提供优化任务创建、进度查询、结果获取等接口
"""

from datetime import datetime
from typing import Any

from nicegui import app

from services.web.state import OptimizationTask
from src.ops.logging import get_logger

logger = get_logger(__name__)


async def list_tasks(
    status: str | None = None,
) -> list[dict[str, Any]]:
    """
    获取优化任务列表
    
    Args:
        status: 状态筛选
        
    Returns:
        任务列表
    """
    if hasattr(app, "state") and app.state:
        tasks = app.state.get_optimization_tasks()
        result = [
            {
                "id": t.id,
                "strategy_name": t.strategy_name,
                "objectives": t.objectives,
                "method": t.method,
                "status": t.status,
                "progress": t.progress,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ]
        
        if status:
            result = [t for t in result if t["status"] == status]
        
        return result
    
    return []


async def get_task(task_id: str) -> dict[str, Any] | None:
    """
    获取优化任务详情
    
    Args:
        task_id: 任务 ID
        
    Returns:
        任务详情或 None
    """
    if hasattr(app, "state") and app.state:
        tasks = app.state.get_optimization_tasks()
        for t in tasks:
            if t.id == task_id:
                return {
                    "id": t.id,
                    "strategy_name": t.strategy_name,
                    "objectives": t.objectives,
                    "method": t.method,
                    "status": t.status,
                    "progress": t.progress,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    "best_params": t.best_params,
                    "pareto_front": t.pareto_front,
                }
    
    return None


async def create_task(
    strategy_name: str,
    objectives: list[str],
    method: str = "grid",
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: list[str] | None = None,
    in_sample_ratio: float = 0.7,
    walk_forward: bool = True,
) -> dict[str, Any]:
    """
    创建优化任务
    
    Args:
        strategy_name: 策略名称
        objectives: 优化目标列表
        method: 优化方法
        start_date: 数据开始日期
        end_date: 数据结束日期
        symbols: 交易对列表
        in_sample_ratio: 样本内比例
        walk_forward: 是否使用 Walk-forward 验证
        
    Returns:
        创建的任务信息
    """
    import uuid
    
    task_id = f"opt_{uuid.uuid4().hex[:8]}"
    now = datetime.now()
    
    task = OptimizationTask(
        id=task_id,
        strategy_name=strategy_name,
        objectives=objectives,
        method=method,
        status="pending",
        progress=0.0,
        created_at=now,
    )
    
    if hasattr(app, "state") and app.state:
        app.state.add_optimization_task(task)
    
    logger.info(
        "optimization_task_created",
        id=task_id,
        strategy=strategy_name,
        objectives=objectives,
        method=method,
    )
    
    return {
        "id": task_id,
        "strategy_name": strategy_name,
        "objectives": objectives,
        "method": method,
        "status": "pending",
        "created_at": now.isoformat(),
    }


async def cancel_task(task_id: str) -> bool:
    """
    取消优化任务
    
    Args:
        task_id: 任务 ID
        
    Returns:
        是否取消成功
    """
    # TODO: 实现任务取消逻辑
    logger.info("optimization_task_cancelled", id=task_id)
    return True


async def apply_params(
    task_id: str,
    params: dict[str, Any],
) -> bool:
    """
    应用优化结果的参数
    
    Args:
        task_id: 任务 ID
        params: 要应用的参数
        
    Returns:
        是否应用成功
    """
    # TODO: 实现参数应用逻辑
    logger.info("optimization_params_applied", task_id=task_id, params=params)
    return True


async def get_pareto_front(task_id: str) -> list[dict[str, Any]]:
    """
    获取 Pareto 前沿结果
    
    Args:
        task_id: 任务 ID
        
    Returns:
        Pareto 前沿解集
    """
    task = await get_task(task_id)
    if task and task.get("pareto_front"):
        return task["pareto_front"]
    
    return []


# 导出
__all__ = [
    "list_tasks",
    "get_task",
    "create_task",
    "cancel_task",
    "apply_params",
    "get_pareto_front",
]
