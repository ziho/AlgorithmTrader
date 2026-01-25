下面给你一套**个人中低频量化（15m~1h、隔夜/跨周期）**可长期演进的系统框架：先把**加密现货（OKX+ccxt）端到端跑通**，再扩展永续、IBKR、美股/期权，A股先做通知+手动下单。整体强调：**同一套数据与策略接口**，研究/回测/实盘可复用，也允许分叉提速。

---

## 0. 设计原则（决定你后面省多少重构成本）

1. **统一“时钟/事件/Bar”语义**：所有策略都只依赖 Bar（15m/1h）与统一的事件流（on_bar / on_signal / on_fill）。
2. **数据分层**：采集(raw) → 清洗(curated) → 特征(features) → 信号(signals) → 交易执行(execution)。
3. **存储分工**（很关键）：

   * **InfluxDB**：实时/近实时 Bar、指标、权益曲线、风控指标、系统指标（高频写入、便于 Grafana）。
   * **Parquet+DuckDB**：历史大体量 OHLCV、特征矩阵、回测读取（便宜、快、适合研究/回测）。
4. **“研究-回测-实盘”共享核心库**：策略逻辑尽量纯函数化（输入=Bar/特征，输出=目标持仓/下单意图）。
5. **执行/风控接口先抽象**：以后上 C++ 优化时，你只替换执行与指标计算，不推倒全局。

---

## 1. 总体架构图（逻辑视图）

```
               ┌──────────────┐
               │ Data Sources  │  OKX/其他交易所 | (未来)IBKR | (A股)数据方
               └──────┬───────┘
                      │
              ┌───────▼────────┐
              │ data-collector  │  ccxt拉取bar/账户/成交；写入raw
              └───┬─────────┬──┘
                  │         │
        ┌─────────▼─┐   ┌──▼───────────┐
        │ Parquet FS │   │  InfluxDB     │
        │ (history)  │   │ (live+metrics)│
        └─────┬──────┘   └───┬──────────┘
              │              │
      ┌───────▼──────┐  ┌───▼───────────┐
      │ feature-engine│  │ monitor/alerts │  Grafana + 告警(Telegram)
      └───────┬──────┘  └───┬───────────┘
              │              │
      ┌───────▼────────┐     │
      │ research/backtest│<───┘  读取Parquet/DuckDB + 输出回测结果(Influx)
      └───────┬────────┘
              │
      ┌───────▼────────┐
      │ live-trader     │  策略→信号→组合→风控→下单
      └───────┬────────┘
              │
      ┌───────▼────────┐
      │ broker-adapters │  OKX现货(先) → 永续(后) → IBKR(后)
      └────────────────┘
```

---

## 2. Docker Compose：建议的容器与职责（单文件统一管理）

你要的“核心库单仓复用 + 轻服务化”，可以按**最小可用 + 可扩展**拆成 8 类容器。

### 2.1 基础设施（必选）

1. **influxdb**

   * 写入：实时 Bar、账户权益、策略指标、回测指标（回测也写，方便 Grafana 对比）
   * 保留策略：可设短保留（如 30~180 天），长期留 Parquet
2. **grafana**

   * 面板：账户权益、回撤、仓位、交易次数、错误率、延迟、数据缺口
3. （建议）**loki + promtail**（日志集中化，强烈建议）

   * 你要求限制日志大小：同时配合 Docker logging rotation + Loki 更稳

### 2.2 业务服务（MVP 必选）

4. **collector**（数据采集）

   * 轮询/定时抓取：OHLCV(15m/1h)、资金费率/指数价（永续后用）、账户余额/持仓/成交
   * 写入：Parquet（历史归档）+ Influx（最新与监控）
5. **scheduler**（统一调度）

   * 负责：定时任务（抓数据、跑特征、跑回测批任务、实盘策略 tick）
   * 个人场景不建议上 Airflow；用一个轻量 scheduler 服务即可（内部用 APScheduler/自研 tick loop）
6. **trader**（实盘交易主进程）

   * 从 Influx/内存总线拿到“bar close”事件 → 运行策略 → 组合/风控 → 调 broker 下单
7. **notifier**（消息通知）

   * Telegram 为主：下单、成交、触发风控、任务失败、数据缺口、回测完成摘要
   * A股阶段：只发“信号+建议动作”，你手动下单

### 2.3 研发与回测（按需启用）

8. **research**（Jupyter/VSCode Remote 可选）

   * 读取 Parquet/DuckDB，做探索、因子研究、Qlib 试验
9. **backtest-runner**（可与 research 合并，也可独立）

   * 以“批任务”的形式跑：参数扫描、Walk-forward、组合回测
   * 输出：结果摘要写 Influx，详细结果落 Parquet/JSON

> 容器间协作的核心只有三条“数据通道”：
>
> * Parquet(历史/大文件)
> * Influx(实时/监控/结果汇总)
> * Telegram(通知)

---

## 3. Repo 目录结构（具体到文件夹职责）

建议单仓（AlgorithmTrader）采用“**src + services + infra + research**”的清晰分层：

```
AlgorithmTrader/
  README.md
  pyproject.toml              # 统一依赖与工具配置（lint/test）
  .env.example                # 交易所key、Influx、Telegram等（不提交真实.env）
  docker-compose.yml          # 单文件编排
  infra/
    grafana/                  # dashboards、datasources
    influxdb/                 # init脚本、bucket/retention配置说明
    loki/ promtail/           # 日志采集配置（可选）
  src/                        # 核心可复用库（研究/回测/实盘共享）
    core/
      config/                 # 配置加载、环境区分(dev/prod)
      timeframes.py           # 15m/1h等统一定义
      instruments.py          # symbol规范化（OKX/IBKR映射）
      events.py               # BarEvent/SignalEvent/OrderEvent/FillEvent
      clock.py                # 交易时钟（bar close触发）
      typing.py               # 公共类型定义
    data/
      connectors/             # 数据源连接器：ccxt、(未来)ibkr、(未来)聚宽/其他
      pipelines/              # raw->curated->features 的ETL逻辑
      store/
        parquet_store.py      # Parquet读写、分区规则
        influx_store.py       # Influx写入/查询封装
      quality/
        validators.py         # 缺口检测、异常值处理、复权/时区等（后续扩展）
    features/
      factor_library/         # 因子库（动量、均线、波动率、截面rank等）
      feature_engine.py       # 特征计算调度入口
    strategy/
      base.py                 # Strategy接口：on_bar -> target_position/orders
      registry.py             # 策略注册与加载
      examples/               # 示例策略：趋势/均值回归/截面多因子
    portfolio/
      position.py             # 头寸对象
      allocator.py            # 从信号到目标持仓/权重
      accounting.py           # 费用、滑点、PNL、权益曲线
    risk/
      rules.py                # 风控规则接口（先留钩子）
      engine.py               # 风控编排（max dd/日亏/杠杆/强平等后续填）
    execution/
      broker_base.py          # Broker抽象：place/cancel/query
      adapters/
        okx_spot.py           # OKX现货（ccxt）
        okx_swap.py           # 永续（后续）
        ibkr.py               # IBKR（后续）
      order_manager.py        # 订单状态机（NEW->PARTIAL->FILLED…）
      slippage_fee.py         # bar级别滑点/手续费模型（回测用）
    backtest/
      engine.py               # 回测主引擎（bar级别撮合近似）
      metrics.py              # 绩效指标：sharpe、dd、胜率、换手等
      reports.py              # 生成摘要（写Influx+落盘）
    ops/
      scheduler.py            # 统一调度入口（collector/feature/backtest/trader）
      healthcheck.py          # 服务健康检查
      logging.py              # 日志规范（结构化日志）
      notify.py               # 通知封装（Telegram）
  services/                   # “进程级”入口（容器运行点）
    collector/
      main.py                 # 拉取bar/账户并写入store
    trader/
      main.py                 # 实盘主循环：等bar close -> run
    scheduler/
      main.py                 # 启动所有定时任务（也可与trader合并）
    backtest_runner/
      main.py                 # 读配置批量跑回测
    notifier/
      main.py                 # 独立通知服务（可选，通常是库调用即可）
  research/
    notebooks/                # 研究用notebook（可选）
    qlib/                     # 未来Qlib实验、数据准备脚本
  tests/
    unit/
    integration/
  .github/
    workflows/                # GitHub Actions：lint/test/build
```

---

## 4. 数据与时间框架（中低频里最容易踩坑的部分）

### 4.1 Bar 的“真相来源”

* **collector**只做两件事：

  1. 从交易所拉 OHLCV（15m/1h）
  2. 以统一时区与统一 symbol 规范化后写入 store
* **trader**的触发依据：

  * 以“bar close”作为唯一触发点（比如每 15 分钟整点后延迟 N 秒触发，避免交易所数据未完全落地）

### 4.2 存储策略（Influx + Parquet）

* Influx：写“最新bar + 指标 + 结果”，Grafana 看板天然友好
* Parquet：历史归档，回测/研究读取快、成本低
* DuckDB：本地/容器内直接 SQL 查 Parquet（不用起重型数据库）

---

## 5. 回测与实盘如何复用策略代码（你最在意的点）

核心是让策略只关心统一输入输出：

* 输入：`BarFrame`（当前bar、必要的历史窗口、可选特征矩阵）
* 输出（两种模式你都允许）：

  1. **target_position 模式**：输出目标权重/目标仓位（推荐，组合层做差分下单）
  2. **order_intent 模式**：直接输出买卖意图（更快上手，但组合一致性稍弱）

回测引擎与实盘 trader 共享：

* 同一套 `StrategyBase`
* 同一套 `Portfolio/Accounting`
* 同一套 `Slippage/Fee`（回测）与 `BrokerAdapter`（实盘）

---

## 6. 监控、日志与告警（全天候运行必须有）

### 6.1 Grafana 面板（MVP 必做）

* 数据完整性：bar 缺口率、最新bar时间滞后
* 交易健康：下单成功率、撤单率、成交延迟
* 风险：实时回撤、日内亏损、杠杆、最大单品种暴露
* 系统：CPU/Mem、容器重启次数、异常日志计数

### 6.2 日志大小限制（你明确要求）

* Docker logging driver 设 rotation（max-size / max-file）
* 同时建议 Loki：避免只靠本地文件滚动导致排障困难

### 6.3 Telegram 通知（MVP 必做）

* 触发：服务异常、数据缺口、触发风控、策略开/平仓、日终总结

---

## 7. 性能调优与未来 C++ 迭代路径（现在设计，未来省命）

### 7.1 Python 阶段的优化（中低频足够）

* 指标/因子计算优先用：numpy/numba/polars（按你的习惯选一个主力）
* 回测批量跑：多进程（按参数切分），结果汇总写 Influx
* IO：Parquet 分区（按交易所/品种/时间框架/年月）

### 7.2 C++ 迭代建议（只替换“热路径”）

把未来可能上 C++ 的部分提前“隔离接口”：

* execution：订单状态机、交易所适配器的关键逻辑
* indicators：滚动窗口指标、截面排名等热点计算
* 绑定方式路线：

  * 先 Numba（最快收益）
  * 再 PyO3 / Cython（需要更强控制时）
  * 或把 execution 做成独立进程（gRPC/ZeroMQ），Python 只发指令

---

## 8. 项目落地步骤（按里程碑推进，避免一上来做成“大而全”）

### Milestone 0：工程与基础设施（1次搭好，后面都吃红利）

* 建目录结构、依赖管理、日志规范、配置系统
* compose 起 InfluxDB + Grafana（+Loki 可选）
* GitHub Actions：lint/test（最小集）

### Milestone 1：Crypto 现货数据闭环

* collector：拉 OKX 15m/1h OHLCV → 写 Parquet + 写 Influx 最新
* Grafana：展示最新bar时间、缺口、写入速率

### Milestone 2：回测引擎（bar级别近似）

* 读 Parquet → 跑示例策略（趋势/均值回归）→ 产出绩效指标
* 写 Influx：权益曲线、回撤曲线、关键指标（Sharpe、DD、turnover）

### Milestone 3：实盘 Trader（只做现货、只做市价/限价简化版）

* trader：等待 bar close → 策略 → 目标仓位 → broker 下单
* notifier：成交/异常/日终摘要

### Milestone 4：永续合约（加密）

* 增加：资金费率、强平/保证金相关风控接口（先钩子，后填规则）
* 风险引擎逐步实装（你说留到写策略时定义，完全可行）

### Milestone 5：IBKR 与美股（正股先、期权后）

* 把 broker 接口实现为 ibkr adapter
* 数据：先用免费行情/延迟行情也能做中低频验证

### Milestone 6：Qlib 整合（研究侧先落地）

* research/qlib：准备数据集与因子实验
* 输出信号对接你统一的 strategy 接口（signal -> allocator）

---

## 9. 用于“vibe coding”的 Prompt（按模块直接喂给 Copilot/ChatGPT）

下面每条都是“你可以直接复制”的工作指令风格（不含代码）：

1. **Repo骨架与约束**

* “为一个个人中低频量化交易系统生成 Python 单仓目录结构与模块职责说明，要求研究/回测/实盘共享核心库，包含 data/features/strategy/portfolio/risk/execution/backtest/ops/services，并给出每个模块的接口边界与依赖方向（禁止反向依赖）。”

2. **事件与策略接口**

* “定义一个 bar 驱动的事件模型（BarEvent/SignalEvent/OrderEvent/FillEvent），并设计 StrategyBase 接口：输入为 bar+历史窗口+可选特征，输出为 target_position 或 order_intent；要求同一策略可被 backtest 与 live trader 调用。”

3. **数据存储抽象**

* “设计 InfluxStore 与 ParquetStore 的职责划分与数据模型：Influx 写最新bar与监控指标，Parquet 存历史分区文件；给出 symbol/timeframe/时间分区规范与缺口检测策略。”

4. **回测引擎（bar级别撮合近似）**

* “设计一个 bar 级别回测引擎：支持手续费与滑点模型（不做订单簿），支持多品种、跨周期持仓、输出权益曲线与回撤；并定义回测结果写入 Influx 的指标列表。”

5. **实盘 Trader 主循环**

* “设计 live trader：基于 bar close 触发，加载策略并生成目标仓位，经过风控引擎后调用 broker adapter 下单；要求具备幂等性（重复触发不重复下单）与断点恢复思路。”

6. **OKX(ccxt) 执行适配器**

* “设计 OKX 现货 broker adapter 的接口实现要点：下单/撤单/查询订单/查询余额与持仓；需要考虑网络失败重试、限频、订单状态一致性与本地订单状态机。”

7. **监控与告警**

* “给出 Grafana 面板规划：数据完整性、交易健康、风险暴露、系统资源四大类；同时定义 Telegram 通知触发规则与消息模板字段。”

8. **Docker Compose 部署规划**

* “规划一个单 docker-compose 的服务编排：influxdb/grafana/(loki+promtail可选)/collector/scheduler/trader/backtest-runner；要求说明容器间通过哪些 volume/network 交互，并给出日志滚动策略与数据持久化目录规划。”

---

## 10. 我对你需求的“优化版 Prompt”（更利于你后续迭代与外包协作）

你原 Prompt 已经很清晰了，我建议补充 3 个“可执行约束”，让产出更落地：

* **统一符号规范**：明确你希望内部统一用 `EXCHANGE:BASE/QUOTE`（例如 `OKX:BTC/USDT`）还是别的格式
* **交易模式**：现货阶段是否允许做空（通常不做），永续阶段是否允许对冲/同时多空不同品种
* **资金曲线基准**：以 USDT 计价还是折算 USD/CAD（影响统计）

（不补也能做，我会默认：内部 `OKX:BTC/USDT`，现货只做多，权益以 USDT 计。）

---

## 11. 你接下来“第一步”应该做什么（最小阻力启动）

按你的条件（Ubuntu Server + Docker 已好），最优先顺序是：

1. 起 InfluxDB + Grafana（确认持久化卷与日志滚动策略）
2. 落地 Parquet 分区规范（决定你未来数据不会乱）
3. 写 collector 的“最小闭环”：OKX 拉 15m BTC/USDT → 同时写 Influx(最新) + Parquet(历史)
4. Grafana 画出“最新bar时间滞后 + 缺口率”两张图
   做到这里，你的系统就已经从“想法”变成“可运行的骨架”。


