# Tushare A股数据接入方案（初稿）

> **状态**：初稿 / 待讨论  
> **日期**：2026-02-10  
> **参考**：`third-party/crazy_big_A/kunup_composite_factor_select.ipynb`

---

## 1. 背景

当前 AlgorithmTrader 支持 Binance / OKX 两个加密货币交易所。架构上已预留了 `AssetType.STOCK`、`Exchange.IBKR` 等扩展点，但尚未有 A 股数据的实际实现。

`kunup_composite_factor_select.ipynb` 展示了一套基于 Tushare Pro API 的复合因子选股流程：
- 使用 `pro.daily()` / `pro.daily_basic()` / `pro.forecast()` 逐日拉取数据
- 计算因子：KDJ 月度、MA60/120 多头、涨跌幅区间筛选、业绩预增、市值等
- 严格避免未来信息（只用 `ann_date <= trade_date` 的数据）
- 输出 `(trade_date, ts_code, factor_1, ..., factor_N, univ)` 面板

---

## 2. Notebook 分析（kunup_composite_factor_select.ipynb）

### 2.1 数据源与 API 调用

| 接口 | 字段 | 用途 | 频率限制 |
|------|------|------|----------|
| `pro.trade_cal()` | 交易日历 | 确定开盘日 | 低频 |
| `pro.daily(trade_date=dt)` | OHLCV + 复权因子 | 日线行情 | ~200 次/分钟 |
| `pro.daily_basic(trade_date=dt)` | `total_mv` (总市值) | 市值筛选 | ~200 次/分钟 |
| `pro.forecast(ann_date=dt)` | 业绩预告 | 年报预增筛选 | ~200 次/分钟 |

**关键问题**：
- Notebook 按逐日拉取（`for dt in trade_dates`），8 年 × ~250 交易日 = **~2000 次 API 调用**，仅 daily 接口就需 ~11 分钟
- Tushare Pro 的权限等级决定了可调用的接口和频率（200 次/分钟需 2000 积分以上）

### 2.2 因子计算逻辑

| 因子 | 说明 | 所需数据 |
|------|------|----------|
| `kdj_month_up` | 月度 KDJ 向上 | OHLCV（日线） |
| `ma60_120_bull` | MA60 > MA120 多头排列 | Close（日线） |
| `ret_1m_0_50` | 1 月涨幅 0%~50% | Close |
| `ret_2m_positive` | 2 月涨幅 > 0 | Close |
| `ret_15_10_above_minus10` | 15 日 / 10 日跌幅 > -10% | Close |
| `ret_4_3_2_below_20` | 4/3/2 日涨幅 < 20% | Close |
| `has_1day_up5_in_6m` | 半年内至少 1 日涨幅 > 5% | Daily Return |
| `has_neg_day_in_4d` | 最近 4 日至少 1 日跌 | Daily Return |
| `earnings_annual_pre_inc` | 年报业绩预增 | `forecast` 接口 |
| `cap_above_50y` | 总市值 > 50 亿 | `daily_basic` 接口 |

### 2.3 Notebook 的局限

1. **逐日 API 调用效率极低** — Tushare 也支持按 `ts_code` 拉取全量历史，效率高得多
2. **无增量更新** — 每次全量拉取，无断点续传
3. **无本地缓存管理** — 只有简单的 CSV 文件缓存
4. **无事件驱动** — 只输出静态面板，未与信号/回测引擎对接

---

## 3. 接入方案设计

### 3.1 架构位置

```
src/
├── core/
│   └── instruments.py     ← 新增 Exchange.SSE / Exchange.SZSE
├── data/
│   ├── connectors/
│   │   └── tushare.py     ← 新增 TushareConnector（日线/分钟线/基本面）
│   ├── fetcher/
│   │   └── tushare_history.py  ← 新增历史数据批量下载器
│   ├── storage/
│   │   └── parquet_store.py    ← 复用（A 股数据也存 Parquet）
│   └── pipelines/
│       └── a_share.py     ← 因子计算 Pipeline（KDJ/MA/涨跌幅等）
├── features/
│   └── a_share_factors.py ← 复合因子选股 Feature 模块
└── core/config/
    └── settings.py        ← 新增 TushareSettings
```

### 3.2 数据获取策略

**方案 A：按股票拉取全量历史（推荐）**
```python
# 更高效：一次调用获取单股全部历史
pro.daily(ts_code='000001.SZ', start_date='20180101', end_date='20260206')
```
- 优点：API 调用次数 = 股票数（~5000），远少于 按日期 × 全市场
- 缺点：首次全量拉取耗时较长

**方案 B：按日期拉取全市场**（Notebook 当前方式）
- 优点：每日增量只需 1 次调用
- 缺点：首次回填需 ~2000 次调用

**建议**：首次按股票全量拉取 → 之后每日增量按日期拉取（类似 Binance 的 HistoryFetcher 模式）

### 3.3 存储格式

复用现有 Parquet 分区方案，但需要调整路径:
```
data/parquet/
├── binance/
│   └── BTC_USDT/1h/year=2024/month=01/data.parquet
├── sse/                    ← A 股上交所
│   └── 600519_CNY/1d/year=2024/month=01/data.parquet
└── szse/                   ← A 股深交所
    └── 000001_CNY/1d/year=2024/month=01/data.parquet
```

### 3.4 配置

```python
# .env
TUSHARE_TOKEN=your_tushare_pro_token
TUSHARE_RATE_LIMIT=200          # 每分钟最大调用次数
TUSHARE_DOWNLOAD_SYMBOLS=600519.SH,000001.SZ,000858.SZ  # 默认下载列表
TUSHARE_DOWNLOAD_TIMEFRAMES=D   # 日线
```

---

## 4. 实现路线图

### Phase 1：数据层（2-3 天）
- [ ] `src/data/connectors/tushare.py` — Tushare 连接器
- [ ] `src/data/fetcher/tushare_history.py` — 历史数据下载（断点续传 + 增量更新）
- [ ] `src/core/instruments.py` — 新增 `Exchange.SSE`, `Exchange.SZSE`
- [ ] `src/core/config/settings.py` — 新增 `TushareSettings`
- [ ] Parquet 存储适配

### Phase 2：因子层（2-3 天）
- [ ] `src/features/a_share_factors.py` — 从 Notebook 迁移因子计算逻辑
- [ ] `src/data/pipelines/a_share.py` — Raw → Curated → Features Pipeline
- [ ] 基本面数据获取（daily_basic, forecast）

### Phase 3：Web UI 集成（1 天）
- [ ] 数据管理页 — 支持 Tushare 数据源下载
- [ ] 策略配置 — 支持 A 股策略
- [ ] 设置页 — Tushare Token 配置

### Phase 4：策略与回测（2-3 天）
- [ ] 将 Notebook 的选股逻辑封装为 `Strategy` 子类
- [ ] 对接回测引擎（`BacktestEngine` 已支持通用 OHLCV）
- [ ] 回测报告适配 A 股（人民币、交易费率、T+1 规则）

---

## 5. 需要确认的问题

> **请直接在每个问题下方编辑回复，然后我会根据你的回答进行开发。**

### Q1：Tushare Pro 积分等级

你的 Tushare Pro 账户积分是多少？这决定了：
- 200 积分：daily 接口，每分钟 200 次
- 2000 积分：daily_basic、forecast、分钟线等
- 5000 积分：更多高级接口

**你的积分等级**：5000积分

---

### Q2：数据范围

需要覆盖哪些数据？

- **时间范围**：从哪年开始？（Notebook 用 2018-01-01 起）就2018年1月1日开始
- **股票范围**：a 全市场
  - (a) 全市场 ~5000 只？
  - (b) 沪深 300 成分股？
  - (c) 自定义列表？
  - (d) 其他（请说明）
- **时间周期**：只要日线 (D)？还是也需要分钟线 (1min / 5min / 15min)？1min 线
- **除 OHLCV 外是否需要**：都需要
  - [x] 总市值 / 流通市值（daily_basic）
  - [x] 业绩预告（forecast）
  - [x] 财务指标（fina_indicator）
  - [x] 复权因子（adj_factor）
  - [ ] 其他（请说明）

**你的回答**：

---

### Q3：与 Notebook 选股策略的关系

对于 `kunup_composite_factor_select.ipynb` 中的选股策略：

- (a) 只做数据层接入，因子计算保持 Notebook 独立运行
- (b) 把因子计算迁移到 AlgorithmTrader 的 Features 层，支持回测
- (c) 把整个选股逻辑封装成 Strategy 子类，接入回测引擎 + 实盘
- (d) 其他（请说明）

**你的选择**：我的理解是 b 因为我不需要实盘，我只需要回测，如果我有错，纠正我

---

### Q4：Exchange 粒度

A 股接入时使用哪种 Exchange 标识？

- (a) `Exchange.SSE` + `Exchange.SZSE` — 区分上交所和深交所
- (b) `Exchange.TUSHARE` — 统一用 Tushare 作为数据源标识（推荐，因为 Tushare 的 `ts_code` 已包含 `.SH` / `.SZ` 后缀）
- (c) `Exchange.A_SHARE` — 统一标识
- (d) 其他

**你的选择**：怎么方便怎么来

---

### Q5：T+1 和交易费率

A 股特有的规则需要在回测引擎中特殊处理：

- **T+1 规则**：当日买入不能当日卖出
- **涨跌停限制**：±10% (主板) / ±20% (创业板/科创板)
- **交易费率**：佣金 ~0.025%、印花税 0.05%（仅卖出）、过户费 0.001%
- **最小交易单位**：100 股（1 手）

你是否需要在回测引擎中实现这些规则？
- (a) 是，需要完整的 A 股交易规则
- (b) 暂时不需要，先简单回测
- (c) 部分需要（请说明哪些）

**你的回答**：a 需要完整A股规则

---

### Q6：数据更新频率

A 股数据的更新频率需求：

- (a) 手动触发（Web UI 上点击下载）
- (b) 每日自动更新（收盘后定时同步）
- (c) 两者都要
- (d) 暂时只需要一次性历史回填

**你的选择**：d 暂时只需要一次性，后续可以考虑 每日更新

---

### Q7：优先级

以下哪个是最优先要做的？

- (a) 先跑通数据接入 → 能在本地查看 A 股日线数据
- (b) 先跑通因子计算 → 能复现 Notebook 的选股结果
- (c) 先跑通回测 → 能回测 A 股策略
- (d) 全部一起做

**你的选择**：d

---

## 6. 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Tushare API 频率限制 | 全量拉取耗时长 | 分批拉取 + 本地缓存 + 断点续传 |
| Tushare 数据质量 | 可能有缺失/异常值 | 对接 `src/data/quality/` 质量检查 |
| Tushare token 过期 | API 调用失败 | 配置文件 + 环境变量 + 重试机制 |
| A 股复权处理 | 因子计算需要前/后复权 | Tushare 提供 `adj_factor`，需统一处理方式 |
| 全市场数据量大 | ~5000 只 × 8 年 × 250 天 ≈ 1000 万行 | Parquet 分区 + DuckDB 查询 |
| 基本面数据与行情数据关联 | 需要严格按公告日关联 | 参考 Notebook 的 `ann_date <= trade_date` 逻辑 |

---

## 7. 备注

- 现有 AlgorithmTrader 的 **Parquet 存储、回测引擎、Web UI** 都可以复用
- `src/core/instruments.py` 已有 `AssetType.STOCK`，适配成本低
- 没有抽象的 Connector 接口（Binance/OKX 各自独立实现），可以考虑是否引入 ABC
- Notebook 中 KDJ / MA 等技术指标计算可以直接迁移，复杂度不高
