# AlgorithmTrader 使用指南

> 个人中低频量化交易系统（以代码为准）

## 目录

- [项目概述](#项目概述)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [核心模块详解](#核心模块详解)
- [数据采集](#数据采集)
- [回测系统](#回测系统)
- [实盘交易](#实盘交易)
- [运维监控](#运维监控)

---

## 项目概述

AlgorithmTrader 是一个面向个人的中低频量化交易系统，当前代码实现支持：

| 维度 | 说明 |
|------|------|
| **交易频率** | 15 分钟 ~ 1 小时为主（可扩展） |
| **数据来源** | OKX / Binance / Tushare |
| **回测支持** | 加密货币 + A 股日线规则 |
| **实盘支持** | OKX 现货 / 永续 |
| **策略类型** | 趋势跟踪、均值回归（内置示例） |
| **特征/因子** | 内置特征引擎 + A 股因子库 |

### 技术栈

- **语言**: Python 3.11+
- **数据存储**: Parquet + DuckDB
- **实时监控**: InfluxDB + Grafana
- **Web 管理**: NiceGUI
- **通知**: Telegram / Bark / Webhook / SMTP

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                         services/                           │
│  collector   trader   scheduler   backtest_runner   web      │
│  notifier    data-fetcher   realtime-sync                   │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                            src/                             │
│  core  data  strategy  backtest  execution  risk  ops        │
│  features  optimization  portfolio                          │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                           storage                            │
│         Parquet (历史)          InfluxDB (实时)               │
└─────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/ziho/AlgorithmTrader.git
cd AlgorithmTrader

# 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

关键配置项（节选）：

```dotenv
# 环境
ENV=dev

# OKX 交易所 (模拟盘/实盘)
OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=
OKX_SIM_API_KEY=
OKX_SIM_API_SECRET=
OKX_SIM_PASSPHRASE=
OKX_SIMULATED_TRADING=true

# Tushare
TUSHARE_TOKEN=
TUSHARE_REQUESTS_PER_MINUTE=200

# InfluxDB
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=algorithmtrader-dev-token
INFLUXDB_ORG=algorithmtrader
INFLUXDB_BUCKET=trading

# 通知
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
BARK_URLS=
WEBHOOK_URL=
# SMTP_* (可选)
```

### 3. 启动基础设施

```bash
# 启动 InfluxDB + Grafana
docker compose up -d influxdb grafana

# 查看状态
docker compose ps
```

### 4. 运行测试

```bash
pytest tests/unit/ -v
```

---

## 核心模块详解

### 数据层 (`src/data/`)

#### OKX / Binance 数据连接器

```python
import asyncio
from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.data.connectors.okx import OKXConnector
from src.data.connectors.binance import BinanceConnector

async def fetch_okx():
    async with OKXConnector() as connector:
        sym = Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT")
        df = await connector.fetch_ohlcv(sym, Timeframe.M15, limit=100)
        return df

async def fetch_binance():
    async with BinanceConnector() as connector:
        sym = Symbol(exchange=Exchange.BINANCE, base="BTC", quote="USDT")
        df = await connector.fetch_ohlcv(sym, Timeframe("1h"), limit=100)
        return df

asyncio.run(fetch_okx())
```

#### Tushare A 股连接器

```python
import asyncio
from src.data.connectors.tushare import TushareConnector

async def fetch_trade_calendar():
    conn = TushareConnector()
    dates = await conn.fetch_trade_calendar(start_date="20240101", end_date="20240131")
    return dates

asyncio.run(fetch_trade_calendar())
```

#### 数据存储

```python
from src.data.storage.parquet_store import ParquetStore
from src.data.storage.influx_store import InfluxStore
from src.data.storage.a_share_store import AShareFundamentalsStore

# Parquet (历史)
parquet = ParquetStore(base_path="./data/parquet")
parquet.write(symbol, timeframe, df)

# InfluxDB (实时指标)
influx = InfluxStore()
influx.write_ohlcv(symbol, timeframe, df.tail(3))

# A 股基本面
fund_store = AShareFundamentalsStore()
fund_store.write("daily_basic", df_basic)
```

---

### 策略层 (`src/strategy/`)

#### 策略基类

```python
from src.strategy.base import StrategyBase, StrategyConfig
from src.core.typing import BarFrame, StrategyOutput

class MyStrategy(StrategyBase):
    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)
        self.period = self.get_param("period", 20)

    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        symbol = bar_frame.symbol
        if bar_frame.history is None or len(bar_frame.history) < self.period:
            return None

        close = float(bar_frame.close)
        ma = bar_frame.history["close"].tail(self.period).mean()

        if close > ma:
            return self.target_long(symbol, quantity=1.0, reason="close_above_ma")
        if close < ma:
            return self.target_flat(symbol, reason="close_below_ma")
        return None
```

#### 内置策略

| 策略 | 类名 | 说明 |
|------|------|------|
| 双均线交叉 | `DualMAStrategy` | 快线上穿慢线做多，下穿平仓 |
| 通道突破 | `DonchianBreakoutStrategy` | 突破 N 日高点做多，跌破 N 日低点平仓 |
| 布林带 | `BollingerBandsStrategy` | 触及下轨做多，触及上轨平仓 |
| RSI | `RSIMeanReversionStrategy` | 超卖做多，超买平仓 |
| Z-Score | `ZScoreStrategy` | 标准化偏离度交易 |

---

### 回测引擎 (`src/backtest/`)

#### 方式一：从 Parquet 读取

```python
from decimal import Decimal
from src.backtest.engine import BacktestConfig, BacktestEngine
from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.strategy.examples import DualMAStrategy
from src.strategy.base import StrategyConfig

strategy = DualMAStrategy(
    config=StrategyConfig(
        name="btc_dual_ma",
        symbols=["BTC/USDT"],
        params={"fast_period": 10, "slow_period": 30, "position_size": 0.1},
    )
)

config = BacktestConfig(
    initial_capital=Decimal("100000"),
    commission_rate=Decimal("0.001"),
    slippage_pct=Decimal("0.0005"),
    exchange="okx",
)

engine = BacktestEngine(config=config)

result = engine.run(
    strategy=strategy,
    symbols=[Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT")],
    timeframe=Timeframe("15m"),
)
```

#### 方式二：直接传入 DataFrame

```python
from src.backtest.engine import BacktestEngine

engine = BacktestEngine()
result = engine.run_with_data(
    strategy=strategy,
    data={"OKX:BTC/USDT": df},
    timeframe="15m",
)
```

#### 回测报告

```python
from src.backtest.reports import ReportConfig, ReportGenerator

generator = ReportGenerator(ReportConfig(output_dir="./reports"))
report = generator.generate_report(result)
print(report["summary"]["total_return"])
```

---

### 执行层 (`src/execution/`)

#### OKX 现货

```python
from src.execution.adapters.okx_spot import OKXSpotBroker

broker = OKXSpotBroker(sandbox=True)

broker.connect()
# ... place_order / get_balance / query_order
broker.disconnect()
```

#### OKX 永续

```python
from src.execution.adapters.okx_swap import OKXSwapBroker

broker = OKXSwapBroker(sandbox=True, default_leverage=10)

broker.connect()
broker.set_leverage("BTC/USDT:USDT", 20)
result = broker.open_long("BTC/USDT:USDT", quantity=0.01)
result = broker.close_long("BTC/USDT:USDT", quantity=0.01)
broker.disconnect()
```

---

### 风控引擎 (`src/risk/`)

```python
from src.risk.engine import create_default_risk_engine, RiskContext

risk_engine = create_default_risk_engine(
    max_daily_loss=0.05,
    max_drawdown=0.15,
    max_position_pct=0.30,
    max_leverage=10.0,
)

context = RiskContext(total_equity=100000, peak_equity=105000, daily_pnl=-3000)
can_trade, results = risk_engine.should_proceed(context)
```

---

### 通知模块 (`src/ops/notify.py`)

```python
from src.ops.notify import Notifier, NotifyLevel

notifier = Notifier()
notifier.setup_telegram(bot_token="...", chat_id="...")
notifier.setup_webhook(webhook_url="https://api.day.app/your_key")
notifier.setup_multi_bark(["https://api.day.app/device1", "https://api.day.app/device2"])

notifier.notify_system("启动完成")
notifier.notify_risk("仓位超限", level=NotifyLevel.WARNING)
```

---

## 数据采集

### OKX 采集（脚本）

```bash
python scripts/demo_collect.py --symbols BTC/USDT,ETH/USDT --days 90
```

### Binance 历史数据（批量下载）

```bash
python -m scripts.fetch_history --symbols BTCUSDT,ETHUSDT --from 2020-01-01 --tf 1m
```

### Binance 实时同步

```bash
python -m scripts.realtime_sync --symbols BTCUSDT,ETHUSDT --timeframes 1m,1h
```

### A 股数据回填（Tushare）

```bash
# 日线 OHLCV
python scripts/backfill_a_share.py daily --incremental

# 每日基本面
python scripts/backfill_a_share.py daily_basic --incremental

# 复权因子
python scripts/backfill_a_share.py adj_factor --incremental
```

---

## 回测系统

- 回测引擎使用**下一根 bar 的 open** 成交
- 支持滑点/手续费模型
- A 股回测支持 T+1/涨跌停/最小手数规则

---

## 实盘交易

### 启动交易服务

```bash
docker compose --profile trading up -d trader
```

### 交易流程

```
K线数据 → 策略信号 → 风控检查 → 订单生成 → 执行下单 → 成交通知
```

---

## 运维监控

### Grafana

访问 `http://localhost:3000`，可查看 InfluxDB 监控指标。

### Web UI

启动 Web 服务后访问：

```
http://localhost:8080
```

页面包含：
- 数据管理（Binance 历史/实时）
- A 股数据分析
- 回测与优化
- 服务状态监控

---

*文档最后更新: 2026-02-13*
