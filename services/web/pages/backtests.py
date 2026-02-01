"""
回测结果页面

功能:
- 回测历史列表
- 新建回测任务
- 回测详情展示
- 多回测对比
"""

from datetime import datetime
from pathlib import Path

from nicegui import ui

from services.web.backtest_manager import BacktestRecord, BacktestResultManager
from services.web.strategy_config import STRATEGY_PARAM_SPACES, StrategyConfigManager


# 配置路径
CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config"
BACKTESTS_PATH = CONFIG_PATH / "backtests.json"
STRATEGIES_PATH = CONFIG_PATH / "strategies.json"


def render():
    """渲染回测结果页面"""
    with ui.row().classes("w-full justify-between items-center mb-4"):
        ui.label("回测结果").classes("text-2xl font-bold")
        
        with ui.row().classes("gap-2"):
            ui.button("对比选中", icon="compare_arrows", on_click=_compare_selected).props(
                "flat"
            )
            ui.button("新建回测", icon="add", on_click=_new_backtest).props("color=primary")
    
    # 筛选条件
    with ui.row().classes("w-full gap-4 mb-4"):
        strategy_filter = ui.select(
            label="策略",
            options=["全部"] + list(STRATEGY_PARAM_SPACES.keys()),
            value="全部",
        ).classes("min-w-32")
        
        status_filter = ui.select(
            label="状态",
            options=["全部", "completed", "running", "pending", "failed"],
            value="全部",
        ).classes("min-w-32")
    
    # 回测列表
    backtest_container = ui.column().classes("w-full")
    
    def refresh_list():
        backtest_container.clear()
        with backtest_container:
            _render_backtest_list(
                strategy=strategy_filter.value if strategy_filter.value != "全部" else None,
                status=status_filter.value if status_filter.value != "全部" else None,
            )
    
    strategy_filter.on("update:model-value", lambda: refresh_list())
    status_filter.on("update:model-value", lambda: refresh_list())
    
    with backtest_container:
        _render_backtest_list()


def _compare_selected():
    """对比选中的回测"""
    ui.notify("请选择 2-5 个回测进行对比", type="info")


def _new_backtest():
    """新建回测"""
    # 获取可用策略列表
    available_strategies = list(STRATEGY_PARAM_SPACES.keys())
    
    # 尝试获取已配置的策略
    configured_strategies = []
    try:
        manager = StrategyConfigManager(config_path=STRATEGIES_PATH)
        manager.load()
        configured_strategies = [s.name for s in manager.get_all()]
    except Exception:
        pass
    
    with ui.dialog() as dialog, ui.card().classes("min-w-[600px] max-h-[90vh] overflow-auto"):
        ui.label("新建回测").classes("text-lg font-medium mb-4")
        
        # 策略来源选择
        ui.label("策略来源").classes("text-sm font-medium mb-2")
        source_tabs = ui.tabs().classes("w-full mb-4")
        with source_tabs:
            tab_registry = ui.tab("策略注册表")
            tab_configured = ui.tab("已配置策略")
        
        with ui.tab_panels(source_tabs, value=tab_registry).classes("w-full"):
            # 从策略注册表选择
            with ui.tab_panel(tab_registry):
                strategy_select = ui.select(
                    label="选择策略类",
                    options=[{"label": s, "value": s} for s in available_strategies],
                    value=available_strategies[0] if available_strategies else None,
                ).classes("w-full mb-4")
                
                # 参数编辑
                ui.label("策略参数").classes("text-sm font-medium mb-2")
                params_container = ui.column().classes("w-full mb-4")
                param_inputs = {}
                
                def update_params():
                    param_inputs.clear()
                    params_container.clear()
                    
                    strategy = strategy_select.value
                    if strategy and strategy in STRATEGY_PARAM_SPACES:
                        with params_container:
                            for name, spec in STRATEGY_PARAM_SPACES[strategy].items():
                                with ui.row().classes("w-full gap-4 items-center"):
                                    if spec["type"] == "int":
                                        inp = ui.number(
                                            label=name,
                                            value=spec["default"],
                                            min=spec["min"],
                                            max=spec["max"],
                                        ).classes("flex-1")
                                    elif spec["type"] == "float":
                                        inp = ui.number(
                                            label=name,
                                            value=spec["default"],
                                            min=spec["min"],
                                            max=spec["max"],
                                            step=0.01,
                                        ).classes("flex-1")
                                    elif spec["type"] == "bool":
                                        inp = ui.checkbox(name, value=spec["default"])
                                    else:
                                        inp = ui.input(label=name, value=str(spec["default"])).classes("flex-1")
                                    param_inputs[name] = inp
                
                strategy_select.on("update:model-value", lambda: update_params())
                update_params()
            
            # 从已配置策略选择
            with ui.tab_panel(tab_configured):
                if configured_strategies:
                    configured_select = ui.select(
                        label="选择已配置策略",
                        options=[{"label": s, "value": s} for s in configured_strategies],
                        value=configured_strategies[0],
                    ).classes("w-full mb-4")
                else:
                    ui.label("暂无已配置策略，请先在策略页面添加").classes("text-gray-500")
                    configured_select = None
        
        # 交易对和时间范围
        ui.label("数据设置").classes("text-sm font-medium mt-4 mb-2")
        with ui.row().classes("w-full gap-4"):
            symbol_input = ui.select(
                label="交易对",
                options=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
                value="BTC/USDT",
            ).classes("flex-1")
            
            timeframe_input = ui.select(
                label="时间周期",
                options=["1m", "5m", "15m", "1h", "4h", "1d"],
                value="15m",
            ).classes("flex-1")
        
        with ui.row().classes("w-full gap-4 mt-2"):
            start_date = ui.input(label="开始日期", value="2024-01-01").classes("flex-1")
            end_date = ui.input(label="结束日期", value="2025-12-31").classes("flex-1")
        
        # 资金设置
        ui.label("资金设置").classes("text-sm font-medium mt-4 mb-2")
        initial_capital = ui.number(
            label="初始资金",
            value=100000,
            min=1000,
            step=1000,
        ).classes("w-full")
        
        with ui.row().classes("w-full justify-end gap-2 mt-6"):
            ui.button("取消", on_click=dialog.close).props("flat")
            
            def submit():
                # 收集参数
                if source_tabs.value == "策略注册表":
                    strategy_class = strategy_select.value
                    params = {}
                    for name, inp in param_inputs.items():
                        if hasattr(inp, 'value'):
                            params[name] = inp.value
                else:
                    if configured_select:
                        # 从已配置策略获取
                        try:
                            manager = StrategyConfigManager(config_path=STRATEGIES_PATH)
                            manager.load()
                            config = manager.get(configured_select.value)
                            if config:
                                strategy_class = config.strategy_class
                                params = config.params
                            else:
                                ui.notify("未找到策略配置", type="warning")
                                return
                        except Exception as e:
                            ui.notify(f"加载策略失败: {e}", type="negative")
                            return
                    else:
                        ui.notify("请先配置策略", type="warning")
                        return
                
                # 创建回测记录
                record = BacktestRecord(
                    id=f"bt_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_class=strategy_class,
                    strategy_params=params,
                    symbol=symbol_input.value,
                    timeframe=timeframe_input.value,
                    start_date=start_date.value,
                    end_date=end_date.value,
                    initial_capital=initial_capital.value,
                    status="pending",
                    created_at=datetime.now().isoformat(),
                )
                
                # 保存
                manager = BacktestResultManager(config_path=BACKTESTS_PATH)
                manager.add(record)
                
                ui.notify(f"回测任务 {record.id} 已提交", type="positive")
                dialog.close()
                ui.navigate.reload()
            
            ui.button("开始回测", on_click=submit).props("color=primary")
    
    dialog.open()


def _render_backtest_list(strategy: str | None = None, status: str | None = None):
    """渲染回测列表"""
    manager = BacktestResultManager(config_path=BACKTESTS_PATH)
    records = manager.filter(strategy=strategy, status=status)
    
    # 按创建时间倒序排列
    records = sorted(records, key=lambda r: r.created_at, reverse=True)
    
    if not records:
        with ui.card().classes("card w-full"):
            ui.label("暂无回测记录").classes("text-gray-400 text-center py-8")
            ui.label("点击「新建回测」开始回测").classes("text-xs text-gray-400 text-center")
        return
    
    with ui.card().classes("card w-full overflow-x-auto"):
        # 表格头
        with ui.row().classes(
            "w-full min-w-[900px] py-3 px-4 border-b border-gray-200 dark:border-gray-700 font-medium text-sm text-gray-500"
        ):
            ui.checkbox().classes("w-8")
            ui.label("ID").classes("w-32")
            ui.label("策略").classes("w-40")
            ui.label("交易对").classes("w-24")
            ui.label("时间范围").classes("flex-1")
            ui.label("收益率").classes("w-20 text-right")
            ui.label("夏普").classes("w-16 text-right")
            ui.label("回撤").classes("w-16 text-right")
            ui.label("状态").classes("w-24 text-center")
            ui.label("操作").classes("w-20 text-center")
        
        # 数据行
        for record in records:
            _render_backtest_row(record)


def _render_backtest_row(record: BacktestRecord):
    """渲染回测行"""
    metrics = record.metrics or {}
    
    with ui.row().classes(
        "w-full min-w-[900px] py-3 px-4 border-b border-gray-100 dark:border-gray-800 items-center hover:bg-gray-50 dark:hover:bg-gray-800/50"
    ):
        ui.checkbox().classes("w-8")
        
        # ID
        ui.label(record.id).classes("w-32 text-xs font-mono truncate")
        
        # 策略
        ui.label(record.strategy_class).classes("w-40 truncate")
        
        # 交易对
        ui.label(record.symbol).classes("w-24")
        
        # 时间范围
        ui.label(f"{record.start_date} ~ {record.end_date}").classes("flex-1 text-sm")
        
        # 收益率
        total_return = metrics.get("total_return", 0)
        if record.status == "completed":
            return_class = "text-green-600" if total_return >= 0 else "text-red-600"
            ui.label(f"{total_return:.1%}").classes(f"w-20 text-right {return_class}")
        else:
            ui.label("-").classes("w-20 text-right text-gray-400")
        
        # 夏普
        sharpe = metrics.get("sharpe_ratio", 0)
        if record.status == "completed":
            ui.label(f"{sharpe:.2f}").classes("w-16 text-right")
        else:
            ui.label("-").classes("w-16 text-right text-gray-400")
        
        # 回撤
        max_dd = metrics.get("max_drawdown", 0)
        if record.status == "completed":
            ui.label(f"{max_dd:.1%}").classes("w-16 text-right text-red-600")
        else:
            ui.label("-").classes("w-16 text-right text-gray-400")
        
        # 状态
        with ui.row().classes("w-24 justify-center"):
            status_colors = {
                "completed": "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
                "running": "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
                "pending": "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
                "failed": "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
            }
            status_class = status_colors.get(record.status, status_colors["pending"])
            ui.label(record.status).classes(f"text-xs px-2 py-1 rounded {status_class}")
        
        # 操作
        with ui.row().classes("w-20 justify-center gap-1"):
            ui.button(
                icon="visibility",
                on_click=lambda r=record: _show_detail(r),
            ).props("flat dense size=sm")
            
            ui.button(
                icon="delete",
                on_click=lambda r=record: _delete_backtest(r),
            ).props("flat dense size=sm color=negative")


def _show_detail(record: BacktestRecord):
    """显示回测详情"""
    with ui.dialog() as dialog, ui.card().classes("min-w-[700px] max-h-[90vh] overflow-auto"):
        ui.label(f"回测详情 - {record.id}").classes("text-lg font-medium mb-4")
        
        # 基本信息
        with ui.card().classes("w-full bg-gray-50 dark:bg-gray-800 p-4 mb-4"):
            with ui.row().classes("w-full gap-8"):
                with ui.column().classes("gap-1"):
                    ui.label("策略").classes("text-xs text-gray-500")
                    ui.label(record.strategy_class).classes("font-medium")
                
                with ui.column().classes("gap-1"):
                    ui.label("交易对").classes("text-xs text-gray-500")
                    ui.label(record.symbol).classes("font-medium")
                
                with ui.column().classes("gap-1"):
                    ui.label("时间周期").classes("text-xs text-gray-500")
                    ui.label(record.timeframe).classes("font-medium")
                
                with ui.column().classes("gap-1"):
                    ui.label("初始资金").classes("text-xs text-gray-500")
                    ui.label(f"${record.initial_capital:,.0f}").classes("font-medium")
        
        # 策略参数
        if record.strategy_params:
            ui.label("策略参数").classes("text-sm font-medium mb-2")
            with ui.row().classes("w-full gap-4 flex-wrap mb-4"):
                for name, value in record.strategy_params.items():
                    with ui.card().classes("p-2 bg-gray-50 dark:bg-gray-800"):
                        ui.label(name).classes("text-xs text-gray-500")
                        ui.label(str(value)).classes("font-medium")
        
        # 性能指标
        if record.status == "completed" and record.metrics:
            ui.label("性能指标").classes("text-sm font-medium mb-2")
            metrics = record.metrics
            
            with ui.row().classes("w-full gap-4 flex-wrap mb-4"):
                _render_metric_card("总收益", metrics.get("total_return", 0), "{:.1%}")
                _render_metric_card("年化收益", metrics.get("annualized_return", 0), "{:.1%}")
                _render_metric_card("夏普比率", metrics.get("sharpe_ratio", 0), "{:.2f}")
                _render_metric_card("索提诺比率", metrics.get("sortino_ratio", 0), "{:.2f}")
                _render_metric_card("最大回撤", metrics.get("max_drawdown", 0), "{:.1%}")
                _render_metric_card("卡尔马比率", metrics.get("calmar_ratio", 0), "{:.2f}")
            
            # 交易统计
            trade_stats = metrics.get("trade_stats", {})
            if trade_stats:
                ui.label("交易统计").classes("text-sm font-medium mb-2")
                with ui.row().classes("w-full gap-4 flex-wrap mb-4"):
                    _render_metric_card("总交易", trade_stats.get("total_trades", 0), "{}")
                    _render_metric_card("胜率", trade_stats.get("win_rate", 0), "{:.1%}")
                    _render_metric_card("盈亏比", trade_stats.get("profit_factor", 0), "{:.2f}")
        
        elif record.status == "failed":
            ui.label("错误信息").classes("text-sm font-medium mb-2")
            with ui.card().classes("w-full bg-red-50 dark:bg-red-900/20 p-4 mb-4"):
                ui.label(record.error or "未知错误").classes("text-red-600 dark:text-red-400")
        
        elif record.status == "running":
            with ui.row().classes("w-full items-center gap-4 mb-4"):
                ui.spinner()
                ui.label("回测正在运行中...").classes("text-gray-500")
        
        ui.button("关闭", on_click=dialog.close).props("flat")
    
    dialog.open()


def _render_metric_card(label: str, value: float, fmt: str):
    """渲染指标卡片"""
    with ui.card().classes("p-3 bg-gray-50 dark:bg-gray-800 min-w-28"):
        ui.label(label).classes("text-xs text-gray-500")
        try:
            formatted = fmt.format(value)
        except Exception:
            formatted = str(value)
        ui.label(formatted).classes("text-lg font-medium")


def _delete_backtest(record: BacktestRecord):
    """删除回测记录"""
    with ui.dialog() as dialog, ui.card():
        ui.label(f"确定删除回测 {record.id} 吗？").classes("mb-4")
        
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("取消", on_click=dialog.close).props("flat")
            
            def confirm():
                manager = BacktestResultManager(config_path=BACKTESTS_PATH)
                manager.delete(record.id)
                ui.notify("已删除", type="positive")
                dialog.close()
                ui.navigate.reload()
            
            ui.button("删除", on_click=confirm).props("color=negative")
    
    dialog.open()
