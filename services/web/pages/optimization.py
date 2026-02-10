"""
参数优化页面

功能:
- 创建优化任务
- 任务队列/进度展示
- 优化结果展示
- Walk-Forward 验证
- 一键应用最优参数
"""

import json
from datetime import datetime
from pathlib import Path

from nicegui import ui

from services.web.strategy_config import (
    STRATEGY_PARAM_SPACES,
    StrategyConfigManager,
)

# 配置路径
CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config"
OPTIMIZATION_RESULTS_PATH = CONFIG_PATH / "optimization_results.json"


def render():
    """渲染参数优化页面"""
    with ui.row().classes("w-full justify-between items-center mb-4"):
        ui.label("参数优化").classes("text-2xl font-bold")
        ui.button("新建优化任务", icon="add", on_click=_new_optimization).props(
            "color=primary"
        )

    # 任务队列
    _render_task_queue()

    # 已完成的优化结果
    ui.label("优化结果").classes("text-lg font-medium mt-6 mb-4")
    _render_optimization_results()


def _new_optimization():
    """新建优化任务"""
    # 获取可用策略列表
    available_strategies = list(STRATEGY_PARAM_SPACES.keys())

    with (
        ui.dialog() as dialog,
        ui.card().classes("min-w-[600px] max-h-[90vh] overflow-auto"),
    ):
        ui.label("新建优化任务").classes("text-lg font-medium mb-4")

        # 策略选择
        strategy_select = ui.select(
            label="选择策略",
            options=[{"label": s, "value": s} for s in available_strategies],
            value=available_strategies[0] if available_strategies else None,
        ).classes("w-full mb-4")

        # 参数范围预览（动态更新）
        param_preview = ui.card().classes("w-full bg-gray-50 dark:bg-gray-800 p-4 mb-4")

        def update_param_preview():
            param_preview.clear()
            with param_preview:
                strategy = strategy_select.value
                if strategy and strategy in STRATEGY_PARAM_SPACES:
                    params = STRATEGY_PARAM_SPACES[strategy]
                    total_combinations = 1
                    for name, spec in params.items():
                        if spec["type"] == "int":
                            step = spec.get("step", 1)
                            count = (spec["max"] - spec["min"]) // step + 1
                            ui.label(
                                f"{name}: {spec['min']} ~ {spec['max']}, step={step}"
                            ).classes("text-xs font-mono")
                            total_combinations *= count
                        elif spec["type"] == "float":
                            ui.label(f"{name}: {spec['min']} ~ {spec['max']}").classes(
                                "text-xs font-mono"
                            )
                            total_combinations *= 10  # 估算
                        elif spec["type"] == "bool":
                            ui.label(f"{name}: True/False").classes("text-xs font-mono")
                            total_combinations *= 2
                    ui.label(f"预计组合数: {total_combinations}").classes(
                        "text-xs text-gray-500 mt-2"
                    )

        strategy_select.on("update:model-value", lambda _: update_param_preview())
        update_param_preview()

        # 优化目标（多选）
        ui.label("优化目标").classes("text-sm font-medium mb-2")
        with ui.row().classes("w-full gap-4 mb-4"):
            obj_sharpe = ui.checkbox("夏普比率", value=True)
            obj_return = ui.checkbox("总收益", value=True)
            obj_drawdown = ui.checkbox("最小回撤", value=True)
            obj_calmar = ui.checkbox("卡尔马比率", value=False)

        # 目标权重
        ui.label("目标权重").classes("text-sm font-medium mb-2")
        with ui.row().classes("w-full gap-4 mb-4"):
            weight_sharpe = ui.number(
                label="夏普", value=0.5, min=0, max=1, step=0.1
            ).classes("flex-1")
            weight_return = ui.number(
                label="收益", value=0.25, min=0, max=1, step=0.1
            ).classes("flex-1")
            weight_drawdown = ui.number(
                label="回撤", value=0.25, min=0, max=1, step=0.1
            ).classes("flex-1")

        # 优化方法
        method_select = ui.select(
            label="优化方法",
            options=[
                {"label": "网格搜索 (Grid Search)", "value": "grid"},
                {"label": "随机搜索 (Random Search)", "value": "random"},
                {"label": "拉丁超立方采样 (LHS)", "value": "lhs"},
            ],
            value="grid",
        ).classes("w-full mb-4")

        # 随机搜索/LHS 的采样数
        n_samples = ui.number(
            label="采样数 (仅随机搜索/LHS)",
            value=100,
            min=10,
            max=1000,
        ).classes("w-full mb-4")

        # 数据范围
        ui.label("数据范围").classes("text-sm font-medium mb-2")
        with ui.row().classes("w-full gap-4 mb-4"):
            start_date = ui.input(label="开始日期", value="2024-01-01").classes(
                "flex-1"
            )
            end_date = ui.input(label="结束日期", value="2025-12-31").classes("flex-1")

        # Walk-Forward 验证设置
        ui.label("验证设置").classes("text-sm font-medium mb-2")
        walk_forward = ui.checkbox("启用 Walk-Forward 验证", value=True)
        with ui.row().classes("w-full gap-4 mb-4"):
            train_days = ui.number(
                label="训练期(天)", value=180, min=30, max=365
            ).classes("flex-1")
            test_days = ui.number(label="测试期(天)", value=30, min=7, max=90).classes(
                "flex-1"
            )
            n_splits = ui.number(label="分割数", value=6, min=2, max=12).classes(
                "flex-1"
            )

        # 交易对
        symbols_input = ui.input(
            label="交易对",
            value="BTC/USDT",
            placeholder="BTC/USDT, ETH/USDT",
        ).classes("w-full mb-4")

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("取消", on_click=dialog.close).props("flat")

            def submit():
                config = {
                    "strategy": strategy_select.value,
                    "method": method_select.value,
                    "n_samples": n_samples.value,
                    "objectives": {
                        "sharpe": obj_sharpe.value,
                        "return": obj_return.value,
                        "drawdown": obj_drawdown.value,
                        "calmar": obj_calmar.value,
                    },
                    "weights": {
                        "sharpe": weight_sharpe.value,
                        "return": weight_return.value,
                        "drawdown": weight_drawdown.value,
                    },
                    "start_date": start_date.value,
                    "end_date": end_date.value,
                    "walk_forward": {
                        "enabled": walk_forward.value,
                        "train_days": train_days.value,
                        "test_days": test_days.value,
                        "n_splits": n_splits.value,
                    },
                    "symbols": [s.strip() for s in symbols_input.value.split(",")],
                }
                _start_optimization(dialog, config)

            ui.button("开始优化", on_click=submit).props("color=primary")

    dialog.open()


def _start_optimization(dialog, config: dict):
    """开始优化"""
    # 保存任务配置
    task = {
        "id": f"opt_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "status": "pending",
        "progress": 0,
        "created_at": datetime.now().isoformat(),
        "config": config,
    }

    # 保存到任务队列
    _save_task(task)

    ui.notify(f"优化任务 {task['id']} 已提交", type="positive")
    dialog.close()

    # 刷新页面
    ui.navigate.reload()


def _save_task(task: dict):
    """保存优化任务"""
    tasks_file = CONFIG_PATH / "optimization_tasks.json"

    tasks = []
    if tasks_file.exists():
        try:
            tasks = json.loads(tasks_file.read_text())
        except Exception:
            pass

    tasks.append(task)
    _write_tasks(tasks)


def _write_tasks(tasks: list[dict]) -> None:
    """写入任务列表"""
    tasks_file = CONFIG_PATH / "optimization_tasks.json"
    CONFIG_PATH.mkdir(parents=True, exist_ok=True)
    tasks_file.write_text(json.dumps(tasks, indent=2, default=str))


def _load_tasks() -> list[dict]:
    """加载优化任务"""
    tasks_file = CONFIG_PATH / "optimization_tasks.json"
    if not tasks_file.exists():
        return []

    try:
        return json.loads(tasks_file.read_text())
    except Exception:
        return []


def _update_task(task_id: str, **changes) -> bool:
    """更新任务状态"""
    tasks = _load_tasks()
    updated = False
    for task in tasks:
        if task.get("id") == task_id:
            task.update(changes)
            updated = True
            break
    if updated:
        _write_tasks(tasks)
    return updated


def _start_task(task_id: str):
    """标记任务为运行中"""
    if _update_task(
        task_id,
        status="running",
        progress=0,
        started_at=datetime.now().isoformat(),
    ):
        ui.notify(f"任务 {task_id} 已开始", type="positive")
        ui.navigate.reload()
    else:
        ui.notify("任务不存在或已更新", type="warning")


def _cancel_task(task_id: str):
    """取消任务"""
    if _update_task(
        task_id,
        status="canceled",
        progress=0,
        canceled_at=datetime.now().isoformat(),
    ):
        ui.notify(f"任务 {task_id} 已取消", type="warning")
        ui.navigate.reload()
    else:
        ui.notify("任务不存在或已更新", type="warning")


def _load_results() -> list[dict]:
    """加载优化结果"""
    if not OPTIMIZATION_RESULTS_PATH.exists():
        return []

    try:
        return json.loads(OPTIMIZATION_RESULTS_PATH.read_text())
    except Exception:
        return []


def _render_task_queue():
    """渲染任务队列"""
    tasks = _load_tasks()

    # 只显示未完成的任务
    pending_tasks = [t for t in tasks if t.get("status") in ("pending", "running")]

    if not pending_tasks:
        return

    ui.label("任务队列").classes("text-lg font-medium mb-4")

    with ui.card().classes("card w-full"):
        for task in pending_tasks:
            _render_task_row(task)


def _render_task_row(task: dict):
    """渲染任务行"""
    config = task.get("config", {})

    with ui.row().classes(
        "w-full items-center gap-4 py-3 border-b border-gray-100 dark:border-gray-700 last:border-0"
    ):
        # 状态图标
        status = task.get("status", "pending")
        if status == "running":
            ui.spinner(size="sm")
        elif status == "pending":
            ui.icon("schedule").classes("text-gray-400")
        elif status == "canceled":
            ui.icon("cancel").classes("text-gray-400")
        elif status == "completed":
            ui.icon("check_circle").classes("text-green-600")
        else:
            ui.icon("error").classes("text-red-600")

        # 任务信息
        with ui.column().classes("flex-1 gap-0"):
            ui.label(
                f"{config.get('strategy', 'Unknown')} - {task.get('id', '')}"
            ).classes("font-medium")
            ui.label(
                f"方法: {config.get('method', 'grid')} | 创建: {task.get('created_at', '')[:16]}"
            ).classes("text-xs text-gray-500")

        # 进度
        progress = task.get("progress", 0)
        if status == "running":
            with ui.column().classes("w-32"):
                ui.linear_progress(value=progress / 100).props("size=8px")
                ui.label(f"{progress}%").classes("text-xs text-center")

        # 操作按钮
        if status == "pending":
            ui.button(
                icon="play_arrow", on_click=lambda t=task: _start_task(t["id"])
            ).props("flat dense")
        if status in ("pending", "running"):
            ui.button(
                icon="cancel", on_click=lambda t=task: _cancel_task(t["id"])
            ).props("flat dense color=negative")


def _render_optimization_results():
    """渲染优化结果"""
    results = _load_results()

    if not results:
        with ui.card().classes("card w-full"):
            ui.label("暂无优化结果").classes("text-gray-400 text-center py-8")
            ui.label("点击「新建优化任务」开始参数优化").classes(
                "text-xs text-gray-400 text-center"
            )
        return

    for result in results[-5:]:  # 只显示最近 5 个
        _render_result_card(result)


def _render_result_card(result: dict):
    """渲染单个优化结果卡片"""
    with ui.card().classes("card w-full mb-4"):
        config = result.get("config", {})
        best = result.get("best", {})

        # 标题行
        with ui.row().classes("w-full justify-between items-center mb-4"):
            with ui.column().classes("gap-0"):
                ui.label(f"{config.get('strategy', 'Unknown')}").classes(
                    "text-lg font-medium"
                )
                ui.label(
                    f"完成于 {result.get('finished_at', '')[:16]} | {result.get('total_trials', 0)} 次试验"
                ).classes("text-xs text-gray-500")

            with ui.row().classes("gap-2"):
                ui.button(
                    "查看详情",
                    on_click=lambda r=result: _show_result_detail(r),
                ).props("flat dense")
                ui.button(
                    "应用最优参数",
                    on_click=lambda r=result: _apply_best_params(r),
                ).props("color=primary dense")

        # 最优参数
        if best.get("params"):
            ui.label("最优参数").classes("text-sm font-medium mb-2")
            with ui.row().classes("w-full gap-4 flex-wrap"):
                for param, value in best["params"].items():
                    with ui.card().classes("p-2 bg-gray-50 dark:bg-gray-800"):
                        ui.label(param).classes("text-xs text-gray-500")
                        ui.label(str(value)).classes("font-medium")

        # 性能指标
        if best.get("metrics"):
            ui.label("性能指标").classes("text-sm font-medium mt-4 mb-2")
            metrics = best["metrics"]
            with ui.row().classes("w-full gap-4"):
                _render_metric("夏普比率", metrics.get("sharpe_ratio", 0), "{:.2f}")
                _render_metric("总收益", metrics.get("total_return", 0), "{:.1%}")
                _render_metric("最大回撤", metrics.get("max_drawdown", 0), "{:.1%}")
                _render_metric("卡尔马比率", metrics.get("calmar_ratio", 0), "{:.2f}")

        # Walk-Forward 结果
        wf = result.get("walk_forward")
        if wf and wf.get("is_robust") is not None:
            ui.label("Walk-Forward 验证").classes("text-sm font-medium mt-4 mb-2")
            with ui.row().classes("w-full gap-4 items-center"):
                is_robust = wf.get("is_robust", False)
                if is_robust:
                    ui.icon("check_circle").classes("text-green-600 text-xl")
                    ui.label("通过稳健性检验").classes("text-green-600")
                else:
                    ui.icon("warning").classes("text-yellow-600 text-xl")
                    ui.label("未通过稳健性检验").classes("text-yellow-600")

                ui.label(
                    f"夏普衰减: {wf.get('sharpe_decay', 0):.1%} | 参数稳定性: {wf.get('parameter_stability', 0):.1%}"
                ).classes("text-xs text-gray-500")


def _render_metric(label: str, value: float, fmt: str = "{:.2f}"):
    """渲染单个指标"""
    with ui.card().classes("p-2 bg-gray-50 dark:bg-gray-800 min-w-24"):
        ui.label(label).classes("text-xs text-gray-500")
        formatted = fmt.format(value) if value != 0 else "-"
        ui.label(formatted).classes("font-medium")


def _show_result_detail(result: dict):
    """显示优化结果详情"""
    with (
        ui.dialog() as dialog,
        ui.card().classes("min-w-[800px] max-h-[90vh] overflow-auto"),
    ):
        config = result.get("config", {})

        ui.label(f"优化结果详情 - {config.get('strategy', '')}").classes(
            "text-lg font-medium mb-4"
        )

        # 配置信息
        ui.label("优化配置").classes("text-sm font-medium mb-2")
        with ui.card().classes("w-full bg-gray-50 dark:bg-gray-800 p-4 mb-4"):
            ui.label(f"策略: {config.get('strategy')}").classes("text-sm")
            ui.label(f"方法: {config.get('method')}").classes("text-sm")
            ui.label(
                f"数据范围: {config.get('start_date')} ~ {config.get('end_date')}"
            ).classes("text-sm")

        # 前 10 名结果
        ui.label("Top 10 参数组合").classes("text-sm font-medium mb-2")
        top_results = result.get("top_results", [])[:10]

        if top_results:
            columns = [
                {"name": "rank", "label": "排名", "field": "rank", "sortable": True},
                {
                    "name": "objective",
                    "label": "目标值",
                    "field": "objective",
                    "sortable": True,
                },
                {
                    "name": "sharpe",
                    "label": "夏普",
                    "field": "sharpe",
                    "sortable": True,
                },
                {
                    "name": "return",
                    "label": "收益",
                    "field": "return",
                    "sortable": True,
                },
                {
                    "name": "drawdown",
                    "label": "回撤",
                    "field": "drawdown",
                    "sortable": True,
                },
            ]

            # 添加参数列
            if top_results:
                for param in top_results[0].get("params", {}).keys():
                    columns.append({"name": param, "label": param, "field": param})

            rows = []
            for i, tr in enumerate(top_results):
                row = {
                    "rank": i + 1,
                    "objective": f"{tr.get('objective_value', 0):.4f}",
                    "sharpe": f"{tr.get('metrics', {}).get('sharpe_ratio', 0):.2f}",
                    "return": f"{tr.get('metrics', {}).get('total_return', 0):.1%}",
                    "drawdown": f"{tr.get('metrics', {}).get('max_drawdown', 0):.1%}",
                }
                row.update(tr.get("params", {}))
                rows.append(row)

            ui.table(columns=columns, rows=rows).classes("w-full mb-4")

        ui.button("关闭", on_click=dialog.close).props("flat")

    dialog.open()


def _apply_best_params(result: dict):
    """应用最优参数到策略配置"""
    config = result.get("config", {})
    best = result.get("best", {})

    if not best.get("params"):
        ui.notify("没有找到最优参数", type="warning")
        return

    strategy_class = config.get("strategy", "")
    params = best["params"]

    # 创建新的策略配置
    manager = StrategyConfigManager(config_path=CONFIG_PATH / "strategies.json")
    manager.load()

    # 生成配置名称
    name = f"{strategy_class.lower()}_optimized_{datetime.now().strftime('%Y%m%d')}"

    from services.web.strategy_config import StrategyRunConfig

    new_config = StrategyRunConfig(
        name=name,
        strategy_class=strategy_class,
        enabled=False,  # 默认禁用
        symbols=config.get("symbols", ["BTC/USDT"]),
        params=params,
    )

    manager.add(new_config)

    ui.notify(f"已创建策略配置 '{name}'，请前往策略页面启用", type="positive")
