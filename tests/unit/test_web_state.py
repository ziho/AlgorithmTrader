"""
Web API 单元测试
"""

import pytest
from datetime import datetime

from services.web.state import (
    AppState,
    ServiceStatus,
    StrategyInfo,
    BacktestInfo,
    OptimizationTask,
)


class TestServiceStatus:
    """ServiceStatus 测试"""
    
    def test_create_service_status(self):
        """测试创建服务状态"""
        status = ServiceStatus(
            name="collector",
            status="healthy",
            message="运行正常",
        )
        
        assert status.name == "collector"
        assert status.status == "healthy"
        assert status.message == "运行正常"
        assert status.last_check is None
    
    def test_default_values(self):
        """测试默认值"""
        status = ServiceStatus(name="test")
        
        assert status.status == "unknown"
        assert status.message == ""
        assert status.details == {}


class TestStrategyInfo:
    """StrategyInfo 测试"""
    
    def test_create_strategy_info(self):
        """测试创建策略信息"""
        info = StrategyInfo(
            name="dual_ma",
            class_name="DualMAStrategy",
            enabled=True,
            symbols=["BTC/USDT"],
            params={"fast_period": 10},
        )
        
        assert info.name == "dual_ma"
        assert info.class_name == "DualMAStrategy"
        assert info.enabled is True
        assert info.symbols == ["BTC/USDT"]
        assert info.params == {"fast_period": 10}
    
    def test_default_values(self):
        """测试默认值"""
        info = StrategyInfo(name="test", class_name="Test")
        
        assert info.enabled is False
        assert info.symbols == []
        assert info.timeframes == []
        assert info.params == {}
        assert info.today_pnl == 0.0
        assert info.status == "stopped"


class TestBacktestInfo:
    """BacktestInfo 测试"""
    
    def test_create_backtest_info(self):
        """测试创建回测信息"""
        now = datetime.now()
        info = BacktestInfo(
            id="bt_001",
            strategy_name="DualMAStrategy",
            start_date=now,
            end_date=now,
            created_at=now,
            status="completed",
            total_return=23.45,
            sharpe_ratio=1.82,
        )
        
        assert info.id == "bt_001"
        assert info.strategy_name == "DualMAStrategy"
        assert info.status == "completed"
        assert info.total_return == 23.45
        assert info.sharpe_ratio == 1.82


class TestOptimizationTask:
    """OptimizationTask 测试"""
    
    def test_create_optimization_task(self):
        """测试创建优化任务"""
        task = OptimizationTask(
            id="opt_001",
            strategy_name="DualMAStrategy",
            objectives=["sharpe", "return"],
            method="grid",
        )
        
        assert task.id == "opt_001"
        assert task.strategy_name == "DualMAStrategy"
        assert task.objectives == ["sharpe", "return"]
        assert task.method == "grid"
        assert task.status == "pending"
        assert task.progress == 0.0


class TestAppState:
    """AppState 测试"""
    
    @pytest.fixture
    def app_state(self):
        """创建测试用 AppState"""
        return AppState()
    
    def test_initial_state(self, app_state):
        """测试初始状态"""
        assert not app_state._initialized
        assert app_state._services == {}
        assert app_state._strategies == {}
    
    @pytest.mark.asyncio
    async def test_initialize(self, app_state):
        """测试初始化"""
        await app_state.initialize()
        
        assert app_state._initialized
        assert "collector" in app_state._services
        assert "trader" in app_state._services
        assert "scheduler" in app_state._services
        assert "influxdb" in app_state._services
    
    @pytest.mark.asyncio
    async def test_cleanup(self, app_state):
        """测试清理"""
        await app_state.initialize()
        await app_state.cleanup()
        
        # 清理后应该取消后台任务
        assert app_state._update_task is not None
    
    @pytest.mark.asyncio
    async def test_get_services(self, app_state):
        """测试获取服务状态"""
        await app_state.initialize()
        
        services = app_state.get_services()
        
        assert len(services) == 4
        assert all(isinstance(s, ServiceStatus) for s in services.values())
    
    @pytest.mark.asyncio
    async def test_update_strategy(self, app_state):
        """测试更新策略"""
        await app_state.initialize()
        
        # 添加测试策略
        app_state._strategies["test"] = StrategyInfo(
            name="test",
            class_name="TestStrategy",
        )
        
        # 更新策略
        success = app_state.update_strategy("test", enabled=True)
        
        assert success
        assert app_state._strategies["test"].enabled is True
    
    @pytest.mark.asyncio
    async def test_update_nonexistent_strategy(self, app_state):
        """测试更新不存在的策略"""
        await app_state.initialize()
        
        success = app_state.update_strategy("nonexistent", enabled=True)
        
        assert not success
    
    @pytest.mark.asyncio
    async def test_add_optimization_task(self, app_state):
        """测试添加优化任务"""
        await app_state.initialize()
        
        task = OptimizationTask(
            id="opt_test",
            strategy_name="Test",
            objectives=["sharpe"],
        )
        
        app_state.add_optimization_task(task)
        
        tasks = app_state.get_optimization_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "opt_test"
