"""
通用配置加载器
统一管理 YAML 配置文件的加载和验证
"""
import os
import yaml
from typing import Dict, Any, Optional
import logging

class ConfigLoader:
    """配置加载器"""
    
    def __init__(self, config_dir: str = "/config"):
        self.config_dir = config_dir
        self.logger = logging.getLogger(__name__)
        self._configs = {}
    
    def load_config(self, config_name: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        加载指定的配置文件
        
        Args:
            config_name: 配置文件名(不含扩展名)
            use_cache: 是否使用缓存
            
        Returns:
            配置字典
        """
        if use_cache and config_name in self._configs:
            return self._configs[config_name]
            
        config_path = os.path.join(self.config_dir, f"{config_name}.yml")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
            if use_cache:
                self._configs[config_name] = config
                
            self.logger.info(f"Loaded config: {config_name}")
            return config
            
        except FileNotFoundError:
            self.logger.error(f"Config file not found: {config_path}")
            raise
        except yaml.YAMLError as e:
            self.logger.error(f"Error parsing YAML config {config_name}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error loading config {config_name}: {e}")
            raise
    
    def get_config_value(self, config_name: str, key_path: str, 
                        default: Any = None) -> Any:
        """
        获取配置中的特定值
        
        Args:
            config_name: 配置文件名
            key_path: 键路径，用点分隔，如 'global.timezone'
            default: 默认值
            
        Returns:
            配置值
        """
        try:
            config = self.load_config(config_name)
            
            keys = key_path.split('.')
            value = config
            
            for key in keys:
                value = value[key]
                
            return value
            
        except (KeyError, TypeError):
            self.logger.warning(
                f"Config key not found: {config_name}.{key_path}, using default: {default}"
            )
            return default
    
    def reload_config(self, config_name: str) -> Dict[str, Any]:
        """重新加载配置文件"""
        if config_name in self._configs:
            del self._configs[config_name]
        return self.load_config(config_name, use_cache=True)
    
    def reload_all_configs(self):
        """重新加载所有缓存的配置"""
        config_names = list(self._configs.keys())
        self._configs.clear()
        
        for config_name in config_names:
            try:
                self.load_config(config_name, use_cache=True)
            except Exception as e:
                self.logger.error(f"Error reloading config {config_name}: {e}")

# 全局配置加载器实例
config_loader = ConfigLoader()

def load_data_collection_config() -> Dict[str, Any]:
    """加载数据采集配置"""
    return config_loader.load_config('data_collection')

def load_strategy_config() -> Dict[str, Any]:
    """加载策略配置"""
    return config_loader.load_config('strategy')

def load_risk_management_config() -> Dict[str, Any]:
    """加载风险管理配置"""
    return config_loader.load_config('risk_management')

def load_monitoring_config() -> Dict[str, Any]:
    """加载监控配置"""
    return config_loader.load_config('monitoring')

def load_alerts_config() -> Dict[str, Any]:
    """加载告警配置"""
    return config_loader.load_config('alerts')

def get_binance_symbols() -> list:
    """获取需要采集的币安交易对列表"""
    return config_loader.get_config_value('data_collection', 'binance.symbols', ['BTCUSDT'])

def get_strategy_parameters(strategy_name: str) -> Dict[str, Any]:
    """获取指定策略的参数"""
    return config_loader.get_config_value('strategy', f'{strategy_name}.parameters', {})

def get_bark_config() -> Dict[str, Any]:
    """获取Bark推送配置"""
    return config_loader.get_config_value('alerts', 'bark', {})
