"""
策略配置管理

负责：
- 加载/保存策略运行配置
- 策略状态持久化
- 与策略注册中心集成
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.ops.logging import get_logger
from src.strategy.registry import get_strategy, list_strategies

logger = get_logger(__name__)


# 内置策略的参数空间定义
STRATEGY_PARAM_SPACES: dict[str, dict[str, dict[str, Any]]] = {
    "DualMAStrategy": {
        "fast_period": {
            "type": "int",
            "min": 5,
            "max": 50,
            "step": 5,
            "default": 10,
            "description": "快线周期",
        },
        "slow_period": {
            "type": "int",
            "min": 20,
            "max": 100,
            "step": 10,
            "default": 30,
            "description": "慢线周期",
        },
        "position_size": {
            "type": "float",
            "min": 0.1,
            "max": 1.0,
            "step": 0.1,
            "default": 1.0,
            "description": "仓位大小",
        },
        "allow_short": {
            "type": "bool",
            "default": False,
            "description": "允许做空",
        },
        "use_ema": {
            "type": "bool",
            "default": False,
            "description": "使用EMA而非SMA",
        },
    },
    "DonchianBreakoutStrategy": {
        "entry_period": {
            "type": "int",
            "min": 10,
            "max": 50,
            "step": 5,
            "default": 20,
            "description": "入场通道周期",
        },
        "exit_period": {
            "type": "int",
            "min": 5,
            "max": 30,
            "step": 5,
            "default": 10,
            "description": "出场通道周期",
        },
        "position_size": {
            "type": "float",
            "min": 0.1,
            "max": 1.0,
            "step": 0.1,
            "default": 1.0,
            "description": "仓位大小",
        },
        "allow_short": {
            "type": "bool",
            "default": False,
            "description": "允许做空",
        },
    },
    "BollingerBandsStrategy": {
        "period": {
            "type": "int",
            "min": 10,
            "max": 50,
            "step": 5,
            "default": 20,
            "description": "布林带周期",
        },
        "std_dev": {
            "type": "float",
            "min": 1.0,
            "max": 3.0,
            "step": 0.5,
            "default": 2.0,
            "description": "标准差倍数",
        },
        "position_size": {
            "type": "float",
            "min": 0.1,
            "max": 1.0,
            "step": 0.1,
            "default": 1.0,
            "description": "仓位大小",
        },
        "exit_at_middle": {
            "type": "bool",
            "default": True,
            "description": "在中轨平仓",
        },
    },
    "RSIMeanReversionStrategy": {
        "period": {
            "type": "int",
            "min": 7,
            "max": 28,
            "step": 7,
            "default": 14,
            "description": "RSI周期",
        },
        "oversold": {
            "type": "int",
            "min": 20,
            "max": 40,
            "step": 5,
            "default": 30,
            "description": "超卖阈值",
        },
        "overbought": {
            "type": "int",
            "min": 60,
            "max": 80,
            "step": 5,
            "default": 70,
            "description": "超买阈值",
        },
        "position_size": {
            "type": "float",
            "min": 0.1,
            "max": 1.0,
            "step": 0.1,
            "default": 1.0,
            "description": "仓位大小",
        },
    },
    "ZScoreStrategy": {
        "lookback_period": {
            "type": "int",
            "min": 10,
            "max": 50,
            "step": 5,
            "default": 20,
            "description": "回看周期",
        },
        "entry_zscore": {
            "type": "float",
            "min": 1.5,
            "max": 3.0,
            "step": 0.5,
            "default": 2.0,
            "description": "入场Z分数",
        },
        "exit_zscore": {
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "step": 0.25,
            "default": 0.5,
            "description": "出场Z分数",
        },
        "position_size": {
            "type": "float",
            "min": 0.1,
            "max": 1.0,
            "step": 0.1,
            "default": 1.0,
            "description": "仓位大小",
        },
    },
}


@dataclass
class StrategyRunConfig:
    """策略运行配置"""

    name: str  # 配置名称（唯一标识）
    strategy_class: str  # 策略类名
    enabled: bool = False
    symbols: list[str] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=lambda: ["15m"])
    params: dict[str, Any] = field(default_factory=dict)

    # 运行时状态（不持久化）
    status: str = "stopped"  # running, stopped, error
    current_position: dict[str, float] = field(default_factory=dict)
    today_pnl: float = 0.0
    last_updated: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化字典"""
        return {
            "name": self.name,
            "strategy_class": self.strategy_class,
            "enabled": self.enabled,
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyRunConfig":
        """从字典创建"""
        return cls(
            name=data["name"],
            strategy_class=data["strategy_class"],
            enabled=data.get("enabled", False),
            symbols=data.get("symbols", []),
            timeframes=data.get("timeframes", ["15m"]),
            params=data.get("params", {}),
        )


class StrategyConfigManager:
    """
    策略配置管理器

    负责加载、保存和管理所有策略的运行配置
    """

    CONFIG_FILE = "config/strategies.json"

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else Path(self.CONFIG_FILE)
        self._configs: dict[str, StrategyRunConfig] = {}
        self._loaded = False

    def load(self) -> None:
        """加载配置文件"""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    data = json.load(f)

                for item in data.get("strategies", []):
                    config = StrategyRunConfig.from_dict(item)
                    self._configs[config.name] = config

                logger.info("strategy_configs_loaded", count=len(self._configs))
            except Exception as e:
                logger.error("strategy_configs_load_failed", error=str(e))

        self._loaded = True

    def save(self) -> None:
        """保存配置文件"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "strategies": [c.to_dict() for c in self._configs.values()],
            "updated_at": datetime.now().isoformat(),
        }

        with open(self.config_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("strategy_configs_saved", count=len(self._configs))

    def get_all(self) -> list[StrategyRunConfig]:
        """获取所有配置"""
        if not self._loaded:
            self.load()
        return list(self._configs.values())

    def get(self, name: str) -> StrategyRunConfig | None:
        """获取单个配置"""
        if not self._loaded:
            self.load()
        return self._configs.get(name)

    def add(self, config: StrategyRunConfig) -> None:
        """添加配置"""
        self._configs[config.name] = config
        self.save()

    def update(self, name: str, **kwargs) -> bool:
        """更新配置"""
        if name not in self._configs:
            return False

        config = self._configs[name]
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)

        self.save()
        return True

    def delete(self, name: str) -> bool:
        """删除配置"""
        if name not in self._configs:
            return False

        del self._configs[name]
        self.save()
        return True

    def get_available_strategies(self) -> list[dict[str, Any]]:
        """
        获取所有可用的策略类

        返回策略类信息，包括参数空间
        """
        strategies = []

        for strategy_name in list_strategies():
            strategy_cls = get_strategy(strategy_name)
            if strategy_cls:
                class_name = strategy_cls.__name__
                param_space = STRATEGY_PARAM_SPACES.get(class_name, {})

                strategies.append(
                    {
                        "name": strategy_name,
                        "class_name": class_name,
                        "param_space": param_space,
                        "doc": strategy_cls.__doc__ or "",
                    }
                )

        return strategies

    def get_param_space(self, strategy_class: str) -> dict[str, dict[str, Any]]:
        """获取策略的参数空间"""
        return STRATEGY_PARAM_SPACES.get(strategy_class, {})

    def get_default_params(self, strategy_class: str) -> dict[str, Any]:
        """获取策略的默认参数"""
        param_space = self.get_param_space(strategy_class)
        return {key: spec.get("default") for key, spec in param_space.items()}


# 全局实例
_config_manager: StrategyConfigManager | None = None


def get_config_manager() -> StrategyConfigManager:
    """获取配置管理器单例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = StrategyConfigManager()
    return _config_manager


# 导出
__all__ = [
    "STRATEGY_PARAM_SPACES",
    "StrategyRunConfig",
    "StrategyConfigManager",
    "get_config_manager",
]
