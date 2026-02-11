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
                await asyncio.sleep(120)  # 120秒更新一次（降低资源消耗）
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("background_update_error", error=str(e))
                await asyncio.sleep(300)  # 出错时 5 分钟后重试

    async def _check_services(self):
        """检查服务状态（完全非阻塞，不会卡住事件循环）"""
        import httpx

        # 检查 InfluxDB（异步 HTTP，不阻塞事件循环）
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("http://localhost:8086/health")
                if resp.status_code == 200:
                    self._services["influxdb"].status = "healthy"
                    self._services["influxdb"].message = ""
                else:
                    self._services["influxdb"].status = "warning"
                    self._services["influxdb"].message = f"HTTP {resp.status_code}"
        except Exception as e:
            self._services["influxdb"].status = "error"
            self._services["influxdb"].message = str(e)[:80]
        self._services["influxdb"].last_check = datetime.now()

        # 检查其他服务：优先读心跳文件（零开销），仅在无心跳时才用 docker
        from src.ops.heartbeat import is_heartbeat_stale, read_all_heartbeats

        heartbeats = read_all_heartbeats()
        used_heartbeat = False

        if heartbeats:
            for service_name in ["collector", "trader", "scheduler"]:
                hb = heartbeats.get(service_name)
                if hb is None:
                    self._services[service_name].status = "not_deployed"
                    self._services[service_name].message = "服务未启用"
                elif is_heartbeat_stale(hb):
                    self._services[service_name].status = "warning"
                    self._services[service_name].message = "心跳超时"
                elif hb.status in ("running", "starting"):
                    self._services[service_name].status = "healthy"
                    self._services[service_name].message = f"运行中"
                else:
                    self._services[service_name].status = "warning"
                    self._services[service_name].message = hb.status
                self._services[service_name].last_check = datetime.now()
            used_heartbeat = True

        if not used_heartbeat:
            # 回退：使用单次 docker ps -a（在线程中，不阻塞事件循环）
            await self._check_services_via_docker()

    async def _check_services_via_docker(self):
        """通过单次 docker 命令检查容器状态（在线程中运行，不阻塞事件循环）"""
        import subprocess

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "docker", "ps", "-a",
                        "--filter", "name=algorithmtrader-",
                        "--format", "{{.Names}}\t{{.State}}\t{{.Status}}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
            )

            all_containers: dict[str, tuple[str, str]] = {}  # name -> (state, status_text)
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        all_containers[parts[0]] = (parts[1], parts[2])
                    elif len(parts) >= 2:
                        all_containers[parts[0]] = (parts[1], parts[1])

            for service_name in ["collector", "trader", "scheduler"]:
                found = False
                for suffix in ("", "-1"):
                    key = f"algorithmtrader-{service_name}{suffix}"
                    if key in all_containers:
                        state, status_text = all_containers[key]
                        found = True
                        if state == "running":
                            self._services[service_name].status = "healthy"
                            self._services[service_name].message = status_text
                        elif state == "exited":
                            self._services[service_name].status = "stopped"
                            self._services[service_name].message = "容器已停止"
                        else:
                            self._services[service_name].status = "warning"
                            self._services[service_name].message = status_text[:30]
                        break

                if not found:
                    self._services[service_name].status = "not_deployed"
                    self._services[service_name].message = "未部署 (Profile 未激活)"
                self._services[service_name].last_check = datetime.now()

        except FileNotFoundError:
            for service_name in ["collector", "trader", "scheduler"]:
                self._services[service_name].status = "unknown"
                self._services[service_name].message = "Docker not available"
                self._services[service_name].last_check = datetime.now()
        except Exception as e:
            for service_name in ["collector", "trader", "scheduler"]:
                self._services[service_name].status = "unknown"
                self._services[service_name].message = str(e)[:50]
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
