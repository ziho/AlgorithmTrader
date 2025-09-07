# Phase 3: 数据可视化

**预计时间**: 1-2天  
**前置条件**: Phase 2 完成，InfluxDB 包含历史数据  
**目标**: 创建 Grafana 仪表盘展示加密货币市场数据

## 步骤清单

### 3.1 配置 InfluxDB 数据源

#### 在 Grafana 中添加数据源
1. 访问 Grafana: http://localhost:3000
2. 登录后进入 Configuration -> Data Sources
3. 添加 InfluxDB 数据源，配置如下：
   - URL: `http://influxdb:8086`
   - Organization: `quant`
   - Token: (从 .env 文件中的 INFLUXDB_ADMIN_TOKEN)
   - Default Bucket: `marketdata`

#### 测试连接
```flux
// 测试查询
from(bucket: "marketdata")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == "BTCUSDT")
  |> limit(n: 10)
```

### 3.2 创建加密货币概览仪表盘

#### 面板 1: BTC 价格走势图
- **查询**:
```flux
from(bucket: "marketdata")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == "BTCUSDT")
  |> filter(fn: (r) => r._field == "close")
  |> aggregateWindow(every: v.windowPeriod, fn: last)
```
- **可视化类型**: Time series
- **设置**: Y轴单位为美元，显示价格范围

#### 面板 2: ETH 价格走势图  
- 类似 BTC，修改 symbol 为 "ETHUSDT"

#### 面板 3: 成交量图表
```flux
from(bucket: "marketdata")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)  
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == "BTCUSDT")
  |> filter(fn: (r) => r._field == "volume")
  |> aggregateWindow(every: v.windowPeriod, fn: sum)
```

#### 面板 4: 24小时涨跌幅
```flux
current = from(bucket: "marketdata")
  |> range(start: -1m)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == "BTCUSDT")
  |> filter(fn: (r) => r._field == "close")
  |> last()

yesterday = from(bucket: "marketdata")
  |> range(start: -24h, stop: -24h+1m)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == "BTCUSDT")
  |> filter(fn: (r) => r._field == "close")
  |> last()

// 计算涨跌幅百分比
```

### 3.3 创建技术指标面板

#### 面板 5: 移动平均线
```flux
// MA5
from(bucket: "marketdata")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == "BTCUSDT")
  |> filter(fn: (r) => r._field == "close")
  |> aggregateWindow(every: 5m, fn: mean)

// MA20  
from(bucket: "marketdata")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == "BTCUSDT")
  |> filter(fn: (r) => r._field == "close")
  |> aggregateWindow(every: 20m, fn: mean)
```

#### 面板 6: OHLC 蜡烛图
- 使用 Candlestick 可视化类型
- 需要 open, high, low, close 四个字段

### 3.4 仪表盘配置

#### 变量设置
1. 创建 Symbol 变量:
   - Name: `symbol`
   - Type: Query
   - Query: 
   ```flux
   import "influxdata/influxdb/schema"
   schema.tagValues(bucket: "marketdata", tag: "symbol")
   ```

2. 创建时间窗口变量:
   - Name: `interval`
   - Type: Interval
   - Values: `1m,5m,15m,1h,4h,1d`

#### 面板布局
```
+------------------+------------------+
|   BTC Price      |   ETH Price      |
|                  |                  |
+------------------+------------------+
|   Volume Chart                      |
|                                     |
+-------------------------------------+
|   24h Change     |   MA Lines       |
|                  |                  |
+------------------+------------------+
```

### 3.5 导出仪表盘配置

```bash
# 创建 Grafana 仪表盘目录
mkdir -p config/grafana/dashboards

# 在 Grafana UI 中导出仪表盘 JSON
# Settings -> JSON Model -> Copy to clipboard
# 保存为 config/grafana/dashboards/crypto_overview.json
```

### 3.6 自动化仪表盘部署

**config/grafana/provisioning/dashboards/dashboards.yml**
```yaml
apiVersion: 1

providers:
  - name: 'default'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
```

### 3.7 设置数据刷新

#### 自动刷新配置
- 设置仪表盘刷新间隔: 30秒
- 缓存配置: 启用查询缓存，缓存时间 5分钟
- 时间范围默认值: 最近24小时

#### 性能优化
```flux
// 使用采样减少数据点
from(bucket: "marketdata")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == v.symbol)
  |> filter(fn: (r) => r._field == "close")
  |> aggregateWindow(every: v.windowPeriod, fn: last)
  |> yield(name: "mean")
```

## 验收标准

### 基础功能
- [ ] Grafana 可以成功连接到 InfluxDB
- [ ] BTC/ETH 价格图表正确显示
- [ ] 成交量图表数据准确
- [ ] 时间范围选择器工作正常

### 交互功能
- [ ] 变量选择器可以切换交易对
- [ ] 时间间隔可以动态调整
- [ ] 缩放和平移功能正常
- [ ] 数据自动刷新

### 视觉效果
- [ ] 图表颜色主题一致
- [ ] 坐标轴标签清晰
- [ ] 图例显示正确
- [ ] 响应式布局适配

### 性能指标
- [ ] 页面加载时间 < 3秒
- [ ] 查询响应时间 < 2秒
- [ ] 刷新无明显卡顿
- [ ] 内存使用稳定

## 故障排除

### 连接问题
```bash
# 检查 Grafana 到 InfluxDB 的网络连通性
docker exec algorithmtrader-grafana curl -f http://influxdb:8086/health

# 验证 InfluxDB token 权限
docker exec algorithmtrader-influxdb influx auth list
```

### 查询问题
```bash
# 在 InfluxDB 中直接测试查询
docker exec -it algorithmtrader-influxdb influx query '
from(bucket: "marketdata")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> count()
'
```

### 性能问题
```bash
# 检查查询执行时间
# 在 Grafana Query Inspector 中查看查询统计

# 优化建议:
# 1. 使用合适的时间聚合窗口
# 2. 限制返回的数据点数量
# 3. 添加适当的过滤条件
```

### 仪表盘问题
```bash
# 检查仪表盘 JSON 格式
cat config/grafana/dashboards/crypto_overview.json | jq .

# 重新加载仪表盘配置
docker-compose restart grafana
```

## 下一步

完成Phase 3后，继续Phase 4: 策略开发与回测

**检查点**:
- Grafana 仪表盘创建成功
- 所有图表数据显示正确
- 交互功能工作正常
- 性能满足要求

继续阅读: `phase_4_strategy.md`
