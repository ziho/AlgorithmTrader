"""
A 股交易规则

实现 A 股特有的交易规则限制:
- T+1：买入当日不可卖出
- 涨跌停：根据板块限制（主板 ±10%，创业板/科创板 ±20%，ST ±5%）
- 最小交易单位：100 股（1 手）
- 手续费：佣金 + 印花税

用法:
    rules = AShareTradingRules()
    # 在回测撮合前调用
    result = rules.validate_order(order_side, quantity, price, symbol_info, ...)
    if not result.allowed:
        # 拒绝成交，记录原因
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum


class AShareBoard(StrEnum):
    """A 股板块分类"""

    MAIN = "main"  # 主板 (60xxxx.SH, 00xxxx.SZ)
    GEM = "gem"  # 创业板 (30xxxx.SZ) - Growth Enterprise Market
    STAR = "star"  # 科创板 (688xxx.SH) - Star Market
    BSE = "bse"  # 北交所 (8xxxxx/4xxxxx)


class OrderRejectReason(StrEnum):
    """订单拒绝原因"""

    T_PLUS_1 = "t_plus_1"  # T+1 限制
    LIMIT_UP = "limit_up"  # 涨停无法买入
    LIMIT_DOWN = "limit_down"  # 跌停无法卖出
    LOT_SIZE = "lot_size"  # 不满足最小交易单位
    INSUFFICIENT_CASH = "insufficient_cash"


@dataclass
class OrderValidation:
    """订单验证结果"""

    allowed: bool
    adjusted_quantity: Decimal  # 调整后的数量（向下取整到 100）
    reject_reason: OrderRejectReason | None = None
    message: str = ""


@dataclass
class AShareCostBreakdown:
    """A 股交易成本分解"""

    commission: Decimal  # 佣金
    stamp_tax: Decimal  # 印花税（仅卖出）
    transfer_fee: Decimal  # 过户费
    total: Decimal  # 总成本

    def to_dict(self) -> dict[str, str]:
        return {
            "commission": str(self.commission),
            "stamp_tax": str(self.stamp_tax),
            "transfer_fee": str(self.transfer_fee),
            "total": str(self.total),
        }


# ============================================
# 默认参数
# ============================================

# 涨跌停幅度
PRICE_LIMIT_PCT: dict[AShareBoard, Decimal] = {
    AShareBoard.MAIN: Decimal("0.10"),  # ±10%
    AShareBoard.GEM: Decimal("0.20"),  # ±20%
    AShareBoard.STAR: Decimal("0.20"),  # ±20%
    AShareBoard.BSE: Decimal("0.30"),  # ±30%
}

# ST 股票涨跌停
ST_PRICE_LIMIT_PCT = Decimal("0.05")  # ±5%

# 最小交易单位
MIN_LOT_SIZE = Decimal("100")

# 费用参数
DEFAULT_COMMISSION_RATE = Decimal("0.0003")  # 万三
MIN_COMMISSION = Decimal("5")  # 最低 5 元
STAMP_TAX_RATE = Decimal("0.0005")  # 印花税 0.05%（2023年8月后减半）
TRANSFER_FEE_RATE = Decimal("0.00001")  # 过户费 0.001%


def classify_board(ts_code: str) -> AShareBoard:
    """
    根据股票代码判断所属板块

    Args:
        ts_code: 如 '600519.SH', '300059.SZ', '688001.SH'

    Returns:
        板块分类
    """
    code = ts_code.split(".")[0] if "." in ts_code else ts_code

    if code.startswith("688"):
        return AShareBoard.STAR
    elif code.startswith("30"):
        return AShareBoard.GEM
    elif code.startswith(("8", "4")):
        return AShareBoard.BSE
    else:
        return AShareBoard.MAIN


def get_price_limit(
    ts_code: str,
    pre_close: Decimal,
    is_st: bool = False,
) -> tuple[Decimal, Decimal]:
    """
    计算涨跌停价格

    Args:
        ts_code: 股票代码
        pre_close: 昨收价
        is_st: 是否为 ST 股票

    Returns:
        (跌停价, 涨停价)
    """
    if is_st:
        limit_pct = ST_PRICE_LIMIT_PCT
    else:
        board = classify_board(ts_code)
        limit_pct = PRICE_LIMIT_PCT[board]

    # 涨跌停价格（精确到分）
    limit_up = (pre_close * (1 + limit_pct)).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )
    limit_down = (pre_close * (1 - limit_pct)).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )

    return limit_down, limit_up


def round_lot_size(quantity: Decimal) -> Decimal:
    """
    将数量向下取整到 100 的整数倍

    Args:
        quantity: 原始数量

    Returns:
        调整后的数量
    """
    lots = int(quantity / MIN_LOT_SIZE)
    return MIN_LOT_SIZE * Decimal(str(lots))


def calculate_a_share_cost(
    quantity: Decimal,
    price: Decimal,
    is_sell: bool,
    commission_rate: Decimal = DEFAULT_COMMISSION_RATE,
    min_commission: Decimal = MIN_COMMISSION,
    stamp_tax_rate: Decimal = STAMP_TAX_RATE,
    transfer_fee_rate: Decimal = TRANSFER_FEE_RATE,
) -> AShareCostBreakdown:
    """
    计算 A 股交易成本

    Args:
        quantity: 成交数量（股）
        price: 成交价格
        is_sell: 是否为卖出
        commission_rate: 佣金费率
        min_commission: 最低佣金
        stamp_tax_rate: 印花税费率
        transfer_fee_rate: 过户费费率

    Returns:
        成本分解
    """
    trade_value = quantity * price

    # 佣金（买卖均收，有最低限额）
    commission = max(trade_value * commission_rate, min_commission)

    # 印花税（仅卖出）
    stamp_tax = trade_value * stamp_tax_rate if is_sell else Decimal("0")

    # 过户费
    transfer_fee = trade_value * transfer_fee_rate

    total = commission + stamp_tax + transfer_fee

    return AShareCostBreakdown(
        commission=commission,
        stamp_tax=stamp_tax,
        transfer_fee=transfer_fee,
        total=total,
    )


class AShareTradingRules:
    """
    A 股交易规则验证器

    在回测撮合前调用，检查:
    1. T+1 规则
    2. 涨跌停限制
    3. 最小交易单位
    """

    def __init__(
        self,
        commission_rate: Decimal = DEFAULT_COMMISSION_RATE,
        min_commission: Decimal = MIN_COMMISSION,
        stamp_tax_rate: Decimal = STAMP_TAX_RATE,
    ) -> None:
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate

        # 记录买入日期 {symbol: last_buy_date}
        self._buy_dates: dict[str, datetime] = {}

    def record_buy(self, symbol: str, trade_date: datetime) -> None:
        """记录买入日期（用于 T+1 判断）"""
        self._buy_dates[symbol] = trade_date

    def clear_buy_record(self, symbol: str) -> None:
        """清除买入记录（平仓后）"""
        self._buy_dates.pop(symbol, None)

    def validate_order(
        self,
        is_buy: bool,
        quantity: Decimal,
        price: Decimal,
        ts_code: str,
        trade_date: datetime,
        pre_close: Decimal | None = None,
        is_st: bool = False,
    ) -> OrderValidation:
        """
        验证订单是否符合 A 股交易规则

        Args:
            is_buy: 是否买入
            quantity: 委托数量
            price: 成交价格（通常为 next bar open）
            ts_code: 股票代码
            trade_date: 交易日
            pre_close: 昨收价（用于涨跌停判断）
            is_st: 是否 ST

        Returns:
            OrderValidation 验证结果
        """
        # 1. 数量取整到 100
        adjusted_qty = round_lot_size(quantity)
        if adjusted_qty <= 0:
            return OrderValidation(
                allowed=False,
                adjusted_quantity=Decimal("0"),
                reject_reason=OrderRejectReason.LOT_SIZE,
                message=f"数量 {quantity} 不足 100 股最小交易单位",
            )

        # 2. T+1 规则：卖出检查
        if not is_buy:
            last_buy = self._buy_dates.get(ts_code)
            if last_buy is not None and last_buy.date() >= trade_date.date():
                return OrderValidation(
                    allowed=False,
                    adjusted_quantity=adjusted_qty,
                    reject_reason=OrderRejectReason.T_PLUS_1,
                    message=(
                        f"T+1 限制: {ts_code} 于 {last_buy.date()} 买入，"
                        f"不可在 {trade_date.date()} 卖出"
                    ),
                )

        # 3. 涨跌停判断
        if pre_close is not None and pre_close > 0:
            limit_down, limit_up = get_price_limit(ts_code, pre_close, is_st)

            if is_buy and price >= limit_up:
                # 涨停买入 → 拒绝（实际涨停时无法买入）
                return OrderValidation(
                    allowed=False,
                    adjusted_quantity=adjusted_qty,
                    reject_reason=OrderRejectReason.LIMIT_UP,
                    message=(f"涨停限制: {ts_code} 价格 {price} >= 涨停价 {limit_up}"),
                )

            if not is_buy and price <= limit_down:
                # 跌停卖出 → 拒绝（实际跌停时无法卖出）
                return OrderValidation(
                    allowed=False,
                    adjusted_quantity=adjusted_qty,
                    reject_reason=OrderRejectReason.LIMIT_DOWN,
                    message=(
                        f"跌停限制: {ts_code} 价格 {price} <= 跌停价 {limit_down}"
                    ),
                )

        return OrderValidation(
            allowed=True,
            adjusted_quantity=adjusted_qty,
        )

    def calculate_cost(
        self,
        quantity: Decimal,
        price: Decimal,
        is_sell: bool,
    ) -> AShareCostBreakdown:
        """计算交易成本"""
        return calculate_a_share_cost(
            quantity=quantity,
            price=price,
            is_sell=is_sell,
            commission_rate=self.commission_rate,
            min_commission=self.min_commission,
            stamp_tax_rate=self.stamp_tax_rate,
        )

    def reset(self) -> None:
        """重置状态（新回测开始时调用）"""
        self._buy_dates.clear()
