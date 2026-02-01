"""
策略管理页面

功能:
- 策略列表展示（真实数据）
- 策略启用/停用
- 策略参数配置
- 策略运行状态
- WebSocket 实时更新
"""

from nicegui import ui

from services.web.strategy_config import (
    StrategyRunConfig,
    get_config_manager,
)


def render():
    """渲染策略管理页面"""
    with ui.row().classes("w-full justify-between items-center mb-4"):
        ui.label("策略管理").classes("text-2xl font-bold")

        with ui.row().classes("gap-2"):
            ui.button("添加策略", icon="add", on_click=_add_strategy_dialog).props(
                "color=primary"
            )
            ui.button(
                "刷新", icon="refresh", on_click=lambda: ui.navigate.reload()
            ).props("flat")

    # 策略列表容器
    strategy_container = ui.column().classes("w-full")

    with strategy_container:
        _render_strategy_list()


def _get_strategies() -> list[dict]:
    """获取策略列表（真实数据）"""
    config_manager = get_config_manager()
    configs = config_manager.get_all()

    strategies = []
    for config in configs:
        param_space = config_manager.get_param_space(config.strategy_class)
        strategies.append(
            {
                "name": config.name,
                "class": config.strategy_class,
                "enabled": config.enabled,
                "symbols": config.symbols,
                "timeframe": config.timeframes[0] if config.timeframes else "15m",
                "status": config.status,
                "position": config.current_position,
                "today_pnl": config.today_pnl,
                "params": config.params,
                "param_space": param_space,
            }
        )

    # 如果没有配置，显示所有可用策略（未配置状态）
    if not strategies:
        available = config_manager.get_available_strategies()
        for strat in available:
            default_params = config_manager.get_default_params(strat["class_name"])
            strategies.append(
                {
                    "name": strat["name"],
                    "class": strat["class_name"],
                    "enabled": False,
                    "symbols": [],
                    "timeframe": "15m",
                    "status": "stopped",
                    "position": {},
                    "today_pnl": 0.0,
                    "params": default_params,
                    "param_space": strat["param_space"],
                }
            )

    return strategies


def _render_strategy_list():
    """渲染策略列表"""
    strategies = _get_strategies()

    with ui.card().classes("card w-full"):
        # 表格头
        with ui.row().classes(
            "w-full py-3 px-4 border-b border-gray-200 dark:border-gray-700 "
            "text-base font-medium text-gray-500 dark:text-gray-400"
        ):
            ui.label("启用").classes("w-16")
            ui.label("策略名称").classes("flex-1 min-w-40")
            ui.label("交易对").classes("w-36")
            ui.label("周期").classes("w-16")
            ui.label("当前持仓").classes("w-36")
            ui.label("今日 PnL").classes("w-28 text-right")
            ui.label("操作").classes("w-28 text-right")

        # 表格内容
        if not strategies:
            with ui.row().classes("w-full py-8 justify-center"):
                ui.label("暂无策略配置").classes("text-gray-400 text-lg")
        else:
            for strategy in strategies:
                _render_strategy_row(strategy)


def _render_strategy_row(strategy: dict):
    """渲染策略行"""
    with ui.row().classes(
        "w-full py-4 px-4 border-b border-gray-100 dark:border-gray-800 "
        "items-center hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors last:border-0"
    ):
        # 启用开关
        with ui.element("div").classes("w-16"):
            ui.switch(
                value=strategy["enabled"],
                on_change=lambda e, s=strategy: _toggle_strategy(s, e.value),
            ).props("dense")

        # 策略名称
        with ui.column().classes("flex-1 min-w-40 gap-0"):
            ui.label(strategy["name"]).classes("font-medium text-base")
            ui.label(strategy["class"]).classes("text-sm text-gray-400")

        # 交易对
        symbols_text = (
            ", ".join(strategy["symbols"]) if strategy["symbols"] else "未配置"
        )
        symbols_class = (
            "text-base" if strategy["symbols"] else "text-base text-gray-400 italic"
        )
        ui.label(symbols_text).classes(f"w-36 {symbols_class} truncate")

        # 周期
        ui.label(strategy["timeframe"]).classes("w-16 text-base")

        # 当前持仓
        with ui.column().classes("w-36 gap-0"):
            if strategy["position"]:
                for symbol, qty in strategy["position"].items():
                    if qty != 0:
                        qty_class = "text-green-600" if qty > 0 else "text-red-600"
                        ui.label(f"{symbol}: {qty:+.4f}").classes(
                            f"text-sm {qty_class}"
                        )
            else:
                ui.label("无持仓").classes("text-sm text-gray-400")

        # 今日 PnL
        pnl = strategy["today_pnl"]
        if pnl != 0:
            pnl_class = "text-green-600" if pnl >= 0 else "text-red-600"
            pnl_text = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        else:
            pnl_class = "text-gray-400"
            pnl_text = "$0.00"
        ui.label(pnl_text).classes(f"w-28 text-right text-base font-medium {pnl_class}")

        # 操作按钮
        with ui.row().classes("w-28 justify-end gap-1"):
            ui.button(
                icon="settings",
                on_click=lambda s=strategy: _open_params_dialog(s),
            ).props("flat dense round").tooltip("配置参数")
            ui.button(
                icon="article",
                on_click=lambda s=strategy: _view_logs(s),
            ).props("flat dense round").tooltip("查看日志")


def _toggle_strategy(strategy: dict, enabled: bool):
    """切换策略启用状态"""
    config_manager = get_config_manager()

    # 检查是否已配置
    config = config_manager.get(strategy["name"])

    if config:
        # 更新现有配置
        config_manager.update(strategy["name"], enabled=enabled)
    else:
        # 创建新配置
        new_config = StrategyRunConfig(
            name=strategy["name"],
            strategy_class=strategy["class"],
            enabled=enabled,
            symbols=strategy.get("symbols", []),
            params=strategy.get("params", {}),
        )
        config_manager.add(new_config)

    action = "启用" if enabled else "停用"

    if enabled and not strategy.get("symbols"):
        ui.notify(f"策略 {strategy['name']} 已启用，但请先配置交易对", type="warning")
    else:
        ui.notify(f"策略 {strategy['name']} 已{action}", type="positive")


def _add_strategy_dialog():
    """添加策略对话框"""
    config_manager = get_config_manager()
    available = config_manager.get_available_strategies()

    with ui.dialog() as dialog, ui.card().classes("min-w-[500px]"):
        ui.label("添加策略配置").classes("text-xl font-medium mb-4")

        # 策略选择
        strategy_options = [
            {"label": s["class_name"], "value": s["class_name"]} for s in available
        ]

        selected_strategy = ui.select(
            label="选择策略类型",
            options=strategy_options,
            value=strategy_options[0]["value"] if strategy_options else None,
        ).classes("w-full mb-4")

        # 配置名称
        config_name = ui.input(
            label="配置名称",
            placeholder="my_dual_ma_btc",
        ).classes("w-full mb-4")

        # 交易对
        symbols_input = ui.input(
            label="交易对（逗号分隔）",
            placeholder="BTC/USDT, ETH/USDT",
        ).classes("w-full mb-4")

        # 时间周期
        timeframe_select = ui.select(
            label="时间周期",
            options=["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            value="15m",
        ).classes("w-full mb-4")

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("取消", on_click=dialog.close).props("flat")

            def save_new_strategy():
                if not config_name.value:
                    ui.notify("请输入配置名称", type="negative")
                    return

                symbols = [
                    s.strip() for s in symbols_input.value.split(",") if s.strip()
                ]
                default_params = config_manager.get_default_params(
                    selected_strategy.value
                )

                new_config = StrategyRunConfig(
                    name=config_name.value,
                    strategy_class=selected_strategy.value,
                    enabled=False,
                    symbols=symbols,
                    timeframes=[timeframe_select.value],
                    params=default_params,
                )
                config_manager.add(new_config)

                ui.notify(f"策略配置 {config_name.value} 已创建", type="positive")
                dialog.close()
                ui.navigate.reload()

            ui.button("创建", on_click=save_new_strategy).props("color=primary")

    dialog.open()


def _open_params_dialog(strategy: dict):
    """打开参数配置对话框"""
    _ = get_config_manager()  # May be used in future
    param_space = strategy.get("param_space", {})

    with ui.dialog() as dialog, ui.card().classes("min-w-[550px]"):
        with ui.row().classes("w-full justify-between items-center mb-4"):
            ui.label(f"策略配置 - {strategy['name']}").classes("text-xl font-medium")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")

        # 参数编辑表单
        param_inputs = {}

        ui.label("策略参数").classes("text-base font-medium text-gray-500 mb-2")

        for key, value in strategy["params"].items():
            spec = param_space.get(key, {})
            description = spec.get("description", key)

            with ui.row().classes("w-full items-center gap-4 mb-2"):
                ui.label(description).classes("w-40 text-base")

                param_type = spec.get("type", "str")
                if param_type == "int":
                    param_inputs[key] = ui.number(
                        value=value,
                        min=spec.get("min"),
                        max=spec.get("max"),
                        step=spec.get("step", 1),
                    ).classes("flex-1")
                elif param_type == "float":
                    param_inputs[key] = ui.number(
                        value=value,
                        min=spec.get("min"),
                        max=spec.get("max"),
                        step=spec.get("step", 0.1),
                    ).classes("flex-1")
                elif param_type == "bool":
                    param_inputs[key] = ui.switch(value=value)
                else:
                    param_inputs[key] = ui.input(value=str(value)).classes("flex-1")

                # 范围提示
                if "min" in spec and "max" in spec:
                    ui.label(f"({spec['min']} ~ {spec['max']})").classes(
                        "text-sm text-gray-400 w-24"
                    )

        # 交易对配置
        ui.separator().classes("my-4")
        ui.label("交易配置").classes("text-base font-medium text-gray-500 mb-2")

        symbols_input = ui.input(
            label="交易对（逗号分隔）",
            value=", ".join(strategy["symbols"]),
            placeholder="BTC/USDT, ETH/USDT",
        ).classes("w-full mb-2")

        timeframe_select = ui.select(
            label="时间周期",
            options=["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            value=strategy["timeframe"],
        ).classes("w-full")

        # 按钮
        with ui.row().classes("w-full justify-end gap-2 mt-6"):
            ui.button("取消", on_click=dialog.close).props("flat")
            ui.button(
                "保存",
                on_click=lambda: _save_strategy_config(
                    strategy, param_inputs, symbols_input, timeframe_select, dialog
                ),
            ).props("color=primary")

    dialog.open()


def _save_strategy_config(
    strategy: dict,
    param_inputs: dict,
    symbols_input,
    timeframe_select,
    dialog,
):
    """保存策略配置"""
    config_manager = get_config_manager()

    # 收集参数值
    new_params = {}
    for key, widget in param_inputs.items():
        if hasattr(widget, "value"):
            new_params[key] = widget.value

    # 解析交易对
    symbols = [s.strip() for s in symbols_input.value.split(",") if s.strip()]

    # 检查是否已有配置
    config = config_manager.get(strategy["name"])

    if config:
        config_manager.update(
            strategy["name"],
            params=new_params,
            symbols=symbols,
            timeframes=[timeframe_select.value],
        )
    else:
        new_config = StrategyRunConfig(
            name=strategy["name"],
            strategy_class=strategy["class"],
            enabled=strategy["enabled"],
            symbols=symbols,
            timeframes=[timeframe_select.value],
            params=new_params,
        )
        config_manager.add(new_config)

    ui.notify("配置已保存", type="positive")
    dialog.close()


def _view_logs(strategy: dict):
    """查看策略日志"""
    with ui.dialog() as dialog, ui.card().classes("min-w-[700px] max-h-[80vh]"):
        with ui.row().classes("w-full justify-between items-center mb-4"):
            ui.label(f"运行日志 - {strategy['name']}").classes("text-xl font-medium")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")

        # 日志内容（TODO: 从 Loki 或日志文件读取）
        with ui.scroll_area().classes(
            "w-full h-96 bg-gray-100 dark:bg-gray-800 rounded p-4"
        ):
            # 示例日志
            logs = [
                {
                    "time": "10:30:15",
                    "level": "INFO",
                    "msg": "Bar received - BTC/USDT close=42350.5",
                },
                {
                    "time": "10:30:15",
                    "level": "INFO",
                    "msg": "Signal: HOLD (fast_ma=42100, slow_ma=42200)",
                },
                {
                    "time": "10:15:12",
                    "level": "INFO",
                    "msg": "Bar received - BTC/USDT close=42280.0",
                },
                {
                    "time": "10:15:12",
                    "level": "INFO",
                    "msg": "Signal: HOLD (fast_ma=42080, slow_ma=42180)",
                },
                {
                    "time": "10:00:10",
                    "level": "INFO",
                    "msg": "Bar received - BTC/USDT close=42150.0",
                },
                {
                    "time": "10:00:10",
                    "level": "WARN",
                    "msg": "Signal: BUY - Golden cross detected",
                },
                {
                    "time": "10:00:11",
                    "level": "INFO",
                    "msg": "Order placed: BUY 0.5 BTC/USDT @ market",
                },
                {
                    "time": "10:00:12",
                    "level": "INFO",
                    "msg": "Order filled: 0.5 BTC/USDT @ 42155.0",
                },
            ]

            if not logs:
                ui.label("暂无日志").classes("text-gray-400 text-center py-8")
            else:
                for log in logs:
                    level_class = {
                        "INFO": "text-gray-600 dark:text-gray-300",
                        "WARN": "text-yellow-600 dark:text-yellow-400",
                        "ERROR": "text-red-600 dark:text-red-400",
                    }.get(log["level"], "text-gray-600")

                    with ui.row().classes("gap-2"):
                        ui.label(f"[{log['time']}]").classes(
                            "text-sm font-mono text-gray-400"
                        )
                        ui.label(log["level"]).classes(
                            f"text-sm font-mono font-medium {level_class}"
                        )
                        ui.label(log["msg"]).classes(f"text-sm font-mono {level_class}")

    dialog.open()
