# 快速开始教程

本教程将带你在 10 分钟内运行第一个回测。

## 环境准备

### 1. 系统要求

- Ubuntu 20.04+ / macOS 12+ / Windows 10+ (WSL2)
- Python 3.11 或更高版本
- Docker & Docker Compose
- 8GB+ 内存（推荐 16GB+）

### 2. 安装 Python 依赖

```bash
# 克隆项目
git clone https://github.com/ziho/AlgorithmTrader.git
cd AlgorithmTrader

# 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装项目（开发模式）
pip install -e ".[dev]"
```

### 3. 启动基础设施

```bash
# 启动 InfluxDB 和 Grafana
docker-compose up -d influxdb grafana

# 检查服务状态
docker-compose ps
```

## 采集数据

### 方式一：使用演示脚本（推荐）

```bash
# 采集 BTC/USDT 最近 90 天的数据
python scripts/demo_collect.py --symbol BTC/USDT --days 90

# 采集多个品种
python scripts/demo_collect.py --symbol BTC/USDT ETH/USDT --days 90
```

### 方式二：编程方式

创建 `collect_data.py`:

```python
from datetime import datetime, timedelta
from src.data.connectors.okx_connector import OKXConnector
from src.data.storage.parquet_store import ParquetStore

# 初始化连接器
connector = OKXConnector()
store = ParquetStore(base_path="data/parquet/okx")

# 设置时间范围
end_date = datetime.now()
start_date = end_date - timedelta(days=90)

# 采集数据
bars = connector.fetch_ohlcv(
    symbol="BTC/USDT",
    timeframe="1h",
    start_time=start_date,
    end_time=end_date
)

# 保存到 Parquet
store.save_bars(bars, symbol="BTC/USDT", timeframe="1h")
print(f"采集完成: {len(bars)} 条数据")
```

运行：

```bash
python collect_data.py
```

## 运行第一个回测

### 使用内置策略

创建 `my_first_backtest.py`:

```python
from datetime import datetime
from decimal import Decimal

from src.backtest.engine import BacktestEngine
from src.strategy.base import StrategyConfig
from src.strategy.examples import DualMAStrategy

# 1. 配置策略
config = StrategyConfig(
    name="btc_dual_ma",
    symbols=["BTC/USDT"],
    timeframes=["1h"],
    params={
        "fast_period": 10,
        "slow_period": 30,
        "position_size": 1.0,
        "allow_short": False,
    }
)

# 2. 创建策略实例
strategy = DualMAStrategy(config)

# 3. 创建回测引擎
engine = BacktestEngine(
    strategies=[strategy],
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31),
    initial_capital=Decimal("10000"),
    data_source="parquet",  # 从 Parquet 读取数据
)

# 4. 运行回测
print("开始回测...")
result = engine.run()

# 5. 查看结果
print("\n=== 回测结果 ===")
print(result.summary())

# 6. 保存报告（可选）
result.save_report("backtest_reports/my_first_backtest.json")
```

运行回测：

```bash
python my_first_backtest.py
```

### 预期输出

```
开始回测...
Processing BTC/USDT 1h bars...
回测完成: 8760 bars processed

=== 回测结果 ===
策略: btc_dual_ma
时间: 2024-01-01 to 2024-12-31
初始资金: $10,000.00
最终资金: $11,234.56
总收益: +12.35%
夏普比率: 1.23
最大回撤: -8.45%
胜率: 55.2%
总交易次数: 42
```

## 在 Grafana 中查看结果

### 1. 访问 Grafana

打开浏览器访问: http://localhost:3000

- 用户名: `admin`
- 密码: `algorithmtrader123`

### 2. 导入面板

1. 点击左侧 **Dashboards** → **Import**
2. 上传 `infra/grafana/dashboards/backtest.json`
3. 选择 InfluxDB 数据源
4. 点击 **Import**

### 3. 查看回测曲线

- **权益曲线**: 资金随时间的变化
- **回撤曲线**: 最大回撤分析
- **交易记录**: 每笔交易的详情
- **持仓分布**: 持仓时间分布

## 尝试不同的策略

### RSI 均值回归策略

```python
from src.strategy.examples import RSIMeanReversionStrategy

config = StrategyConfig(
    name="btc_rsi",
    symbols=["BTC/USDT"],
    params={
        "period": 14,
        "oversold": 30,
        "overbought": 70,
        "position_size": 1.0,
    }
)

strategy = RSIMeanReversionStrategy(config)
```

### 布林带策略

```python
from src.strategy.examples import BollingerBandsStrategy

config = StrategyConfig(
    name="btc_bb",
    symbols=["BTC/USDT"],
    params={
        "period": 20,
        "std_dev": 2.0,
        "position_size": 1.0,
    }
)

strategy = BollingerBandsStrategy(config)
```

## 调整参数

修改策略参数观察效果：

```python
# 修改均线周期
params={
    "fast_period": 5,   # 更快响应
    "slow_period": 20,  # 更快响应
}

# 修改 RSI 阈值
params={
    "oversold": 25,     # 更严格的超卖条件
    "overbought": 75,   # 更严格的超买条件
}

# 修改仓位大小
params={
    "position_size": 0.5,  # 使用一半仓位
}
```

## 常见问题

### Q: 提示找不到数据

A: 确保先运行数据采集：

```bash
python scripts/demo_collect.py --symbol BTC/USDT --days 90
```

检查数据文件是否存在：

```bash
ls -lh data/parquet/okx/BTC_USDT/
```

### Q: InfluxDB 连接失败

A: 检查 Docker 容器状态：

```bash
docker-compose ps
docker-compose logs influxdb
```

重启服务：

```bash
docker-compose restart influxdb
```

### Q: 回测速度很慢

A: 几个优化建议：

1. 减少回测时间范围
2. 使用更大的时间周期（1h 而非 15m）
3. 减少交易品种数量

### Q: 想修改初始资金

A: 在 BacktestEngine 中设置：

```python
engine = BacktestEngine(
    strategies=[strategy],
    initial_capital=Decimal("50000"),  # $50,000
    ...
)
```

## 下一步

现在你已经运行了第一个回测，接下来可以：

1. **编写自己的策略**: 阅读 [策略开发指南](../guides/strategy_development.md)
2. **优化参数**: 学习 [参数优化教程](parameter_optimization.md)
3. **部署实盘**: 了解 [实盘交易指南](../guides/live_trading.md)
4. **监控系统**: 设置 [Grafana 监控](../guides/monitoring.md)

## 需要帮助？

- 查看 [用户指南](../guides/user_guide.md) 了解更多功能
- 遇到问题？提交 [GitHub Issue](https://github.com/ziho/AlgorithmTrader/issues)
- 查看 [FAQ](../guides/faq.md) 常见问题解答
