"""
数据管理页面

功能:
- 显示 Parquet 数据状态
- 显示 InfluxDB 数据状态
- 数据缺口检测
- 历史数据下载控制
- 实时同步状态
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nicegui import ui

from services.web.download_tasks import format_eta, get_download_manager
from services.web.utils import candidate_urls
from src.core.config import get_settings
from src.ops.logging import get_logger

logger = get_logger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def render():
    """渲染数据管理页面"""
    ui.label("数据管理").classes("text-2xl font-bold mb-4")

    # 顶部统计卡片
    with ui.row().classes("w-full gap-4 flex-wrap"):
        _render_data_stats()

    # Tab 切换
    with ui.tabs().classes("w-full mt-4") as tabs:
        parquet_tab = ui.tab("Parquet 数据")
        influx_tab = ui.tab("InfluxDB 数据")
        download_tab = ui.tab("数据下载")
        sync_tab = ui.tab("实时同步")

    with ui.tab_panels(tabs, value=parquet_tab).classes("w-full"):
        with ui.tab_panel(parquet_tab):
            _render_parquet_data()

        with ui.tab_panel(influx_tab):
            _render_influx_data()

        with ui.tab_panel(download_tab):
            _render_download_panel()

        with ui.tab_panel(sync_tab):
            _render_sync_panel()


def _render_data_stats():
    """渲染数据统计卡片"""
    stats = _get_data_stats()

    cards = [
        ("📊 Parquet 数据集", str(stats["parquet_datasets"]), "个交易对", True),  # inline=True
        ("💾 Parquet 大小", stats["parquet_size"], "", False),
        ("📈 InfluxDB 连接", stats["influx_status"], stats["influx_message"], False),
        ("🔄 最后同步", stats["last_sync"], "", False),
    ]

    for title, value, subtitle, inline in cards:
        with ui.card().classes("card min-w-48 flex-1"):
            ui.label(title).classes("text-sm text-gray-500 dark:text-gray-400")
            if inline and subtitle:
                # 数字和单位在同一行
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
        "influx_status": "未知",
        "influx_message": "",
        "last_sync": "未知",
    }

    # 统计 Parquet 数据
    parquet_dir = PROJECT_ROOT / "data" / "parquet"
    if parquet_dir.exists():
        datasets = set()
        total_size = 0

        for parquet_file in parquet_dir.glob("**/*.parquet"):
            total_size += parquet_file.stat().st_size
            # 解析路径: exchange/symbol/timeframe/...
            parts = parquet_file.relative_to(parquet_dir).parts
            if len(parts) >= 2:
                datasets.add(f"{parts[0]}/{parts[1]}")

        stats["parquet_datasets"] = len(datasets)

        # 格式化大小
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


def _render_parquet_data():
    """渲染 Parquet 数据表格"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("Parquet 数据集").classes("text-lg font-medium")
            ui.button("刷新", icon="refresh", on_click=lambda: ui.notify("正在刷新...")).props(
                "flat"
            )

        # 加载数据
        datasets = _load_parquet_datasets()

        if not datasets:
            ui.label("暂无 Parquet 数据").classes("text-gray-400 text-center py-8")
            ui.label("使用以下命令下载历史数据:").classes("text-gray-500 text-center")
            ui.code(
                "python -m scripts.fetch_history --symbol BTCUSDT --tf 1m --from 2020-01-01"
            ).classes("mt-2")
        else:
            # 创建表格
            columns = [
                {"name": "exchange", "label": "交易所", "field": "exchange", "align": "left"},
                {"name": "symbol", "label": "交易对", "field": "symbol", "align": "left"},
                {"name": "timeframe", "label": "周期", "field": "timeframe", "align": "center"},
                {"name": "start", "label": "开始时间", "field": "start", "align": "center"},
                {"name": "end", "label": "结束时间", "field": "end", "align": "center"},
                {"name": "rows", "label": "数据量", "field": "rows", "align": "right"},
                {"name": "size", "label": "大小", "field": "size", "align": "right"},
                {"name": "gaps", "label": "缺口", "field": "gaps", "align": "center"},
            ]

            ui.table(columns=columns, rows=datasets, row_key="id").classes("w-full")


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
            # 计算大小
            path = (
                parquet_dir
                / item["exchange"].lower()
                / item["symbol"].replace("/", "_")
                / item["timeframe"]
            )
            size = sum(f.stat().st_size for f in path.glob("**/*.parquet")) if path.exists() else 0

            # 格式化
            start_str = item["range"][0].strftime("%Y-%m-%d") if item["range"] else "-"
            end_str = item["range"][1].strftime("%Y-%m-%d") if item["range"] else "-"

            # 检测缺口
            gaps = manager.detect_gaps(
                item["exchange"], item["symbol"].replace("/", ""), item["timeframe"]
            )

            datasets.append({
                "id": i,
                "exchange": item["exchange"].upper(),
                "symbol": item["symbol"],
                "timeframe": item["timeframe"],
                "start": start_str,
                "end": end_str,
                "rows": "-",  # 可以优化读取行数
                "size": f"{size / 1024 / 1024:.1f} MB" if size > 0 else "-",
                "gaps": f"⚠️ {len(gaps)}" if gaps else "✅ 0",
            })

    except Exception as e:
        logger.warning("load_parquet_datasets_error", error=str(e))

    return datasets


def _render_influx_data():
    """渲染 InfluxDB 数据信息"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("InfluxDB 数据").classes("text-lg font-medium")

            with ui.row().classes("gap-2"):
                ui.button(
                    "打开 InfluxDB UI",
                    icon="open_in_new",
                    on_click=lambda: ui.run_javascript(
                        "window.open('http://' + window.location.hostname + ':8086', '_blank')"
                    ),
                ).props("flat")

        # 连接状态
        status_container = ui.column().classes("w-full")

        async def check_influx():
            status_container.clear()
            with status_container:
                ui.spinner("dots").classes("mx-auto")

            try:
                import httpx
                settings = get_settings()

                async with httpx.AsyncClient(timeout=5.0) as client:
                    last_error: str | None = None
                    for url in candidate_urls(settings.influxdb.url, service_host="influxdb"):
                        try:
                            resp = await client.get(f"{url.rstrip('/')}/health")
                            if resp.status_code == 200:
                                data = resp.json()
                                status_container.clear()
                                with status_container:
                                    ui.label("✅ InfluxDB 连接正常").classes(
                                        "text-green-600 dark:text-green-400 font-medium"
                                    )
                                    ui.label(
                                        f"状态: {data.get('status', 'ready')}"
                                    ).classes("text-gray-500 mt-1")
                                    ui.label(
                                        f"版本: {data.get('version', 'unknown')}"
                                    ).classes("text-gray-500")

                                    # 显示数据统计
                                    await _render_influx_stats(status_container)
                                return
                            last_error = f"HTTP {resp.status_code}"
                            break
                        except httpx.ConnectError as e:
                            last_error = str(e)
                            continue

                    status_container.clear()
                    with status_container:
                        ui.label("⚠️ InfluxDB 响应异常").classes(
                            "text-yellow-600 dark:text-yellow-400"
                        )
                        if last_error:
                            ui.label(f"错误: {last_error}").classes(
                                "text-gray-500 text-sm mt-1"
                            )
            except Exception as e:
                status_container.clear()
                with status_container:
                    ui.label("❌ 无法连接到 InfluxDB").classes(
                        "text-red-600 dark:text-red-400"
                    )
                    ui.label(f"错误: {str(e)}").classes("text-gray-500 text-sm mt-1")
                    ui.label("提示: 确保 InfluxDB 服务正在运行").classes(
                        "text-gray-400 text-sm"
                    )

        ui.timer(0.1, check_influx, once=True)


async def _render_influx_stats(container):
    """渲染 InfluxDB 统计信息"""
    try:
        from src.core.config import get_settings

        settings = get_settings()

        with container:
            ui.separator().classes("my-4")
            ui.label("数据统计").classes("font-medium mb-2")

            # 查询最近数据
            from influxdb_client import InfluxDBClient

            client = InfluxDBClient(
                url=settings.influxdb.url,
                token=settings.influxdb.token.get_secret_value(),
                org=settings.influxdb.org,
            )

            query_api = client.query_api()

            # 查询各交易对的数据点数
            query = f'''
            from(bucket: "{settings.influxdb.bucket}")
                |> range(start: -30d)
                |> filter(fn: (r) => r["_measurement"] == "ohlcv")
                |> group(columns: ["exchange", "symbol", "timeframe"])
                |> count()
            '''

            try:
                tables = query_api.query(query)

                data_summary = []
                for table in tables:
                    for record in table.records:
                        data_summary.append({
                            "exchange": record.values.get("exchange", "unknown"),
                            "symbol": record.values.get("symbol", "unknown"),
                            "timeframe": record.values.get("timeframe", "unknown"),
                            "count": record.get_value(),
                        })

                if data_summary:
                    for item in data_summary[:10]:  # 最多显示 10 个
                        with ui.row().classes("gap-4 py-1"):
                            ui.label(f"{item['exchange']}/{item['symbol']}").classes(
                                "font-mono text-sm"
                            )
                            ui.label(item["timeframe"]).classes("text-gray-500 text-sm")
                            ui.label(f"{item['count']:,} 点").classes(
                                "text-gray-400 text-sm"
                            )
                else:
                    ui.label("暂无数据").classes("text-gray-400")

            except Exception as e:
                ui.label(f"查询失败: {e}").classes("text-gray-400 text-sm")

            client.close()

    except Exception as e:
        logger.warning("influx_stats_error", error=str(e))


def _render_download_panel():
    """渲染数据下载面板"""
    with ui.card().classes("card w-full"):
        ui.label("历史数据下载").classes("text-lg font-medium mb-4")
        manager = get_download_manager(PROJECT_ROOT / "data")

        # 常用交易对快捷选项
        common_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
            "ADAUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT"
        ]

        with ui.row().classes("gap-4 flex-wrap items-end"):
            # 交易所选择
            exchange = ui.select(
                ["binance", "okx"],
                value="binance",
                label="交易所",
            ).classes("min-w-32").props("outlined dense")

            # 交易对 - 多选下拉 + 自定义输入
            symbols_select = ui.select(
                common_symbols,
                value=["BTCUSDT", "ETHUSDT"],
                label="交易对",
                multiple=True,
                with_input=True,
            ).classes("min-w-64").props("outlined dense use-chips")

            # 时间框架
            timeframe = ui.select(
                ["1m", "5m", "15m", "1h", "4h", "1d"],
                value="1m",
                label="时间框架",
            ).classes("min-w-24").props("outlined dense")

        ui.separator().classes("my-4")

        # 日期范围 - 使用日期选择器
        with ui.row().classes("gap-4 items-end flex-wrap"):
            # 快捷日期选择
            with ui.column().classes("gap-1"):
                ui.label("快捷选择").classes("text-sm text-gray-500")
                with ui.row().classes("gap-2 flex-wrap"):
                    def set_date_range(months: int, start_ref, end_ref):
                        end = datetime.now()
                        start = end - timedelta(days=months * 30)
                        start_ref.value = start.strftime("%Y-%m-%d")
                        end_ref.value = end.strftime("%Y-%m-%d")

                    def set_full_range(start_ref, end_ref):
                        start_ref.value = "2020-01-01"
                        end_ref.value = datetime.now().strftime("%Y-%m-%d")

        # 日期输入框
        with ui.row().classes("gap-4 items-end mt-2"):
            # 开始日期
            with ui.input(label="开始日期", value="2020-01-01").classes("min-w-40").props("outlined dense") as start_input:
                with ui.menu().props('no-parent-event') as start_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(start_input):
                        with ui.row().classes('justify-end'):
                            ui.button('确定', on_click=start_menu.close).props('flat')
                with start_input.add_slot('append'):
                    ui.icon('event').on('click', start_menu.open).classes('cursor-pointer')

            # 结束日期
            with ui.input(label="结束日期", value=datetime.now().strftime("%Y-%m-%d")).classes("min-w-40").props("outlined dense") as end_input:
                with ui.menu().props('no-parent-event') as end_menu:
                    with ui.date(mask="YYYY-MM-DD").bind_value(end_input):
                        with ui.row().classes('justify-end'):
                            ui.button('确定', on_click=end_menu.close).props('flat')
                with end_input.add_slot('append'):
                    ui.icon('event').on('click', end_menu.open).classes('cursor-pointer')

        # 快捷按钮 - 放在日期输入后面
        with ui.row().classes("gap-2 mt-2 flex-wrap"):
            ui.button("近 3 月", on_click=lambda: set_date_range(3, start_input, end_input)).props("flat dense size=sm")
            ui.button("近 6 月", on_click=lambda: set_date_range(6, start_input, end_input)).props("flat dense size=sm")
            ui.button("近 1 年", on_click=lambda: set_date_range(12, start_input, end_input)).props("flat dense size=sm")
            ui.button("近 2 年", on_click=lambda: set_date_range(24, start_input, end_input)).props("flat dense size=sm")
            ui.button("全部 (2020起)", on_click=lambda: set_full_range(start_input, end_input)).props("flat dense size=sm")

        # 下载按钮和进度
        with ui.row().classes("gap-4 mt-6 items-center"):
            download_btn = ui.button("加入队列", icon="download").props("color=primary")
            progress_label = ui.label("").classes("text-gray-500")

        # 命令预览
        with ui.expansion("查看命令", icon="code").classes("mt-4 w-full"):
            cmd_display = ui.code("").classes("w-full")

            def update_cmd():
                # 处理多选的 symbols
                selected = symbols_select.value if symbols_select.value else []
                symbols_str = ",".join(selected) if isinstance(selected, list) else selected
                cmd = (
                    f"python -m scripts.fetch_history "
                    f"--exchange {exchange.value} "
                    f"--symbols {symbols_str} "
                    f"--tf {timeframe.value} "
                    f"--from {start_input.value} "
                    f"--to {end_input.value}"
                )
                cmd_display.set_content(cmd)

            for widget in [exchange, symbols_select, timeframe, start_input, end_input]:
                widget.on("update:model-value", lambda _: update_cmd())

            update_cmd()

        # 下载日志
        log_area = ui.log(max_lines=20).classes("w-full h-48 mt-4")

        async def start_download():
            # 处理多选的 symbols
            selected = symbols_select.value if symbols_select.value else []
            symbol_list = selected if isinstance(selected, list) else [selected]
            start = datetime.strptime(start_input.value, "%Y-%m-%d").replace(
                tzinfo=UTC
            )
            end = datetime.strptime(end_input.value, "%Y-%m-%d").replace(tzinfo=UTC)

            task = await manager.enqueue(
                exchange=exchange.value,
                symbols=symbol_list,
                timeframe=timeframe.value,
                start_date=start,
                end_date=end,
            )

            progress_label.set_text("已加入队列")
            log_area.push(
                f"任务已加入队列: {task.id} ({exchange.value} {','.join(symbol_list)})"
            )
            ui.notify(f"任务 {task.id} 已加入队列", type="positive")

        download_btn.on_click(start_download)

        # 下载任务队列
        with ui.column().classes("w-full mt-4") as tasks_container:
            ui.label("下载任务").classes("text-base font-medium")

        def render_tasks():
            tasks_container.clear()
            with tasks_container:
                ui.label("下载任务").classes("text-base font-medium")
                tasks = manager.list_tasks()
                if not tasks:
                    ui.label("暂无任务").classes("text-gray-400")
                    return

                for task in tasks[:5]:
                    with ui.card().classes("w-full"):
                        title = (
                            f"{task.exchange} · {','.join(task.symbols)} · {task.timeframe}"
                        )
                        ui.label(title).classes("font-medium")
                        ui.label(
                            f"状态: {task.status} | 进度: {task.progress:.1f}%"
                        ).classes("text-xs text-gray-500")
                        if task.current_symbol:
                            ui.label(f"当前: {task.current_symbol}").classes(
                                "text-xs text-gray-500"
                            )
                        ui.linear_progress(value=task.progress / 100).props("size=8px")
                        ui.label(
                            f"{task.completed_units}/{task.total_units} 月 | ETA {format_eta(task.eta_seconds)}"
                        ).classes("text-xs text-gray-400")

        ui.timer(1.0, render_tasks)


def _render_sync_panel():
    """渲染实时同步面板"""
    # 当前数据状态卡片
    with ui.card().classes("card w-full mb-4"):
        ui.label("📊 当前数据状态").classes("text-lg font-medium mb-4")

        status_container = ui.column().classes("w-full")

        async def load_data_status():
            """加载所有交易对的数据状态"""
            status_container.clear()
            with status_container:
                ui.spinner("dots").classes("mx-auto")

            try:
                from src.data.fetcher.manager import DataManager

                manager = DataManager(data_dir=PROJECT_ROOT / "data")
                data_list = manager.list_available_data()

                status_container.clear()
                with status_container:
                    if not data_list:
                        ui.label("暂无数据，请先下载历史数据").classes("text-gray-400")
                        return

                    # 表格显示
                    rows = []
                    for item in data_list:
                        symbol = item["symbol"].replace("/", "")
                        tf = item["timeframe"]
                        range_info = item.get("range", (None, None))

                        # 检查缺口
                        gaps = manager.detect_gaps(item["exchange"], symbol, tf)
                        gap_count = len(gaps) if gaps else 0

                        # 计算数据覆盖
                        if range_info[0] and range_info[1]:
                            start_str = range_info[0].strftime("%Y-%m-%d")
                            end_str = range_info[1].strftime("%Y-%m-%d")
                            # 计算距今天数
                            days_behind = (datetime.now(UTC) - range_info[1]).days
                            freshness = "✅ 最新" if days_behind <= 1 else f"⚠️ 落后 {days_behind} 天"
                        else:
                            start_str = "-"
                            end_str = "-"
                            freshness = "❓ 未知"

                        rows.append({
                            "id": f"{item['exchange']}_{symbol}_{tf}",
                            "exchange": item["exchange"].upper(),
                            "symbol": symbol,
                            "timeframe": tf,
                            "start": start_str,
                            "end": end_str,
                            "freshness": freshness,
                            "gaps": f"⚠️ {gap_count}" if gap_count > 0 else "✅ 0",
                        })

                    columns = [
                        {"name": "exchange", "label": "交易所", "field": "exchange", "align": "left"},
                        {"name": "symbol", "label": "交易对", "field": "symbol", "align": "left"},
                        {"name": "timeframe", "label": "周期", "field": "timeframe", "align": "center"},
                        {"name": "start", "label": "开始", "field": "start", "align": "center"},
                        {"name": "end", "label": "结束", "field": "end", "align": "center"},
                        {"name": "freshness", "label": "新鲜度", "field": "freshness", "align": "center"},
                        {"name": "gaps", "label": "缺口", "field": "gaps", "align": "center"},
                    ]

                    ui.table(columns=columns, rows=rows, row_key="id").classes("w-full")

            except Exception as e:
                status_container.clear()
                with status_container:
                    ui.label(f"❌ 加载失败: {e}").classes("text-red-600")

        # 自动加载
        ui.timer(0.1, load_data_status, once=True)

        # 刷新按钮
        with ui.row().classes("mt-4"):
            ui.button("刷新状态", icon="refresh", on_click=load_data_status).props("flat")

    # 实时同步配置
    with ui.card().classes("card w-full"):
        ui.label("🔄 实时同步服务").classes("text-lg font-medium mb-4")

        ui.label(
            "实时同步服务会持续从交易所获取最新 K 线数据，并自动补齐缺口。"
        ).classes("text-gray-500 mb-4")

        # 同步配置
        with ui.row().classes("gap-4 flex-wrap"):
            symbols = ui.input(
                label="交易对",
                value="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT",
            ).classes("min-w-64")

            timeframes = ui.input(
                label="时间框架",
                value="1m",
            ).classes("min-w-24")

        # 启动命令
        with ui.expansion("启动命令", icon="code").classes("mt-4 w-full"):
            ui.markdown("""
```bash
# 前台运行 (用于调试)
docker-compose exec collector python -m scripts.realtime_sync \\
    --symbols BTCUSDT,ETHUSDT --timeframes 1m,1h

# 后台运行
docker-compose --profile data up realtime-sync -d

# 查看日志
docker-compose logs -f realtime-sync
```
            """)

        # 快速操作
        with ui.row().classes("gap-4 mt-4"):
            ui.button(
                "检查缺口",
                icon="search",
                on_click=lambda: _check_gaps_dialog(),
            ).props("outline")

            ui.button(
                "手动同步",
                icon="sync",
                on_click=lambda: _manual_sync_dialog(),
            ).props("outline")


def _check_gaps_dialog():
    """检查缺口对话框"""
    with ui.dialog() as dialog, ui.card().classes("min-w-96"):
        ui.label("检查数据缺口").classes("text-lg font-medium mb-4")

        symbol_input = ui.input(label="交易对", value="BTCUSDT")
        tf_input = ui.select(["1m", "5m", "15m", "1h", "4h", "1d"], value="1m", label="时间框架")

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

            except Exception as e:
                result_area.clear()
                with result_area:
                    ui.label(f"❌ 错误: {e}").classes("text-red-600")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("检查", on_click=check).props(
                "color=primary"
            )
            ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()


def _manual_sync_dialog():
    """手动同步对话框"""
    with ui.dialog() as dialog, ui.card().classes("min-w-96"):
        ui.label("手动同步最新数据").classes("text-lg font-medium mb-4")

        symbol_input = ui.input(label="交易对", value="BTCUSDT")
        tf_input = ui.select(["1m", "5m", "15m", "1h"], value="1m", label="时间框架")

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
                    ui.label(f"✅ 同步完成").classes("text-green-600")
                    ui.label(f"  新数据: {rows} 条").classes("text-gray-500")
                    ui.label(f"  缺口修复: {gaps_filled} 条").classes("text-gray-500")

            except Exception as e:
                result_area.clear()
                with result_area:
                    ui.label(f"❌ 错误: {e}").classes("text-red-600")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("同步", on_click=sync).props(
                "color=primary"
            )
            ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()
