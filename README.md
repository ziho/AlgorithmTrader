# AlgorithmTrader

[![CI](https://github.com/ziho/AlgorithmTrader/actions/workflows/ci.yml/badge.svg)](https://github.com/ziho/AlgorithmTrader/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

一个现代化的个人量化交易系统，专注于中低频策略研发与自动化执行。

## 特性

- **统一架构**: 研究、回测、实盘使用相同的策略接口，确保研究结果的可复现性
- **灵活数据层**: 历史数据用 Parquet 存储，实时监控用 InfluxDB，兼顾效率与成本
- **内置策略**: 5+ 种经典策略开箱即用（双均线、布林带、RSI、通道突破等）
- **完整工具链**: 数据采集、回测、参数优化、实盘执行、监控告警一站式解决
- **容器化部署**: Docker Compose 一键启动所有服务，集成 Grafana 监控面板
- **扩展友好**: 清晰的模块边界，便于添加新交易所、新策略、新因子

## 支持的市场

| 市场 | 资产类型 | 状态 |
|------|---------|------|
| 加密货币 | 现货 / 永续合约 | ✅ 已实现 |
| 美股 | 正股 / 期权 | 🚧 规划中 |
| A股 | 正股 / 期权 | 🚧 规划中 |

**交易所**: OKX（已实现）、IBKR（规划中）

## 快速开始

### 前置要求

- Python 3.11+
- Docker & Docker Compose
- 64GB+ RAM（推荐）

### 安装

```bash
# 克隆项目
git clone https://github.com/ziho/AlgorithmTrader.git
cd AlgorithmTrader

# 安装依赖
pip install -e ".[dev]"

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API 密钥和配置
```

### 启动基础设施

```bash
# 启动 InfluxDB + Grafana
docker-compose up -d influxdb grafana

# 访问 Grafana: http://localhost:3000
# 默认账号: admin / algorithmtrader123
```

### 数据采集

```bash
# 采集历史数据
python scripts/demo_collect.py --symbol BTC/USDT --days 90

# 启动实时采集服务
docker-compose up -d collector
```

### 运行回测

```bash
# 运行示例回测
python scripts/demo_backtest.py

# 查看回测结果（在 Grafana 中查看图表）
```

## 架构设计

### 核心理念

1. **统一接口**: 策略只关心 `on_bar()` 和 `on_fill()`，研究/回测/实盘无需改代码
2. **数据分层**: 采集 → 清洗 → 特征 → 信号 → 执行，每层职责清晰
3. **存储分工**: 
   - InfluxDB: 实时数据、监控指标、告警
   - Parquet: 历史数据、回测、特征工程
4. **松耦合服务**: 各服务通过数据存储层交互，便于独立扩展

### 项目结构

```
AlgorithmTrader/
├── src/                    # 核心库（研究/回测/实盘共享）
│   ├── core/               # 基础设施（时钟、事件、配置）
│   ├── data/               # 数据层（采集、存储、质量检测）
│   ├── strategy/           # 策略框架与示例策略
│   ├── backtest/           # 回测引擎
│   ├── execution/          # 订单执行与交易所适配
│   ├── portfolio/          # 组合管理与账户核算
│   ├── risk/               # 风控引擎
│   ├── features/           # 因子库与特征工程
│   └── ops/                # 运维工具（日志、通知、健康检查）
│
├── services/               # 微服务（容器化部署）
│   ├── collector/          # 数据采集服务
│   ├── trader/             # 实盘交易服务
│   ├── scheduler/          # 任务调度服务
│   ├── backtest_runner/    # 批量回测服务
│   ├── notifier/           # 消息通知服务
│   └── web/                # Web 管理界面
│
├── infra/                  # 基础设施配置
│   ├── grafana/            # 监控面板
│   ├── influxdb/           # 时序数据库
│   └── loki/               # 日志聚合
│
├── research/               # 研究环境
│   ├── notebooks/          # Jupyter 笔记本
│   └── qlib/               # Qlib 框架集成
│
├── docs/                   # 文档
│   ├── guides/             # 操作指南
│   ├── tutorials/          # 教程
│   └── development/        # 开发文档
│
└── tests/                  # 测试套件
    ├── unit/               # 单元测试
    └── integration/        # 集成测试
```

## 内置策略

| 策略 | 类型 | 说明 |
|------|------|------|
| 双均线交叉 | 趋势跟踪 | 快线上穿慢线做多，死叉平仓 |
| 通道突破 | 趋势跟踪 | 突破N日高点做多，跌破N日低点平仓 |
| 布林带 | 均值回归 | 价格触及下轨做多，上轨平仓 |
| RSI | 均值回归 | 超卖做多，超买平仓 |
| Z-Score | 均值回归 | 基于统计偏离度的配对交易 |

查看 [策略开发指南](docs/guides/strategy_development.md) 了解如何创建自定义策略。

## 技术栈

| 组件 | 技术选型 | 用途 |
|------|---------|------|
| 语言 | Python 3.11+ | 快速开发与原型验证 |
| 数据存储 | InfluxDB + Parquet | 实时监控 + 历史回测 |
| 交易所接口 | ccxt | 统一的交易所抽象层 |
| 容器化 | Docker Compose | 一键部署所有服务 |
| 监控 | Grafana + Loki | 可视化面板与日志聚合 |
| 通知 | Telegram / Bark / Webhook | 多渠道消息推送 |
| 测试 | pytest | 单元测试与集成测试 |
| CI/CD | GitHub Actions | 自动化测试与部署 |

## 数据流

```
OKX/交易所 API
       ↓
   collector 服务
       ↓
    ┌──────┴──────┐
    ↓             ↓
Parquet      InfluxDB
(历史)        (实时)
    ↓             ↓
research    Grafana 监控
回测引擎          ↓
    ↓         告警通知
策略信号
    ↓
trader 服务
    ↓
订单执行
```

## 开发路线

### Phase 1: 核心框架（已完成）
- [x] 项目结构与配置管理
- [x] 数据采集与存储
- [x] 回测引擎（单策略 + 批量）
- [x] 5种内置策略
- [x] 风控引擎
- [x] 通知系统
- [x] 特征引擎

### Phase 2: Web 管理界面（进行中）
- [x] 回测结果可视化
- [x] 策略配置管理
- [x] 服务状态监控
- [x] 参数优化框架
- [ ] 实时数据刷新
- [ ] 任务进度展示

### Phase 3: 实盘交易（进行中）
- [x] OKX 现货/永续下单
- [x] 订单管理与追踪
- [x] 滑点与手续费模型
- [ ] 实盘风控完善
- [ ] 异常恢复机制

### Phase 4: 高级功能（规划中）
- [ ] OKX 永续合约
- [ ] Walk-forward 优化
- [ ] 多策略组合管理
- [ ] Qlib 框架集成

### Phase 5: 其他市场（远期）
- [ ] IBKR 接口（美股）
- [ ] A股数据对接
- [ ] 期权策略

查看 [GitHub Projects](https://github.com/ziho/AlgorithmTrader/projects) 了解详细进度。

## 文档

- [用户指南](docs/guides/user_guide.md) - 系统使用完整指南
- [策略开发](docs/guides/strategy_development.md) - 如何编写自定义策略
- [部署指南](docs/guides/deployment.md) - 生产环境部署
- [API 参考](docs/api/README.md) - 核心 API 文档
- [架构设计](docs/development/architecture.md) - 系统架构详解
- [**功能完成度**](docs/KNOWN_LIMITATIONS.md) - 各模块状态与已知限制

## 快速验证

运行烟雾测试脚本验证核心功能：

```bash
python scripts/smoke_test.py
```

## 测试

```bash
# 运行所有测试
pytest

# 运行单元测试
pytest tests/unit/

# 运行集成测试
pytest tests/integration/

# 生成覆盖率报告
pytest --cov=src tests/
```

## 贡献

这是一个个人项目，主要用于学习和实验。欢迎提 Issue 讨论想法，但不保证会接受 PR。

## 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 免责声明

本项目仅供学习与研究使用。量化交易存在风险，使用本系统进行实盘交易造成的任何损失，作者不承担责任。请在充分理解策略逻辑和风险的前提下谨慎使用。

## 相关资源

- [ccxt 文档](https://docs.ccxt.com/)
- [InfluxDB 文档](https://docs.influxdata.com/)
- [Grafana 文档](https://grafana.com/docs/)
- [Qlib 框架](https://github.com/microsoft/qlib)

---

**注意**: 本系统设计用于中低频交易（15分钟至1小时级别），不适合高频交易场景。
