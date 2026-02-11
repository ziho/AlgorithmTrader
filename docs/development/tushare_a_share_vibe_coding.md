# A 股全链路开发说明（给 Copilot / Vibe Coding）

本文件用于指导实现 A 股全链路：数据下载 → 存储 → 因子 → 回测 → 报告 → Web UI 展示。  
目标是一次到位，代码可跑、路径清晰、规则可控。

---

## 目标与边界

### 必做
- 全市场 A 股 **日线数据** 从 2018-01-01 开始一次性回填
- 在选择个股后再补充 **1m** 数据（先不做增量更新）
- 需要数据质量检查
- 需要 A 股回测规则：T+1、涨跌停、最小 100 股、印花税、手续费（默认万三）
- Web UI 增加一个独立 Tab：**A 股数据**
- 回测结果可在 Web UI 查看（不要求复杂交互）

### 不做（当前）
- 自动增量更新
- 多数据库或新的数据库引入
- 实盘接入

---

## 现有框架对接点（必须遵守）

- `src/core/instruments.py` 定义 `Exchange`、`Symbol`
- `src/data/connectors/` 负责数据源接口
- `src/data/storage/parquet_store.py` 负责 OHLCV 存储
- `src/data/quality/validators.py` 可用于质量检查
- `src/backtest/engine.py` 为回测主流程
- `src/execution/slippage_fee.py` 为成本模型
- `services/web/pages/data.py` 是数据管理页（需新增 A 股 Tab）

---

## 数据设计

### 统一 Symbol 规则

- 新增 `Exchange.A_TUSHARE`（或同等清晰命名）
- A 股使用 `Symbol(exchange=A_TUSHARE, base=ts_code, quote=CNY, asset_type=STOCK)`
- `ts_code` 例：`600519.SH`、`000001.SZ`

### Parquet 存储结构

**日线 OHLCV**
```
data/parquet/a_tushare/600519.SH_CNY/1d/year=2024/month=01/data.parquet
```

**分钟 OHLCV（后续）**
```
data/parquet/a_tushare/600519.SH_CNY/1m/year=2024/month=01/data.parquet
```

### 基本面与辅助数据（非 OHLCV）

新建轻量存储（可 Parquet 或 CSV）：
```
data/parquet/a_tushare_fundamentals/
  daily_basic/year=2024/data.parquet
  adj_factor/year=2024/data.parquet
  forecast/year=2024/data.parquet
  fina_indicator/year=2024/data.parquet
```

字段保留原始列名 + 统一 `trade_date` / `ann_date`。

---

## 数据源与接口（Tushare）

### 必用接口
- `trade_cal`：交易日历
- `daily`：OHLCV 日线
- `daily_basic`：市值、换手等
- `adj_factor`：复权因子
- `forecast`：业绩预告
- `fina_indicator`：财务指标

### 下载策略（一次性回填）
- 以 **交易日** 为粒度循环下载（2018-01-01 至当前）
- 每个交易日拉全市场数据：一次调用
- 5000 积分允许高频调用，但仍需限速（例如 200~300 次/分钟）
- 失败重试 + 日志记录

---

## A 股回测规则（必须实现）

### 交易规则
- **T+1**：买入当日不可卖出
- **涨跌停**：  
  - 默认 ±10%  
  - 科创板/创业板 ±20%  
  - ST 股票 ±5%（若能获取 `is_st`）
- **最小交易单位**：100 股
- **手续费**：默认万分之三（0.0003），买卖均收
- **印花税**：0.0005，仅卖出收

### 实现方式建议
新增 `AShareTradingRules`：
- 在回测撮合前判断：
  - 若违反 T+1 或涨跌停，则拒绝成交
  - 买入数量向下取整到 100 的整数倍
- 成本模型：
  - 在 `slippage_fee.py` 中新增 `a_share` 费率配置
  - 在回测成交处额外叠加卖出印花税（可单独函数）

---

## Web UI 要求

在 `services/web/pages/data.py` 的 tabs 中新增：

- Tab 名：`A 股数据`
- 功能：
  - 触发 **全市场日线下载**（按钮）
  - 显示下载进度与完成状态
  - 显示 A 股数据的本地统计（文件数量、时间范围）

不需要复杂交互，不需要实时行情展示。

---

## 任务顺序（严格按此顺序）

1. **数据下载**
   - 新增 `src/data/connectors/tushare.py`
   - 新增 `src/data/fetcher/tushare_history.py`
   - 支持 trade_date 批量下载

2. **存储**
   - 复用 `ParquetStore` 保存日线 OHLCV
   - 新增简易存储类保存 daily_basic/adj_factor/forecast/fina_indicator

3. **因子**
   - 新增 `src/features/a_share_factors.py`
   - 只保留可复用、高价值因子（去掉冗余逻辑）

4. **回测**
   - 在 `src/backtest/engine.py` 引入 A 股交易规则判断
   - 增加 `A_TUSHARE` 成本模型

5. **报告**
   - 复用现有报告输出
   - 报告中显示交易成本分解（含印花税）

6. **Web UI**
   - 新增 A 股数据 Tab
   - 显示数据统计与下载状态

---

## 需要新增/修改的文件清单

新增：
- `src/data/connectors/tushare.py`
- `src/data/fetcher/tushare_history.py`
- `src/data/storage/a_share_store.py`（或 `fundamentals_store.py`）
- `src/features/a_share_factors.py`
- `docs/development/tushare_a_share_vibe_coding.md`（本文件）

修改：
- `src/core/instruments.py`（新增 Exchange）
- `src/core/config/settings.py`（新增 TushareSettings）
- `src/backtest/engine.py`（A 股规则挂载）
- `src/execution/slippage_fee.py`（A 股费用与印花税）
- `services/web/pages/data.py`（新增 A 股 Tab）

---

## 关键实现细节（避免踩坑）

- **时间戳**：Tushare `trade_date` 是日期字符串，需转为 UTC 时间戳。  
  建议以 `Asia/Shanghai 00:00` 转 UTC 存储。

- **交易日历**：必须用 `trade_cal` 过滤非交易日，避免伪缺口。

- **数据质量检查**：
  - 缺口检测：按交易日而非自然日
  - OHLC 合法性校验

- **涨跌停判断**：
  - 以昨收价为基准计算涨跌停价  
  - 若当前开盘价触及涨停且为买入 → 拒绝成交  
  - 若当前开盘价触及跌停且为卖出 → 拒绝成交

---

## 验收标准

- 能完成 2018-01-01 至今全市场日线回填
- Parquet 文件按交易所/股票/时间框架正确落盘
- 基本面数据落盘并可读取
- 回测中严格执行 T+1、涨跌停、手续费、印花税
- Web UI 有独立 A 股 Tab，可触发下载并看到统计
- 文档 `docs/KNOWN_LIMITATIONS.md` 更新 A 股完成度

---

## 开发提示（Copilot 关键点）

- 不要做增量更新逻辑
- 不要引入新数据库
- 如果接口字段不够，宁可多拉原始字段保存
- 重要规则写成独立函数，不要散在引擎里

