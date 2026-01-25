"""
Core 模块 - 基础组件

包含:
- config: 配置加载与环境区分
- events: 事件模型 (BarEvent/SignalEvent/OrderEvent/FillEvent)
- clock: 交易时钟 (bar close 触发)
- instruments: Symbol 规范化
- timeframes: 时间框架定义
- typing: 公共类型定义
"""

from .events import (
    BarEvent,
    Event,
    EventType,
    FillEvent,
    OrderEvent,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalDirection,
    SignalEvent,
)
from .instruments import AssetType, CommonSymbols, Exchange, Symbol
from .timeframes import TRADING_TIMEFRAMES, Timeframe

__all__ = [
    # Events
    "Event",
    "EventType",
    "BarEvent",
    "SignalEvent",
    "OrderEvent",
    "FillEvent",
    # Enums
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "SignalDirection",
    # Instruments
    "Exchange",
    "AssetType",
    "Symbol",
    "CommonSymbols",
    # Timeframes
    "Timeframe",
    "TRADING_TIMEFRAMES",
]
