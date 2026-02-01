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
        ("📊 Parquet 数据集", str(stats["parquet_datasets"]), "个交易对"),
        ("💾 Parquet 大小", stats["parquet_size"], ""),
        ("📈 InfluxDB 连接", stats["influx_status"], stats["influx_message"]),
        ("🔄 最后同步", stats["last_sync"], ""),
    ]

    for title, value, subtitle in cards:
        with ui.card().classes("card min-w-48 flex-1"):
            ui.label(title).classes("text-sm text-gray-500 dark:text-gray-400")
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
                    on_click=lambda: ui.open("http://localhost:8086"),
                ).props("flat")

        # 连接状态
        status_container = ui.column().classes("w-full")

        async def check_influx():
            status_container.clear()
            with status_container:
                ui.spinner("dots").classes("mx-auto")

            try:
                import httpx

                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get("http://influxdb:8086/health")
                    if resp.status_code == 200:
                        data = resp.json()
                        status_container.clear()
                        with status_container:
                            ui.label("✅ InfluxDB 连接正常").classes(
                                "text-green-600 dark:text-green-400 font-medium"
                            )
                            ui.label(f"状态: {data.get('status', 'ready')}").classes(
                                "text-gray-500 mt-1"
                            )
                            ui.label(f"版本: {data.get('version', 'unknown')}").classes(
                                "text-gray-500"
                            )

                            # 显示数据统计
                            await _render_influx_stats(status_container)
                    else:
                        status_container.clear()
                        with status_container:
                            ui.label("⚠️ InfluxDB 响应异常").classes(
                                "text-yellow-600 dark:text-yellow-400"
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

        with ui.row().classes("gap-4 flex-wrap"):
            # 交易所选择
            exchange = ui.select(
                ["binance", "okx"],
                value="binance",
                label="交易所",
            ).classes("min-w-32")

            # 交易对输入
            symbols = ui.input(
                label="交易对",
                value="BTCUSDT,ETHUSDT",
                placeholder="逗号分隔多个交易对",
            ).classes("min-w-48")

            # 时间框架
            timeframe = ui.select(
                ["1m", "5m", "15m", "1h", "4h", "1d"],
                value="1m",
                label="时间框架",
            ).classes("min-w-24")

        with ui.row().classes("gap-4 mt-4"):
            # 开始日期
            start_date = ui.input(
                label="开始日期",
                value="2020-01-01",
            ).classes("min-w-36")

            # 结束日期
            end_date = ui.input(
                label="结束日期",
                value=datetime.now().strftime("%Y-%m-%d"),
            ).classes("min-w-36")

        # 下载按钮和进度
        with ui.row().classes("gap-4 mt-6 items-center"):
            download_btn = ui.button("开始下载", icon="download").props("color=primary")
            progress_label = ui.label("").classes("text-gray-500")

        # 命令预览
        with ui.expansion("查看命令", icon="code").classes("mt-4 w-full"):
            cmd_display = ui.code("").classes("w-full")

            def update_cmd():
                cmd = (
                    f"python -m scripts.fetch_history "
                    f"--exchange {exchange.value} "
                    f"--symbols {symbols.value} "
                    f"--tf {timeframe.value} "
                    f"--from {start_date.value} "
                    f"--to {end_date.value}"
                )
                cmd_display.set_content(cmd)

            for widget in [exchange, symbols, timeframe, start_date, end_date]:
                widget.on("update:model-value", lambda: update_cmd())

            update_cmd()

        # 下载日志
        log_area = ui.log(max_lines=20).classes("w-full h-48 mt-4")

        async def start_download():
            download_btn.disable()
            progress_label.set_text("正在下载...")
            log_area.push("开始下载...")

            try:
                from src.data.fetcher.history import HistoryFetcher

                fetcher = HistoryFetcher(
                    data_dir=PROJECT_ROOT / "data",
                    exchange=exchange.value,
                )

                symbol_list = [s.strip() for s in symbols.value.split(",")]
                start = datetime.strptime(start_date.value, "%Y-%m-%d").replace(tzinfo=UTC)
                end = datetime.strptime(end_date.value, "%Y-%m-%d").replace(tzinfo=UTC)

                async with fetcher:
                    for symbol in symbol_list:
                        log_area.push(f"下载 {symbol}...")
                        stats = await fetcher.download_and_save(
                            symbol=symbol,
                            timeframe=timeframe.value,
                            start_date=start,
                            end_date=end,
                        )
                        log_area.push(
                            f"  完成: {stats.completed_months} 月, "
                            f"{stats.total_rows:,} 行"
                        )

                progress_label.set_text("下载完成!")
                ui.notify("下载完成", type="positive")

            except Exception as e:
                log_area.push(f"错误: {e}")
                progress_label.set_text("下载失败")
                ui.notify(f"下载失败: {e}", type="negative")

            finally:
                download_btn.enable()

        download_btn.on_click(lambda: asyncio.create_task(start_download()))


def _render_sync_panel():
    """渲染实时同步面板"""
    with ui.card().classes("card w-full"):
        ui.label("实时数据同步").classes("text-lg font-medium mb-4")

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
            ui.button("检查", on_click=lambda: asyncio.create_task(check())).props(
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
            ui.button("同步", on_click=lambda: asyncio.create_task(sync())).props(
                "color=primary"
            )
            ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()
