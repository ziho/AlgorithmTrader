"""
健康检查模块测试
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.ops.healthcheck import (
    HealthChecker,
    HealthCheckResult,
    HealthStatus,
    check_influxdb_health,
    check_network_health,
    create_default_health_checker,
)


class TestHealthStatus:
    """HealthStatus 枚举测试"""

    def test_status_values(self):
        """测试状态值"""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"


class TestHealthCheckResult:
    """HealthCheckResult 测试"""

    def test_basic_result(self):
        """测试基本结果"""
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
        )

        assert result.name == "test"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "OK"
        assert result.latency_ms == 0.0
        assert result.checked_at is not None

    def test_result_with_details(self):
        """测试带详情的结果"""
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.UNHEALTHY,
            message="Connection failed",
            details={"error": "timeout"},
            latency_ms=100.5,
        )

        assert result.details == {"error": "timeout"}
        assert result.latency_ms == 100.5


class TestCheckInfluxDBHealth:
    """check_influxdb_health 测试"""

    def test_healthy_influxdb(self):
        """测试 InfluxDB 健康"""
        with patch("influxdb_client.InfluxDBClient") as mock_client_class:
            mock_client = MagicMock()
            mock_health = MagicMock()
            mock_health.status = "pass"
            mock_health.message = "OK"
            mock_client.health.return_value = mock_health
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=None)

            result = check_influxdb_health(
                url="http://localhost:8086",
                token="test-token",
            )

            assert result is True

    def test_unhealthy_influxdb(self):
        """测试 InfluxDB 不健康"""
        with patch("influxdb_client.InfluxDBClient") as mock_client_class:
            mock_client = MagicMock()
            mock_health = MagicMock()
            mock_health.status = "fail"
            mock_client.health.return_value = mock_health
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=None)

            result = check_influxdb_health(
                url="http://localhost:8086",
                token="test-token",
            )

            assert result is False

    def test_influxdb_import_error(self):
        """测试 InfluxDB 库未安装"""
        with patch.dict("sys.modules", {"influxdb_client": None}):
            # 这会触发 ImportError 逻辑
            pass  # 实际测试需要更复杂的 mock

    def test_influxdb_connection_error(self):
        """测试 InfluxDB 连接错误"""
        with patch("influxdb_client.InfluxDBClient") as mock_client_class:
            mock_client_class.side_effect = Exception("Connection refused")

            result = check_influxdb_health(
                url="http://localhost:8086",
                token="test-token",
            )

            assert result is False


class TestCheckNetworkHealth:
    """check_network_health 测试"""

    @patch("httpx.Client")
    def test_network_healthy(self, mock_client_class):
        """测试网络健康"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=None)

        result = check_network_health(url="https://example.com")

        assert result is True

    @patch("httpx.Client")
    def test_network_unhealthy(self, mock_client_class):
        """测试网络不健康"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=None)

        result = check_network_health(url="https://example.com")

        assert result is False

    @patch("httpx.Client")
    def test_network_connection_error(self, mock_client_class):
        """测试网络连接错误"""
        mock_client_class.side_effect = Exception("Connection timeout")

        result = check_network_health(url="https://example.com")

        assert result is False


class TestHealthChecker:
    """HealthChecker 测试"""

    def test_register_check(self):
        """测试注册检查函数"""
        checker = HealthChecker()

        checker.register("test", lambda: True)

        assert "test" in checker._checks

    def test_check_healthy(self):
        """测试健康检查通过"""
        checker = HealthChecker()
        checker.register("test", lambda: True)

        result = checker.check("test")

        assert result.name == "test"
        assert result.status == HealthStatus.HEALTHY

    def test_check_unhealthy(self):
        """测试健康检查失败"""
        checker = HealthChecker()
        checker.register("test", lambda: False)

        result = checker.check("test")

        assert result.status == HealthStatus.UNHEALTHY

    def test_check_unknown(self):
        """测试未知检查"""
        checker = HealthChecker()

        result = checker.check("unknown")

        assert result.status == HealthStatus.UNKNOWN
        assert "Unknown check" in result.message

    def test_check_with_exception(self):
        """测试检查抛出异常"""
        checker = HealthChecker()
        checker.register("test", lambda: 1 / 0)

        result = checker.check("test")

        assert result.status == HealthStatus.UNHEALTHY
        assert "division by zero" in result.message

    def test_check_returns_health_result(self):
        """测试检查返回 HealthCheckResult"""
        checker = HealthChecker()
        custom_result = HealthCheckResult(
            name="custom",
            status=HealthStatus.DEGRADED,
            message="Partially working",
        )
        checker.register("test", lambda: custom_result)

        result = checker.check("test")

        assert result == custom_result

    def test_check_all(self):
        """测试检查所有"""
        checker = HealthChecker()
        checker.register("healthy", lambda: True)
        checker.register("unhealthy", lambda: False)

        results = checker.check_all()

        assert len(results) == 2
        assert results["healthy"].status == HealthStatus.HEALTHY
        assert results["unhealthy"].status == HealthStatus.UNHEALTHY

    def test_is_healthy_all_pass(self):
        """测试全部健康"""
        checker = HealthChecker()
        checker.register("test1", lambda: True)
        checker.register("test2", lambda: True)

        assert checker.is_healthy() is True

    def test_is_healthy_some_fail(self):
        """测试部分失败"""
        checker = HealthChecker()
        checker.register("healthy", lambda: True)
        checker.register("unhealthy", lambda: False)

        assert checker.is_healthy() is False

    def test_get_status(self):
        """测试获取状态"""
        checker = HealthChecker()
        checker.register("test", lambda: True)

        status = checker.get_status()

        assert status["status"] == "healthy"
        assert "test" in status["checks"]
        assert "checked_at" in status

    def test_get_status_degraded(self):
        """测试获取降级状态"""
        checker = HealthChecker()
        checker.register(
            "degraded",
            lambda: HealthCheckResult(
                name="degraded",
                status=HealthStatus.DEGRADED,
            ),
        )

        status = checker.get_status()

        assert status["status"] == "degraded"

    def test_get_status_unhealthy(self):
        """测试获取不健康状态"""
        checker = HealthChecker()
        checker.register("unhealthy", lambda: False)

        status = checker.get_status()

        assert status["status"] == "unhealthy"


class TestCreateDefaultHealthChecker:
    """create_default_health_checker 测试"""

    def test_creates_checker_with_defaults(self):
        """测试创建默认检查器"""
        checker = create_default_health_checker()

        assert isinstance(checker, HealthChecker)
        assert "influxdb" in checker._checks
        assert "network" in checker._checks
