"""
Trader 服务入口

运行方式:
    python -m services.trader.main

职责:
- 基于 bar close 触发策略
- 生成目标仓位 → 风控检查 → 下单
- 幂等性保证
- 断点恢复
"""

import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.core.config import get_settings
from src.core.typing import BarFrame, OrderIntent, PositionSide, TargetPosition
from src.execution.adapters.okx_spot import OKXSpotBroker
from src.execution.broker_base import BrokerBase, Position
from src.execution.order_manager import OrderManager
from src.ops.logging import configure_logging
from src.ops.notify import get_notifier
from src.ops.scheduler import TradingScheduler
from src.risk.engine import RiskContext, RiskEngine, create_default_risk_engine
from src.strategy.base import StrategyBase
from src.strategy.registry import get_strategy

logger = structlog.get_logger(__name__)


@dataclass
class TraderConfig:
    """Trader 配置"""

    # 交易对和时间框架
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT"])
    timeframe: str = "15m"

    # 策略
    strategy_name: str = "example_sma"
    strategy_params: dict[str, Any] = field(default_factory=dict)

    # 风控
    max_daily_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.20
    max_position_pct: float = 0.30

    # 其他
    sandbox: bool = True  # 是否使用模拟盘
    dry_run: bool = False  # 干运行模式（不实际下单）


@dataclass
class TraderState:
    """Trader 状态"""

    # 运行状态
    running: bool = False
    started_at: datetime | None = None

    # 统计
    bars_processed: int = 0
    signals_generated: int = 0
    orders_placed: int = 0
    orders_filled: int = 0

    # 账户
    peak_equity: Decimal = Decimal("0")
    current_equity: Decimal = Decimal("0")

    # 当日
    daily_pnl: Decimal = Decimal("0")
    daily_trades: int = 0


class LiveTrader:
    """
    实盘交易器

    核心职责:
    1. 监听 bar close 事件
    2. 调用策略生成目标仓位/订单意图
    3. 经过风控引擎检查
    4. 调用 OrderManager 下单
    5. 发送通知
    """

    def __init__(
        self,
        config: TraderConfig,
        broker: BrokerBase | None = None,
        strategy: StrategyBase | None = None,
        risk_engine: RiskEngine | None = None,
    ):
        """
        初始化 LiveTrader

        Args:
            config: 配置
            broker: Broker 实例，默认使用 OKX 现货
            strategy: 策略实例，默认从注册表加载
            risk_engine: 风控引擎，默认使用标准配置
        """
        self.config = config
        self.state = TraderState()

        # 初始化 Broker
        self._broker = broker or OKXSpotBroker(sandbox=config.sandbox)

        # 初始化策略
        if strategy:
            self._strategy = strategy
        else:
            strategy_cls = get_strategy(config.strategy_name)
            if strategy_cls is None:
                raise ValueError(f"Strategy not found: {config.strategy_name}")
            self._strategy = strategy_cls()

        # 初始化风控引擎
        self._risk_engine = risk_engine or create_default_risk_engine(
            max_daily_loss_pct=config.max_daily_loss_pct,
            max_drawdown_pct=config.max_drawdown_pct,
            max_position_pct=config.max_position_pct,
        )

        # 初始化订单管理器
        self._order_manager = OrderManager(self._broker)

        # 初始化调度器
        self._scheduler = TradingScheduler()

        # 初始化通知器
        self._notifier = get_notifier()

        # 当前持仓缓存
        self._positions: dict[str, Position] = {}

        # 幂等性: bar 时间戳 -> 是否已处理
        self._processed_bars: set[str] = set()

    @property
    def broker(self) -> BrokerBase:
        """获取 Broker"""
        return self._broker

    @property
    def strategy(self) -> StrategyBase:
        """获取策略"""
        return self._strategy

    @property
    def risk_engine(self) -> RiskEngine:
        """获取风控引擎"""
        return self._risk_engine

    @property
    def order_manager(self) -> OrderManager:
        """获取订单管理器"""
        return self._order_manager

    def start(self) -> None:
        """启动 Trader"""
        logger.info(
            "trader_starting",
            symbols=self.config.symbols,
            timeframe=self.config.timeframe,
            strategy=self.config.strategy_name,
            sandbox=self.config.sandbox,
            dry_run=self.config.dry_run,
        )

        # 连接 Broker
        result = self._broker.connect()
        if not result.success:
            logger.error("broker_connect_failed", error=result.error_message)
            raise RuntimeError(f"Failed to connect broker: {result.error_message}")

        # 初始化策略
        self._strategy.initialize()

        # 同步账户状态
        self._sync_account()

        # 设置调度任务
        self._setup_scheduler()

        # 启动调度器
        self._scheduler.start()

        self.state.running = True
        self.state.started_at = datetime.now(UTC)

        logger.info("trader_started")

        # 发送启动通知
        self._notifier.notify_system(
            title="🚀 Trader Started",
            content=(
                f"Strategy: {self.config.strategy_name}\n"
                f"Symbols: {', '.join(self.config.symbols)}\n"
                f"Timeframe: {self.config.timeframe}\n"
                f"Mode: {'Sandbox' if self.config.sandbox else 'Live'}"
            ),
        )

    def stop(self) -> None:
        """停止 Trader"""
        logger.info("trader_stopping")

        self.state.running = False

        # 停止调度器
        self._scheduler.stop(wait=True)

        # 取消所有挂单
        self._order_manager.cancel_all_orders()

        # 断开 Broker
        self._broker.disconnect()

        # 停止策略
        self._strategy.on_stop()

        logger.info("trader_stopped")

        # 发送停止通知
        self._notifier.notify_system(
            title="🛑 Trader Stopped",
            content=(
                f"Bars processed: {self.state.bars_processed}\n"
                f"Orders placed: {self.state.orders_placed}\n"
                f"Daily PnL: {self.state.daily_pnl:+.2f} USDT"
            ),
        )

    def _setup_scheduler(self) -> None:
        """设置调度任务"""
        # Bar close 策略任务
        self._scheduler.add_bar_close_task(
            task_id="strategy_run",
            func=self._on_bar_close,
            timeframe=self.config.timeframe,
            symbols=self.config.symbols,
            description=f"Strategy run ({self.config.strategy_name})",
        )

        # 账户同步任务 (每分钟)
        self._scheduler.add_task(
            self._scheduler.get_all_tasks()[0].__class__(
                task_id="sync_account",
                task_type=self._scheduler.get_all_tasks()[0].task_type.HEALTH_CHECK,
                func=self._sync_account,
                interval_seconds=60,
                description="Sync account state",
            )
        )

    def _sync_account(self) -> None:
        """同步账户状态"""
        try:
            # 获取余额
            balance_result = self._broker.get_balance("USDT")
            if balance_result.success and balance_result.data:
                balance = balance_result.data
                self.state.current_equity = balance.total

                # 更新峰值
                if balance.total > self.state.peak_equity:
                    self.state.peak_equity = balance.total

            # 获取持仓
            position_result = self._broker.get_positions()
            if position_result.success:
                self._positions = {p.symbol: p for p in position_result.data or []}

            # 同步挂单
            self._order_manager.sync_all_open_orders()

            logger.debug(
                "account_synced",
                equity=str(self.state.current_equity),
                positions=len(self._positions),
            )

        except Exception as e:
            logger.error("sync_account_failed", error=str(e))

    def _on_bar_close(self, symbols: list[str] | None = None) -> None:
        """
        Bar close 触发

        Args:
            symbols: 要处理的交易对
        """
        symbols = symbols or self.config.symbols
        bar_time = datetime.now(UTC)

        # 幂等性检查
        bar_key = f"{bar_time.strftime('%Y%m%d%H%M')}_{self.config.timeframe}"
        if bar_key in self._processed_bars:
            logger.debug("bar_already_processed", bar_key=bar_key)
            return

        logger.info("bar_close_triggered", bar_time=bar_time.isoformat())

        for symbol in symbols:
            try:
                self._process_symbol(symbol, bar_time)
            except Exception as e:
                logger.error(
                    "process_symbol_failed",
                    symbol=symbol,
                    error=str(e),
                    exc_info=True,
                )
                self._notifier.notify_error(
                    title=f"Strategy Error: {symbol}",
                    error=str(e),
                )

        # 标记已处理
        self._processed_bars.add(bar_key)
        self.state.bars_processed += 1

        # 清理旧记录
        if len(self._processed_bars) > 1000:
            oldest = sorted(self._processed_bars)[:500]
            for key in oldest:
                self._processed_bars.discard(key)

    def _process_symbol(self, symbol: str, bar_time: datetime) -> None:
        """
        处理单个交易对

        Args:
            symbol: 交易对
            bar_time: Bar 时间
        """
        # TODO: 从数据存储获取真实的 bar 数据
        # 这里先用模拟数据
        bar_frame = self._get_bar_frame(symbol, bar_time)
        if bar_frame is None:
            logger.warning("bar_data_not_available", symbol=symbol)
            return

        # 调用策略
        output = self._strategy.on_bar(bar_frame)

        if output is None:
            logger.debug("strategy_no_output", symbol=symbol)
            return

        self.state.signals_generated += 1

        # 处理策略输出
        if isinstance(output, TargetPosition):
            self._process_target_position(output)
        elif isinstance(output, OrderIntent):
            self._process_order_intent(output)
        elif isinstance(output, list):
            for item in output:
                if isinstance(item, TargetPosition):
                    self._process_target_position(item)
                elif isinstance(item, OrderIntent):
                    self._process_order_intent(item)

    def _get_bar_frame(self, symbol: str, bar_time: datetime) -> BarFrame | None:
        """
        获取 Bar 数据

        TODO: 从 ParquetStore 或 InfluxDB 获取真实数据
        """
        # 获取当前价格
        ticker_result = self._broker.get_ticker(symbol)
        if not ticker_result.success:
            return None

        ticker = ticker_result.data
        close_price = Decimal(str(ticker.get("last", 0)))

        return BarFrame(
            symbol=f"OKX:{symbol}",
            timeframe=self.config.timeframe,
            timestamp=bar_time,
            open=close_price,
            high=close_price,
            low=close_price,
            close=close_price,
            volume=Decimal(str(ticker.get("baseVolume", 0))),
        )

    def _process_target_position(self, target: TargetPosition) -> None:
        """
        处理目标持仓

        计算当前持仓与目标的差值，生成订单
        """
        symbol = target.symbol
        if ":" in symbol:
            symbol = symbol.split(":")[-1]

        # 获取当前持仓
        current_position = self._positions.get(symbol)
        current_qty = current_position.quantity if current_position else Decimal("0")

        # 计算差值
        if target.side == PositionSide.FLAT:
            target_qty = Decimal("0")
        elif target.side == PositionSide.LONG:
            target_qty = target.quantity
        else:
            target_qty = -target.quantity

        diff = target_qty - current_qty

        if abs(diff) < Decimal("0.0001"):  # 忽略微小差异
            logger.debug("position_unchanged", symbol=symbol)
            return

        # 转换为订单意图
        if diff > 0:
            intent = OrderIntent(
                symbol=symbol,
                side=PositionSide.LONG,
                quantity=diff,
                strategy_name=target.strategy_name,
                reason=target.reason,
            )
        else:
            intent = OrderIntent(
                symbol=symbol,
                side=PositionSide.SHORT,
                quantity=abs(diff),
                strategy_name=target.strategy_name,
                reason=target.reason,
            )

        self._process_order_intent(intent)

    def _process_order_intent(self, intent: OrderIntent) -> None:
        """
        处理订单意图

        1. 风控检查
        2. 下单
        3. 通知
        """
        symbol = intent.symbol
        if ":" in symbol:
            symbol = symbol.split(":")[-1]

        logger.info(
            "processing_order_intent",
            symbol=symbol,
            side=intent.side.value,
            quantity=str(intent.quantity),
            reason=intent.reason,
        )

        # 构建风控上下文
        risk_context = RiskContext(
            total_equity=self.state.current_equity,
            available_balance=self.state.current_equity,
            daily_pnl=self.state.daily_pnl,
            daily_trades=self.state.daily_trades,
            positions={p.symbol: p.quantity for p in self._positions.values()},
            position_values={p.symbol: p.value for p in self._positions.values()},
            peak_equity=self.state.peak_equity,
            pending_order=intent,
        )

        # 风控检查
        should_proceed, risk_results = self._risk_engine.should_proceed(risk_context)

        if not should_proceed:
            # 找出拒绝的规则
            reject_result = next((r for r in risk_results if r.rejected), None)
            if reject_result:
                logger.warning(
                    "order_rejected_by_risk",
                    rule=reject_result.rule_name,
                    message=reject_result.message,
                )
                self._notifier.notify_risk(
                    rule_name=reject_result.rule_name,
                    action="reject",
                    reason=reject_result.message,
                    details=reject_result.details,
                )
            return

        # 干运行模式
        if self.config.dry_run:
            logger.info(
                "dry_run_order",
                symbol=symbol,
                side=intent.side.value,
                quantity=str(intent.quantity),
            )
            return

        # 生成意图ID用于幂等性
        intent_id = (
            f"{symbol}_{intent.side.value}_{intent.quantity}_"
            f"{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
        )

        # 下单
        if intent.side == PositionSide.LONG:
            result = self._order_manager.buy_market(
                symbol=symbol,
                quantity=intent.quantity,
                strategy_name=intent.strategy_name,
                intent_id=intent_id,
            )
        else:
            result = self._order_manager.sell_market(
                symbol=symbol,
                quantity=intent.quantity,
                strategy_name=intent.strategy_name,
                intent_id=intent_id,
            )

        if result.success:
            self.state.orders_placed += 1
            order = result.data

            # 发送通知
            self._notifier.notify_order(
                symbol=symbol,
                side="buy" if intent.side == PositionSide.LONG else "sell",
                quantity=intent.quantity,
                strategy=intent.strategy_name,
            )

            logger.info(
                "order_placed",
                symbol=symbol,
                client_order_id=order.client_order_id,
            )
        else:
            logger.error(
                "order_failed",
                symbol=symbol,
                error=result.error_message,
            )
            self._notifier.notify_error(
                title=f"Order Failed: {symbol}",
                error=result.error_message,
            )


def main() -> None:
    """Trader 服务主入口"""
    # 配置日志
    configure_logging(service_name="trader")

    settings = get_settings()

    # 解析配置
    config = TraderConfig(
        symbols=["BTC/USDT", "ETH/USDT"],
        timeframe="15m",
        strategy_name="example_sma",
        sandbox=True,
        dry_run=settings.is_dev,  # 开发环境默认干运行
    )

    # 创建 Trader
    trader = LiveTrader(config)

    # 信号处理
    def signal_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        logger.info("shutdown_signal_received", signal=signum)
        trader.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 启动
        trader.start()

        # 保持运行
        while trader.state.running:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
    except Exception as e:
        logger.error("trader_error", error=str(e), exc_info=True)
    finally:
        trader.stop()


if __name__ == "__main__":
    main()
