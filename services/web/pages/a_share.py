"""
A 股数据分析页面 (A-Share / Tushare)

功能:
- 选股筛选: 全市场截面因子排名，多维度筛选
- 个股分析: OHLCV K 线图 + 因子时序图
- 数据下载: 全市场日线/基本面一键回填
- 本地数据: 数据统计与健康检查

路由: /a-share
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from nicegui import ui

from src.ops.logging import get_logger

logger = get_logger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def render():
    """渲染 A 股数据分析页面"""
    ui.label("A 股数据分析").classes("text-2xl font-bold mb-2")

    with ui.row().classes("w-full items-center gap-2 mb-2"):
        ui.icon("info").classes("text-blue-400 text-sm")
        ui.label(
            "基于 Tushare 数据源的 A 股全链路：数据下载 → 选股筛选 → 个股分析 → 因子可视化。"
            "首次使用请先在「数据下载」标签页完成全市场日线回填。"
        ).classes("text-gray-500 text-sm")

    # 顶部数据概览
    overview_row = ui.row().classes("w-full gap-4 flex-wrap mb-2")
    _render_quick_overview(overview_row)

    # Tab
    with ui.tabs().classes("w-full mt-2") as tabs:
        screening_tab = ui.tab("选股筛选")
        stock_tab = ui.tab("个股分析")
        download_tab = ui.tab("数据下载")
        stats_tab = ui.tab("本地数据")

    with ui.tab_panels(tabs, value=screening_tab).classes("w-full"):
        with ui.tab_panel(screening_tab):
            _render_screening_panel()

        with ui.tab_panel(stock_tab):
            _render_stock_analysis_panel()

        with ui.tab_panel(download_tab):
            _render_download_panel()

        with ui.tab_panel(stats_tab):
            _render_stats_panel()


# ============================================
# 顶部数据概览
# ============================================


def _render_quick_overview(container):
    """快速数据概览卡片"""

    async def load_overview():
        container.clear()
        with container:
            try:
                from src.data.fetcher.tushare_history import TushareHistoryFetcher

                fetcher = TushareHistoryFetcher(data_dir=PROJECT_ROOT / "data")
                stats = await asyncio.get_event_loop().run_in_executor(
                    None, fetcher.get_local_stats
                )
                await fetcher.close()

                stock_count = stats.get("stock_count", 0)
                file_count = stats.get("file_count", 0)
                size_mb = stats.get("total_size_mb", 0.0)
                fund_types = len(stats.get("fundamentals", {}))

                with ui.card().classes("card flex-1 min-w-36 p-3"):
                    ui.label("股票数量").classes("text-xs text-gray-500")
                    ui.label(f"{stock_count:,}").classes("text-lg font-bold")

                with ui.card().classes("card flex-1 min-w-36 p-3"):
                    ui.label("数据文件").classes("text-xs text-gray-500")
                    ui.label(f"{file_count:,}").classes("text-lg font-bold")

                with ui.card().classes("card flex-1 min-w-36 p-3"):
                    ui.label("磁盘占用").classes("text-xs text-gray-500")
                    if size_mb >= 1024:
                        ui.label(f"{size_mb / 1024:.2f} GB").classes(
                            "text-lg font-bold"
                        )
                    else:
                        ui.label(f"{size_mb:.1f} MB").classes("text-lg font-bold")

                with ui.card().classes("card flex-1 min-w-36 p-3"):
                    ui.label("基本面数据").classes("text-xs text-gray-500")
                    ui.label(f"{fund_types} 类").classes("text-lg font-bold")

                tushare_ok = _check_tushare_available()
                with ui.card().classes("card flex-1 min-w-36 p-3"):
                    ui.label("Tushare 状态").classes("text-xs text-gray-500")
                    if tushare_ok:
                        ui.label("✅ 已连接").classes("text-lg font-bold text-green-600")
                    else:
                        ui.label("❌ 未配置").classes("text-lg font-bold text-red-500")

            except Exception as e:
                with ui.card().classes("card w-full p-3"):
                    ui.label(f"⚠️ 概览加载失败: {e}").classes("text-yellow-600 text-sm")

    from services.web.utils import safe_timer

    safe_timer(0.3, load_overview, once=True)


def _check_tushare_available() -> bool:
    """检查 Tushare 是否可用"""
    try:
        from src.core.config import get_settings

        settings = get_settings()
        return settings.tushare.enabled
    except Exception:
        return False


# ============================================
# 选股筛选
# ============================================


def _render_screening_panel():
    """选股筛选面板 — 截面因子排名"""
    with ui.card().classes("card w-full"):
        ui.label("📊 选股筛选").classes("text-lg font-medium mb-2")
        ui.label(
            "基于因子截面排名，快速筛选全市场 A 股。"
            "需要先下载 daily 和 daily_basic 数据才能使用。"
        ).classes("text-gray-500 text-sm mb-4")

        with ui.row().classes("gap-4 flex-wrap items-end"):
            # 筛选日期
            date_input = (
                ui.input(
                    label="筛选日期",
                    value=_get_latest_trade_date(),
                )
                .classes("min-w-40")
                .props("outlined dense")
            )
            with ui.menu().props("no-parent-event") as date_menu:
                with ui.date(mask="YYYYMMDD").bind_value(date_input):
                    with ui.row().classes("justify-end"):
                        ui.button("确定", on_click=date_menu.close).props("flat")
            with date_input.add_slot("append"):
                ui.icon("event").on("click", date_menu.open).classes("cursor-pointer")

            # 排序因子
            rank_select = (
                ui.select(
                    {
                        "total_mv": "总市值",
                        "circ_mv": "流通市值",
                        "turnover_rate": "换手率",
                        "pe_ttm": "市盈率(TTM)",
                        "pb": "市净率",
                        "ps_ttm": "市销率(TTM)",
                        "volume_ratio": "量比",
                    },
                    value="total_mv",
                    label="排序因子",
                )
                .classes("min-w-40")
                .props("outlined dense")
            )

            # 排序方向
            order_select = (
                ui.select(
                    {"asc": "升序 (小→大)", "desc": "降序 (大→小)"},
                    value="desc",
                    label="排序方向",
                )
                .classes("min-w-36")
                .props("outlined dense")
            )

            # 市场板块过滤
            market_select = (
                ui.select(
                    {
                        "all": "全部",
                        "main": "主板",
                        "gem": "创业板(3xx)",
                        "star": "科创板(688)",
                        "bse": "北交所(8xx/4xx)",
                    },
                    value="all",
                    label="板块筛选",
                )
                .classes("min-w-36")
                .props("outlined dense")
            )

            # 条数限制
            limit_select = (
                ui.select(
                    {"50": "Top 50", "100": "Top 100", "200": "Top 200", "500": "Top 500"},
                    value="100",
                    label="显示条数",
                )
                .classes("min-w-28")
                .props("outlined dense")
            )

            search_btn = ui.button("查询", icon="search").props("color=primary")

        # 结果表格
        result_container = ui.column().classes("w-full mt-4")

        async def do_screening():
            result_container.clear()
            with result_container:
                with ui.row().classes("justify-center py-4"):
                    ui.spinner("dots")
                    ui.label("正在查询全市场数据...").classes("text-gray-400 ml-2")

            try:
                trade_date = date_input.value.replace("-", "")
                rank_by = rank_select.value
                ascending = order_select.value == "asc"
                market = market_select.value
                limit = int(limit_select.value)

                # 从本地数据读取
                rows = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _screening_query(
                        trade_date, rank_by, ascending, market, limit
                    ),
                )

                result_container.clear()
                with result_container:
                    if rows is None or len(rows) == 0:
                        with ui.column().classes("items-center py-6"):
                            ui.icon("search_off").classes("text-4xl text-gray-300")
                            ui.label("未找到数据").classes("text-gray-400 mt-2")
                            ui.label(
                                f"请确认 {trade_date} 是否已下载 daily_basic 数据"
                            ).classes("text-gray-400 text-sm")
                        return

                    ui.label(
                        f"📋 {trade_date} · {_factor_label(rank_by)} · "
                        f"共 {len(rows)} 条"
                    ).classes("text-sm text-gray-500 mb-2")

                    # 构建表格
                    columns = [
                        {"name": "rank", "label": "#", "field": "rank", "align": "center", "sortable": True},
                        {"name": "ts_code", "label": "代码", "field": "ts_code", "align": "left", "sortable": True},
                        {"name": "name", "label": "名称", "field": "name", "align": "left", "sortable": True},
                        {"name": "close", "label": "收盘价", "field": "close", "align": "right", "sortable": True},
                        {"name": "pct_chg", "label": "涨跌幅%", "field": "pct_chg", "align": "right", "sortable": True},
                        {"name": "value", "label": _factor_label(rank_by), "field": "value", "align": "right", "sortable": True},
                        {"name": "total_mv", "label": "总市值(亿)", "field": "total_mv", "align": "right", "sortable": True},
                        {"name": "turnover_rate", "label": "换手率%", "field": "turnover_rate", "align": "right", "sortable": True},
                        {"name": "pe_ttm", "label": "PE(TTM)", "field": "pe_ttm", "align": "right", "sortable": True},
                    ]

                    table = ui.table(
                        columns=columns,
                        rows=rows,
                        row_key="ts_code",
                        pagination={"rowsPerPage": 50, "sortBy": "rank"},
                    ).classes("w-full").props("dense flat bordered")

                    # 允许搜索
                    table.add_slot(
                        "top-right",
                        '''
                        <q-input borderless dense debounce="300" v-model="props.filter"
                                 placeholder="搜索代码/名称">
                            <template v-slot:append>
                                <q-icon name="search" />
                            </template>
                        </q-input>
                        ''',
                    )
                    table.props('filter=""')

            except Exception as e:
                result_container.clear()
                with result_container:
                    ui.label(f"❌ 查询失败: {e}").classes("text-red-500 text-sm")
                logger.error("screening_error", error=str(e))

        search_btn.on_click(do_screening)

    # 实时行情面板 (从Tushare获取)
    _render_live_market_snapshot()


def _screening_query(
    trade_date: str,
    rank_by: str,
    ascending: bool,
    market: str,
    limit: int,
) -> list[dict]:
    """
    执行选股查询 (同步, 在线程中运行)

    从 daily_basic + daily 本地Parquet读取
    """
    try:
        from src.data.storage.a_share_store import AShareFundamentalsStore

        store = AShareFundamentalsStore(
            PROJECT_ROOT / "data" / "parquet" / "a_tushare_fundamentals"
        )

        # 读取该日 daily_basic
        daily_basic = store.read(
            "daily_basic",
            start_date=trade_date,
            end_date=trade_date,
        )

        if daily_basic.empty:
            return []

        # 过滤有效数据
        if rank_by not in daily_basic.columns:
            return []

        df = daily_basic.dropna(subset=[rank_by]).copy()

        # 板块过滤
        if market != "all":
            df = _filter_by_market(df, market)

        if df.empty:
            return []

        # 排序
        df = df.sort_values(rank_by, ascending=ascending)

        # 取 top N
        df = df.head(limit)

        # 排名
        df = df.reset_index(drop=True)
        df["rank"] = range(1, len(df) + 1)

        # 尝试拼接股票名称 (从 stock_basic 缓存)
        name_map = _get_stock_name_map()

        # 构建前端行数据
        rows = []
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code", ""))
            close_val = row.get("close", row.get("trade_close", None))
            pct_chg = row.get("pct_chg", None)
            total_mv = row.get("total_mv", None)
            turnover_rate = row.get("turnover_rate", None)
            pe_ttm = row.get("pe_ttm", None)
            value = row.get(rank_by, None)

            rows.append({
                "rank": int(row["rank"]),
                "ts_code": ts_code,
                "name": name_map.get(ts_code, ""),
                "close": _fmt_num(close_val, 2),
                "pct_chg": _fmt_num(pct_chg, 2),
                "value": _fmt_num(value, 2),
                "total_mv": _fmt_num(total_mv / 10000 if total_mv else None, 2),  # 万→亿
                "turnover_rate": _fmt_num(turnover_rate, 2),
                "pe_ttm": _fmt_num(pe_ttm, 2),
            })

        return rows

    except Exception as e:
        logger.error("screening_query_error", error=str(e))
        return []


def _filter_by_market(df, market: str):
    """按板块过滤"""
    if "ts_code" not in df.columns:
        return df

    codes = df["ts_code"].astype(str)
    if market == "main":
        # 主板: 60xxxx.SH, 000xxx.SZ, 001xxx.SZ
        mask = codes.str.match(r"^(6\d{5}\.SH|00[01]\d{3}\.SZ)")
    elif market == "gem":
        # 创业板: 3xxxxx.SZ
        mask = codes.str.startswith("3") & codes.str.endswith(".SZ")
    elif market == "star":
        # 科创板: 688xxx.SH
        mask = codes.str.startswith("688")
    elif market == "bse":
        # 北交所: 8xxxxx, 4xxxxx
        mask = codes.str.match(r"^[48]\d{5}\.")
    else:
        return df

    return df[mask]


# 股票名称缓存
_STOCK_NAME_CACHE: dict[str, str] = {}


def _get_stock_name_map() -> dict[str, str]:
    """获取股票代码→名称映射 (缓存)"""
    global _STOCK_NAME_CACHE
    if _STOCK_NAME_CACHE:
        return _STOCK_NAME_CACHE

    try:
        # 尝试从本地缓存文件读取
        cache_path = PROJECT_ROOT / "data" / "parquet" / "a_tushare_meta" / "stock_basic.parquet"
        if cache_path.exists():
            import pandas as pd
            basic_df = pd.read_parquet(cache_path)
            if "ts_code" in basic_df.columns and "name" in basic_df.columns:
                _STOCK_NAME_CACHE = dict(
                    zip(basic_df["ts_code"].astype(str), basic_df["name"].astype(str))
                )
                return _STOCK_NAME_CACHE
    except Exception:
        pass

    return _STOCK_NAME_CACHE


async def _fetch_and_cache_stock_basic():
    """异步获取并缓存股票基本信息"""
    global _STOCK_NAME_CACHE
    try:
        from src.data.connectors.tushare import TushareConnector

        async with TushareConnector() as conn:
            df = await conn.fetch_stock_basic()
            if not df.empty:
                # 缓存到内存
                _STOCK_NAME_CACHE = dict(
                    zip(df["ts_code"].astype(str), df["name"].astype(str))
                )
                # 缓存到文件
                cache_dir = PROJECT_ROOT / "data" / "parquet" / "a_tushare_meta"
                cache_dir.mkdir(parents=True, exist_ok=True)
                df.to_parquet(cache_dir / "stock_basic.parquet", index=False)
                logger.info("stock_basic_cached", count=len(df))
                return df
    except Exception as e:
        logger.warning("stock_basic_fetch_error", error=str(e))
    return None


def _render_live_market_snapshot():
    """实时市场快照 — 从 Tushare 获取最新行情概览"""
    with ui.card().classes("card w-full mt-4"):
        with ui.row().classes("justify-between items-center mb-2"):
            ui.label("🏪 市场概览").classes("text-lg font-medium")
            refresh_btn = ui.button("刷新股票列表", icon="refresh").props("flat dense")

        snapshot_container = ui.column().classes("w-full")

        async def load_snapshot():
            snapshot_container.clear()
            with snapshot_container:
                with ui.row().classes("justify-center py-3"):
                    ui.spinner("dots")
                    ui.label("正在加载股票列表...").classes("text-gray-400 ml-2")

            try:
                df = await _fetch_and_cache_stock_basic()
                snapshot_container.clear()
                with snapshot_container:
                    if df is None or df.empty:
                        ui.label("⚠️ 无法获取股票列表（请检查 TUSHARE_TOKEN）").classes(
                            "text-yellow-600 text-sm"
                        )
                        return

                    # 统计
                    total = len(df)
                    sh_count = len(df[df["ts_code"].str.endswith(".SH")])
                    sz_count = len(df[df["ts_code"].str.endswith(".SZ")])
                    bj_count = len(df[df["ts_code"].str.endswith(".BJ")])

                    with ui.row().classes("gap-6 flex-wrap mb-4"):
                        ui.label(f"📈 上市股票总数: {total:,}").classes("font-medium")
                        ui.label(f"上交所: {sh_count:,}").classes("text-gray-500")
                        ui.label(f"深交所: {sz_count:,}").classes("text-gray-500")
                        if bj_count > 0:
                            ui.label(f"北交所: {bj_count:,}").classes("text-gray-500")

                    # 按行业分布
                    if "industry" in df.columns:
                        industry_counts = (
                            df["industry"]
                            .value_counts()
                            .head(20)
                            .reset_index()
                        )
                        industry_counts.columns = ["industry", "count"]

                        ui.label("行业分布 (Top 20)").classes(
                            "font-medium text-gray-600 dark:text-gray-300 mt-2 mb-2"
                        )

                        ind_rows = [
                            {
                                "id": str(i),
                                "industry": str(row["industry"]),
                                "count": str(row["count"]),
                            }
                            for i, row in industry_counts.iterrows()
                        ]

                        ui.table(
                            columns=[
                                {"name": "industry", "label": "行业", "field": "industry", "align": "left"},
                                {"name": "count", "label": "上市公司数", "field": "count", "align": "right"},
                            ],
                            rows=ind_rows,
                            row_key="id",
                        ).classes("w-full max-w-xl").props("dense flat bordered")

            except Exception as e:
                snapshot_container.clear()
                with snapshot_container:
                    ui.label(f"⚠️ 加载失败: {e}").classes("text-yellow-600 text-sm")

        refresh_btn.on_click(load_snapshot)
        from services.web.utils import safe_timer

        safe_timer(0.5, load_snapshot, once=True)


# ============================================
# 个股分析
# ============================================


def _render_stock_analysis_panel():
    """个股分析面板 — K 线图 + 因子"""
    with ui.card().classes("card w-full"):
        ui.label("📈 个股分析").classes("text-lg font-medium mb-2")
        ui.label("输入股票代码查看 K 线走势与因子数据。需要先下载对应股票的日线数据。").classes(
            "text-gray-500 text-sm mb-4"
        )

        with ui.row().classes("gap-4 flex-wrap items-end"):
            ts_code_input = (
                ui.input(
                    label="股票代码",
                    value="600519.SH",
                    placeholder="例: 600519.SH",
                )
                .classes("min-w-40")
                .props("outlined dense")
            )

            # 时间范围
            period_select = (
                ui.select(
                    {
                        "3m": "近 3 个月",
                        "6m": "近 6 个月",
                        "1y": "近 1 年",
                        "2y": "近 2 年",
                        "all": "全部",
                    },
                    value="6m",
                    label="时间范围",
                )
                .classes("min-w-32")
                .props("outlined dense")
            )

            # 因子叠加
            factor_select = (
                ui.select(
                    {
                        "none": "不显示因子",
                        "momentum_20": "动量(20日)",
                        "volatility_20": "波动率(20日)",
                        "price_volume_div": "量价背离",
                        "turnover_ma_20": "换手率MA20",
                        "pe_ttm": "市盈率TTM",
                        "total_mv": "总市值",
                    },
                    value="none",
                    label="叠加因子",
                )
                .classes("min-w-40")
                .props("outlined dense")
            )

            analyze_btn = ui.button("分析", icon="analytics").props("color=primary")

        # 图表区域
        chart_container = ui.column().classes("w-full mt-4")

        async def do_analysis():
            chart_container.clear()
            with chart_container:
                with ui.row().classes("justify-center py-4"):
                    ui.spinner("dots")
                    ui.label("正在加载数据并生成图表...").classes("text-gray-400 ml-2")

            try:
                ts_code = ts_code_input.value.strip().upper()
                period = period_select.value
                factor_name = factor_select.value

                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _load_stock_data(ts_code, period, factor_name),
                )

                chart_container.clear()
                with chart_container:
                    if result is None:
                        with ui.column().classes("items-center py-6"):
                            ui.icon("error_outline").classes("text-4xl text-gray-300")
                            ui.label(f"未找到 {ts_code} 的数据").classes(
                                "text-gray-400 mt-2"
                            )
                            ui.label(
                                "请确认股票代码正确且已下载日线数据"
                            ).classes("text-gray-400 text-sm")
                        return

                    ohlcv_data = result["ohlcv"]
                    stock_name = result.get("name", ts_code)
                    factor_data = result.get("factor")
                    basic_info = result.get("basic_info")

                    # 股票基本信息
                    if basic_info:
                        with ui.row().classes("gap-6 flex-wrap mb-2 items-center"):
                            ui.label(f"📌 {ts_code} {stock_name}").classes(
                                "font-medium text-lg"
                            )
                            if "industry" in basic_info:
                                ui.badge(basic_info["industry"]).props("color=blue outline")
                            if "market" in basic_info:
                                ui.badge(basic_info["market"]).props("color=grey outline")

                    # 最新价格信息
                    if len(ohlcv_data) > 0:
                        last = ohlcv_data[-1]
                        prev = ohlcv_data[-2] if len(ohlcv_data) > 1 else last
                        change_pct = (
                            (last["close"] - prev["close"]) / prev["close"] * 100
                            if prev["close"] != 0
                            else 0
                        )
                        color = (
                            "text-red-600"
                            if change_pct > 0
                            else "text-green-600"
                            if change_pct < 0
                            else "text-gray-500"
                        )

                        with ui.row().classes("gap-6 flex-wrap mb-4 items-baseline"):
                            ui.label(f"¥{last['close']:.2f}").classes(
                                f"text-2xl font-bold {color}"
                            )
                            sign = "+" if change_pct > 0 else ""
                            ui.label(f"{sign}{change_pct:.2f}%").classes(
                                f"text-base {color}"
                            )
                            ui.label(
                                f"最高 {last['high']:.2f} · 最低 {last['low']:.2f} · "
                                f"成交量 {last['volume']:,.0f}"
                            ).classes("text-sm text-gray-500")

                    # K线图 (用 ECharts)
                    _render_candlestick_chart(ohlcv_data, ts_code, stock_name, factor_data, factor_name)

                    # 数据统计
                    _render_stock_data_stats(ohlcv_data, ts_code)

            except Exception as e:
                chart_container.clear()
                with chart_container:
                    ui.label(f"❌ 分析失败: {e}").classes("text-red-500 text-sm")
                logger.error("stock_analysis_error", error=str(e))

        analyze_btn.on_click(do_analysis)


def _load_stock_data(
    ts_code: str,
    period: str,
    factor_name: str,
) -> dict | None:
    """加载个股数据 (同步, 线程中运行)"""
    import pandas as pd

    from src.core.instruments import AssetType, Exchange, Symbol
    from src.core.timeframes import Timeframe
    from src.data.storage.parquet_store import ParquetStore

    symbol = Symbol(
        exchange=Exchange.A_TUSHARE,
        base=ts_code,
        quote="CNY",
        asset_type=AssetType.STOCK,
    )

    store = ParquetStore(PROJECT_ROOT / "data" / "parquet")
    ohlcv = store.read(symbol, Timeframe.D1)

    if ohlcv is None or ohlcv.empty:
        return None

    ohlcv = ohlcv.sort_values("timestamp").reset_index(drop=True)

    # 时间过滤
    if period != "all" and len(ohlcv) > 0:
        cutoff_map = {"3m": 63, "6m": 126, "1y": 252, "2y": 504}
        n_bars = cutoff_map.get(period, len(ohlcv))
        if len(ohlcv) > n_bars:
            ohlcv = ohlcv.tail(n_bars)

    # 转换为列表（给前端）
    ohlcv_list = []
    for _, row in ohlcv.iterrows():
        ts = row["timestamp"]
        if hasattr(ts, "strftime"):
            date_str = ts.strftime("%Y-%m-%d")
        else:
            date_str = str(ts)[:10]

        ohlcv_list.append({
            "date": date_str,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })

    result: dict = {"ohlcv": ohlcv_list}

    # 股票名称
    name_map = _get_stock_name_map()
    result["name"] = name_map.get(ts_code, "")

    # 获取基本信息
    try:
        cache_path = (
            PROJECT_ROOT / "data" / "parquet" / "a_tushare_meta" / "stock_basic.parquet"
        )
        if cache_path.exists():
            basic_df = pd.read_parquet(cache_path)
            match = basic_df[basic_df["ts_code"] == ts_code]
            if not match.empty:
                row = match.iloc[0]
                result["basic_info"] = {
                    "industry": str(row.get("industry", "")),
                    "market": str(row.get("market", "")),
                    "area": str(row.get("area", "")),
                    "list_date": str(row.get("list_date", "")),
                }
    except Exception:
        pass

    # 计算因子
    if factor_name and factor_name != "none":
        try:
            from src.features.a_share_factors import AShareFeatureEngine

            engine = AShareFeatureEngine(data_dir=PROJECT_ROOT / "data")

            # 获取日期范围
            if ohlcv_list:
                start_date = ohlcv_list[0]["date"].replace("-", "")
                end_date = ohlcv_list[-1]["date"].replace("-", "")
            else:
                start_date = None
                end_date = None

            factors_df = engine.calculate_stock_factors(
                ts_code, start_date, end_date, [factor_name]
            )

            if not factors_df.empty and factor_name in factors_df.columns:
                factor_series = factors_df[factor_name].dropna()
                factor_list = []
                for idx, val in factor_series.items():
                    date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                    factor_list.append({"date": date_str, "value": float(val)})
                result["factor"] = factor_list
        except Exception as e:
            logger.warning("factor_calc_error_in_ui", error=str(e))

    return result


def _render_candlestick_chart(ohlcv_data, ts_code, stock_name, factor_data, factor_name):
    """渲染 K 线图 (ECharts via Highcharts-style ui.echart)"""
    if not ohlcv_data:
        ui.label("无数据可显示").classes("text-gray-400")
        return

    dates = [d["date"] for d in ohlcv_data]
    candlestick_values = [[d["open"], d["close"], d["low"], d["high"]] for d in ohlcv_data]
    volumes = [d["volume"] for d in ohlcv_data]

    # 计算 MA
    closes = [d["close"] for d in ohlcv_data]
    ma5 = _calc_ma(closes, 5)
    ma20 = _calc_ma(closes, 20)
    ma60 = _calc_ma(closes, 60)

    # 涨跌颜色 (中国标准: 红涨绿跌)
    vol_colors = []
    for d in ohlcv_data:
        vol_colors.append("#ef4444" if d["close"] >= d["open"] else "#22c55e")

    # Grid 和 axes 设置
    grid = [
        {"left": "8%", "right": "3%", "top": "12%", "height": "45%"},
        {"left": "8%", "right": "3%", "top": "62%", "height": "13%"},
    ]

    x_axis = [
        {"type": "category", "data": dates, "gridIndex": 0, "axisLabel": {"show": False}, "boundaryGap": False},
        {"type": "category", "data": dates, "gridIndex": 1, "boundaryGap": False},
    ]

    y_axis = [
        {"type": "value", "gridIndex": 0, "scale": True, "splitArea": {"show": True}},
        {"type": "value", "gridIndex": 1, "scale": True, "splitNumber": 2,
         "axisLabel": {"show": False}, "splitLine": {"show": False}},
    ]

    series = [
        {
            "name": "K线",
            "type": "candlestick",
            "data": candlestick_values,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "itemStyle": {
                "color": "#ef4444",       # 阳线红
                "color0": "#22c55e",      # 阴线绿
                "borderColor": "#ef4444",
                "borderColor0": "#22c55e",
            },
        },
        {
            "name": "MA5",
            "type": "line",
            "data": ma5,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "smooth": True,
            "lineStyle": {"width": 1},
            "symbol": "none",
        },
        {
            "name": "MA20",
            "type": "line",
            "data": ma20,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "smooth": True,
            "lineStyle": {"width": 1},
            "symbol": "none",
        },
        {
            "name": "MA60",
            "type": "line",
            "data": ma60,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "smooth": True,
            "lineStyle": {"width": 1},
            "symbol": "none",
        },
        {
            "name": "成交量",
            "type": "bar",
            "data": [
                {"value": v, "itemStyle": {"color": c}}
                for v, c in zip(volumes, vol_colors)
            ],
            "xAxisIndex": 1,
            "yAxisIndex": 1,
        },
    ]

    # 因子图 (第三区域)
    if factor_data and factor_name != "none":
        grid.append(
            {"left": "8%", "right": "3%", "top": "78%", "height": "15%"}
        )
        x_axis.append(
            {"type": "category", "data": dates, "gridIndex": 2, "boundaryGap": False}
        )
        y_axis.append(
            {"type": "value", "gridIndex": 2, "scale": True, "splitNumber": 2}
        )

        # 对齐因子数据到K线日期
        factor_map = {fd["date"]: fd["value"] for fd in factor_data}
        factor_aligned = [factor_map.get(d, None) for d in dates]

        series.append({
            "name": _factor_label(factor_name),
            "type": "line",
            "data": factor_aligned,
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "smooth": True,
            "lineStyle": {"width": 1.5, "color": "#f59e0b"},
            "areaStyle": {"color": "rgba(245, 158, 11, 0.1)"},
            "symbol": "none",
        })
        # 调整高度
        grid[0]["height"] = "38%"
        grid[1]["top"] = "55%"
        grid[1]["height"] = "10%"
        grid[2]["top"] = "68%"

    option = {
        "title": {"text": f"{ts_code} {stock_name}", "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "cross"},
        },
        "legend": {
            "data": ["MA5", "MA20", "MA60"] + ([_factor_label(factor_name)] if factor_data else []),
            "top": "3%",
            "textStyle": {"fontSize": 11},
        },
        "grid": grid,
        "xAxis": x_axis,
        "yAxis": y_axis,
        "dataZoom": [
            {"type": "inside", "xAxisIndex": list(range(len(x_axis))), "start": max(0, 100 - 3000 / max(len(dates), 1) * 100), "end": 100},
            {"type": "slider", "xAxisIndex": list(range(len(x_axis))), "bottom": "1%"},
        ],
        "series": series,
    }

    ui.echart(option).classes("w-full").style("height: 600px")


def _render_stock_data_stats(ohlcv_data, ts_code):
    """渲染个股数据统计摘要"""
    if not ohlcv_data or len(ohlcv_data) < 2:
        return

    closes = [d["close"] for d in ohlcv_data]
    highs = [d["high"] for d in ohlcv_data]
    lows = [d["low"] for d in ohlcv_data]

    with ui.card().classes("card w-full mt-4 p-4"):
        ui.label("📊 数据摘要").classes("font-medium mb-2")
        with ui.row().classes("gap-6 flex-wrap"):
            ui.label(f"日期范围: {ohlcv_data[0]['date']} ~ {ohlcv_data[-1]['date']}").classes("text-sm text-gray-600")
            ui.label(f"总交易日: {len(ohlcv_data)}").classes("text-sm text-gray-600")
            ui.label(f"最高: ¥{max(highs):.2f}").classes("text-sm text-red-500")
            ui.label(f"最低: ¥{min(lows):.2f}").classes("text-sm text-green-500")
            total_return = (closes[-1] / closes[0] - 1) * 100 if closes[0] != 0 else 0
            color = "text-red-500" if total_return > 0 else "text-green-500"
            ui.label(f"区间涨幅: {total_return:+.2f}%").classes(f"text-sm {color}")


def _calc_ma(values: list, period: int) -> list:
    """计算移动平均线"""
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            avg = sum(values[i - period + 1: i + 1]) / period
            result.append(round(avg, 2))
    return result


# ============================================
# 数据下载面板
# ============================================


def _render_download_panel():
    """数据下载面板"""
    import os

    with ui.card().classes("card w-full"):
        ui.label("🇨🇳 A 股全市场数据下载").classes("text-lg font-medium mb-2")
        ui.label(
            "使用 Tushare 数据源下载全市场数据。支持日线 OHLCV、每日指标(daily_basic)、复权因子(adj_factor)。"
            "下载后自动存储为 Parquet 格式，支持断点续传。"
        ).classes("text-gray-500 text-sm mb-4")

        # 提示
        with ui.row().classes(
            "gap-2 items-center mb-4 bg-blue-50 dark:bg-blue-900/20 p-2 rounded"
        ):
            ui.icon("lightbulb").classes("text-blue-500 text-sm")
            ui.label(
                "推荐下载顺序: ① daily (日线数据) → ② daily_basic (每日指标) → ③ adj_factor (复权因子)。"
                "全市场日线约需 30-60 分钟，取决于网络和积分速率。"
            ).classes("text-xs text-blue-600 dark:text-blue-300")

        # 参数
        default_start = os.getenv("TUSHARE_BACKFILL_START", "20180101")
        formatted_start = (
            f"{default_start[:4]}-{default_start[4:6]}-{default_start[6:8]}"
            if len(default_start) == 8
            else "2018-01-01"
        )

        with ui.row().classes("gap-4 flex-wrap items-end"):
            data_type_select = (
                ui.select(
                    {
                        "daily": "① 日线 OHLCV",
                        "daily_basic": "② 每日指标 (市值/换手等)",
                        "adj_factor": "③ 复权因子",
                    },
                    value="daily",
                    label="数据类型",
                )
                .classes("min-w-52")
                .props("outlined dense")
            )

            with (
                ui.input(label="开始日期", value=formatted_start)
                .classes("min-w-40")
                .props("outlined dense") as start_input
            ):
                with ui.menu().props("no-parent-event") as start_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(start_input):
                        with ui.row().classes("justify-end"):
                            ui.button("确定", on_click=start_menu.close).props("flat")
                with start_input.add_slot("append"):
                    ui.icon("event").on("click", start_menu.open).classes("cursor-pointer")

            with (
                ui.input(
                    label="结束日期",
                    value=datetime.now().strftime("%Y-%m-%d"),
                )
                .classes("min-w-40")
                .props("outlined dense") as end_input
            ):
                with ui.menu().props("no-parent-event") as end_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(end_input):
                        with ui.row().classes("justify-end"):
                            ui.button("确定", on_click=end_menu.close).props("flat")
                with end_input.add_slot("append"):
                    ui.icon("event").on("click", end_menu.open).classes("cursor-pointer")

        # 进度
        progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full mt-4")
        progress_bar.visible = False
        progress_label = ui.label("").classes("text-sm text-gray-500 mt-1")
        progress_container = ui.column().classes("w-full mt-2")

        # 按钮
        with ui.row().classes("gap-4 mt-4 items-center"):
            download_btn = ui.button("开始下载", icon="cloud_download").props("color=primary")
            cancel_btn = ui.button("取消", icon="cancel").props("flat color=red")
            cancel_btn.visible = False

        _fetcher_ref: dict = {"fetcher": None}

        def _on_progress(stats):
            pct = stats.progress
            progress_bar.value = pct / 100
            eta_str = ""
            if stats.eta_seconds is not None:
                eta_str = f" · ETA {_format_eta(stats.eta_seconds)}"
            progress_label.set_text(
                f"已完成 {stats.completed_days + stats.skipped_days}"
                f" / {stats.total_days} 交易日"
                f" ({pct:.1f}%){eta_str}"
                f" · 共 {stats.total_rows:,} 条 · 失败 {stats.failed_days}"
            )

        async def start_download():
            download_btn.disable()
            cancel_btn.visible = True
            progress_bar.visible = True
            progress_bar.value = 0
            progress_label.set_text("正在初始化 Tushare 连接...")
            progress_container.clear()

            try:
                from src.data.fetcher.tushare_history import TushareHistoryFetcher

                fetcher = TushareHistoryFetcher(data_dir=PROJECT_ROOT / "data")
                _fetcher_ref["fetcher"] = fetcher
                fetcher.set_progress_callback(_on_progress)

                start_str = start_input.value.replace("-", "")
                end_str = end_input.value.replace("-", "")
                selected_type = data_type_select.value

                if selected_type == "daily":
                    progress_label.set_text("正在获取交易日历并下载日线数据...")
                    stats = await fetcher.backfill_daily(start_date=start_str, end_date=end_str)
                elif selected_type == "daily_basic":
                    progress_label.set_text("正在下载每日指标数据...")
                    stats = await fetcher.backfill_daily_basic(start_date=start_str, end_date=end_str)
                elif selected_type == "adj_factor":
                    progress_label.set_text("正在下载复权因子数据...")
                    stats = await fetcher.backfill_adj_factor(start_date=start_str, end_date=end_str)
                else:
                    progress_label.set_text("未知数据类型")
                    return

                await fetcher.close()
                _fetcher_ref["fetcher"] = None

                progress_bar.value = 1.0
                progress_container.clear()
                with progress_container:
                    with ui.card().classes("bg-green-50 dark:bg-green-900/20 p-4 w-full"):
                        ui.label("✅ 下载完成").classes("text-green-600 font-medium")
                        ui.label(
                            f"  完成: {stats.completed_days} 日"
                            f" · 跳过: {stats.skipped_days} 日"
                            f" · 失败: {stats.failed_days} 日"
                        ).classes("text-gray-600 text-sm")
                        ui.label(f"  共写入 {stats.total_rows:,} 条数据").classes("text-gray-600 text-sm")
                        ui.label(f"  耗时 {stats.elapsed_seconds:.1f} 秒").classes("text-gray-500 text-sm")

                progress_label.set_text("")

            except Exception as e:
                progress_container.clear()
                with progress_container:
                    with ui.card().classes("bg-red-50 dark:bg-red-900/20 p-4 w-full"):
                        ui.label("❌ 下载失败").classes("text-red-600 font-medium")
                        ui.label(f"  {e}").classes("text-red-500 text-sm")
                progress_label.set_text("")
                logger.error("a_share_download_error", error=str(e))
            finally:
                download_btn.enable()
                cancel_btn.visible = False
                progress_bar.visible = False

        async def cancel_download():
            fetcher = _fetcher_ref.get("fetcher")
            if fetcher is not None:
                fetcher.cancel()
                ui.notify("取消请求已发送，将在当前交易日完成后停止", type="warning")

        download_btn.on_click(start_download)
        cancel_btn.on_click(cancel_download)


# ============================================
# 本地数据统计面板
# ============================================


def _render_stats_panel():
    """本地数据统计面板"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📦 本地 A 股数据统计").classes("text-lg font-medium")
            refresh_btn = ui.button("刷新", icon="refresh").props("flat dense")

        stats_container = ui.column().classes("w-full")

        async def load_stats():
            stats_container.clear()
            with stats_container:
                with ui.row().classes("justify-center py-4"):
                    ui.spinner("dots")
                    ui.label("正在扫描本地数据...").classes("text-gray-400 ml-2")

            try:
                from src.data.fetcher.tushare_history import TushareHistoryFetcher

                fetcher = TushareHistoryFetcher(data_dir=PROJECT_ROOT / "data")
                local_stats = await asyncio.get_event_loop().run_in_executor(
                    None, fetcher.get_local_stats
                )
                await fetcher.close()

                stats_container.clear()
                with stats_container:
                    # OHLCV
                    with ui.row().classes("gap-4 flex-wrap mb-4"):
                        with ui.card().classes("card flex-1 min-w-40"):
                            ui.label("🏢 股票数量").classes("text-sm text-gray-500")
                            ui.label(f"{local_stats['stock_count']:,}").classes("text-xl font-bold mt-1")
                            ui.label("已下载的 A 股日线").classes("text-xs text-gray-400")

                        with ui.card().classes("card flex-1 min-w-40"):
                            ui.label("📁 Parquet 文件数").classes("text-sm text-gray-500")
                            ui.label(f"{local_stats['file_count']:,}").classes("text-xl font-bold mt-1")
                            size_mb = local_stats["total_size_mb"]
                            size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"
                            ui.label(f"占用 {size_str}").classes("text-xs text-gray-400")

                        with ui.card().classes("card flex-1 min-w-40"):
                            ui.label("📦 数据源").classes("text-sm text-gray-500")
                            ui.label("Tushare").classes("text-xl font-bold mt-1")
                            ui.label("A 股全市场日线").classes("text-xs text-gray-400")

                    # 基本面数据
                    fundamentals = local_stats.get("fundamentals", {})
                    if fundamentals:
                        ui.label("基本面数据明细").classes("font-medium text-gray-600 dark:text-gray-300 mt-2 mb-2")

                        fund_rows = []
                        name_map = {
                            "daily_basic": "每日指标 (市值/换手率/PE/PB)",
                            "adj_factor": "复权因子",
                            "forecast": "业绩预告",
                            "fina_indicator": "财务指标",
                        }
                        for api_name, info in fundamentals.items():
                            fund_rows.append({
                                "id": api_name,
                                "type": name_map.get(api_name, api_name),
                                "files": str(info.get("file_count", 0)),
                                "size": f"{info.get('size_mb', 0):.1f} MB",
                            })

                        if fund_rows:
                            ui.table(
                                columns=[
                                    {"name": "type", "label": "数据类型", "field": "type", "align": "left"},
                                    {"name": "files", "label": "文件数", "field": "files", "align": "right"},
                                    {"name": "size", "label": "磁盘大小", "field": "size", "align": "right"},
                                ],
                                rows=fund_rows,
                                row_key="id",
                            ).classes("w-full").props("dense flat bordered")
                    else:
                        ui.label("暂无基本面数据").classes("text-gray-400 text-sm mt-2")

                    # 采样展示部分已下载股票
                    _render_sample_stocks(local_stats)

                    if local_stats["stock_count"] == 0 and not fundamentals:
                        with ui.column().classes("items-center py-6"):
                            ui.icon("cloud_download").classes("text-4xl text-gray-300")
                            ui.label("暂无 A 股本地数据").classes("text-gray-400 mt-2")
                            ui.label("请先到「数据下载」标签页开始采集").classes("text-gray-400 text-sm")

            except Exception as e:
                stats_container.clear()
                with stats_container:
                    ui.label(f"⚠️ 统计失败: {e}").classes("text-yellow-600 text-sm")
                logger.warning("a_share_stats_error_in_page", error=str(e))

        refresh_btn.on_click(load_stats)
        from services.web.utils import safe_timer

        safe_timer(0.5, load_stats, once=True)


def _render_sample_stocks(local_stats):
    """展示部分已下载的股票列表"""
    if local_stats["stock_count"] == 0:
        return

    a_share_dir = PROJECT_ROOT / "data" / "parquet" / "a_tushare"
    if not a_share_dir.exists():
        return

    # 获取前20个股票目录
    symbol_dirs = sorted(
        [d.name for d in a_share_dir.iterdir() if d.is_dir() and d.name != "__pycache__"]
    )[:20]

    if not symbol_dirs:
        return

    ui.label("已下载股票 (部分)").classes("font-medium text-gray-600 dark:text-gray-300 mt-4 mb-2")

    name_map = _get_stock_name_map()
    sample_rows = []
    for sd in symbol_dirs:
        # sd 格式: 600519.SH_CNY
        ts_code = sd.replace("_CNY", "").replace("_cny", "")
        stock_name = name_map.get(ts_code, "")

        # 检查数据文件
        stock_dir = a_share_dir / sd / "1d"
        parquet_count = len(list(stock_dir.rglob("data.parquet"))) if stock_dir.exists() else 0

        sample_rows.append({
            "id": ts_code,
            "ts_code": ts_code,
            "name": stock_name,
            "files": str(parquet_count),
        })

    ui.table(
        columns=[
            {"name": "ts_code", "label": "代码", "field": "ts_code", "align": "left"},
            {"name": "name", "label": "名称", "field": "name", "align": "left"},
            {"name": "files", "label": "Parquet文件数", "field": "files", "align": "right"},
        ],
        rows=sample_rows,
        row_key="id",
    ).classes("w-full max-w-2xl").props("dense flat bordered")

    if local_stats["stock_count"] > 20:
        ui.label(f"... 共 {local_stats['stock_count']:,} 只股票").classes(
            "text-gray-400 text-sm mt-1"
        )


# ============================================
# 辅助函数
# ============================================


def _get_latest_trade_date() -> str:
    """获取最近交易日 (近似)"""
    from datetime import date, timedelta

    today = date.today()
    # 简单处理：如果是周六日则往前推
    while today.weekday() >= 5:  # 5=Sat, 6=Sun
        today -= timedelta(days=1)
    return today.strftime("%Y%m%d")


def _factor_label(factor_name: str) -> str:
    """因子名称→显示标签"""
    labels = {
        "total_mv": "总市值",
        "circ_mv": "流通市值",
        "turnover_rate": "换手率",
        "pe_ttm": "市盈率(TTM)",
        "pb": "市净率",
        "ps_ttm": "市销率(TTM)",
        "volume_ratio": "量比",
        "momentum_5": "动量(5日)",
        "momentum_20": "动量(20日)",
        "momentum_60": "动量(60日)",
        "volatility_20": "波动率(20日)",
        "volatility_60": "波动率(60日)",
        "price_volume_div": "量价背离",
        "turnover_ma_5": "换手率MA5",
        "turnover_ma_20": "换手率MA20",
        "adjusted_close": "前复权收盘价",
        "amplitude": "振幅",
    }
    return labels.get(factor_name, factor_name)


def _fmt_num(val, decimals: int = 2) -> str:
    """格式化数字（处理 None/NaN）"""
    if val is None:
        return "-"
    try:
        import math
        if math.isnan(float(val)):
            return "-"
        return f"{float(val):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(val)


def _format_eta(seconds: float) -> str:
    """格式化 ETA"""
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    elif seconds < 3600:
        return f"{seconds / 60:.1f} 分钟"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h{m:02d}m"
