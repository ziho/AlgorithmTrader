"""
A 股基本面数据存储与读取

存储结构:
    data/parquet/a_tushare_fundamentals/
        daily_basic/year=2024/data.parquet
        adj_factor/year=2024/data.parquet
        forecast/year=2024/data.parquet
        fina_indicator/year=2024/data.parquet

特性:
- 按 API 名称和年份分区
- 支持 DuckDB 查询
- 保留原始列名
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from src.core.config import get_settings
from src.ops.logging import get_logger

logger = get_logger(__name__)

# 支持的基本面数据类型
FUNDAMENTAL_TYPES = [
    "daily_basic",
    "adj_factor",
    "forecast",
    "fina_indicator",
]


class AShareFundamentalsStore:
    """
    A 股基本面数据存储

    读写 Parquet 格式的基本面数据，按年份分区。
    """

    def __init__(self, base_path: Path | str | None = None) -> None:
        """
        初始化

        Args:
            base_path: 基本面数据根目录，默认为
                       data/parquet/a_tushare_fundamentals
        """
        settings = get_settings()
        if base_path:
            self.base_path = Path(base_path)
        else:
            self.base_path = (
                Path(settings.data_dir) / "parquet" / "a_tushare_fundamentals"
            )
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(":memory:")

    def _get_parquet_path(self, data_type: str, year: int) -> Path:
        """获取 Parquet 文件路径"""
        return self.base_path / data_type / f"year={year:04d}" / "data.parquet"

    def _get_data_dir(self, data_type: str) -> Path:
        """获取数据类型目录"""
        return self.base_path / data_type

    # ============================================
    # 写入
    # ============================================

    def write(
        self,
        data_type: str,
        df: pd.DataFrame,
        year: int | None = None,
    ) -> int:
        """
        写入基本面数据

        如果不指定 year，自动从 trade_date/ann_date 列推断。

        Args:
            data_type: 数据类型 ('daily_basic', 'adj_factor', ...)
            df: 数据 DataFrame
            year: 年份，不指定则按日期列自动拆分

        Returns:
            写入行数
        """
        if df.empty:
            return 0

        if data_type not in FUNDAMENTAL_TYPES:
            logger.warning(
                "unknown_fundamental_type",
                data_type=data_type,
                known_types=FUNDAMENTAL_TYPES,
            )

        total_rows = 0

        if year is not None:
            # 直接写入指定年份
            total_rows = self._write_year(data_type, df, year)
        else:
            # 自动按年份拆分
            date_col = self._get_date_column(df)
            if date_col is None:
                logger.warning(
                    "no_date_column_found",
                    data_type=data_type,
                    columns=list(df.columns),
                )
                # 默认写入当前年份
                total_rows = self._write_year(data_type, df, datetime.now().year)
            else:
                # 按年份分组写入
                df["_year"] = pd.to_datetime(df[date_col], format="%Y%m%d").dt.year
                for yr, group_df in df.groupby("_year"):
                    group_df = group_df.drop(columns=["_year"])
                    total_rows += self._write_year(data_type, group_df, int(yr))

        return total_rows

    def _write_year(self, data_type: str, df: pd.DataFrame, year: int) -> int:
        """写入某一年的数据（合并去重）"""
        path = self._get_parquet_path(data_type, year)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 合并已有数据
        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)

            # 去重
            dedup_keys = self._get_dedup_keys(data_type, df)
            if dedup_keys:
                df = df.drop_duplicates(subset=dedup_keys, keep="last")

        df.to_parquet(path, index=False)
        logger.debug(
            "fundamentals_written",
            data_type=data_type,
            year=year,
            rows=len(df),
        )
        return len(df)

    @staticmethod
    def _get_date_column(df: pd.DataFrame) -> str | None:
        """推断日期列名"""
        for col in ["trade_date", "ann_date", "end_date"]:
            if col in df.columns:
                return col
        return None

    @staticmethod
    def _get_dedup_keys(data_type: str, df: pd.DataFrame) -> list[str] | None:
        """根据数据类型获取去重键"""
        if "ts_code" in df.columns and "trade_date" in df.columns:
            return ["ts_code", "trade_date"]
        if "ts_code" in df.columns and "ann_date" in df.columns:
            return ["ts_code", "ann_date"]
        if "ts_code" in df.columns and "end_date" in df.columns:
            return ["ts_code", "end_date"]
        return None

    # ============================================
    # 读取
    # ============================================

    def read(
        self,
        data_type: str,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """
        读取基本面数据

        通过 DuckDB 查询 Parquet 文件，支持过滤。

        Args:
            data_type: 数据类型
            ts_code: 股票代码过滤
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            pd.DataFrame
        """
        data_dir = self._get_data_dir(data_type)
        if not data_dir.exists():
            return pd.DataFrame()

        # 查找所有 Parquet 文件
        parquet_files = list(data_dir.rglob("data.parquet"))
        if not parquet_files:
            return pd.DataFrame()

        # 使用 DuckDB 查询
        glob_pattern = str(data_dir / "**" / "data.parquet")
        query = f"SELECT * FROM read_parquet('{glob_pattern}', hive_partitioning=true)"

        conditions: list[str] = []
        if ts_code:
            conditions.append(f"ts_code = '{ts_code}'")
        if start_date:
            date_col = "trade_date"  # 默认
            conditions.append(f"{date_col} >= '{start_date}'")
        if end_date:
            date_col = "trade_date"
            conditions.append(f"{date_col} <= '{end_date}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        try:
            return self._conn.execute(query).fetchdf()
        except Exception as e:
            logger.error(
                "fundamentals_read_error",
                data_type=data_type,
                error=str(e),
            )
            return pd.DataFrame()

    def read_adj_factor(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """
        读取复权因子

        Returns:
            DataFrame with columns: ts_code, trade_date, adj_factor
        """
        return self.read(
            data_type="adj_factor",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    def read_daily_basic(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """读取每日指标"""
        return self.read(
            data_type="daily_basic",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    # ============================================
    # 统计
    # ============================================

    def get_stats(self) -> dict[str, Any]:
        """获取所有基本面数据统计"""
        stats: dict[str, Any] = {}

        for data_type in FUNDAMENTAL_TYPES:
            data_dir = self._get_data_dir(data_type)
            if not data_dir.exists():
                stats[data_type] = {"exists": False}
                continue

            files = list(data_dir.rglob("data.parquet"))
            size_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)
            years = sorted(
                [
                    d.parent.name.replace("year=", "")
                    for d in files
                    if "year=" in d.parent.name
                ]
            )

            stats[data_type] = {
                "exists": True,
                "file_count": len(files),
                "size_mb": round(size_mb, 2),
                "years": years,
            }

        return stats
