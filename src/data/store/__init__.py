"""
数据存储模块

存储分工:
- ParquetStore: 历史大体量数据 (OHLCV/特征矩阵/回测)
- InfluxStore: 实时/监控数据 (最新Bar/权益曲线/系统指标)

注意：此模块已弃用，请使用 src.data.storage 中的实现。
以下导入是为了向后兼容。
"""

# 向后兼容：从 storage 模块导入
from src.data.storage.influx_store import InfluxStore
from src.data.storage.parquet_store import ParquetStore

__all__ = ["ParquetStore", "InfluxStore"]
