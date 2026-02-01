"""
策略配置管理器单元测试
"""

import json
import tempfile
from pathlib import Path

import pytest

from services.web.strategy_config import (
    STRATEGY_PARAM_SPACES,
    StrategyConfigManager,
    StrategyRunConfig,
)


class TestStrategyRunConfig:
    """StrategyRunConfig 测试"""

    def test_create_config(self):
        """测试创建配置"""
        config = StrategyRunConfig(
            name="my_dual_ma",
            strategy_class="DualMAStrategy",
            enabled=True,
            symbols=["BTC/USDT"],
            params={"fast_period": 10},
        )

        assert config.name == "my_dual_ma"
        assert config.strategy_class == "DualMAStrategy"
        assert config.enabled is True
        assert config.symbols == ["BTC/USDT"]
        assert config.params == {"fast_period": 10}

    def test_to_dict(self):
        """测试转为字典"""
        config = StrategyRunConfig(
            name="test",
            strategy_class="DualMAStrategy",
            enabled=True,
            symbols=["BTC/USDT"],
        )

        data = config.to_dict()

        assert data["name"] == "test"
        assert data["strategy_class"] == "DualMAStrategy"
        assert data["enabled"] is True
        assert data["symbols"] == ["BTC/USDT"]

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "name": "test",
            "strategy_class": "DualMAStrategy",
            "enabled": True,
            "symbols": ["BTC/USDT"],
            "params": {"fast_period": 15},
        }

        config = StrategyRunConfig.from_dict(data)

        assert config.name == "test"
        assert config.strategy_class == "DualMAStrategy"
        assert config.enabled is True
        assert config.params["fast_period"] == 15


class TestStrategyConfigManager:
    """StrategyConfigManager 测试"""

    @pytest.fixture
    def temp_config_file(self):
        """创建临时配置文件"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"strategies": []}, f)
            return Path(f.name)

    @pytest.fixture
    def manager(self, temp_config_file):
        """创建测试用管理器"""
        return StrategyConfigManager(config_path=temp_config_file)

    def test_load_empty_config(self, manager):
        """测试加载空配置"""
        manager.load()

        assert len(manager.get_all()) == 0

    def test_add_and_get(self, manager):
        """测试添加和获取配置"""
        config = StrategyRunConfig(
            name="test_strategy",
            strategy_class="DualMAStrategy",
        )

        manager.add(config)

        result = manager.get("test_strategy")
        assert result is not None
        assert result.name == "test_strategy"

    def test_update_config(self, manager):
        """测试更新配置"""
        config = StrategyRunConfig(
            name="test_strategy",
            strategy_class="DualMAStrategy",
            enabled=False,
        )
        manager.add(config)

        success = manager.update("test_strategy", enabled=True)

        assert success
        result = manager.get("test_strategy")
        assert result.enabled is True

    def test_update_nonexistent(self, manager):
        """测试更新不存在的配置"""
        success = manager.update("nonexistent", enabled=True)

        assert not success

    def test_delete_config(self, manager):
        """测试删除配置"""
        config = StrategyRunConfig(
            name="test_strategy",
            strategy_class="DualMAStrategy",
        )
        manager.add(config)

        success = manager.delete("test_strategy")

        assert success
        assert manager.get("test_strategy") is None

    def test_persistence(self, temp_config_file):
        """测试配置持久化"""
        # 创建并保存
        manager1 = StrategyConfigManager(config_path=temp_config_file)
        config = StrategyRunConfig(
            name="persistent_strategy",
            strategy_class="DualMAStrategy",
            enabled=True,
            symbols=["BTC/USDT"],
        )
        manager1.add(config)

        # 重新加载
        manager2 = StrategyConfigManager(config_path=temp_config_file)
        manager2.load()

        result = manager2.get("persistent_strategy")
        assert result is not None
        assert result.name == "persistent_strategy"
        assert result.enabled is True

    def test_get_param_space(self, manager):
        """测试获取参数空间"""
        param_space = manager.get_param_space("DualMAStrategy")

        assert "fast_period" in param_space
        assert "slow_period" in param_space
        assert param_space["fast_period"]["type"] == "int"

    def test_get_default_params(self, manager):
        """测试获取默认参数"""
        defaults = manager.get_default_params("DualMAStrategy")

        assert defaults["fast_period"] == 10
        assert defaults["slow_period"] == 30
        assert defaults["position_size"] == 1.0


class TestStrategyParamSpaces:
    """参数空间定义测试"""

    def test_all_strategies_have_position_size(self):
        """测试所有策略都有 position_size 参数"""
        for strategy, params in STRATEGY_PARAM_SPACES.items():
            assert "position_size" in params, f"{strategy} missing position_size"

    def test_param_space_structure(self):
        """测试参数空间结构正确"""
        for strategy, params in STRATEGY_PARAM_SPACES.items():
            for param_name, spec in params.items():
                assert "type" in spec, f"{strategy}.{param_name} missing type"
                assert "default" in spec, f"{strategy}.{param_name} missing default"

                if spec["type"] in ("int", "float"):
                    assert "min" in spec, f"{strategy}.{param_name} missing min"
                    assert "max" in spec, f"{strategy}.{param_name} missing max"
