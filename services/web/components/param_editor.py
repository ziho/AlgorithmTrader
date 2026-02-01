"""
参数编辑器组件

用于编辑策略参数
"""

from collections.abc import Callable
from typing import Any

from nicegui import ui


def render(
    params: dict[str, Any],
    param_space: dict[str, dict] | None = None,
    on_save: Callable[[dict[str, Any]], None] | None = None,
    on_cancel: Callable[[], None] | None = None,
):
    """
    渲染参数编辑器

    Args:
        params: 当前参数值
        param_space: 参数范围定义 (可选)
        on_save: 保存回调
        on_cancel: 取消回调
    """
    param_inputs: dict[str, Any] = {}

    for key, value in params.items():
        space = param_space.get(key, {}) if param_space else {}

        with ui.row().classes("w-full items-center gap-4 mb-2"):
            # 参数名
            ui.label(key).classes("w-32 text-sm font-medium")

            # 输入控件
            param_type = space.get("type", _infer_type(value))

            if param_type == "int":
                input_widget = ui.number(
                    value=value,
                    min=space.get("min"),
                    max=space.get("max"),
                    step=space.get("step", 1),
                ).classes("flex-1")
            elif param_type == "float":
                input_widget = ui.number(
                    value=value,
                    min=space.get("min"),
                    max=space.get("max"),
                    step=space.get("step", 0.1),
                    format="%.2f",
                ).classes("flex-1")
            elif param_type == "bool":
                input_widget = ui.switch(value=value)
            elif param_type == "choice":
                input_widget = ui.select(
                    options=space.get("choices", [value]),
                    value=value,
                ).classes("flex-1")
            else:
                input_widget = ui.input(value=str(value)).classes("flex-1")

            param_inputs[key] = input_widget

            # 范围提示
            if space:
                hint = _format_range_hint(space)
                if hint:
                    ui.label(hint).classes("text-xs text-gray-400 w-24")

    # 按钮
    with ui.row().classes("w-full justify-end gap-2 mt-4"):
        if on_cancel:
            ui.button("取消", on_click=on_cancel).props("flat")

        if on_save:

            def save():
                values = {}
                for key, widget in param_inputs.items():
                    if hasattr(widget, "value"):
                        values[key] = widget.value
                on_save(values)

            ui.button("保存", on_click=save).props("color=primary")

    return param_inputs


def _infer_type(value: Any) -> str:
    """推断参数类型"""
    if isinstance(value, bool):
        return "bool"
    elif isinstance(value, int):
        return "int"
    elif isinstance(value, float):
        return "float"
    else:
        return "str"


def _format_range_hint(space: dict) -> str:
    """格式化范围提示"""
    parts = []

    if "min" in space and "max" in space:
        parts.append(f"{space['min']} ~ {space['max']}")
    elif "min" in space:
        parts.append(f">= {space['min']}")
    elif "max" in space:
        parts.append(f"<= {space['max']}")

    if "step" in space:
        parts.append(f"步长 {space['step']}")

    return ", ".join(parts)


def render_readonly(params: dict[str, Any]):
    """
    渲染只读参数展示

    Args:
        params: 参数值
    """
    with ui.row().classes("w-full gap-4 flex-wrap"):
        for key, value in params.items():
            with ui.card().classes("bg-gray-50 dark:bg-gray-800 px-4 py-2"):
                ui.label(key).classes("text-xs text-gray-400")
                ui.label(str(value)).classes("font-medium")
