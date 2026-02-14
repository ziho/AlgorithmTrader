# AlgorithmTrader 数据采集使用指南

## 系统入口

- **Web UI**: http://localhost:8080
- **Grafana**: http://localhost:3000 (admin / algorithmtrader123)
- **InfluxDB**: http://localhost:8086

---

## OKX 自动采集（Collector 服务）

`collector` 服务会定时拉取 OKX K 线并写入 Parquet + InfluxDB。

默认配置：
- 交易对: BTC/USDT, ETH/USDT
- 时间框架: 15m, 1h
- 写入: Parquet + InfluxDB

启动服务：

```bash
docker compose --profile trading up -d collector
```

查看日志：

```bash
docker compose logs -f collector
```

---

## Binance 历史数据（批量下载）

### 方式一：命令行脚本

```bash
# 下载 BTC 1m 数据（2020-至今）
python -m scripts.fetch_history --symbol BTCUSDT --from 2020-01-01 --tf 1m

# 下载多个交易对
python -m scripts.fetch_history --symbols BTCUSDT,ETHUSDT,BNBUSDT --from 2020-01-01 --tf 1m

# 强制重新下载
python -m scripts.fetch_history --symbol BTCUSDT --tf 1m --force
```

特点：
- 断点续传（基于 `data/fetch_checkpoint.db`）
- 自动校验与重试
- 月级/日级回退

### 方式二：Web UI

进入 `数据管理 / 历史数据下载` 页面，选择交易对与时间范围即可启动。

---

## Binance 实时同步

`realtime_sync` 支持 WebSocket + REST 纠偏，落盘到 Parquet。

```bash
# 启动实时同步（默认主流币）
python -m scripts.realtime_sync

# 自定义交易对/周期
python -m scripts.realtime_sync --symbols BTCUSDT,ETHUSDT --timeframes 1m,1h

# 禁用 WebSocket（仅 REST 轮询）
python -m scripts.realtime_sync --no-websocket
```

Docker Profile：

```bash
docker compose --profile data up -d realtime-sync
```

---

## A 股数据回填（Tushare）

支持日线 OHLCV、每日基本面与复权因子回填：

```bash
# 日线 OHLCV
python scripts/backfill_a_share.py daily --incremental

# daily_basic
python scripts/backfill_a_share.py daily_basic --incremental

# adj_factor
python scripts/backfill_a_share.py adj_factor --incremental
```

查看状态：

```bash
python scripts/backfill_a_share.py status
```

---

## 数据查询

### InfluxDB CLI

```bash
docker compose exec influxdb influx query \
  'from(bucket:"trading") |> range(start: -1h) |> filter(fn: (r) => r["_measurement"] == "ohlcv") |> limit(n:10)' \
  --org algorithmtrader --token algorithmtrader-dev-token
```

### 本地 Parquet 查询

```bash
python -m scripts.data_query --list
python -m scripts.data_query --symbol BTCUSDT --from 2024-01-01 --to 2024-12-31
python -m scripts.data_query --symbol BTCUSDT --gaps
```

---

## 数据存储结构

- **Parquet**: `data/parquet/{exchange}/{symbol}/{timeframe}/year=YYYY/month=MM/data.parquet`
- **断点状态**: `data/fetch_checkpoint.db`
- **InfluxDB**: Docker volume `influxdb-data`
- **回测报告**: `reports/<run_id>/`

A 股基本面数据：
- `data/parquet/a_tushare_fundamentals/{daily_basic|adj_factor|forecast|fina_indicator}/year=YYYY/data.parquet`

---

## 常用命令

```bash
# 查看服务状态
docker compose ps

# 重启 Collector
docker compose restart collector

# 进入容器
docker compose exec collector bash
```
