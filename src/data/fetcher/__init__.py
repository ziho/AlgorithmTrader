"""
数据获取器模块

提供统一的历史数据下载和实时数据追赶能力:
- 历史数据批量下载 (Binance Public Data / OKX API)
- 实时数据追赶和补齐
- 断点续传
- 缺口检测与修复

主要组件:
- HistoryFetcher: 历史数据批量下载器
- RealtimeSyncer: 实时追赶与补齐
- DataManager: 统一 Python API
"""

from .history import HistoryFetcher
from .manager import DataManager, get_history
from .realtime import RealtimeSyncer

__all__ = [
    "HistoryFetcher",
    "RealtimeSyncer",
    "DataManager",
    "get_history",
]
