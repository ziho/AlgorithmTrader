"""
数据管理页面

功能:
- 历史数据下载 (Binance Public Data)
- 实时行情显示 (Binance REST API, 3-5s 刷新)
- 本地 Parquet 数据浏览
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nicegui import ui

from services.web.download_tasks import format_eta, get_download_manager
from src.core.config import get_settings
from src.ops.logging import get_logger

logger = get_logger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# ============================================
# 常量
# ============================================
COMMON_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "LTCUSDT", "MATICUSDT",
]

BINANCE_API_URL = "https://api.binance.com"


def render():
    """渲染数据管理页面"""
    ui.label("数据管理").classes("text-2xl font-bold mb-4")

    # 顶部统计卡片
    with ui.row().classes("w-full gap-4 flex-wrap"):
        _render_data_stats()

    # Tab 切换 — 3 个核心 tab
    with ui.tabs().classes("w-full mt-4") as tabs:
        download_tab = ui.tab("历史数据下载")
        market_tab = ui.tab("实时行情")
        local_tab = ui.tab("本地数据")

    with ui.tab_panels(tabs, value=download_tab).classes("w-full"):
        with ui.tab_panel(download_tab):
            _render_download_panel()

        with ui.tab_panel(market_tab):
            _render_market_panel()

        with ui.tab_panel(local_tab):
            _render_local_data_panel()


# ============================================
# 顶部统计
# ============================================

def _render_data_stats():
    """渲染数据统计卡片"""
    stats = _get_data_stats()

    cards = [
        ("📊 数据集", str(stats["parquet_datasets"]), "个交易对", True),
        ("💾 存储大小", stats["parquet_size"], "", False),
        ("🔄 最后下载", stats["last_sync"], "", False),
        ("📦 数据源", "Binance", "data.binance.vision", False),
    ]

    for title, value, subtitle, inline in cards:
        with ui.card().classes("card min-w-48 flex-1"):
            ui.label(title).classes("text-sm text-gray-500 dark:text-gray-400")
            if inline and subtitle:
                with ui.row().classes("items-baseline gap-1 mt-1"):
                    ui.label(value).classes("text-xl font-bold")
                    ui.label(subtitle).classes("text-sm text-gray-500 dark:text-gray-400")
            else:
                ui.label(value).classes("text-xl font-bold mt-1")
                if subtitle:
                    ui.label(subtitle).classes(
                        "text-xs text-gray-400 dark:text-gray-500 mt-1"
                    )


def _get_data_stats() -> dict:
    """获取数据统计信息"""
    stats = {
        "parquet_datasets": 0,
        "parquet_size": "0 MB",
        "last_sync": "未知",
    }

    parquet_dir = PROJECT_ROOT / "data" / "parquet"
    if parquet_dir.exists():
        datasets = set()
        total_size = 0

        for parquet_file in parquet_dir.glob("**/*.parquet"):
            total_size += parquet_file.stat().st_size
            parts = parquet_file.relative_to(parquet_dir).parts
            if len(parts) >= 2:
                datasets.add(f"{parts[0]}/{parts[1]}")

        stats["parquet_datasets"] = len(datasets)

        if total_size < 1024 * 1024:
            stats["parquet_size"] = f"{total_size / 1024:.1f} KB"
        elif total_size < 1024 * 1024 * 1024:
            stats["parquet_size"] = f"{total_size / 1024 / 1024:.1f} MB"
        else:
            stats["parquet_size"] = f"{total_size / 1024 / 1024 / 1024:.2f} GB"

    # 检查断点状态
    checkpoint_db = PROJECT_ROOT / "data" / "fetch_checkpoint.db"
    if checkpoint_db.exists():
        import sqlite3

        try:
            with sqlite3.connect(checkpoint_db) as conn:
                cursor = conn.execute(
                    "SELECT MAX(updated_at) FROM download_progress"
                )
                row = cursor.fetchone()
                if row and row[0]:
                    stats["last_sync"] = row[0][:19].replace("T", " ")
        except Exception:
            pass

    return stats


# ============================================
# Tab 1: 历史数据下载
# ============================================

def _render_download_panel():
    """渲染历史数据下载面板"""
    with ui.card().classes("card w-full"):
        ui.label("📥 历史 K 线下载").classes("text-lg font-medium mb-2")
        ui.label(
            "从 Binance Public Data (data.binance.vision) 下载历史 OHLCV 数据。"
            "支持断点续传，自动跳过已下载月份。"
        ).classes("text-gray-500 text-sm mb-4")

        manager = get_download_manager(PROJECT_ROOT / "data")

        # 交易所 + 市场类型
        with ui.row().classes("gap-4 flex-wrap items-end"):
            exchange = ui.select(
                ["binance"],
                value="binance",
                label="数据源",
            ).classes("min-w-32").props("outlined dense")

            market_type = ui.select(
                {"spot": "现货 (Spot)", "um": "U本位合约", "cm": "币本位合约"},
                value="spot",
                label="市场类型",
            ).classes("min-w-40").props("outlined dense")

            symbols_select = ui.select(
                COMMON_SYMBOLS,
                value=["BTCUSDT", "ETHUSDT"],
                label="交易对",
                multiple=True,
                with_input=True,
            ).classes("min-w-64").props("outlined dense use-chips")

            timeframe = ui.select(
                ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                value="1m",
                label="K 线周期",
            ).classes("min-w-24").props("outlined dense")

        ui.separator().classes("my-4")

        # 日期范围
        with ui.row().classes("gap-4 items-end flex-wrap"):
            with ui.input(
                label="开始日期", value="2020-01-01"
            ).classes("min-w-40").props("outlined dense") as start_input:
                with ui.menu().props("no-parent-event") as start_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(start_input):
                        with ui.row().classes("justify-end"):
                            ui.button("确定", on_click=start_menu.close).props("flat")
                with start_input.add_slot("append"):
                    ui.icon("event").on("click", start_menu.open).classes("cursor-pointer")

            with ui.input(
                label="结束日期", value=datetime.now().strftime("%Y-%m-%d")
            ).classes("min-w-40").props("outlined dense") as end_input:
                with ui.menu().props("no-parent-event") as end_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(end_input):
                        with ui.row().classes("justify-end"):
                            ui.button("确定", on_click=end_menu.close).props("flat")
                with end_input.add_slot("append"):
                    ui.icon("event").on("click", end_menu.open).classes("cursor-pointer")

        # 快捷按钮
        def set_date_range(months: int):
            end = datetime.now()
            start = end - timedelta(days=months * 30)
            start_input.value = start.strftime("%Y-%m-%d")
            end_input.value = end.strftime("%Y-%m-%d")

        with ui.row().classes("gap-2 mt-2 flex-wrap"):
            ui.button("近 3 月", on_click=lambda: set_date_range(3)).props("flat dense size=sm")
            ui.button("近 6 月", on_click=lambda: set_date_range(6)).props("flat dense size=sm")
            ui.button("近 1 年", on_click=lambda: set_date_range(12)).props("flat dense size=sm")
            ui.button("近 2 年", on_click=lambda: set_date_range(24)).props("flat dense size=sm")
            ui.button(
                "全部 (2020 起)",
                on_click=lambda: (
                    setattr(start_input, "value", "2020-01-01"),
                    setattr(end_input, "value", datetime.now().strftime("%Y-%m-%d")),
                ),
            ).props("flat dense size=sm")

        # 操作按钮
        with ui.row().classes("gap-4 mt-6 items-center"):
            download_btn = ui.button("加入下载队列", icon="download").props("color=primary")
            progress_label = ui.label("").classes("text-gray-500")

        # 命令预览
        with ui.expansion("查看等效 CLI 命令", icon="code").classes("mt-4 w-full"):
            cmd_display = ui.code("").classes("w-full")

            def update_cmd():
                selected = symbols_select.value if symbols_select.value else []
                symbols_str = ",".join(selected) if isinstance(selected, list) else selected
                cmd = (
                    f"python -m scripts.fetch_history "
                    f"--exchange {exchange.value} "
                    f"--symbols {symbols_str} "
                    f"--tf {timeframe.value} "
                    f"--from {start_input.value} "
                    f"--to {end_input.value} "
                    f"--market {market_type.value}"
                )
                cmd_display.set_content(cmd)

            for widget in [exchange, symbols_select, timeframe, start_input, end_input, market_type]:
                widget.on("update:model-value", lambda _: update_cmd())

            update_cmd()

        # 下载回调
        async def start_download():
            selected = symbols_select.value if symbols_select.value else []
            symbol_list = selected if isinstance(selected, list) else [selected]
            if not symbol_list:
                ui.notify("请选择至少一个交易对", type="warning")
                return

            start = datetime.strptime(start_input.value, "%Y-%m-%d").replace(tzinfo=UTC)
            end = datetime.strptime(end_input.value, "%Y-%m-%d").replace(tzinfo=UTC)

            task = await manager.enqueue(
                exchange=exchange.value,
                symbols=symbol_list,
                timeframe=timeframe.value,
                start_date=start,
                end_date=end,
            )

            progress_label.set_text(f"✅ 任务 {task.id} 已加入队列")
            ui.notify(f"下载任务 {task.id} 已加入队列", type="positive")

        download_btn.on_click(start_download)

    # 下载任务队列
    _render_task_queue(manager)


def _render_task_queue(manager):
    """渲染下载任务队列"""
    with ui.card().classes("card w-full mt-4"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📋 下载任务队列").classes("text-lg font-medium")

        tasks_container = ui.column().classes("w-full")

        def render_tasks():
            tasks_container.clear()
            with tasks_container:
                tasks = manager.list_tasks()
                if not tasks:
                    with ui.column().classes("items-center py-6"):
                        ui.icon("cloud_download").classes("text-4xl text-gray-300")
                        ui.label("暂无下载任务").classes("text-gray-400 mt-2")
                    return

                for task in tasks[:10]:
                    with ui.card().classes("w-full p-3"):
                        with ui.row().classes("justify-between items-center"):
                            with ui.column().classes("gap-0"):
                                with ui.row().classes("gap-2 items-center"):
                                    # 状态图标
                                    status_icons = {
                                        "queued": ("hourglass_empty", "text-gray-400"),
                                        "running": ("sync", "text-blue-500"),
                                        "completed": ("check_circle", "text-green-500"),
                                        "failed": ("error", "text-red-500"),
                                        "cancelled": ("cancel", "text-gray-400"),
                                    }
                                    icon, color = status_icons.get(task.status, ("help", "text-gray-400"))
                                    ui.icon(icon).classes(f"text-lg {color}")
                                    ui.label(
                                        f"{task.exchange.upper()} · {','.join(task.symbols)} · {task.timeframe}"
                                    ).classes("font-medium text-sm")

                                ui.label(
                                    f"{task.start_date.strftime('%Y-%m-%d')} → {task.end_date.strftime('%Y-%m-%d')}"
                                ).classes("text-xs text-gray-400 ml-8")

                            with ui.column().classes("items-end gap-0"):
                                ui.label(f"{task.progress:.0f}%").classes("font-bold text-sm")
                                if task.eta_seconds:
                                    ui.label(f"ETA {format_eta(task.eta_seconds)}").classes(
                                        "text-xs text-gray-400"
                                    )

                        # 进度条
                        bar_color = "primary"
                        if task.status == "completed":
                            bar_color = "green"
                        elif task.status == "failed":
                            bar_color = "red"
                        elif task.status == "queued":
                            bar_color = "grey"

                        ui.linear_progress(value=task.progress / 100).props(
                            f"size=6px color={bar_color}"
                        )

                        if task.current_symbol and task.status == "running":
                            ui.label(f"正在下载: {task.current_symbol}").classes(
                                "text-xs text-blue-500 mt-1"
                            )

                        if task.error:
                            ui.label(f"错误: {task.error}").classes(
                                "text-xs text-red-500 mt-1"
                            )

        ui.timer(1.0, render_tasks)


# ============================================
# Tab 2: 实时行情
# ============================================

def _render_market_panel():
    """渲染实时行情面板"""

    # 配置区
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📈 实时市场行情").classes("text-lg font-medium")
            with ui.row().classes("gap-2 items-center"):
                refresh_label = ui.label("").classes("text-xs text-gray-400")
                auto_refresh = ui.switch("自动刷新", value=True).classes("ml-2")

        ui.label(
            "通过 Binance REST API 获取 24h 行情快照，无需 API Key。"
        ).classes("text-gray-500 text-sm mb-4")

        # 交易对选择
        with ui.row().classes("gap-4 items-end flex-wrap"):
            market_symbols = ui.select(
                COMMON_SYMBOLS,
                value=["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"],
                label="监控交易对",
                multiple=True,
                with_input=True,
            ).classes("min-w-80").props("outlined dense use-chips")

            refresh_interval = ui.select(
                {"3": "3 秒", "5": "5 秒", "10": "10 秒", "30": "30 秒"},
                value="5",
                label="刷新频率",
            ).classes("min-w-32").props("outlined dense")

    # 行情表格
    with ui.card().classes("card w-full mt-4"):
        table_container = ui.column().classes("w-full")

        # 存储上一次的价格用于计算闪烁
        last_prices: dict[str, float] = {}

        async def refresh_quotes():
            """从 Binance API 拉取行情"""
            selected = market_symbols.value or []
            if not selected or not auto_refresh.value:
                return

            try:
                import aiohttp

                symbols_param = '["' + '","'.join(selected) + '"]'
                url = f"{BINANCE_API_URL}/api/v3/ticker/24hr"

                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as session:
                    async with session.get(
                        url, params={"symbols": symbols_param}
                    ) as resp:
                        if resp.status != 200:
                            return
                        data = await resp.json()

                if not isinstance(data, list):
                    data = [data]

                # 构建行数据
                rows = []
                for i, item in enumerate(data):
                    symbol = item.get("symbol", "")
                    price = float(item.get("lastPrice", 0))
                    prev_price = last_prices.get(symbol, price)
                    change_pct = float(item.get("priceChangePercent", 0))
                    high = float(item.get("highPrice", 0))
                    low = float(item.get("lowPrice", 0))
                    volume = float(item.get("volume", 0))
                    quote_volume = float(item.get("quoteVolume", 0))

                    last_prices[symbol] = price

                    rows.append({
                        "id": i,
                        "symbol": symbol,
                        "price": _fmt_price(price),
                        "change": f"{change_pct:+.2f}%",
                        "high": _fmt_price(high),
                        "low": _fmt_price(low),
                        "volume": _fmt_volume(volume),
                        "quote_vol": _fmt_volume(quote_volume),
                        "price_raw": price,
                        "change_raw": change_pct,
                        "flash": "up" if price > prev_price else "down" if price < prev_price else "",
                    })

                # 渲染
                table_container.clear()
                with table_container:
                    _render_quote_table(rows)

                refresh_label.set_text(
                    f"更新于 {datetime.now().strftime('%H:%M:%S')}"
                )

            except Exception as e:
                logger.warning("market_quote_fetch_error", error=str(e))
                table_container.clear()
                with table_container:
                    ui.label(f"⚠️ 获取行情失败: {e}").classes("text-yellow-600 py-4")

        # 初次加载
        ui.timer(0.3, refresh_quotes, once=True)

        # 定时刷新 — 动态间隔
        timer_ref = {"timer": None}

        def setup_timer():
            if timer_ref["timer"] is not None:
                timer_ref["timer"].deactivate()
            interval = int(refresh_interval.value)
            timer_ref["timer"] = ui.timer(interval, refresh_quotes)

        setup_timer()
        refresh_interval.on("update:model-value", lambda _: setup_timer())


def _render_quote_table(rows: list[dict]):
    """渲染行情表格"""
    if not rows:
        ui.label("暂无数据").classes("text-gray-400 text-center py-8")
        return

    # 表格头
    with ui.row().classes(
        "w-full px-4 py-2 text-xs text-gray-400 dark:text-gray-500 "
        "border-b border-gray-100 dark:border-gray-700"
    ):
        ui.label("交易对").classes("w-28")
        ui.label("最新价").classes("w-32 text-right")
        ui.label("24h 涨跌").classes("w-24 text-right")
        ui.label("24h 最高").classes("w-28 text-right")
        ui.label("24h 最低").classes("w-28 text-right")
        ui.label("24h 成交量").classes("w-28 text-right")
        ui.label("24h 成交额").classes("flex-1 text-right")

    for row in rows:
        change_color = (
            "text-green-600 dark:text-green-400"
            if row["change_raw"] > 0
            else "text-red-600 dark:text-red-400"
            if row["change_raw"] < 0
            else "text-gray-500"
        )

        # 闪烁效果
        flash_class = ""
        if row.get("flash") == "up":
            flash_class = "bg-green-50 dark:bg-green-900/20"
        elif row.get("flash") == "down":
            flash_class = "bg-red-50 dark:bg-red-900/20"

        with ui.row().classes(
            f"w-full px-4 py-3 items-center "
            f"border-b border-gray-50 dark:border-gray-800 "
            f"hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors "
            f"{flash_class}"
        ):
            # 交易对
            ui.label(row["symbol"]).classes("w-28 font-medium text-sm")

            # 最新价
            ui.label(row["price"]).classes(
                f"w-32 text-right font-mono font-bold text-sm {change_color}"
            )

            # 涨跌幅 badge
            with ui.row().classes("w-24 justify-end"):
                badge_color = (
                    "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
                    if row["change_raw"] > 0
                    else "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
                    if row["change_raw"] < 0
                    else "bg-gray-100 text-gray-500"
                )
                ui.label(row["change"]).classes(
                    f"px-2 py-0.5 rounded text-xs font-medium {badge_color}"
                )

            # 最高 / 最低
            ui.label(row["high"]).classes("w-28 text-right font-mono text-xs text-gray-500")
            ui.label(row["low"]).classes("w-28 text-right font-mono text-xs text-gray-500")

            # 成交量 / 成交额
            ui.label(row["volume"]).classes("w-28 text-right text-xs text-gray-500")
            ui.label(row["quote_vol"]).classes("flex-1 text-right text-xs text-gray-500")


def _fmt_price(v: float) -> str:
    """格式化价格"""
    if v == 0:
        return "-"
    if v >= 1:
        return f"{v:,.2f}"
    if v >= 0.01:
        return f"{v:.4f}"
    return f"{v:.6f}"


def _fmt_volume(v: float) -> str:
    """格式化成交量"""
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return f"{v:.2f}"


# ============================================
# Tab 3: 本地数据
# ============================================

def _render_local_data_panel():
    """渲染本地数据面板"""
    # Parquet 数据总览
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📂 Parquet 数据集").classes("text-lg font-medium")

            with ui.row().classes("gap-2"):
                refresh_btn = ui.button("刷新", icon="refresh").props("flat dense")

        data_container = ui.column().classes("w-full")

        async def load_datasets():
            data_container.clear()
            with data_container:
                ui.spinner("dots").classes("mx-auto my-4")

            datasets = await asyncio.get_event_loop().run_in_executor(
                None, _load_parquet_datasets
            )

            data_container.clear()
            with data_container:
                if not datasets:
                    with ui.column().classes("items-center py-8"):
                        ui.icon("folder_open").classes("text-5xl text-gray-300")
                        ui.label("暂无本地数据").classes("text-gray-400 mt-2 text-lg")
                        ui.label('前往「历史数据下载」tab 下载数据').classes(
                            "text-gray-400 text-sm"
                        )
                else:
                    columns = [
                        {"name": "exchange", "label": "交易所", "field": "exchange", "align": "left", "sortable": True},
                        {"name": "symbol", "label": "交易对", "field": "symbol", "align": "left", "sortable": True},
                        {"name": "timeframe", "label": "周期", "field": "timeframe", "align": "center", "sortable": True},
                        {"name": "start", "label": "开始时间", "field": "start", "align": "center", "sortable": True},
                        {"name": "end", "label": "结束时间", "field": "end", "align": "center", "sortable": True},
                        {"name": "rows", "label": "数据条数", "field": "rows", "align": "right", "sortable": True},
                        {"name": "size", "label": "大小", "field": "size", "align": "right", "sortable": True},
                        {"name": "gaps", "label": "缺口", "field": "gaps", "align": "center"},
                    ]

                    ui.table(
                        columns=columns, rows=datasets, row_key="id"
                    ).classes("w-full").props("dense flat")

        refresh_btn.on_click(load_datasets)
        ui.timer(0.3, load_datasets, once=True)

    # 数据操作
    with ui.card().classes("card w-full mt-4"):
        ui.label("🔧 数据操作").classes("text-lg font-medium mb-4")

        with ui.row().classes("gap-4"):
            ui.button(
                "检查缺口", icon="search",
                on_click=lambda: _check_gaps_dialog(),
            ).props("outline")

            ui.button(
                "手动同步最新", icon="sync",
                on_click=lambda: _manual_sync_dialog(),
            ).props("outline")


def _load_parquet_datasets() -> list[dict]:
    """加载 Parquet 数据集信息"""
    datasets = []
    parquet_dir = PROJECT_ROOT / "data" / "parquet"

    if not parquet_dir.exists():
        return datasets

    try:
        from src.data.fetcher.manager import DataManager

        manager = DataManager(data_dir=PROJECT_ROOT / "data")
        data_list = manager.list_available_data()

        for i, item in enumerate(data_list):
            path = (
                parquet_dir
                / item["exchange"].lower()
                / item["symbol"].replace("/", "_")
                / item["timeframe"]
            )
            size = sum(f.stat().st_size for f in path.glob("**/*.parquet")) if path.exists() else 0

            start_str = item["range"][0].strftime("%Y-%m-%d") if item["range"] else "-"
            end_str = item["range"][1].strftime("%Y-%m-%d") if item["range"] else "-"

            # 尝试计算行数
            row_count = "-"
            try:
                import duckdb
                if path.exists():
                    result = duckdb.sql(
                        f"SELECT COUNT(*) FROM read_parquet('{path}/**/*.parquet')"
                    ).fetchone()
                    if result:
                        row_count = f"{result[0]:,}"
            except Exception:
                pass

            # 检测缺口
            try:
                gaps = manager.detect_gaps(
                    item["exchange"], item["symbol"].replace("/", ""), item["timeframe"]
                )
            except Exception:
                gaps = []

            datasets.append({
                "id": i,
                "exchange": item["exchange"].upper(),
                "symbol": item["symbol"],
                "timeframe": item["timeframe"],
                "start": start_str,
                "end": end_str,
                "rows": row_count,
                "size": f"{size / 1024 / 1024:.1f} MB" if size > 0 else "-",
                "gaps": f"⚠️ {len(gaps)}" if gaps else "✅ 0",
            })

    except Exception as e:
        logger.warning("load_parquet_datasets_error", error=str(e))

    return datasets


# ============================================
# 对话框
# ============================================

def _check_gaps_dialog():
    """检查缺口对话框"""
    with ui.dialog() as dialog, ui.card().classes("min-w-96"):
        ui.label("检查数据缺口").classes("text-lg font-medium mb-4")

        symbol_input = ui.input(label="交易对", value="BTCUSDT")
        tf_input = ui.select(
            ["1m", "5m", "15m", "1h", "4h", "1d"], value="1m", label="K 线周期"
        )

        result_area = ui.column().classes("w-full mt-4")

        async def check():
            result_area.clear()
            with result_area:
                ui.spinner("dots")

            try:
                from src.data.fetcher.manager import DataManager

                manager = DataManager(data_dir=PROJECT_ROOT / "data")
                gaps = manager.detect_gaps("binance", symbol_input.value, tf_input.value)

                result_area.clear()
                with result_area:
                    if not gaps:
                        ui.label("✅ 无缺口").classes("text-green-600")
                    else:
                        ui.label(f"⚠️ 发现 {len(gaps)} 个缺口:").classes("text-yellow-600")
                        for gap_start, gap_end in gaps[:10]:
                            ui.label(
                                f"  {gap_start.strftime('%Y-%m-%d %H:%M')} ~ "
                                f"{gap_end.strftime('%Y-%m-%d %H:%M')}"
                            ).classes("text-sm text-gray-500 font-mono")
                        if len(gaps) > 10:
                            ui.label(f"  ... 还有 {len(gaps) - 10} 个").classes(
                                "text-sm text-gray-400"
                            )

            except Exception as e:
                result_area.clear()
                with result_area:
                    ui.label(f"❌ 错误: {e}").classes("text-red-600")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("检查", on_click=check).props("color=primary")
            ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()


def _manual_sync_dialog():
    """手动同步对话框"""
    with ui.dialog() as dialog, ui.card().classes("min-w-96"):
        ui.label("手动同步最新数据").classes("text-lg font-medium mb-4")
        ui.label(
            "从 Binance API 拉取最近的 K 线并写入 Parquet。"
        ).classes("text-gray-500 text-sm mb-4")

        symbol_input = ui.input(label="交易对", value="BTCUSDT")
        tf_input = ui.select(["1m", "5m", "15m", "1h"], value="1m", label="K 线周期")

        result_area = ui.column().classes("w-full mt-4")

        async def sync():
            result_area.clear()
            with result_area:
                ui.spinner("dots")
                ui.label("正在同步...")

            try:
                from src.data.fetcher.realtime import RealtimeSyncer

                syncer = RealtimeSyncer(
                    symbols=[symbol_input.value],
                    timeframes=[tf_input.value],
                    data_dir=str(PROJECT_ROOT / "data"),
                )

                rows = await syncer.sync_to_latest(symbol_input.value, tf_input.value)
                gaps_filled = await syncer.check_and_fill_gaps(
                    symbol_input.value, tf_input.value
                )

                await syncer.close()

                result_area.clear()
                with result_area:
                    ui.label("✅ 同步完成").classes("text-green-600")
                    ui.label(f"  新数据: {rows} 条").classes("text-gray-500")
                    ui.label(f"  缺口修复: {gaps_filled} 条").classes("text-gray-500")

            except Exception as e:
                result_area.clear()
                with result_area:
                    ui.label(f"❌ 错误: {e}").classes("text-red-600")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("同步", on_click=sync).props("color=primary")
            ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()
