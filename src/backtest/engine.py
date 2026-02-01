"""
回测引擎

职责:
- 读取历史数据
- Bar 级别撮合 (不做订单簿)
- 多品种/跨周期支持
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from src.core.events import FillEvent, OrderSide
from src.core.instruments import Symbol
from src.core.timeframes import Timeframe
from src.core.typing import BarFrame, OrderIntent, PositionSide, TargetPosition
from src.data.storage.parquet_store import ParquetStore
from src.execution.slippage_fee import (
    CostCalculator,
    ExecutionCost,
    FeeModel,
    PercentSlippage,
)
from src.execution.slippage_fee import OrderSide as CostOrderSide
from src.ops.logging import get_logger
from src.strategy.base import StrategyBase, StrategyConfig

logger = get_logger(__name__)


@dataclass
class Trade:
    """成交记录"""

    timestamp: datetime
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal  # 成交价（含滑点）
    commission: Decimal
    strategy_name: str = ""

    @property
    def value(self) -> Decimal:
        """成交金额"""
        return self.quantity * self.price

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "commission": str(self.commission),
            "value": str(self.value),
            "strategy_name": self.strategy_name,
        }


@dataclass
class Position:
    """持仓状态"""

    symbol: str
    quantity: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    def update(self, side: OrderSide, quantity: Decimal, price: Decimal) -> Decimal:
        """
        更新持仓

        Args:
            side: 订单方向
            quantity: 成交数量
            price: 成交价格

        Returns:
            实现盈亏
        """
        realized = Decimal("0")
        signed_qty = quantity if side == OrderSide.BUY else -quantity

        if self.is_flat:
            # 开仓
            self.quantity = signed_qty
            self.avg_price = price
        elif (self.is_long and side == OrderSide.BUY) or (
            self.is_short and side == OrderSide.SELL
        ):
            # 加仓
            total_value = self.quantity * self.avg_price + signed_qty * price
            self.quantity += signed_qty
            if self.quantity != 0:
                self.avg_price = abs(total_value / self.quantity)
        else:
            # 减仓或反向
            if abs(signed_qty) <= abs(self.quantity):
                # 部分/全部平仓
                realized = quantity * (price - self.avg_price)
                if self.is_short:
                    realized = -realized
                self.quantity += signed_qty
                if self.is_flat:
                    self.avg_price = Decimal("0")
            else:
                # 反向开仓
                close_qty = abs(self.quantity)
                realized = close_qty * (price - self.avg_price)
                if self.is_short:
                    realized = -realized
                remain_qty = quantity - close_qty
                self.quantity = remain_qty if side == OrderSide.BUY else -remain_qty
                self.avg_price = price

        self.realized_pnl += realized
        return realized


@dataclass
class EquityPoint:
    """权益曲线点"""

    timestamp: datetime
    equity: Decimal
    cash: Decimal
    position_value: Decimal
    drawdown: Decimal = Decimal("0")
    drawdown_pct: Decimal = Decimal("0")


@dataclass
class BacktestConfig:
    """回测配置"""

    # 初始资金
    initial_capital: Decimal = Decimal("100000")

    # 交易成本
    slippage_pct: Decimal = Decimal("0.0005")  # 0.05%
    commission_rate: Decimal = Decimal("0.001")  # 0.1%

    # 交易所（用于费率配置）
    exchange: str = "okx"

    # 回测时间范围
    start_date: datetime | None = None
    end_date: datetime | None = None

    # 历史窗口大小（用于策略指标计算）
    lookback_bars: int = 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": str(self.initial_capital),
            "slippage_pct": str(self.slippage_pct),
            "commission_rate": str(self.commission_rate),
            "exchange": self.exchange,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "lookback_bars": self.lookback_bars,
        }


@dataclass
class BacktestResult:
    """回测结果"""

    config: BacktestConfig
    strategy_config: StrategyConfig

    # 资金曲线
    equity_curve: list[EquityPoint] = field(default_factory=list)

    # 成交记录
    trades: list[Trade] = field(default_factory=list)

    # 最终状态
    final_equity: Decimal = Decimal("0")
    final_cash: Decimal = Decimal("0")
    final_positions: dict[str, Position] = field(default_factory=dict)

    # 统计摘要
    total_trades: int = 0
    total_commission: Decimal = Decimal("0")

    # 时间信息
    start_time: datetime | None = None
    end_time: datetime | None = None
    run_duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "strategy_config": self.strategy_config.to_dict(),
            "final_equity": str(self.final_equity),
            "final_cash": str(self.final_cash),
            "total_trades": self.total_trades,
            "total_commission": str(self.total_commission),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "run_duration_seconds": self.run_duration_seconds,
            "equity_curve_length": len(self.equity_curve),
            "trades_count": len(self.trades),
        }


class BacktestEngine:
    """
    Bar 级别回测引擎

    特点:
    - 使用下一根 bar 的 open 价格成交
    - 支持多品种
    - 支持滑点和手续费模型
    """

    def __init__(
        self,
        config: BacktestConfig | None = None,
        parquet_store: ParquetStore | None = None,
    ):
        self.config = config or BacktestConfig()
        self.parquet_store = parquet_store or ParquetStore()

        # 成本计算器
        self.cost_calculator = CostCalculator(
            slippage_model=PercentSlippage(self.config.slippage_pct),
            fee_model=FeeModel.from_exchange(self.config.exchange),
        )

        # 状态
        self._cash = self.config.initial_capital
        self._positions: dict[str, Position] = {}
        self._equity_curve: list[EquityPoint] = []
        self._trades: list[Trade] = []
        self._peak_equity = self.config.initial_capital

    def _get_position(self, symbol: str) -> Position:
        """获取或创建持仓"""
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol)
        return self._positions[symbol]

    def _calculate_equity(self, prices: dict[str, Decimal]) -> Decimal:
        """计算当前权益"""
        position_value = Decimal("0")
        for symbol, pos in self._positions.items():
            if symbol in prices:
                position_value += pos.quantity * prices[symbol]
        return self._cash + position_value

    def _process_target_position(
        self,
        target: TargetPosition,
        next_open: Decimal,
        bar_volume: Decimal,
        timestamp: datetime,
    ) -> Trade | None:
        """
        处理目标持仓

        将目标持仓转换为订单并执行
        """
        position = self._get_position(target.symbol)
        current_qty = position.quantity

        # 计算需要交易的数量
        if target.side == PositionSide.FLAT:
            target_qty = Decimal("0")
        elif target.side == PositionSide.LONG:
            target_qty = target.quantity
        else:  # SHORT
            target_qty = -target.quantity

        diff = target_qty - current_qty

        if diff == 0:
            return None

        # 确定订单方向和数量
        side = OrderSide.BUY if diff > 0 else OrderSide.SELL
        trade_qty = abs(diff)

        return self._execute_trade(
            symbol=target.symbol,
            side=side,
            quantity=trade_qty,
            price=next_open,
            bar_volume=bar_volume,
            timestamp=timestamp,
            strategy_name=target.strategy_name,
        )

    def _process_order_intent(
        self,
        intent: OrderIntent,
        next_open: Decimal,
        bar_volume: Decimal,
        timestamp: datetime,
    ) -> Trade | None:
        """处理下单意图"""
        side = OrderSide.BUY if intent.side == PositionSide.LONG else OrderSide.SELL

        return self._execute_trade(
            symbol=intent.symbol,
            side=side,
            quantity=intent.quantity,
            price=next_open,
            bar_volume=bar_volume,
            timestamp=timestamp,
            strategy_name=intent.strategy_name,
        )

    def _execute_trade(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        bar_volume: Decimal,
        timestamp: datetime,
        strategy_name: str = "",
    ) -> Trade | None:
        """执行交易"""
        if quantity <= 0:
            return None

        # 计算交易成本
        cost_side = CostOrderSide.BUY if side == OrderSide.BUY else CostOrderSide.SELL
        cost: ExecutionCost = self.cost_calculator.calculate(
            price=price,
            quantity=quantity,
            side=cost_side,
            bar_volume=bar_volume,
        )

        # 检查资金是否足够（买入时）
        if side == OrderSide.BUY:
            required = cost.trade_value + cost.commission
            if required > self._cash:
                logger.warning(
                    "insufficient_cash",
                    required=str(required),
                    available=str(self._cash),
                )
                return None

        # 更新持仓
        position = self._get_position(symbol)
        position.update(side, quantity, cost.filled_price)

        # 更新现金
        if side == OrderSide.BUY:
            self._cash -= cost.trade_value + cost.commission
        else:
            self._cash += cost.trade_value - cost.commission

        # 创建成交记录
        trade = Trade(
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=cost.filled_price,
            commission=cost.commission,
            strategy_name=strategy_name,
        )
        self._trades.append(trade)

        return trade

    def _create_bar_frame(
        self,
        symbol: str,
        timeframe: str,
        row: pd.Series,
        history_df: pd.DataFrame,
    ) -> BarFrame:
        """创建 BarFrame"""
        return BarFrame(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=row["timestamp"].to_pydatetime(),
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row["volume"])),
            history=history_df,
        )

    def run(
        self,
        strategy: StrategyBase,
        symbols: list[Symbol],
        timeframe: Timeframe,
    ) -> BacktestResult:
        """
        运行回测

        Args:
            strategy: 策略实例
            symbols: 交易品种列表
            timeframe: 时间框架

        Returns:
            回测结果
        """
        import time

        run_start = time.time()

        # 重置状态
        self._cash = self.config.initial_capital
        self._positions = {}
        self._equity_curve = []
        self._trades = []
        self._peak_equity = self.config.initial_capital

        # 加载数据
        data: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            df = self.parquet_store.read(
                symbol=symbol,
                timeframe=timeframe,
                start=self.config.start_date,
                end=self.config.end_date,
            )
            if not df.empty:
                symbol_str = str(symbol)
                data[symbol_str] = df.reset_index(drop=True)
                logger.info(
                    "data_loaded",
                    symbol=symbol_str,
                    rows=len(df),
                )

        if not data:
            logger.warning("no_data_loaded")
            return BacktestResult(
                config=self.config,
                strategy_config=strategy.config,
            )

        # 获取所有时间戳的并集
        all_timestamps = set()
        for df in data.values():
            all_timestamps.update(df["timestamp"].tolist())
        all_timestamps = sorted(all_timestamps)

        logger.info("backtest_start", bars=len(all_timestamps), symbols=len(data))

        # 初始化策略
        strategy.initialize()

        # 主循环
        for ts in all_timestamps:
            current_prices: dict[str, Decimal] = {}
            next_opens: dict[str, Decimal] = {}
            bar_volumes: dict[str, Decimal] = {}

            # 获取每个品种的当前 bar
            for symbol_str, df in data.items():
                mask = df["timestamp"] == ts
                if not mask.any():
                    continue

                idx = df.index[mask][0]
                row = df.iloc[idx]

                current_prices[symbol_str] = Decimal(str(row["close"]))
                bar_volumes[symbol_str] = Decimal(str(row["volume"]))

                # 获取下一根 bar 的 open（用于成交）
                if idx + 1 < len(df):
                    next_opens[symbol_str] = Decimal(str(df.iloc[idx + 1]["open"]))
                else:
                    next_opens[symbol_str] = current_prices[symbol_str]

                # 准备历史数据
                start_idx = max(0, idx - self.config.lookback_bars)
                history_df = df.iloc[start_idx:idx][
                    ["timestamp", "open", "high", "low", "close", "volume"]
                ].copy()

                # 创建 BarFrame 并调用策略
                bar_frame = self._create_bar_frame(
                    symbol=symbol_str,
                    timeframe=timeframe.value,
                    row=row,
                    history_df=history_df,
                )

                # 策略决策
                output = strategy.on_bar(bar_frame)

                # 处理策略输出
                if output is not None:
                    outputs = output if isinstance(output, list) else [output]
                    for out in outputs:
                        trade = None
                        if isinstance(out, TargetPosition):
                            trade = self._process_target_position(
                                target=out,
                                next_open=next_opens.get(
                                    symbol_str, current_prices[symbol_str]
                                ),
                                bar_volume=bar_volumes[symbol_str],
                                timestamp=ts.to_pydatetime()
                                if hasattr(ts, "to_pydatetime")
                                else ts,
                            )
                        elif isinstance(out, OrderIntent):
                            trade = self._process_order_intent(
                                intent=out,
                                next_open=next_opens.get(
                                    out.symbol,
                                    current_prices.get(out.symbol, Decimal("0")),
                                ),
                                bar_volume=bar_volumes.get(out.symbol, Decimal("0")),
                                timestamp=ts.to_pydatetime()
                                if hasattr(ts, "to_pydatetime")
                                else ts,
                            )

                        # 通知策略成交
                        if trade:
                            fill = FillEvent(
                                symbol=trade.symbol,
                                side=trade.side,
                                quantity=trade.quantity,
                                price=trade.price,
                                commission=trade.commission,
                            )
                            strategy.on_fill(fill)

            # 记录权益曲线
            equity = self._calculate_equity(current_prices)
            self._peak_equity = max(self._peak_equity, equity)
            drawdown = self._peak_equity - equity
            drawdown_pct = (
                drawdown / self._peak_equity if self._peak_equity > 0 else Decimal("0")
            )

            position_value = equity - self._cash
            point_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            self._equity_curve.append(
                EquityPoint(
                    timestamp=point_ts,
                    equity=equity,
                    cash=self._cash,
                    position_value=position_value,
                    drawdown=drawdown,
                    drawdown_pct=drawdown_pct,
                )
            )

        # 策略停止
        strategy.on_stop()

        run_duration = time.time() - run_start

        # 计算最终状态
        final_prices = {}
        for symbol_str, df in data.items():
            if not df.empty:
                final_prices[symbol_str] = Decimal(str(df.iloc[-1]["close"]))

        final_equity = self._calculate_equity(final_prices)
        total_commission = sum(t.commission for t in self._trades)

        result = BacktestResult(
            config=self.config,
            strategy_config=strategy.config,
            equity_curve=self._equity_curve,
            trades=self._trades,
            final_equity=final_equity,
            final_cash=self._cash,
            final_positions=self._positions.copy(),
            total_trades=len(self._trades),
            total_commission=total_commission,
            start_time=all_timestamps[0].to_pydatetime()
            if hasattr(all_timestamps[0], "to_pydatetime")
            else all_timestamps[0],
            end_time=all_timestamps[-1].to_pydatetime()
            if hasattr(all_timestamps[-1], "to_pydatetime")
            else all_timestamps[-1],
            run_duration_seconds=run_duration,
        )

        logger.info(
            "backtest_complete",
            final_equity=str(final_equity),
            total_trades=len(self._trades),
            run_duration=f"{run_duration:.2f}s",
        )

        return result


# 导出
__all__ = [
    "Trade",
    "Position",
    "EquityPoint",
    "BacktestConfig",
    "BacktestResult",
    "BacktestEngine",
]
