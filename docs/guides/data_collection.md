# AlgorithmTrader 数据采集使用指南

## 📊 系统状态

访问以下链接查看系统:
- **Web UI**: http://localhost:8080
- **Grafana**: http://localhost:3000 (用户名: admin, 密码: algorithmtrader123)
- **InfluxDB**: http://localhost:8086 (用户名: admin, 密码: algorithmtrader123)

## 🔄 数据采集服务

### 1. OKX 自动采集 (默认运行)

`collector` 服务会自动从 OKX 采集数据：
- 交易对: BTC/USDT, ETH/USDT
- 时间框架: 15m, 1h
- 数据存储: InfluxDB + Parquet

查看状态:
```bash
docker-compose logs -f collector
```

### 2. Binance 实时采集

#### 前台运行 (测试用)
```bash
docker-compose exec collector python scripts/realtime_collector.py \
    --symbols BTCUSDT,ETHUSDT \
    --timeframes 1m,1h \
    --exchange binance \
    --interval 60
```

#### 后台运行 (生产用)
```bash
nohup docker-compose exec -T collector python scripts/realtime_collector.py \
    --symbols BTCUSDT,ETHUSDT \
    --timeframes 1m,1h \
    --exchange binance \
    --interval 60 > /tmp/binance_collector.log 2>&1 &
```

查看日志:
```bash
tail -f /tmp/binance_collector.log
```

### 3. 历史数据导入

从 Binance 下载历史数据并导入:
```bash
docker-compose exec collector python scripts/import_historical_data.py \
    --symbol BTCUSDT \
    --timeframe 1h \
    --start 2024-01-01 \
    --end 2025-12-31
```

## 📈 回测

运行 BTC 回测:
```bash
docker-compose exec collector python scripts/run_btc_backtest.py
```

回测报告存储在 `reports/` 目录.

## 🔍 数据查询

### InfluxDB CLI
```bash
docker-compose exec influxdb influx query \
  'from(bucket:"trading") |> range(start: -1h) |> filter(fn: (r) => r["_measurement"] == "ohlcv") |> limit(n:10)' \
  --org algorithmtrader --token algorithmtrader-dev-token
```

### 查看 Binance 数据
```bash
docker-compose exec influxdb influx query \
  'from(bucket:"trading") |> range(start: -1h) |> filter(fn: (r) => r["exchange"] == "BINANCE") |> limit(n:5)' \
  --org algorithmtrader --token algorithmtrader-dev-token
```

## 📁 数据存储位置

- **Parquet 文件**: `data/parquet/{exchange}/{symbol}/{timeframe}/year={YYYY}/month={MM}/data.parquet`
- **原始文件** (可选): `data/raw/{exchange}/{symbol}/{timeframe}/`
- **断点状态**: `data/fetch_checkpoint.db`
- **InfluxDB**: Docker volume `influxdb-data`
- **回测报告**: `reports/`

---

## 📥 历史数据批量下载

### 1. 使用 fetch_history 脚本

从 Binance Public Data (data.binance.vision) 批量下载历史 K 线:

```bash
# 下载 BTC 1分钟数据 (2020-2026)
docker-compose exec collector python -m scripts.fetch_history \
    --symbol BTCUSDT --from 2020-01-01 --to 2026-02-01 --tf 1m

# 下载多个交易对
docker-compose exec collector python -m scripts.fetch_history \
    --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT \
    --from 2017-01-01 --tf 1m

# 下载小时数据
docker-compose exec collector python -m scripts.fetch_history \
    --symbol BTCUSDT --tf 1h --from 2020-01-01

# 强制重新下载 (忽略断点)
docker-compose exec collector python -m scripts.fetch_history \
    --symbol BTCUSDT --tf 1m --force

# 指定输出目录和市场类型
docker-compose exec collector python -m scripts.fetch_history \
    --symbol BTCUSDT --tf 1m --dest data --market spot
```

**特点:**
- ✅ 断点续传: 中断后重新运行自动跳过已完成月份
- ✅ 校验和验证: 自动验证 SHA256 (如果提供)
- ✅ 速率限制: 遵守交易所限制，自动重试
- ✅ 日级回退: 如果月级数据不存在，自动尝试日级数据

### 2. Python API

```python
import asyncio
from datetime import datetime, UTC
from src.data.fetcher import HistoryFetcher, get_history

# 方式 1: 使用 HistoryFetcher
async def download_data():
    fetcher = HistoryFetcher(data_dir="./data", exchange="binance")
    
    async with fetcher:
        stats = await fetcher.download_and_save(
            symbol="BTCUSDT",
            timeframe="1m",
            start_date=datetime(2024, 1, 1, tzinfo=UTC),
            end_date=datetime(2024, 12, 31, tzinfo=UTC),
        )
        print(f"下载完成: {stats.completed_months} 月, {stats.total_rows} 行")

asyncio.run(download_data())

# 方式 2: 使用 get_history 便捷函数 (已下载后读取)
df = get_history("binance", "BTCUSDT", "2024-01-01", "2024-12-31", tf="1m")
print(df.head())
```

---

## 🔄 实时数据同步

### 1. 使用 realtime_sync 脚本

持续同步最新 K 线数据:

```bash
# 启动实时同步 (默认 6 个主流币种)
docker-compose exec collector python -m scripts.realtime_sync

# 指定交易对和时间框架
docker-compose exec collector python -m scripts.realtime_sync \
    --symbols BTCUSDT,ETHUSDT --timeframes 1m,1h

# 禁用 WebSocket，使用 REST 轮询
docker-compose exec collector python -m scripts.realtime_sync --no-websocket

# 后台运行
nohup docker-compose exec -T collector python -m scripts.realtime_sync \
    > logs/realtime_sync.log 2>&1 &
```

**特点:**
- 📡 WebSocket 实时接收新 bar
- 🔧 启动时自动检测并补齐缺口
- 🔄 定期与 REST API 对比纠偏
- 🚀 支持多交易对并发

### 2. 数据查询工具

```bash
# 查看可用数据
docker-compose exec collector python -m scripts.data_query --list

# 查询特定交易对
docker-compose exec collector python -m scripts.data_query \
    --symbol BTCUSDT --from 2024-01-01 --to 2024-12-31

# 检测缺口
docker-compose exec collector python -m scripts.data_query --symbol BTCUSDT --gaps

# 导出为 CSV
docker-compose exec collector python -m scripts.data_query \
    --symbol BTCUSDT --tf 1h --export btc_1h.csv

# 聚合到更高周期
docker-compose exec collector python -m scripts.data_query \
    --symbol BTCUSDT --tf 1m --aggregate 1h
```

---

## 🛠️ 常用命令

```bash
# 查看所有服务状态
docker-compose ps

# 重启服务
docker-compose restart collector

# 查看日志
docker-compose logs -f --tail 50 collector

# 进入容器
docker-compose exec collector bash

# 测试 Binance 连接
docker-compose exec collector python -c "
import asyncio
from src.data.connectors.binance import BinanceConnector
from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe

async def test():
    conn = BinanceConnector()
    sym = Symbol(exchange=Exchange.BINANCE, base='BTC', quote='USDT')
    df = await conn.fetch_ohlcv(symbol=sym, timeframe=Timeframe('1h'), limit=5)
    print(df)
    await conn.close()

asyncio.run(test())
"
```

## 📊 Grafana Dashboards

访问 http://localhost:3000 查看:
1. **Data Monitor** - K线数据和交易对价格
2. **Trading Monitor** - 交易监控
3. **Risk Monitor** - 风险指标
4. **Backtest Results** - 回测结果

选择时间范围为 "Last 7 days" 或更长来查看历史数据。
