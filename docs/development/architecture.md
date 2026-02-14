# 架构设计文档

## 系统概述

AlgorithmTrader 面向个人量化交易者，当前实现覆盖：
- 加密货币数据采集与回测
- OKX 实盘执行
- A 股日线数据与回测规则
- 参数优化与 Walk-Forward 验证
- Web 管理界面与监控

## 设计原则

### 1. 统一策略接口

- **输入**: Bar 数据（OHLCV）
- **输出**: 目标持仓或订单意图
- **状态**: 可序列化策略状态

策略在研究、回测、实盘间复用。

### 2. 数据分层

```
采集 → 存储 → 特征/因子 → 信号 → 执行
```

### 3. 存储分工

| 存储 | 用途 | 特点 |
|------|------|------|
| Parquet | 历史数据、回测 | 列式存储、压缩高、便于 DuckDB 查询 |
| InfluxDB | 实时监控、回测摘要 | 时序优化，Grafana 可视化 |

### 4. 松耦合服务

服务通过存储层协作，减少相互依赖：

```
collector → Parquet / InfluxDB ← trader
                     ↓
                 Grafana
```

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      外部数据源                              │
│     OKX API   Binance Public Data   Tushare A 股             │
└────────────────────────┬────────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  Data Services      │
              │  collector / fetcher│
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │   Data Storage      │
              │  Parquet / InfluxDB │
              └─────────┬───────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
    ┌─────▼─────┐ ┌─────▼────┐ ┌──────▼─────┐
    │ Research  │ │ Backtest │ │ Live Trader│
    │ notebooks │ │ Engine   │ │  Service   │
    └───────────┘ └─────┬────┘ └──────┬─────┘
                        │             │
                ┌───────▼─────────────▼───┐
                │    Strategy Framework  │
                └─────────────┬──────────┘
                              │
                      ┌───────▼────────┐
                      │ Execution/Risk │
                      └────────────────┘
```

## 核心模块

### 1. Data Layer (`src/data/`)

- `connectors/`: OKX、Binance、Tushare（IBKR 占位）
- `fetcher/`: 历史数据下载、实时同步、断点续传
- `storage/`: Parquet / InfluxDB / A 股基本面存储
- `quality/`: 数据质量检测

### 2. Strategy Layer (`src/strategy/`)

- `StrategyBase` 统一策略接口
- 内置示例策略（趋势跟踪 / 均值回归）
- 策略注册与参数空间定义

### 3. Backtest Layer (`src/backtest/`)

- Bar 级回测引擎（下一根 bar open 成交）
- 滑点/手续费模型
- A 股规则 (T+1、涨跌停、最小手数)
- 报告输出（JSON/Parquet）

### 4. Optimization Layer (`src/optimization/`)

- Grid / Random / LHS 搜索
- Walk-Forward 验证

### 5. Execution Layer (`src/execution/`)

- OKX 现货/永续适配器
- 订单管理与重试
- 成本模型

### 6. Ops Layer (`src/ops/`)

- 日志
- 通知（Telegram / Bark / Webhook / SMTP）
- 健康检查

---

如需更细节的执行流程，请参考 `docs/guides/user_guide.md`。
