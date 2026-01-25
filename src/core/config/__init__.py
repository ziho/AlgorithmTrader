"""
配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
支持从环境变量和 .env 文件加载配置
"""

from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
