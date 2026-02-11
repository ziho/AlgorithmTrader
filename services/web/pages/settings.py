"""
系统设置页面

功能:
- 环境变量总览与验证
- 数据库连接管理 (InfluxDB, Grafana)
- 服务看门狗状态
- 系统信息
"""

import os
import platform
import sys
from pathlib import Path

from dotenv import load_dotenv
from nicegui import ui

from services.web.utils import candidate_urls
from src.ops.logging import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def _reload_env() -> None:
    """重新加载 .env 文件到当前进程环境。"""
    load_dotenv(PROJECT_ROOT / ".env", override=True)


def render():
    """渲染系统设置页面"""
    _reload_env()
    ui.label("系统设置").classes("text-2xl font-bold mb-4")

    # Tab 切换
    with ui.tabs().classes("w-full") as tabs:
        env_tab = ui.tab("环境变量")
        database_tab = ui.tab("数据库连接")
        watchdog_tab = ui.tab("服务看门狗")
        system_tab = ui.tab("系统信息")

    with ui.tab_panels(tabs, value=env_tab).classes("w-full"):
        with ui.tab_panel(env_tab):
            _render_env_variables()

        with ui.tab_panel(database_tab):
            _render_database_settings()

        with ui.tab_panel(watchdog_tab):
            _render_watchdog_settings()

        with ui.tab_panel(system_tab):
            _render_system_info()


# ============================================
# 环境变量总览
# ============================================


def _render_env_variables():
    """渲染环境变量总览与验证"""
    with ui.card().classes("card w-full"):
        ui.label("环境变量配置").classes("text-lg font-medium mb-2")
        ui.label("显示所有关键环境变量的配置状态。变量从 .env 文件加载。").classes(
            "text-gray-500 text-sm mb-4"
        )

        # 分组显示环境变量
        env_groups = [
            {
                "title": "🏠 基础设置",
                "vars": [
                    ("ENV", "运行环境 (dev/prod)"),
                    ("LOG_LEVEL", "日志级别"),
                    ("DATA_DIR", "数据目录"),
                    ("LOG_DIR", "日志目录"),
                ],
            },
            {
                "title": "📊 InfluxDB",
                "vars": [
                    ("INFLUXDB_URL", "数据库 URL"),
                    ("INFLUXDB_TOKEN", "认证 Token"),
                    ("INFLUXDB_ORG", "组织名称"),
                    ("INFLUXDB_BUCKET", "存储桶"),
                ],
            },
            {
                "title": "🔐 OKX 交易所",
                "vars": [
                    ("OKX_API_KEY", "API Key"),
                    ("OKX_API_SECRET", "API Secret"),
                    ("OKX_PASSPHRASE", "Passphrase"),
                    ("OKX_SANDBOX", "模拟盘开关"),
                ],
            },
            {
                "title": "💬 Telegram",
                "vars": [
                    ("TELEGRAM_BOT_TOKEN", "Bot Token"),
                    ("TELEGRAM_CHAT_ID", "Chat ID"),
                    ("TELEGRAM_CHANNELS", "多 Bot 配置"),
                ],
            },
            {
                "title": "📱 Bark 推送",
                "vars": [
                    ("BARK_URLS", "推送 URL 列表"),
                    ("WEBHOOK_URL", "Webhook URL (兼容)"),
                ],
            },
            {
                "title": "📧 邮件 (可选)",
                "vars": [
                    ("SMTP_HOST", "SMTP 服务器"),
                    ("SMTP_PORT", "SMTP 端口"),
                    ("SMTP_USER", "用户名"),
                    ("SMTP_PASSWORD", "密码"),
                    ("SMTP_FROM", "发件人"),
                    ("SMTP_TO", "收件人"),
                ],
            },
        ]

        for group in env_groups:
            with ui.card().classes("w-full bg-gray-50 dark:bg-gray-800 p-4 mb-3"):
                ui.label(group["title"]).classes("font-medium mb-2")

                for var_name, description in group["vars"]:
                    value = os.getenv(var_name, "")

                    with ui.row().classes(
                        "w-full gap-2 py-1.5 items-center "
                        "border-b border-gray-100 dark:border-gray-700 last:border-0"
                    ):
                        # 状态图标
                        if value:
                            ui.icon("check_circle").classes("text-green-500 text-sm")
                        else:
                            ui.icon("radio_button_unchecked").classes(
                                "text-gray-300 text-sm"
                            )

                        # 变量名
                        ui.label(var_name).classes(
                            "w-44 font-mono text-sm text-gray-700 dark:text-gray-300"
                        )

                        # 值显示
                        if value:
                            display = _mask_sensitive_value(var_name, value)
                            ui.label(display).classes(
                                "flex-1 font-mono text-sm text-gray-500"
                            )
                        else:
                            ui.label("(未设置)").classes(
                                "flex-1 text-sm text-gray-400 italic"
                            )

                        # 描述
                        ui.label(description).classes(
                            "text-xs text-gray-400 w-28 text-right"
                        )

    # 验证按钮
    with ui.card().classes("card w-full mt-4"):
        ui.label("配置验证").classes("text-lg font-medium mb-4")

        result_container = ui.column().classes("w-full")

        async def validate_all():
            result_container.clear()
            with result_container:
                ui.spinner("dots").classes("mx-auto")

            results = await _validate_env_config()

            result_container.clear()
            with result_container:
                for item in results:
                    with ui.row().classes("gap-2 items-center py-1"):
                        icon = "check_circle" if item["ok"] else "error"
                        color = "text-green-500" if item["ok"] else "text-red-500"
                        ui.icon(icon).classes(f"{color} text-sm")
                        ui.label(item["name"]).classes("font-medium text-sm w-40")
                        ui.label(item["message"]).classes("text-sm text-gray-500")

        ui.button("验证所有配置", icon="verified", on_click=validate_all).props(
            "color=primary"
        )


def _mask_sensitive_value(var_name: str, value: str) -> str:
    """隐藏敏感值"""
    sensitive_keywords = ["KEY", "SECRET", "TOKEN", "PASSWORD", "PASSPHRASE"]
    if any(kw in var_name.upper() for kw in sensitive_keywords):
        if len(value) > 12:
            return value[:6] + "***" + value[-4:]
        return "***"
    if "URL" in var_name.upper() and len(value) > 40:
        return value[:40] + "..."
    return value


async def _validate_env_config() -> list[dict]:
    """验证环境配置"""
    results = []

    # 检查 InfluxDB
    influx_url = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            for url in candidate_urls(influx_url, service_host="influxdb"):
                try:
                    resp = await client.get(f"{url.rstrip('/')}/health")
                    if resp.status_code == 200:
                        results.append(
                            {"name": "InfluxDB", "ok": True, "message": "连接正常"}
                        )
                        break
                except httpx.ConnectError:
                    continue
            else:
                results.append({"name": "InfluxDB", "ok": False, "message": "无法连接"})
    except Exception as e:
        results.append({"name": "InfluxDB", "ok": False, "message": str(e)[:50]})

    # 检查 Telegram
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if bot_token and chat_id:
        try:
            import aiohttp

            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        bot_name = data.get("result", {}).get("username", "unknown")
                        results.append(
                            {
                                "name": "Telegram Bot",
                                "ok": True,
                                "message": f"@{bot_name}",
                            }
                        )
                    else:
                        results.append(
                            {
                                "name": "Telegram Bot",
                                "ok": False,
                                "message": "Token 无效",
                            }
                        )
        except Exception as e:
            results.append(
                {"name": "Telegram Bot", "ok": False, "message": str(e)[:50]}
            )
    else:
        results.append({"name": "Telegram Bot", "ok": False, "message": "未配置"})

    # 检查 Bark
    bark_urls_str = os.getenv("BARK_URLS", "")
    webhook_url = os.getenv("WEBHOOK_URL", "")
    if bark_urls_str:
        urls = [u.strip() for u in bark_urls_str.split(",") if u.strip()]
        results.append(
            {"name": "Bark 推送", "ok": True, "message": f"{len(urls)} 个设备已配置"}
        )
    elif webhook_url and "api.day.app" in webhook_url:
        results.append({"name": "Bark 推送", "ok": True, "message": "1 个设备已配置"})
    else:
        results.append({"name": "Bark 推送", "ok": False, "message": "未配置"})

    # 检查 OKX
    okx_key = os.getenv("OKX_API_KEY", "")
    if okx_key:
        results.append(
            {"name": "OKX API", "ok": True, "message": f"Key: {okx_key[:8]}..."}
        )
    else:
        results.append({"name": "OKX API", "ok": False, "message": "未配置"})

    # 检查邮件
    smtp_host = os.getenv("SMTP_HOST", "")
    if smtp_host:
        results.append({"name": "邮件 SMTP", "ok": True, "message": smtp_host})
    else:
        results.append({"name": "邮件 SMTP", "ok": False, "message": "未配置 (可选)"})

    # 数据目录
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    if data_dir.exists():
        results.append({"name": "数据目录", "ok": True, "message": str(data_dir)})
    else:
        results.append(
            {"name": "数据目录", "ok": False, "message": f"{data_dir} 不存在"}
        )

    return results


# ============================================
# 数据库连接
# ============================================


def _render_database_settings():
    """渲染数据库设置"""
    with ui.card().classes("card w-full"):
        ui.label("InfluxDB 连接").classes("text-lg font-medium mb-4")

        influx_url = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
        influx_org = os.getenv("INFLUXDB_ORG", "algorithmtrader")
        influx_bucket = os.getenv("INFLUXDB_BUCKET", "trading")

        with ui.column().classes("gap-2"):
            ui.label(f"URL: {influx_url}").classes("text-gray-600 font-mono text-sm")
            ui.label(f"Organization: {influx_org}").classes(
                "text-gray-600 font-mono text-sm"
            )
            ui.label(f"Bucket: {influx_bucket}").classes(
                "text-gray-600 font-mono text-sm"
            )

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

        ui.separator().classes("my-4")

        with ui.row().classes("gap-2"):
            ui.button(
                "打开 InfluxDB UI",
                icon="open_in_new",
                on_click=lambda: ui.run_javascript(
                    "window.open('http://' + window.location.hostname + ':8086', '_blank')"
                ),
            ).props("flat")

    # InfluxDB 数据概览
    with ui.card().classes("card w-full mt-4"):
        ui.label("InfluxDB 数据概览").classes("text-lg font-medium mb-4")

        influx_data_container = ui.column().classes("w-full")

        async def load_influx_data():
            influx_data_container.clear()
            with influx_data_container:
                ui.spinner("dots").classes("mx-auto")

            try:
                from src.data.storage.influx_store import InfluxStore

                store = InfluxStore()

                query = f'''
                import "influxdata/influxdb/schema"
                schema.measurements(bucket: "{influx_bucket}")
                '''
                result = store._query_api.query(query)

                measurements = []
                for table in result:
                    for record in table.records:
                        measurements.append(record.get_value())

                store.close()

                influx_data_container.clear()
                with influx_data_container:
                    if measurements:
                        ui.label(f"共 {len(measurements)} 个 measurement").classes(
                            "text-gray-500 text-sm mb-2"
                        )
                        for m in measurements:
                            ui.label(f"  • {m}").classes(
                                "text-gray-600 font-mono text-sm"
                            )
                    else:
                        ui.label("InfluxDB 中暂无数据").classes("text-gray-400")
                        ui.label("下载历史数据后可选择「同步到 InfluxDB」").classes(
                            "text-gray-400 text-sm"
                        )

            except Exception as e:
                influx_data_container.clear()
                with influx_data_container:
                    ui.label(f"查询失败: {e}").classes("text-red-500 text-sm")

        ui.button("查询数据概览", icon="storage", on_click=load_influx_data).props(
            "flat"
        )

    # Grafana
    with ui.card().classes("card w-full mt-4"):
        ui.label("Grafana").classes("text-lg font-medium mb-4")

        grafana_url = os.getenv("GRAFANA_URL", "http://grafana:3000")
        ui.label(f"URL: {grafana_url}").classes("text-gray-600 font-mono text-sm")
        ui.label("默认用户: admin / algorithmtrader123").classes(
            "text-gray-500 text-sm"
        )

        with ui.row().classes("gap-2 mt-4"):
            ui.button(
                "打开 Grafana",
                icon="open_in_new",
                on_click=lambda: ui.run_javascript(
                    "window.open('http://' + window.location.hostname + ':3000', '_blank')"
                ),
            ).props("flat")


# ============================================
# 服务看门狗
# ============================================


def _render_watchdog_settings():
    """渲染看门狗配置"""
    with ui.card().classes("card w-full"):
        ui.label("服务看门狗 (Watchdog)").classes("text-lg font-medium mb-2")
        ui.label(
            "自动监控 Docker 容器服务的健康状态。当服务异常时自动尝试重启，"
            "连续失败 3 次后通过 Bark/Telegram 发送告警通知。"
        ).classes("text-gray-500 text-sm mb-4")

        from src.ops.watchdog import get_watchdog

        watchdog = get_watchdog()
        status_container = ui.column().classes("w-full")

        async def start_watchdog():
            if not watchdog._running:
                await watchdog.start()
                ui.notify("看门狗已启动", type="positive")
                render_status()

        async def stop_watchdog():
            if watchdog._running:
                await watchdog.stop()
                ui.notify("看门狗已停止", type="info")
                render_status()

        def render_status():
            status_container.clear()
            with status_container:
                # 运行状态
                if watchdog._running:
                    with ui.row().classes("gap-2 items-center mb-4"):
                        ui.icon("play_circle").classes("text-green-500")
                        ui.label("看门狗运行中").classes("text-green-600 font-medium")
                        ui.button("停止", icon="stop", on_click=stop_watchdog).props(
                            "flat color=red size=sm"
                        )
                else:
                    with ui.row().classes("gap-2 items-center mb-4"):
                        ui.icon("pause_circle").classes("text-gray-400")
                        ui.label("看门狗已停止").classes("text-gray-500 font-medium")
                        ui.button(
                            "启动", icon="play_arrow", on_click=start_watchdog
                        ).props("color=primary size=sm")

                # 各服务状态
                for svc_name, health in watchdog.health_status.items():
                    with ui.card().classes(
                        "w-full bg-gray-50 dark:bg-gray-800 p-3 mb-2"
                    ):
                        with ui.row().classes("justify-between items-center"):
                            with ui.row().classes("gap-2 items-center"):
                                status_icons = {
                                    "healthy": ("check_circle", "text-green-500"),
                                    "unhealthy": ("error", "text-red-500"),
                                    "restarting": ("sync", "text-yellow-500"),
                                    "alert_sent": (
                                        "notification_important",
                                        "text-red-600",
                                    ),
                                    "not_deployed": (
                                        "remove_circle_outline",
                                        "text-gray-300",
                                    ),
                                    "unknown": ("help", "text-gray-400"),
                                }
                                icon, color = status_icons.get(
                                    health.status, ("help", "text-gray-400")
                                )
                                ui.icon(icon).classes(f"{color}")
                                ui.label(svc_name.capitalize()).classes("font-medium")
                                if health.status == "not_deployed":
                                    ui.label("(未部署)").classes(
                                        "text-xs text-gray-400"
                                    )

                            with ui.row().classes("gap-3 text-sm text-gray-500"):
                                if health.status == "not_deployed":
                                    ui.label("服务未启动，不会触发告警").classes(
                                        "italic"
                                    )
                                else:
                                    ui.label(f"失败: {health.consecutive_failures}")
                                    ui.label(f"重启: {health.restart_count}")
                                    if health.last_check:
                                        ui.label(
                                            f"上次检查: {health.last_check.strftime('%H:%M:%S')}"
                                        )

        render_status()
        from services.web.utils import safe_timer

        safe_timer(30.0, render_status)

    # 配置说明
    with ui.card().classes("card w-full mt-4"):
        ui.label("看门狗配置").classes("text-lg font-medium mb-4")
        ui.markdown("""
- **监控间隔**: 60 秒 (每分钟检查一次)
- **最大容忍失败次数**: 3 次 (达到后发送告警)
- **自动重启**: 每次检测失败后自动执行 `docker compose restart`
- **告警通道**: Bark 推送 + Telegram 通知
- **智能检测**: 自动识别已部署的服务，未通过 Docker Compose Profile 启动的服务不会触发误报告警
- **默认状态**: 已关闭（需手动启动，避免消耗系统资源）

> 看门狗只监控实际部署运行的容器。如果你只启动了 `--profile web`，
> 则 collector / trader / scheduler / notifier 不会被监控，也不会发送告警。
> 
> **注意**: 看门狗会定期调用 `docker ps` 检查容器状态，在系统资源有限时可能影响性能。
> 仅在需要自动重启和告警时才启用。
        """).classes("text-sm")


# ============================================
# 系统信息
# ============================================


def _render_system_info():
    """渲染系统信息"""
    with ui.card().classes("card w-full"):
        ui.label("系统信息").classes("text-lg font-medium mb-4")

        info_items = [
            ("Python 版本", sys.version.split()[0]),
            ("操作系统", platform.system()),
            ("平台", platform.platform()),
            ("数据目录", str(PROJECT_ROOT / "data")),
            ("配置目录", str(PROJECT_ROOT / "config")),
            ("日志目录", str(PROJECT_ROOT / "logs")),
        ]

        for label, value in info_items:
            with ui.row().classes(
                "gap-4 py-1 border-b border-gray-100 dark:border-gray-700"
            ):
                ui.label(label).classes("w-32 text-gray-500")
                ui.label(value).classes("font-mono text-sm")

    # 数据统计
    with ui.card().classes("card w-full mt-4"):
        ui.label("数据统计").classes("text-lg font-medium mb-4")

        data_dir = PROJECT_ROOT / "data"
        parquet_dir = data_dir / "parquet"

        stats = []

        # Parquet 数据
        if parquet_dir.exists():
            parquet_files = list(parquet_dir.glob("**/*.parquet"))
            total_size = sum(f.stat().st_size for f in parquet_files)
            if total_size > 1024 * 1024 * 1024:
                size_str = f"{total_size / 1024 / 1024 / 1024:.2f} GB"
            elif total_size > 0:
                size_str = f"{total_size / 1024 / 1024:.1f} MB"
            else:
                size_str = "0 MB"
            stats.append(("Parquet 文件", f"{len(parquet_files)} 个 ({size_str})"))

        # 日志文件
        log_dir = PROJECT_ROOT / "logs"
        if log_dir.exists():
            log_files = list(log_dir.glob("*.log"))
            log_size = sum(f.stat().st_size for f in log_files)
            log_size_str = (
                f"{log_size / 1024 / 1024:.1f} MB" if log_size > 0 else "0 MB"
            )
            stats.append(("日志文件", f"{len(log_files)} 个 ({log_size_str})"))

        # 回测报告
        reports_dir = PROJECT_ROOT / "reports"
        if reports_dir.exists():
            report_dirs = [d for d in reports_dir.iterdir() if d.is_dir()]
            stats.append(("回测报告", f"{len(report_dirs)} 个"))

        for label, value in stats:
            with ui.row().classes("gap-4 py-1"):
                ui.label(label).classes("w-32 text-gray-500")
                ui.label(value).classes("font-mono text-sm")

        ui.separator().classes("my-4")
        ui.markdown("""
**关于 Parquet 文件**

Parquet 是本系统的核心本地数据存储格式，用于存储历史 OHLCV (K 线) 数据。
它具有列式存储、高压缩比、快速查询的优势，是回测引擎和策略信号计算的数据源。

- 从 Binance 下载的历史数据会自动存储为 Parquet 格式
- 回测引擎直接从 Parquet 文件读取数据
- 可选同步到 InfluxDB 用于 Grafana 实时可视化
        """).classes("text-sm text-gray-500")
