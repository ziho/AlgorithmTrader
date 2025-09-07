# Phase 4: 策略开发与回测

**预计时间**: 2-3天  
**前置条件**: Phase 3 完成，数据可视化正常  
**目标**: 实现双均线策略，建立回测框架，计算策略表现

## 步骤清单

### 4.1 创建策略引擎框架

#### 目录结构
```bash
mkdir -p apps/strategy_engine
mkdir -p apps/common
```

#### 基础事件模型

**apps/common/events.py**
```python
"""
事件模型定义
遵循 vibe_rule.md: 统一事件结构，支持审计追踪
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum

class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL" 
    HOLD = "HOLD"

@dataclass
class MarketData:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = "binance"

@dataclass
class TradingSignal:
    symbol: str
    timestamp: datetime
    signal_type: SignalType
    strength: float  # 0.0 - 1.0
    price: float
    reason: str
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float
    entry_time: datetime
    current_price: float
    unrealized_pnl: float
    
@dataclass
class Trade:
    symbol: str
    side: str  # 'BUY' or 'SELL'
    quantity: float
    price: float
    timestamp: datetime
    commission: float
    trade_id: str
```

#### 策略基类

**apps/strategy_engine/base_strategy.py**
```python
"""
策略基类
所有策略都应继承此类
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import pandas as pd
import logging

from apps.common.events import MarketData, TradingSignal, Position

class BaseStrategy(ABC):
    def __init__(self, name: str, config: Dict):
        self.name = name
        self.config = config
        self.logger = logging.getLogger(f"strategy.{name}")
        self.positions: Dict[str, Position] = {}
        self.signals_history: List[TradingSignal] = []
        
    @abstractmethod
    def calculate_signal(self, market_data: MarketData, 
                        historical_data: pd.DataFrame) -> Optional[TradingSignal]:
        """
        计算交易信号
        
        Args:
            market_data: 当前市场数据
            historical_data: 历史数据DataFrame
            
        Returns:
            TradingSignal or None
        """
        pass
        
    @abstractmethod
    def get_required_history_length(self) -> int:
        """返回策略所需的历史数据长度"""
        pass
        
    def add_signal(self, signal: TradingSignal):
        """添加信号到历史记录"""
        self.signals_history.append(signal)
        self.logger.info(f"Generated signal: {signal}")
        
    def get_current_position(self, symbol: str) -> Optional[Position]:
        """获取当前持仓"""
        return self.positions.get(symbol)
        
    def update_position(self, symbol: str, position: Position):
        """更新持仓"""
        self.positions[symbol] = position
```

### 4.2 实现双均线策略

**apps/strategy_engine/ma_strategy.py**
```python
"""
双均线策略实现
策略逻辑: MA5 > MA20 买入, MA5 < MA20 卖出
"""
import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime

from .base_strategy import BaseStrategy
from apps.common.events import MarketData, TradingSignal, SignalType

class MovingAverageStrategy(BaseStrategy):
    def __init__(self, config: Dict):
        super().__init__("MovingAverage", config)
        self.short_window = config.get('short_window', 5)
        self.long_window = config.get('long_window', 20)
        self.min_strength_threshold = config.get('min_strength', 0.02)  # 2%
        
    def get_required_history_length(self) -> int:
        return max(self.short_window, self.long_window) + 1
        
    def calculate_signal(self, market_data: MarketData, 
                        historical_data: pd.DataFrame) -> Optional[TradingSignal]:
        """
        计算双均线交易信号
        """
        if len(historical_data) < self.get_required_history_length():
            return None
            
        # 计算移动平均线
        prices = historical_data['close'].values
        ma_short = np.mean(prices[-self.short_window:])
        ma_long = np.mean(prices[-self.long_window:])
        
        # 计算前一时刻的移动平均线(用于判断交叉)
        if len(prices) > self.get_required_history_length():
            prev_ma_short = np.mean(prices[-self.short_window-1:-1])
            prev_ma_long = np.mean(prices[-self.long_window-1:-1])
        else:
            return None
            
        # 判断交叉信号
        signal_type = SignalType.HOLD
        strength = 0.0
        reason = f"MA{self.short_window}={ma_short:.2f}, MA{self.long_window}={ma_long:.2f}"
        
        # 金叉: 短期均线上穿长期均线
        if (prev_ma_short <= prev_ma_long and ma_short > ma_long):
            signal_type = SignalType.BUY
            strength = abs(ma_short - ma_long) / ma_long  # 相对差值作为强度
            reason = f"Golden Cross: {reason}"
            
        # 死叉: 短期均线下穿长期均线  
        elif (prev_ma_short >= prev_ma_long and ma_short < ma_long):
            signal_type = SignalType.SELL
            strength = abs(ma_long - ma_short) / ma_long
            reason = f"Death Cross: {reason}"
            
        # 只有当信号强度足够大时才发出信号
        if signal_type != SignalType.HOLD and strength >= self.min_strength_threshold:
            signal = TradingSignal(
                symbol=market_data.symbol,
                timestamp=market_data.timestamp,
                signal_type=signal_type,
                strength=strength,
                price=market_data.close,
                reason=reason,
                metadata={
                    'ma_short': ma_short,
                    'ma_long': ma_long,
                    'prev_ma_short': prev_ma_short,
                    'prev_ma_long': prev_ma_long
                }
            )
            self.add_signal(signal)
            return signal
            
        return None
```

### 4.3 建立回测引擎

**apps/strategy_engine/backtest.py**
```python
"""
回测引擎
支持历史数据回放，计算策略表现
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
import logging

from .base_strategy import BaseStrategy
from apps.common.events import MarketData, TradingSignal, Trade, SignalType

class BacktestEngine:
    def __init__(self, initial_capital: float = 10000, 
                 commission_rate: float = 0.001):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.logger = logging.getLogger("backtest")
        
    def run_backtest(self, strategy: BaseStrategy, 
                    historical_data: pd.DataFrame,
                    symbol: str) -> Dict:
        """
        运行回测
        
        Args:
            strategy: 策略实例
            historical_data: 历史数据 (OHLCV)
            symbol: 交易对
            
        Returns:
            回测结果字典
        """
        # 初始化回测状态
        capital = self.initial_capital
        position = 0.0  # 持仓数量
        trades: List[Trade] = []
        equity_curve = []
        
        required_length = strategy.get_required_history_length()
        
        self.logger.info(f"Starting backtest for {symbol} with {len(historical_data)} bars")
        
        # 逐根K线回放
        for i in range(required_length, len(historical_data)):
            current_bar = historical_data.iloc[i]
            history_window = historical_data.iloc[i-required_length:i]
            
            # 构造当前市场数据
            market_data = MarketData(
                symbol=symbol,
                timestamp=current_bar['timestamp'],
                open=current_bar['open'],
                high=current_bar['high'], 
                low=current_bar['low'],
                close=current_bar['close'],
                volume=current_bar['volume']
            )
            
            # 计算策略信号
            signal = strategy.calculate_signal(market_data, history_window)
            
            # 执行交易逻辑
            if signal and signal.signal_type != SignalType.HOLD:
                trade = self._execute_trade(signal, capital, position, trades)
                if trade:
                    capital = trade['new_capital']
                    position = trade['new_position']
                    trades.append(trade['trade'])
                    
            # 记录权益曲线
            current_value = capital
            if position > 0:
                current_value = position * current_bar['close']
            
            equity_curve.append({
                'timestamp': current_bar['timestamp'],
                'equity': current_value,
                'capital': capital,
                'position': position,
                'price': current_bar['close']
            })
            
        # 计算回测结果
        return self._calculate_performance_metrics(
            equity_curve, trades, historical_data)
    
    def _execute_trade(self, signal: TradingSignal, capital: float, 
                      current_position: float, trades: List) -> Optional[Dict]:
        """执行交易"""
        commission = 0.0
        new_capital = capital
        new_position = current_position
        
        if signal.signal_type == SignalType.BUY and current_position == 0:
            # 全仓买入
            quantity = capital / signal.price
            commission = quantity * signal.price * self.commission_rate
            new_capital = 0
            new_position = quantity - (commission / signal.price)
            
            trade = Trade(
                symbol=signal.symbol,
                side='BUY',
                quantity=new_position,
                price=signal.price,
                timestamp=signal.timestamp,
                commission=commission,
                trade_id=f"T{len(trades)+1}"
            )
            
            return {
                'trade': trade,
                'new_capital': new_capital,
                'new_position': new_position
            }
            
        elif signal.signal_type == SignalType.SELL and current_position > 0:
            # 全部卖出
            commission = current_position * signal.price * self.commission_rate
            new_capital = (current_position * signal.price) - commission
            new_position = 0
            
            trade = Trade(
                symbol=signal.symbol,
                side='SELL',
                quantity=current_position,
                price=signal.price,
                timestamp=signal.timestamp,
                commission=commission,
                trade_id=f"T{len(trades)+1}"
            )
            
            return {
                'trade': trade,
                'new_capital': new_capital,
                'new_position': new_position
            }
            
        return None
    
    def _calculate_performance_metrics(self, equity_curve: List[Dict], 
                                     trades: List[Trade], 
                                     historical_data: pd.DataFrame) -> Dict:
        """计算回测表现指标"""
        df_equity = pd.DataFrame(equity_curve)
        
        if len(df_equity) == 0:
            return {'error': 'No equity data'}
            
        final_equity = df_equity['equity'].iloc[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital
        
        # 计算收益率序列
        df_equity['returns'] = df_equity['equity'].pct_change().fillna(0)
        
        # 计算指标
        metrics = {
            'initial_capital': self.initial_capital,
            'final_equity': final_equity,
            'total_return': total_return,
            'total_trades': len(trades),
            'winning_trades': sum(1 for t in trades if t.side == 'SELL'),
            'equity_curve': df_equity.to_dict('records'),
            'trades': [t.__dict__ for t in trades]
        }
        
        if len(df_equity) > 1:
            returns = df_equity['returns'].dropna()
            if len(returns) > 0 and returns.std() > 0:
                metrics.update({
                    'sharpe_ratio': returns.mean() / returns.std() * np.sqrt(252),
                    'max_drawdown': self._calculate_max_drawdown(df_equity['equity']),
                    'volatility': returns.std() * np.sqrt(252),
                    'win_rate': len([t for t in trades if self._is_winning_trade(t, trades)]) / max(len(trades), 1)
                })
        
        return metrics
    
    def _calculate_max_drawdown(self, equity_series: pd.Series) -> float:
        """计算最大回撤"""
        peak = equity_series.cummax()
        drawdown = (equity_series - peak) / peak
        return abs(drawdown.min())
    
    def _is_winning_trade(self, trade: Trade, all_trades: List[Trade]) -> bool:
        """判断是否为盈利交易(简化版本)"""
        # 实际实现需要配对买卖交易
        return True  # 占位符
```

### 4.4 策略运行脚本

**apps/strategy_engine/main.py**
```python
"""
策略引擎主程序
"""
import os
import sys
import json
import pandas as pd
from datetime import datetime
import logging

from ma_strategy import MovingAverageStrategy
from backtest import BacktestEngine

def load_historical_data(symbol: str) -> pd.DataFrame:
    """从Parquet文件加载历史数据"""
    file_path = f"/data/lake/crypto/spot/{symbol}/{symbol}_1m_historical.parquet"
    df = pd.read_parquet(file_path)
    
    # 确保时间列格式正确
    if 'open_time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['open_time'])
    
    # 确保数据按时间排序
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    return df

def main():
    # 配置日志
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # 策略配置
    strategy_config = {
        'short_window': int(os.getenv('STRATEGY_MA_SHORT', 5)),
        'long_window': int(os.getenv('STRATEGY_MA_LONG', 20)),
        'min_strength': 0.01
    }
    
    # 回测配置
    backtest_config = {
        'initial_capital': float(os.getenv('STRATEGY_INITIAL_CAPITAL', 10000)),
        'commission_rate': float(os.getenv('STRATEGY_TRADING_FEE', 0.001))
    }
    
    # 交易对列表
    symbols = os.getenv('BINANCE_DATA_SYMBOLS', 'BTCUSDT,ETHUSDT').split(',')
    
    # 运行回测
    results = {}
    
    for symbol in symbols:
        logger.info(f"Processing {symbol}...")
        
        try:
            # 加载数据
            historical_data = load_historical_data(symbol)
            logger.info(f"Loaded {len(historical_data)} bars for {symbol}")
            
            # 初始化策略和回测引擎
            strategy = MovingAverageStrategy(strategy_config)
            backtest_engine = BacktestEngine(**backtest_config)
            
            # 运行回测
            result = backtest_engine.run_backtest(strategy, historical_data, symbol)
            results[symbol] = result
            
            # 输出结果摘要
            logger.info(f"Backtest completed for {symbol}:")
            logger.info(f"  Total Return: {result.get('total_return', 0):.2%}")
            logger.info(f"  Total Trades: {result.get('total_trades', 0)}")
            logger.info(f"  Sharpe Ratio: {result.get('sharpe_ratio', 0):.2f}")
            logger.info(f"  Max Drawdown: {result.get('max_drawdown', 0):.2%}")
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {str(e)}")
            results[symbol] = {'error': str(e)}
    
    # 保存结果
    output_path = "/data/backtest_results.json"
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"Results saved to {output_path}")

if __name__ == "__main__":
    main()
```

### 4.5 Docker化策略引擎

**apps/strategy_engine/Dockerfile**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV TZ=UTC

CMD ["python", "main.py"]
```

**apps/strategy_engine/requirements.txt**
```
pandas>=2.0.0
numpy>=1.24.0
pyarrow>=12.0.0
python-dateutil>=2.8.2
```

### 4.6 运行策略回测

```bash
# 构建策略引擎镜像
cd apps/strategy_engine
docker build -t strategy-engine .

# 运行回测
docker run --rm \
  --network algorithmtrader_quant-net \
  --env-file ../../.env \
  -v $(pwd)/../../data:/data \
  strategy-engine
```

### 4.7 在Grafana中展示策略结果

创建策略表现面板，展示：
- 权益曲线对比基准
- 交易信号标记
- 回测关键指标
- 策略参数设置

## 验收标准

### 策略逻辑
- [ ] 双均线计算正确
- [ ] 交叉信号识别准确
- [ ] 信号强度计算合理
- [ ] 历史信号可追溯

### 回测功能
- [ ] 历史数据回放正确
- [ ] 交易执行逻辑准确
- [ ] 佣金计算正确
- [ ] 权益曲线连续

### 性能指标
- [ ] 总收益率计算准确
- [ ] 夏普比率计算正确
- [ ] 最大回撤计算准确
- [ ] 胜率统计正确

### 结果输出
- [ ] JSON格式结果正确
- [ ] 日志信息完整
- [ ] 错误处理适当
- [ ] 可视化展示清晰

## 故障排除

### 数据问题
```bash
# 检查历史数据完整性
python -c "
import pandas as pd
df = pd.read_parquet('/data/lake/crypto/spot/BTCUSDT/BTCUSDT_1m_historical.parquet')
print(f'Data shape: {df.shape}')
print(f'Columns: {df.columns.tolist()}')
print(f'Date range: {df.open_time.min()} to {df.open_time.max()}')
print(f'Missing values: {df.isnull().sum().sum()}')
"
```

### 策略问题
```bash
# 验证移动平均线计算
python -c "
import numpy as np
import pandas as pd

# 生成测试数据
prices = [100, 101, 102, 99, 98, 103, 105, 104, 106, 108]
ma5 = [np.mean(prices[i-5:i]) for i in range(5, len(prices))]
print('MA5:', ma5)
"
```

### 回测问题
```bash
# 检查回测结果文件
cat /data/backtest_results.json | jq .

# 验证交易逻辑
grep -i "trade" /var/log/strategy_engine.log
```

## 下一步

完成Phase 4后，继续Phase 5: 监控与告警

**检查点**:
- 策略信号生成正确
- 回测结果合理
- 性能指标计算准确
- 结果可视化正常

继续阅读: `phase_5_monitoring.md`
