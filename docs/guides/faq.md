# 常见问题 (FAQ)

## 安装与配置

### Q: pip install 失败，提示某些包无法安装

**A**: 确保使用 Python 3.11+：

```bash
python --version
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Q: Docker Compose 启动失败

**A**: 常见排查：

```bash
# Docker 是否运行
docker ps

# 端口是否被占用
sudo netstat -tulpn | grep :8086
sudo netstat -tulpn | grep :3000

# 查看日志
docker compose logs influxdb
docker compose logs grafana
```

### Q: 提示找不到 .env 文件

**A**: 先创建配置文件：

```bash
cp .env.example .env
```

## 数据相关

### Q: 回测提示 "No data found"

**A**: 需要先采集或下载数据：

```bash
# OKX 历史数据
python scripts/demo_collect.py --symbols BTC/USDT --days 90

# Binance 历史数据
python -m scripts.fetch_history --symbol BTCUSDT --from 2020-01-01 --tf 1m
```

### Q: 数据有缺失怎么办

**A**: 使用工具检查缺口：

```bash
python scripts/test_quality.py --symbol BTC/USDT --timeframe 1h
python -m scripts.data_query --symbol BTCUSDT --gaps
```

## 回测相关

### Q: 回测速度很慢

**A**: 建议：

1. 缩短回测时间范围
2. 使用更大的时间框架
3. 减少策略计算量

### Q: 如何批量回测或对比多个策略

**A**: 使用 `backtest_runner`：

```bash
python -m services.backtest_runner.main --strategy dual_ma --symbol BTC/USDT --days 30
```

### Q: 回测结果与预期不符

**A**: 常见原因：

- 前视偏差（使用了未来数据）
- 数据对齐问题（时间戳不一致）
- 滑点/手续费设置过低

## 策略开发

### Q: 策略不产生信号

**A**: 添加日志检查输入与状态：

```python
from src.ops.logging import get_logger
logger = get_logger(__name__)

def on_bar(self, bar_frame):
    logger.info("processing", symbol=bar_frame.symbol, ts=bar_frame.timestamp)
    logger.info("position", pos=str(self.state.get_position(bar_frame.symbol)))
```

### Q: 如何使用多周期数据

**A**: 在 `StrategyConfig.timeframes` 中指定多个周期，并在 `on_bar` 中判断：

```python
if bar_frame.timeframe == "1h":
    ...
```
