"""
Parquet Store - 历史 OHLCV 数据存储

分区规则: data/parquet/{exchange}/{symbol_base}_{symbol_quote}/{timeframe}/year={YYYY}/month={MM}/data.parquet

特性:
- 按交易所/品种/时间框架/年月分区
- DuckDB 直接查询 Parquet 文件
- 支持数据追加和去重
- 缺口检测
"""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from src.core.config import get_settings
from src.core.instruments import Symbol
from src.core.timeframes import Timeframe
from src.ops.logging import get_logger

logger = get_logger(__name__)


class ParquetStore:
    """Parquet 历史数据存储"""

    # Parquet schema 定义
    OHLCV_SCHEMA = pa.schema(
        [
            ("timestamp", pa.timestamp("us", tz="UTC")),
            ("open", pa.float64()),
            ("high", pa.float64()),
            ("low", pa.float64()),
            ("close", pa.float64()),
            ("volume", pa.float64()),
        ]
    )

    def __init__(self, base_path: Path | str | None = None):
        """
        初始化 Parquet Store

        Args:
            base_path: 数据存储根目录，默认使用配置中的路径
        """
        settings = get_settings()
        self.base_path = (
            Path(base_path) if base_path else Path(settings.data_dir) / "parquet"
        )
        self.base_path.mkdir(parents=True, exist_ok=True)

        # DuckDB 内存连接（用于查询）
        self._conn = duckdb.connect(":memory:")

        logger.info(
            "parquet_store_initialized",
            base_path=str(self.base_path),
        )

    def _get_partition_path(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        year: int,
        month: int,
    ) -> Path:
        """
        获取分区目录路径

        分区规则: {base}/{exchange}/{base}_{quote}/{timeframe}/year={YYYY}/month={MM}/
        """
        return (
            self.base_path
            / symbol.exchange.value.lower()
            / f"{symbol.base}_{symbol.quote}".upper()
            / timeframe.value
            / f"year={year:04d}"
            / f"month={month:02d}"
        )

    def _get_parquet_path(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        year: int,
        month: int,
    ) -> Path:
        """获取 Parquet 文件路径"""
        partition_dir = self._get_partition_path(symbol, timeframe, year, month)
        return partition_dir / "data.parquet"

    def write(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        df: pd.DataFrame,
        deduplicate: bool = True,
    ) -> int:
        """
        写入 OHLCV 数据到 Parquet

        Args:
            symbol: 交易对
            timeframe: 时间框架
            df: 包含 OHLCV 数据的 DataFrame，必须有 timestamp 列
            deduplicate: 是否对相同时间戳去重（保留新数据）

        Returns:
            写入的行数
        """
        if df.empty:
            logger.warning("write_empty_dataframe", symbol=str(symbol))
            return 0

        # 确保 timestamp 列存在且为 UTC
        if "timestamp" not in df.columns:
            raise ValueError("DataFrame must have 'timestamp' column")

        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        # 确保数值列是 float 类型 (处理 Decimal)
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(float)

        # 按年月分组写入
        df["_year"] = df["timestamp"].dt.year
        df["_month"] = df["timestamp"].dt.month

        total_written = 0

        for (year, month), group_df in df.groupby(["_year", "_month"]):
            year = int(year)
            month = int(month)

            # 删除临时列
            write_df = group_df.drop(columns=["_year", "_month"])

            parquet_path = self._get_parquet_path(symbol, timeframe, year, month)
            parquet_path.parent.mkdir(parents=True, exist_ok=True)

            if parquet_path.exists() and deduplicate:
                # 读取现有数据
                existing_df = pd.read_parquet(parquet_path)

                # 合并并去重（保留新数据）
                combined_df = pd.concat([existing_df, write_df], ignore_index=True)
                combined_df = combined_df.drop_duplicates(
                    subset=["timestamp"],
                    keep="last",
                )
                combined_df = combined_df.sort_values("timestamp").reset_index(
                    drop=True
                )

                rows_written = len(combined_df) - len(existing_df)
            else:
                combined_df = write_df.sort_values("timestamp").reset_index(drop=True)
                rows_written = len(combined_df)

            # 写入 Parquet
            table = pa.Table.from_pandas(combined_df, schema=self.OHLCV_SCHEMA)
            pq.write_table(table, parquet_path, compression="snappy")

            total_written += rows_written

            logger.debug(
                "parquet_partition_written",
                symbol=str(symbol),
                timeframe=timeframe.value,
                year=year,
                month=month,
                rows=rows_written,
            )

        logger.info(
            "parquet_write_complete",
            symbol=str(symbol),
            timeframe=timeframe.value,
            total_rows=total_written,
        )

        return total_written

    def read(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """
        读取 OHLCV 数据

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start: 开始时间（包含）
            end: 结束时间（包含）

        Returns:
            OHLCV DataFrame
        """
        # 构建目录路径模式
        pattern_path = (
            self.base_path
            / symbol.exchange.value.lower()
            / f"{symbol.base}_{symbol.quote}".upper()
            / timeframe.value
        )

        if not pattern_path.exists():
            logger.debug(
                "parquet_path_not_found",
                path=str(pattern_path),
            )
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        # 使用 DuckDB 查询（支持 Hive 分区）
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM read_parquet('{pattern_path}/**/data.parquet', hive_partitioning=true)
        """

        conditions = []
        if start:
            start_utc = (
                start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
            )
            conditions.append(f"timestamp >= '{start_utc.isoformat()}'")
        if end:
            end_utc = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
            conditions.append(f"timestamp <= '{end_utc.isoformat()}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp"

        try:
            df = self._conn.execute(query).fetchdf()

            logger.debug(
                "parquet_read_complete",
                symbol=str(symbol),
                timeframe=timeframe.value,
                rows=len(df),
            )

            return df
        except duckdb.IOException:
            # 没有匹配的文件
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

    def read_polars(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """
        使用 Polars 读取 OHLCV 数据（更高性能）

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start: 开始时间（包含）
            end: 结束时间（包含）

        Returns:
            Polars OHLCV DataFrame
        """
        pattern_path = (
            self.base_path
            / symbol.exchange.value.lower()
            / f"{symbol.base}_{symbol.quote}".upper()
            / timeframe.value
        )

        if not pattern_path.exists():
            return pl.DataFrame(
                schema={
                    "timestamp": pl.Datetime("us", "UTC"),
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                }
            )

        try:
            # 扫描所有 parquet 文件
            lf = pl.scan_parquet(str(pattern_path / "**" / "data.parquet"))

            # 应用过滤条件
            if start:
                start_utc = (
                    start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
                )
                lf = lf.filter(pl.col("timestamp") >= start_utc)
            if end:
                end_utc = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
                lf = lf.filter(pl.col("timestamp") <= end_utc)

            # 排序并收集
            df = lf.sort("timestamp").collect()

            return df
        except Exception:
            return pl.DataFrame(
                schema={
                    "timestamp": pl.Datetime("us", "UTC"),
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                }
            )

    def detect_gaps(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[tuple[datetime, datetime]]:
        """
        检测数据缺口

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start: 开始时间
            end: 结束时间

        Returns:
            缺口列表，每个元素为 (缺口开始时间, 缺口结束时间)
        """
        df = self.read(symbol, timeframe, start, end)

        if df.empty or len(df) < 2:
            return []

        gaps = []
        expected_delta = timeframe.timedelta

        for i in range(1, len(df)):
            prev_ts = df.iloc[i - 1]["timestamp"]
            curr_ts = df.iloc[i]["timestamp"]
            actual_delta = curr_ts - prev_ts

            # 如果实际间隔大于预期间隔的 1.5 倍，认为是缺口
            if actual_delta > expected_delta * 1.5:
                gap_start = prev_ts + expected_delta
                gap_end = curr_ts - expected_delta
                gaps.append(
                    (
                        gap_start.to_pydatetime(),
                        gap_end.to_pydatetime(),
                    )
                )

        if gaps:
            logger.warning(
                "data_gaps_detected",
                symbol=str(symbol),
                timeframe=timeframe.value,
                gap_count=len(gaps),
            )

        return gaps

    def get_data_range(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
    ) -> tuple[datetime, datetime] | None:
        """
        获取数据的时间范围

        Args:
            symbol: 交易对
            timeframe: 时间框架

        Returns:
            (最早时间, 最晚时间) 或 None
        """
        pattern_path = (
            self.base_path
            / symbol.exchange.value.lower()
            / f"{symbol.base}_{symbol.quote}".upper()
            / timeframe.value
        )

        if not pattern_path.exists():
            return None

        try:
            # 使用 Polars 获取时间范围，避免 DuckDB 的 pytz 依赖
            lf = pl.scan_parquet(str(pattern_path / "**" / "data.parquet"))
            result = lf.select(
                [
                    pl.col("timestamp").min().alias("min_ts"),
                    pl.col("timestamp").max().alias("max_ts"),
                ]
            ).collect()

            if len(result) > 0:
                min_ts = result["min_ts"][0]
                max_ts = result["max_ts"][0]
                if min_ts and max_ts:
                    # 转换为 Python datetime
                    return (min_ts.replace(tzinfo=UTC), max_ts.replace(tzinfo=UTC))
            return None
        except Exception:
            return None

    def list_symbols(self, exchange: str | None = None) -> list[Symbol]:
        """
        列出存储的所有交易对

        Args:
            exchange: 可选，过滤特定交易所

        Returns:
            Symbol 列表
        """
        symbols = []

        search_path = self.base_path
        if exchange:
            search_path = search_path / exchange.lower()

        if not search_path.exists():
            return symbols

        for exchange_dir in search_path.iterdir():
            if not exchange_dir.is_dir():
                continue

            exchange_name = exchange_dir.name.upper()

            for symbol_dir in exchange_dir.iterdir():
                if not symbol_dir.is_dir():
                    continue

                # 解析 BASE_QUOTE 格式
                parts = symbol_dir.name.split("_")
                if len(parts) == 2:
                    try:
                        symbol = Symbol.from_internal(
                            f"{exchange_name}:{parts[0]}/{parts[1]}"
                        )
                        symbols.append(symbol)
                    except ValueError:
                        continue

        return symbols

    def delete(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> bool:
        """
        删除数据

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start: 开始时间（如果不指定，删除所有）
            end: 结束时间

        Returns:
            是否成功
        """
        import shutil

        pattern_path = (
            self.base_path
            / symbol.exchange.value.lower()
            / f"{symbol.base}_{symbol.quote}".upper()
            / timeframe.value
        )

        if not pattern_path.exists():
            return False

        if start is None and end is None:
            # 删除整个目录
            shutil.rmtree(pattern_path)
            logger.info(
                "parquet_data_deleted",
                symbol=str(symbol),
                timeframe=timeframe.value,
            )
            return True

        # 需要按时间过滤删除，读取-过滤-重写
        df = self.read(symbol, timeframe)

        if df.empty:
            return False

        mask = pd.Series([True] * len(df))
        if start:
            start_utc = (
                start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
            )
            mask &= df["timestamp"] < start_utc
        if end:
            end_utc = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
            mask |= df["timestamp"] > end_utc

        filtered_df = df[mask]

        # 删除并重写
        shutil.rmtree(pattern_path)

        if not filtered_df.empty:
            self.write(symbol, timeframe, filtered_df, deduplicate=False)

        return True

    def close(self):
        """关闭 DuckDB 连接"""
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
