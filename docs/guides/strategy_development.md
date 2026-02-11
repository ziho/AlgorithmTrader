# 策略开发指南

本指南将教你如何在 AlgorithmTrader 中开发自己的交易策略。

## 策略架构

### 核心概念

AlgorithmTrader 的策略遵循事件驱动模型：

```
Bar 数据到达 → on_bar() 处理 → 返回交易信号 → 执行引擎处理 → on_fill() 确认成交
```

所有策略都继承自 `StrategyBase`，实现以下两个核心方法：

- `on_bar(bar_frame)`: 处理新的 K线数据，返回交易信号
- `on_fill(fill_event)`: 处理成交回报（可选）

### 最小策略示例

```python
from src.strategy.base import StrategyBase, StrategyConfig
from src.core.typing import BarFrame, StrategyOutput

class MyFirstStrategy(StrategyBase):
    """我的第一个策略"""
    
    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)
        
        # 提取参数
        self.threshold = self.get_param("threshold", 0.02)
    
    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理 bar 数据"""
        # 检查历史数据
        if bar_frame.history is None or len(bar_frame.history) < 10:
            return None
        
        symbol = bar_frame.symbol
        current_price = bar_frame.close
        
        # 计算简单逻辑（涨幅超过阈值就做多）
        prev_price = bar_frame.history["close"].iloc[-2]
        change = (current_price - prev_price) / prev_price
        
        if change > self.threshold:
            return self.target_long(
                symbol=symbol,
                quantity=1.0,
                reason=f"price_up: {change:.2%}"
            )
        
        return None
```

## 策略配置

### 配置文件

策略通过 `StrategyConfig` 进行配置：

```python
from src.strategy.base import StrategyConfig

config = StrategyConfig(
    name="my_strategy",
    symbols=["BTC/USDT", "ETH/USDT"],
    timeframes=["15m"],
    params={
        "threshold": 0.02,
        "position_size": 0.1,
    },
    # 风控参数（可选）
    max_position_size=Decimal("10000"),
    stop_loss_pct=0.05,
    take_profit_pct=0.10,
)

strategy = MyFirstStrategy(config)
```

### 参数访问

使用 `get_param()` 获取参数，支持默认值：

```python
self.threshold = self.get_param("threshold", 0.02)  # 默认 0.02
self.use_ema = self.get_param("use_ema", False)      # 默认 False
```

## 访问数据

### Bar 数据

`bar_frame` 包含当前 bar 和历史数据：

```python
def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
    # 当前 bar
    current_close = bar_frame.close
    current_volume = bar_frame.volume
    timestamp = bar_frame.timestamp
    
    # 历史数据（pandas DataFrame）
    history = bar_frame.history  # columns: open, high, low, close, volume
    
    # 获取历史收盘价
    close_prices = history["close"].values
    
    # 计算技术指标
    sma_20 = close_prices[-20:].mean()
```

### 持仓查询

```python
# 获取当前持仓
current_position = self.state.get_position(symbol)  # Decimal 类型

# 检查是否持仓
if current_position > 0:
    # 持有多仓
    pass
elif current_position < 0:
    # 持有空仓
    pass
else:
    # 空仓
    pass
```

### 状态存储

策略可以存储状态用于跨 bar 传递信息：

```python
# 存储状态
self.set_state("last_ma", ma_value)
self.set_state("entry_price", current_price)

# 读取状态
last_ma = self.get_state("last_ma")
entry_price = self.get_state("entry_price")
```

## 生成交易信号

### 目标持仓模式（推荐）

```python
# 做多（持仓量为 quantity）
return self.target_long(
    symbol="BTC/USDT",
    quantity=1.0,
    reason="golden_cross"
)

# 做空
return self.target_short(
    symbol="BTC/USDT",
    quantity=0.5,
    reason="death_cross"
)

# 平仓
return self.target_flat(
    symbol="BTC/USDT",
    reason="take_profit"
)
```

### 订单意图模式（高级）

```python
from src.core.typing import OrderIntent, OrderSide

return OrderIntent(
    symbol="BTC/USDT",
    side=OrderSide.BUY,
    quantity=Decimal("1.0"),
    order_type="market",
    reason="custom_signal"
)
```

## 技术指标计算

### 使用 NumPy

```python
import numpy as np

def _calculate_sma(self, prices: np.ndarray, period: int) -> float:
    """简单移动平均"""
    if len(prices) < period:
        return np.nan
    return float(np.mean(prices[-period:]))

def _calculate_ema(self, prices: np.ndarray, period: int) -> float:
    """指数移动平均"""
    if len(prices) < period:
        return np.nan
    weights = np.exp(np.linspace(-1, 0, period))
    weights /= weights.sum()
    return float(np.dot(prices[-period:], weights))
```

### RSI 示例

```python
def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
    """相对强弱指标"""
    if len(prices) < period + 1:
        return np.nan
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)
```

### 布林带示例

```python
def _calculate_bollinger_bands(
    self, prices: np.ndarray, period: int = 20, std_dev: float = 2.0
) -> tuple[float, float, float]:
    """布林带: (中轨, 上轨, 下轨)"""
    if len(prices) < period:
        return np.nan, np.nan, np.nan
    
    middle = np.mean(prices[-period:])
    std = np.std(prices[-period:])
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    return float(middle), float(upper), float(lower)
```

## 完整策略示例

### 双均线交叉策略

```python
from decimal import Decimal
import numpy as np
from src.strategy.base import StrategyBase, StrategyConfig
from src.core.typing import BarFrame, StrategyOutput

class DualMAStrategy(StrategyBase):
    """
    双均线交叉策略
    
    规则:
    - 快线上穿慢线 → 做多
    - 快线下穿慢线 → 平仓
    """
    
    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)
        self.fast_period = self.get_param("fast_period", 10)
        self.slow_period = self.get_param("slow_period", 30)
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))
    
    def _calculate_ma(self, prices: np.ndarray, period: int) -> float:
        if len(prices) < period:
            return np.nan
        return float(np.mean(prices[-period:]))
    
    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        # 检查历史数据
        if bar_frame.history is None or len(bar_frame.history) < self.slow_period:
            return None
        
        symbol = bar_frame.symbol
        close_prices = bar_frame.history["close"].values.astype(float)
        
        # 计算均线
        fast_ma = self._calculate_ma(close_prices, self.fast_period)
        slow_ma = self._calculate_ma(close_prices, self.slow_period)
        
        if np.isnan(fast_ma) or np.isnan(slow_ma):
            return None
        
        # 保存状态
        self.set_state("fast_ma", fast_ma)
        self.set_state("slow_ma", slow_ma)
        
        # 获取当前持仓
        current_position = self.state.get_position(symbol)
        
        # 金叉做多
        if fast_ma > slow_ma and current_position <= 0:
            return self.target_long(
                symbol=symbol,
                quantity=self.position_size,
                reason=f"golden_cross: fast={fast_ma:.2f} > slow={slow_ma:.2f}"
            )
        
        # 死叉平仓
        elif fast_ma < slow_ma and current_position > 0:
            return self.target_flat(
                symbol=symbol,
                reason=f"death_cross: fast={fast_ma:.2f} < slow={slow_ma:.2f}"
            )
        
        return None
```

## 回测策略

### 使用脚本回测

创建 `backtest_my_strategy.py`:

```python
from datetime import datetime
from src.backtest.engine import BacktestEngine
from src.strategy.base import StrategyConfig
from my_strategy import MyFirstStrategy

# 配置策略
config = StrategyConfig(
    name="my_strategy_backtest",
    symbols=["BTC/USDT"],
    params={
        "threshold": 0.02,
        "position_size": 1.0,
    }
)

strategy = MyFirstStrategy(config)

# 运行回测
engine = BacktestEngine(
    strategies=[strategy],
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31),
    initial_capital=10000.0,
    data_source="parquet"
)

result = engine.run()
print(result.summary())
```

运行：

```bash
python backtest_my_strategy.py
```

## 最佳实践

### 1. 参数化

将所有可调参数放在配置中，不要硬编码：

```python
# ❌ 不好
if price > 50000:
    ...

# ✅ 好
threshold = self.get_param("price_threshold", 50000)
if price > threshold:
    ...
```

### 2. 避免前视偏差

不要使用未来数据：

```python
# ❌ 错误 - 使用了当前 bar 之后的数据
future_high = bar_frame.history["high"].iloc[-1]

# ✅ 正确 - 使用历史数据
prev_high = bar_frame.history["high"].iloc[-2]
```

### 3. 处理缺失数据

始终检查数据完整性：

```python
if bar_frame.history is None or len(bar_frame.history) < self.required_bars:
    return None
```

### 4. 合理的信号频率

避免每个 bar 都发送信号：

```python
# 只在条件真正改变时发送信号
prev_signal = self.get_state("last_signal")
if signal != prev_signal:
    self.set_state("last_signal", signal)
    return signal
return None
```

### 5. 添加日志

使用日志帮助调试：

```python
from src.ops.logging import get_logger

logger = get_logger(__name__)

def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
    logger.debug(f"Processing {bar_frame.symbol} at {bar_frame.timestamp}")
    ...
```

## 常见问题

### Q: 如何在策略中使用多个时间周期？

A: 在配置中指定多个 timeframe，系统会为每个周期调用 on_bar：

```python
config = StrategyConfig(
    name="multi_timeframe",
    symbols=["BTC/USDT"],
    timeframes=["15m", "1h"],
    ...
)
```

在策略中：

```python
def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
    timeframe = bar_frame.timeframe
    if timeframe == "15m":
        # 处理 15 分钟数据
        pass
    elif timeframe == "1h":
        # 处理 1 小时数据
        pass
```

### Q: 如何实现止损止盈？

A: 在策略中跟踪入场价格并检查：

```python
def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
    current_price = bar_frame.close
    entry_price = self.get_state("entry_price")
    
    if entry_price is not None:
        pnl_pct = (current_price - entry_price) / entry_price
        
        # 止损
        if pnl_pct < -0.05:
            return self.target_flat(symbol, reason="stop_loss")
        
        # 止盈
        if pnl_pct > 0.10:
            return self.target_flat(symbol, reason="take_profit")
```

### Q: 策略可以访问多个品种的数据吗？

A: on_bar 每次只传入一个品种的数据。如果需要多品种联动，可以在状态中存储其他品种的信息。

## 下一步

- 查看 [内置策略源码](../../src/strategy/examples/) 学习更多示例
- 阅读 [第一个策略](../tutorials/first_strategy.md) 了解完整流程
- 查看 [数据采集](data_collection.md) 了解数据准备
- 了解 [Web 界面](web_ui.md) 中的策略与回测入口
