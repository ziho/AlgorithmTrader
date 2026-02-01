"""
OKX 现货 Broker 适配器

使用 ccxt 实现:
- 下单/撤单
- 查询订单状态
- 查询余额/持仓

特性:
- 网络失败重试
- 限频处理
- 订单状态机
"""

import time
from datetime import UTC, datetime
from decimal import Decimal
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


class OKXSpotBroker(BrokerBase):
    """
    OKX 现货交易适配器

    使用 ccxt 统一 API 实现 OKX 现货交易

    特性:
    - 支持市价/限价单
    - 自动重试网络失败
    - 限频保护
    - 订单状态同步
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None,
        sandbox: bool = True,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        初始化 OKX 现货适配器

        Args:
            api_key: API Key，默认从配置读取
            api_secret: API Secret，默认从配置读取
            passphrase: API Passphrase，默认从配置读取
            sandbox: 是否使用模拟盘
            max_retries: 最大重试次数
            retry_delay: 重试间隔 (秒)
        """
        super().__init__(
            broker_type=BrokerType.OKX_SPOT,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        # 从配置读取或使用传入的值
        settings = get_settings()
        self._api_key = api_key or settings.okx.api_key.get_secret_value()
        self._api_secret = api_secret or settings.okx.api_secret.get_secret_value()
        self._passphrase = passphrase or settings.okx.passphrase.get_secret_value()
        self._sandbox = sandbox if sandbox is not None else settings.okx.sandbox

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
                        "defaultType": "spot",
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
                "okx_connected",
                sandbox=self._sandbox,
                markets_count=len(self._exchange.markets),
            )

            return BrokerResult.ok()

        except ccxt.AuthenticationError as e:
            logger.error("okx_auth_failed", error=str(e))
            return BrokerResult.fail("AUTH_ERROR", str(e))
        except ccxt.NetworkError as e:
            logger.error("okx_network_error", error=str(e))
            return BrokerResult.fail("NETWORK_ERROR", str(e))
        except Exception as e:
            logger.error("okx_connect_failed", error=str(e))
            return BrokerResult.fail("CONNECT_ERROR", str(e))

    def disconnect(self) -> BrokerResult:
        """断开连接"""
        self._exchange = None
        self._connected = False
        logger.info("okx_disconnected")
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

        内部格式: "BTC/USDT"
        ccxt 格式: "BTC/USDT"
        """
        # 如果带有 exchange 前缀，去掉
        if ":" in symbol:
            symbol = symbol.split(":")[-1]
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

    def place_order(self, order: Order) -> BrokerResult:
        """下单"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            symbol = self._convert_symbol(order.symbol)
            side = "buy" if order.side == OrderSide.BUY else "sell"
            order_type = "limit" if order.order_type == OrderType.LIMIT else "market"

            params = {"clOrdId": order.client_order_id}

            logger.info(
                "placing_order",
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
                "order_placed",
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
            logger.error("place_order_failed", error=str(e))
            return BrokerResult.fail("ORDER_ERROR", str(e))

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
                "cancelling_order",
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

            logger.info("order_cancelled", order_id=exchange_order_id or client_order_id)

            return BrokerResult.ok(raw_order)

        except ccxt.OrderNotFound as e:
            logger.error("order_not_found", error=str(e))
            return BrokerResult.fail("ORDER_NOT_FOUND", str(e))
        except Exception as e:
            logger.error("cancel_order_failed", error=str(e))
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

            raw_order = self._retry_request(
                self._exchange.fetch_order,
                order_id,
                symbol,
                params,
            )

            order = self._parse_order(raw_order)

            return BrokerResult.ok(order)

        except ccxt.OrderNotFound as e:
            logger.error("order_not_found", error=str(e))
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

    def get_balance(self, asset: str | None = None) -> BrokerResult:
        """查询余额"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            raw_balance = self._retry_request(self._exchange.fetch_balance)

            if asset:
                # 返回单个资产余额
                asset_balance = raw_balance.get(asset, {})
                balance = Balance(
                    asset=asset,
                    free=Decimal(str(asset_balance.get("free", 0) or 0)),
                    locked=Decimal(str(asset_balance.get("used", 0) or 0)),
                )
                return BrokerResult.ok(balance)

            # 返回所有非零余额
            balances = []
            for currency, data in raw_balance.items():
                if currency in ("info", "free", "used", "total", "timestamp", "datetime"):
                    continue
                if isinstance(data, dict):
                    total = float(data.get("total", 0) or 0)
                    if total > 0:
                        balances.append(
                            Balance(
                                asset=currency,
                                free=Decimal(str(data.get("free", 0) or 0)),
                                locked=Decimal(str(data.get("used", 0) or 0)),
                            )
                        )

            return BrokerResult.ok(balances)

        except Exception as e:
            logger.error("get_balance_failed", error=str(e))
            return BrokerResult.fail("BALANCE_ERROR", str(e))

    def get_positions(self, symbol: str | None = None) -> BrokerResult:
        """
        查询持仓

        现货没有真正的 "持仓" 概念，这里用余额模拟
        """
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            balance_result = self.get_balance()
            if not balance_result.success:
                return balance_result

            positions = []
            balances = balance_result.data

            if isinstance(balances, list):
                for bal in balances:
                    if symbol and bal.asset not in symbol:
                        continue

                    if bal.total > 0:
                        positions.append(
                            Position(
                                symbol=f"{bal.asset}/USDT",
                                side="long",
                                quantity=bal.total,
                                avg_price=Decimal("0"),  # 现货无持仓价格
                                leverage=1,
                            )
                        )

            return BrokerResult.ok(positions)

        except Exception as e:
            logger.error("get_positions_failed", error=str(e))
            return BrokerResult.fail("POSITION_ERROR", str(e))

    def get_ticker(self, symbol: str) -> BrokerResult:
        """获取当前行情"""
        if not self._connected or not self._exchange:
            return BrokerResult.fail("NOT_CONNECTED", "Broker not connected")

        try:
            converted_symbol = self._convert_symbol(symbol)

            ticker = self._retry_request(
                self._exchange.fetch_ticker,
                converted_symbol,
            )

            return BrokerResult.ok(ticker)

        except Exception as e:
            logger.error("get_ticker_failed", symbol=symbol, error=str(e))
            return BrokerResult.fail("TICKER_ERROR", str(e))


# 导出
__all__ = ["OKXSpotBroker"]
