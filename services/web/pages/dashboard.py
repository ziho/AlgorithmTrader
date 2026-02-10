"""
Dashboard 页面

系统状态概览:
- 服务健康状态
- 数据采集状态（历史数据覆盖、缺口、最新更新）
- 回测进程状态
- 实盘策略运行状态
- 快捷链接
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from nicegui import ui

from services.web.components import status_card
from services.web.download_tasks import format_eta, get_download_manager
from services.web.service_monitor import ServiceStatus, get_monitor
from services.web.strategy_config import StrategyConfigManager

# 配置路径
CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "strategies.json"
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def render():
    """渲染 Dashboard 页面"""
    ui.label("Dashboard").classes("text-2xl font-bold mb-4")

    with ui.row().classes("w-full gap-4 flex-wrap") as status_row:
        _render_service_status(status_row)

    with ui.row().classes("w-full mt-4"):
        _render_quick_links()

    with ui.row().classes("w-full gap-4 mt-4"):
        _render_data_status_overview()

    with ui.row().classes("w-full gap-4 mt-4"):
        _render_download_task_overview()

    with ui.row().classes("w-full gap-4 mt-4"):
        with ui.column().classes("flex-1 min-w-80"):
            _render_live_trading_status()
        with ui.column().classes("flex-1 min-w-80"):
            _render_backtest_status()

    with ui.row().classes("w-full gap-4 mt-4"):
        with ui.column().classes("flex-1 min-w-80"):
            _render_recent_alerts()
        with ui.column().classes("flex-1 min-w-80"):
            _render_recent_backtests()


async def _fetch_service_statuses() -> list[ServiceStatus]:
    """获取服务状态（异步）"""
    try:
        monitor = get_monitor()
        return await monitor.check_all()
    except Exception:
        # 获取失败时返回模拟数据
        return get_monitor().get_mock_statuses()


def _render_service_status(container):
    """渲染服务状态"""
    # 使用模拟数据先显示，然后异步更新
    monitor = get_monitor()
    statuses = monitor.get_mock_statuses()

    for status in statuses:
        with container:
            status_card.render(
                title=status.name,
                status=status.status,
                message=status.message,
                url=getattr(status, "url", None),
            )

    # 后台异步获取真实状态
    async def update_statuses():
        try:
            real_statuses = await _fetch_service_statuses()
            container.clear()
            with container:
                for status in real_statuses:
                    status_card.render(
                        title=status.name,
                        status=status.status,
                        message=status.message,
                        url=getattr(status, "url", None),
                    )
        except Exception:
            pass  # 保持模拟数据

    # 启动异步更新
    ui.timer(0.5, update_statuses, once=True)


def _render_quick_links():
    """渲染快捷链接"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center"):
            ui.label("快捷入口").classes("text-lg font-medium")

            with ui.row().classes("gap-2"):
                # 使用当前浏览器的 host，自动适配内网/VPN/公网访问
                ui.button(
                    "Grafana 监控面板",
                    icon="dashboard",
                    on_click=lambda: ui.run_javascript(
                        "window.open('http://' + window.location.hostname + ':3000', '_blank')"
                    ),
                ).props("flat color=blue")

                ui.button(
                    "InfluxDB 数据库",
                    icon="storage",
                    on_click=lambda: ui.run_javascript(
                        "window.open('http://' + window.location.hostname + ':8086', '_blank')"
                    ),
                ).props("flat color=purple")

                ui.button(
                    "数据管理",
                    icon="folder_open",
                    on_click=lambda: ui.navigate.to("/data"),
                ).props("flat color=green")


def _render_data_status_overview():
    """渲染数据状态概览"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("📊 数据采集状态").classes("text-lg font-medium")
            ui.button(
                "查看详情",
                icon="arrow_forward",
                on_click=lambda: ui.navigate.to("/data"),
            ).props("flat size=sm")

        status_container = ui.column().classes("w-full")

        async def load_data_status():
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
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("warning").classes("text-yellow-500")
                            ui.label("暂无数据").classes("text-yellow-600")
                        ui.link("→ 前往下载历史数据", "/data").classes(
                            "text-sm text-blue-500"
                        )
                        return

                    # 统计概览
                    total_symbols = len(data_list)
                    total_gaps = 0
                    outdated_count = 0
                    latest_update = None

                    for item in data_list:
                        symbol = item["symbol"].replace("/", "")
                        tf = item["timeframe"]
                        gaps = manager.detect_gaps(item["exchange"], symbol, tf)
                        if gaps:
                            total_gaps += len(gaps)

                        range_info = item.get("range", (None, None))
                        if range_info[1]:
                            days_behind = (datetime.now(UTC) - range_info[1]).days
                            if days_behind > 1:
                                outdated_count += 1
                            if latest_update is None or range_info[1] > latest_update:
                                latest_update = range_info[1]

                    # 显示概览卡片
                    with ui.row().classes("w-full gap-4 flex-wrap"):
                        # 数据集数量
                        with ui.column().classes("flex-1 min-w-32"):
                            with ui.row().classes("items-baseline gap-1"):
                                ui.label(str(total_symbols)).classes(
                                    "text-2xl font-bold text-blue-600"
                                )
                                ui.label("个交易对").classes("text-sm text-gray-500")

                        # 缺口状态
                        with ui.column().classes("flex-1 min-w-32"):
                            if total_gaps == 0:
                                with ui.row().classes("items-center gap-1"):
                                    ui.icon("check_circle").classes("text-green-500")
                                    ui.label("无缺口").classes(
                                        "text-green-600 font-medium"
                                    )
                            else:
                                with ui.row().classes("items-center gap-1"):
                                    ui.icon("warning").classes("text-yellow-500")
                                    ui.label(f"{total_gaps} 个缺口").classes(
                                        "text-yellow-600 font-medium"
                                    )

                        # 数据新鲜度
                        with ui.column().classes("flex-1 min-w-32"):
                            if outdated_count == 0:
                                with ui.row().classes("items-center gap-1"):
                                    ui.icon("check_circle").classes("text-green-500")
                                    ui.label("数据最新").classes(
                                        "text-green-600 font-medium"
                                    )
                            else:
                                with ui.row().classes("items-center gap-1"):
                                    ui.icon("update").classes("text-yellow-500")
                                    ui.label(f"{outdated_count} 个落后").classes(
                                        "text-yellow-600 font-medium"
                                    )

                        # 最后更新
                        with ui.column().classes("flex-1 min-w-40"):
                            ui.label("最后更新").classes("text-xs text-gray-400")
                            if latest_update:
                                time_ago = datetime.now(UTC) - latest_update
                                if time_ago.days > 0:
                                    time_str = f"{time_ago.days} 天前"
                                elif time_ago.seconds > 3600:
                                    time_str = f"{time_ago.seconds // 3600} 小时前"
                                else:
                                    time_str = f"{time_ago.seconds // 60} 分钟前"
                                ui.label(time_str).classes("font-medium")
                            else:
                                ui.label("-").classes("font-medium")

            except Exception as e:
                status_container.clear()
                with status_container:
                    ui.label(f"加载失败: {e}").classes("text-red-500 text-sm")

        ui.timer(0.1, load_data_status, once=True)


def _render_download_task_overview():
    """渲染下载任务概览"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-2"):
            ui.label("⬇️ 下载任务").classes("text-lg font-medium")
            ui.link("查看详情 →", "/data").classes("text-sm text-blue-500")

        manager = get_download_manager(PROJECT_ROOT / "data")
        tasks_container = ui.column().classes("w-full")

        _prev_snap: list[tuple] = []

        def render_tasks():
            tasks = manager.get_active_tasks()
            snap = [(t.id, t.status, round(t.progress, 1)) for t in tasks[:3]]
            if snap == _prev_snap:
                return
            _prev_snap.clear()
            _prev_snap.extend(snap)

            tasks_container.clear()
            with tasks_container:
                if not tasks:
                    ui.label("暂无进行中的任务").classes("text-gray-400")
                    return

                for task in tasks[:3]:
                    with ui.row().classes("w-full items-center gap-4 py-2"):
                        with ui.column().classes("flex-1"):
                            ui.label(
                                f"{task.exchange} · {','.join(task.symbols)} · {task.timeframe}"
                            ).classes("text-sm font-medium")
                            status_text = {
                                "queued": "等待中",
                                "running": "下载中",
                            }.get(task.status, task.status)
                            eta_text = (
                                f" · ETA {format_eta(task.eta_seconds)}"
                                if task.eta_seconds
                                else ""
                            )
                            ui.label(f"{status_text}{eta_text}").classes(
                                "text-xs text-gray-500"
                            )
                        with ui.column().classes("min-w-40"):
                            bar_color = (
                                "light-blue-7" if task.status == "running" else "grey-5"
                            )
                            ui.linear_progress(value=task.progress / 100).props(
                                f'size="10px" color="{bar_color}" track-color="grey-3" rounded'
                            )
                            ui.label(f"{task.progress:.1f}%").classes(
                                "text-xs text-center font-medium text-gray-700 dark:text-gray-300 mt-0.5"
                            )

        from services.web.utils import safe_timer

        safe_timer(2.0, render_tasks)


def _render_live_trading_status():
    """渲染实盘交易状态"""
    with ui.card().classes("card w-full h-full"):
        ui.label("🤖 实盘交易").classes("text-lg font-medium mb-4")

        # 从策略配置获取数据
        try:
            manager = StrategyConfigManager(config_path=CONFIG_PATH)
            manager.load()
            strategies = manager.get_all()
            enabled_strategies = [s for s in strategies if s.enabled]
        except Exception:
            enabled_strategies = []

        if not enabled_strategies:
            with ui.column().classes("items-center py-4"):
                ui.icon("pause_circle").classes("text-4xl text-gray-300")
                ui.label("暂无运行中的策略").classes("text-gray-400 mt-2")
                ui.link("→ 配置策略", "/strategies").classes(
                    "text-sm text-blue-500 mt-1"
                )
        else:
            for strategy in enabled_strategies[:3]:  # 最多显示3个
                with ui.row().classes(
                    "w-full items-center gap-3 py-2 border-b border-gray-100 dark:border-gray-700"
                ):
                    ui.icon("play_circle").classes("text-green-500")
                    with ui.column().classes("flex-1"):
                        ui.label(strategy.name).classes("font-medium")
                        ui.label(f"{strategy.symbol} · {strategy.timeframe}").classes(
                            "text-xs text-gray-400"
                        )
                    # TODO: 从实盘服务获取真实数据
                    with ui.column().classes("items-end"):
                        ui.label("0 笔").classes("text-sm")
                        ui.label("$0.00").classes("text-xs text-gray-400")

            if len(enabled_strategies) > 3:
                ui.link(
                    f"查看全部 {len(enabled_strategies)} 个策略 →", "/strategies"
                ).classes("text-sm text-blue-500 mt-2")


def _render_backtest_status():
    """渲染回测进程状态"""
    with ui.card().classes("card w-full"):
        ui.label("⚡ 回测进程").classes("text-lg font-medium mb-4")

        # 检查是否有正在运行的回测
        from services.web.backtest_manager import BacktestResultManager

        try:
            config_path = PROJECT_ROOT / "config" / "backtests.json"
            manager = BacktestResultManager(config_path=config_path)
            records = manager.get_all()
            running = [r for r in records if r.status == "running"]
        except Exception:
            running = []

        if not running:
            with ui.column().classes("items-center py-4"):
                ui.icon("hourglass_empty").classes("text-4xl text-gray-300")
                ui.label("暂无运行中的回测").classes("text-gray-400 mt-2")
                ui.link("→ 开始新回测", "/backtests").classes(
                    "text-sm text-blue-500 mt-1"
                )
        else:
            for bt in running:
                with ui.row().classes("w-full items-center gap-3 py-2"):
                    ui.spinner(size="sm")
                    with ui.column().classes("flex-1"):
                        ui.label(bt.strategy_class).classes("font-medium")
                        ui.label(
                            f"{bt.symbol} · {bt.start_date} ~ {bt.end_date}"
                        ).classes("text-xs text-gray-400")


def _render_recent_alerts():
    """渲染最近告警"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("⚠️ 最近告警").classes("text-lg font-medium")

            async def clear_old_logs():
                """清理旧的错误日志"""
                log_dir = Path(__file__).parent.parent.parent.parent / "logs"
                if not log_dir.exists():
                    ui.notify("日志目录不存在", type="warning")
                    return
                cleared = 0
                for log_file in log_dir.glob("*.log"):
                    try:
                        # 只保留最后 50 行 (清除历史错误)
                        lines = log_file.read_text().strip().split("\n")
                        if len(lines) > 50:
                            log_file.write_text("\n".join(lines[-50:]) + "\n")
                            cleared += 1
                    except Exception:
                        pass
                ui.notify(f"已清理 {cleared} 个日志文件", type="positive")
                # 刷新页面
                ui.navigate.reload()

            ui.button("清理日志", icon="delete_sweep", on_click=clear_old_logs).props(
                "flat dense color=grey"
            )

        # 从日志文件加载真实告警
        alerts = _load_recent_alerts()

        if not alerts:
            ui.label("暂无告警 ✅").classes("text-gray-400 text-center py-4")
        else:
            for alert in alerts:
                _render_alert_item(alert)


def _load_recent_alerts() -> list[dict]:
    """加载最近告警（从 JSON 结构化日志读取）"""
    import json
    from pathlib import Path

    alerts: list[dict] = []
    seen_messages: set[str] = set()  # 去重
    log_dir = Path(__file__).parent.parent.parent.parent / "logs"

    # 读取所有日志文件
    log_files = (
        sorted(log_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]
        if log_dir.exists()
        else []
    )

    for log_file in log_files:
        try:
            lines = log_file.read_text().split("\n")[-200:]  # 最后200行
            for line in reversed(lines):
                if len(alerts) >= 8:
                    break

                line = line.strip()
                if not line:
                    continue

                # 尝试 JSON 解析（structlog 输出）
                try:
                    entry = json.loads(line)
                    level = entry.get("level", "").lower()
                    if level not in ("error", "warning"):
                        continue

                    event = entry.get("event", "")
                    error = entry.get("error", "")
                    logger_name = entry.get("logger", "")
                    timestamp = entry.get("timestamp", "")

                    # 构建可读消息
                    if error:
                        # 尝试解析嵌套的 JSON 错误（如 OKX 返回）
                        try:
                            # "okx {\"msg\":\"Invalid OK-ACCESS-KEY\",\"code\":\"50111\"}"
                            if error.startswith("okx "):
                                inner = json.loads(error[4:])
                                message = f"[{event}] OKX: {inner.get('msg', error)} (code: {inner.get('code', '?')})"
                            else:
                                message = f"[{event}] {error}"
                        except (json.JSONDecodeError, Exception):
                            message = f"[{event}] {error}" if event else error
                    elif event:
                        message = event
                    else:
                        continue

                    # 去重: 相同事件+错误只保留最新一条
                    dedup_key = f"{event}|{error[:50]}"
                    if dedup_key in seen_messages:
                        continue
                    seen_messages.add(dedup_key)

                    # 格式化时间
                    time_str = _format_log_time(timestamp)

                    # 来源 (从 logger 提取简短名)
                    source = (
                        logger_name.split(".")[-1] if logger_name else log_file.stem
                    )

                    alerts.append(
                        {
                            "level": level,
                            "message": message[:120],
                            "time": time_str,
                            "source": source,
                        }
                    )

                except json.JSONDecodeError:
                    # 非 JSON 格式日志行，使用旧方式解析
                    if "error" in line.lower():
                        import re

                        match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line)
                        time_str = match.group(0) if match else "未知时间"
                        message = (
                            line[line.find("]") + 1 :].strip()
                            if "]" in line
                            else line[:100]
                        )
                        dedup_key = message[:50]
                        if dedup_key not in seen_messages:
                            seen_messages.add(dedup_key)
                            alerts.append(
                                {
                                    "level": "error",
                                    "message": message[:120],
                                    "time": time_str,
                                    "source": log_file.stem,
                                }
                            )

        except Exception:
            pass

    return alerts


def _format_log_time(timestamp: str) -> str:
    """格式化日志时间为相对时间"""
    try:
        from datetime import UTC
        from datetime import datetime as dt

        ts = dt.fromisoformat(timestamp)
        now = dt.now(UTC)
        diff = now - ts

        if diff.days > 0:
            return f"{diff.days}天前"
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours}小时前"
        minutes = diff.seconds // 60
        if minutes > 0:
            return f"{minutes}分钟前"
        return "刚刚"
    except Exception:
        # 回退：截取时间部分
        if "T" in timestamp:
            return timestamp.split("T")[1][:8]
        return timestamp[:19]


def _render_alert_item(alert: dict):
    """渲染单个告警项"""
    level_colors = {
        "info": "text-blue-600 dark:text-blue-400",
        "warning": "text-yellow-600 dark:text-yellow-400",
        "error": "text-red-600 dark:text-red-400",
    }

    level_icons = {
        "info": "info",
        "warning": "warning",
        "error": "error",
    }

    with ui.row().classes(
        "w-full items-start gap-3 py-2 border-b border-gray-100 dark:border-gray-700 last:border-0"
    ):
        ui.icon(level_icons.get(alert["level"], "info")).classes(
            f"text-lg {level_colors.get(alert['level'], '')}"
        )
        with ui.column().classes("flex-1 gap-0"):
            ui.label(alert["message"]).classes("text-sm")
            with ui.row().classes("gap-2"):
                ui.label(alert["time"]).classes("text-xs text-gray-400")
                source = alert.get("source", "")
                if source:
                    ui.label(f"· {source}").classes("text-xs text-gray-400")


def _render_recent_backtests():
    """渲染最近回测"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("最近回测").classes("text-lg font-medium")
            ui.link("查看全部 →", "/backtests").classes(
                "text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400"
            )

        # 从回测管理器获取真实数据
        backtests = _load_recent_backtests()

        if not backtests:
            ui.label("暂无回测记录").classes("text-gray-400 text-center py-4")
        else:
            for bt in backtests:
                _render_backtest_item(bt)


def _load_recent_backtests() -> list[dict]:
    """加载最近回测记录"""
    from services.web.backtest_manager import BacktestResultManager

    try:
        config_path = (
            Path(__file__).parent.parent.parent.parent / "config" / "backtests.json"
        )
        manager = BacktestResultManager(config_path=config_path)
        records = manager.get_recent(n=5)

        backtests = []
        for record in records:
            metrics = record.metrics or {}
            total_return = metrics.get("total_return", 0)
            sharpe = metrics.get("sharpe_ratio", 0)

            # 格式化返回数据
            if record.status == "completed" and total_return != 0:
                return_str = (
                    f"+{total_return:.1%}"
                    if total_return >= 0
                    else f"{total_return:.1%}"
                )
                sharpe_str = f"{sharpe:.2f}" if sharpe else "-"
            else:
                return_str = "-"
                sharpe_str = "-"

            backtests.append(
                {
                    "strategy": record.strategy_class,
                    "period": f"{record.start_date} ~ {record.end_date}",
                    "return": return_str,
                    "sharpe": sharpe_str,
                    "status": record.status,
                }
            )

        return backtests
    except Exception:
        return []


def _render_backtest_item(backtest: dict):
    """渲染单个回测项"""
    with ui.row().classes(
        "w-full items-center gap-4 py-2 border-b border-gray-100 dark:border-gray-700 last:border-0"
    ):
        with ui.column().classes("flex-1 gap-0"):
            ui.label(backtest["strategy"]).classes("text-sm font-medium")
            ui.label(backtest["period"]).classes("text-xs text-gray-400")

        if backtest["status"] == "completed":
            with ui.column().classes("items-end gap-0"):
                ret = backtest["return"]
                if ret != "-":
                    return_class = (
                        "text-green-600" if ret.startswith("+") else "text-red-600"
                    )
                else:
                    return_class = "text-gray-400"
                ui.label(ret).classes(f"text-sm font-medium {return_class}")
                ui.label(f"Sharpe {backtest['sharpe']}").classes(
                    "text-xs text-gray-400"
                )
        elif backtest["status"] == "running":
            ui.spinner(size="sm")
        else:
            ui.label(backtest["status"]).classes("text-xs text-gray-400")


def _render_notification_test():
    """渲染通知测试区域"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("通知测试").classes("text-lg font-medium")

        # 显示当前配置的 Webhook URL
        webhook_url = os.getenv("WEBHOOK_URL", "")
        bark_configured = webhook_url and "api.day.app" in webhook_url

        with ui.row().classes("gap-4 items-center"):
            if bark_configured:
                ui.label("✅ Bark 已配置").classes("text-green-600 dark:text-green-400")
                # 隐藏敏感部分
                masked_url = webhook_url[:30] + "..."
                ui.label(masked_url).classes("text-gray-500 text-sm font-mono")
            elif webhook_url:
                ui.label("✅ Webhook 已配置").classes(
                    "text-green-600 dark:text-green-400"
                )
            else:
                ui.label("⚠️ 通知未配置").classes("text-yellow-600 dark:text-yellow-400")
                ui.label("请在 .env 中设置 WEBHOOK_URL").classes(
                    "text-gray-500 text-sm"
                )

        # 测试按钮
        result_label = ui.label("").classes("mt-2")

        async def send_test_notification():
            result_label.set_text("正在发送...")

            try:
                from src.ops.notify import send_notification

                await send_notification(
                    title="AlgorithmTrader 测试",
                    message="这是一条测试通知，如果您收到此消息说明通知功能正常工作。",
                    level="info",
                )
                result_label.set_text("✅ 测试通知已发送!")
                result_label.classes(remove="text-red-600", add="text-green-600")
                ui.notify("测试通知已发送", type="positive")

            except Exception as e:
                result_label.set_text(f"❌ 发送失败: {e}")
                result_label.classes(remove="text-green-600", add="text-red-600")
                ui.notify(f"发送失败: {e}", type="negative")

        with ui.row().classes("gap-2 mt-4"):
            notify_btn = ui.button(
                "发送测试通知",
                icon="notifications",
                on_click=send_test_notification,
            ).props("color=primary")
            if not webhook_url:
                notify_btn.disable()
