"""
通知管理页面

功能:
- Telegram 通知配置与测试 (支持多个 Bot)
- Bark 推送配置与测试 (支持多个设备)
- 邮件通知配置与测试 (预留)
- 通知历史 (近期发送记录)
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from nicegui import ui

from src.ops.logging import get_logger

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def _reload_env() -> None:
    """重新加载 .env 文件到当前进程环境。"""
    load_dotenv(PROJECT_ROOT / ".env", override=True)


def render():
    """渲染通知管理页面"""
    _reload_env()
    ui.label("通知管理").classes("text-2xl font-bold mb-4")

    # Tab 切换
    with ui.tabs().classes("w-full") as tabs:
        telegram_tab = ui.tab("Telegram")
        bark_tab = ui.tab("Bark 推送")
        email_tab = ui.tab("邮件通知")
        webhook_tab = ui.tab("通用 Webhook")

    with ui.tab_panels(tabs, value=telegram_tab).classes("w-full"):
        with ui.tab_panel(telegram_tab):
            _render_telegram_section()

        with ui.tab_panel(bark_tab):
            _render_bark_section()

        with ui.tab_panel(email_tab):
            _render_email_section()

        with ui.tab_panel(webhook_tab):
            _render_webhook_section()


# ============================================
# Telegram
# ============================================


def _render_telegram_section():
    """渲染 Telegram 通知配置"""
    with ui.card().classes("card w-full"):
        ui.label("Telegram Bot 通知").classes("text-lg font-medium mb-2")
        ui.label("通过 Telegram Bot 发送交易信号、系统告警等通知。").classes(
            "text-gray-500 text-sm mb-4"
        )

        # 读取配置
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        channels_str = os.getenv("TELEGRAM_CHANNELS", "")

        # 主 Bot 配置
        with ui.card().classes("w-full bg-gray-50 dark:bg-gray-800 p-4"):
            ui.label("主 Bot").classes("font-medium mb-2")

            if bot_token and chat_id:
                with ui.row().classes("gap-2 items-center"):
                    ui.icon("check_circle").classes("text-green-500")
                    ui.label("已配置").classes(
                        "text-green-600 dark:text-green-400 font-medium"
                    )

                masked_token = (
                    bot_token[:10] + "..." + bot_token[-4:]
                    if len(bot_token) > 14
                    else "***"
                )
                ui.label(f"Bot Token: {masked_token}").classes(
                    "text-gray-500 text-sm font-mono"
                )
                ui.label(f"Chat ID: {chat_id}").classes(
                    "text-gray-500 text-sm font-mono"
                )
            else:
                with ui.row().classes("gap-2 items-center"):
                    ui.icon("warning").classes("text-yellow-500")
                    ui.label("未配置").classes("text-yellow-600 font-medium")

            # 验证按钮
            result_label = ui.label("").classes("mt-2 text-sm")

            async def test_telegram():
                if not bot_token or not chat_id:
                    result_label.set_text(
                        "❌ 请先在 .env 中配置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID"
                    )
                    result_label.classes(add="text-red-600")
                    return

                result_label.set_text("⏳ 正在发送测试消息...")
                result_label.classes(remove="text-red-600 text-green-600")

                try:
                    import aiohttp

                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    payload = {
                        "chat_id": chat_id,
                        "text": "🎉 <b>AlgorithmTrader 通知测试</b>\n\n✅ Telegram 通知功能正常！",
                        "parse_mode": "HTML",
                    }

                    async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as session:
                        async with session.post(url, json=payload) as resp:
                            if resp.status == 200:
                                result_label.set_text(
                                    "✅ 测试消息已发送！请检查 Telegram"
                                )
                                result_label.classes(
                                    add="text-green-600", remove="text-red-600"
                                )
                            else:
                                data = await resp.json()
                                desc = data.get("description", f"HTTP {resp.status}")
                                result_label.set_text(f"❌ 发送失败: {desc}")
                                result_label.classes(
                                    add="text-red-600", remove="text-green-600"
                                )

                except Exception as e:
                    result_label.set_text(f"❌ 错误: {e}")
                    result_label.classes(add="text-red-600", remove="text-green-600")

            ui.button("🤖 发送 Telegram 测试", on_click=test_telegram).props(
                "color=primary"
            ).classes("mt-2")

        # 额外 Bot 配置
        if channels_str:
            ui.separator().classes("my-4")
            ui.label("额外 Bot 通道").classes("font-medium mb-2")
            for i, ch in enumerate(channels_str.split(","), 1):
                parts = ch.strip().split("|")
                if len(parts) == 2:
                    token, cid = parts
                    masked = token[:10] + "..." if len(token) > 10 else "***"
                    ui.label(f"  Bot {i}: {masked} → Chat {cid}").classes(
                        "text-gray-500 text-sm font-mono"
                    )

        # 配置说明
        ui.separator().classes("my-4")
        with ui.expansion("配置说明", icon="help_outline").classes("w-full"):
            ui.markdown("""
**1. 创建 Telegram Bot**

在 Telegram 中找到 [@BotFather](https://t.me/BotFather)，发送 `/newbot` 创建机器人，获取 Bot Token。

**2. 获取 Chat ID**

向机器人发送一条消息，然后访问:
`https://api.telegram.org/bot<TOKEN>/getUpdates`
在返回的 JSON 中找到 `chat.id`。

**3. 配置 `.env`**

```env
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

**多个 Bot (可选):**
```env
TELEGRAM_CHANNELS=token1|chatid1,token2|chatid2
```

**4. 重启服务**
```bash
docker compose restart web
```
            """).classes("text-sm")


# ============================================
# Bark
# ============================================


def _render_bark_section():
    """渲染 Bark 推送配置"""
    with ui.card().classes("card w-full"):
        ui.label("Bark 推送 (iOS)").classes("text-lg font-medium mb-2")
        ui.label("通过 Bark App 向 iOS 设备发送推送通知。支持配置多个设备。").classes(
            "text-gray-500 text-sm mb-4"
        )

        # 读取配置
        bark_urls_str = os.getenv("BARK_URLS", "")
        webhook_url = os.getenv("WEBHOOK_URL", "")

        # 解析所有 Bark URL
        bark_urls: list[str] = []
        if bark_urls_str:
            bark_urls = [u.strip() for u in bark_urls_str.split(",") if u.strip()]
        elif webhook_url and "api.day.app" in webhook_url:
            bark_urls = [webhook_url]

        if bark_urls:
            for i, url in enumerate(bark_urls, 1):
                with ui.card().classes("w-full bg-gray-50 dark:bg-gray-800 p-4 mb-2"):
                    with ui.row().classes("justify-between items-center"):
                        with ui.row().classes("gap-2 items-center"):
                            ui.icon("check_circle").classes("text-green-500")
                            ui.label(f"设备 {i}").classes("font-medium")

                        masked = url[:35] + "..." if len(url) > 35 else url
                        ui.label(masked).classes("text-gray-500 text-sm font-mono")

                    result_label = ui.label("").classes("mt-2 text-sm")
                    _url = url  # capture for closure

                    async def test_bark(u=_url, rl=result_label):
                        rl.set_text("⏳ 正在发送...")
                        try:
                            import aiohttp

                            payload = {
                                "title": "🎉 AlgorithmTrader",
                                "body": "Bark 推送测试成功！",
                                "group": "AlgorithmTrader",
                                "level": "active",
                            }
                            async with aiohttp.ClientSession(
                                timeout=aiohttp.ClientTimeout(total=10)
                            ) as session:
                                async with session.post(
                                    u.rstrip("/"), json=payload
                                ) as resp:
                                    if resp.status in (200, 201, 204):
                                        rl.set_text("✅ 推送已发送！")
                                        rl.classes(
                                            add="text-green-600", remove="text-red-600"
                                        )
                                    else:
                                        rl.set_text(f"❌ 失败: HTTP {resp.status}")
                                        rl.classes(
                                            add="text-red-600", remove="text-green-600"
                                        )
                        except Exception as e:
                            rl.set_text(f"❌ 错误: {e}")
                            rl.classes(add="text-red-600", remove="text-green-600")

                    ui.button(f"📱 测试设备 {i}", on_click=test_bark).props(
                        "color=primary outline"
                    ).classes("mt-1")
        else:
            with ui.row().classes("gap-2 items-center"):
                ui.icon("warning").classes("text-yellow-500")
                ui.label("未配置").classes("text-yellow-600 font-medium")

        # 配置说明
        ui.separator().classes("my-4")
        with ui.expansion("配置说明", icon="help_outline").classes("w-full"):
            ui.markdown("""
**1. 安装 Bark App**

在 iOS 设备上安装 [Bark App](https://apps.apple.com/app/bark/id1403753865)。

**2. 获取推送 URL**

打开 Bark App，复制推送地址，格式为:
`https://api.day.app/你的设备Key`

**3. 配置 `.env`**

单个设备:
```env
BARK_URLS=https://api.day.app/your-key
```

多个设备 (逗号分隔):
```env
BARK_URLS=https://api.day.app/key1,https://api.day.app/key2
```

**4. 重启服务**
```bash
docker compose restart web
```
            """).classes("text-sm")


# ============================================
# 邮件通知 (预留)
# ============================================


def _render_email_section():
    """渲染邮件通知配置"""
    with ui.card().classes("card w-full"):
        ui.label("邮件通知").classes("text-lg font-medium mb-2")
        ui.label("通过 SMTP 发送邮件通知。支持 Gmail、Outlook 等邮箱服务。").classes(
            "text-gray-500 text-sm mb-4"
        )

        # 读取配置
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_port = os.getenv("SMTP_PORT", "587")
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_password = os.getenv("SMTP_PASSWORD", "")
        smtp_from = os.getenv("SMTP_FROM", "")
        smtp_to = os.getenv("SMTP_TO", "")
        smtp_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

        if smtp_host and smtp_user:
            with ui.card().classes("w-full bg-gray-50 dark:bg-gray-800 p-4"):
                with ui.row().classes("gap-2 items-center"):
                    ui.icon("check_circle").classes("text-green-500")
                    ui.label("已配置").classes("text-green-600 font-medium")

                ui.label(f"SMTP: {smtp_host}:{smtp_port}").classes(
                    "text-gray-500 text-sm font-mono"
                )
                ui.label(f"发件人: {smtp_from or smtp_user}").classes(
                    "text-gray-500 text-sm font-mono"
                )
                if smtp_to:
                    ui.label(f"收件人: {smtp_to}").classes(
                        "text-gray-500 text-sm font-mono"
                    )

                result_label = ui.label("").classes("mt-2 text-sm")

                async def test_email():
                    result_label.set_text("⏳ 正在发送测试邮件...")
                    try:
                        import smtplib
                        from email.mime.text import MIMEText

                        msg = MIMEText(
                            "这是一封来自 AlgorithmTrader 的测试邮件。\n\n"
                            "如果您收到此邮件，说明邮件通知功能已正确配置。",
                            "plain",
                            "utf-8",
                        )
                        msg["Subject"] = "🎉 AlgorithmTrader 邮件通知测试"
                        msg["From"] = smtp_from or smtp_user
                        msg["To"] = smtp_to or smtp_user

                        def _send():
                            with smtplib.SMTP(
                                smtp_host, int(smtp_port), timeout=15
                            ) as server:
                                if smtp_tls:
                                    server.starttls()
                                if smtp_password:
                                    server.login(smtp_user, smtp_password)
                                server.send_message(msg)

                        await asyncio.get_running_loop().run_in_executor(None, _send)

                        result_label.set_text("✅ 测试邮件已发送！")
                        result_label.classes(
                            add="text-green-600", remove="text-red-600"
                        )
                    except Exception as e:
                        result_label.set_text(f"❌ 发送失败: {e}")
                        result_label.classes(
                            add="text-red-600", remove="text-green-600"
                        )

                ui.button("📧 发送测试邮件", on_click=test_email).props(
                    "color=primary"
                ).classes("mt-2")
        else:
            with ui.column().classes("items-center py-6"):
                ui.icon("email").classes("text-4xl text-gray-300")
                ui.label("邮件通知尚未配置").classes("text-gray-400 mt-2")

        # 配置说明
        ui.separator().classes("my-4")
        with ui.expansion("配置说明", icon="help_outline").classes("w-full"):
            ui.markdown("""
**在 `.env` 中添加以下配置:**

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-email@gmail.com
SMTP_TO=recipient1@example.com,recipient2@example.com
SMTP_USE_TLS=true
```

**Gmail 用户注意:**
需要使用「应用专用密码」而非登录密码。
在 Google 账户 → 安全 → 两步验证 → 应用密码 中生成。

**重启服务:**
```bash
docker compose restart web
```
            """).classes("text-sm")


# ============================================
# 通用 Webhook (预留)
# ============================================


def _render_webhook_section():
    """渲染通用 Webhook 配置"""
    with ui.card().classes("card w-full"):
        ui.label("通用 Webhook").classes("text-lg font-medium mb-2")
        ui.label(
            "支持企业微信、钉钉、飞书等任何接受 POST JSON 的 Webhook 服务。"
        ).classes("text-gray-500 text-sm mb-4")

        webhook_url = os.getenv("WEBHOOK_URL", "")
        is_bark = "api.day.app" in webhook_url if webhook_url else False

        if webhook_url and not is_bark:
            with ui.card().classes("w-full bg-gray-50 dark:bg-gray-800 p-4"):
                with ui.row().classes("gap-2 items-center"):
                    ui.icon("check_circle").classes("text-green-500")
                    ui.label("已配置").classes("text-green-600 font-medium")

                masked = (
                    webhook_url[:40] + "..." if len(webhook_url) > 40 else webhook_url
                )
                ui.label(f"URL: {masked}").classes("text-gray-500 text-sm font-mono")

                result_label = ui.label("").classes("mt-2 text-sm")

                async def test_webhook():
                    result_label.set_text("⏳ 正在发送...")
                    try:
                        import aiohttp

                        payload = {
                            "type": "system",
                            "level": "info",
                            "title": "AlgorithmTrader 通知测试",
                            "content": "Webhook 功能测试成功！",
                            "timestamp": __import__("datetime")
                            .datetime.now()
                            .isoformat(),
                        }
                        async with aiohttp.ClientSession(
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as session:
                            async with session.post(webhook_url, json=payload) as resp:
                                if resp.status in (200, 201, 204):
                                    result_label.set_text("✅ Webhook 测试成功！")
                                    result_label.classes(
                                        add="text-green-600", remove="text-red-600"
                                    )
                                else:
                                    result_label.set_text(f"❌ HTTP {resp.status}")
                                    result_label.classes(
                                        add="text-red-600", remove="text-green-600"
                                    )
                    except Exception as e:
                        result_label.set_text(f"❌ 错误: {e}")
                        result_label.classes(
                            add="text-red-600", remove="text-green-600"
                        )

                ui.button("🔔 测试 Webhook", on_click=test_webhook).props(
                    "color=primary"
                ).classes("mt-2")
        elif is_bark:
            ui.label(
                "当前 WEBHOOK_URL 已识别为 Bark，请在「Bark 推送」页签查看。"
            ).classes("text-gray-500 text-sm")
        else:
            with ui.column().classes("items-center py-6"):
                ui.icon("webhook").classes("text-4xl text-gray-300")
                ui.label("Webhook 尚未配置").classes("text-gray-400 mt-2")

        ui.separator().classes("my-4")
        with ui.expansion("配置说明", icon="help_outline").classes("w-full"):
            ui.markdown("""
**在 `.env` 中配置:**

```env
WEBHOOK_URL=https://your-webhook-endpoint.com/api/notify
```

请求会以 `POST` JSON 格式发送:
```json
{
    "type": "system",
    "level": "info",
    "title": "通知标题",
    "content": "通知内容",
    "timestamp": "2025-01-01T00:00:00"
}
```
            """).classes("text-sm")
