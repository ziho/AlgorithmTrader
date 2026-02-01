"""
应用全局状态管理

管理服务连接、缓存状态等
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.ops.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ServiceStatus:
    """服务状态"""

    name: str
    status: str = "unknown"  # healthy, warning, error, unknown
    message: str = ""
    last_check: datetime | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyInfo:
    """策略信息"""

    name: str
    class_name: str
    enabled: bool = False
    symbols: list[str] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    current_position: dict[str, float] = field(default_factory=dict)
    today_pnl: float = 0.0
    status: str = "stopped"  # running, stopped, error


@dataclass
class BacktestInfo:
    """回测信息"""

    id: str
    strategy_name: str
    start_date: datetime
    end_date: datetime
    created_at: datetime
    status: str = "pending"  # pending, running, completed, failed

    # 结果指标
    total_return: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    win_rate: float | None = None
    total_trades: int | None = None


@dataclass
class OptimizationTask:
    """优化任务"""

    id: str
    strategy_name: str
    objectives: list[str]
    method: str = "grid"
    status: str = "pending"  # pending, running, completed, failed
    progress: float = 0.0
    created_at: datetime | None = None
    completed_at: datetime | None = None

    # 结果
    best_params: dict[str, Any] | None = None
    pareto_front: list[dict[str, Any]] | None = None


class AppState:
    """
    应用状态管理

    管理:
    - 服务状态缓存
    - 策略状态
    - 回测结果
    - 优化任务
    """

    def __init__(self):
        self._services: dict[str, ServiceStatus] = {}
        self._strategies: dict[str, StrategyInfo] = {}
        self._backtests: list[BacktestInfo] = []
        self._optimization_tasks: list[OptimizationTask] = []
        self._initialized = False
        self._update_task: asyncio.Task | None = None

    async def initialize(self):
        """初始化状态"""
        if self._initialized:
            return

        # 初始化服务状态
        self._services = {
            "collector": ServiceStatus(name="collector"),
            "trader": ServiceStatus(name="trader"),
            "scheduler": ServiceStatus(name="scheduler"),
            "influxdb": ServiceStatus(name="influxdb"),
        }

        # 加载策略列表
        await self._load_strategies()

        # 加载回测历史
        await self._load_backtests()

        # 启动后台更新任务
        self._update_task = asyncio.create_task(self._background_update())

        self._initialized = True
        logger.info("app_state_initialized")

    async def cleanup(self):
        """清理资源"""
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass

        logger.info("app_state_cleaned")

    async def _load_strategies(self):
        """加载策略列表"""
        # TODO: 从配置文件或数据库加载
        # 暂时使用示例数据
        from src.strategy.registry import get_strategy, list_strategies

        try:
            for name in list_strategies():
                strategy_cls = get_strategy(name)
                if strategy_cls:
                    param_space = getattr(strategy_cls, "PARAM_SPACE", {})
                    self._strategies[name] = StrategyInfo(
                        name=name,
                        class_name=strategy_cls.__name__,
                        enabled=False,
                        symbols=[],
                        timeframes=["15m"],
                        params={
                            k: v.get("default", v.get("min", 0))
                            for k, v in param_space.items()
                        },
                    )
        except Exception as e:
            logger.warning("load_strategies_failed", error=str(e))

    async def _load_backtests(self):
        """加载回测历史"""
        # TODO: 从文件系统或数据库加载
        pass

    async def _background_update(self):
        """后台状态更新"""
        while True:
            try:
                await self._check_services()
                await asyncio.sleep(30)  # 30秒更新一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("background_update_error", error=str(e))
                await asyncio.sleep(60)

    async def _check_services(self):
        """检查服务状态"""
        for service_name, status in self._services.items():
            try:
                # TODO: 实现真正的健康检查
                status.status = "healthy"
                status.last_check = datetime.now()
            except Exception as e:
                status.status = "error"
                status.message = str(e)
                status.last_check = datetime.now()

    # ==================== 公共方法 ====================

    def get_services(self) -> dict[str, ServiceStatus]:
        """获取所有服务状态"""
        return self._services.copy()

    def get_strategies(self) -> dict[str, StrategyInfo]:
        """获取所有策略"""
        return self._strategies.copy()

    def get_strategy(self, name: str) -> StrategyInfo | None:
        """获取单个策略"""
        return self._strategies.get(name)

    def update_strategy(self, name: str, **kwargs) -> bool:
        """更新策略配置"""
        if name not in self._strategies:
            return False

        strategy = self._strategies[name]
        for key, value in kwargs.items():
            if hasattr(strategy, key):
                setattr(strategy, key, value)

        # TODO: 持久化到配置文件
        logger.info("strategy_updated", name=name, changes=kwargs)
        return True

    def get_backtests(self, limit: int = 50) -> list[BacktestInfo]:
        """获取回测历史"""
        return sorted(
            self._backtests,
            key=lambda x: x.created_at,
            reverse=True,
        )[:limit]

    def get_optimization_tasks(self) -> list[OptimizationTask]:
        """获取优化任务"""
        return self._optimization_tasks.copy()

    def add_optimization_task(self, task: OptimizationTask):
        """添加优化任务"""
        self._optimization_tasks.append(task)
        logger.info("optimization_task_added", task_id=task.id)


# 导出
__all__ = [
    "AppState",
    "ServiceStatus",
    "StrategyInfo",
    "BacktestInfo",
    "OptimizationTask",
]
