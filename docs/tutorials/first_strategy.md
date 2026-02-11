# 编写第一个策略

本教程将手把手教你编写一个简单但完整的交易策略。

## 策略目标

我们要实现一个基于 **价格突破** 的简单策略：

- 当价格突破最近 N 根 K线的最高价时，做多
- 当价格跌破最近 M 根 K线的最低价时，平仓

这是一个经典的趋势跟踪策略，也称为 Donchian Channel 突破策略。

## Step 1: 创建策略文件

在项目中创建 `my_strategies/breakout_strategy.py`:

```python
"""
价格突破策略

当价格突破 N 日高点时做多，跌破 M 日低点时平仓
"""

from decimal import Decimal
import numpy as np

from src.strategy.base import StrategyBase, StrategyConfig
from src.core.typing import BarFrame, StrategyOutput


class SimpleBreakoutStrategy(StrategyBase):
    """简单突破策略"""
    
    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)
        
        # 提取参数
        self.entry_period = self.get_param("entry_period", 20)  # 入场周期
        self.exit_period = self.get_param("exit_period", 10)    # 出场周期
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))
    
    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理每根 K线"""
        # TODO: 实现逻辑
        pass
```

## Step 2: 实现数据检查

首先检查是否有足够的历史数据：

```python
def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
    """处理每根 K线"""
    # 检查数据
    required_bars = max(self.entry_period, self.exit_period)
    if bar_frame.history is None or len(bar_frame.history) < required_bars:
        return None  # 数据不足，跳过
    
    symbol = bar_frame.symbol
    current_price = bar_frame.close
    
    # TODO: 计算指标
```

## Step 3: 计算技术指标

计算最近 N 日的最高价和最低价：

```python
def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
    """处理每根 K线"""
    # ... 数据检查代码 ...
    
    # 获取历史价格
    history = bar_frame.history
    high_prices = history["high"].values.astype(float)
    low_prices = history["low"].values.astype(float)
    
    # 计算指标（不包括当前 bar）
    entry_high = float(np.max(high_prices[-(self.entry_period+1):-1]))
    exit_low = float(np.min(low_prices[-(self.exit_period+1):-1]))
    
    # 保存状态用于调试
    self.set_state("entry_high", entry_high)
    self.set_state("exit_low", exit_low)
    
    # TODO: 生成信号
```

## Step 4: 实现交易逻辑

根据价格突破情况生成交易信号：

```python
def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
    """处理每根 K线"""
    # ... 前面的代码 ...
    
    # 获取当前持仓
    current_position = self.state.get_position(symbol)
    
    # 入场信号：突破最高点且当前未持仓
    if current_price > entry_high and current_position <= 0:
        return self.target_long(
            symbol=symbol,
            quantity=self.position_size,
            reason=f"breakout: price={current_price:.2f} > high={entry_high:.2f}"
        )
    
    # 出场信号：跌破最低点且当前持仓
    elif current_price < exit_low and current_position > 0:
        return self.target_flat(
            symbol=symbol,
            reason=f"breakdown: price={current_price:.2f} < low={exit_low:.2f}"
        )
    
    return None
```

## Step 5: 完整代码

```python
"""
价格突破策略

当价格突破 N 日高点时做多，跌破 M 日低点时平仓
"""

from decimal import Decimal
import numpy as np

from src.strategy.base import StrategyBase, StrategyConfig
from src.core.typing import BarFrame, StrategyOutput


class SimpleBreakoutStrategy(StrategyBase):
    """
    简单突破策略
    
    规则:
    - 价格突破 N 日最高价 → 做多
    - 价格跌破 M 日最低价 → 平仓
    
    参数:
    - entry_period: 入场周期，默认 20
    - exit_period: 出场周期，默认 10
    - position_size: 仓位大小，默认 1.0
    """
    
    def __init__(self, config: StrategyConfig | None = None):
        super().__init__(config)
        
        self.entry_period = self.get_param("entry_period", 20)
        self.exit_period = self.get_param("exit_period", 10)
        self.position_size = Decimal(str(self.get_param("position_size", 1.0)))
    
    def on_bar(self, bar_frame: BarFrame) -> StrategyOutput:
        """处理每根 K线"""
        # 1. 检查数据
        required_bars = max(self.entry_period, self.exit_period)
        if bar_frame.history is None or len(bar_frame.history) < required_bars:
            return None
        
        symbol = bar_frame.symbol
        current_price = bar_frame.close
        
        # 2. 计算指标
        history = bar_frame.history
        high_prices = history["high"].values.astype(float)
        low_prices = history["low"].values.astype(float)
        
        # 不包括当前 bar
        entry_high = float(np.max(high_prices[-(self.entry_period+1):-1]))
        exit_low = float(np.min(low_prices[-(self.exit_period+1):-1]))
        
        # 保存状态
        self.set_state("entry_high", entry_high)
        self.set_state("exit_low", exit_low)
        
        # 3. 生成信号
        current_position = self.state.get_position(symbol)
        
        # 突破入场
        if current_price > entry_high and current_position <= 0:
            return self.target_long(
                symbol=symbol,
                quantity=self.position_size,
                reason=f"breakout: {current_price:.2f} > {entry_high:.2f}"
            )
        
        # 跌破出场
        elif current_price < exit_low and current_position > 0:
            return self.target_flat(
                symbol=symbol,
                reason=f"breakdown: {current_price:.2f} < {exit_low:.2f}"
            )
        
        return None
```

## Step 6: 编写回测脚本

创建 `test_breakout.py`:

```python
from datetime import datetime
from decimal import Decimal

from src.backtest.engine import BacktestEngine
from src.strategy.base import StrategyConfig
from my_strategies.breakout_strategy import SimpleBreakoutStrategy

# 配置策略
config = StrategyConfig(
    name="btc_breakout",
    symbols=["BTC/USDT"],
    timeframes=["1h"],
    params={
        "entry_period": 20,
        "exit_period": 10,
        "position_size": 1.0,
    }
)

# 创建策略
strategy = SimpleBreakoutStrategy(config)

# 创建回测引擎
engine = BacktestEngine(
    strategies=[strategy],
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31),
    initial_capital=Decimal("10000"),
    data_source="parquet",
)

# 运行回测
print("开始回测...")
result = engine.run()

# 查看结果
print("\n" + "="*50)
print(result.summary())
print("="*50)

# 详细指标
metrics = result.metrics
print(f"\n总收益率: {metrics.total_return:.2%}")
print(f"年化收益: {metrics.annual_return:.2%}")
print(f"夏普比率: {metrics.sharpe_ratio:.2f}")
print(f"最大回撤: {metrics.max_drawdown:.2%}")
print(f"胜率: {metrics.win_rate:.2%}")
print(f"交易次数: {metrics.total_trades}")

# 保存报告
result.save_report("backtest_reports/breakout_strategy.json")
```

## Step 7: 运行回测

```bash
# 确保已采集数据
python scripts/demo_collect.py --symbol BTC/USDT --days 365

# 运行回测
python test_breakout.py
```

## Step 8: 分析结果

查看输出：

```
开始回测...
Processing BTC/USDT 1h bars...
回测完成

==================================================
策略: btc_breakout
时间范围: 2024-01-01 to 2024-12-31
初始资金: $10,000.00
最终资金: $12,345.67
==================================================

总收益率: 23.46%
年化收益: 23.46%
夏普比率: 1.45
最大回撤: -12.34%
胜率: 48.5%
交易次数: 33
```

### 解读指标

- **总收益率 23.46%**: 不错的收益
- **夏普比率 1.45**: > 1.0，风险调整后收益合理
- **最大回撤 -12.34%**: 可接受范围内
- **胜率 48.5%**: 虽然不到 50%，但趋势策略通常靠盈亏比取胜

## Step 9: 可视化分析

在 Grafana 中查看：

1. 访问 http://localhost:3000
2. 打开 "Backtest Analysis" 面板
3. 选择策略 "btc_breakout"
4. 查看：
   - 权益曲线
   - 回撤曲线
   - 交易点位
   - 持仓分布

## Step 10: 参数优化

尝试不同的参数组合：

```python
# 测试不同的周期
test_configs = [
    {"entry_period": 10, "exit_period": 5},
    {"entry_period": 20, "exit_period": 10},
    {"entry_period": 30, "exit_period": 15},
]

for params in test_configs:
    config = StrategyConfig(
        name=f"breakout_{params['entry_period']}_{params['exit_period']}",
        symbols=["BTC/USDT"],
        params=params
    )
    
    strategy = SimpleBreakoutStrategy(config)
    engine = BacktestEngine(...)
    result = engine.run()
    
    print(f"\n参数: {params}")
    print(f"收益: {result.metrics.total_return:.2%}")
    print(f"夏普: {result.metrics.sharpe_ratio:.2f}")
```

## 改进方向

### 1. 添加过滤条件

避免在震荡市场频繁交易：

```python
# 计算波动率
volatility = np.std(history["close"].pct_change().dropna())

# 只在高波动时交易
if volatility > 0.02:  # 2% 以上波动率
    # 执行突破逻辑
    pass
```

### 2. 动态止损

根据 ATR 设置止损：

```python
def _calculate_atr(self, history, period=14):
    """计算 ATR"""
    high = history["high"].values
    low = history["low"].values
    close = history["close"].values
    
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    
    return np.mean(tr[-period:])

# 使用 ATR 设置止损
atr = self._calculate_atr(history)
stop_loss = entry_price - 2 * atr
```

### 3. 仓位管理

根据波动率动态调整仓位：

```python
# 波动率越大，仓位越小
volatility = np.std(history["close"].pct_change().dropna())
position_size = min(1.0, 0.02 / volatility)
```

## 常见问题

### Q: 为什么计算指标时要排除当前 bar？

A: 避免前视偏差。在实盘中，当前 bar 还未收盘，价格会变化。回测时必须模拟这个限制。

```python
# ❌ 错误：包含当前 bar
entry_high = np.max(high_prices[-self.entry_period:])

# ✅ 正确：排除当前 bar
entry_high = np.max(high_prices[-(self.entry_period+1):-1])
```

### Q: 如何调试策略？

A: 使用状态存储和日志：

```python
# 存储中间变量
self.set_state("entry_high", entry_high)
self.set_state("current_price", current_price)

# 添加日志
from src.ops.logging import get_logger
logger = get_logger(__name__)

logger.debug(f"Price: {current_price}, High: {entry_high}")
```

### Q: 策略不产生任何交易？

A: 检查几个地方：

1. 数据是否充足
2. 参数是否合理
3. 条件是否太严格

```python
# 在 on_bar 中添加日志
logger.info(f"Position: {current_position}, Price: {current_price}, High: {entry_high}")
```

## 下一步

- 尝试修改参数，观察效果
- 添加更多过滤条件
- 组合多个策略
- 查看 [内置策略源码](../../src/strategy/examples/) 学习更多技巧
- 阅读 [策略开发指南](../guides/strategy_development.md) 深入了解接口
