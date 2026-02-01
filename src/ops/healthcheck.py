"""
健康检查

职责:
- 服务健康状态检测
- 依赖服务可用性检查
- InfluxDB、Redis 等外部服务检测
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog

from src.core.config import get_settings

logger = structlog.get_logger(__name__)


class HealthStatus(str, Enum):
    """健康状态"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """健康检查结果"""

    name: str
    status: HealthStatus
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def check_influxdb_health(
    url: str | None = None,
    token: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """
    检查 InfluxDB 健康状态

    Args:
        url: InfluxDB URL，默认从配置读取
        token: InfluxDB Token，默认从配置读取
        timeout: 超时时间(秒)

    Returns:
        bool: 是否健康
    """
    try:
        from influxdb_client import InfluxDBClient

        settings = get_settings()
        url = url or settings.influxdb.url
        token = token or settings.influxdb.token.get_secret_value()

        with InfluxDBClient(url=url, token=token, timeout=int(timeout * 1000)) as client:
            health = client.health()
            is_healthy = health.status == "pass"

            logger.debug(
                "influxdb_health_check",
                status=health.status,
                message=health.message,
            )

            return is_healthy

    except ImportError:
        logger.warning("influxdb_client_not_installed")
        return False
    except Exception as e:
        logger.error("influxdb_health_check_failed", error=str(e))
        return False


def check_redis_health(
    host: str = "localhost",
    port: int = 6379,
    timeout: float = 5.0,
) -> bool:
    """
    检查 Redis 健康状态

    Args:
        host: Redis 主机
        port: Redis 端口
        timeout: 超时时间(秒)

    Returns:
        bool: 是否健康
    """
    try:
        import redis

        client = redis.Redis(host=host, port=port, socket_timeout=timeout)
        response = client.ping()

        logger.debug("redis_health_check", healthy=response)

        return response

    except ImportError:
        logger.warning("redis_not_installed")
        return False
    except Exception as e:
        logger.error("redis_health_check_failed", error=str(e))
        return False


def check_network_health(
    url: str = "https://api.okx.com/api/v5/public/time",
    timeout: float = 10.0,
) -> bool:
    """
    检查网络连通性

    Args:
        url: 测试 URL
        timeout: 超时时间(秒)

    Returns:
        bool: 是否可连接
    """
    try:
        import httpx

        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
            is_healthy = response.status_code == 200

            logger.debug(
                "network_health_check",
                url=url,
                status_code=response.status_code,
            )

            return is_healthy

    except ImportError:
        logger.warning("httpx_not_installed")
        return False
    except Exception as e:
        logger.error("network_health_check_failed", error=str(e))
        return False


class HealthChecker:
    """
    健康检查器

    统一管理所有健康检查
    """

    def __init__(self):
        self._checks: dict[str, Any] = {}

    def register(self, name: str, check_func: Any) -> None:
        """
        注册健康检查函数

        Args:
            name: 检查名称
            check_func: 检查函数，返回 bool 或 HealthCheckResult
        """
        self._checks[name] = check_func

    def check(self, name: str) -> HealthCheckResult:
        """
        执行单个健康检查

        Args:
            name: 检查名称

        Returns:
            HealthCheckResult: 检查结果
        """
        if name not in self._checks:
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNKNOWN,
                message=f"Unknown check: {name}",
            )

        start_time = datetime.now(UTC)

        try:
            result = self._checks[name]()

            if isinstance(result, HealthCheckResult):
                return result

            # 布尔结果转换
            status = HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
            latency = (datetime.now(UTC) - start_time).total_seconds() * 1000

            return HealthCheckResult(
                name=name,
                status=status,
                latency_ms=latency,
            )

        except Exception as e:
            latency = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=latency,
            )

    def check_all(self) -> dict[str, HealthCheckResult]:
        """
        执行所有健康检查

        Returns:
            dict: 所有检查结果
        """
        results = {}
        for name in self._checks:
            results[name] = self.check(name)
        return results

    def is_healthy(self) -> bool:
        """
        检查是否所有服务健康

        Returns:
            bool: 是否全部健康
        """
        results = self.check_all()
        return all(r.status == HealthStatus.HEALTHY for r in results.values())

    def get_status(self) -> dict[str, Any]:
        """
        获取总体健康状态

        Returns:
            dict: 状态信息
        """
        results = self.check_all()
        overall = HealthStatus.HEALTHY

        for result in results.values():
            if result.status == HealthStatus.UNHEALTHY:
                overall = HealthStatus.UNHEALTHY
                break
            elif result.status == HealthStatus.DEGRADED:
                overall = HealthStatus.DEGRADED

        return {
            "status": overall.value,
            "checks": {
                name: {
                    "status": result.status.value,
                    "message": result.message,
                    "latency_ms": result.latency_ms,
                }
                for name, result in results.items()
            },
            "checked_at": datetime.now(UTC).isoformat(),
        }


def create_default_health_checker() -> HealthChecker:
    """
    创建默认健康检查器

    Returns:
        HealthChecker: 配置好的健康检查器
    """
    checker = HealthChecker()
    checker.register("influxdb", check_influxdb_health)
    checker.register("network", check_network_health)
    return checker


# 导出
__all__ = [
    "HealthStatus",
    "HealthCheckResult",
    "HealthChecker",
    "check_influxdb_health",
    "check_redis_health",
    "check_network_health",
    "create_default_health_checker",
]
