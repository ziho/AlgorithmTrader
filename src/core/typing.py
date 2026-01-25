"""
公共类型定义

包含系统中使用的类型别名和通用类型
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class PositionSide(str, Enum):
    """持仓方向"""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"  # 空仓


@dataclass
class BarFrame:
    """
    Bar 数据帧

    策略输入的核心数据结构，包含:
    - 当前 bar 数据
    - 历史 bar 窗口（用于计算指标）
    - 可选的特征矩阵

    设计原则:
    - 不可变数据（策略只读）
    - 支持多时间框架
    - 便于向量化计算
    """

    symbol: str  # 交易对，如 "OKX:BTC/USDT"
    timeframe: str  # 时间框架，如 "15m", "1h"

    # 当前 bar
    timestamp: datetime  # bar 时间
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    # 历史窗口 (DataFrame: columns=[open, high, low, close, volume], index=datetime)
    history: pd.DataFrame = field(default_factory=pd.DataFrame)

    # 可选特征矩阵 (DataFrame: columns=特征名, index=datetime)
    features: pd.DataFrame | None = None

    # 额外数据 (如资金费率等)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def close_price(self) -> float:
        """获取当前收盘价（浮点数）"""
        return float(self.close)

    @property
    def ohlcv(self) -> tuple[float, float, float, float, float]:
        """获取 OHLCV 元组"""
        return (
            float(self.open),
            float(self.high),
            float(self.low),
            float(self.close),
            float(self.volume),
        )

    @property
    def history_close(self) -> np.ndarray:
        """获取历史收盘价数组"""
        if self.history.empty:
            return np.array([float(self.close)])
        return self.history["close"].values

    @property
    def history_high(self) -> np.ndarray:
        """获取历史最高价数组"""
        if self.history.empty:
            return np.array([float(self.high)])
        return self.history["high"].values

    @property
    def history_low(self) -> np.ndarray:
        """获取历史最低价数组"""
        if self.history.empty:
            return np.array([float(self.low)])
        return self.history["low"].values

    def get_feature(self, name: str) -> np.ndarray | None:
        """获取指定特征"""
        if self.features is None or name not in self.features.columns:
            return None
        return self.features[name].values


@dataclass
class TargetPosition:
    """
    目标持仓

    策略输出模式1：声明式
    指定目标持仓量，由组合层计算差分并生成订单
    推荐用于组合策略和多品种策略
    """

    symbol: str
    side: PositionSide = PositionSide.FLAT
    quantity: Decimal = Decimal("0")  # 目标持仓量（绝对值）
    weight: Decimal | None = None  # 可选：目标权重 (0-1)

    # 元信息
    strategy_name: str = ""
    reason: str = ""  # 调仓原因
    confidence: float = 1.0  # 置信度 [0, 1]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_flat(self) -> bool:
        """是否为空仓"""
        return self.side == PositionSide.FLAT or self.quantity == Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "weight": str(self.weight) if self.weight else None,
            "strategy_name": self.strategy_name,
            "reason": self.reason,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class OrderIntent:
    """
    下单意图

    策略输出模式2：命令式
    直接指定买卖意图，更快上手
    适合单品种策略
    """

    symbol: str
    side: PositionSide  # LONG=买入, SHORT=卖出/做空, FLAT=平仓
    quantity: Decimal  # 数量

    # 价格相关
    order_type: str = "market"  # "market" | "limit"
    limit_price: Decimal | None = None

    # 元信息
    strategy_name: str = ""
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_market_order(self) -> bool:
        """是否为市价单"""
        return self.order_type == "market"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "order_type": self.order_type,
            "limit_price": str(self.limit_price) if self.limit_price else None,
            "strategy_name": self.strategy_name,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


# 策略输出类型
StrategyOutput = TargetPosition | OrderIntent | list[TargetPosition] | list[OrderIntent] | None


# 导出
__all__ = [
    "PositionSide",
    "BarFrame",
    "TargetPosition",
    "OrderIntent",
    "StrategyOutput",
]
