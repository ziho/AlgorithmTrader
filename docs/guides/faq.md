# 常见问题 (FAQ)

## 安装与配置

### Q: pip install 失败，提示某些包无法安装

**A**: 确保使用 Python 3.11+:

```bash
python --version  # 应该显示 3.11 或更高

# 如果版本不对，使用正确的 Python
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Q: Docker Compose 启动失败

**A**: 检查几个常见问题:

```bash
# 1. 检查 Docker 是否运行
docker ps

# 2. 检查端口占用
sudo netstat -tulpn | grep :8086
sudo netstat -tulpn | grep :3000

# 3. 查看详细日志
docker-compose logs influxdb
docker-compose logs grafana

# 4. 重新构建
docker-compose down
docker-compose up -d --force-recreate
```

### Q: 提示找不到 .env 文件

**A**: 需要先创建配置文件:

```bash
cp .env.example .env
vim .env  # 编辑配置
```

## 数据相关

### Q: 运行回测提示"No data found"

**A**: 需要先采集数据:

```bash
# 采集最近 90 天的数据
python scripts/demo_collect.py --symbol BTC/USDT --days 90

# 检查数据文件
ls -lh data/parquet/okx/BTC_USDT/
```

### Q: 数据采集很慢

**A**: 几个优化方法:

1. 使用更大的时间周期（1h 比 5m 快）
2. 减少采集天数
3. 单个品种分别采集

```bash
# 快速采集（1h 周期，30天）
python scripts/demo_collect.py --symbol BTC/USDT --days 30 --timeframe 1h
```

### Q: 数据有缺失怎么办

**A**: 使用数据质量检查工具:

```bash
python scripts/test_quality.py --symbol BTC/USDT --timeframe 1h
```

重新采集缺失的数据:

```bash
python scripts/demo_collect.py --symbol BTC/USDT --start 2024-01-01 --end 2024-01-31
```

## 回测相关

### Q: 回测速度很慢

**A**: 优化建议:

1. 减少回测时间范围
2. 使用更大的时间周期
3. 减少策略复杂度
4. 关闭详细日志

```python
# 在策略中减少计算
def on_bar(self, bar_frame):
    # 只在需要时计算指标
    if not self.should_calculate():
        return None
```

### Q: 回测结果与预期不符

**A**: 检查几个常见错误:

1. **前视偏差**: 使用了未来数据
```python
# ❌ 错误
high = history["high"].iloc[-1]  # 当前 bar

# ✅ 正确
high = history["high"].iloc[-2]  # 前一根 bar
```

2. **数据对齐问题**: 时间戳不一致
3. **滑点设置**: 实盘滑点可能更大

### Q: 想对比多个策略

**A**: 在回测引擎中传入多个策略:

```python
strategies = [
    DualMAStrategy(config1),
    RSIMeanReversionStrategy(config2),
]

engine = BacktestEngine(
    strategies=strategies,
    ...
)
```

## 策略开发

### Q: 策略不产生任何信号

**A**: 添加调试日志:

```python
from src.ops.logging import get_logger
logger = get_logger(__name__)

def on_bar(self, bar_frame):
    logger.info(f"Processing {bar_frame.symbol} at {bar_frame.timestamp}")
    logger.info(f"Position: {self.state.get_position(bar_frame.symbol)}")
    logger.info(f"Indicator value: {indicator_value}")
    
    # ... 策略逻辑
```

检查条件是否太严格。

### Q: 如何在策略中访问多个时间周期

**A**: 在配置中指定多个周期:

```python
config = StrategyConfig(
    name="multi_tf",
    symbols=["BTC/USDT"],
    timeframes=["15m", "1h"],  # 多周期
)
```

在策略中区分:

```python
def on_bar(self, bar_frame):
    if bar_frame.timeframe == "1h":
        # 处理 1h 数据
        pass
    elif bar_frame.timeframe == "15m":
        # 处理 15m 数据
        pass
```

### Q: 如何实现止损止盈

**A**: 在策略中跟踪入场价格:

```python
def on_bar(self, bar_frame):
    current_price = bar_frame.close
    entry_price = self.get_state("entry_price")
    
    if entry_price:
        pnl_pct = (current_price - entry_price) / entry_price
        
        # 止损
        if pnl_pct < -0.05:
            self.set_state("entry_price", None)
            return self.target_flat(symbol, reason="stop_loss")
        
        # 止盈
        if pnl_pct > 0.10:
            self.set_state("entry_price", None)
            return self.target_flat(symbol, reason="take_profit")
    
    # 入场时记录价格
    if signal_to_enter:
        self.set_state("entry_price", current_price)
        return self.target_long(...)
```

## 实盘交易

### Q: 实盘如何确保安全

**A**: 几个建议:

1. **小仓位测试**: 先用最小仓位运行
2. **设置限额**: 严格的风控参数
3. **监控告警**: 配置 Grafana 告警
4. **手动确认**: 重要操作前确认

### Q: API 密钥安全吗

**A**: 安全措施:

1. 密钥存在 `.env` 中，不提交 Git
2. 使用只读 API（如果只监控）
3. 限制 IP 白名单
4. 定期轮换密钥

### Q: 如何测试实盘代码

**A**: 使用测试网络:

```bash
# .env 中配置测试网
OKX_TESTNET=true
OKX_TESTNET_API_KEY=...
```

或使用模拟盘:

```python
broker = OKXBroker(
    api_key=...,
    paper_trading=True  # 模拟盘
)
```

## 监控与运维

### Q: Grafana 无法连接 InfluxDB

**A**: 检查配置:

1. InfluxDB 是否运行: `docker-compose ps`
2. Token 是否正确: 检查 `.env`
3. 组织和 Bucket 是否存在

重新配置数据源:
1. Grafana → Configuration → Data Sources
2. 添加 InfluxDB
3. 填入 URL: `http://influxdb:8086`
4. 填入 Token、Org、Bucket

### Q: 收不到 Telegram 通知

**A**: 测试配置:

```python
from src.ops.notify import TelegramNotifier

notifier = TelegramNotifier()
notifier.send("测试消息")
```

检查:
- Bot Token 是否正确
- Chat ID 是否正确
- 机器人是否在群组中（如果发送到群组）

### Q: 日志文件太大

**A**: Docker Compose 已配置日志轮转:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "50m"
    max-file: "10"
```

手动清理:

```bash
# 清理 Docker 日志
docker-compose down
sudo find /var/lib/docker/containers -name "*.log" -delete
docker-compose up -d
```

## 性能优化

### Q: 内存占用太高

**A**: 优化方法:

1. 限制历史数据长度
```python
# 只保留必要的历史数据
if len(bar_frame.history) > 100:
    bar_frame.history = bar_frame.history.tail(100)
```

2. 使用生成器而非列表
3. 及时清理不用的数据

### Q: CPU 使用率过高

**A**: 
1. 减少轮询频率
2. 使用 WebSocket 代替轮询
3. 优化计算密集的代码（使用 NumPy）

## 其他问题

### Q: 如何备份数据

**A**: 使用备份脚本:

```bash
# 备份 Parquet 数据
tar -czf backup_$(date +%Y%m%d).tar.gz data/parquet/

# 备份 InfluxDB
docker-compose exec influxdb influx backup /backup/
```

### Q: 如何升级系统

**A**: 安全升级流程:

```bash
# 1. 备份数据
./scripts/backup.sh

# 2. 停止服务
docker-compose down

# 3. 拉取新代码
git pull origin main

# 4. 重新构建
docker-compose build

# 5. 启动服务
docker-compose up -d

# 6. 检查日志
docker-compose logs -f
```

### Q: 遇到其他问题怎么办

**A**: 几个途径:

1. 查看日志: `docker-compose logs <service>`
2. 搜索 GitHub Issues
3. 提交新 Issue: https://github.com/ziho/AlgorithmTrader/issues
4. 查看文档: [用户指南](user_guide.md)

---

**提示**: 如果你的问题在这里没有列出，欢迎提交 Issue 或 PR 补充！
