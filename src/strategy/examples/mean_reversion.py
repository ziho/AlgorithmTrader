"""
均值回归策略

实现了两种经典的均值回归方法:
1. 布林带策略 (Bollinger Bands)
2. RSI 超买超卖策略 (RSI Mean Reversion)

使用方式:
    from src.strategy.examples.mean_reversion import BollingerBandsStrategy

    strategy = BollingerBandsStrategy(
        config=StrategyConfig(
            name="bb_btc",
            symbols=["BTC/USDT"],
            params={"period": 20, "std_dev": 2.0, "position_size": 0.1}
        )
    )
"""

from decimal import Decimal
from typing import Any

import numpy as np

from src.core.typing import BarFrame, StrategyOutput
from src.strategy.base import StrategyBase, StrategyConfig


class BollingerBandsStrategy(StrategyBase):
    """
    布林带均值回归策略

    规则:
    - 价格触及下轨 → 做多（预期回归中轨）
    - 价格触及上轨 → 平多/做空（预期回归中轨）
    - 价格回归中轨 → 平仓

    参数:
    - period: 布林带周期 (默认 20)
    - std_dev: 标准差倍数 (默认 2.0)
    - position_size: 仓位大小 (默认 1.0)
    - allow_short: 是否允许做空 (默认 False)
    - exit_at_middle: 是否在中轨平仓 (默认 True)
    """

    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)

        # 提取参数
        self.period = self.get_param("period", 20)
        self.std_dev = self.get_param("std_dev", 2.0)
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))
        self.allow_short = self.get_param("allow_short", False)
        self.exit_at_middle = self.get_param("exit_at_middle", True)

    def _calculate_bollinger_bands(
        self, prices: np.ndarray
    ) -> tuple[float, float, float]:
        """
        计算布林带

        Returns:
            (中轨, 上轨, 下轨)
        """
        if len(prices) < self.period:
            return np.nan, np.nan, np.nan

        window = prices[-self.period :]
        middle = float(np.mean(window))
        std = float(np.std(window, ddof=1))

        upper = middle + self.std_dev * std
        lower = middle - self.std_dev * std

        return middle, upper, lower

    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理 bar 数据"""
        if bar_frame.history is None or len(bar_frame.history) < self.period:
            return None

        symbol = bar_frame.symbol
        current_price = float(bar_frame.close)

        # 获取收盘价序列
        close_prices = bar_frame.history["close"].values.astype(float)

        # 计算布林带
        middle, upper, lower = self._calculate_bollinger_bands(close_prices)

        if np.isnan(middle):
            return None

        # 保存状态
        self.set_state("bb_middle", middle)
        self.set_state("bb_upper", upper)
        self.set_state("bb_lower", lower)

        # 获取当前持仓和入场方向
        current_position = self.state.get_position(symbol)
        entry_side = self.get_state("entry_side")

        # 中轨平仓逻辑
        if self.exit_at_middle and current_position != 0:
            if entry_side == "long" and current_price >= middle:
                self.set_state("entry_side", None)
                return self.target_flat(
                    symbol=symbol,
                    reason=f"exit_at_middle: price={current_price:.2f} >= middle={middle:.2f}",
                )
            elif entry_side == "short" and current_price <= middle:
                self.set_state("entry_side", None)
                return self.target_flat(
                    symbol=symbol,
                    reason=f"exit_at_middle: price={current_price:.2f} <= middle={middle:.2f}",
                )

        # 入场信号
        if current_price <= lower:
            # 触及下轨 → 做多
            if current_position <= 0:
                self.set_state("entry_side", "long")
                return self.target_long(
                    symbol=symbol,
                    quantity=self.position_size,
                    reason=f"touch_lower: price={current_price:.2f} <= lower={lower:.2f}",
                )
        elif current_price >= upper:
            # 触及上轨
            if current_position > 0:
                # 平多仓
                self.set_state("entry_side", None)
                return self.target_flat(
                    symbol=symbol,
                    reason=f"touch_upper: price={current_price:.2f} >= upper={upper:.2f}",
                )
            elif self.allow_short and current_position == 0:
                # 开空仓
                self.set_state("entry_side", "short")
                return self.target_short(
                    symbol=symbol,
                    quantity=self.position_size,
                    reason=f"touch_upper_short: price={current_price:.2f} >= upper={upper:.2f}",
                )

        return None


class RSIMeanReversionStrategy(StrategyBase):
    """
    RSI 均值回归策略

    规则:
    - RSI < 超卖阈值 → 做多
    - RSI > 超买阈值 → 平多/做空
    - RSI 回归中性区域 → 平仓

    参数:
    - period: RSI 周期 (默认 14)
    - oversold: 超卖阈值 (默认 30)
    - overbought: 超买阈值 (默认 70)
    - exit_level: 平仓阈值 (默认 50)
    - position_size: 仓位大小 (默认 1.0)
    - allow_short: 是否允许做空 (默认 False)
    """

    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)

        # 提取参数
        self.period = self.get_param("period", 14)
        self.oversold = self.get_param("oversold", 30)
        self.overbought = self.get_param("overbought", 70)
        self.exit_level = self.get_param("exit_level", 50)
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))
        self.allow_short = self.get_param("allow_short", False)

    def _calculate_rsi(self, prices: np.ndarray) -> float:
        """
        计算 RSI (Relative Strength Index)

        Returns:
            RSI 值 (0-100)
        """
        if len(prices) < self.period + 1:
            return np.nan

        # 计算价格变动
        deltas = np.diff(prices)

        # 分离上涨和下跌
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        # 计算平均涨跌
        avg_gain = np.mean(gains[-self.period :])
        avg_loss = np.mean(losses[-self.period :])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return float(rsi)

    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理 bar 数据"""
        if bar_frame.history is None or len(bar_frame.history) < self.period + 1:
            return None

        symbol = bar_frame.symbol

        # 获取收盘价序列
        close_prices = bar_frame.history["close"].values.astype(float)

        # 计算 RSI
        rsi = self._calculate_rsi(close_prices)

        if np.isnan(rsi):
            return None

        # 保存状态
        self.set_state("rsi", rsi)

        # 获取当前持仓和入场方向
        current_position = self.state.get_position(symbol)
        entry_side = self.get_state("entry_side")

        # 平仓逻辑：RSI 回归中性
        if current_position != 0:
            if entry_side == "long" and rsi >= self.exit_level:
                self.set_state("entry_side", None)
                return self.target_flat(
                    symbol=symbol,
                    reason=f"rsi_neutral: rsi={rsi:.1f} >= exit_level={self.exit_level}",
                )
            elif entry_side == "short" and rsi <= self.exit_level:
                self.set_state("entry_side", None)
                return self.target_flat(
                    symbol=symbol,
                    reason=f"rsi_neutral: rsi={rsi:.1f} <= exit_level={self.exit_level}",
                )

        # 入场信号
        if rsi < self.oversold:
            # 超卖 → 做多
            if current_position <= 0:
                self.set_state("entry_side", "long")
                return self.target_long(
                    symbol=symbol,
                    quantity=self.position_size,
                    reason=f"rsi_oversold: rsi={rsi:.1f} < oversold={self.oversold}",
                )
        elif rsi > self.overbought:
            # 超买
            if current_position > 0:
                # 平多仓
                self.set_state("entry_side", None)
                return self.target_flat(
                    symbol=symbol,
                    reason=f"rsi_overbought: rsi={rsi:.1f} > overbought={self.overbought}",
                )
            elif self.allow_short and current_position == 0:
                # 开空仓
                self.set_state("entry_side", "short")
                return self.target_short(
                    symbol=symbol,
                    quantity=self.position_size,
                    reason=f"rsi_overbought_short: rsi={rsi:.1f} > overbought={self.overbought}",
                )

        return None


class ZScoreStrategy(StrategyBase):
    """
    Z-Score 均值回归策略

    适用于配对交易或统计套利

    规则:
    - Z-Score < -阈值 → 做多（价格低于均值）
    - Z-Score > 阈值 → 做空（价格高于均值）
    - Z-Score 回归 0 附近 → 平仓

    参数:
    - lookback: 回看周期 (默认 20)
    - entry_threshold: 入场阈值 (默认 2.0)
    - exit_threshold: 平仓阈值 (默认 0.5)
    - position_size: 仓位大小 (默认 1.0)
    """

    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)

        # 提取参数
        self.lookback = self.get_param("lookback", 20)
        self.entry_threshold = self.get_param("entry_threshold", 2.0)
        self.exit_threshold = self.get_param("exit_threshold", 0.5)
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))

    def _calculate_zscore(self, prices: np.ndarray) -> float:
        """计算 Z-Score"""
        if len(prices) < self.lookback:
            return np.nan

        window = prices[-self.lookback :]
        mean = np.mean(window)
        std = np.std(window, ddof=1)

        if std == 0:
            return 0.0

        current = prices[-1]
        zscore = (current - mean) / std

        return float(zscore)

    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理 bar 数据"""
        if bar_frame.history is None or len(bar_frame.history) < self.lookback:
            return None

        symbol = bar_frame.symbol

        # 获取收盘价序列
        close_prices = bar_frame.history["close"].values.astype(float)

        # 计算 Z-Score
        zscore = self._calculate_zscore(close_prices)

        if np.isnan(zscore):
            return None

        # 保存状态
        self.set_state("zscore", zscore)

        # 获取当前持仓
        current_position = self.state.get_position(symbol)

        # 平仓逻辑
        if current_position > 0 and zscore >= -self.exit_threshold:
            return self.target_flat(
                symbol=symbol,
                reason=f"zscore_exit_long: zscore={zscore:.2f} >= -{self.exit_threshold}",
            )
        elif current_position < 0 and zscore <= self.exit_threshold:
            return self.target_flat(
                symbol=symbol,
                reason=f"zscore_exit_short: zscore={zscore:.2f} <= {self.exit_threshold}",
            )

        # 入场信号
        # 入场信号: 价格显著低于均值 → 做多
        if zscore < -self.entry_threshold and current_position <= 0:
            return self.target_long(
                symbol=symbol,
                quantity=self.position_size,
                reason=f"zscore_long: zscore={zscore:.2f} < -{self.entry_threshold}",
            )
        # 入场信号: 价格显著高于均值 → 做空
        elif zscore > self.entry_threshold and current_position >= 0:
            return self.target_short(
                symbol=symbol,
                quantity=self.position_size,
                reason=f"zscore_short: zscore={zscore:.2f} > {self.entry_threshold}",
            )

        return None


def create_mean_reversion_strategy(
    strategy_type: str = "bollinger",
    name: str = "mean_reversion_strategy",
    symbols: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> StrategyBase:
    """
    工厂函数：创建均值回归策略

    Args:
        strategy_type: 策略类型 ("bollinger", "rsi", "zscore")
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

    if strategy_type == "bollinger":
        return BollingerBandsStrategy(config)
    elif strategy_type == "rsi":
        return RSIMeanReversionStrategy(config)
    elif strategy_type == "zscore":
        return ZScoreStrategy(config)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")


# 导出
__all__ = [
    "BollingerBandsStrategy",
    "RSIMeanReversionStrategy",
    "ZScoreStrategy",
    "create_mean_reversion_strategy",
]
