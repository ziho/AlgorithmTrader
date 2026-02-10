"""
数据源连接器

支持的数据源:
- Binance: 加密货币现货/合约 (via aiohttp)
- OKX (via ccxt): 加密货币现货/合约
- IBKR: 美股/期权 (待实现)
"""

from .okx import OKXConnector, fetch_ohlcv_simple
from .binance import BinanceConnector, BinanceDataDownloader

__all__ = [
    "OKXConnector",
    "fetch_ohlcv_simple",
    "BinanceConnector",
    "BinanceDataDownloader",
]
