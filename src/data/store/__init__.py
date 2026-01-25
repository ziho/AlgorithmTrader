"""
数据存储模块

存储分工:
- ParquetStore: 历史大体量数据 (OHLCV/特征矩阵/回测)
- InfluxStore: 实时/监控数据 (最新Bar/权益曲线/系统指标)
"""
