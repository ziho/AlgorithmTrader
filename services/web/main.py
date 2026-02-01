"""
Web 管理服务主入口

基于 NiceGUI 的 Web 管理界面

特点:
- 纯 Python 实现
- 内置 WebSocket 实时更新
- 响应式设计，支持移动端
- 暗色/亮色模式跟随系统

运行方式:
    python -m services.web.main
"""

import asyncio
from contextlib import asynccontextmanager

from nicegui import app, ui

from services.web.pages import backtests, dashboard, optimization, strategies
from services.web.state import AppState
from src.ops.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan():
    """应用生命周期管理"""
    logger.info("web_service_starting")
    
    # 初始化应用状态
    app.state = AppState()
    await app.state.initialize()
    
    yield
    
    # 清理资源
    await app.state.cleanup()
    logger.info("web_service_stopped")


def create_header():
    """创建页面头部"""
    with ui.header().classes("items-center justify-between px-4 py-3"):
        with ui.row().classes("items-center gap-4"):
            ui.label("AlgorithmTrader").classes("text-2xl font-bold")
            
            # 导航菜单
            with ui.row().classes("gap-2"):
                ui.link("Dashboard", "/").classes("nav-link text-base")
                ui.link("策略", "/strategies").classes("nav-link text-base")
                ui.link("回测", "/backtests").classes("nav-link text-base")
                ui.link("优化", "/optimization").classes("nav-link text-base")
        
        # 暗色模式切换（三态：跟随系统、亮色、暗色）
        dark = ui.dark_mode()
        
        def cycle_theme():
            """循环切换主题"""
            if dark.value is None:
                dark.value = False  # 跟随系统 -> 亮色
            elif dark.value is False:
                dark.value = True   # 亮色 -> 暗色
            else:
                dark.value = None   # 暗色 -> 跟随系统
        
        def get_theme_icon():
            if dark.value is None:
                return "brightness_auto"  # 跟随系统
            elif dark.value:
                return "dark_mode"        # 暗色
            else:
                return "light_mode"       # 亮色
        
        def get_theme_tooltip():
            if dark.value is None:
                return "跟随系统 (点击切换)"
            elif dark.value:
                return "暗色模式 (点击切换)"
            else:
                return "亮色模式 (点击切换)"
        
        theme_btn = ui.button(icon=get_theme_icon(), on_click=cycle_theme).props("flat round")
        theme_btn.tooltip(get_theme_tooltip())


def create_layout(content_func):
    """创建页面布局的装饰器"""
    def wrapper():
        # 应用全局样式
        ui.add_head_html("""
        <style>
            :root {
                --primary-color: #1a1a1a;
                --secondary-color: #4a4a4a;
                --accent-color: #666666;
            }
            
            /* 全局字体大小调整 */
            body {
                font-size: 16px;
            }
            
            .q-table tbody td {
                font-size: 15px;
            }
            
            .nav-link {
                color: inherit;
                text-decoration: none;
                padding: 10px 18px;
                border-radius: 6px;
                transition: background-color 0.2s;
                font-size: 16px;
            }
            
            .nav-link:hover {
                background-color: rgba(0, 0, 0, 0.1);
            }
            
            .dark .nav-link:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            
            .card {
                background: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            }
            
            .dark .card {
                background: #2d2d2d;
            }
            
            .status-badge {
                padding: 6px 14px;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 500;
            }
            
            .status-healthy {
                background-color: #dcfce7;
                color: #166534;
            }
            
            .status-warning {
                background-color: #fef3c7;
                color: #92400e;
            }
            
            .status-error {
                background-color: #fee2e2;
                color: #991b1b;
            }
            
            .dark .status-healthy {
                background-color: #166534;
                color: #dcfce7;
            }
            
            .dark .status-warning {
                background-color: #92400e;
                color: #fef3c7;
            }
            
            .dark .status-error {
                background-color: #991b1b;
                color: #fee2e2;
            }
            
            /* 增大文字尺寸 */
            .text-sm { font-size: 0.9375rem; }
            .text-xs { font-size: 0.8125rem; }
            .text-lg { font-size: 1.25rem; }
            .text-xl { font-size: 1.5rem; }
            .text-2xl { font-size: 1.75rem; }
        </style>
        """)
        
        create_header()
        
        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            content_func()
    
    return wrapper


# 注册路由
@ui.page("/")
@create_layout
def index_page():
    """Dashboard 首页"""
    dashboard.render()


@ui.page("/strategies")
@create_layout
def strategies_page():
    """策略管理页"""
    strategies.render()


@ui.page("/backtests")
@create_layout
def backtests_page():
    """回测结果页"""
    backtests.render()


@ui.page("/optimization")
@create_layout
def optimization_page():
    """参数优化页"""
    optimization.render()


def main():
    """Web 服务主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="AlgorithmTrader Web Service")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind (default: 8080)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    
    args = parser.parse_args()
    
    logger.info(
        "web_service_config",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    
    ui.run(
        host=args.host,
        port=args.port,
        title="AlgorithmTrader",
        favicon="🤖",
        dark=None,  # 跟随系统
        reload=args.reload,
        show=False,  # 不自动打开浏览器
    )


if __name__ == "__main__":
    main()
