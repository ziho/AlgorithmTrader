"""
Web 页面模块
"""

from . import (
    backtests,
    dashboard,
    data,
    notifications,
    optimization,
    settings,
    strategies,
)

__all__ = [
    "dashboard",
    "data",
    "strategies",
    "backtests",
    "optimization",
    "notifications",
    "settings",
]
