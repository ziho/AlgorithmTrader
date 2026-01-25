# InfluxDB 配置

## Bucket 规划

- `trading` - 交易数据 (OHLCV, 权益曲线, 交易记录)
- `metrics` - 系统监控指标
- `backtest` - 回测结果

## 保留策略

- 实时数据: 30-180 天
- 长期数据: 存储在 Parquet
