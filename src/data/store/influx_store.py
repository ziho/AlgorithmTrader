"""
InfluxDB 存储

职责:
- 写入最新 Bar 数据
- 写入监控指标
- 查询接口

注意：此模块已弃用，请使用 src.data.storage.influx_store。
以下导入是为了向后兼容。
"""

# 向后兼容：从 storage 模块导入
from src.data.storage.influx_store import InfluxStore

__all__ = ["InfluxStore"]
