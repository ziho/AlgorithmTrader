"""
状态卡片组件

用于显示服务健康状态
"""

from nicegui import ui


def render(
    title: str,
    status: str = "unknown",
    message: str = "",
    last_check: str = "",
):
    """
    渲染状态卡片

    Args:
        title: 标题
        status: 状态 (healthy, warning, error, unknown)
        message: 状态消息
        last_check: 最后检查时间
    """
    status_config = {
        "healthy": {
            "icon": "check_circle",
            "color": "text-green-600 dark:text-green-400",
            "bg": "bg-green-50 dark:bg-green-900/20",
            "label": "正常",
        },
        "warning": {
            "icon": "warning",
            "color": "text-yellow-600 dark:text-yellow-400",
            "bg": "bg-yellow-50 dark:bg-yellow-900/20",
            "label": "警告",
        },
        "error": {
            "icon": "error",
            "color": "text-red-600 dark:text-red-400",
            "bg": "bg-red-50 dark:bg-red-900/20",
            "label": "异常",
        },
        "unknown": {
            "icon": "help",
            "color": "text-gray-600 dark:text-gray-400",
            "bg": "bg-gray-50 dark:bg-gray-800",
            "label": "未知",
        },
    }

    config = status_config.get(status, status_config["unknown"])

    with ui.card().classes(f"card min-w-40 {config['bg']}"):
        with ui.row().classes("items-center gap-2"):
            ui.icon(config["icon"]).classes(f"text-xl {config['color']}")
            ui.label(title).classes("font-medium")

        with ui.row().classes("items-center gap-2 mt-2"):
            ui.label(config["label"]).classes(f"text-sm {config['color']}")
            if message:
                ui.label(f"- {message}").classes("text-sm text-gray-500")

        if last_check:
            ui.label(f"最后检查: {last_check}").classes("text-xs text-gray-400 mt-1")
