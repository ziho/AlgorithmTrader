"""
Tushare A 股历史数据批量下载器

支持:
- 全市场日线 OHLCV 一次性回填（2018-01-01 至今）
- 基本面数据（daily_basic, adj_factor, forecast, fina_indicator）
- 断点续传（复用 CheckpointStore）
- 限速控制与重试
- 进度回调

策略:
- 以交易日为粒度循环下载全市场数据
- 每个交易日一次 API 调用拉取全市场
- 数据按 ts_code 拆分后存入 ParquetStore
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.config.settings import get_settings
from src.core.timeframes import Timeframe
from src.data.connectors.tushare import TushareConnector
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import get_logger

from .checkpoint import CheckpointStore

logger = get_logger(__name__)


@dataclass
class TushareDownloadStats:
    """下载统计"""

    total_days: int = 0
    completed_days: int = 0
    skipped_days: int = 0
    failed_days: int = 0
    total_rows: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(UTC) - self.start_time).total_seconds()

    @property
    def progress(self) -> float:
        if self.total_days == 0:
            return 0.0
        return (self.completed_days + self.skipped_days) / self.total_days * 100

    @property
    def eta_seconds(self) -> float | None:
        """预计剩余时间"""
        done = self.completed_days + self.skipped_days
        if done == 0:
            return None
        remaining = self.total_days - done
        rate = self.elapsed_seconds / done
        return remaining * rate


# 回调类型
ProgressCallback = Callable[[TushareDownloadStats], Any]


class TushareHistoryFetcher:
    """
    Tushare A 股历史数据批量下载器

    以交易日为粒度，逐日拉取全市场日线数据并存储到 ParquetStore。
    支持断点续传，使用 CheckpointStore 记录进度。
    """

    def __init__(
        self,
        data_dir: Path | str | None = None,
        token: str | None = None,
    ) -> None:
        """
        初始化

        Args:
            data_dir: 数据目录，默认从配置读取
            token: Tushare token，默认从配置读取
        """
        settings = get_settings()
        self._data_dir = Path(data_dir) if data_dir else settings.data_dir

        self._connector = TushareConnector(token=token)
        self._store = ParquetStore(self._data_dir / "parquet")
        self._checkpoint = CheckpointStore(self._data_dir)

        self._stats = TushareDownloadStats()
        self._progress_callback: ProgressCallback | None = None
        self._cancelled = False

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """设置进度回调"""
        self._progress_callback = callback

    def cancel(self) -> None:
        """取消下载"""
        self._cancelled = True

    @property
    def stats(self) -> TushareDownloadStats:
        return self._stats

    # ============================================
    # 日线 OHLCV 回填
    # ============================================

    async def backfill_daily(
        self,
        start_date: str = "20180101",
        end_date: str | None = None,
    ) -> TushareDownloadStats:
        """
        全市场日线 OHLCV 回填

        以交易日为粒度，逐日下载全市场日线数据，
        按 ts_code 拆分后存入 ParquetStore。

        Args:
            start_date: 起始日期 YYYYMMDD，默认 20180101
            end_date: 结束日期 YYYYMMDD，默认今天

        Returns:
            下载统计
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        self._stats = TushareDownloadStats()
        self._cancelled = False

        logger.info(
            "tushare_backfill_start",
            start_date=start_date,
            end_date=end_date,
        )

        # 1. 获取交易日历
        trade_dates = await self._connector.fetch_trade_calendar(
            start_date=start_date,
            end_date=end_date,
        )

        if not trade_dates:
            logger.warning("tushare_no_trade_dates", start=start_date, end=end_date)
            return self._stats

        self._stats.total_days = len(trade_dates)
        logger.info(
            "tushare_trade_dates_loaded",
            total_days=self._stats.total_days,
            first=trade_dates[0],
            last=trade_dates[-1],
        )

        # 2. 逐交易日下载
        for trade_date in trade_dates:
            if self._cancelled:
                logger.info("tushare_backfill_cancelled")
                break

            # 检查是否已完成（断点续传）
            # 用 year/month/day 作为 checkpoint key
            dt = datetime.strptime(trade_date, "%Y%m%d")
            if self._checkpoint.is_completed(
                exchange="a_tushare",
                symbol="__ALL__",
                timeframe="1d",
                year=dt.year,
                month=dt.month,
                day=dt.day,
            ):
                self._stats.skipped_days += 1
                self._notify_progress()
                continue

            # 下载并存储
            try:
                rows = await self._download_and_store_daily(trade_date)
                self._stats.completed_days += 1
                self._stats.total_rows += rows

                # 标记完成
                self._checkpoint.mark_completed(
                    exchange="a_tushare",
                    symbol="__ALL__",
                    timeframe="1d",
                    year=dt.year,
                    month=dt.month,
                    day=dt.day,
                    rows_count=rows,
                )

                if self._stats.completed_days % 50 == 0:
                    logger.info(
                        "tushare_backfill_progress",
                        completed=self._stats.completed_days,
                        skipped=self._stats.skipped_days,
                        total=self._stats.total_days,
                        progress=f"{self._stats.progress:.1f}%",
                        total_rows=self._stats.total_rows,
                    )

            except Exception as e:
                self._stats.failed_days += 1
                self._checkpoint.mark_failed(
                    exchange="a_tushare",
                    symbol="__ALL__",
                    timeframe="1d",
                    year=dt.year,
                    month=dt.month,
                    day=dt.day,
                    error_message=str(e),
                )
                logger.error(
                    "tushare_daily_download_error",
                    trade_date=trade_date,
                    error=str(e),
                )

            self._notify_progress()

        logger.info(
            "tushare_backfill_complete",
            completed=self._stats.completed_days,
            skipped=self._stats.skipped_days,
            failed=self._stats.failed_days,
            total_rows=self._stats.total_rows,
            elapsed_seconds=self._stats.elapsed_seconds,
        )

        return self._stats

    async def _download_and_store_daily(self, trade_date: str) -> int:
        """
        下载某一交易日的全市场日线数据并存储

        Args:
            trade_date: 交易日 YYYYMMDD

        Returns:
            存储的总行数
        """
        # 拉取全市场日线
        df = await self._connector.fetch_daily_as_ohlcv(trade_date=trade_date)
        if df.empty:
            return 0

        total_rows = 0

        # 按 ts_code 拆分并存储
        if "ts_code" not in df.columns:
            logger.warning("tushare_no_ts_code_column", trade_date=trade_date)
            return 0

        for ts_code, group_df in df.groupby("ts_code"):
            symbol = TushareConnector.ts_code_to_symbol(str(ts_code))

            # 移除 ts_code 列后写入 ParquetStore
            ohlcv_df = group_df.drop(
                columns=["ts_code", "pre_close"],
                errors="ignore",
            )

            rows = self._store.write(
                symbol=symbol,
                timeframe=Timeframe.D1,
                df=ohlcv_df,
                deduplicate=True,
            )
            total_rows += rows

        return total_rows

    # ============================================
    # 基本面数据回填
    # ============================================

    async def backfill_daily_basic(
        self,
        start_date: str = "20180101",
        end_date: str | None = None,
    ) -> TushareDownloadStats:
        """
        回填每日基本面指标（daily_basic）

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            下载统计
        """
        return await self._backfill_by_date(
            api_name="daily_basic",
            start_date=start_date,
            end_date=end_date,
        )

    async def backfill_adj_factor(
        self,
        start_date: str = "20180101",
        end_date: str | None = None,
    ) -> TushareDownloadStats:
        """
        回填复权因子（adj_factor）

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            下载统计
        """
        return await self._backfill_by_date(
            api_name="adj_factor",
            start_date=start_date,
            end_date=end_date,
        )

    async def _backfill_by_date(
        self,
        api_name: str,
        start_date: str = "20180101",
        end_date: str | None = None,
    ) -> TushareDownloadStats:
        """
        按交易日回填基本面数据的通用逻辑

        数据存储到 data/parquet/a_tushare_fundamentals/{api_name}/year=YYYY/data.parquet

        Args:
            api_name: Tushare API 名称 ('daily_basic', 'adj_factor')
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            下载统计
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        self._stats = TushareDownloadStats()
        self._cancelled = False

        # 获取交易日历
        trade_dates = await self._connector.fetch_trade_calendar(
            start_date=start_date,
            end_date=end_date,
        )
        self._stats.total_days = len(trade_dates)

        logger.info(
            f"tushare_{api_name}_backfill_start",
            total_days=self._stats.total_days,
        )

        # 基本面数据存储目录
        fundamentals_dir = self._data_dir / "parquet" / "a_tushare_fundamentals"

        # 按交易日逐日下载
        accumulated_rows: list[pd.DataFrame] = []
        current_year: int | None = None

        for trade_date in trade_dates:
            if self._cancelled:
                break

            dt = datetime.strptime(trade_date, "%Y%m%d")

            # 检查断点
            if self._checkpoint.is_completed(
                exchange="a_tushare",
                symbol="__ALL__",
                timeframe=api_name,
                year=dt.year,
                month=dt.month,
                day=dt.day,
            ):
                self._stats.skipped_days += 1
                self._notify_progress()
                continue

            try:
                # 调用 API
                df = await self._connector._call_api(api_name, trade_date=trade_date)

                if not df.empty:
                    accumulated_rows.append(df)
                    self._stats.total_rows += len(df)

                # 年度切换时写入文件
                if current_year is not None and dt.year != current_year:
                    self._flush_fundamentals(
                        accumulated_rows, fundamentals_dir, api_name, current_year
                    )
                    accumulated_rows = []

                current_year = dt.year
                self._stats.completed_days += 1

                # 标记完成
                self._checkpoint.mark_completed(
                    exchange="a_tushare",
                    symbol="__ALL__",
                    timeframe=api_name,
                    year=dt.year,
                    month=dt.month,
                    day=dt.day,
                    rows_count=len(df) if not df.empty else 0,
                )

            except Exception as e:
                self._stats.failed_days += 1
                self._checkpoint.mark_failed(
                    exchange="a_tushare",
                    symbol="__ALL__",
                    timeframe=api_name,
                    year=dt.year,
                    month=dt.month,
                    day=dt.day,
                    error_message=str(e),
                )
                logger.error(
                    f"tushare_{api_name}_error",
                    trade_date=trade_date,
                    error=str(e),
                )

            self._notify_progress()

        # 刷写剩余数据
        if accumulated_rows and current_year is not None:
            self._flush_fundamentals(
                accumulated_rows, fundamentals_dir, api_name, current_year
            )

        logger.info(
            f"tushare_{api_name}_backfill_complete",
            completed=self._stats.completed_days,
            skipped=self._stats.skipped_days,
            failed=self._stats.failed_days,
            total_rows=self._stats.total_rows,
        )

        return self._stats

    def _flush_fundamentals(
        self,
        dfs: list[pd.DataFrame],
        base_dir: Path,
        api_name: str,
        year: int,
    ) -> None:
        """将积累的基本面数据写入 Parquet 文件"""
        if not dfs:
            return

        combined = pd.concat(dfs, ignore_index=True)
        if combined.empty:
            return

        # 写入路径: a_tushare_fundamentals/{api_name}/year={YYYY}/data.parquet
        output_dir = base_dir / api_name / f"year={year:04d}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "data.parquet"

        # 如果已存在，合并去重
        if output_path.exists():
            existing = pd.read_parquet(output_path)
            combined = pd.concat([existing, combined], ignore_index=True)

            # 根据 API 类型选择去重键
            if "trade_date" in combined.columns and "ts_code" in combined.columns:
                combined = combined.drop_duplicates(
                    subset=["ts_code", "trade_date"], keep="last"
                )
            elif "ann_date" in combined.columns and "ts_code" in combined.columns:
                combined = combined.drop_duplicates(
                    subset=["ts_code", "ann_date"], keep="last"
                )

        combined.to_parquet(output_path, index=False)
        logger.debug(
            "fundamentals_flushed",
            api_name=api_name,
            year=year,
            rows=len(combined),
            path=str(output_path),
        )

    # ============================================
    # 单股票数据下载
    # ============================================

    async def download_stock_daily(
        self,
        ts_code: str,
        start_date: str = "20180101",
        end_date: str | None = None,
    ) -> int:
        """
        下载单个股票的日线数据

        Args:
            ts_code: 股票代码，如 '600519.SH'
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            存储行数
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        df = await self._connector.fetch_daily_as_ohlcv(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        if df.empty:
            return 0

        symbol = TushareConnector.ts_code_to_symbol(ts_code)

        # 移除非 OHLCV 列
        ohlcv_df = df.drop(columns=["ts_code", "pre_close"], errors="ignore")

        rows = self._store.write(
            symbol=symbol,
            timeframe=Timeframe.D1,
            df=ohlcv_df,
            deduplicate=True,
        )

        logger.info(
            "tushare_stock_download_complete",
            ts_code=ts_code,
            rows=rows,
            start=start_date,
            end=end_date,
        )

        return rows

    # ============================================
    # 数据统计
    # ============================================

    def get_local_stats(self) -> dict[str, Any]:
        """
        获取本地 A 股数据统计

        Returns:
            dict with keys: stock_count, date_range, file_count, total_size_mb
        """
        a_share_dir = self._data_dir / "parquet" / "a_tushare"
        fundamentals_dir = self._data_dir / "parquet" / "a_tushare_fundamentals"

        stats: dict[str, Any] = {
            "stock_count": 0,
            "file_count": 0,
            "total_size_mb": 0.0,
            "date_range": None,
            "fundamentals": {},
        }

        # OHLCV 数据统计
        if a_share_dir.exists():
            # 统计 symbol 目录数
            symbol_dirs = [
                d
                for d in a_share_dir.iterdir()
                if d.is_dir() and d.name != "__pycache__"
            ]
            stats["stock_count"] = len(symbol_dirs)

            # 统计文件
            parquet_files = list(a_share_dir.rglob("data.parquet"))
            stats["file_count"] = len(parquet_files)
            stats["total_size_mb"] = sum(f.stat().st_size for f in parquet_files) / (
                1024 * 1024
            )

        # 基本面数据统计
        if fundamentals_dir.exists():
            for api_dir in fundamentals_dir.iterdir():
                if api_dir.is_dir():
                    files = list(api_dir.rglob("data.parquet"))
                    size_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)
                    stats["fundamentals"][api_dir.name] = {
                        "file_count": len(files),
                        "size_mb": round(size_mb, 2),
                    }

        return stats

    def _notify_progress(self) -> None:
        """通知进度回调"""
        if self._progress_callback:
            try:
                self._progress_callback(self._stats)
            except Exception:
                pass

    async def close(self) -> None:
        """关闭资源"""
        await self._connector.close()

    async def __aenter__(self) -> "TushareHistoryFetcher":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
