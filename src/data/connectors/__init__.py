"""
数据源连接器

支持的数据源:
- Binance: 加密货币现货/合约 (via aiohttp)
- OKX (via ccxt): 加密货币现货/合约
- Tushare: A 股数据 (via tushare pro)
- IBKR: 美股/期权 (待实现)
"""

from .binance import BinanceConnector, BinanceDataDownloader
from .okx import OKXConnector, fetch_ohlcv_simple
from .tushare import TushareConnector

__all__ = [
    "OKXConnector",
    "fetch_ohlcv_simple",
    "BinanceConnector",
    "BinanceDataDownloader",
    "TushareConnector",
]
