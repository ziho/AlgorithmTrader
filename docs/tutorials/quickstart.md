# 快速开始教程

本教程将在 10 分钟内完成一次数据采集与回测。

## 环境准备

- Python 3.11+
- Docker & Docker Compose

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

## 启动基础设施

```bash
docker compose up -d influxdb grafana
```

## 采集数据（OKX）

```bash
python scripts/demo_collect.py --symbols BTC/USDT --days 90
```

## 运行第一个回测

创建 `my_first_backtest.py`：

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
    initial_capital=Decimal("10000"),
    exchange="okx",
)

engine = BacktestEngine(config)
result = engine.run(
    strategy=strategy,
    symbols=[Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT")],
    timeframe=Timeframe("15m"),
)

print("Total Return:", result.summary.total_return)
print("Sharpe:", result.summary.sharpe_ratio)
```

运行：

```bash
python my_first_backtest.py
```

## 查看回测报告

```bash
python scripts/demo_backtest.py
```

输出目录：

```
reports/<run_id>/
```

包含 `summary.json`、`equity_curve.parquet`、`trades.parquet` 以及示例 `report.html`/`report.md`。
