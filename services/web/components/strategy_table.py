"""
策略表格组件

用于展示策略列表
"""

from collections.abc import Callable

from nicegui import ui


def render(
    strategies: list[dict],
    on_toggle: Callable[[dict, bool], None] | None = None,
    on_edit: Callable[[dict], None] | None = None,
    on_logs: Callable[[dict], None] | None = None,
):
    """
    渲染策略表格

    Args:
        strategies: 策略列表
        on_toggle: 切换启用状态回调
        on_edit: 编辑参数回调
        on_logs: 查看日志回调
    """
    with ui.card().classes("card w-full"):
        # 表格头
        with ui.row().classes(
            "w-full py-3 px-4 border-b border-gray-200 dark:border-gray-700 "
            "text-sm font-medium text-gray-500 dark:text-gray-400"
        ):
            ui.label("状态").classes("w-16")
            ui.label("策略名称").classes("flex-1 min-w-40")
            ui.label("交易对").classes("w-32")
            ui.label("周期").classes("w-16")
            ui.label("当前持仓").classes("w-32")
            ui.label("今日 PnL").classes("w-24 text-right")
            ui.label("操作").classes("w-24 text-right")

        # 表格内容
        if not strategies:
            with ui.row().classes("w-full py-8 justify-center"):
                ui.label("暂无策略").classes("text-gray-400")
        else:
            for strategy in strategies:
                _render_row(strategy, on_toggle, on_edit, on_logs)


def _render_row(
    strategy: dict,
    on_toggle: Callable[[dict, bool], None] | None,
    on_edit: Callable[[dict], None] | None,
    on_logs: Callable[[dict], None] | None,
):
    """渲染策略行"""
    with ui.row().classes(
        "w-full py-3 px-4 border-b border-gray-100 dark:border-gray-800 "
        "items-center hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors last:border-0"
    ):
        # 启用开关
        with ui.element("div").classes("w-16"):
            ui.switch(
                value=strategy.get("enabled", False),
                on_change=lambda e, s=strategy: on_toggle(s, e.value)
                if on_toggle
                else None,
            ).props("dense")

        # 策略名称
        with ui.column().classes("flex-1 min-w-40 gap-0"):
            ui.label(strategy.get("name", "unnamed")).classes("font-medium")
            ui.label(strategy.get("class", "")).classes("text-xs text-gray-400")

        # 交易对
        symbols = strategy.get("symbols", [])
        symbols_text = ", ".join(symbols) if symbols else "-"
        ui.label(symbols_text).classes("w-32 text-sm truncate")

        # 周期
        ui.label(strategy.get("timeframe", "-")).classes("w-16 text-sm")

        # 当前持仓
        with ui.column().classes("w-32 gap-0"):
            position = strategy.get("position", {})
            if position:
                for symbol, qty in position.items():
                    if qty != 0:
                        ui.label(f"{symbol}: {qty}").classes("text-xs")
            else:
                ui.label("-").classes("text-sm text-gray-400")

        # 今日 PnL
        pnl = strategy.get("today_pnl", 0.0)
        pnl_class = "text-green-600" if pnl >= 0 else "text-red-600"
        pnl_text = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        ui.label(pnl_text).classes(f"w-24 text-right text-sm font-medium {pnl_class}")

        # 操作按钮
        with ui.row().classes("w-24 justify-end gap-1"):
            ui.button(
                icon="settings",
                on_click=lambda s=strategy: on_edit(s) if on_edit else None,
            ).props("flat dense round size=sm")
            ui.button(
                icon="article",
                on_click=lambda s=strategy: on_logs(s) if on_logs else None,
            ).props("flat dense round size=sm")
