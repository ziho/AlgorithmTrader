"""
Backtest 模块 - 回测引擎

包含:
- engine: 回测主引擎 (bar级别撮合)
- metrics: 绩效指标计算
- reports: 回测报告生成
"""

from src.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    EquityPoint,
    Position,
    Trade,
)
from src.backtest.metrics import MetricsCalculator, PerformanceMetrics, TradeStats

__all__ = [
    # Engine
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "EquityPoint",
    "Position",
    "Trade",
    # Metrics
    "MetricsCalculator",
    "PerformanceMetrics",
    "TradeStats",
]
