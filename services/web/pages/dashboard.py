"""
Dashboard 页面

系统状态概览:
- 服务健康状态
- 快捷链接 (Grafana, InfluxDB)
- 运行中的策略
- 最近告警
- 最近回测
- 通知测试
"""

import asyncio
import os
from pathlib import Path

from nicegui import ui

from services.web.components import status_card
from services.web.service_monitor import ServiceStatus, get_monitor
from services.web.strategy_config import StrategyConfigManager

# 配置路径
CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "strategies.json"


def render():
    """渲染 Dashboard 页面"""
    ui.label("Dashboard").classes("text-2xl font-bold mb-4")

    # 服务状态区域
    with ui.row().classes("w-full gap-4 flex-wrap") as status_row:
        _render_service_status(status_row)

    # 快捷链接
    with ui.row().classes("w-full gap-4 mt-4"):
        _render_quick_links()

    # 统计卡片
    with ui.row().classes("w-full gap-4 flex-wrap mt-4"):
        _render_stats_cards()

    # 下方两栏布局
    with ui.row().classes("w-full gap-4 mt-4"):
        # 最近告警
        with ui.column().classes("flex-1 min-w-80"):
            _render_recent_alerts()

        # 最近回测
        with ui.column().classes("flex-1 min-w-80"):
            _render_recent_backtests()

    # 通知测试区域
    with ui.row().classes("w-full mt-4"):
        _render_notification_test()


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
                url=getattr(status, 'url', None),
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
                        url=getattr(status, 'url', None),
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
                ui.button(
                    "Grafana 监控面板",
                    icon="dashboard",
                    on_click=lambda: ui.open("http://localhost:3000"),
                ).props("flat color=blue")

                ui.button(
                    "InfluxDB 数据库",
                    icon="storage",
                    on_click=lambda: ui.open("http://localhost:8086"),
                ).props("flat color=purple")

                ui.button(
                    "数据管理",
                    icon="folder_open",
                    on_click=lambda: ui.navigate.to("/data"),
                ).props("flat color=green")


def _render_stats_cards():
    """渲染统计卡片"""
    # 从策略配置获取真实数据
    try:
        manager = StrategyConfigManager(config_path=CONFIG_PATH)
        manager.load()
        strategies = manager.get_all()
        running_count = len([s for s in strategies if s.enabled])
    except Exception:
        running_count = 0

    stats = [
        ("运行策略", str(running_count), "个策略正在运行"),
        ("今日交易", "0", "笔订单已执行"),
        ("今日 PnL", "$0.00", "收益率 0.00%"),
        ("数据延迟", "< 1s", "最后更新 刚刚"),
    ]

    for title, value, subtitle in stats:
        with ui.card().classes("card min-w-48 flex-1"):
            ui.label(title).classes("text-sm text-gray-500 dark:text-gray-400")
            ui.label(value).classes("text-2xl font-bold mt-1")
            ui.label(subtitle).classes("text-xs text-gray-400 dark:text-gray-500 mt-1")


def _render_recent_alerts():
    """渲染最近告警"""
    with ui.card().classes("card w-full"):
        with ui.row().classes("justify-between items-center mb-4"):
            ui.label("最近告警").classes("text-lg font-medium")

        # 从日志文件加载真实告警
        alerts = _load_recent_alerts()

        if not alerts:
            ui.label("暂无告警").classes("text-gray-400 text-center py-4")
        else:
            for alert in alerts:
                _render_alert_item(alert)


def _load_recent_alerts() -> list[dict]:
    """加载最近告警（从日志读取）"""
    import re
    from pathlib import Path

    alerts = []
    log_dir = Path(__file__).parent.parent.parent.parent / "logs"

    # 尝试读取最近的日志文件
    log_files = (
        sorted(log_dir.glob("*.log"), reverse=True)[:3] if log_dir.exists() else []
    )

    for log_file in log_files:
        try:
            lines = log_file.read_text().split("\n")[-100:]  # 最后100行
            for line in reversed(lines):
                if len(alerts) >= 5:  # 最多5条
                    break

                # 解析日志行
                if "error" in line.lower():
                    match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line)
                    time_str = match.group(0) if match else "未知时间"
                    message = (
                        line[line.find("]") + 1 :].strip()
                        if "]" in line
                        else line[:100]
                    )
                    alerts.append(
                        {"level": "error", "message": message[:80], "time": time_str}
                    )
                elif "warning" in line.lower():
                    match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line)
                    time_str = match.group(0) if match else "未知时间"
                    message = (
                        line[line.find("]") + 1 :].strip()
                        if "]" in line
                        else line[:100]
                    )
                    alerts.append(
                        {"level": "warning", "message": message[:80], "time": time_str}
                    )
        except Exception:
            pass

    return alerts


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
            ui.label(alert["time"]).classes("text-xs text-gray-400")


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
                ui.label("✅ Webhook 已配置").classes("text-green-600 dark:text-green-400")
            else:
                ui.label("⚠️ 通知未配置").classes("text-yellow-600 dark:text-yellow-400")
                ui.label("请在 .env 中设置 WEBHOOK_URL").classes("text-gray-500 text-sm")

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
            ui.button(
                "发送测试通知",
                icon="notifications",
                on_click=lambda: asyncio.create_task(send_test_notification()),
            ).props("color=primary" if webhook_url else "disabled")
