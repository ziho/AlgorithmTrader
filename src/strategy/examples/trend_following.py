"""
趋势跟踪策略

实现了两种经典的趋势跟踪方法:
1. 双均线交叉 (Dual Moving Average Crossover)
2. 通道突破 (Donchian Channel Breakout)

使用方式:
    from src.strategy.examples.trend_following import DualMAStrategy

    strategy = DualMAStrategy(
        config=StrategyConfig(
            name="dual_ma_btc",
            symbols=["BTC/USDT"],
            params={"fast_period": 10, "slow_period": 30, "position_size": 0.1}
        )
    )
"""

from decimal import Decimal
from typing import Any

import numpy as np

from src.core.typing import BarFrame, StrategyOutput
from src.strategy.base import StrategyBase, StrategyConfig
from src.strategy.registry import register_strategy


@register_strategy("DualMAStrategy")
class DualMAStrategy(StrategyBase):
    """
    双均线交叉策略

    规则:
    - 快线上穿慢线 → 做多
    - 快线下穿慢线 → 平仓/做空
    - 可配置是否允许做空

    参数:
    - fast_period: 快线周期 (默认 10)
    - slow_period: 慢线周期 (默认 30)
    - position_size: 仓位大小 (默认 1.0)
    - allow_short: 是否允许做空 (默认 False)
    - use_ema: 使用 EMA 而非 SMA (默认 False)
    """

    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)

        # 提取参数
        self.fast_period = self.get_param("fast_period", 10)
        self.slow_period = self.get_param("slow_period", 30)
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))
        self.allow_short = self.get_param("allow_short", False)
        self.use_ema = self.get_param("use_ema", False)

    def _calculate_ma(self, prices: np.ndarray, period: int) -> float:
        """计算移动平均"""
        if len(prices) < period:
            return np.nan

        if self.use_ema:
            # EMA
            weights = np.exp(np.linspace(-1, 0, period))
            weights /= weights.sum()
            return float(np.dot(prices[-period:], weights))
        else:
            # SMA
            return float(np.mean(prices[-period:]))

    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理 bar 数据"""
        # 检查是否有足够的历史数据
        if bar_frame.history is None or len(bar_frame.history) < self.slow_period:
            return None

        symbol = bar_frame.symbol

        # 获取收盘价序列
        close_prices = bar_frame.history["close"].values.astype(float)

        # 计算均线
        fast_ma = self._calculate_ma(close_prices, self.fast_period)
        slow_ma = self._calculate_ma(close_prices, self.slow_period)

        if np.isnan(fast_ma) or np.isnan(slow_ma):
            return None

        # 保存状态用于调试
        self.set_state("fast_ma", fast_ma)
        self.set_state("slow_ma", slow_ma)

        # 获取当前持仓
        current_position = self.state.get_position(symbol)

        # 生成信号
        if fast_ma > slow_ma:
            # 金叉 → 做多
            if current_position <= 0:
                return self.target_long(
                    symbol=symbol,
                    quantity=self.position_size,
                    reason=f"golden_cross: fast_ma={fast_ma:.2f} > slow_ma={slow_ma:.2f}",
                )
        elif fast_ma < slow_ma:
            # 死叉
            if current_position > 0:
                # 平多仓
                return self.target_flat(
                    symbol=symbol,
                    reason=f"death_cross: fast_ma={fast_ma:.2f} < slow_ma={slow_ma:.2f}",
                )
            elif self.allow_short and current_position == 0:
                # 开空仓
                return self.target_short(
                    symbol=symbol,
                    quantity=self.position_size,
                    reason=f"death_cross_short: fast_ma={fast_ma:.2f} < slow_ma={slow_ma:.2f}",
                )

        return None


@register_strategy("DonchianBreakoutStrategy")
class DonchianBreakoutStrategy(StrategyBase):
    """
    唐奇安通道突破策略 (海龟交易法则)

    规则:
    - 价格突破 N 日最高价 → 做多
    - 价格跌破 M 日最低价 → 平仓/做空
    - 可设置止损

    参数:
    - entry_period: 入场通道周期 (默认 20)
    - exit_period: 出场通道周期 (默认 10)
    - position_size: 仓位大小 (默认 1.0)
    - allow_short: 是否允许做空 (默认 False)
    - use_atr_stop: 是否使用 ATR 止损 (默认 False)
    - atr_multiplier: ATR 止损倍数 (默认 2.0)
    """

    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)

        # 提取参数
        self.entry_period = self.get_param("entry_period", 20)
        self.exit_period = self.get_param("exit_period", 10)
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))
        self.allow_short = self.get_param("allow_short", False)
        self.use_atr_stop = self.get_param("use_atr_stop", False)
        self.atr_multiplier = self.get_param("atr_multiplier", 2.0)

    def _calculate_donchian(
        self, high_prices: np.ndarray, low_prices: np.ndarray, period: int
    ) -> tuple[float, float]:
        """计算唐奇安通道"""
        if len(high_prices) < period:
            return np.nan, np.nan

        upper = float(np.max(high_prices[-period:]))
        lower = float(np.min(low_prices[-period:]))
        return upper, lower

    def _calculate_atr(
        self,
        high_prices: np.ndarray,
        low_prices: np.ndarray,
        close_prices: np.ndarray,
        period: int = 14,
    ) -> float:
        """计算 ATR (Average True Range)"""
        if len(high_prices) < period + 1:
            return np.nan

        tr_list = []
        for i in range(1, len(high_prices)):
            high = high_prices[i]
            low = low_prices[i]
            prev_close = close_prices[i - 1]

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

        if len(tr_list) < period:
            return np.nan

        return float(np.mean(tr_list[-period:]))

    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理 bar 数据"""
        # 检查是否有足够的历史数据
        min_period = max(self.entry_period, self.exit_period)
        if bar_frame.history is None or len(bar_frame.history) < min_period:
            return None

        symbol = bar_frame.symbol
        current_price = float(bar_frame.close)

        # 获取价格序列
        high_prices = bar_frame.history["high"].values.astype(float)
        low_prices = bar_frame.history["low"].values.astype(float)
        close_prices = bar_frame.history["close"].values.astype(float)

        # 计算通道 (不包含当前 bar)
        entry_upper, entry_lower = self._calculate_donchian(
            high_prices[:-1], low_prices[:-1], self.entry_period
        )
        exit_upper, exit_lower = self._calculate_donchian(
            high_prices[:-1], low_prices[:-1], self.exit_period
        )

        if np.isnan(entry_upper) or np.isnan(exit_lower):
            return None

        # 保存状态
        self.set_state("entry_upper", entry_upper)
        self.set_state("entry_lower", entry_lower)
        self.set_state("exit_upper", exit_upper)
        self.set_state("exit_lower", exit_lower)

        # 获取当前持仓
        current_position = self.state.get_position(symbol)

        # ATR 止损检查
        if self.use_atr_stop and current_position != 0:
            atr = self._calculate_atr(high_prices, low_prices, close_prices)
            entry_price = self.get_state("entry_price", current_price)
            stop_distance = atr * self.atr_multiplier

            if current_position > 0 and current_price < entry_price - stop_distance:
                return self.target_flat(
                    symbol=symbol,
                    reason=f"atr_stop_long: price={current_price:.2f} < stop={entry_price - stop_distance:.2f}",
                )
            elif current_position < 0 and current_price > entry_price + stop_distance:
                return self.target_flat(
                    symbol=symbol,
                    reason=f"atr_stop_short: price={current_price:.2f} > stop={entry_price + stop_distance:.2f}",
                )

        # 生成信号
        if current_price > entry_upper:
            # 向上突破 → 做多
            if current_position <= 0:
                self.set_state("entry_price", current_price)
                return self.target_long(
                    symbol=symbol,
                    quantity=self.position_size,
                    reason=f"breakout_long: price={current_price:.2f} > upper={entry_upper:.2f}",
                )
        # 向下突破 → 做空
        elif current_price < entry_lower and self.allow_short and current_position >= 0:
            self.set_state("entry_price", current_price)
            return self.target_short(
                symbol=symbol,
                quantity=self.position_size,
                reason=f"breakout_short: price={current_price:.2f} < lower={entry_lower:.2f}",
            )

        # 出场信号
        if current_position > 0 and current_price < exit_lower:
            return self.target_flat(
                symbol=symbol,
                reason=f"exit_long: price={current_price:.2f} < exit_lower={exit_lower:.2f}",
            )
        elif current_position < 0 and current_price > exit_upper:
            return self.target_flat(
                symbol=symbol,
                reason=f"exit_short: price={current_price:.2f} > exit_upper={exit_upper:.2f}",
            )

        return None


def create_trend_strategy(
    strategy_type: str = "dual_ma",
    name: str = "trend_strategy",
    symbols: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> StrategyBase:
    """
    工厂函数：创建趋势跟踪策略

    Args:
        strategy_type: 策略类型 ("dual_ma" 或 "donchian")
        name: 策略名称
        symbols: 交易品种列表
        params: 策略参数

    Returns:
        策略实例
    """
    config = StrategyConfig(
        name=name,
        symbols=symbols or ["BTC/USDT"],
        params=params or {},
    )

    if strategy_type == "dual_ma":
        return DualMAStrategy(config)
    elif strategy_type == "donchian":
        return DonchianBreakoutStrategy(config)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")


# 导出
__all__ = [
    "DualMAStrategy",
    "DonchianBreakoutStrategy",
    "create_trend_strategy",
]
