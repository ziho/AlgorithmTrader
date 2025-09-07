下面是一套“个人中低频量化交易系统”的完整架构设计与落地蓝图。它以**Python 快速原型**为主、**Qlib 可无缝融入**、并为未来**C++ 性能化迭代**预留边界；同时把你现有的 **Linux Ubuntu Server + Docker + Grafana + InfluxDB** 纳入体系，给出自洽的数据流、服务编排、监控观测与风控路径。整套方案不含任何实际代码，但具体到目录结构、容器角色、数据与控制接口、实施步骤以及“vibe coding”的提示模版。

---

# 1. 总览（场景与约束）

**交易频率**：中低频（分钟级/小时级/日级重平衡）
**资产范围**：加密货币、A股、美股；股票/期货/期权
**硬件**：12代 i5，64GB RAM，12GB 显存 GPU，7×24 运行
**既有组件**：Docker、Grafana、InfluxDB
**研发栈**：Python 为主；后续可引入 Qlib；性能热点可用 C++ 演进

---

# 2. 分层架构与数据流

```
[数据源] ──> [采集层 Ingest] ──> [校验&清洗] ──> [特征&因子/标签工程] ──> [特征库/数据湖]
    |                     |               |                       |
    |                     v               v                       v
    |                 [InfluxDB(行情TS)]  [Parquet/Arrow(研究)]   [Postgres(元数据)]
    |                                                           
    |────────────> [回测/研究实验室: Backtrader/Qlib/Notebook] ──> [模型/策略产物登记]
                                                              
[调度] Prefect/Airflow ──驱动上述批处理/重采样/回测/训练/再平衡任务
[事件总线] Redis Streams ──策略信号 → 风控 → 执行路由 → 券商/交易所适配器

                                    实盘路径
策略引擎 →(信号/权重)→ 风控引擎 →(合格订单)→ 执行路由 →(路由/拆单)→ 券商适配器
  ↑             |            |                             ↑
  |             v            v                             |
[监控/告警] ← InfluxDB(指标) + Loki(日志) + Grafana(面板&告警) ← Telegraf/Promtail
```

**关键理念**

* **研究与实盘解耦**：数据落地与特征生成一致化，但回测与实盘用“同一逻辑不同数据时点”。
* **轻量消息总线**：Redis Streams 足以支撑个人中低频；复杂到一定程度可平滑替换为 Kafka。
* **存储分工**：

  * InfluxDB：**高频/近实时行情与运行指标**（已部署，继续用）
  * Parquet/Arrow（本地磁盘或 MinIO 本地对象存储）：**研究/回测数据湖**
  * Postgres：**元数据/实验追踪/订单与成交账本**（结构化、可事务）
* **跨市场日历与合规**：A 股（T+1/涨跌停/交易时段）、美股（T+0/盘前盘后）、Crypto（7×24），在**日历层**统一约束。
* **GPU 用途**：模型训练（PyTorch/LightGBM GPU）、大规模特征计算（Polars、Numba）——**不在撮合链路**。

---

# 3. 容器与服务清单（Docker 编排视角）

> 说明：保留你现有 Grafana/InfluxDB 容器；其余服务按需增加。各容器通过同一 Docker 网络通讯，统一使用 `.env` 管理密钥/凭据（或 Docker Secrets/HashiCorp Vault）。

**基础设施**

1. **influxdb**（已部署）

   * 存行情TS、系统指标、风控/执行KPI。
2. **grafana**（已部署）

   * 看板与告警（接入邮件/Telegram/企业微信）。
3. **postgres**

   * 订单/成交账本、元数据（合约定义、交易日历、实验记录、模型版本）。
4. **redis**

   * 事件总线（Streams）：`signals`、`orders`、`executions`、`risk_events`。
5. **minio（可选，或直接本地磁盘路径）**

   * 研究数据湖（Parquet/Arrow）与模型产物。

**采集与数据管道**
6\. **collector-crypto**

* 行情：交易所 REST/WebSocket（分钟级K线、盘口快照、Funding/期货基差）。
* 写入：InfluxDB（近实时），Parquet（日终/定时批量）。

7. **collector-us**

   * 来源：合法数据源或券商端点（遵循许可）；EOD/分钟级即可。
8. **collector-cn**

   * 来源：合规渠道（券商/数据供应商）；A股日内或日线。
9. **validator**

   * 去重、缺失补齐、时区对齐、公司行为校正（分红/拆并股）。
10. **resampler**

* Tick→1m/5m/1h/1d 聚合，落 InfluxDB（便于看板）与 Parquet（研究）。

**特征与研究**
11\. **feature-engine**

* 指标/因子：技术面（MA/ATR/RSI）、量价（VWAP/成交结构）、基本面融合、横截面因子。
* 输出：Parquet/Arrow（按`market/date/symbol`分区），同步摘要到 Postgres。

12. **qlib-service**（后续启用）

* 加载数据湖（或 Qlib 数据目录），提供 Alpha 研究、因子挖掘、模型训练接口。

13. **research-lab**

* JupyterLab（内置 Backtrader/Qlib/Polars），与数据湖/InfluxDB 只读连接。

14. **backtest-runner**

* 批量回测/WF/蒙特卡洛、交易成本/滑点模型、复现实盘撮合约束。

**实盘路径**
15\. **strategy-engine**

* 产出**目标权重/信号**（而非具体订单），写入 `signals`。

16. **risk-engine**

* 账户与组合层限制（资金/杠杆/敞口/波动率/回撤/单票/盘口冲击等）。
* 交易所与市场规则校验（A股 T+1/涨跌停、US Reg、Crypto 合约限制）。
* 合格后生成**订单指令** → `orders`。

17. **execution-router**

* 接收订单指令，按市场/品种路由到对应**券商/交易所适配器**。
* 简单的 VWAP/TWAP/POV 拆单（中低频即可）。

18. **adapter-binance / adapter-ib / adapter-xtp（示例）**

* 各券商/交易所 REST/WebSocket 封装，状态机化；回推成交到 `executions`。

19. **paper-broker**

* 本地撮合模拟（盘口/价差/滑点与延迟模型），用于 Dry-Run 与回归测试。

**监控与可观测性**
20\. **telegraf**

* 主机/容器资源、应用自定义指标 → InfluxDB。

21. **loki + promtail（或 Grafana Agent）**

* 聚合日志、Grafana 日志面板 & 日志告警。

22. **alertmanager（可选，或用 Grafana Alerting）**

* 告警分发（邮件/IM）。

**调度与自动化**
23\. **prefect-server**（或 Airflow，二选一）

* 定时采集、日终校验、重采样、因子计算、回测、再平衡执行等流程化。

---

# 4. 目录结构（单一 Git 仓库，多服务 Monorepo）

```
quant-stack/
├─ infra/               # 基础设施与编排（说明文档、环境变量样例、网络/卷规划）
│  ├─ compose/          # 各环境的容器编排清单（dev / paper / live）
│  ├─ secrets/          # 密钥占位（用 .template + Docker secrets/Vault 管理）
│  └─ dashboards/       # Grafana JSON 面板、InfluxDB 任务/Retention 策略说明
├─ apps/
│  ├─ collectors/       # crypto / us / cn 采集器（REST/WS）与 validator/resampler
│  ├─ feature_engine/   # 指标/因子流水线（批/流皆可）
│  ├─ qlib_service/     # Qlib 集成与数据桥
│  ├─ backtest_runner/  # 回测/走查/蒙特卡洛/参数寻优批处理
│  ├─ strategy_engine/  # 策略组合 & 决策（发目标权重/信号）
│  ├─ risk_engine/      # 事前/事中/事后风控（限额、合规、回撤、熔断）
│  ├─ execution_router/ # 拆单/路由/节流/容错
│  ├─ adapters/         # binance / ib / xtp / paper 等适配器
│  ├─ monitoring/       # 指标埋点、日志包装、健康检查探针
│  └─ common/           # 公共库：事件模型、日历、配置、数据契约、撮合仿真
├─ data/
│  ├─ lake/             # Parquet/Arrow 数据湖（按 market/date/symbol 分区）
│  └─ cache/            # 中间缓存、校验产物
├─ models/              # 训练好的模型、特征选择清单、版本登记（配合 Postgres）
├─ research/
│  ├─ notebooks/        # 研究/可视化原型
│  └─ playbooks/        # 常用研究流程（WF、因子评估、组合构建）说明
├─ docs/
│  ├─ runbook/          # 运维/应急/发布/回滚手册
│  ├─ risk_policies/    # 风控矩阵与阈值说明
│  ├─ slippage_models/  # 市场 & 品种滑点/冲击参数
│  └─ data_contracts/   # 各阶段数据契约（schema、单位、时区、NULL 约束）
└─ tests/
   ├─ unit/             # 单元测试（策略/风控/撮合）
   └─ integration/      # 端到端回放（paper-broker 驱动）
```

---

# 5. 数据与存储设计

## 5.1 InfluxDB（时序库）

* **库与保留策略**

  * `marketdata`（保留 60\~180 天）：分钟/小时级行情、盘口快照摘要
  * `ops`（保留 365 天）：系统指标（延迟、队列长度、失败率、PnL、风险事件）
* **测量（measurement）建议**

  * `ohlcv_{tf}`：tags=`exchange,symbol,asset_class`；fields=`open,high,low,close,volume,vwap`
  * `greeks_{tf}`（期权）：`delta, gamma, vega, theta, iv`
  * `ops_metrics`：`latency_ms, dropped_msgs, risk_blocks, fill_ratio`
* **下采样**：用 Influx 任务定时聚合（日/周），提升面板性能。

## 5.2 数据湖（Parquet/Arrow）

* **分区路径**：`market=<cn|us|crypto>/date=YYYY-MM-DD/symbol=<...>/`
* **表类**：

  * `bars_{1m,5m,1h,1d}.parquet`（OHLCV、VWAP、turnover、交易费用估计）
  * `features.parquet`（对齐到 bar 的因子列，含滞后/正交化信息）
  * `labels.parquet`（未来收益/分类标签，严格避免窥探）
  * `events.parquet`（分红、拆股、停牌、涨跌停信息）
* **一致性**：写入前统一**时区=UTC**，在可视化/回测层再按市场日历转换。

## 5.3 Postgres（结构化）

* **表建议**：`instruments`、`trading_calendar`、`experiments`、`models`、`orders`、`fills`、`positions`、`pnl_ledger`、`risk_limits`、`risk_events`。
* 用作**权威账本**与**实验/模型登记**；保证审计可追溯。

---

# 6. 策略研究与回测平台

**框架选择**

* **Backtrader**：简洁、易扩展，适合中低频；自定义成交/滑点/费用模型。
* **Qlib**：强项是**因子/模型流水线、数据日历与评估**；后续可把数据湖映射为 Qlib DataHandler，借力其 Alpha 研究生态。
* （可选）`vectorbt/Polars`：快速指标实验与组合回放。

**关键要点**

* **数据契约一致**：研究/回测/实盘共用同一“预处理与特征工程”模块，回测中仅禁止使用**当前 bar 的未来信息**（滞后处理）。
* **交易成本模型**：按市场分别配置（A股千分比印花税/佣金、涨跌停拒单；美股 SEC/TAF/ECN 费用；Crypto 手续费/ funding/滑点）。
* **风险与资金管理**：在回测中启用与实盘一致的**风控校验器**（仓位限额、单票限额、波动率目标、杠杆上限、相关性约束、行业/风格暴露）。
* **走查机制**：

  * **Walk-Forward**：滚动训练/验证；
  * **时点一致性**：仅使用“上个收盘后可得”的数据训练当日策略；
  * **再平衡频率**：日/周/月；分钟级策略则采用定时窗口。

---

# 7. 实盘交易与风控

## 7.1 统一信号到订单

* **策略引擎输出**：**目标权重/目标持仓**（更稳健）或“买卖信号 + 限价/市价偏好”。
* **风险引擎**：

  * **事前**：

    * 账户层：净敞口、杠杆、行业/因子暴露、单日 VaR、日内预期最大回撤（E-MDD）。
    * 市场层：A股 T+1/涨跌停价检查；美股开盘/收盘/盘前后可成交性；Crypto 持仓与保证金不足检查。
    * 品种层：期权希腊字母阈值（|Δ|、Γ敞口、Vega 暴露）、期货多空/跨期限额。
  * **事中**：

    * 按 bar 更新**波动率目标**（vol targeting）：`target_vol / realized_vol` 自动缩放权重；
    * **风控熔断**：单策略/全局回撤超过阈值、连续拒单/拒成交、延迟飙升等触发**Kill Switch**。
  * **事后**：PnL/因子暴露/成交质量归因（Implementation Shortfall、Fill Ratio、到价率）。

## 7.2 执行与适配

* **execution-router**：

  * 简易 **VWAP/TWAP/POV**（中低频足够）；
  * **节流与速率限制**（遵守券商API额度）；
  * **重试/超时/回滚**：订单状态机（New→Ack→PartFill→Filled/Cancelled/Rejected）。
* **券商/交易所适配器**：

  * `adapter-binance`（加密）、`adapter-ib`（美股/期货/期权）、`adapter-xtp` 或券商私有接口（A股）。
  * 负责**时区、单位、合约ID、精度**规范化；
  * 回推 `executions` 与持仓更新，落 Postgres 账本与 InfluxDB 指标。

---

# 8. 监控、日志与告警

* **指标**（写入 InfluxDB）：

  * 采集延迟、缺失率、去重率；因子计算耗时；回测批次用时；实时链路（信号→风控→下单→回报）的端到端延迟；订单拒绝/撤单率；成交价偏离（IS）；策略与全局 PnL、回撤；Redis Streams 积压量。
* **日志**：Loki 聚合，Promtail 采集；统一结构化字段（`service, market, symbol, order_id, latency_ms, risk_code`）。
* **Grafana 面板**：

  * “实盘指挥台”：订单流转漏斗、成交质量、PnL 曲线、风险暴露仪表；
  * “数据健康页”：采集覆盖、缺失/迟到、连续性、波动率与成交量热力；
  * “系统资源”：CPU/RAM/GPU/容器重启、磁盘与句柄。
* **告警**：

  * **高优**：风控熔断、订单拒绝率飙升、PnL 回撤越界、延迟>阈值、数据中断；
  * **中优**：Streams 积压、适配器断连、训练失败；
  * **低优**：磁盘/对象存储容量临界。

---

# 9. 中低频场景的算法优化与性能调优

**数据/特征层**

* **Polars/Arrow** 代替 pandas 做大表列式计算；
* **Numba** 加速循环（例如自定义指标）；
* **内存映射（mmap）** + Parquet 分区裁剪，避免全量扫描；
* **缓存**：特征计算结果按版本与参数哈希缓存到数据湖；
* **多进程/多任务**：Prefect/Airflow 拆分资产簇并行；

**执行链路**

* **异步 I/O**（Python `asyncio` + `uvloop`）处理行情与下单回报；
* **轻量消息总线**（Redis Streams）保证可回放与背压可见；
* **拆单限速**：将“交易时段×标的×策略”的**请求速率上限**参数化。

**模型层**

* **波动率目标**与**风险平价**（或最小方差）作为顶层配权器，模型仅决定“alpha 分配”；
* **多策略集成**（不同频段/资产/风格）做**相关性约束**与**稀释 idiosyncratic 风险**。

---

# 10. C++ 性能化演进路线（可选）

**边界与协议**

* 先确定 **跨语言消息契约**（建议 FlatBuffers/Cap’n Proto 或 Protobuf + gRPC）。
* 在 Python 与 C++ 间用 **pybind11** 或 gRPC 进程间通讯（后者更稳健）。

**优先迁移模块（从收益高处下刀）**

1. **execution-router 核心**（拆单/撮合仿真/回报状态机）
2. **高吞吐数据管道**（WS 行情解包/规整）
3. **重计算型特征**（如大窗口统计/路径依赖指标）

**部署方式**

* 将 C++ 服务做成独立容器，通过 gRPC 与 Python 服务连接；
* 统一日志与指标导出（OpenTelemetry/自定义 Influx line protocol）。

---

# 11. 市场合规与细则（策略/风控需内置）

* **A股**：T+1、涨跌停、开盘/收盘集合竞价、停牌、科创板/创业板涨跌幅不同；
* **美股**：盘前/盘后流动性差，**Pattern Day Trader 规则**；做空借券成本；
* **Crypto**：永续合约资金费；保证金率、自动减仓/穿仓处理。
* **期权**：希腊暴露与保证金，流动性与跨期/跨品种对冲路径。
* **公司行为**：分红/拆并股/配股统一通过 `events.parquet` 与回测对齐。

---

# 12. 分步实施（零到一落地路线图）

**第 0 步：环境与安全**

* 制定 `.env.template`（API Key、DB 连接、时区），落 Vault/Secrets；
* 建 Docker 网络与持久卷；建立只读服务账号（Grafana→Influx/Postgres）。

**第 1 步：数据最小闭环**

* 启动 `collector-crypto` → InfluxDB `marketdata` → Grafana 简版行情面板；
* 同时批量落地 Parquet（1m/1h/1d），建立 `data_contracts` 文档。

**第 2 步：特征与研究**

* 跑 `feature-engine` 生成 5\~10 个常见技术/量价因子；
* `research-lab` 做 EDA、基线策略（简单动量/均值回归/风险平价）回测；
* 将 Parquet 映射到 Qlib（后续），验证 Alpha360/Alpha158 等基线。

**第 3 步：实盘通道（纸上→仿真）**

* `strategy-engine` 输出目标权重；`risk-engine` 套用静态限额与波动率目标；
* `paper-broker` 全链路回放，验证订单状态机与指标/日志。

**第 4 步：小资金/白名单标的试运行**

* 接一条真实适配器（如 `adapter-binance` 或 IB 纸面账户）；
* 设置**极严风控**（仓位<10%，日亏损/回撤小阈值）与**Kill Switch**；
* 完成“盘中巡检 & 日终对账”Runbook。

**第 5 步：扩市场与完善风控**

* 接入 A股/美股多券商；完善期货/期权希腊暴露控制；
* 丰富 Grafana 面板与告警矩阵；引入 Loki 日志导航。

**第 6 步：性能与稳健性**

* 将热点因子与执行路由下沉至 C++ 服务（如有必要）；
* 压测与混沌演练（断线/迟到/拒单场景）。

---

# 13. 中低频风控配方（可直接落参）

* **资金分配**：波动率目标法（目标年化波动 10%/12%/15% 档），对冲不同策略簇相关性；
* **单票/行业/国家暴露**：单票 ≤ 10% NAV，行业 ≤ 30%，国家 ≤ 60%；
* **杠杆**：总杠杆 ≤ 1.5×（现货+期货净敞口），Crypto 永续单边≤ 0.5× NAV；
* **开仓/加仓节奏**：分批成交（TWAP N 批），价差偏离阈值> x 个 tick 则暂停；
* **止损/减仓**：日内浮亏> y%，或 E-MDD> 阈值触发减仓/平仓；
* **PnL 与成交质量**：Implementation Shortfall、到价率、滑点基准（月度评估/调参）。

---

# 14. 与 Qlib 的整合要点（后续阶段）

* 将数据湖 Parquet 通过**数据适配器**暴露给 Qlib 的 DataHandler（保持**交易日历/对齐/复权**一致）；
* 让 Qlib 负责**因子流水线/模型训练/评估**，训练产物（权重、scaler、特征选择）登记在 Postgres 的 `models`；
* 实盘时 `strategy-engine` 只需加载**最新已冻结的模型版本**与**特征字典**。

---

# 15. “vibe coding” 提示库（直接复制给模型生成骨架）

> **使用方式**：把以下提示喂给你的编码助手，让其生成该模块的目录、配置、自检清单、对接点与测试样例（但你可以暂时不粘贴代码，以便后续自行整合）。

**A. 事件总线与数据契约（common/）**

* “请为一个量化交易系统生成**事件模型契约**与字段校验清单：`Signal`、`OrderIntent`、`Order`、`ExecutionReport`、`RiskEvent`、`NavSnapshot`、`OpsMetric`。要求包含字段名、类型、单位、时区、必填/可空、示例与不变量规则。输出同时给出 FlatBuffers 与 Protobuf 的等价描述草案。”

**B. 采集器（apps/collectors/）**

* “为 `collector-crypto` 生成模块骨架与任务流程：启动→鉴权→订阅→节流→心跳→断线重连→批量落 InfluxDB 与 Parquet。请列出配置项（API Key、symbols、timeframe、batch\_size、max\_lag\_ms、write\_policy）与健康检查项（最近心跳、落库速率、积压）。同时附带数据质量 checks（重复率、缺失率、时间回退）。”

**C. 特征工程（apps/feature\_engine/）**

* “为特征流水线生成 DAG 说明：输入 bars→标准化→缺失处理→技术指标→横截面去极值/中性化→滞后对齐。请输出任务依赖、失败重试策略、产物命名规范与 Parquet 分区设计。”

**D. 回测运行器（apps/backtest\_runner/）**

* “生成一个可批量回测的配置清单：策略参数网格、交易成本模型（A股/美股/Crypto）、撮合规则、资金曲线指标（Sharpe、Sortino、Calmar、HitRate、Turnover、IS）、Walk-Forward 切分方案。要求产出目录结构与实验登记字段（写入 Postgres）。”

**E. 风控引擎（apps/risk\_engine/）**

* “生成事前/事中/事后风控规则表与评估顺序：账户/组合/单票/品种层级，含阈值、操作（拒单/改价/限速/熔断）、审计日志字段。请附上‘A股 T+1/涨跌停’与‘期权希腊暴露’的规则模板。”

**F. 执行路由（apps/execution\_router/）**

* “生成订单状态机与路由/拆单策略说明（TWAP/VWAP/POV 参数），包含失败重试、部分成交合并、最小成交手数、价格保护带与速率限制。请定义与适配器的 gRPC/HTTP 接口字段。”

**G. 券商适配器（apps/adapters/binance|ib|xtp/）**

* “生成适配器抽象接口：下单、撤单、查询、订阅成交回报；定义错误码映射、时区/精度/合约ID 规范化表、健康检查与重连策略。请附上 PaperBroker 的撮合规则说明与如何用它做端到端回归测试。”

**H. 监控与看板（apps/monitoring/ + infra/dashboards/）**

* “列出需要写入 InfluxDB 的业务指标与字段（延迟、拒单率、IS、PnL、E-MDD、Streams 积压、各服务心跳），并为 Grafana 生成 3 个面板布局的 JSON 结构说明（无需具体 JSON），以及 10 条高优先级告警规则（条件/阈值/抑制规则/分派渠道）。”

**I. Qlib 集成（apps/qlib\_service/）**

* “生成 Qlib DataHandler 适配说明：如何把 Parquet 数据湖映射为 Qlib 数据目录；如何在训练/验证/回测过程中保证数据时间一致性与不窥探；如何登记模型版本并冻结为实盘可用的‘工件’。”

**J. C++ 迁移（cpp-services/）**

* “生成 C++ `execution-router` 微服务设计：gRPC IDL、线程模型、内存池、无锁环形队列、撮合仿真与回报回推；给出与 Python 侧互操作的集成测试用例设计（仅说明，不要代码）。”

---

# 16. 风险提示与合规建议（务必执行）

* 确认各数据源与券商 API 的**使用许可**，避免违规抓取；
* 在小资金与白名单标的上**逐步放量**；
* 任何实盘前，至少进行**两周纸面 + 一周小额实盘并行对账**；
* 对**期权与杠杆产品**设置更严格的阈值与自动降风险机制。
