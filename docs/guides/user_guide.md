# AlgorithmTrader 使用指南

> 个人中低频量化交易系统 - v0.1.0

## 📋 目录

- [项目概述](#项目概述)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [核心模块详解](#核心模块详解)
- [策略开发](#策略开发)
- [数据采集](#数据采集)
- [回测系统](#回测系统)
- [实盘交易](#实盘交易)
- [运维监控](#运维监控)
- [常见问题](#常见问题)

---

## 项目概述

AlgorithmTrader 是一个面向个人的中低频量化交易系统，支持：

| 特性 | 说明 |
|------|------|
| **交易频率** | 15分钟 ~ 1小时级别 |
| **资产类型** | 加密货币现货/永续合约、美股 (规划中) |
| **支持交易所** | OKX (已实现)、IBKR (规划中) |
| **策略类型** | 趋势跟踪、均值回归、多因子 |

### 技术栈

- **语言**: Python 3.11+
- **数据存储**: InfluxDB (实时监控) + Parquet (历史数据)
- **部署**: Docker Compose
- **监控**: Grafana
- **通知**: Telegram / Bark / Webhook

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        AlgorithmTrader                          │
├─────────────────────────────────────────────────────────────────┤
│  services/          (进程入口)                                   │
│  ├── collector      数据采集服务 - 定时拉取 K线/资金费率          │
│  ├── trader         实盘交易服务 - 策略信号 → 订单执行            │
│  ├── scheduler      调度服务 - 统一任务调度                      │
│  ├── backtest_runner 批量回测服务                                │
│  └── notifier       通知服务 - 消息推送                          │
├─────────────────────────────────────────────────────────────────┤
│  src/               (核心库)                                     │
│  ├── core/          基础组件 (时钟、事件、配置)                   │
│  ├── data/          数据层 (连接器、存储、质量检测)               │
│  ├── strategy/      策略层 (基类、注册中心、示例策略)             │
│  ├── backtest/      回测引擎 (模拟撮合、绩效计算、报告生成)       │
│  ├── execution/     执行层 (Broker抽象、订单管理、滑点模型)       │
│  ├── portfolio/     组合管理 (头寸、分配、核算)                   │
│  ├── risk/          风控引擎 (规则、检查、限制)                   │
│  └── ops/           运维支持 (调度、健康检查、通知、日志)         │
├─────────────────────────────────────────────────────────────────┤
│  infra/             (基础设施)                                   │
│  ├── influxdb       时序数据库配置                               │
│  ├── grafana        监控面板配置                                 │
│  └── loki           日志聚合配置                                 │
└─────────────────────────────────────────────────────────────────┘
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
# 复制配置模板
cp .env.example .env

# 编辑配置文件
vim .env
```

关键配置项：

```dotenv
# 环境
ENV=dev

# OKX 交易所 (获取公开数据无需 API Key)
OKX_API_KEY=your_api_key
OKX_API_SECRET=your_api_secret
OKX_PASSPHRASE=your_passphrase
OKX_SANDBOX=true  # 使用模拟盘

# InfluxDB
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=algorithmtrader-dev-token
INFLUXDB_ORG=algorithmtrader
INFLUXDB_BUCKET=trading

# 通知 (可选)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
WEBHOOK_URL=https://api.day.app/your_device_key  # Bark 推送
```

### 3. 启动基础设施

```bash
# 启动 InfluxDB + Grafana
docker compose up -d

# 查看状态
docker compose ps

# 访问 Grafana: http://localhost:3000
# 用户名/密码: admin / algorithmtrader123
```

### 4. 运行测试

```bash
# 运行所有单元测试
docker compose --profile dev run --rm app pytest tests/unit/ -v

# 或本地运行
pytest tests/unit/ -v
```

### 5. 数据采集演示

```bash
# 采集 7 天 BTC/ETH 15分钟 K线数据
python scripts/demo_collect.py

# 自定义参数
python scripts/demo_collect.py --days 14 --symbols BTC/USDT,ETH/USDT,SOL/USDT
```

### 6. 回测演示

```bash
# 使用双均线策略回测
python scripts/demo_backtest.py

# 自定义参数
python scripts/demo_backtest.py --strategy dual_ma --fast 5 --slow 20 --days 30

# 使用通道突破策略
python scripts/demo_backtest.py --strategy donchian --entry-period 20 --exit-period 10
```

回测完成后会生成：
- `reports/backtest_report_YYYYMMDD_HHMMSS.html` - HTML 可视化报告
- `reports/backtest_report_YYYYMMDD_HHMMSS.md` - Markdown 报告

---

## 核心模块详解

### 数据层 (`src/data/`)

#### OKX 数据连接器

```python
from src.data.connectors.okx import OKXConnector

async with OKXConnector() as connector:
    # 获取 K 线数据
    df = await connector.fetch_ohlcv(
        symbol="BTC/USDT",
        timeframe="15m",
        limit=100
    )
    
    # 获取当前资金费率 (永续合约)
    rate = await connector.fetch_funding_rate("BTC/USDT:USDT")
    
    # 获取资金费率历史
    history = await connector.fetch_funding_rate_history(
        symbol="BTC/USDT:USDT",
        limit=100
    )
```

#### 数据存储

```python
# Parquet 存储 (历史数据)
from src.data.storage.parquet_store import ParquetStore

store = ParquetStore(base_path="./data/parquet")
store.write(df, exchange="okx", symbol="BTC/USDT", timeframe="15m")
df = store.read(exchange="okx", symbol="BTC/USDT", timeframe="15m")

# InfluxDB 存储 (实时监控)
from src.data.storage.influx_store import InfluxStore

influx = InfluxStore()
await influx.write_ohlcv(df, symbol="BTC/USDT", timeframe="15m")
await influx.write_funding_rate(symbol="BTC/USDT:USDT", rate=0.0001, timestamp=now)
```

### 策略层 (`src/strategy/`)

#### 策略基类

所有策略继承自 `StrategyBase`：

```python
from src.strategy.base import StrategyBase, StrategyConfig
from src.core.typing import BarFrame, StrategyOutput

class MyStrategy(StrategyBase):
    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)
        self.period = self.get_param("period", 20)
    
    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """每根 K 线调用一次"""
        symbol = bar_frame.symbol
        close = float(bar_frame.current_bar["close"])
        
        # 返回目标仓位
        if self.should_buy():
            return self.target_long(symbol, quantity=1.0, reason="买入信号")
        elif self.should_sell():
            return self.target_flat(symbol, reason="卖出信号")
        
        return None  # 保持现有仓位
```

#### 内置策略

| 策略 | 类名 | 说明 |
|------|------|------|
| 双均线交叉 | `DualMAStrategy` | 快线上穿慢线做多，下穿平仓 |
| 通道突破 | `DonchianBreakoutStrategy` | 突破 N 日高点做多，跌破 N 日低点平仓 |
| 布林带 | `BollingerBandsStrategy` | 触及下轨做多，触及上轨平仓 |
| RSI 均值回归 | `RSIMeanReversionStrategy` | 超卖做多，超买平仓 |
| Z-Score | `ZScoreStrategy` | 基于标准化价格偏离度交易 |

使用示例：

```python
from src.strategy.examples.trend_following import DualMAStrategy
from src.strategy.base import StrategyConfig

strategy = DualMAStrategy(
    config=StrategyConfig(
        name="btc_dual_ma",
        symbols=["BTC/USDT"],
        params={
            "fast_period": 10,
            "slow_period": 30,
            "position_size": 0.1,
            "allow_short": False
        }
    )
)
```

### 回测引擎 (`src/backtest/`)

```python
from decimal import Decimal
from src.backtest.engine import BacktestEngine, BacktestConfig

# 配置回测
config = BacktestConfig(
    initial_capital=Decimal("100000"),
    commission_rate=Decimal("0.001"),  # 0.1% 手续费
    slippage_rate=Decimal("0.0005"),   # 0.05% 滑点
)

# 创建引擎
engine = BacktestEngine(config=config)

# 运行回测
result = engine.run(
    strategy=strategy,
    data={"BTC/USDT": df},  # DataFrame with OHLCV
)

# 查看结果
print(f"总收益: {result.summary.total_return:.2%}")
print(f"夏普比率: {result.summary.sharpe_ratio:.2f}")
print(f"最大回撤: {result.summary.max_drawdown:.2%}")
print(f"胜率: {result.summary.win_rate:.2%}")
```

### 执行层 (`src/execution/`)

#### OKX 现货

```python
from src.execution.adapters.okx_spot import OKXSpotBroker

broker = OKXSpotBroker(
    api_key="...",
    api_secret="...",
    passphrase="...",
    sandbox=True  # 模拟盘
)

await broker.connect()

# 下单
result = await broker.place_order(order)

# 查询余额
result = await broker.get_balance()

await broker.disconnect()
```

#### OKX 永续合约

```python
from src.execution.adapters.okx_swap import OKXSwapBroker, MarginMode, PositionSide

broker = OKXSwapBroker(
    api_key="...",
    api_secret="...",
    passphrase="...",
    sandbox=True,
    default_leverage=10
)

await broker.connect()

# 设置杠杆
await broker.set_leverage("BTC/USDT:USDT", 20)

# 设置保证金模式
await broker.set_margin_mode("BTC/USDT:USDT", MarginMode.ISOLATED)

# 开多
result = await broker.open_long("BTC/USDT:USDT", quantity=0.01)

# 平多
result = await broker.close_long("BTC/USDT:USDT", quantity=0.01)

# 计算预估强平价
liq_price = broker.calculate_liquidation_price(
    symbol="BTC/USDT:USDT",
    side=PositionSide.LONG,
    entry_price=Decimal("50000"),
    quantity=Decimal("0.1"),
    leverage=20
)

await broker.disconnect()
```

### 风控引擎 (`src/risk/`)

```python
from src.risk.engine import RiskEngine, RiskContext, create_default_risk_engine

# 创建默认风控引擎
risk_engine = create_default_risk_engine(
    max_daily_loss=0.05,      # 单日最大亏损 5%
    max_drawdown=0.15,        # 最大回撤 15%
    max_position_pct=0.30,    # 单仓最大占比 30%
    max_leverage=10.0         # 最大杠杆 10x
)

# 检查是否可以交易
context = RiskContext(
    current_equity=100000,
    peak_equity=105000,
    daily_pnl=-3000,
    positions=[...],
)

can_trade, results = risk_engine.should_proceed(context)
if not can_trade:
    print("风控拒绝:", results)
```

### 通知模块 (`src/ops/notify.py`)

```python
from src.ops.notify import Notifier, NotifyLevel

# 创建通知器
notifier = Notifier(name="trader")

# 设置 Telegram
notifier.setup_telegram(bot_token="...", chat_id="...")

# 设置 Webhook (Bark / 通用)
notifier.setup_webhook(webhook_url="https://api.day.app/your_key")

# 发送通知
await notifier.notify_order(order)
await notifier.notify_fill(fill)
await notifier.notify_risk("仓位超限", level=NotifyLevel.WARNING)
await notifier.notify_error(exception)
await notifier.notify_daily_summary(pnl=1000, trades=5, win_rate=0.6)
```

---

## 策略开发

### 创建新策略

1. 在 `src/strategy/examples/` 下创建文件：

```python
# src/strategy/examples/my_strategy.py
from decimal import Decimal
from src.strategy.base import StrategyBase, StrategyConfig
from src.core.typing import BarFrame, StrategyOutput

class MyAwesomeStrategy(StrategyBase):
    """我的策略"""
    
    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)
        # 从配置获取参数
        self.lookback = self.get_param("lookback", 20)
        self.threshold = self.get_param("threshold", 0.02)
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))
    
    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        # 检查历史数据
        if bar_frame.history is None or len(bar_frame.history) < self.lookback:
            return None
        
        symbol = bar_frame.symbol
        close = float(bar_frame.current_bar["close"])
        history = bar_frame.history["close"].values
        
        # 你的交易逻辑
        mean_price = history[-self.lookback:].mean()
        deviation = (close - mean_price) / mean_price
        
        current_position = self.get_position(symbol)
        
        if deviation < -self.threshold and current_position == 0:
            return self.target_long(
                symbol=symbol,
                quantity=self.position_size,
                reason=f"价格偏离均值 {deviation:.2%}"
            )
        elif deviation > 0 and current_position > 0:
            return self.target_flat(
                symbol=symbol,
                reason=f"价格回归均值"
            )
        
        return None
```

2. 注册策略（可选）：

```python
from src.strategy.registry import StrategyRegistry

StrategyRegistry.register("my_awesome", MyAwesomeStrategy)
```

3. 回测验证：

```python
strategy = MyAwesomeStrategy(
    config=StrategyConfig(
        name="test",
        symbols=["BTC/USDT"],
        params={"lookback": 20, "threshold": 0.02}
    )
)

result = engine.run(strategy=strategy, data={"BTC/USDT": df})
```

### 策略最佳实践

1. **参数化**: 所有可调参数通过 `get_param()` 获取
2. **状态管理**: 使用 `self.state` 保存策略状态
3. **日志记录**: 使用 `self.logger` 记录关键信息
4. **异常处理**: 在 `on_bar()` 中妥善处理异常
5. **单元测试**: 为策略编写测试用例

---

## 数据采集

### 使用 DataCollector 服务

```python
from services.collector.main import DataCollector

collector = DataCollector()

# 采集 K 线数据
await collector.collect_ohlcv(
    symbol="BTC/USDT",
    timeframe="15m",
    days=7
)

# 采集资金费率
await collector.collect_funding_rate("BTC/USDT:USDT")

# 回填历史资金费率
await collector.backfill_funding_rates(
    symbol="BTC/USDT:USDT",
    days=30
)

# 启动定时采集
await collector.start()  # 自动调度采集任务
```

### 定时任务配置

DataCollector 默认调度：
- **K 线数据**: 每 15 分钟采集一次
- **资金费率**: 每 8 小时采集一次 (0:01, 8:01, 16:01 UTC)

---

## 回测系统

### 生成报告

```python
from src.backtest.reports import ReportGenerator, ReportConfig

generator = ReportGenerator(ReportConfig(
    output_dir="./reports",
    include_trades=True,
    write_to_influx=True
))

# 生成所有格式报告
report = generator.generate_report(result)

# 单独生成
from src.backtest.reports import generate_text_report, generate_markdown_report
text = generate_text_report(result.summary)
markdown = generate_markdown_report(result.summary)
```

### 绩效指标

| 指标 | 说明 |
|------|------|
| `total_return` | 总收益率 |
| `annualized_return` | 年化收益率 |
| `volatility` | 年化波动率 |
| `sharpe_ratio` | 夏普比率 |
| `sortino_ratio` | 索提诺比率 |
| `calmar_ratio` | 卡尔马比率 |
| `max_drawdown` | 最大回撤 |
| `win_rate` | 胜率 |
| `profit_factor` | 盈亏比 |
| `avg_trade_return` | 平均交易收益 |
| `total_trades` | 总交易次数 |

---

## 实盘交易

### 启动交易服务

```bash
# 使用 Docker
docker compose --profile trading up -d trader

# 或直接运行
python -m services.trader.main
```

### 交易流程

```
K线数据 → 策略信号 → 风控检查 → 订单生成 → 执行下单 → 成交通知
   ↑                                              ↓
   └──────────────────────────────────────────────┘
                    循环执行
```

---

## 运维监控

### Grafana 面板

访问 `http://localhost:3000`，预置面板包括：

- **Trading Monitor**: 实时交易监控
- **Risk Monitor**: 风险指标监控
- **Data Monitor**: 数据质量监控
- **Backtest Results**: 回测结果对比

### 健康检查

```python
from src.ops.healthcheck import create_default_health_checker

checker = create_default_health_checker()
results = checker.check_all()
status = checker.get_status()  # "healthy" | "degraded" | "unhealthy"
```

### 日志

```python
from src.ops.logging import get_logger

logger = get_logger(__name__)
logger.info("订单已提交", order_id="12345", symbol="BTC/USDT")
```

日志输出到 `logs/` 目录，可通过 Loki + Grafana 查看。

---

## 常见问题

### Q: 如何获取 OKX API Key?

1. 登录 OKX 官网
2. 进入 API 管理页面
3. 创建 API Key，勾选"交易"权限
4. 保存 API Key、Secret 和 Passphrase

### Q: 模拟盘和实盘如何切换?

修改 `.env` 文件：
```dotenv
OKX_SANDBOX=true   # 模拟盘
OKX_SANDBOX=false  # 实盘 (谨慎!)
```

### Q: 如何添加新的交易所?

1. 在 `src/data/connectors/` 创建连接器
2. 在 `src/execution/adapters/` 创建 Broker 适配器
3. 实现 `BrokerBase` 接口

### Q: 回测和实盘结果差异大?

可能原因：
- 滑点设置过低
- 未考虑交易所限制 (最小下单量等)
- 流动性影响
- 资金费率影响 (永续合约)

### Q: 如何调试策略?

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 或使用 structlog
from src.ops.logging import configure_logging
configure_logging(level="DEBUG")
```

---

## 版本历史

### v0.1.0 (2026-02-01)

- ✅ 核心框架搭建
- ✅ OKX 现货/永续适配器
- ✅ 回测引擎 + HTML 报告
- ✅ 5 种内置策略
- ✅ 风控引擎
- ✅ Telegram / Bark / Webhook 通知
- ✅ 资金费率采集
- ✅ Docker Compose 部署

### 规划中

- 🔲 IBKR 美股适配器
- 🔲 多因子策略支持
- 🔲 Qlib 集成
- 🔲 Web 管理界面
- 🔲 策略参数优化

---

## 联系方式

- GitHub: https://github.com/ziho/AlgorithmTrader
- Issues: https://github.com/ziho/AlgorithmTrader/issues

---

*文档最后更新: 2026-02-01*
