"""
示例策略

提供了多种经典量化交易策略的实现:

趋势跟踪策略:
- DualMAStrategy: 双均线交叉策略
- DonchianBreakoutStrategy: 唐奇安通道突破策略 (海龟交易法)

均值回归策略:
- BollingerBandsStrategy: 布林带策略
- RSIMeanReversionStrategy: RSI 超买超卖策略
- ZScoreStrategy: Z-Score 统计套利策略
"""

from src.strategy.examples.mean_reversion import (
    BollingerBandsStrategy,
    RSIMeanReversionStrategy,
    ZScoreStrategy,
    create_mean_reversion_strategy,
)
from src.strategy.examples.trend_following import (
    DonchianBreakoutStrategy,
    DualMAStrategy,
    create_trend_strategy,
)

__all__ = [
    # Trend Following
    "DualMAStrategy",
    "DonchianBreakoutStrategy",
    "create_trend_strategy",
    # Mean Reversion
    "BollingerBandsStrategy",
    "RSIMeanReversionStrategy",
    "ZScoreStrategy",
    "create_mean_reversion_strategy",
]
