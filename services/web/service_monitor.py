"""
服务状态监控

提供实时服务健康状态检查

支持多种检测方式:
1. HTTP 健康端点 (InfluxDB, Grafana, Web)
2. Docker 容器状态检查 (Collector, Trader, Scheduler)
3. 进程文件检查 (.pid 文件)
"""

import asyncio
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx


@dataclass
class ServiceStatus:
    """服务状态"""

    name: str
    status: str  # healthy, unhealthy, unknown
    message: str
    last_check: datetime = field(default_factory=datetime.now)
    details: dict = field(default_factory=dict)
    url: str | None = None  # 可访问的 URL


class ServiceMonitor:
    """
    服务状态监控器

    监控以下服务:
    - InfluxDB: 数据库 (HTTP 端点)
    - Grafana: 可视化 (HTTP 端点)
    - Collector: 数据采集服务 (容器状态)
    - Trader: 交易服务 (容器状态)
    - Scheduler: 调度服务 (容器状态)
    - Notifier: 通知服务 (容器状态)
    """

    # 容器名称与服务名称映射
    CONTAINER_SERVICES = {
        "algorithmtrader-collector-1": "Collector",
        "algorithmtrader-trader-1": "Trader",
        "algorithmtrader-scheduler-1": "Scheduler",
        "algorithmtrader-notifier-1": "Notifier",
        "algorithmtrader_collector_1": "Collector",
        "algorithmtrader_trader_1": "Trader",
        "algorithmtrader_scheduler_1": "Scheduler",
        "algorithmtrader_notifier_1": "Notifier",
        # Compose V2 命名
        "collector": "Collector",
        "trader": "Trader",
        "scheduler": "Scheduler",
        "notifier": "Notifier",
    }

    def __init__(self):
        self._statuses: dict[str, ServiceStatus] = {}
        self._callbacks: list[Callable] = []
        self._data_dir = Path("/app/data")

    def get_all_statuses(self) -> list[ServiceStatus]:
        """获取所有服务状态"""
        return list(self._statuses.values())

    def get_status(self, service_name: str) -> ServiceStatus | None:
        """获取指定服务状态"""
        return self._statuses.get(service_name)

    async def check_all(self) -> list[ServiceStatus]:
        """检查所有服务状态"""
        # HTTP 端点检查
        http_tasks = [
            self._check_influxdb(),
            self._check_grafana(),
        ]

        http_results = await asyncio.gather(*http_tasks, return_exceptions=True)

        for result in http_results:
            if isinstance(result, ServiceStatus):
                self._statuses[result.name] = result

        # 容器状态检查
        container_statuses = await self._check_docker_containers()
        for status in container_statuses:
            self._statuses[status.name] = status

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
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://influxdb:8086/health")

                if response.status_code == 200:
                    data = response.json()
                    return ServiceStatus(
                        name="InfluxDB",
                        status="healthy",
                        message=f"v{data.get('version', 'unknown')}",
                        url="http://localhost:8086",
                        details=data,
                    )
                else:
                    return ServiceStatus(
                        name="InfluxDB",
                        status="unhealthy",
                        message=f"HTTP {response.status_code}",
                        url="http://localhost:8086",
                    )
        except httpx.ConnectError:
            return ServiceStatus(
                name="InfluxDB",
                status="unknown",
                message="无法连接",
            )
        except Exception as e:
            return ServiceStatus(
                name="InfluxDB",
                status="unhealthy",
                message=str(e)[:50],
            )

    async def _check_grafana(self) -> ServiceStatus:
        """检查 Grafana 连接"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://grafana:3000/api/health")

                if response.status_code == 200:
                    data = response.json()
                    return ServiceStatus(
                        name="Grafana",
                        status="healthy",
                        message=f"v{data.get('version', 'unknown')}",
                        url="http://localhost:3000",
                        details=data,
                    )
                else:
                    return ServiceStatus(
                        name="Grafana",
                        status="unhealthy",
                        message=f"HTTP {response.status_code}",
                        url="http://localhost:3000",
                    )
        except httpx.ConnectError:
            return ServiceStatus(
                name="Grafana",
                status="unknown",
                message="无法连接",
            )
        except Exception as e:
            return ServiceStatus(
                name="Grafana",
                status="unhealthy",
                message=str(e)[:50],
            )

    async def _check_docker_containers(self) -> list[ServiceStatus]:
        """通过 Docker 检查容器状态"""
        statuses = []

        # 初始化所有服务为 unknown
        service_found = {
            "Collector": False,
            "Trader": False,
            "Scheduler": False,
            "Notifier": False,
        }

        try:
            # 使用 docker ps 检查容器状态
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--format",
                    "{{.Names}}\t{{.Status}}\t{{.State}}",
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
                    if len(parts) >= 3:
                        container_name = parts[0]
                        status_text = parts[1]
                        state = parts[2]

                        # 查找对应的服务名称
                        service_name = None
                        for pattern, svc_name in self.CONTAINER_SERVICES.items():
                            if pattern in container_name or container_name.endswith(
                                f"-{pattern.split('-')[-1]}"
                            ):
                                service_name = svc_name
                                break

                        if service_name and service_name in service_found:
                            service_found[service_name] = True

                            if state == "running":
                                # 解析运行时长
                                message = self._parse_uptime(status_text)
                                statuses.append(
                                    ServiceStatus(
                                        name=service_name,
                                        status="healthy",
                                        message=message,
                                    )
                                )
                            elif state == "exited":
                                statuses.append(
                                    ServiceStatus(
                                        name=service_name,
                                        status="unhealthy",
                                        message="已停止",
                                        details={"status": status_text},
                                    )
                                )
                            else:
                                statuses.append(
                                    ServiceStatus(
                                        name=service_name,
                                        status="unknown",
                                        message=status_text[:30],
                                    )
                                )

        except FileNotFoundError:
            # Docker 命令不可用，尝试使用 PID 文件检查
            statuses = await self._check_pid_files()
            return statuses
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

        # 添加未找到的服务
        for service_name, found in service_found.items():
            if not found:
                statuses.append(
                    ServiceStatus(
                        name=service_name,
                        status="unknown",
                        message="服务未部署",
                    )
                )

        return statuses

    def _parse_uptime(self, status_text: str) -> str:
        """解析 Docker 状态文本中的运行时长"""
        # 示例: "Up 2 hours", "Up 5 minutes", "Up About a minute"
        status_lower = status_text.lower()

        if "up" in status_lower:
            # 提取 Up 后面的时间
            parts = status_text.split()
            if len(parts) >= 2:
                time_parts = parts[1:]
                return f"运行 {' '.join(time_parts)}"

        return status_text[:30]

    async def _check_pid_files(self) -> list[ServiceStatus]:
        """通过 PID 文件检查服务状态（备用方案）"""
        statuses = []
        pid_dir = self._data_dir / ".pids"

        services = ["collector", "trader", "scheduler", "notifier"]

        for service in services:
            pid_file = pid_dir / f"{service}.pid"
            service_name = service.capitalize()

            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    # 检查进程是否存在
                    import os

                    os.kill(pid, 0)  # 不会真正杀死进程，只是检查存在性
                    statuses.append(
                        ServiceStatus(
                            name=service_name,
                            status="healthy",
                            message=f"PID {pid}",
                        )
                    )
                except (ProcessLookupError, ValueError):
                    statuses.append(
                        ServiceStatus(
                            name=service_name,
                            status="unhealthy",
                            message="进程不存在",
                        )
                    )
                except PermissionError:
                    # 进程存在但无权限检查
                    statuses.append(
                        ServiceStatus(
                            name=service_name,
                            status="healthy",
                            message="运行中",
                        )
                    )
            else:
                statuses.append(
                    ServiceStatus(
                        name=service_name,
                        status="unknown",
                        message="服务未启动",
                    )
                )

        return statuses

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
                message="v2.7.0",
                url="http://localhost:8086",
            ),
            ServiceStatus(
                name="Grafana",
                status="healthy",
                message="v10.0.0",
                url="http://localhost:3000",
            ),
            ServiceStatus(
                name="Collector",
                status="healthy",
                message="运行 2 hours",
            ),
            ServiceStatus(
                name="Trader",
                status="unknown",
                message="服务未部署",
            ),
            ServiceStatus(
                name="Scheduler",
                status="healthy",
                message="运行 2 hours",
            ),
            ServiceStatus(
                name="Notifier",
                status="healthy",
                message="运行 2 hours",
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
