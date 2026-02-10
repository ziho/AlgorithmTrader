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
        import json
        from pathlib import Path

        # 从 config/backtests.json 加载
        backtests_file = Path("config/backtests.json")
        if backtests_file.exists():
            try:
                with open(backtests_file) as f:
                    data = json.load(f)
                    for bt_data in data.get("backtests", []):
                        self._backtests.append(
                            BacktestInfo(
                                id=bt_data.get("id", "unknown"),
                                strategy_name=bt_data.get("strategy_name", "unknown"),
                                start_date=datetime.fromisoformat(
                                    bt_data.get(
                                        "start_date", datetime.now().isoformat()
                                    )
                                ),
                                end_date=datetime.fromisoformat(
                                    bt_data.get("end_date", datetime.now().isoformat())
                                ),
                                created_at=datetime.fromisoformat(
                                    bt_data.get(
                                        "created_at", datetime.now().isoformat()
                                    )
                                ),
                                status=bt_data.get("status", "completed"),
                                total_return=bt_data.get("total_return"),
                                sharpe_ratio=bt_data.get("sharpe_ratio"),
                                max_drawdown=bt_data.get("max_drawdown"),
                                win_rate=bt_data.get("win_rate"),
                                total_trades=bt_data.get("total_trades"),
                            )
                        )
                logger.info("backtests_loaded", count=len(self._backtests))
            except Exception as e:
                logger.warning("load_backtests_from_json_failed", error=str(e))

        # 从 reports 目录扫描
        reports_dir = Path("reports")
        if reports_dir.exists():
            for report_dir in reports_dir.iterdir():
                if report_dir.is_dir():
                    summary_file = report_dir / "summary.json"
                    if summary_file.exists():
                        try:
                            with open(summary_file) as f:
                                summary = json.load(f)
                                # 检查是否已存在
                                run_id = summary.get("run_id", report_dir.name)
                                if not any(bt.id == run_id for bt in self._backtests):
                                    self._backtests.append(
                                        BacktestInfo(
                                            id=run_id,
                                            strategy_name=summary.get(
                                                "strategy_name", "unknown"
                                            ),
                                            start_date=datetime.fromisoformat(
                                                summary.get(
                                                    "start_date",
                                                    datetime.now().isoformat(),
                                                )
                                            )
                                            if summary.get("start_date")
                                            else datetime.now(),
                                            end_date=datetime.fromisoformat(
                                                summary.get(
                                                    "end_date",
                                                    datetime.now().isoformat(),
                                                )
                                            )
                                            if summary.get("end_date")
                                            else datetime.now(),
                                            created_at=datetime.fromisoformat(
                                                summary.get(
                                                    "run_timestamp",
                                                    datetime.now().isoformat(),
                                                )
                                            ),
                                            status="completed",
                                            total_return=summary.get("total_return"),
                                            sharpe_ratio=summary.get("metrics", {}).get(
                                                "sharpe_ratio"
                                            ),
                                            max_drawdown=summary.get("metrics", {}).get(
                                                "max_drawdown"
                                            ),
                                            win_rate=summary.get("metrics", {})
                                            .get("trade_stats", {})
                                            .get("win_rate"),
                                            total_trades=summary.get("metrics", {})
                                            .get("trade_stats", {})
                                            .get("total_trades"),
                                        )
                                    )
                        except Exception as e:
                            logger.warning(
                                "load_report_failed",
                                path=str(summary_file),
                                error=str(e),
                            )

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
        import aiohttp

        # 检查 InfluxDB
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://localhost:8086/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        self._services["influxdb"].status = "healthy"
                        self._services["influxdb"].message = ""
                    else:
                        self._services["influxdb"].status = "warning"
                        self._services["influxdb"].message = f"HTTP {resp.status}"
        except Exception as e:
            self._services["influxdb"].status = "error"
            self._services["influxdb"].message = str(e)
        self._services["influxdb"].last_check = datetime.now()

        # 检查其他服务（通过 docker ps 或进程检查）
        import subprocess

        # 先获取所有容器（包括已停止的），用于区分"未部署"和"已停止"
        all_containers: dict[str, str] = {}
        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    "name=algorithmtrader-",
                    "--format",
                    "{{.Names}}\t{{.State}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        all_containers[parts[0]] = parts[1]
        except Exception:
            pass

        for service_name in ["collector", "trader", "scheduler"]:
            try:
                # 检查容器是否存在（已部署）
                container_exists = any(
                    name in all_containers
                    for name in [
                        f"algorithmtrader-{service_name}",
                        f"algorithmtrader-{service_name}-1",
                        f"algorithmtrader_{service_name}_1",
                    ]
                )

                if not container_exists:
                    # 容器从未创建过 → 未部署（不是错误）
                    self._services[service_name].status = "not_deployed"
                    self._services[service_name].message = "未部署 (Profile 未激活)"
                else:
                    result = subprocess.run(
                        [
                            "docker",
                            "ps",
                            "--filter",
                            f"name=algorithmtrader-{service_name}",
                            "--format",
                            "{{.Status}}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    status_output = result.stdout.strip()
                    if status_output and "Up" in status_output:
                        self._services[service_name].status = "healthy"
                        self._services[service_name].message = status_output
                    elif status_output:
                        self._services[service_name].status = "warning"
                        self._services[service_name].message = status_output
                    else:
                        self._services[service_name].status = "stopped"
                        self._services[service_name].message = "容器已停止"
            except subprocess.TimeoutExpired:
                self._services[service_name].status = "unknown"
                self._services[service_name].message = "Check timed out"
            except FileNotFoundError:
                # Docker not installed, check if running locally via process
                self._services[service_name].status = "unknown"
                self._services[service_name].message = "Docker not available"
            except Exception as e:
                self._services[service_name].status = "error"
                self._services[service_name].message = str(e)
            self._services[service_name].last_check = datetime.now()

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
