"""
订单管理器

职责:
- 订单状态机 (NEW -> PARTIAL -> FILLED / CANCELLED)
- 本地订单缓存
- 状态同步
- 幂等性保证

设计原则:
- 本地缓存与交易所状态同步
- 防止重复下单
- 断点恢复支持
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.core.events import OrderSide, OrderStatus
from src.execution.broker_base import (
    BrokerBase,
    BrokerResult,
    Order,
)

logger = structlog.get_logger(__name__)


@dataclass
class OrderManagerState:
    """
    订单管理器状态

    用于持久化和恢复
    """

    # 本地订单缓存
    orders: dict[str, Order] = field(default_factory=dict)  # client_order_id -> Order

    # 当日交易统计
    daily_trades: int = 0
    daily_volume: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")

    # 状态记录
    last_sync_time: datetime | None = None
    last_trade_time: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "orders": {k: v.to_dict() for k, v in self.orders.items()},
            "daily_trades": self.daily_trades,
            "daily_volume": str(self.daily_volume),
            "daily_pnl": str(self.daily_pnl),
            "last_sync_time": (
                self.last_sync_time.isoformat() if self.last_sync_time else None
            ),
            "last_trade_time": (
                self.last_trade_time.isoformat() if self.last_trade_time else None
            ),
        }


class OrderManager:
    """
    订单管理器

    管理订单的完整生命周期:
    - 创建订单 (幂等)
    - 提交订单
    - 取消订单
    - 同步状态
    """

    def __init__(self, broker: BrokerBase):
        """
        初始化订单管理器

        Args:
            broker: Broker 实例
        """
        self._broker = broker
        self._state = OrderManagerState()

        # 幂等性: 记录已处理的订单意图
        self._processed_intents: set[str] = set()

    @property
    def broker(self) -> BrokerBase:
        """获取 Broker"""
        return self._broker

    @property
    def state(self) -> OrderManagerState:
        """获取状态"""
        return self._state

    # ==================== 订单操作 ====================

    def submit_order(
        self,
        order: Order,
        intent_id: str | None = None,
    ) -> BrokerResult:
        """
        提交订单

        Args:
            order: 订单对象
            intent_id: 意图ID，用于幂等性检查

        Returns:
            BrokerResult: 提交结果
        """
        # 幂等性检查
        if intent_id and intent_id in self._processed_intents:
            logger.warning("duplicate_intent", intent_id=intent_id)
            # 返回已存在的订单
            existing = self._state.orders.get(order.client_order_id)
            if existing:
                return BrokerResult.ok(existing)
            return BrokerResult.fail("DUPLICATE", "Intent already processed")

        # 检查是否已有相同的挂单
        if order.client_order_id in self._state.orders:
            existing = self._state.orders[order.client_order_id]
            if existing.is_open:
                logger.warning(
                    "order_already_exists",
                    client_order_id=order.client_order_id,
                )
                return BrokerResult.ok(existing)

        # 提交到交易所
        result = self._broker.place_order(order)

        if result.success:
            # 更新本地缓存
            filled_order = result.data
            self._state.orders[filled_order.client_order_id] = filled_order

            # 标记意图已处理
            if intent_id:
                self._processed_intents.add(intent_id)

            logger.info(
                "order_submitted",
                client_order_id=filled_order.client_order_id,
                exchange_order_id=filled_order.exchange_order_id,
                symbol=order.symbol,
                side=order.side.value,
            )

        return result

    def cancel_order(
        self,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
        symbol: str | None = None,  # noqa: ARG002
    ) -> BrokerResult:
        """
        取消订单

        Args:
            client_order_id: 客户端订单ID
            exchange_order_id: 交易所订单ID
            symbol: 交易对

        Returns:
            BrokerResult: 取消结果
        """
        # 查找订单
        order = None
        if client_order_id:
            order = self._state.orders.get(client_order_id)
        elif exchange_order_id:
            for o in self._state.orders.values():
                if o.exchange_order_id == exchange_order_id:
                    order = o
                    break

        if order is None:
            return BrokerResult.fail("ORDER_NOT_FOUND", "Order not in local cache")

        if not order.is_open:
            return BrokerResult.fail("ORDER_NOT_OPEN", "Order is not open")

        # 调用 Broker 取消
        result = self._broker.cancel_order(
            symbol=order.symbol,
            client_order_id=order.client_order_id,
            exchange_order_id=order.exchange_order_id,
        )

        if result.success:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now(UTC)

            logger.info(
                "order_cancelled",
                client_order_id=order.client_order_id,
            )

        return result

    def cancel_all_orders(self, symbol: str | None = None) -> list[BrokerResult]:
        """
        取消所有挂单

        Args:
            symbol: 交易对，None 表示所有

        Returns:
            list[BrokerResult]: 取消结果列表
        """
        results = []

        for order in list(self._state.orders.values()):
            if not order.is_open:
                continue
            if symbol and order.symbol != symbol:
                continue

            result = self.cancel_order(client_order_id=order.client_order_id)
            results.append(result)

        return results

    def sync_order(self, client_order_id: str) -> BrokerResult:
        """
        同步订单状态

        Args:
            client_order_id: 客户端订单ID

        Returns:
            BrokerResult: 同步结果
        """
        order = self._state.orders.get(client_order_id)
        if order is None:
            return BrokerResult.fail("ORDER_NOT_FOUND", "Order not in local cache")

        result = self._broker.query_order(
            symbol=order.symbol,
            client_order_id=client_order_id,
            exchange_order_id=order.exchange_order_id,
        )

        if result.success:
            updated_order = result.data
            self._state.orders[client_order_id] = updated_order

            # 检查是否有新成交
            if updated_order.is_filled and not order.is_filled:
                self._on_order_filled(updated_order)

            logger.debug(
                "order_synced",
                client_order_id=client_order_id,
                status=updated_order.status.value,
            )

        return result

    def sync_all_open_orders(self) -> list[BrokerResult]:
        """同步所有挂单状态"""
        results = []

        for order in list(self._state.orders.values()):
            if order.is_open:
                result = self.sync_order(order.client_order_id)
                results.append(result)

        self._state.last_sync_time = datetime.now(UTC)

        return results

    def _on_order_filled(self, order: Order) -> None:
        """订单成交回调"""
        self._state.daily_trades += 1
        self._state.daily_volume += order.filled_value
        self._state.last_trade_time = datetime.now(UTC)

        logger.info(
            "order_filled",
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            filled_quantity=str(order.filled_quantity),
            filled_avg_price=str(order.filled_avg_price),
        )

    # ==================== 查询方法 ====================

    def get_order(self, client_order_id: str) -> Order | None:
        """获取订单"""
        return self._state.orders.get(client_order_id)

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """获取所有挂单"""
        orders = []
        for order in self._state.orders.values():
            if not order.is_open:
                continue
            if symbol and order.symbol != symbol:
                continue
            orders.append(order)
        return orders

    def get_balance(self, asset: str | None = None) -> BrokerResult:
        """查询余额"""
        return self._broker.get_balance(asset)

    def get_positions(self, symbol: str | None = None) -> BrokerResult:
        """查询持仓"""
        return self._broker.get_positions(symbol)

    # ==================== 便捷方法 ====================

    def buy_market(
        self,
        symbol: str,
        quantity: Decimal,
        strategy_name: str = "",
        intent_id: str | None = None,
    ) -> BrokerResult:
        """市价买入"""
        order = self._broker.create_market_order(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            strategy_name=strategy_name,
        )
        return self.submit_order(order, intent_id)

    def sell_market(
        self,
        symbol: str,
        quantity: Decimal,
        strategy_name: str = "",
        intent_id: str | None = None,
    ) -> BrokerResult:
        """市价卖出"""
        order = self._broker.create_market_order(
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            strategy_name=strategy_name,
        )
        return self.submit_order(order, intent_id)

    def buy_limit(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        strategy_name: str = "",
        intent_id: str | None = None,
    ) -> BrokerResult:
        """限价买入"""
        order = self._broker.create_limit_order(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
        )
        return self.submit_order(order, intent_id)

    def sell_limit(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        strategy_name: str = "",
        intent_id: str | None = None,
    ) -> BrokerResult:
        """限价卖出"""
        order = self._broker.create_limit_order(
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
        )
        return self.submit_order(order, intent_id)

    # ==================== 状态管理 ====================

    def reset_daily_stats(self) -> None:
        """重置当日统计"""
        self._state.daily_trades = 0
        self._state.daily_volume = Decimal("0")
        self._state.daily_pnl = Decimal("0")
        self._processed_intents.clear()

        logger.info("daily_stats_reset")

    def clear_completed_orders(self, keep_recent: int = 100) -> int:
        """
        清理已完成的订单

        Args:
            keep_recent: 保留最近的订单数量

        Returns:
            int: 清理的订单数量
        """
        completed = [o for o in self._state.orders.values() if not o.is_open]
        completed.sort(key=lambda o: o.updated_at, reverse=True)

        to_remove = completed[keep_recent:]
        for order in to_remove:
            del self._state.orders[order.client_order_id]

        if to_remove:
            logger.info("orders_cleaned", count=len(to_remove))

        return len(to_remove)


# 导出
__all__ = [
    "OrderManagerState",
    "OrderManager",
]
