"""
OKX 永续合约 Broker 适配器

使用 ccxt 实现:
- 永续合约下单 (开多/开空/平仓)
- 杠杆设置 (全仓/逐仓)
- 保证金查询
- 强平价格计算
- 查询持仓/余额

特性:
- 网络失败重试
- 限频处理
- 订单状态机
- 双向持仓模式支持
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import ccxt
import structlog

from src.core.config import get_settings
from src.core.events import OrderSide, OrderStatus, OrderType
from src.execution.broker_base import (
    Balance,
    BrokerBase,
    BrokerResult,
    BrokerType,
    Order,
    Position,
)

logger = structlog.get_logger(__name__)


class MarginMode(str, Enum):
    """保证金模式"""
    CROSS = "cross"  # 全仓
    ISOLATED = "isolated"  # 逐仓


class PositionSide(str, Enum):
    """持仓方向 (双向持仓模式)"""
    LONG = "long"
    SHORT = "short"
    NET = "net"  # 单向持仓模式


@dataclass
class SwapPosition:
    """
    永续合约持仓

    扩展基础 Position，包含合约特有字段
    """
    symbol: str
    side: PositionSide  # 持仓方向
    quantity: Decimal  # 持仓数量 (张数)
    notional: Decimal  # 名义价值
    avg_price: Decimal  # 持仓均价
    mark_price: Decimal  # 标记价格
    unrealized_pnl: Decimal  # 未实现盈亏
    realized_pnl: Decimal  # 已实现盈亏
    leverage: int  # 杠杆倍数
    margin_mode: MarginMode  # 保证金模式
    liquidation_price: Decimal  # 强平价格
    margin: Decimal  # 保证金
    margin_ratio: Decimal  # 保证金率

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "notional": str(self.notional),
            "avg_price": str(self.avg_price),
            "mark_price": str(self.mark_price),
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl": str(self.realized_pnl),
            "leverage": self.leverage,
            "margin_mode": self.margin_mode.value,
            "liquidation_price": str(self.liquidation_price),
            "margin": str(self.margin),
            "margin_ratio": str(self.margin_ratio),
        }

    def to_position(self) -> Position:
        """转换为基础 Position 对象"""
        return Position(
            symbol=self.symbol,
            side=self.side.value,
            quantity=self.quantity,
            avg_price=self.avg_price,
            unrealized_pnl=self.unrealized_pnl,
            leverage=self.leverage,
        )


class OKXSwapBroker(BrokerBase):
    """
    OKX 永续合约交易适配器

    使用 ccxt 统一 API 实现 OKX 永续合约交易

    特性:
    - 支持 USDT 本位永续合约
    - 支持市价/限价单
    - 支持双向持仓模式
    - 杠杆和保证金模式设置
    - 自动重试网络失败
    - 限频保护
    """

    # USDT 本位永续合约后缀
    SWAP_SUFFIX = "-USDT-SWAP"

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None,
        sandbox: bool = True,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        default_leverage: int = 10,
        margin_mode: MarginMode = MarginMode.CROSS,
    ):
        """
        初始化 OKX 永续合约适配器

        Args:
            api_key: API Key，默认从配置读取
            api_secret: API Secret，默认从配置读取
            passphrase: API Passphrase，默认从配置读取
            sandbox: 是否使用模拟盘
            max_retries: 最大重试次数
            retry_delay: 重试间隔 (秒)
            default_leverage: 默认杠杆倍数
            margin_mode: 保证金模式 (全仓/逐仓)
        """
        super().__init__(
            broker_type=BrokerType.OKX_SWAP,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        # 从配置读取或使用传入的值
        settings = get_settings()
        self._api_key = api_key or settings.okx.api_key.get_secret_value()
        self._api_secret = api_secret or settings.okx.api_secret.get_secret_value()
        self._passphrase = passphrase or settings.okx.passphrase.get_secret_value()
        self._sandbox = sandbox if sandbox is not None else settings.okx.sandbox

        # 合约特有配置
        self._default_leverage = default_leverage
        self._margin_mode = margin_mode

        # ccxt exchange 实例
        self._exchange: ccxt.okx | None = None

        # 限频控制
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.1  # 100ms

    def connect(self) -> BrokerResult:
        """连接到 OKX"""
        try:
            self._exchange = ccxt.okx(
                {
                    "apiKey": self._api_key,
                    "secret": self._api_secret,
                    "password": self._passphrase,
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "swap",  # 永续合约
                    },
                }
            )

            # 设置模拟盘
            if self._sandbox:
                self._exchange.set_sandbox_mode(True)

            # 测试连接
            self._exchange.load_markets()

            self._connected = True
            logger.info(
                "okx_swap_connected",
                sandbox=self._sandbox,
                markets_count=len(self._exchange.markets),
            )

            return BrokerResult.ok()

        except ccxt.AuthenticationError as e:
            logger.error("okx_swap_auth_failed", error=str(e))
            return BrokerResult.fail("AUTH_ERROR", str(e))
        except ccxt.NetworkError as e:
            logger.error("okx_swap_network_error", error=str(e))
            return BrokerResult.fail("NETWORK_ERROR", str(e))
        except Exception as e:
            logger.error("okx_swap_connect_failed", error=str(e))
            return BrokerResult.fail("CONNECT_ERROR", str(e))

    def disconnect(self) -> BrokerResult:
        """断开连接"""
        self._exchange = None
        self._connected = False
        logger.info("okx_swap_disconnected")
        return BrokerResult.ok()

    def _rate_limit(self) -> None:
        """限频控制"""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _retry_request(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """带重试的请求"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                return func(*args, **kwargs)

            except ccxt.RateLimitExceeded as e:
                logger.warning(
                    "rate_limit_exceeded",
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )
                time.sleep(self.retry_delay * (attempt + 1))
                last_error = e

            except ccxt.NetworkError as e:
                logger.warning(
                    "network_error_retry",
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                    error=str(e),
                )
                time.sleep(self.retry_delay)
                last_error = e

            except ccxt.ExchangeNotAvailable as e:
                logger.warning(
                    "exchange_unavailable_retry",
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )
                time.sleep(self.retry_delay * 2)
                last_error = e

        raise last_error if last_error else RuntimeError("Unknown error")

    def _convert_symbol(self, symbol: str) -> str:
        """
        转换交易对格式

        内部格式: "BTC/USDT" 或 "BTC/USDT:USDT"
        ccxt 永续格式: "BTC/USDT:USDT"
        """
        # 如果带有 exchange 前缀，去掉
        if ":" in symbol and not symbol.endswith(":USDT"):
            parts = symbol.split(":")
            symbol = parts[-1]

        # 确保是 USDT 本位永续格式
        if not symbol.endswith(":USDT"):
            base_symbol = symbol.replace("/USDT", "").replace("-USDT", "")
            symbol = f"{base_symbol}/USDT:USDT"

        return symbol

    def _parse_order_status(self, status: str) -> OrderStatus:
        """解析订单状态"""
        status_map = {
            "open": OrderStatus.SUBMITTED,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        return status_map.get(status, OrderStatus.NEW)

    def _parse_order_side(self, side: str) -> OrderSide:
        """解析订单方向"""
        return OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    def _parse_order_type(self, order_type: str) -> OrderType:
        """解析订单类型"""
        return OrderType.LIMIT if order_type.lower() == "limit" else OrderType.MARKET

    def _parse_order(self, raw_order: dict[str, Any], original_order: Order | None = None) -> Order:
        """解析 ccxt 订单为 Order 对象"""
        order = Order(
            symbol=raw_order.get("symbol", ""),
            side=self._parse_order_side(raw_order.get("side", "buy")),
            order_type=self._parse_order_type(raw_order.get("type", "market")),
            quantity=Decimal(str(raw_order.get("amount", 0))),
            price=Decimal(str(raw_order.get("price", 0))) if raw_order.get("price") else None,
            client_order_id=raw_order.get("clientOrderId", "")
            or (original_order.client_order_id if original_order else ""),
            exchange_order_id=raw_order.get("id", ""),
            status=self._parse_order_status(raw_order.get("status", "")),
            filled_quantity=Decimal(str(raw_order.get("filled", 0))),
            filled_avg_price=Decimal(str(raw_order.get("average", 0) or 0)),
            commission=Decimal(str(raw_order.get("fee", {}).get("cost", 0) or 0)),
            commission_asset=raw_order.get("fee", {}).get("currency", ""),
            strategy_name=original_order.strategy_name if original_order else "",
            broker_type=self.broker_type,
            updated_at=datetime.now(UTC),
        )
        return order

    def _parse_swap_position(self, raw_position: dict[str, Any]) -> SwapPosition:
        """解析 ccxt 持仓为 SwapPosition 对象"""
        info = raw_position.get("info", {})

        # 解析持仓方向
        side_str = raw_position.get("side", "").lower()
        if side_str == "long":
            side = PositionSide.LONG
        elif side_str == "short":
            side = PositionSide.SHORT
        else:
            side = PositionSide.NET

        # 解析保证金模式
        margin_mode_str = info.get("mgnMode", "cross").lower()
        margin_mode = MarginMode.ISOLATED if margin_mode_str == "isolated" else MarginMode.CROSS

        return SwapPosition(
            symbol=raw_position.get("symbol", ""),
            side=side,
            quantity=Decimal(str(raw_position.get("contracts", 0) or 0)),
            notional=Decimal(str(raw_position.get("notional", 0) or 0)),
            avg_price=Decimal(str(raw_position.get("entryPrice", 0) or 0)),
            mark_price=Decimal(str(raw_position.get("markPrice", 0) or 0)),
            unrealized_pnl=Decimal(str(raw_position.get("unrealizedPnl", 0) or 0)),
            realized_pnl=Decimal(str(info.get("realizedPnl", 0) or 0)),
            leverage=int(raw_position.get("leverage", 1) or 1),
            margin_mode=margin_mode,
            liquidation_price=Decimal(str(raw_position.get("liquidationPrice", 0) or 0)),
            margin=Decimal(str(raw_position.get("collateral", 0) or 0)),
            margin_ratio=Decimal(str(raw_position.get("marginRatio", 0) or 0)),
        )

    # ==================== 杠杆和保证金设置 ====================

    def set_leverage(self, symbol: str, leverage: int) -> BrokerResult:
        """
        设置杠杆倍数

        Args:
            symbol: 交易对
            leverage: 杠杆倍数 (1-125)

        Returns:
            BrokerResult: 设置结果
        """
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            symbol = self._convert_symbol(symbol)

            logger.info("setting_leverage", symbol=symbol, leverage=leverage)

            result = self._retry_request(
                self._exchange.set_leverage,
                leverage,
                symbol,
            )

            logger.info("leverage_set", symbol=symbol, leverage=leverage)

            return BrokerResult.ok(result)

        except Exception as e:
            logger.error("set_leverage_failed", error=str(e))
            return BrokerResult.fail("LEVERAGE_ERROR", str(e))

    def set_margin_mode(self, symbol: str, mode: MarginMode) -> BrokerResult:
        """
        设置保证金模式

        Args:
            symbol: 交易对
            mode: 保证金模式 (全仓/逐仓)

        Returns:
            BrokerResult: 设置结果
        """
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            symbol = self._convert_symbol(symbol)

            logger.info("setting_margin_mode", symbol=symbol, mode=mode.value)

            result = self._retry_request(
                self._exchange.set_margin_mode,
                mode.value,
                symbol,
            )

            logger.info("margin_mode_set", symbol=symbol, mode=mode.value)

            return BrokerResult.ok(result)

        except Exception as e:
            # 如果已经是目标模式，OKX 会报错，忽略
            if "already" in str(e).lower():
                return BrokerResult.ok()
            logger.error("set_margin_mode_failed", error=str(e))
            return BrokerResult.fail("MARGIN_MODE_ERROR", str(e))

    # ==================== 订单操作 ====================

    def place_order(self, order: Order) -> BrokerResult:
        """下单"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            symbol = self._convert_symbol(order.symbol)
            side = "buy" if order.side == OrderSide.BUY else "sell"
            order_type = "limit" if order.order_type == OrderType.LIMIT else "market"

            params = {
                "clOrdId": order.client_order_id,
            }

            logger.info(
                "placing_swap_order",
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=str(order.quantity),
                price=str(order.price) if order.price else None,
            )

            if order_type == "limit":
                if order.price is None:
                    return BrokerResult.fail(
                        "INVALID_ORDER", "Limit order requires price"
                    )
                raw_order = self._retry_request(
                    self._exchange.create_order,
                    symbol,
                    order_type,
                    side,
                    float(order.quantity),
                    float(order.price),
                    params,
                )
            else:
                raw_order = self._retry_request(
                    self._exchange.create_order,
                    symbol,
                    order_type,
                    side,
                    float(order.quantity),
                    None,
                    params,
                )

            filled_order = self._parse_order(raw_order, order)
            filled_order.status = OrderStatus.SUBMITTED

            logger.info(
                "swap_order_placed",
                exchange_order_id=filled_order.exchange_order_id,
                client_order_id=filled_order.client_order_id,
            )

            return BrokerResult.ok(filled_order)

        except ccxt.InsufficientFunds as e:
            logger.error("insufficient_funds", error=str(e))
            return BrokerResult.fail("INSUFFICIENT_FUNDS", str(e))
        except ccxt.InvalidOrder as e:
            logger.error("invalid_order", error=str(e))
            return BrokerResult.fail("INVALID_ORDER", str(e))
        except ccxt.OrderNotFound as e:
            logger.error("order_not_found", error=str(e))
            return BrokerResult.fail("ORDER_NOT_FOUND", str(e))
        except Exception as e:
            logger.error("place_swap_order_failed", error=str(e))
            return BrokerResult.fail("ORDER_ERROR", str(e))

    def open_long(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal | None = None,
        leverage: int | None = None,
        strategy_name: str = "",
    ) -> BrokerResult:
        """
        开多仓

        Args:
            symbol: 交易对
            quantity: 数量 (张数)
            price: 限价单价格，None 为市价单
            leverage: 杠杆倍数，None 使用默认值
            strategy_name: 策略名称

        Returns:
            BrokerResult: 下单结果
        """
        # 设置杠杆
        if leverage is not None:
            result = self.set_leverage(symbol, leverage)
            if not result.success:
                return result

        # 创建买入订单
        order = Order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT if price else OrderType.MARKET,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            broker_type=self.broker_type,
        )

        return self.place_order(order)

    def open_short(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal | None = None,
        leverage: int | None = None,
        strategy_name: str = "",
    ) -> BrokerResult:
        """
        开空仓

        Args:
            symbol: 交易对
            quantity: 数量 (张数)
            price: 限价单价格，None 为市价单
            leverage: 杠杆倍数，None 使用默认值
            strategy_name: 策略名称

        Returns:
            BrokerResult: 下单结果
        """
        # 设置杠杆
        if leverage is not None:
            result = self.set_leverage(symbol, leverage)
            if not result.success:
                return result

        # 创建卖出订单
        order = Order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT if price else OrderType.MARKET,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            broker_type=self.broker_type,
        )

        return self.place_order(order)

    def close_long(
        self,
        symbol: str,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
        strategy_name: str = "",
    ) -> BrokerResult:
        """
        平多仓

        Args:
            symbol: 交易对
            quantity: 数量，None 表示全部平仓
            price: 限价单价格，None 为市价单
            strategy_name: 策略名称

        Returns:
            BrokerResult: 下单结果
        """
        # 获取当前持仓
        if quantity is None:
            pos_result = self.get_swap_positions(symbol)
            if not pos_result.success:
                return pos_result

            positions = pos_result.data
            long_pos = None
            for p in positions:
                if p.side == PositionSide.LONG and p.quantity > 0:
                    long_pos = p
                    break

            if long_pos is None:
                return BrokerResult.fail("NO_POSITION", "No long position to close")

            quantity = long_pos.quantity

        # 创建卖出订单平仓
        order = Order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT if price else OrderType.MARKET,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            broker_type=self.broker_type,
        )

        return self.place_order(order)

    def close_short(
        self,
        symbol: str,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
        strategy_name: str = "",
    ) -> BrokerResult:
        """
        平空仓

        Args:
            symbol: 交易对
            quantity: 数量，None 表示全部平仓
            price: 限价单价格，None 为市价单
            strategy_name: 策略名称

        Returns:
            BrokerResult: 下单结果
        """
        # 获取当前持仓
        if quantity is None:
            pos_result = self.get_swap_positions(symbol)
            if not pos_result.success:
                return pos_result

            positions = pos_result.data
            short_pos = None
            for p in positions:
                if p.side == PositionSide.SHORT and p.quantity > 0:
                    short_pos = p
                    break

            if short_pos is None:
                return BrokerResult.fail("NO_POSITION", "No short position to close")

            quantity = short_pos.quantity

        # 创建买入订单平仓
        order = Order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT if price else OrderType.MARKET,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            broker_type=self.broker_type,
        )

        return self.place_order(order)

    def cancel_order(
        self,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BrokerResult:
        """撤单"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        if not exchange_order_id and not client_order_id:
            return BrokerResult.fail(
                "INVALID_PARAMS", "Either exchange_order_id or client_order_id required"
            )

        try:
            symbol = self._convert_symbol(symbol)
            params = {}

            if client_order_id:
                params["clOrdId"] = client_order_id

            order_id = exchange_order_id or ""

            logger.info(
                "cancelling_swap_order",
                symbol=symbol,
                exchange_order_id=exchange_order_id,
                client_order_id=client_order_id,
            )

            raw_order = self._retry_request(
                self._exchange.cancel_order,
                order_id,
                symbol,
                params,
            )

            logger.info("swap_order_cancelled", order_id=exchange_order_id or client_order_id)

            return BrokerResult.ok(raw_order)

        except ccxt.OrderNotFound as e:
            logger.warning("order_not_found", error=str(e))
            return BrokerResult.fail("ORDER_NOT_FOUND", str(e))
        except Exception as e:
            logger.error("cancel_swap_order_failed", error=str(e))
            return BrokerResult.fail("CANCEL_ERROR", str(e))

    def query_order(
        self,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BrokerResult:
        """查询订单"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            symbol = self._convert_symbol(symbol)
            order_id = exchange_order_id or client_order_id or ""

            raw_order = self._retry_request(
                self._exchange.fetch_order,
                order_id,
                symbol,
            )

            order = self._parse_order(raw_order)

            return BrokerResult.ok(order)

        except ccxt.OrderNotFound as e:
            return BrokerResult.fail("ORDER_NOT_FOUND", str(e))
        except Exception as e:
            logger.error("query_order_failed", error=str(e))
            return BrokerResult.fail("QUERY_ERROR", str(e))

    def get_open_orders(self, symbol: str | None = None) -> BrokerResult:
        """获取当前挂单"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            converted_symbol = self._convert_symbol(symbol) if symbol else None

            raw_orders = self._retry_request(
                self._exchange.fetch_open_orders,
                converted_symbol,
            )

            orders = [self._parse_order(o) for o in raw_orders]

            return BrokerResult.ok(orders)

        except Exception as e:
            logger.error("get_open_orders_failed", error=str(e))
            return BrokerResult.fail("QUERY_ERROR", str(e))

    # ==================== 账户查询 ====================

    def get_balance(self, asset: str | None = None) -> BrokerResult:
        """查询余额"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            raw_balance = self._retry_request(
                self._exchange.fetch_balance,
                {"type": "swap"},
            )

            balances: list[Balance] = []

            for currency, balance_info in raw_balance.items():
                if currency in ("info", "timestamp", "datetime", "free", "used", "total"):
                    continue

                if isinstance(balance_info, dict):
                    free = Decimal(str(balance_info.get("free", 0) or 0))
                    used = Decimal(str(balance_info.get("used", 0) or 0))

                    if free > 0 or used > 0:
                        b = Balance(
                            asset=currency,
                            free=free,
                            locked=used,
                        )
                        balances.append(b)

            if asset:
                for b in balances:
                    if b.asset.upper() == asset.upper():
                        return BrokerResult.ok(b)
                return BrokerResult.ok(Balance(asset=asset))

            return BrokerResult.ok(balances)

        except Exception as e:
            logger.error("get_balance_failed", error=str(e))
            return BrokerResult.fail("BALANCE_ERROR", str(e))

    def get_positions(self, symbol: str | None = None) -> BrokerResult:
        """查询持仓 (基础接口)"""
        result = self.get_swap_positions(symbol)
        if not result.success:
            return result

        positions = [p.to_position() for p in result.data]
        return BrokerResult.ok(positions)

    def get_swap_positions(self, symbol: str | None = None) -> BrokerResult:
        """
        查询永续合约持仓 (详细信息)

        Args:
            symbol: 交易对，None 查询所有

        Returns:
            BrokerResult: 成功时 data 为 list[SwapPosition]
        """
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            symbols = [self._convert_symbol(symbol)] if symbol else None

            raw_positions = self._retry_request(
                self._exchange.fetch_positions,
                symbols,
            )

            positions: list[SwapPosition] = []
            for raw_pos in raw_positions:
                # 只返回有持仓的
                contracts = float(raw_pos.get("contracts", 0) or 0)
                if contracts > 0:
                    pos = self._parse_swap_position(raw_pos)
                    positions.append(pos)

            return BrokerResult.ok(positions)

        except Exception as e:
            logger.error("get_swap_positions_failed", error=str(e))
            return BrokerResult.fail("POSITION_ERROR", str(e))

    def get_ticker(self, symbol: str) -> BrokerResult:
        """获取当前行情"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            symbol = self._convert_symbol(symbol)

            ticker = self._retry_request(
                self._exchange.fetch_ticker,
                symbol,
            )

            return BrokerResult.ok(ticker)

        except Exception as e:
            logger.error("get_ticker_failed", error=str(e))
            return BrokerResult.fail("TICKER_ERROR", str(e))

    # ==================== 辅助方法 ====================

    def calculate_liquidation_price(
        self,
        symbol: str,  # noqa: ARG002
        side: PositionSide,
        entry_price: Decimal,
        quantity: Decimal,  # noqa: ARG002
        leverage: int,
        margin_mode: MarginMode = MarginMode.CROSS,  # noqa: ARG002
    ) -> Decimal:
        """
        计算预估强平价格

        Args:
            symbol: 交易对 (预留)
            side: 持仓方向
            entry_price: 开仓均价
            quantity: 持仓数量 (预留)
            leverage: 杠杆倍数
            margin_mode: 保证金模式 (预留)

        Returns:
            预估强平价格

        Note:
            这是简化计算，实际强平价格取决于交易所的维持保证金率等因素
        """
        # 简化计算：维持保证金率约为 0.5%
        maintenance_margin_rate = Decimal("0.005")

        if side == PositionSide.LONG:
            # 多头强平价格 = 开仓价 * (1 - 1/杠杆 + 维持保证金率)
            liq_price = entry_price * (
                Decimal("1")
                - Decimal("1") / Decimal(leverage)
                + maintenance_margin_rate
            )
        else:
            # 空头强平价格 = 开仓价 * (1 + 1/杠杆 - 维持保证金率)
            liq_price = entry_price * (
                Decimal("1")
                + Decimal("1") / Decimal(leverage)
                - maintenance_margin_rate
            )

        return liq_price


# 导出
__all__ = [
    "MarginMode",
    "PositionSide",
    "SwapPosition",
    "OKXSwapBroker",
]
