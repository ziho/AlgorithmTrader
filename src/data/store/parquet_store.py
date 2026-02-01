"""
Parquet 存储

职责:
- 历史数据读写
- 分区规则 (交易所/品种/时间框架/年月)
- 增量追加与去重

注意：此模块已弃用，请使用 src.data.storage.parquet_store。
以下导入是为了向后兼容。
"""

# 向后兼容：从 storage 模块导入
from src.data.storage.parquet_store import ParquetStore

__all__ = ["ParquetStore"]
