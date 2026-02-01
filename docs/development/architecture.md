# 架构设计文档

## 系统概述

AlgorithmTrader 是一个为个人量化交易者设计的中低频交易系统，支持加密货币、美股、A股等多市场交易。系统采用模块化设计，研究、回测、实盘共享同一套核心代码，确保研究结果的可复现性。

## 设计原则

### 1. 统一接口

所有策略使用相同的接口：

- **输入**: Bar 数据（OHLCV）
- **输出**: 目标持仓或订单意图
- **状态**: 可序列化的策略状态

这确保了：
- 研究代码可以直接用于回测
- 回测验证的策略可以直接上线
- 便于策略组合和对比

### 2. 数据分层

```
Raw Data (原始数据)
    ↓
Curated Data (清洗后的数据)
    ↓
Features (特征/因子)
    ↓
Signals (交易信号)
    ↓
Execution (订单执行)
```

每层职责清晰，互不干扰。

### 3. 存储分工

| 存储 | 用途 | 特点 |
|------|------|------|
| Parquet | 历史数据、回测 | 列式存储、压缩率高、查询快 |
| InfluxDB | 实时监控、告警 | 时序优化、便于 Grafana 可视化 |

### 4. 松耦合服务

各服务通过数据存储层交互，不直接调用：

```
collector → Parquet/InfluxDB ← trader
                ↓
             Grafana
```

好处：
- 服务可以独立重启
- 便于横向扩展
- 故障隔离

## 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      外部数据源                              │
│    OKX API │ Binance API │ IBKR API │ TradingView          │
└────────────────────────┬────────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  Data Collector     │  数据采集服务
              │  (services/collector)│
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │   Data Storage      │
              │  ┌────────────────┐ │
              │  │  Parquet Store │ │  历史数据
              │  └────────────────┘ │
              │  ┌────────────────┐ │
              │  │   InfluxDB     │ │  实时数据
              │  └────────────────┘ │
              └─────────┬───────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
    ┌─────▼─────┐ ┌────▼────┐ ┌─────▼─────┐
    │ Research  │ │ Backtest│ │Live Trader│
    │(notebooks)│ │ Engine  │ │  Service  │
    └───────────┘ └────┬────┘ └─────┬─────┘
                       │            │
              ┌────────▼────────────▼────┐
              │   Strategy Framework     │
              │   (src/strategy/)        │
              │  ┌──────────────────┐   │
              │  │  Strategy Base   │   │
              │  │  Example Strats  │   │
              │  │  Registry        │   │
              │  └──────────────────┘   │
              └──────────┬───────────────┘
                         │
              ┌──────────▼──────────┐
              │   Execution Layer   │
              │  ┌────────────────┐ │
              │  │ Broker Adapters│ │
              │  │ Order Manager  │ │
              │  │ Risk Engine    │ │
              │  └────────────────┘ │
              └─────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  Monitoring & Ops   │
              │  ┌────────────────┐ │
              │  │   Grafana      │ │
              │  │   Loki         │ │
              │  │   Notifier     │ │
              │  └────────────────┘ │
              └─────────────────────┘
```

### 核心模块

#### 1. Data Layer (`src/data/`)

**职责**: 数据采集、存储、质量控制

**组件**:
- `connectors/`: 交易所连接器（OKX, Binance, IBKR）
- `storage/`: 存储抽象层（Parquet, InfluxDB）
- `quality/`: 数据质量检测（缺失、异常）
- `pipelines/`: ETL 数据管道

**设计**:
```python
class DataConnector(ABC):
    """数据连接器抽象"""
    @abstractmethod
    def fetch_ohlcv(self, symbol, timeframe, start, end):
        pass
    
    @abstractmethod
    def fetch_orderbook(self, symbol, depth):
        pass

class DataStore(ABC):
    """存储抽象"""
    @abstractmethod
    def save_bars(self, bars, symbol, timeframe):
        pass
    
    @abstractmethod
    def load_bars(self, symbol, timeframe, start, end):
        pass
```

#### 2. Strategy Layer (`src/strategy/`)

**职责**: 策略框架、示例策略、策略注册

**核心接口**:
```python
class StrategyBase(ABC):
    """策略基类"""
    
    @abstractmethod
    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理 bar 数据"""
        pass
    
    def on_fill(self, fill_event: FillEvent) -> None:
        """处理成交回报（可选）"""
        pass
```

**特点**:
- 纯函数式：输入 bar，输出信号
- 无副作用：不直接访问数据库或 API
- 可序列化：所有状态可以保存/恢复

#### 3. Backtest Engine (`src/backtest/`)

**职责**: 回测引擎、绩效计算、报告生成

**流程**:
```
1. 加载历史数据
2. 按时间顺序遍历 bar
3. 调用策略 on_bar()
4. Bar 级别撮合
5. 计算滑点和手续费
6. 更新账户状态
7. 计算绩效指标
8. 生成报告
```

**支持特性**:
- 多品种回测
- 多策略组合
- 参数扫描
- Walk-forward 验证

#### 4. Execution Layer (`src/execution/`)

**职责**: 订单执行、交易所适配、滑点模型

**组件**:
- `broker_base.py`: Broker 抽象接口
- `adapters/`: 交易所适配器（OKX, IBKR）
- `order_manager.py`: 订单生命周期管理
- `slippage_fee.py`: 滑点和手续费模型

**设计**:
```python
class BrokerBase(ABC):
    """Broker 抽象"""
    
    @abstractmethod
    def submit_order(self, order: Order) -> str:
        """提交订单"""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        pass
    
    @abstractmethod
    def get_positions(self) -> dict[str, Position]:
        """获取持仓"""
        pass
```

#### 5. Risk Management (`src/risk/`)

**职责**: 风控规则、限额检查

**规则**:
- 单笔最大亏损
- 单日最大亏损
- 最大回撤限制
- 单品种持仓限制
- 杠杆限制

**流程**:
```
信号产生 → 风控检查 → 通过/拒绝 → 订单执行
```

#### 6. Operations (`src/ops/`)

**职责**: 运维工具、日志、通知、健康检查

**组件**:
- `logging.py`: 统一日志配置
- `notify.py`: 多渠道通知（Telegram, Bark, Webhook）
- `healthcheck.py`: 服务健康检查
- `scheduler.py`: 任务调度

## 服务架构

### Docker Compose 部署

```yaml
services:
  # 基础设施
  influxdb:      # 时序数据库
  grafana:       # 监控面板
  loki:          # 日志聚合
  promtail:      # 日志采集
  
  # 业务服务
  collector:     # 数据采集
  trader:        # 实盘交易
  scheduler:     # 任务调度
  backtest:      # 批量回测
  notifier:      # 消息通知
  web:           # Web 管理界面
```

### 服务通信

```
collector → Parquet/InfluxDB
               ↓
trader ← Parquet/InfluxDB → Grafana
               ↓
          notifier → Telegram/Bark
```

服务间不直接通信，通过数据层解耦。

## 数据流

### 数据采集流程

```
1. Scheduler 触发采集任务
2. Collector 调用交易所 API
3. 获取 OHLCV 数据
4. 数据质量检查
5. 保存到 Parquet（历史归档）
6. 保存到 InfluxDB（实时监控）
7. 更新采集元数据
```

### 回测流程

```
1. 加载配置（策略、时间范围、资金）
2. 从 Parquet 读取历史数据
3. 初始化策略和引擎
4. 逐 bar 回测:
   - 调用策略 on_bar()
   - 生成订单
   - Bar 级别撮合
   - 计算滑点/手续费
   - 更新持仓和资金
5. 计算绩效指标
6. 生成报告
7. 保存结果到 InfluxDB
8. 发送通知
```

### 实盘交易流程

```
1. Trader 服务启动
2. 加载策略配置
3. 连接交易所
4. 同步持仓和资金
5. 实时获取 bar:
   - WebSocket 订阅
   - 或定时轮询
6. 调用策略 on_bar()
7. 风控检查
8. 提交订单
9. 监听成交
10. 更新持仓
11. 记录到 InfluxDB
12. 发送通知
```

## 扩展性设计

### 添加新交易所

1. 实现 `DataConnector` 接口
2. 实现 `BrokerAdapter` 接口
3. 添加配置文件
4. 注册到工厂

```python
# src/data/connectors/new_exchange.py
class NewExchangeConnector(DataConnector):
    def fetch_ohlcv(self, ...):
        # 实现逻辑
        pass

# src/execution/adapters/new_exchange.py
class NewExchangeBroker(BrokerBase):
    def submit_order(self, ...):
        # 实现逻辑
        pass
```

### 添加新策略

1. 继承 `StrategyBase`
2. 实现 `on_bar()` 方法
3. 注册到策略注册中心

```python
from src.strategy.base import StrategyBase

class MyStrategy(StrategyBase):
    def on_bar(self, bar_frame):
        # 策略逻辑
        return signal
```

### 添加新因子

1. 在 `src/features/factor_library/` 添加因子
2. 实现计算逻辑
3. 在策略中使用

```python
# src/features/factor_library/my_factor.py
def calculate_my_factor(prices, volume):
    # 计算逻辑
    return factor_value
```

## 性能优化

### 数据层优化

- Parquet 使用列式存储和压缩
- InfluxDB 使用合适的保留策略
- 数据预加载和缓存

### 回测优化

- 向量化计算（NumPy）
- 多进程并行回测
- 增量回测（只计算新数据）

### 实盘优化

- WebSocket 减少延迟
- 订单池批量处理
- 异步 I/O

## 安全性设计

### API 密钥管理

- 环境变量存储
- 不提交到 Git
- 支持只读密钥

### 风控保护

- 多层风控检查
- 紧急熔断机制
- 异常自动停止

### 数据备份

- 定时备份 Parquet
- InfluxDB 快照
- 配置文件备份

## 监控体系

### 系统监控

- CPU/内存/磁盘使用率
- 网络延迟
- 服务健康状态

### 业务监控

- 数据采集成功率
- 策略信号频率
- 订单成交率
- 滑点和手续费
- 盈亏曲线

### 告警机制

- Grafana 告警规则
- Telegram 即时通知
- 邮件报告（可选）

## 未来规划

### Phase 3: 实盘交易
- OKX 现货交易
- 订单管理完善
- 实盘风控验证

### Phase 4: 高级功能
- OKX 永续合约
- Walk-forward 优化
- Qlib 框架集成

### Phase 5: 多市场
- IBKR 接口（美股）
- A股数据对接
- 期权策略支持

### Phase 6: 性能优化
- C++ 核心模块
- 低延迟执行
- 分布式回测

## 参考资料

- [CCXT 文档](https://docs.ccxt.com/)
- [InfluxDB 最佳实践](https://docs.influxdata.com/influxdb/v2.7/write-data/best-practices/)
- [Grafana 可视化](https://grafana.com/docs/)
- [Docker Compose 部署](https://docs.docker.com/compose/)

---

**文档版本**: v1.0
**最后更新**: 2026-02-01
