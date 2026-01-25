"""
回测报告

职责:
- 生成回测摘要
- 写入 InfluxDB (便于 Grafana 对比)
- 详细结果落盘 (Parquet/JSON)
"""
