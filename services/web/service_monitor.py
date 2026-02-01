"""
服务状态监控

提供实时服务健康状态检查
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import httpx


@dataclass
class ServiceStatus:
    """服务状态"""

    name: str
    status: str  # healthy, unhealthy, unknown
    message: str
    last_check: datetime = field(default_factory=datetime.now)
    details: dict = field(default_factory=dict)


class ServiceMonitor:
    """
    服务状态监控器

    监控以下服务:
    - InfluxDB: 数据库连接
    - Collector: 数据采集服务
    - Trader: 交易服务
    - Scheduler: 调度服务
    """

    def __init__(self):
        self._statuses: dict[str, ServiceStatus] = {}
        self._callbacks: list[Callable] = []

    def get_all_statuses(self) -> list[ServiceStatus]:
        """获取所有服务状态"""
        return list(self._statuses.values())

    def get_status(self, service_name: str) -> ServiceStatus | None:
        """获取指定服务状态"""
        return self._statuses.get(service_name)

    async def check_all(self) -> list[ServiceStatus]:
        """检查所有服务状态"""
        tasks = [
            self._check_influxdb(),
            self._check_service("Collector", "http://collector:8001/health"),
            self._check_service("Trader", "http://trader:8002/health"),
            self._check_service("Scheduler", "http://scheduler:8003/health"),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, ServiceStatus):
                self._statuses[result.name] = result
            elif isinstance(result, Exception):
                # 异常情况记录为 unknown
                pass

        # 触发回调
        for callback in self._callbacks:
            try:
                callback(self._statuses)
            except Exception:
                pass

        return self.get_all_statuses()

    async def _check_influxdb(self) -> ServiceStatus:
        """检查 InfluxDB 连接"""
        try:
            # 使用 HTTP 检查 InfluxDB health 端点
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://influxdb:8086/health")

                if response.status_code == 200:
                    return ServiceStatus(
                        name="InfluxDB",
                        status="healthy",
                        message="数据库连接正常",
                    )
                else:
                    return ServiceStatus(
                        name="InfluxDB",
                        status="unhealthy",
                        message=f"HTTP {response.status_code}",
                    )
        except httpx.ConnectError:
            return ServiceStatus(
                name="InfluxDB",
                status="unknown",
                message="无法连接到 InfluxDB",
            )
        except Exception as e:
            return ServiceStatus(
                name="InfluxDB",
                status="unhealthy",
                message=f"连接失败: {e}",
            )

    async def _check_service(self, name: str, health_url: str) -> ServiceStatus:
        """检查服务健康端点"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(health_url)

                if response.status_code == 200:
                    data = response.json() if response.content else {}
                    return ServiceStatus(
                        name=name,
                        status="healthy",
                        message=data.get("message", f"{name} 服务正常"),
                        details=data,
                    )
                else:
                    return ServiceStatus(
                        name=name,
                        status="unhealthy",
                        message=f"HTTP {response.status_code}",
                    )
        except httpx.ConnectError:
            return ServiceStatus(
                name=name,
                status="unknown",
                message="服务未启动或无法连接",
            )
        except Exception as e:
            return ServiceStatus(
                name=name,
                status="unknown",
                message=f"检查失败: {e}",
            )

    def on_status_change(self, callback: Callable):
        """注册状态变化回调"""
        self._callbacks.append(callback)

    def get_mock_statuses(self) -> list[ServiceStatus]:
        """
        获取模拟状态（开发/演示用）

        当无法连接到真实服务时使用
        """
        return [
            ServiceStatus(
                name="InfluxDB",
                status="healthy",
                message="数据库连接正常",
            ),
            ServiceStatus(
                name="Collector",
                status="healthy",
                message="数据采集正常",
            ),
            ServiceStatus(
                name="Trader",
                status="unknown",
                message="服务未启动",
            ),
            ServiceStatus(
                name="Scheduler",
                status="healthy",
                message="调度服务正常",
            ),
        ]


# 全局实例
_monitor: ServiceMonitor | None = None


def get_monitor() -> ServiceMonitor:
    """获取全局监控器实例"""
    global _monitor
    if _monitor is None:
        _monitor = ServiceMonitor()
    return _monitor
