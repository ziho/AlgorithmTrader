"""
数据管理器 - 统一 Python API

提供简洁的接口获取历史数据:
- get_history(): 获取历史数据，自动补齐缺口
- 支持 pandas/polars 输出格式
- 自动处理多时间框架聚合
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional, Union

import pandas as pd
import polars as pl

from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import get_logger

logger = get_logger(__name__)


class DataManager:
    """
    数据管理器
    
    提供统一的数据访问接口:
    - 自动从 Parquet 读取历史数据
    - 支持缺口检测和自动补齐
    - 支持 1m 数据聚合到其他周期
    """
    
    # 支持的交易所
    EXCHANGES = {
        "binance": Exchange.BINANCE,
        "okx": Exchange.OKX,
    }
    
    def __init__(
        self,
        data_dir: Path | str = "./data",
        auto_fill_gaps: bool = True,
    ):
        """
        初始化数据管理器
        
        Args:
            data_dir: 数据目录
            auto_fill_gaps: 是否自动补齐缺口
        """
        self.data_dir = Path(data_dir)
        self.auto_fill_gaps = auto_fill_gaps
        
        # Parquet 存储
        self._parquet_store = ParquetStore(base_path=self.data_dir / "parquet")
        
        logger.info(
            "data_manager_initialized",
            data_dir=str(self.data_dir),
        )
    
    def _parse_symbol(
        self,
        symbol: str,
        exchange: str = "binance",
    ) -> Symbol:
        """解析交易对字符串"""
        symbol_upper = symbol.replace("/", "").upper()
        
        if symbol_upper.endswith("USDT"):
            base = symbol_upper[:-4]
            quote = "USDT"
        elif symbol_upper.endswith("BUSD"):
            base = symbol_upper[:-4]
            quote = "BUSD"
        elif symbol_upper.endswith("BTC"):
            base = symbol_upper[:-3]
            quote = "BTC"
        else:
            # 默认假设后 3 位是 quote
            base = symbol_upper[:-3]
            quote = symbol_upper[-3:]
        
        ex = self.EXCHANGES.get(exchange.lower(), Exchange.BINANCE)
        return Symbol(exchange=ex, base=base, quote=quote)
    
    def get_history(
        self,
        exchange: str,
        symbol: str,
        start: datetime | str,
        end: datetime | str,
        tf: str = "1m",
        fmt: Literal["pandas", "polars", "path"] = "pandas",
    ) -> Union[pd.DataFrame, pl.DataFrame, Path, None]:
        """
        获取历史数据
        
        Args:
            exchange: 交易所 (binance, okx)
            symbol: 交易对 (如 BTCUSDT, BTC/USDT)
            start: 开始时间 (datetime 或 ISO 字符串)
            end: 结束时间
            tf: 时间框架 (1m, 5m, 15m, 1h, 4h, 1d)
            fmt: 返回格式 (pandas, polars, path)
            
        Returns:
            DataFrame 或 Parquet 文件路径
        """
        # 解析时间
        if isinstance(start, str):
            start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if isinstance(end, str):
            end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        
        # 确保 UTC
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        
        # 解析 symbol
        sym = self._parse_symbol(symbol, exchange)
        timeframe = Timeframe(tf)
        
        logger.debug(
            "get_history",
            symbol=str(sym),
            timeframe=tf,
            start=start.isoformat(),
            end=end.isoformat(),
            fmt=fmt,
        )
        
        # 读取数据
        if fmt == "polars":
            df = self._parquet_store.read_polars(sym, timeframe, start, end)
            return df
        elif fmt == "path":
            # 返回 parquet 目录路径
            path = (
                self._parquet_store.base_path
                / sym.exchange.value.lower()
                / f"{sym.base}_{sym.quote}".upper()
                / timeframe.value
            )
            return path if path.exists() else None
        else:
            # pandas
            df = self._parquet_store.read(sym, timeframe, start, end)
            return df
    
    def get_data_range(
        self,
        exchange: str,
        symbol: str,
        tf: str = "1m",
    ) -> tuple[datetime, datetime] | None:
        """
        获取数据的时间范围
        
        Returns:
            (earliest, latest) 或 None
        """
        sym = self._parse_symbol(symbol, exchange)
        timeframe = Timeframe(tf)
        return self._parquet_store.get_data_range(sym, timeframe)
    
    def detect_gaps(
        self,
        exchange: str,
        symbol: str,
        tf: str = "1m",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[tuple[datetime, datetime]]:
        """
        检测数据缺口
        
        Returns:
            [(gap_start, gap_end), ...]
        """
        sym = self._parse_symbol(symbol, exchange)
        timeframe = Timeframe(tf)
        return self._parquet_store.detect_gaps(sym, timeframe, start, end)
    
    def aggregate_to_higher_tf(
        self,
        df: pd.DataFrame,
        source_tf: str,
        target_tf: str,
    ) -> pd.DataFrame:
        """
        将低频数据聚合到高频
        
        Args:
            df: 源 DataFrame (必须有 timestamp, open, high, low, close, volume 列)
            source_tf: 源时间框架
            target_tf: 目标时间框架
            
        Returns:
            聚合后的 DataFrame
        """
        if df.empty:
            return df
        
        source = Timeframe(source_tf)
        target = Timeframe(target_tf)
        
        if target.seconds <= source.seconds:
            raise ValueError(f"Target timeframe {target_tf} must be higher than source {source_tf}")
        
        # 按目标时间框架分组
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        
        # 计算每个 bar 属于哪个目标周期
        df["group_ts"] = df["timestamp"].apply(lambda x: target.floor(x.to_pydatetime()))
        
        # 聚合
        agg_df = df.groupby("group_ts").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).reset_index()
        
        agg_df = agg_df.rename(columns={"group_ts": "timestamp"})
        agg_df = agg_df.sort_values("timestamp").reset_index(drop=True)
        
        return agg_df
    
    def get_latest(
        self,
        exchange: str,
        symbol: str,
        tf: str = "1m",
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        获取最新的 N 条数据
        
        Args:
            exchange: 交易所
            symbol: 交易对
            tf: 时间框架
            limit: 数量限制
            
        Returns:
            DataFrame
        """
        sym = self._parse_symbol(symbol, exchange)
        timeframe = Timeframe(tf)
        
        # 获取数据范围
        data_range = self._parquet_store.get_data_range(sym, timeframe)
        
        if not data_range:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
        
        _, latest = data_range
        
        # 计算开始时间
        start = latest - (timeframe.timedelta * limit)
        
        return self._parquet_store.read(sym, timeframe, start, latest)
    
    def list_available_data(
        self,
        exchange: Optional[str] = None,
    ) -> list[dict]:
        """
        列出可用数据
        
        Returns:
            [{"exchange": str, "symbol": str, "timeframe": str, "range": (start, end)}]
        """
        results = []
        
        base_path = self._parquet_store.base_path
        
        # 遍历交易所目录
        if not base_path.exists():
            return results
        
        for ex_dir in base_path.iterdir():
            if not ex_dir.is_dir():
                continue
            
            ex_name = ex_dir.name
            
            if exchange and ex_name.lower() != exchange.lower():
                continue
            
            # 遍历交易对目录
            for sym_dir in ex_dir.iterdir():
                if not sym_dir.is_dir():
                    continue
                
                # 解析交易对 (格式: BTC_USDT)
                parts = sym_dir.name.split("_")
                if len(parts) != 2:
                    continue
                
                base, quote = parts
                
                # 遍历时间框架
                for tf_dir in sym_dir.iterdir():
                    if not tf_dir.is_dir():
                        continue
                    
                    tf_name = tf_dir.name
                    
                    # 检查是否有数据
                    parquet_files = list(tf_dir.glob("**/data.parquet"))
                    if not parquet_files:
                        continue
                    
                    try:
                        sym = Symbol(
                            exchange=self.EXCHANGES.get(ex_name.lower(), Exchange.BINANCE),
                            base=base,
                            quote=quote,
                        )
                        timeframe = Timeframe(tf_name)
                        data_range = self._parquet_store.get_data_range(sym, timeframe)
                    except Exception:
                        data_range = None
                    
                    results.append({
                        "exchange": ex_name,
                        "symbol": f"{base}/{quote}",
                        "timeframe": tf_name,
                        "range": data_range,
                    })
        
        return results


# 便捷函数
_manager: DataManager | None = None


def get_history(
    exchange: str,
    symbol: str,
    start: datetime | str,
    end: datetime | str,
    tf: str = "1m",
    fmt: Literal["pandas", "polars", "path"] = "pandas",
    data_dir: str = "./data",
) -> Union[pd.DataFrame, pl.DataFrame, Path, None]:
    """
    获取历史数据（便捷函数）
    
    Args:
        exchange: 交易所 (binance, okx)
        symbol: 交易对
        start: 开始时间
        end: 结束时间
        tf: 时间框架
        fmt: 返回格式
        data_dir: 数据目录
        
    Returns:
        DataFrame 或路径
        
    Example:
        >>> from src.data.fetcher import get_history
        >>> df = get_history("binance", "BTCUSDT", "2024-01-01", "2024-12-31", tf="1h")
        >>> print(df.head())
    """
    global _manager
    
    if _manager is None:
        _manager = DataManager(data_dir=data_dir)
    
    return _manager.get_history(exchange, symbol, start, end, tf, fmt)
