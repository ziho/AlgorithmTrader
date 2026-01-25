"""
策略基类

接口设计:
- on_bar(bar_frame) -> target_position | order_intent
- on_fill(fill_event) -> None

研究/回测/实盘共用同一接口
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.events import FillEvent
from src.core.typing import (
    BarFrame,
    OrderIntent,
    PositionSide,
    StrategyOutput,
    TargetPosition,
)


@dataclass
class StrategyConfig:
    """
    策略配置

    可序列化的策略参数，便于回测参数扫描
    """

    name: str = "unnamed"
    symbols: list[str] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=lambda: ["15m"])
    params: dict[str, Any] = field(default_factory=dict)

    # 风控相关（可选覆盖全局设置）
    max_position_size: Decimal | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "params": self.params,
            "max_position_size": str(self.max_position_size)
            if self.max_position_size
            else None,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }


@dataclass
class StrategyState:
    """
    策略状态

    策略运行时的可变状态
    """

    # 当前持仓
    positions: dict[str, Decimal] = field(default_factory=dict)  # symbol -> quantity

    # 策略内部状态（自定义）
    custom: dict[str, Any] = field(default_factory=dict)

    # 统计
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: Decimal = Decimal("0")

    # 时间戳
    last_bar_time: datetime | None = None
    last_trade_time: datetime | None = None

    def get_position(self, symbol: str) -> Decimal:
        """获取指定品种持仓"""
        return self.positions.get(symbol, Decimal("0"))

    def update_position(self, symbol: str, quantity: Decimal) -> None:
        """更新持仓"""
        if quantity == Decimal("0"):
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = quantity


class StrategyBase(ABC):
    """
    策略基类

    所有策略必须继承此类并实现 on_bar 方法

    设计原则:
    - 纯函数化核心逻辑（输入 bar → 输出目标持仓/下单意图）
    - 研究/回测/实盘可复用
    - 状态与逻辑分离

    使用方式:
    1. target_position 模式（推荐）:
       - 输出目标持仓量，由组合层计算差分并生成订单
       - 适合组合策略、多品种策略

    2. order_intent 模式:
       - 直接输出买卖意图
       - 适合单品种策略，更快上手
    """

    def __init__(self, config: StrategyConfig | None = None):
        """
        初始化策略

        Args:
            config: 策略配置
        """
        self.config = config or StrategyConfig()
        self.state = StrategyState()
        self._initialized = False

    @property
    def name(self) -> str:
        """策略名称"""
        return self.config.name

    @property
    def symbols(self) -> list[str]:
        """交易品种列表"""
        return self.config.symbols

    @property
    def timeframes(self) -> list[str]:
        """时间框架列表"""
        return self.config.timeframes

    def initialize(self) -> None:
        """
        策略初始化

        在第一次 on_bar 调用前执行
        子类可覆盖以执行初始化逻辑
        """
        self._initialized = True

    @abstractmethod
    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """
        处理新的 bar 数据

        这是策略的核心方法，必须实现

        Args:
            bar_frame: 包含当前 bar 和历史数据的帧

        Returns:
            TargetPosition: 目标持仓（声明式）
            OrderIntent: 下单意图（命令式）
            list[TargetPosition | OrderIntent]: 多个目标/意图
            None: 不做任何操作
        """
        pass

    def on_fill(self, fill: FillEvent) -> None:
        """
        处理成交事件

        可选实现，用于更新策略内部状态

        Args:
            fill: 成交事件
        """
        # 更新交易统计
        self.state.total_trades += 1
        self.state.last_trade_time = fill.timestamp

    def on_stop(self) -> None:  # noqa: B027
        """
        策略停止时调用

        可选实现，用于清理资源
        """

    def get_param(self, key: str, default: Any = None) -> Any:
        """获取策略参数"""
        return self.config.params.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        """设置自定义状态"""
        self.state.custom[key] = value

    def get_state(self, key: str, default: Any = None) -> Any:
        """获取自定义状态"""
        return self.state.custom.get(key, default)

    # ==================== 辅助方法 ====================

    def target_long(
        self,
        symbol: str,
        quantity: Decimal,
        reason: str = "",
        confidence: float = 1.0,
    ) -> TargetPosition:
        """创建多头目标持仓"""
        return TargetPosition(
            symbol=symbol,
            side=PositionSide.LONG,
            quantity=quantity,
            strategy_name=self.name,
            reason=reason,
            confidence=confidence,
        )

    def target_short(
        self,
        symbol: str,
        quantity: Decimal,
        reason: str = "",
        confidence: float = 1.0,
    ) -> TargetPosition:
        """创建空头目标持仓"""
        return TargetPosition(
            symbol=symbol,
            side=PositionSide.SHORT,
            quantity=quantity,
            strategy_name=self.name,
            reason=reason,
            confidence=confidence,
        )

    def target_flat(self, symbol: str, reason: str = "") -> TargetPosition:
        """创建平仓目标"""
        return TargetPosition(
            symbol=symbol,
            side=PositionSide.FLAT,
            quantity=Decimal("0"),
            strategy_name=self.name,
            reason=reason,
        )

    def intent_buy(
        self,
        symbol: str,
        quantity: Decimal,
        reason: str = "",
        limit_price: Decimal | None = None,
    ) -> OrderIntent:
        """创建买入意图"""
        return OrderIntent(
            symbol=symbol,
            side=PositionSide.LONG,
            quantity=quantity,
            order_type="limit" if limit_price else "market",
            limit_price=limit_price,
            strategy_name=self.name,
            reason=reason,
        )

    def intent_sell(
        self,
        symbol: str,
        quantity: Decimal,
        reason: str = "",
        limit_price: Decimal | None = None,
    ) -> OrderIntent:
        """创建卖出意图"""
        return OrderIntent(
            symbol=symbol,
            side=PositionSide.SHORT,
            quantity=quantity,
            order_type="limit" if limit_price else "market",
            limit_price=limit_price,
            strategy_name=self.name,
            reason=reason,
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, symbols={self.symbols})"


# 导出
__all__ = [
    "StrategyConfig",
    "StrategyState",
    "StrategyBase",
]
