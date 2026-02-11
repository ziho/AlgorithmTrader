"""
数据管理页面

功能:
- 历史数据下载 (Binance Public Data)
- 实时行情显示 (Binance REST API, 3-5s 刷新)
- 本地 Parquet 数据浏览 (真实扫描)
- 数据同步到 InfluxDB
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nicegui import ui

from services.web.download_tasks import format_eta, get_download_manager
from src.ops.logging import get_logger

logger = get_logger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# ============================================
# 常量
# ============================================
COMMON_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "MATICUSDT",
]

BINANCE_API_URL = "https://api.binance.com"


def render():
    """渲染数据管理页面"""
    ui.label("数据管理").classes("text-2xl font-bold mb-4")

    # 说明
    with ui.row().classes("w-full items-center gap-2 mb-2"):
        ui.icon("info").classes("text-blue-400 text-sm")
        ui.label(
            "历史数据使用 Binance (data.binance.vision) 作为数据源；"
            "实盘交易通过 OKX 执行。所有数据存储在 Parquet 文件中，可选同步到 InfluxDB。"
        ).classes("text-gray-500 text-sm")

    # 顶部统计卡片 (动态刷新)
    stats_container = ui.row().classes("w-full gap-4 flex-wrap")

    def refresh_stats():
        stats_container.clear()
        with stats_container:
            _render_data_stats()

    refresh_stats()

    # Tab 切换 — 5 个 tab
    with ui.tabs().classes("w-full mt-4") as tabs:
        download_tab = ui.tab("历史数据下载")
        market_tab = ui.tab("实时行情")
        local_tab = ui.tab("本地数据")
        influx_tab = ui.tab("InfluxDB 同步")
        a_share_tab = ui.tab("A 股数据")

    with ui.tab_panels(tabs, value=download_tab).classes("w-full"):
        with ui.tab_panel(download_tab):
            _render_download_panel(refresh_stats)

        with ui.tab_panel(market_tab):
            _render_market_panel()

        with ui.tab_panel(local_tab):
            _render_local_data_panel()

        with ui.tab_panel(influx_tab):
            _render_influx_sync_panel()

        with ui.tab_panel(a_share_tab):
            _render_a_share_panel(refresh_stats)


# ============================================
# 顶部统计
# ============================================


def _render_data_stats():
    """渲染数据统计卡片 — 每次调用重新扫描文件系统"""
    parquet_dir = PROJECT_ROOT / "data" / "parquet"

    # 实时扫描
    datasets: set[str] = set()  # exchange/symbol/tf
    symbols: set[str] = set()
    total_size = 0
    file_count = 0

    if parquet_dir.exists():
        for pf in parquet_dir.glob("**/*.parquet"):
            total_size += pf.stat().st_size
            file_count += 1
            parts = pf.relative_to(parquet_dir).parts
            if len(parts) >= 3:
                datasets.add(f"{parts[0]}/{parts[1]}/{parts[2]}")
            if len(parts) >= 2:
                symbols.add(parts[1])

    # 格式化大小
    if total_size >= 1024**3:
        size_str = f"{total_size / 1024**3:.2f} GB"
    elif total_size >= 1024**2:
        size_str = f"{total_size / 1024**2:.1f} MB"
    elif total_size > 0:
        size_str = f"{total_size / 1024:.1f} KB"
    else:
        size_str = "0"

    # 最后下载时间
    last_sync = "未知"
    checkpoint_db = PROJECT_ROOT / "data" / "fetch_checkpoint.db"
    if checkpoint_db.exists():
        import sqlite3

        try:
            with sqlite3.connect(checkpoint_db) as conn:
                cursor = conn.execute("SELECT MAX(updated_at) FROM download_progress")
                row = cursor.fetchone()
                if row and row[0]:
                    last_sync = row[0][:19].replace("T", " ")
        except Exception:
            pass

    cards = [
        (
            "📊 数据集",
            f"{len(datasets)}",
            f"{len(symbols)} 个交易对 · {file_count} 个文件",
        ),
        ("💾 存储大小", size_str, str(parquet_dir)),
        ("🔄 最后下载", last_sync, "UTC+0"),
        ("📦 数据源", "Binance", "研究 / 回测"),
    ]

    for title, value, subtitle in cards:
        with ui.card().classes("card flex-1 min-w-44"):
            ui.label(title).classes("text-sm text-gray-500 dark:text-gray-400")
            ui.label(value).classes("text-xl font-bold mt-1")
            if subtitle:
                ui.label(subtitle).classes(
                    "text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate"
                )


# ============================================
# Tab 1: 历史数据下载
# ============================================


def _render_download_panel(refresh_stats_fn=None):
    """渲染历史数据下载面板"""
    with ui.card().classes("card w-full"):
        ui.label("📥 历史 K 线下载").classes("text-lg font-medium mb-2")
        ui.label(
            "从 Binance Public Data (data.binance.vision) 下载历史 OHLCV 数据，"
            "自动存储为 Parquet 格式（支持断点续传）。"
        ).classes("text-gray-500 text-sm mb-2")

        # 存储路径提示
        with ui.row().classes(
            "gap-2 items-center mb-4 bg-blue-50 dark:bg-blue-900/20 p-2 rounded"
        ):
            ui.icon("folder").classes("text-blue-500 text-sm")
            ui.label(
                f"下载目录: {PROJECT_ROOT / 'data' / 'parquet' / 'binance' / '<交易对>' / '<周期>'}"
            ).classes("text-xs text-blue-600 dark:text-blue-300 font-mono")

        manager = get_download_manager(PROJECT_ROOT / "data")

        # 交易所 + 市场类型
        with ui.row().classes("gap-4 flex-wrap items-end"):
            exchange = (
                ui.select(
                    ["binance"],
                    value="binance",
                    label="数据源",
                )
                .classes("min-w-32")
                .props("outlined dense")
            )

            market_type = (
                ui.select(
                    {"spot": "现货 (Spot)", "um": "U本位合约", "cm": "币本位合约"},
                    value="spot",
                    label="市场类型",
                )
                .classes("min-w-40")
                .props("outlined dense")
            )

            symbols_select = (
                ui.select(
                    COMMON_SYMBOLS,
                    value=["BTCUSDT", "ETHUSDT"],
                    label="交易对",
                    multiple=True,
                    with_input=True,
                )
                .classes("min-w-64")
                .props("outlined dense use-chips")
            )

            timeframe = (
                ui.select(
                    ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                    value="1m",
                    label="K 线周期",
                )
                .classes("min-w-24")
                .props("outlined dense")
            )

        ui.separator().classes("my-4")

        # 日期范围
        with ui.row().classes("gap-4 items-end flex-wrap"):
            with (
                ui.input(label="开始日期", value="2020-01-01")
                .classes("min-w-40")
                .props("outlined dense") as start_input
            ):
                with ui.menu().props("no-parent-event") as start_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(start_input):
                        with ui.row().classes("justify-end"):
                            ui.button("确定", on_click=start_menu.close).props("flat")
                with start_input.add_slot("append"):
                    ui.icon("event").on("click", start_menu.open).classes(
                        "cursor-pointer"
                    )

            with (
                ui.input(label="结束日期", value=datetime.now().strftime("%Y-%m-%d"))
                .classes("min-w-40")
                .props("outlined dense") as end_input
            ):
                with ui.menu().props("no-parent-event") as end_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(end_input):
                        with ui.row().classes("justify-end"):
                            ui.button("确定", on_click=end_menu.close).props("flat")
                with end_input.add_slot("append"):
                    ui.icon("event").on("click", end_menu.open).classes(
                        "cursor-pointer"
                    )

        # 快捷按钮
        def set_date_range(months: int):
            end = datetime.now()
            start = end - timedelta(days=months * 30)
            start_input.value = start.strftime("%Y-%m-%d")
            end_input.value = end.strftime("%Y-%m-%d")

        with ui.row().classes("gap-2 mt-2 flex-wrap"):
            ui.button("近 3 月", on_click=lambda: set_date_range(3)).props(
                "flat dense size=sm"
            )
            ui.button("近 6 月", on_click=lambda: set_date_range(6)).props(
                "flat dense size=sm"
            )
            ui.button("近 1 年", on_click=lambda: set_date_range(12)).props(
                "flat dense size=sm"
            )
            ui.button("近 2 年", on_click=lambda: set_date_range(24)).props(
                "flat dense size=sm"
            )
            ui.button(
                "全部 (2020 起)",
                on_click=lambda: (
                    setattr(start_input, "value", "2020-01-01"),
                    setattr(end_input, "value", datetime.now().strftime("%Y-%m-%d")),
                ),
            ).props("flat dense size=sm")

        # 操作按钮
        with ui.row().classes("gap-4 mt-6 items-center"):
            download_btn = ui.button("加入下载队列", icon="download").props(
                "color=primary"
            )
            progress_label = ui.label("").classes("text-gray-500")

        # 命令预览
        with ui.expansion("查看等效 CLI 命令", icon="code").classes("mt-4 w-full"):
            cmd_display = ui.code("").classes("w-full")

            def update_cmd():
                selected = symbols_select.value if symbols_select.value else []
                symbols_str = (
                    ",".join(selected) if isinstance(selected, list) else selected
                )
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

            for widget in [
                exchange,
                symbols_select,
                timeframe,
                start_input,
                end_input,
                market_type,
            ]:
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
    _render_task_queue(manager, refresh_stats_fn)


def _render_task_queue(manager, refresh_stats_fn=None):
    """渲染下载任务队列"""
    with ui.card().classes("card w-full mt-4"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📋 下载任务队列").classes("text-lg font-medium")

            # 清除已完成任务按钮
            async def clear_completed():
                count = manager.clear_finished()
                ui.notify(f"已清除 {count} 个已完成任务", type="info")

            ui.button(
                "清除已完成", icon="delete_sweep", on_click=clear_completed
            ).props("flat dense size=sm")

        tasks_container = ui.column().classes("w-full")

        # 用于跟踪之前的任务状态，仅在变化时才重建 DOM
        _prev_snapshot: list[tuple] = []

        def render_tasks():
            tasks = manager.list_tasks()

            # 构建快照用于判断是否需要更新
            snapshot = [
                (t.id, t.status, round(t.progress, 1), t.current_symbol, t.error)
                for t in tasks[:10]
            ]
            if snapshot == _prev_snapshot:
                return  # 状态未变，跳过 DOM 重建
            _prev_snapshot.clear()
            _prev_snapshot.extend(snapshot)

            tasks_container.clear()
            with tasks_container:
                if not tasks:
                    with ui.column().classes("items-center py-6"):
                        ui.icon("cloud_download").classes("text-4xl text-gray-300")
                        ui.label("暂无下载任务").classes("text-gray-400 mt-2")
                    return

                for task in tasks[:10]:
                    # 根据状态选择卡片边框颜色
                    border_class = {
                        "queued": "border-l-4 border-l-gray-300",
                        "running": "border-l-4 border-l-blue-500",
                        "completed": "border-l-4 border-l-green-500",
                        "failed": "border-l-4 border-l-red-500",
                        "cancelled": "border-l-4 border-l-gray-400",
                    }.get(task.status, "border-l-4 border-l-gray-300")

                    with ui.card().classes(f"w-full p-3 {border_class}"):
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
                                    icon, color = status_icons.get(
                                        task.status, ("help", "text-gray-400")
                                    )
                                    ui.icon(icon).classes(f"text-lg {color}")
                                    ui.label(
                                        f"{task.exchange.upper()} · {','.join(task.symbols)} · {task.timeframe}"
                                    ).classes("font-medium text-sm")

                                ui.label(
                                    f"{task.start_date.strftime('%Y-%m-%d')} → {task.end_date.strftime('%Y-%m-%d')}"
                                ).classes("text-xs text-gray-400 ml-8")

                            # 右侧进度百分比 — 大号醒目
                            with ui.column().classes("items-end gap-0"):
                                pct_color = {
                                    "completed": "text-green-600",
                                    "failed": "text-red-600",
                                    "running": "text-blue-600",
                                }.get(task.status, "text-gray-500")
                                ui.label(f"{task.progress:.1f}%").classes(
                                    f"font-bold text-base {pct_color}"
                                )
                                if task.eta_seconds and task.status == "running":
                                    ui.label(
                                        f"ETA {format_eta(task.eta_seconds)}"
                                    ).classes("text-xs text-gray-500")
                                # 取消按钮（排队中 / 运行中）
                                if task.status in ("queued", "running"):
                                    _tid = task.id

                                    async def _cancel(tid=_tid):
                                        manager.cancel_task(tid)
                                        ui.notify("任务取消请求已发送", type="warning")

                                    ui.button(icon="close", on_click=_cancel).props(
                                        "flat dense round size=xs color=red"
                                    ).tooltip("取消任务")

                        # 进度条 — 更粗、更明显的颜色
                        bar_color = {
                            "completed": "green",
                            "failed": "red",
                            "queued": "grey-5",
                            "running": "light-blue-7",
                            "cancelled": "grey-4",
                        }.get(task.status, "primary")

                        with ui.row().classes("w-full items-center gap-2 mt-1"):
                            ui.linear_progress(
                                value=task.progress / 100,
                                show_value=False,
                            ).props(
                                f'size="12px" color="{bar_color}" track-color="grey-3" rounded'
                            ).classes("flex-1")
                            # 附带小字百分比
                            ui.label(f"{task.progress:.0f}%").classes(
                                "text-xs font-medium text-gray-600 dark:text-gray-300 min-w-[36px] text-right"
                            )

                        # 状态详情
                        if task.current_symbol and task.status == "running":
                            with ui.row().classes("gap-1 items-center mt-1"):
                                ui.spinner("dots", size="xs").classes("text-blue-500")
                                ui.label(f"正在下载: {task.current_symbol}").classes(
                                    "text-xs text-blue-600 dark:text-blue-400"
                                )

                        if task.error:
                            with ui.row().classes(
                                "gap-1 items-center mt-1 bg-red-50 dark:bg-red-900/20 rounded px-2 py-1"
                            ):
                                ui.icon("error_outline").classes("text-red-500 text-sm")
                                ui.label(f"{task.error}").classes(
                                    "text-xs text-red-600 dark:text-red-400"
                                )

                        # 完成后显示存储信息
                        if task.status == "completed":
                            with ui.row().classes(
                                "gap-2 items-center mt-1 bg-green-50 dark:bg-green-900/20 rounded px-2 py-1"
                            ):
                                ui.icon("folder").classes("text-green-500 text-sm")
                                ui.label(
                                    f"已保存到 data/parquet/{task.exchange}/"
                                ).classes(
                                    "text-xs text-green-600 dark:text-green-400 font-mono"
                                )

                # 完成后刷新统计
                completed_any = any(t.status == "completed" for t in tasks)
                if completed_any and refresh_stats_fn:
                    pass  # 统计将在下次定时器中更新

        from services.web.utils import safe_timer

        safe_timer(5.0, render_tasks)


# ============================================


def _render_market_panel():
    """渲染实时行情面板"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📈 实时市场行情").classes("text-lg font-medium")
            with ui.row().classes("gap-2 items-center"):
                refresh_label = ui.label("").classes("text-xs text-gray-400")
                auto_refresh = ui.switch("自动刷新", value=True).classes("ml-2")

        ui.label("通过 Binance REST API 获取 24h 行情快照，无需 API Key。").classes(
            "text-gray-500 text-sm mb-4"
        )

        # 交易对选择
        with ui.row().classes("gap-4 items-end flex-wrap"):
            market_symbols = (
                ui.select(
                    COMMON_SYMBOLS,
                    value=[
                        "BTCUSDT",
                        "ETHUSDT",
                        "BNBUSDT",
                        "SOLUSDT",
                        "XRPUSDT",
                        "DOGEUSDT",
                    ],
                    label="监控交易对",
                    multiple=True,
                    with_input=True,
                )
                .classes("min-w-80")
                .props("outlined dense use-chips")
            )

            refresh_interval = (
                ui.select(
                    {"3": "3 秒", "5": "5 秒", "10": "10 秒", "30": "30 秒"},
                    value="5",
                    label="刷新频率",
                )
                .classes("min-w-32")
                .props("outlined dense")
            )

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

                    rows.append(
                        {
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
                            "flash": "up"
                            if price > prev_price
                            else "down"
                            if price < prev_price
                            else "",
                        }
                    )

                # 渲染
                table_container.clear()
                with table_container:
                    _render_quote_table(rows)

                refresh_label.set_text(f"更新于 {datetime.now().strftime('%H:%M:%S')}")

            except Exception as e:
                logger.warning("market_quote_fetch_error", error=str(e))
                table_container.clear()
                with table_container:
                    ui.label(f"⚠️ 获取行情失败: {e}").classes("text-yellow-600 py-4")

        # 初次加载
        from services.web.utils import safe_timer as _safe_timer

        _safe_timer(0.3, refresh_quotes, once=True)

        # 定时刷新 — 动态间隔
        timer_ref = {"timer": None}

        def setup_timer():
            if timer_ref["timer"] is not None:
                timer_ref["timer"].deactivate()
            interval = int(refresh_interval.value)
            from services.web.utils import safe_timer

            timer_ref["timer"] = safe_timer(interval, refresh_quotes)

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
            ui.label(row["symbol"]).classes("w-28 font-medium text-sm")
            ui.label(row["price"]).classes(
                f"w-32 text-right font-mono font-bold text-sm {change_color}"
            )

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

            ui.label(row["high"]).classes(
                "w-28 text-right font-mono text-xs text-gray-500"
            )
            ui.label(row["low"]).classes(
                "w-28 text-right font-mono text-xs text-gray-500"
            )
            ui.label(row["volume"]).classes("w-28 text-right text-xs text-gray-500")
            ui.label(row["quote_vol"]).classes(
                "flex-1 text-right text-xs text-gray-500"
            )


def _fmt_price(v: float) -> str:
    if v == 0:
        return "-"
    if v >= 1:
        return f"{v:,.2f}"
    if v >= 0.01:
        return f"{v:.4f}"
    return f"{v:.6f}"


def _fmt_volume(v: float) -> str:
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
    """渲染本地数据面板 — 直接扫描文件系统生成真实数据"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📂 本地 Parquet 数据").classes("text-lg font-medium")
            refresh_btn = ui.button("刷新", icon="refresh").props("flat dense")

        ui.label(
            "扫描 data/parquet/ 目录下所有真实数据集。"
            "数据按 交易所/交易对/周期 分区存储，支持缺口检测。"
        ).classes("text-gray-500 text-sm mb-4")

        data_container = ui.column().classes("w-full")

        async def load_datasets():
            data_container.clear()
            with data_container:
                with ui.row().classes("justify-center py-4"):
                    ui.spinner("dots")
                    ui.label("正在扫描本地数据...").classes("text-gray-400 ml-2")

            rows = await asyncio.get_event_loop().run_in_executor(
                None, _scan_parquet_datasets
            )

            data_container.clear()
            with data_container:
                if not rows:
                    with ui.column().classes("items-center py-8"):
                        ui.icon("folder_open").classes("text-5xl text-gray-300")
                        ui.label("暂无本地数据").classes("text-gray-400 mt-2 text-lg")
                        ui.label("前往「历史数据下载」tab 下载数据").classes(
                            "text-gray-400 text-sm"
                        )
                    return

                # 汇总
                total_rows = sum(r.get("row_count_raw", 0) for r in rows)
                total_size_bytes = sum(r.get("size_bytes", 0) for r in rows)
                if total_size_bytes >= 1024**3:
                    ts = f"{total_size_bytes / 1024**3:.2f} GB"
                elif total_size_bytes >= 1024**2:
                    ts = f"{total_size_bytes / 1024**2:.1f} MB"
                else:
                    ts = f"{total_size_bytes / 1024:.1f} KB"

                with ui.row().classes("gap-4 mb-4 text-sm text-gray-500"):
                    ui.label(f"共 {len(rows)} 个数据集")
                    ui.label(f"·  {total_rows:,} 条数据")
                    ui.label(f"·  {ts}")

                # 按交易所分组显示
                from collections import defaultdict

                by_exchange: dict[str, list] = defaultdict(list)
                for r in rows:
                    by_exchange[r["exchange"]].append(r)

                for ex_name, ex_rows in sorted(by_exchange.items()):
                    ui.label(f"━━ {ex_name.upper()} ━━").classes(
                        "font-bold text-gray-600 dark:text-gray-300 mt-2 mb-1"
                    )

                    columns = [
                        {
                            "name": "symbol",
                            "label": "交易对",
                            "field": "symbol",
                            "align": "left",
                            "sortable": True,
                        },
                        {
                            "name": "timeframe",
                            "label": "周期",
                            "field": "timeframe",
                            "align": "center",
                            "sortable": True,
                        },
                        {
                            "name": "start",
                            "label": "数据开始",
                            "field": "start",
                            "align": "center",
                            "sortable": True,
                        },
                        {
                            "name": "end",
                            "label": "数据结束",
                            "field": "end",
                            "align": "center",
                            "sortable": True,
                        },
                        {
                            "name": "rows",
                            "label": "数据条数",
                            "field": "rows",
                            "align": "right",
                            "sortable": True,
                        },
                        {
                            "name": "size",
                            "label": "磁盘大小",
                            "field": "size",
                            "align": "right",
                            "sortable": True,
                        },
                        {
                            "name": "files",
                            "label": "文件数",
                            "field": "files",
                            "align": "right",
                        },
                        {
                            "name": "gaps",
                            "label": "缺口",
                            "field": "gaps",
                            "align": "center",
                        },
                    ]

                    ui.table(
                        columns=columns,
                        rows=ex_rows,
                        row_key="id",
                    ).classes("w-full").props("dense flat bordered")

        refresh_btn.on_click(load_datasets)
        from services.web.utils import safe_timer as _safe_timer2

        _safe_timer2(0.5, load_datasets, once=True)

    # 数据操作
    with ui.card().classes("card w-full mt-4"):
        ui.label("🔧 数据操作").classes("text-lg font-medium mb-4")

        with ui.row().classes("gap-4 flex-wrap"):
            ui.button(
                "检查缺口",
                icon="search",
                on_click=lambda: _check_gaps_dialog(),
            ).props("outline")

            ui.button(
                "手动同步最新",
                icon="sync",
                on_click=lambda: _manual_sync_dialog(),
            ).props("outline")

            ui.button(
                "删除数据集",
                icon="delete_forever",
                on_click=lambda: _delete_dataset_dialog(),
            ).props("outline color=red")

    # Parquet 说明
    with ui.card().classes("card w-full mt-4"):
        with ui.expansion("关于 Parquet 数据存储", icon="help_outline").classes(
            "w-full"
        ):
            ui.markdown("""
**Parquet 是核心历史数据存储格式**，所有回测和策略研发均从 Parquet 读取。

- **目录结构**: `data/parquet/{exchange}/{SYMBOL}/{timeframe}/year=YYYY/month=MM/data.parquet`
- **建议**: 优先下载 **1m (1 分钟)** 数据，更大周期可由 1m 聚合得到
- **数据源**: 历史数据统一使用 **Binance** (全球最大交易量，数据质量高)
- **实盘**: 使用 **OKX** 作为交易执行，不影响研究数据的完整性
- **InfluxDB**: 可选同步，用于 Grafana 可视化监控
            """).classes("text-sm")


def _scan_parquet_datasets() -> list[dict]:
    """扫描 parquet 目录，返回真实数据集列表，每个元素包含:
    exchange, symbol, timeframe, start, end, rows, size, files, gaps
    """
    parquet_dir = PROJECT_ROOT / "data" / "parquet"
    if not parquet_dir.exists():
        return []

    results = []
    idx = 0

    for ex_dir in sorted(parquet_dir.iterdir()):
        if not ex_dir.is_dir():
            continue
        ex_name = ex_dir.name  # e.g. "binance", "okx"

        for sym_dir in sorted(ex_dir.iterdir()):
            if not sym_dir.is_dir():
                continue
            sym_name = sym_dir.name  # e.g. "BTC_USDT"

            for tf_dir in sorted(sym_dir.iterdir()):
                if not tf_dir.is_dir():
                    continue
                tf_name = tf_dir.name  # e.g. "1m", "1h"

                # 收集所有 parquet 文件
                pq_files = list(tf_dir.glob("**/*.parquet"))
                if not pq_files:
                    continue

                file_count = len(pq_files)
                total_size = sum(f.stat().st_size for f in pq_files)

                # 读取数据范围和行数
                row_count = 0
                min_ts = None
                max_ts = None
                gap_count = 0

                try:
                    import polars as pl

                    lf = pl.scan_parquet(
                        [str(f) for f in pq_files],
                        hive_partitioning=False,
                    )
                    stats = lf.select(
                        [
                            pl.col("timestamp").min().alias("min_ts"),
                            pl.col("timestamp").max().alias("max_ts"),
                            pl.len().alias("count"),
                        ]
                    ).collect()

                    if len(stats) > 0:
                        row_count = stats["count"][0]
                        ts_min = stats["min_ts"][0]
                        ts_max = stats["max_ts"][0]

                        if ts_min is not None:
                            min_ts = (
                                ts_min.strftime("%Y-%m-%d %H:%M")
                                if hasattr(ts_min, "strftime")
                                else str(ts_min)[:16]
                            )
                        if ts_max is not None:
                            max_ts = (
                                ts_max.strftime("%Y-%m-%d %H:%M")
                                if hasattr(ts_max, "strftime")
                                else str(ts_max)[:16]
                            )

                    # 基本缺口检测: 比较实际行数 vs 理论行数
                    if min_ts and max_ts and row_count > 0:
                        try:
                            from src.core.timeframes import Timeframe

                            tf_obj = Timeframe(tf_name)
                            if ts_min is not None and ts_max is not None:
                                delta = ts_max - ts_min
                                if hasattr(delta, "total_seconds"):
                                    expected_rows = (
                                        int(delta.total_seconds() / tf_obj.seconds) + 1
                                    )
                                    if (
                                        expected_rows > 0
                                        and row_count < expected_rows * 0.95
                                    ):
                                        gap_count = expected_rows - row_count
                        except Exception:
                            pass

                except Exception as e:
                    logger.warning(
                        "scan_parquet_read_error", path=str(tf_dir), error=str(e)
                    )

                # 格式化
                if total_size >= 1024**3:
                    size_str = f"{total_size / 1024**3:.2f} GB"
                elif total_size >= 1024**2:
                    size_str = f"{total_size / 1024**2:.1f} MB"
                else:
                    size_str = f"{total_size / 1024:.1f} KB"

                results.append(
                    {
                        "id": idx,
                        "exchange": ex_name,
                        "symbol": sym_name.replace("_", "/"),
                        "timeframe": tf_name,
                        "start": min_ts or "-",
                        "end": max_ts or "-",
                        "rows": f"{row_count:,}" if row_count else "-",
                        "row_count_raw": row_count,
                        "size": size_str,
                        "size_bytes": total_size,
                        "files": str(file_count),
                        "gaps": f"⚠️ ~{gap_count:,}" if gap_count > 0 else "✅ 0",
                    }
                )
                idx += 1

    return results


# ============================================
# Tab 4: InfluxDB 同步
# ============================================


def _render_influx_sync_panel():
    """渲染 InfluxDB 同步面板"""
    import os

    influx_bucket = os.getenv("INFLUXDB_BUCKET", "trading")

    with ui.card().classes("card w-full"):
        ui.label("🗄️ 同步到 InfluxDB").classes("text-lg font-medium mb-2")
        ui.label(
            "将本地 Parquet 历史数据批量写入 InfluxDB，以便通过 Grafana 进行可视化。"
        ).classes("text-gray-500 text-sm mb-4")

        with ui.row().classes("gap-4 flex-wrap items-end"):
            exchange_input = (
                ui.select(["binance"], value="binance", label="数据源")
                .classes("min-w-28")
                .props("outlined dense")
            )
            symbol_input = (
                ui.select(
                    COMMON_SYMBOLS,
                    value="BTCUSDT",
                    label="交易对",
                    with_input=True,
                )
                .classes("min-w-40")
                .props("outlined dense")
            )
            tf_input = (
                ui.select(
                    ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                    value="1h",
                    label="K 线周期",
                )
                .classes("min-w-24")
                .props("outlined dense")
            )

        with ui.row().classes(
            "gap-2 items-center mt-2 bg-yellow-50 dark:bg-yellow-900/20 p-2 rounded"
        ):
            ui.icon("warning").classes("text-yellow-500 text-sm")
            ui.label("1m 数据量非常大，建议先同步 1h 或 4h 周期测试").classes(
                "text-xs text-yellow-600 dark:text-yellow-300"
            )

        result_area = ui.column().classes("w-full mt-4")
        progress_bar = ui.linear_progress(value=0, show_value=False).classes(
            "w-full mt-2"
        )
        progress_bar.visible = False
        progress_label = ui.label("").classes("text-sm text-gray-500 mt-1")

        async def do_sync():
            result_area.clear()
            progress_bar.visible = True
            progress_bar.value = 0
            progress_label.set_text("正在读取 Parquet 数据...")

            try:
                from src.core.instruments import Exchange, Symbol
                from src.core.timeframes import Timeframe
                from src.data.storage.parquet_store import ParquetStore

                pq_store = ParquetStore(base_path=PROJECT_ROOT / "data" / "parquet")

                exchange = exchange_input.value
                symbol_str = symbol_input.value.replace("/", "").upper()

                # 解析 symbol
                if symbol_str.endswith("USDT"):
                    base, quote = symbol_str[:-4], "USDT"
                else:
                    base, quote = symbol_str[:-3], symbol_str[-3:]

                ex_enum = Exchange.BINANCE if exchange == "binance" else Exchange.OKX
                sym = Symbol(exchange=ex_enum, base=base, quote=quote)
                tf = Timeframe(tf_input.value)

                # 读取 parquet
                df = pq_store.read(sym, tf)

                if df is None or df.empty:
                    progress_bar.visible = False
                    progress_label.set_text("")
                    with result_area:
                        ui.label(
                            f"⚠️ 未找到 {exchange}/{symbol_str}/{tf_input.value} 的 Parquet 数据"
                        ).classes("text-yellow-600")
                    return

                total_rows = len(df)
                progress_label.set_text(
                    f"读取到 {total_rows:,} 条数据，正在写入 InfluxDB..."
                )
                progress_bar.value = 0.1

                from src.data.storage.influx_store import InfluxStore

                store = InfluxStore(async_write=False)  # 用同步写入确保可靠

                # 分批写入
                batch_size = 5000
                total_written = 0

                for i in range(0, total_rows, batch_size):
                    batch = df.iloc[i : i + batch_size]
                    written = store.write_ohlcv(sym, tf, batch)
                    total_written += written
                    progress_bar.value = min(0.95, (i + batch_size) / total_rows)
                    progress_label.set_text(
                        f"已写入 {total_written:,} / {total_rows:,} 条 ({progress_bar.value * 100:.0f}%)"
                    )
                    await asyncio.sleep(0)  # yield to event loop

                store.close()
                progress_bar.value = 1.0
                progress_label.set_text("")
                progress_bar.visible = False

                result_area.clear()
                with result_area:
                    with ui.card().classes("bg-green-50 dark:bg-green-900/20 p-4"):
                        ui.label("✅ 同步完成").classes("text-green-600 font-medium")
                        ui.label(f"  {total_written:,} 条数据已写入 InfluxDB").classes(
                            "text-gray-600 text-sm"
                        )
                        ts_min = df["timestamp"].min()
                        ts_max = df["timestamp"].max()
                        ui.label(f"  时间范围: {ts_min} ~ {ts_max}").classes(
                            "text-gray-500 text-sm"
                        )
                        ui.label("  可在 Grafana (端口 3000) 中查看此数据").classes(
                            "text-gray-400 text-sm"
                        )

            except Exception as e:
                progress_bar.visible = False
                progress_label.set_text("")
                result_area.clear()
                with result_area:
                    ui.label(f"❌ 同步失败: {e}").classes("text-red-600")
                logger.warning("influx_sync_error", error=str(e))

        ui.button("开始同步", icon="cloud_upload", on_click=do_sync).props(
            "color=deep-purple"
        ).classes("mt-4")

    # InfluxDB 数据概览
    with ui.card().classes("card w-full mt-4"):
        ui.label("📊 InfluxDB 数据概览").classes("text-lg font-medium mb-4")

        influx_container = ui.column().classes("w-full")

        async def load_influx_overview():
            influx_container.clear()
            with influx_container:
                ui.spinner("dots").classes("mx-auto")

            try:
                from src.data.storage.influx_store import InfluxStore

                store = InfluxStore()

                # 查询所有 measurements
                query = f'''
                import "influxdata/influxdb/schema"
                schema.measurements(bucket: "{influx_bucket}")
                '''
                result = store._query_api.query(query)
                measurements = []
                for table in result:
                    for record in table.records:
                        measurements.append(record.get_value())

                # 查询 ohlcv 中的 tag 信息
                tag_info = []
                if "ohlcv" in measurements:
                    tag_query = f'''
                    from(bucket: "{influx_bucket}")
                        |> range(start: -365d)
                        |> filter(fn: (r) => r._measurement == "ohlcv")
                        |> keep(columns: ["exchange", "symbol", "timeframe"])
                        |> distinct(column: "symbol")
                    '''
                    try:
                        tag_result = store._query_api.query(tag_query)
                        for table in tag_result:
                            for record in table.records:
                                tag_info.append(
                                    {
                                        "exchange": record.values.get("exchange", "?"),
                                        "symbol": record.get_value(),
                                        "timeframe": record.values.get(
                                            "timeframe", "?"
                                        ),
                                    }
                                )
                    except Exception:
                        pass

                store.close()

                influx_container.clear()
                with influx_container:
                    if measurements:
                        ui.label(
                            f"共 {len(measurements)} 个 measurement: {', '.join(measurements)}"
                        ).classes("text-gray-500 text-sm mb-2")

                        if tag_info:
                            ui.label("OHLCV 数据:").classes("font-medium text-sm mb-1")
                            for info in tag_info:
                                ui.label(
                                    f"  • {info['exchange']} / {info['symbol']} / {info['timeframe']}"
                                ).classes("text-gray-600 font-mono text-sm")
                        else:
                            ui.label("InfluxDB 中暂无 OHLCV 数据").classes(
                                "text-gray-400 text-sm"
                            )
                    else:
                        ui.label("InfluxDB 中暂无数据").classes("text-gray-400")

            except Exception as e:
                influx_container.clear()
                with influx_container:
                    ui.label(f"查询失败: {e}").classes("text-red-500 text-sm")

        ui.button(
            "查询 InfluxDB 数据", icon="storage", on_click=load_influx_overview
        ).props("flat")


# ============================================
# Tab 5: A 股数据
# ============================================


def _render_a_share_panel(refresh_stats_fn=None):
    """渲染 A 股数据面板 — 全市场日线下载 + 本地数据统计"""
    with ui.card().classes("card w-full"):
        ui.label("🇨🇳 A 股日线数据下载").classes("text-lg font-medium mb-2")
        ui.label(
            "使用 Tushare 数据源下载 A 股全市场日线 OHLCV 及基本面数据，"
            "自动按交易日逐日回填并存储为 Parquet 格式（支持断点续传）。"
        ).classes("text-gray-500 text-sm mb-2")

        # 存储路径提示
        with ui.row().classes(
            "gap-2 items-center mb-4 bg-blue-50 dark:bg-blue-900/20 p-2 rounded"
        ):
            ui.icon("folder").classes("text-blue-500 text-sm")
            ui.label(
                f"下载目录: {PROJECT_ROOT / 'data' / 'parquet' / 'a_tushare' / '<股票代码>' / '1d'}"
            ).classes("text-xs text-blue-600 dark:text-blue-300 font-mono")

        # 参数配置
        import os

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
                        "daily": "日线 OHLCV",
                        "daily_basic": "每日指标 (市值/换手等)",
                        "adj_factor": "复权因子",
                    },
                    value="daily",
                    label="数据类型",
                )
                .classes("min-w-48")
                .props("outlined dense")
            )

            with (
                ui.input(label="开始日期", value=formatted_start)
                .classes("min-w-40")
                .props("outlined dense") as a_start_input
            ):
                with ui.menu().props("no-parent-event") as a_start_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(a_start_input):
                        with ui.row().classes("justify-end"):
                            ui.button("确定", on_click=a_start_menu.close).props("flat")
                with a_start_input.add_slot("append"):
                    ui.icon("event").on("click", a_start_menu.open).classes(
                        "cursor-pointer"
                    )

            with (
                ui.input(
                    label="结束日期",
                    value=datetime.now().strftime("%Y-%m-%d"),
                )
                .classes("min-w-40")
                .props("outlined dense") as a_end_input
            ):
                with ui.menu().props("no-parent-event") as a_end_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(a_end_input):
                        with ui.row().classes("justify-end"):
                            ui.button("确定", on_click=a_end_menu.close).props("flat")
                with a_end_input.add_slot("append"):
                    ui.icon("event").on("click", a_end_menu.open).classes(
                        "cursor-pointer"
                    )

        # 进度条 & 状态
        progress_container = ui.column().classes("w-full mt-4")
        progress_bar = ui.linear_progress(value=0, show_value=False).classes(
            "w-full mt-2"
        )
        progress_bar.visible = False
        progress_label = ui.label("").classes("text-sm text-gray-500 mt-1")

        # 按钮行
        with ui.row().classes("gap-4 mt-4 items-center"):
            download_btn = ui.button("开始全市场下载", icon="cloud_download").props(
                "color=primary"
            )
            cancel_btn = ui.button("取消", icon="cancel").props("flat color=red")
            cancel_btn.visible = False

        # 下载器引用
        _fetcher_ref: dict[str, object] = {"fetcher": None}

        def _on_progress(stats):
            """进度回调"""
            pct = stats.progress
            progress_bar.value = pct / 100
            eta_str = ""
            if stats.eta_seconds is not None:
                eta_str = f" · ETA {_format_eta(stats.eta_seconds)}"
            progress_label.set_text(
                f"已完成 {stats.completed_days + stats.skipped_days}"
                f" / {stats.total_days} 交易日"
                f" ({pct:.1f}%){eta_str}"
                f" · 共 {stats.total_rows:,} 条"
                f" · 失败 {stats.failed_days}"
            )

        async def start_a_share_download():
            """启动 A 股数据下载"""
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

                # 日期格式转换
                start_str = a_start_input.value.replace("-", "")
                end_str = a_end_input.value.replace("-", "")

                selected_type = data_type_select.value

                if selected_type == "daily":
                    progress_label.set_text("正在获取交易日历并下载日线数据...")
                    stats = await fetcher.backfill_daily(
                        start_date=start_str, end_date=end_str
                    )
                elif selected_type == "daily_basic":
                    progress_label.set_text("正在下载每日指标数据...")
                    stats = await fetcher.backfill_daily_basic(
                        start_date=start_str, end_date=end_str
                    )
                elif selected_type == "adj_factor":
                    progress_label.set_text("正在下载复权因子数据...")
                    stats = await fetcher.backfill_adj_factor(
                        start_date=start_str, end_date=end_str
                    )
                else:
                    progress_label.set_text("未知数据类型")
                    return

                await fetcher.close()
                _fetcher_ref["fetcher"] = None

                # 完成
                progress_bar.value = 1.0
                progress_container.clear()
                with progress_container:
                    with ui.card().classes(
                        "bg-green-50 dark:bg-green-900/20 p-4 w-full"
                    ):
                        ui.label("✅ 下载完成").classes("text-green-600 font-medium")
                        ui.label(
                            f"  完成: {stats.completed_days} 日"
                            f" · 跳过: {stats.skipped_days} 日"
                            f" · 失败: {stats.failed_days} 日"
                        ).classes("text-gray-600 text-sm")
                        ui.label(f"  共写入 {stats.total_rows:,} 条数据").classes(
                            "text-gray-600 text-sm"
                        )
                        ui.label(f"  耗时 {stats.elapsed_seconds:.1f} 秒").classes(
                            "text-gray-500 text-sm"
                        )

                progress_label.set_text("")
                if refresh_stats_fn:
                    refresh_stats_fn()

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

        download_btn.on_click(start_a_share_download)
        cancel_btn.on_click(cancel_download)

    # 本地 A 股数据统计
    _render_a_share_local_stats()


def _render_a_share_local_stats():
    """渲染本地 A 股数据统计面板"""
    with ui.card().classes("card w-full mt-4"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📊 本地 A 股数据统计").classes("text-lg font-medium")
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
                    # OHLCV 统计卡片
                    with ui.row().classes("gap-4 flex-wrap mb-4"):
                        with ui.card().classes("card flex-1 min-w-40"):
                            ui.label("🏢 股票数量").classes("text-sm text-gray-500")
                            ui.label(f"{local_stats['stock_count']:,}").classes(
                                "text-xl font-bold mt-1"
                            )
                            ui.label("已下载的 A 股").classes("text-xs text-gray-400")

                        with ui.card().classes("card flex-1 min-w-40"):
                            ui.label("📁 Parquet 文件").classes("text-sm text-gray-500")
                            ui.label(f"{local_stats['file_count']:,}").classes(
                                "text-xl font-bold mt-1"
                            )
                            size_mb = local_stats["total_size_mb"]
                            if size_mb >= 1024:
                                size_str = f"{size_mb / 1024:.2f} GB"
                            else:
                                size_str = f"{size_mb:.1f} MB"
                            ui.label(f"占用 {size_str}").classes(
                                "text-xs text-gray-400"
                            )

                        with ui.card().classes("card flex-1 min-w-40"):
                            ui.label("📦 数据源").classes("text-sm text-gray-500")
                            ui.label("Tushare").classes("text-xl font-bold mt-1")
                            ui.label("A 股全市场日线").classes("text-xs text-gray-400")

                    # 基本面数据明细
                    fundamentals = local_stats.get("fundamentals", {})
                    if fundamentals:
                        ui.label("基本面数据").classes(
                            "font-medium text-gray-600 dark:text-gray-300 mt-2 mb-2"
                        )

                        fund_rows = []
                        for api_name, info in fundamentals.items():
                            fund_rows.append(
                                {
                                    "id": api_name,
                                    "type": api_name,
                                    "files": str(info.get("file_count", 0)),
                                    "size": f"{info.get('size_mb', 0):.1f} MB",
                                }
                            )

                        if fund_rows:
                            columns = [
                                {
                                    "name": "type",
                                    "label": "数据类型",
                                    "field": "type",
                                    "align": "left",
                                },
                                {
                                    "name": "files",
                                    "label": "文件数",
                                    "field": "files",
                                    "align": "right",
                                },
                                {
                                    "name": "size",
                                    "label": "磁盘大小",
                                    "field": "size",
                                    "align": "right",
                                },
                            ]
                            ui.table(
                                columns=columns,
                                rows=fund_rows,
                                row_key="id",
                            ).classes("w-full").props("dense flat bordered")
                    else:
                        ui.label("暂无基本面数据").classes("text-gray-400 text-sm mt-2")

                    if local_stats["stock_count"] == 0 and not fundamentals:
                        with ui.column().classes("items-center py-6"):
                            ui.icon("cloud_download").classes("text-4xl text-gray-300")
                            ui.label("暂无 A 股本地数据").classes("text-gray-400 mt-2")
                            ui.label("点击上方「开始全市场下载」按钮开始采集").classes(
                                "text-gray-400 text-sm"
                            )

            except Exception as e:
                stats_container.clear()
                with stats_container:
                    ui.label(f"⚠️ 统计失败: {e}").classes("text-yellow-600 text-sm")
                logger.warning("a_share_stats_error", error=str(e))

        refresh_btn.on_click(load_stats)
        from services.web.utils import safe_timer as _safe_timer3

        _safe_timer3(0.5, load_stats, once=True)


def _format_eta(seconds: float) -> str:
    """格式化 ETA 时间"""
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    elif seconds < 3600:
        return f"{seconds / 60:.1f} 分钟"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h{m:02d}m"


# ============================================
# 对话框
# ============================================


def _check_gaps_dialog():
    """检查缺口对话框 - 真实扫描 Parquet 数据"""
    with ui.dialog() as dialog, ui.card().classes("min-w-[520px]"):
        ui.label("检查数据缺口").classes("text-lg font-medium mb-4")

        with ui.row().classes("gap-4 flex-wrap"):
            exchange_in = (
                ui.select(
                    ["binance"],
                    value="binance",
                    label="数据源",
                )
                .classes("min-w-28")
                .props("outlined dense")
            )
            symbol_in = (
                ui.select(
                    COMMON_SYMBOLS, value="BTCUSDT", label="交易对", with_input=True
                )
                .classes("min-w-40")
                .props("outlined dense")
            )
            tf_in = (
                ui.select(
                    ["1m", "5m", "15m", "1h", "4h", "1d"], value="1h", label="K 线周期"
                )
                .classes("min-w-24")
                .props("outlined dense")
            )

        result_area = ui.column().classes("w-full mt-4")

        async def check():
            result_area.clear()
            with result_area:
                ui.spinner("dots")

            try:
                from src.core.instruments import Exchange, Symbol
                from src.core.timeframes import Timeframe
                from src.data.storage.parquet_store import ParquetStore

                pq_store = ParquetStore(base_path=PROJECT_ROOT / "data" / "parquet")

                sym_str = symbol_in.value.replace("/", "").upper()
                if sym_str.endswith("USDT"):
                    base, quote = sym_str[:-4], "USDT"
                else:
                    base, quote = sym_str[:-3], sym_str[-3:]

                ex_enum = (
                    Exchange.BINANCE if exchange_in.value == "binance" else Exchange.OKX
                )
                sym = Symbol(exchange=ex_enum, base=base, quote=quote)
                tf = Timeframe(tf_in.value)

                # 先检查有没有数据
                data_range = pq_store.get_data_range(sym, tf)
                gaps = pq_store.detect_gaps(sym, tf)

                result_area.clear()
                with result_area:
                    if data_range is None:
                        ui.label(
                            f"⚠️ 未找到 {exchange_in.value}/{sym_str}/{tf_in.value} 的本地数据"
                        ).classes("text-yellow-600")
                        ui.label("请先下载数据").classes("text-gray-400 text-sm")
                        return

                    start_dt, end_dt = data_range
                    ui.label(
                        f"数据范围: {start_dt.strftime('%Y-%m-%d %H:%M')} ~ "
                        f"{end_dt.strftime('%Y-%m-%d %H:%M')}"
                    ).classes("text-gray-600 text-sm mb-2")

                    if not gaps:
                        ui.label("✅ 数据完整，无缺口").classes(
                            "text-green-600 font-medium"
                        )
                    else:
                        ui.label(f"⚠️ 发现 {len(gaps)} 个缺口:").classes(
                            "text-yellow-600 font-medium"
                        )

                        with ui.column().classes(
                            "w-full mt-2 max-h-60 overflow-y-auto"
                        ):
                            for i, (gs, ge) in enumerate(gaps[:20]):
                                duration = ge - gs
                                hours = duration.total_seconds() / 3600
                                dur_str = (
                                    f"{hours / 24:.1f} 天"
                                    if hours >= 24
                                    else f"{hours:.1f} 小时"
                                )

                                with ui.row().classes(
                                    "gap-2 py-1 border-b border-gray-100 dark:border-gray-700 items-center"
                                ):
                                    ui.label(f"#{i + 1}").classes(
                                        "w-8 text-gray-400 text-xs"
                                    )
                                    ui.label(gs.strftime("%Y-%m-%d %H:%M")).classes(
                                        "text-sm font-mono text-gray-600"
                                    )
                                    ui.label("→").classes("text-gray-400")
                                    ui.label(ge.strftime("%Y-%m-%d %H:%M")).classes(
                                        "text-sm font-mono text-gray-600"
                                    )
                                    ui.label(f"({dur_str})").classes(
                                        "text-xs text-gray-400"
                                    )

                            if len(gaps) > 20:
                                ui.label(f"... 还有 {len(gaps) - 20} 个缺口").classes(
                                    "text-sm text-gray-400 mt-2"
                                )

                        # 提供修复选项
                        ui.separator().classes("my-3")
                        fill_area = ui.column().classes("w-full")

                        async def fill_gaps():
                            fill_area.clear()
                            with fill_area:
                                ui.spinner("dots")
                                ui.label("正在创建补齐下载任务...").classes(
                                    "text-gray-500 text-sm"
                                )

                            try:
                                mgr = get_download_manager(PROJECT_ROOT / "data")
                                task = await mgr.enqueue(
                                    exchange=exchange_in.value,
                                    symbols=[symbol_in.value],
                                    timeframe=tf_in.value,
                                    start_date=gaps[0][0],
                                    end_date=gaps[-1][1],
                                )
                                fill_area.clear()
                                with fill_area:
                                    ui.label(
                                        f"✅ 任务 {task.id} 已创建，覆盖所有缺口时段"
                                    ).classes("text-green-600 text-sm")
                            except Exception as e:
                                fill_area.clear()
                                with fill_area:
                                    ui.label(f"❌ {e}").classes("text-red-600 text-sm")

                        ui.button(
                            "自动补齐缺口", icon="build", on_click=fill_gaps
                        ).props("color=primary size=sm")

            except Exception as e:
                result_area.clear()
                with result_area:
                    ui.label(f"❌ 错误: {e}").classes("text-red-600")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("检查", on_click=check).props("color=primary")
            ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()


def _manual_sync_dialog():
    """手动同步对话框 — 从 Binance REST API 拉取最新数据"""
    with ui.dialog() as dialog, ui.card().classes("min-w-[480px]"):
        ui.label("手动同步最新数据").classes("text-lg font-medium mb-2")
        ui.label("从 Binance REST API 拉取最近的 K 线数据并写入 Parquet。").classes(
            "text-gray-500 text-sm mb-4"
        )

        with ui.row().classes("gap-4 flex-wrap"):
            symbol_in = (
                ui.select(
                    COMMON_SYMBOLS, value="BTCUSDT", label="交易对", with_input=True
                )
                .classes("min-w-40")
                .props("outlined dense")
            )
            tf_in = (
                ui.select(["1m", "5m", "15m", "1h"], value="1m", label="K 线周期")
                .classes("min-w-24")
                .props("outlined dense")
            )

        result_area = ui.column().classes("w-full mt-4")

        async def sync():
            result_area.clear()
            with result_area:
                ui.spinner("dots")
                ui.label("正在同步...")

            try:
                from src.data.fetcher.realtime import RealtimeSyncer

                syncer = RealtimeSyncer(
                    symbols=[symbol_in.value],
                    timeframes=[tf_in.value],
                    data_dir=str(PROJECT_ROOT / "data"),
                )

                rows = await syncer.sync_to_latest(symbol_in.value, tf_in.value)
                gaps_filled = await syncer.check_and_fill_gaps(
                    symbol_in.value, tf_in.value
                )

                await syncer.close()

                result_area.clear()
                with result_area:
                    ui.label("✅ 同步完成").classes("text-green-600 font-medium")
                    ui.label(f"  新数据: {rows} 条").classes("text-gray-500 text-sm")
                    ui.label(f"  缺口修复: {gaps_filled} 条").classes(
                        "text-gray-500 text-sm"
                    )

            except Exception as e:
                result_area.clear()
                with result_area:
                    ui.label(f"❌ 同步失败: {e}").classes("text-red-600")
                    import traceback

                    ui.label(traceback.format_exc()).classes(
                        "text-xs text-gray-400 font-mono whitespace-pre-wrap mt-2"
                    )

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("同步", on_click=sync).props("color=primary")
            ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()


def _delete_dataset_dialog():
    """删除数据集对话框 — 选择交易所/交易对/周期删除本地 Parquet 数据"""
    import shutil

    parquet_dir = PROJECT_ROOT / "data" / "parquet"

    # 扫描可删除的数据集
    datasets: list[dict] = []
    if parquet_dir.exists():
        for ex_dir in sorted(parquet_dir.iterdir()):
            if not ex_dir.is_dir():
                continue
            for sym_dir in sorted(ex_dir.iterdir()):
                if not sym_dir.is_dir():
                    continue
                for tf_dir in sorted(sym_dir.iterdir()):
                    if not tf_dir.is_dir():
                        continue
                    pq_files = list(tf_dir.glob("**/*.parquet"))
                    if not pq_files:
                        continue
                    total_size = sum(f.stat().st_size for f in pq_files)
                    if total_size >= 1024**2:
                        sz = f"{total_size / 1024**2:.1f} MB"
                    else:
                        sz = f"{total_size / 1024:.1f} KB"
                    datasets.append(
                        {
                            "label": f"{ex_dir.name}/{sym_dir.name}/{tf_dir.name}  ({sz})",
                            "path": str(tf_dir),
                            "exchange": ex_dir.name,
                            "symbol": sym_dir.name,
                            "timeframe": tf_dir.name,
                        }
                    )

    with ui.dialog() as dialog, ui.card().classes("min-w-[520px]"):
        ui.label("🗑️ 删除数据集").classes("text-lg font-medium mb-2")
        ui.label("选择要删除的本地 Parquet 数据集。删除后不可恢复！").classes(
            "text-red-500 text-sm mb-4"
        )

        if not datasets:
            ui.label("未找到本地数据集。").classes("text-gray-400")
        else:
            # 快捷清理按钮
            exchange_names = sorted({d["exchange"] for d in datasets})
            if "okx" in exchange_names:

                async def delete_all_okx():
                    okx_dir = parquet_dir / "okx"
                    if okx_dir.exists():
                        shutil.rmtree(okx_dir)
                        ui.notify("已删除所有 OKX 数据", type="positive")
                        dialog.close()

                with ui.row().classes(
                    "gap-2 mb-4 bg-orange-50 dark:bg-orange-900/20 rounded p-3"
                ):
                    ui.icon("warning").classes("text-orange-500")
                    ui.label("检测到 OKX 数据残留").classes(
                        "text-sm text-orange-700 dark:text-orange-300"
                    )
                    ui.button("一键清除全部 OKX 数据", on_click=delete_all_okx).props(
                        "flat dense color=orange size=sm"
                    )

            selected = (
                ui.select(
                    options={d["path"]: d["label"] for d in datasets},
                    label="选择数据集",
                    multiple=True,
                )
                .classes("w-full")
                .props("outlined dense use-chips")
            )

        result_area = ui.column().classes("w-full mt-4")

        async def do_delete():
            if not selected.value:
                ui.notify("请选择要删除的数据集", type="warning")
                return

            paths = (
                selected.value if isinstance(selected.value, list) else [selected.value]
            )
            deleted = 0
            for p in paths:
                try:
                    target = Path(p)
                    if target.exists() and target.is_dir():
                        shutil.rmtree(target)
                        deleted += 1
                        # 清理空的父目录
                        sym_dir = target.parent
                        if sym_dir.exists() and not any(sym_dir.iterdir()):
                            sym_dir.rmdir()
                            ex_dir = sym_dir.parent
                            if ex_dir.exists() and not any(ex_dir.iterdir()):
                                ex_dir.rmdir()
                except Exception as e:
                    logger.warning("delete_dataset_error", path=p, error=str(e))

            result_area.clear()
            with result_area:
                ui.label(f"✅ 已删除 {deleted} 个数据集").classes(
                    "text-green-600 font-medium"
                )
            ui.notify(f"已删除 {deleted} 个数据集", type="positive")

        with ui.row().classes("justify-end gap-2 mt-4"):
            if datasets:
                ui.button("删除选中", on_click=do_delete).props("color=red")
            ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()
