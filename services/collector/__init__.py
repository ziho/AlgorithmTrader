"""
Collector 服务 - 数据采集

职责:
- 定时拉取 K线数据 (15m/1h)
- 同时写入 Parquet + InfluxDB
- 缺口检测与告警
"""
