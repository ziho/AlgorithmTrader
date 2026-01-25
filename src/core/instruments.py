"""
Symbol 规范化模块

内部格式: EXCHANGE:BASE/QUOTE (例如 OKX:BTC/USDT)

职责:
- 交易所 Symbol 映射 (OKX/IBKR)
- 标准化转换
- Symbol 解析与验证
"""

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class Exchange(str, Enum):
    """支持的交易所"""

    OKX = "OKX"
    BINANCE = "BINANCE"
    IBKR = "IBKR"


class AssetType(str, Enum):
    """资产类型"""

    SPOT = "spot"  # 现货
    SWAP = "swap"  # 永续合约
    FUTURES = "futures"  # 交割合约
    STOCK = "stock"  # 股票
    OPTION = "option"  # 期权


@dataclass
class Symbol:
    """
    统一 Symbol 表示

    内部格式: EXCHANGE:BASE/QUOTE
    例如: OKX:BTC/USDT, IBKR:AAPL/USD
    """

    exchange: Exchange
    base: str  # 基础资产，如 BTC, AAPL
    quote: str  # 计价资产，如 USDT, USD
    asset_type: AssetType = AssetType.SPOT

    # 交易所映射规则
    _EXCHANGE_FORMATS: ClassVar[dict[Exchange, str]] = {
        Exchange.OKX: "{base}-{quote}",  # OKX 格式: BTC-USDT
        Exchange.BINANCE: "{base}{quote}",  # Binance 格式: BTCUSDT
        Exchange.IBKR: "{base}",  # IBKR 格式: AAPL (股票代码)
    }

    @property
    def internal(self) -> str:
        """
        内部标准格式

        Returns:
            str: 如 "OKX:BTC/USDT"
        """
        return f"{self.exchange.value}:{self.base}/{self.quote}"

    @property
    def ccxt(self) -> str:
        """
        CCXT 格式

        Returns:
            str: 如 "BTC/USDT"
        """
        return f"{self.base}/{self.quote}"

    @property
    def exchange_format(self) -> str:
        """
        交易所原生格式

        Returns:
            str: 交易所特定格式
        """
        fmt = self._EXCHANGE_FORMATS.get(self.exchange, "{base}/{quote}")
        return fmt.format(base=self.base, quote=self.quote)

    @classmethod
    def from_internal(cls, symbol_str: str) -> "Symbol":
        """
        从内部格式解析

        Args:
            symbol_str: 如 "OKX:BTC/USDT"

        Returns:
            Symbol 实例
        """
        if ":" not in symbol_str:
            raise ValueError(
                f"Invalid internal format: {symbol_str}, expected EXCHANGE:BASE/QUOTE"
            )

        exchange_str, pair = symbol_str.split(":", 1)

        if "/" not in pair:
            raise ValueError(f"Invalid pair format: {pair}, expected BASE/QUOTE")

        base, quote = pair.split("/", 1)

        try:
            exchange = Exchange(exchange_str.upper())
        except ValueError as err:
            raise ValueError(f"Unknown exchange: {exchange_str}") from err

        return cls(exchange=exchange, base=base.upper(), quote=quote.upper())

    @classmethod
    def from_ccxt(cls, ccxt_symbol: str, exchange: Exchange) -> "Symbol":
        """
        从 CCXT 格式解析

        Args:
            ccxt_symbol: 如 "BTC/USDT"
            exchange: 交易所

        Returns:
            Symbol 实例
        """
        if "/" not in ccxt_symbol:
            raise ValueError(f"Invalid CCXT format: {ccxt_symbol}")

        base, quote = ccxt_symbol.split("/", 1)
        return cls(exchange=exchange, base=base.upper(), quote=quote.upper())

    def __str__(self) -> str:
        return self.internal

    def __repr__(self) -> str:
        return f"Symbol({self.internal}, type={self.asset_type.value})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Symbol):
            return (
                self.internal == other.internal and self.asset_type == other.asset_type
            )
        return False

    def __hash__(self) -> int:
        return hash((self.internal, self.asset_type))


# 常用交易对预定义
class CommonSymbols:
    """常用交易对"""

    # OKX 现货
    OKX_BTC_USDT = Symbol(Exchange.OKX, "BTC", "USDT")
    OKX_ETH_USDT = Symbol(Exchange.OKX, "ETH", "USDT")
    OKX_SOL_USDT = Symbol(Exchange.OKX, "SOL", "USDT")

    # IBKR 美股
    IBKR_AAPL = Symbol(Exchange.IBKR, "AAPL", "USD", AssetType.STOCK)
    IBKR_TSLA = Symbol(Exchange.IBKR, "TSLA", "USD", AssetType.STOCK)
    IBKR_SPY = Symbol(Exchange.IBKR, "SPY", "USD", AssetType.STOCK)


# 导出
__all__ = [
    "Exchange",
    "AssetType",
    "Symbol",
    "CommonSymbols",
]
