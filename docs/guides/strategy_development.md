# 策略开发指南

本指南说明如何在 AlgorithmTrader 中开发自定义交易策略。

## 策略架构

AlgorithmTrader 的策略遵循事件驱动模型：

```
Bar 数据到达 → on_bar() 处理 → 返回交易信号 → 执行引擎处理 → on_fill() 确认成交
```

所有策略都继承自 `StrategyBase`，实现以下核心方法：
- `on_bar(bar_frame)`：处理新的 K 线数据，返回交易信号
- `on_fill(fill_event)`：处理成交回报（可选）

## 最小策略示例

```python
from src.strategy.base import StrategyBase, StrategyConfig
from src.core.typing import BarFrame, StrategyOutput

class MyFirstStrategy(StrategyBase):
    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)
        self.threshold = self.get_param("threshold", 0.02)

    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        # 数据不足时跳过
        if bar_frame.history is None or len(bar_frame.history) < 10:
            return None

        symbol = bar_frame.symbol  # 例如 "OKX:BTC/USDT"
        current_price = float(bar_frame.close)
        prev_price = float(bar_frame.history["close"].iloc[-2])
        change = (current_price - prev_price) / prev_price

        if change > self.threshold:
            return self.target_long(
                symbol=symbol,
                quantity=1.0,
                reason=f"price_up: {change:.2%}",
            )
        return None
```

## 策略配置

```python
from decimal import Decimal
from src.strategy.base import StrategyConfig

config = StrategyConfig(
    name="my_strategy",
    symbols=["BTC/USDT"],
    timeframes=["15m"],
    params={
        "threshold": 0.02,
        "position_size": 0.1,
    },
    max_position_size=Decimal("10000"),
    stop_loss_pct=0.05,
    take_profit_pct=0.10,
)
```

## 访问数据

`bar_frame` 包含当前 bar 与历史窗口：

```python
def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
    current_close = float(bar_frame.close)
    current_volume = float(bar_frame.volume)
    timestamp = bar_frame.timestamp

    history = bar_frame.history  # DataFrame: open, high, low, close, volume
    close_prices = history["close"].values
```

## 持仓查询

```python
current_position = self.state.get_position(symbol)
if current_position > 0:
    pass  # 多仓
elif current_position < 0:
    pass  # 空仓
else:
    pass  # 空仓
```

## 状态存储

```python
self.set_state("last_ma", ma_value)
self.set_state("entry_price", current_price)

last_ma = self.get_state("last_ma")
entry_price = self.get_state("entry_price")
```

## 生成交易信号

### 目标持仓模式（推荐）

```python
return self.target_long("OKX:BTC/USDT", quantity=1.0, reason="golden_cross")
return self.target_short("OKX:BTC/USDT", quantity=0.5, reason="death_cross")
return self.target_flat("OKX:BTC/USDT", reason="take_profit")
```

### 订单意图模式（高级）

```python
from decimal import Decimal
from src.core.typing import OrderIntent, PositionSide

return OrderIntent(
    symbol="OKX:BTC/USDT",
    side=PositionSide.LONG,
    quantity=Decimal("1.0"),
    order_type="market",
    reason="custom_signal",
)
```

## 技术指标计算

```python
import numpy as np

def _calculate_sma(self, prices: np.ndarray, period: int) -> float:
    if len(prices) < period:
        return np.nan
    return float(np.mean(prices[-period:]))
```

## 策略注册（可选）

```python
from src.strategy.registry import register_strategy

@register_strategy("my_strategy")
class MyStrategy(StrategyBase):
    ...
```

## 最佳实践

1. 所有可调参数通过 `get_param()` 获取
2. 避免在 `on_bar()` 中做网络/IO 操作
3. 使用 `self.set_state()` 保存策略状态
4. 保持策略输出可复现且可解释
