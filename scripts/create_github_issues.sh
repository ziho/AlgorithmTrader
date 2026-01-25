#!/bin/bash
# AlgorithmTrader - GitHub Milestones & Issues 创建脚本
# 运行前请确保已认证: gh auth login

set -e

REPO="ziho/AlgorithmTrader"

echo "=== 创建 Milestones ==="

# Milestone 0: 工程与基础设施
gh api repos/$REPO/milestones -f title="M0: 工程与基础设施" -f description="建目录结构、依赖管理、日志规范、配置系统。compose 起 InfluxDB + Grafana。GitHub Actions: lint/test（最小集）" -f state="open"

# Milestone 1: Crypto 现货数据闭环
gh api repos/$REPO/milestones -f title="M1: Crypto 现货数据闭环" -f description="collector: 拉 OKX 15m/1h OHLCV → 写 Parquet + 写 Influx 最新。Grafana: 展示最新bar时间、缺口、写入速率" -f state="open"

# Milestone 2: 回测引擎
gh api repos/$REPO/milestones -f title="M2: 回测引擎（bar级别近似）" -f description="读 Parquet → 跑示例策略（趋势/均值回归）→ 产出绩效指标。写 Influx: 权益曲线、回撤曲线、关键指标（Sharpe、DD、turnover）" -f state="open"

# Milestone 3: 实盘 Trader
gh api repos/$REPO/milestones -f title="M3: 实盘 Trader（现货简化版）" -f description="trader: 等待 bar close → 策略 → 目标仓位 → broker 下单。notifier: 成交/异常/日终摘要" -f state="open"

# Milestone 4: 永续合约
gh api repos/$REPO/milestones -f title="M4: 永续合约（加密）" -f description="增加: 资金费率、强平/保证金相关风控接口。风险引擎逐步实装" -f state="open"

# Milestone 5: IBKR 与美股
gh api repos/$REPO/milestones -f title="M5: IBKR 与美股" -f description="把 broker 接口实现为 ibkr adapter。数据: 先用免费行情/延迟行情验证中低频" -f state="open"

# Milestone 6: Qlib 整合
gh api repos/$REPO/milestones -f title="M6: Qlib 整合（研究侧）" -f description="research/qlib: 准备数据集与因子实验。输出信号对接统一的 strategy 接口" -f state="open"

echo "Milestones 创建完成!"

echo ""
echo "=== 创建 Issues ==="

# ============================================
# Milestone 0: 工程与基础设施
# ============================================

echo "创建 M0 Issues..."

gh issue create --repo $REPO \
  --title "[M0] 初始化项目目录结构" \
  --body "## 描述
创建项目的完整目录结构，包括：
- \`src/\` 核心可复用库（研究/回测/实盘共享）
  - \`core/\` 配置、事件、时钟等基础模块
  - \`data/\` 数据连接器、存储、ETL
  - \`features/\` 因子库
  - \`strategy/\` 策略基类与示例
  - \`portfolio/\` 组合与仓位管理
  - \`risk/\` 风控规则
  - \`execution/\` 执行与 broker 适配
  - \`backtest/\` 回测引擎
  - \`ops/\` 调度、日志、通知
- \`services/\` 进程级入口（collector/trader/scheduler）
- \`research/\` 研究 notebooks
- \`infra/\` 基础设施配置
- \`tests/\` 测试

## 验收标准
- [ ] 目录结构完整
- [ ] 每个模块有 \`__init__.py\`
- [ ] README 说明模块职责" \
  --label "core,infra" \
  --milestone "M0: 工程与基础设施"

gh issue create --repo $REPO \
  --title "[M0] 配置 pyproject.toml 依赖管理" \
  --body "## 描述
使用 pyproject.toml 统一管理项目依赖与工具配置

## 核心依赖
- ccxt (交易所接口)
- pandas, numpy, polars (数据处理)
- influxdb-client (时序数据库)
- pyarrow (Parquet 读写)
- duckdb (本地 SQL 查询)
- python-telegram-bot (通知)
- APScheduler (调度)

## 开发依赖
- pytest
- ruff (lint)
- mypy (类型检查)

## 验收标准
- [ ] pyproject.toml 配置完整
- [ ] 可通过 pip install -e . 安装
- [ ] lint/test 配置完成" \
  --label "core,infra" \
  --milestone "M0: 工程与基础设施"

gh issue create --repo $REPO \
  --title "[M0] 创建 .env.example 与配置加载模块" \
  --body "## 描述
创建配置管理系统：
- \`.env.example\` 模板（不提交真实密钥）
- \`src/core/config/\` 配置加载模块

## 配置项
- 交易所 API Key/Secret (OKX)
- InfluxDB 连接信息
- Telegram Bot Token
- 环境区分 (dev/prod)

## 验收标准
- [ ] .env.example 完整
- [ ] 配置加载模块可区分环境
- [ ] .gitignore 排除 .env" \
  --label "core,infra" \
  --milestone "M0: 工程与基础设施"

gh issue create --repo $REPO \
  --title "[M0] 设计统一日志规范" \
  --body "## 描述
设计结构化日志规范 \`src/ops/logging.py\`：
- 统一日志格式（JSON 结构化）
- 日志级别规范
- 文件滚动策略（与 Docker 配合）

## 验收标准
- [ ] 日志模块可复用
- [ ] 支持 console + file 双输出
- [ ] 便于 Loki 采集" \
  --label "core,infra" \
  --milestone "M0: 工程与基础设施"

gh issue create --repo $REPO \
  --title "[M0] Docker Compose 部署 InfluxDB + Grafana" \
  --body "## 描述
创建 docker-compose.yml 部署基础设施：
- InfluxDB 2.x
- Grafana
- (可选) Loki + Promtail

## 配置要求
- 数据持久化卷
- 日志滚动策略 (max-size/max-file)
- 网络隔离
- InfluxDB bucket/retention 配置

## 验收标准
- [ ] docker-compose up 可启动全部服务
- [ ] 数据持久化正常
- [ ] Grafana 可访问 InfluxDB" \
  --label "infra" \
  --milestone "M0: 工程与基础设施"

gh issue create --repo $REPO \
  --title "[M0] 配置 GitHub Actions CI/CD" \
  --body "## 描述
创建 \`.github/workflows/\` 配置：
- Lint (ruff)
- Test (pytest)
- 类型检查 (mypy)

## 验收标准
- [ ] PR 自动运行检查
- [ ] 状态徽章添加到 README" \
  --label "infra" \
  --milestone "M0: 工程与基础设施"

gh issue create --repo $REPO \
  --title "[M0] 定义核心事件模型" \
  --body "## 描述
在 \`src/core/events.py\` 定义事件驱动模型：
- BarEvent (K线事件)
- SignalEvent (信号事件)
- OrderEvent (订单事件)
- FillEvent (成交事件)

## 设计原则
- 事件不可变
- 包含时间戳与来源标识
- 支持序列化

## 验收标准
- [ ] 事件类定义完整
- [ ] 类型注解完善
- [ ] 单元测试覆盖" \
  --label "core" \
  --milestone "M0: 工程与基础设施"

gh issue create --repo $REPO \
  --title "[M0] 定义统一 Symbol/Timeframe 规范" \
  --body "## 描述
在 \`src/core/\` 定义：
- \`instruments.py\`: Symbol 规范化 (内部格式: \`OKX:BTC/USDT\`)
- \`timeframes.py\`: 时间框架定义 (15m/1h)

## 要求
- 支持 OKX/IBKR 等交易所映射
- 时间框架统一处理

## 验收标准
- [ ] Symbol 映射正确
- [ ] 时区处理统一 (UTC)" \
  --label "core" \
  --milestone "M0: 工程与基础设施"

# ============================================
# Milestone 1: Crypto 现货数据闭环
# ============================================

echo "创建 M1 Issues..."

gh issue create --repo $REPO \
  --title "[M1] 实现 ccxt OKX 数据连接器" \
  --body "## 描述
在 \`src/data/connectors/\` 实现 OKX 数据连接器：
- 使用 ccxt 库
- 拉取 OHLCV (15m/1h)
- 拉取账户余额/持仓

## 接口设计
\`\`\`python
class OKXConnector:
    async def fetch_ohlcv(symbol, timeframe, since, limit) -> pd.DataFrame
    async def fetch_balance() -> dict
    async def fetch_positions() -> list
\`\`\`

## 验收标准
- [ ] 可成功拉取 BTC/USDT 数据
- [ ] 错误处理与重试机制
- [ ] 限频控制" \
  --label "data" \
  --milestone "M1: Crypto 现货数据闭环"

gh issue create --repo $REPO \
  --title "[M1] 实现 Parquet 存储模块" \
  --body "## 描述
在 \`src/data/store/parquet_store.py\` 实现：
- Parquet 文件读写
- 分区规则 (交易所/品种/时间框架/年月)
- 追加写入与去重

## 分区示例
\`\`\`
data/parquet/
  okx/
    btc_usdt/
      15m/
        2026-01.parquet
        2026-02.parquet
\`\`\`

## 验收标准
- [ ] 写入性能满足需求
- [ ] 分区结构正确
- [ ] 支持增量追加" \
  --label "data" \
  --milestone "M1: Crypto 现货数据闭环"

gh issue create --repo $REPO \
  --title "[M1] 实现 InfluxDB 存储模块" \
  --body "## 描述
在 \`src/data/store/influx_store.py\` 实现：
- 写入最新 Bar 数据
- 写入监控指标
- 查询接口

## 数据模型
- measurement: ohlcv
- tags: exchange, symbol, timeframe
- fields: open, high, low, close, volume

## 验收标准
- [ ] 写入成功
- [ ] Grafana 可查询" \
  --label "data,infra" \
  --milestone "M1: Crypto 现货数据闭环"

gh issue create --repo $REPO \
  --title "[M1] 实现 Collector 服务" \
  --body "## 描述
在 \`services/collector/main.py\` 实现数据采集服务：
- 定时拉取 15m/1h K线
- 同时写入 Parquet + InfluxDB
- 缺口检测与告警

## 调度策略
- 15m: 每 15 分钟整点后 10 秒触发
- 1h: 每小时整点后 10 秒触发

## 验收标准
- [ ] 定时任务稳定运行
- [ ] 数据完整写入
- [ ] 缺口检测可用" \
  --label "data,infra" \
  --milestone "M1: Crypto 现货数据闭环"

gh issue create --repo $REPO \
  --title "[M1] 创建 Grafana 数据监控面板" \
  --body "## 描述
创建 Grafana Dashboard：
- 最新 bar 时间滞后
- 数据缺口率
- 写入速率
- 系统资源监控

## 验收标准
- [ ] Dashboard JSON 导出
- [ ] 可导入复现
- [ ] 告警规则配置" \
  --label "infra" \
  --milestone "M1: Crypto 现货数据闭环"

gh issue create --repo $REPO \
  --title "[M1] 实现数据质量检测模块" \
  --body "## 描述
在 \`src/data/quality/validators.py\` 实现：
- 缺口检测（连续 bar 时间间隔）
- 异常值检测（价格跳变）
- 时区标准化检查

## 验收标准
- [ ] 缺口检测准确
- [ ] 异常值标记
- [ ] 检测结果可写入 InfluxDB" \
  --label "data" \
  --milestone "M1: Crypto 现货数据闭环"

# ============================================
# Milestone 2: 回测引擎
# ============================================

echo "创建 M2 Issues..."

gh issue create --repo $REPO \
  --title "[M2] 设计 StrategyBase 策略接口" \
  --body "## 描述
在 \`src/strategy/base.py\` 设计策略基类：
- 输入: BarFrame (当前bar + 历史窗口 + 可选特征)
- 输出: target_position 或 order_intent

## 接口设计
\`\`\`python
class StrategyBase(ABC):
    @abstractmethod
    def on_bar(self, bar_frame: BarFrame) -> TargetPosition | OrderIntent:
        pass
    
    def on_fill(self, fill: FillEvent):
        pass
\`\`\`

## 验收标准
- [ ] 接口定义清晰
- [ ] 回测与实盘可共用
- [ ] 类型注解完善" \
  --label "core" \
  --milestone "M2: 回测引擎（bar级别近似）"

gh issue create --repo $REPO \
  --title "[M2] 实现 Bar 级别回测引擎" \
  --body "## 描述
在 \`src/backtest/engine.py\` 实现：
- 读取 Parquet 历史数据
- Bar 级别撮合（不做订单簿）
- 支持多品种、跨周期持仓

## 撮合逻辑
- 使用下一根 bar 的 open 价格成交
- 滑点模型: 固定点数或百分比
- 手续费模型: maker/taker 费率

## 验收标准
- [ ] 回测结果正确
- [ ] 支持多品种
- [ ] 性能满足需求" \
  --label "core" \
  --milestone "M2: 回测引擎（bar级别近似）"

gh issue create --repo $REPO \
  --title "[M2] 实现滑点与手续费模型" \
  --body "## 描述
在 \`src/execution/slippage_fee.py\` 实现：
- 滑点模型
  - 固定点数
  - 百分比
- 手续费模型
  - Maker/Taker 费率
  - 支持不同交易所配置

## 验收标准
- [ ] 模型可配置
- [ ] 回测引擎正确调用" \
  --label "core,execution" \
  --milestone "M2: 回测引擎（bar级别近似）"

gh issue create --repo $REPO \
  --title "[M2] 实现绩效指标计算模块" \
  --body "## 描述
在 \`src/backtest/metrics.py\` 实现：
- Sharpe Ratio
- Maximum Drawdown
- 胜率/盈亏比
- 换手率
- Calmar Ratio
- 年化收益率

## 验收标准
- [ ] 指标计算正确
- [ ] 支持滚动窗口计算
- [ ] 输出格式统一" \
  --label "core" \
  --milestone "M2: 回测引擎（bar级别近似）"

gh issue create --repo $REPO \
  --title "[M2] 实现组合与仓位管理模块" \
  --body "## 描述
在 \`src/portfolio/\` 实现：
- \`position.py\`: 头寸对象
- \`allocator.py\`: 信号到目标持仓转换
- \`accounting.py\`: PNL 计算、权益曲线

## 验收标准
- [ ] 仓位跟踪准确
- [ ] 权益曲线计算正确
- [ ] 支持多品种组合" \
  --label "core" \
  --milestone "M2: 回测引擎（bar级别近似）"

gh issue create --repo $REPO \
  --title "[M2] 实现回测报告生成模块" \
  --body "## 描述
在 \`src/backtest/reports.py\` 实现：
- 生成回测摘要报告
- 写入 InfluxDB（便于 Grafana 对比）
- 详细结果落盘 Parquet/JSON

## 报告内容
- 绩效指标汇总
- 权益曲线数据
- 交易明细

## 验收标准
- [ ] 报告格式清晰
- [ ] Grafana 可展示
- [ ] 支持多次回测对比" \
  --label "core" \
  --milestone "M2: 回测引擎（bar级别近似）"

gh issue create --repo $REPO \
  --title "[M2] 实现示例策略: 趋势跟踪" \
  --body "## 描述
在 \`src/strategy/examples/\` 实现趋势跟踪策略：
- 双均线交叉
- 突破策略

## 验收标准
- [ ] 策略逻辑正确
- [ ] 可通过回测引擎运行
- [ ] 作为模板参考" \
  --label "core" \
  --milestone "M2: 回测引擎（bar级别近似）"

gh issue create --repo $REPO \
  --title "[M2] 实现示例策略: 均值回归" \
  --body "## 描述
在 \`src/strategy/examples/\` 实现均值回归策略：
- 布林带策略
- RSI 超买超卖

## 验收标准
- [ ] 策略逻辑正确
- [ ] 可通过回测引擎运行" \
  --label "core" \
  --milestone "M2: 回测引擎（bar级别近似）"

gh issue create --repo $REPO \
  --title "[M2] 创建 Grafana 回测结果面板" \
  --body "## 描述
创建 Grafana Dashboard 展示回测结果：
- 权益曲线
- 回撤曲线
- 关键指标对比

## 验收标准
- [ ] Dashboard 可导入
- [ ] 支持多回测对比" \
  --label "infra" \
  --milestone "M2: 回测引擎（bar级别近似）"

# ============================================
# Milestone 3: 实盘 Trader
# ============================================

echo "创建 M3 Issues..."

gh issue create --repo $REPO \
  --title "[M3] 设计 Broker 抽象接口" \
  --body "## 描述
在 \`src/execution/broker_base.py\` 设计 Broker 抽象：
- place_order(): 下单
- cancel_order(): 撤单
- query_order(): 查询订单
- get_balance(): 查询余额
- get_positions(): 查询持仓

## 验收标准
- [ ] 接口定义清晰
- [ ] 支持多交易所扩展" \
  --label "execution" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] 实现 OKX 现货 Broker Adapter" \
  --body "## 描述
在 \`src/execution/adapters/okx_spot.py\` 实现：
- 使用 ccxt 下单/撤单/查询
- 网络失败重试
- 限频控制
- 订单状态一致性

## 验收标准
- [ ] 下单成功
- [ ] 错误处理完善
- [ ] 日志记录详细" \
  --label "execution" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] 实现订单状态机" \
  --body "## 描述
在 \`src/execution/order_manager.py\` 实现：
- 订单状态: NEW → PARTIAL → FILLED / CANCELLED
- 状态转换逻辑
- 本地订单缓存与同步

## 验收标准
- [ ] 状态转换正确
- [ ] 支持断点恢复" \
  --label "execution" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] 实现 Live Trader 主循环" \
  --body "## 描述
在 \`services/trader/main.py\` 实现：
- 等待 bar close 触发
- 加载并运行策略
- 生成目标仓位
- 风控检查
- 调用 Broker 下单

## 幂等性要求
- 重复触发不重复下单
- 支持断点恢复

## 验收标准
- [ ] 主循环稳定运行
- [ ] 下单逻辑正确
- [ ] 幂等性保证" \
  --label "execution,core" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] 实现交易时钟模块" \
  --body "## 描述
在 \`src/core/clock.py\` 实现：
- Bar close 事件触发
- 延迟触发（避免交易所数据未落地）
- 支持不同时间框架

## 验收标准
- [ ] 触发时间准确
- [ ] 支持配置延迟" \
  --label "core" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] 实现 Telegram 通知模块" \
  --body "## 描述
在 \`src/ops/notify.py\` 实现：
- 下单通知
- 成交通知
- 异常告警
- 日终摘要

## 消息模板
- 包含: 时间、品种、方向、数量、价格、原因

## 验收标准
- [ ] 消息发送成功
- [ ] 模板可配置
- [ ] 异步发送不阻塞" \
  --label "infra" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] 实现 Notifier 服务" \
  --body "## 描述
在 \`services/notifier/main.py\` 实现通知服务：
- 独立进程（可选）
- 消息队列消费
- 批量发送优化

## 验收标准
- [ ] 通知稳定可靠
- [ ] 支持消息聚合" \
  --label "infra" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] 实现统一调度器" \
  --body "## 描述
在 \`services/scheduler/main.py\` 实现：
- 统一管理定时任务
- 使用 APScheduler
- 任务: 数据采集、策略运行、健康检查

## 验收标准
- [ ] 任务调度准确
- [ ] 支持动态添加任务
- [ ] 任务失败告警" \
  --label "infra" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] 创建 Grafana 实盘监控面板" \
  --body "## 描述
创建 Grafana Dashboard：
- 交易健康: 下单成功率、撤单率、成交延迟
- 风险: 实时回撤、日内亏损、仓位
- 系统: CPU/Mem、容器重启次数

## 验收标准
- [ ] Dashboard 完整
- [ ] 告警规则配置" \
  --label "infra" \
  --milestone "M3: 实盘 Trader（现货简化版）"

gh issue create --repo $REPO \
  --title "[M3] Docker Compose 添加业务服务" \
  --body "## 描述
更新 docker-compose.yml：
- collector 服务
- scheduler 服务
- trader 服务
- notifier 服务

## 配置
- 服务依赖关系
- 健康检查
- 资源限制

## 验收标准
- [ ] 所有服务可启动
- [ ] 服务间通信正常" \
  --label "infra" \
  --milestone "M3: 实盘 Trader（现货简化版）"

# ============================================
# Milestone 4: 永续合约
# ============================================

echo "创建 M4 Issues..."

gh issue create --repo $REPO \
  --title "[M4] 实现 OKX 永续合约 Adapter" \
  --body "## 描述
在 \`src/execution/adapters/okx_swap.py\` 实现：
- 永续合约下单
- 杠杆设置
- 保证金查询
- 强平价格计算

## 验收标准
- [ ] 合约下单成功
- [ ] 杠杆管理正确" \
  --label "execution" \
  --milestone "M4: 永续合约（加密）"

gh issue create --repo $REPO \
  --title "[M4] 实现资金费率数据采集" \
  --body "## 描述
扩展 Collector：
- 采集资金费率
- 采集指数价格
- 存储到 InfluxDB + Parquet

## 验收标准
- [ ] 资金费率采集正确
- [ ] 历史数据完整" \
  --label "data" \
  --milestone "M4: 永续合约（加密）"

gh issue create --repo $REPO \
  --title "[M4] 实现风控引擎框架" \
  --body "## 描述
在 \`src/risk/engine.py\` 实现风控编排：
- 风控规则接口
- 规则链执行
- 拦截与告警

## 验收标准
- [ ] 框架可扩展
- [ ] 规则可配置" \
  --label "risk" \
  --milestone "M4: 永续合约（加密）"

gh issue create --repo $REPO \
  --title "[M4] 实现基础风控规则" \
  --body "## 描述
在 \`src/risk/rules.py\` 实现：
- 最大回撤限制
- 单日最大亏损
- 杠杆上限
- 单品种最大仓位
- 强平预警

## 验收标准
- [ ] 规则触发正确
- [ ] 支持参数配置" \
  --label "risk" \
  --milestone "M4: 永续合约（加密）"

# ============================================
# Milestone 5: IBKR 与美股
# ============================================

echo "创建 M5 Issues..."

gh issue create --repo $REPO \
  --title "[M5] 研究 IBKR API 接入方案" \
  --body "## 描述
调研 Interactive Brokers API：
- TWS API vs IB Gateway
- ib_insync 库
- 数据权限与费用
- 延迟与限制

## 输出
- 技术方案文档
- 接口设计建议

## 验收标准
- [ ] 方案文档完成
- [ ] 风险点明确" \
  --label "docs,execution" \
  --milestone "M5: IBKR 与美股"

gh issue create --repo $REPO \
  --title "[M5] 实现 IBKR Broker Adapter" \
  --body "## 描述
在 \`src/execution/adapters/ibkr.py\` 实现：
- 美股正股下单
- 查询持仓/余额
- 订单状态同步

## 验收标准
- [ ] 基础功能可用
- [ ] 错误处理完善" \
  --label "execution" \
  --milestone "M5: IBKR 与美股"

gh issue create --repo $REPO \
  --title "[M5] 实现 IBKR 数据连接器" \
  --body "## 描述
在 \`src/data/connectors/ibkr.py\` 实现：
- 历史数据拉取
- 实时行情订阅（可选）
- 数据格式转换

## 验收标准
- [ ] 数据拉取成功
- [ ] 格式与系统统一" \
  --label "data" \
  --milestone "M5: IBKR 与美股"

gh issue create --repo $REPO \
  --title "[M5] 支持美股期权数据与交易" \
  --body "## 描述
扩展支持美股期权：
- 期权链数据
- 期权报价
- 期权下单

## 验收标准
- [ ] 期权数据可获取
- [ ] 基础下单可用" \
  --label "execution,data" \
  --milestone "M5: IBKR 与美股"

# ============================================
# Milestone 6: Qlib 整合
# ============================================

echo "创建 M6 Issues..."

gh issue create --repo $REPO \
  --title "[M6] 研究 Qlib 框架集成方案" \
  --body "## 描述
调研微软 Qlib 框架：
- 数据格式要求
- 因子计算流程
- 模型训练接口
- 与现有系统对接点

## 输出
- 集成方案文档
- 数据转换需求

## 验收标准
- [ ] 方案文档完成
- [ ] 对接方式明确" \
  --label "docs" \
  --milestone "M6: Qlib 整合（研究侧）"

gh issue create --repo $REPO \
  --title "[M6] 准备 Qlib 数据集" \
  --body "## 描述
在 \`research/qlib/\` 实现：
- 数据格式转换脚本
- Qlib 数据目录生成
- 数据验证

## 验收标准
- [ ] Qlib 可加载数据
- [ ] 数据完整性验证" \
  --label "data" \
  --milestone "M6: Qlib 整合（研究侧）"

gh issue create --repo $REPO \
  --title "[M6] 实现 Qlib 信号到策略接口转换" \
  --body "## 描述
实现 Qlib 输出对接 Strategy 接口：
- Qlib 预测信号解析
- 转换为 target_position
- 接入 allocator

## 验收标准
- [ ] 信号转换正确
- [ ] 可与回测引擎配合" \
  --label "core" \
  --milestone "M6: Qlib 整合（研究侧）"

echo ""
echo "=== 全部完成! ==="
echo "请查看 GitHub Project 确认 Issues 已创建"
