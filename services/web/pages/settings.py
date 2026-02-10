"""
设置页面

系统配置:
- 通知设置 (Bark/Webhook)
- InfluxDB 连接
- 数据目录
- 其他系统配置
"""

import asyncio
import os
from pathlib import Path

from nicegui import ui

from services.web.utils import candidate_urls

def render():
    """渲染设置页面"""
    ui.label("系统设置").classes("text-2xl font-bold mb-4")

    # Tab 切换
    with ui.tabs().classes("w-full") as tabs:
        notify_tab = ui.tab("通知设置")
        database_tab = ui.tab("数据库连接")
        system_tab = ui.tab("系统信息")

    with ui.tab_panels(tabs, value=notify_tab).classes("w-full"):
        with ui.tab_panel(notify_tab):
            _render_notification_settings()

        with ui.tab_panel(database_tab):
            _render_database_settings()

        with ui.tab_panel(system_tab):
            _render_system_info()


def _render_notification_settings():
    """渲染通知设置"""
    with ui.card().classes("card w-full"):
        ui.label("Bark / Webhook 通知").classes("text-lg font-medium mb-4")

        # 当前配置
        webhook_url = os.getenv("WEBHOOK_URL", "")
        is_bark = "api.day.app" in webhook_url if webhook_url else False

        with ui.row().classes("gap-4 items-center mb-4"):
            if webhook_url:
                status_icon = "✅"
                status_text = "Bark 已配置" if is_bark else "Webhook 已配置"
                status_class = "text-green-600 dark:text-green-400"
            else:
                status_icon = "⚠️"
                status_text = "通知未配置"
                status_class = "text-yellow-600 dark:text-yellow-400"

            ui.label(f"{status_icon} {status_text}").classes(f"font-medium {status_class}")

        # URL 显示（隐藏敏感信息）
        if webhook_url:
            masked_url = webhook_url[:35] + "..." if len(webhook_url) > 35 else webhook_url
            ui.label(f"当前 URL: {masked_url}").classes("text-gray-500 text-sm font-mono")

        ui.separator().classes("my-4")

        # 设置说明
        ui.label("配置方法").classes("font-medium mb-2")

        ui.markdown("""
**1. 获取 Bark Key**

在 iOS 设备上安装 [Bark App](https://apps.apple.com/app/bark/id1403753865)，打开后复制设备推送地址。

**2. 设置环境变量**

在 `.env` 文件中添加：

```env
WEBHOOK_URL=https://api.day.app/your-device-key
```

或者使用其他 Webhook 服务（如企业微信、钉钉等），只要支持 POST JSON 即可。

**3. 重启服务**

```bash
docker-compose down
docker-compose up -d
```
        """).classes("text-sm")

        # 测试通知
        ui.separator().classes("my-4")
        ui.label("测试通知").classes("font-medium mb-2")

        result_label = ui.label("").classes("mt-2")

        async def send_test():
            result_label.set_text("正在发送...")

            try:
                from src.ops.notify import send_notification

                success = await send_notification(
                    title="AlgorithmTrader",
                    message="🎉 通知测试成功！",
                    level="info",
                )

                if success:
                    result_label.set_text("✅ 测试通知已发送!")
                    result_label.classes(remove="text-red-600", add="text-green-600")
                else:
                    result_label.set_text("❌ 发送失败，请检查配置")
                    result_label.classes(remove="text-green-600", add="text-red-600")

            except Exception as e:
                result_label.set_text(f"❌ 错误: {e}")
                result_label.classes(remove="text-green-600", add="text-red-600")

        notify_btn = ui.button(
            "发送测试通知",
            icon="notifications_active",
            on_click=send_test,
        ).props("color=primary")
        if not webhook_url:
            notify_btn.disable()


def _render_database_settings():
    """渲染数据库设置"""
    with ui.card().classes("card w-full"):
        ui.label("InfluxDB 连接").classes("text-lg font-medium mb-4")

        # 从环境变量读取配置
        influx_url = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
        influx_org = os.getenv("INFLUXDB_ORG", "algorithmtrader")
        influx_bucket = os.getenv("INFLUXDB_BUCKET", "trading")

        with ui.column().classes("gap-2"):
            ui.label(f"URL: {influx_url}").classes("text-gray-600 font-mono text-sm")
            ui.label(f"Organization: {influx_org}").classes("text-gray-600 font-mono text-sm")
            ui.label(f"Bucket: {influx_bucket}").classes("text-gray-600 font-mono text-sm")

        # 连接测试
        status_container = ui.column().classes("mt-4")

        async def check_connection():
            status_container.clear()
            with status_container:
                ui.spinner("dots")

            try:
                import httpx

                async with httpx.AsyncClient(timeout=5.0) as client:
                    last_error: str | None = None
                    for url in candidate_urls(influx_url, service_host="influxdb"):
                        try:
                            resp = await client.get(f"{url.rstrip('/')}/health")
                            if resp.status_code == 200:
                                data = resp.json()
                                status_container.clear()
                                with status_container:
                                    ui.label("✅ 连接正常").classes("text-green-600")
                                    ui.label(
                                        f"版本: {data.get('version', 'unknown')}"
                                    ).classes("text-gray-500 text-sm")
                                return
                            last_error = f"HTTP {resp.status_code}"
                            break
                        except httpx.ConnectError as e:
                            last_error = str(e)
                            continue

                    status_container.clear()
                    with status_container:
                        ui.label("⚠️ 连接异常").classes("text-yellow-600")
                        if last_error:
                            ui.label(f"错误: {last_error}").classes(
                                "text-gray-500 text-sm"
                            )
            except Exception as e:
                status_container.clear()
                with status_container:
                    ui.label(f"❌ 连接失败: {e}").classes("text-red-600")

        ui.button("测试连接", icon="sync", on_click=check_connection).props("flat")

        # 快捷链接
        ui.separator().classes("my-4")

        with ui.row().classes("gap-2"):
            ui.button(
                "打开 InfluxDB UI",
                icon="open_in_new",
                on_click=lambda: ui.run_javascript(
                    "window.open('http://' + window.location.hostname + ':8086', '_blank')"
                ),
            ).props("flat")

    with ui.card().classes("card w-full mt-4"):
        ui.label("Grafana").classes("text-lg font-medium mb-4")

        grafana_url = os.getenv("GRAFANA_URL", "http://grafana:3000")

        ui.label(f"URL: {grafana_url}").classes("text-gray-600 font-mono text-sm")
        ui.label("默认用户: admin / admin").classes("text-gray-500 text-sm")

        with ui.row().classes("gap-2 mt-4"):
            ui.button(
                "打开 Grafana",
                icon="open_in_new",
                on_click=lambda: ui.run_javascript(
                    "window.open('http://' + window.location.hostname + ':3000', '_blank')"
                ),
            ).props("flat")


def _render_system_info():
    """渲染系统信息"""
    import platform
    import sys

    with ui.card().classes("card w-full"):
        ui.label("系统信息").classes("text-lg font-medium mb-4")

        info_items = [
            ("Python 版本", sys.version.split()[0]),
            ("操作系统", platform.system()),
            ("平台", platform.platform()),
            ("数据目录", str(Path("/app/data").resolve())),
            ("配置目录", str(Path("/app/config").resolve())),
        ]

        for label, value in info_items:
            with ui.row().classes("gap-4 py-1 border-b border-gray-100 dark:border-gray-700"):
                ui.label(label).classes("w-32 text-gray-500")
                ui.label(value).classes("font-mono text-sm")

    with ui.card().classes("card w-full mt-4"):
        ui.label("环境变量").classes("text-lg font-medium mb-4")

        # 显示关键环境变量（隐藏敏感信息）
        env_vars = [
            "INFLUXDB_URL",
            "INFLUXDB_ORG",
            "INFLUXDB_BUCKET",
            "OKX_API_KEY",
            "BINANCE_API_KEY",
            "WEBHOOK_URL",
            "TELEGRAM_BOT_TOKEN",
        ]

        for var in env_vars:
            value = os.getenv(var, "")
            if value:
                # 隐藏敏感信息
                if "KEY" in var or "TOKEN" in var or "SECRET" in var:
                    display_value = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
                elif "URL" in var and len(value) > 30:
                    display_value = value[:30] + "..."
                else:
                    display_value = value
                status = "✅"
            else:
                display_value = "(未设置)"
                status = "⚪"

            with ui.row().classes("gap-2 py-1"):
                ui.label(status)
                ui.label(var).classes("w-48 font-mono text-sm text-gray-600")
                ui.label(display_value).classes("font-mono text-sm")

    with ui.card().classes("card w-full mt-4"):
        ui.label("数据统计").classes("text-lg font-medium mb-4")

        data_dir = Path("/app/data")
        parquet_dir = data_dir / "parquet"

        stats = []

        # Parquet 数据
        if parquet_dir.exists():
            parquet_files = list(parquet_dir.glob("**/*.parquet"))
            total_size = sum(f.stat().st_size for f in parquet_files)
            size_str = f"{total_size / 1024 / 1024:.1f} MB" if total_size > 0 else "0 MB"
            stats.append(("Parquet 文件", f"{len(parquet_files)} 个 ({size_str})"))

        # 日志文件
        log_dir = data_dir.parent / "logs"
        if log_dir.exists():
            log_files = list(log_dir.glob("*.log"))
            stats.append(("日志文件", f"{len(log_files)} 个"))

        # 回测报告
        reports_dir = data_dir.parent / "reports"
        if reports_dir.exists():
            report_dirs = [d for d in reports_dir.iterdir() if d.is_dir()]
            stats.append(("回测报告", f"{len(report_dirs)} 个"))

        for label, value in stats:
            with ui.row().classes("gap-4 py-1"):
                ui.label(label).classes("w-32 text-gray-500")
                ui.label(value).classes("font-mono text-sm")
