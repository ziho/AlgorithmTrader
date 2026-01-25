"""
Portfolio 模块 - 组合管理

包含:
- position: 头寸对象
- allocator: 信号到目标持仓转换
- accounting: 费用/滑点/PNL/权益曲线
"""

from src.portfolio.accounting import (
    AccountingEngine,
    DailySummary,
    EquityPoint,
    PnLCalculator,
    TradeRecord,
)
from src.portfolio.allocator import (
    AllocationConfig,
    AllocationMethod,
    OrderIntent,
    PositionAllocator,
    Signal,
    TargetPosition,
    WeightCalculator,
)
from src.portfolio.position import (
    OrderSide,
    Position,
    PositionSide,
    PositionSnapshot,
    PositionTracker,
)

__all__ = [
    # position
    "Position",
    "PositionSide",
    "OrderSide",
    "PositionSnapshot",
    "PositionTracker",
    # allocator
    "AllocationMethod",
    "AllocationConfig",
    "TargetPosition",
    "OrderIntent",
    "Signal",
    "PositionAllocator",
    "WeightCalculator",
    # accounting
    "TradeRecord",
    "EquityPoint",
    "DailySummary",
    "AccountingEngine",
    "PnLCalculator",
]
