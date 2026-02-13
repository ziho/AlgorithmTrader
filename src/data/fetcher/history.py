"""
历史数据批量下载器

支持:
- Binance Public Data (data.binance.vision) 批量下载
- OKX API 历史数据拉取
- 断点续传
- 校验和验证
- 速率限制和重试
"""

import asyncio
import gzip
import hashlib
import io
import zipfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import aiohttp
import pandas as pd

from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.ops.logging import get_logger

from .checkpoint import CheckpointStore

logger = get_logger(__name__)

# Binance Public Data 基础 URL
BINANCE_DATA_VISION_URL = "https://data.binance.vision/data"

# 默认支持的交易对
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]


@dataclass
class DownloadStats:
    """下载统计"""

    total_months: int = 0
    completed_months: int = 0
    skipped_months: int = 0
    failed_months: int = 0
    total_rows: int = 0
    total_bytes: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def elapsed(self) -> timedelta:
        return datetime.now(UTC) - self.start_time

    @property
    def progress(self) -> float:
        if self.total_months == 0:
            return 0.0
        return (self.completed_months + self.skipped_months) / self.total_months * 100


@dataclass
class RetryConfig:
    """重试配置"""

    max_retries: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0

    def get_delay(self, attempt: int) -> float:
        """计算退避延迟"""
        delay = self.base_delay * (self.exponential_base**attempt)
        return min(delay, self.max_delay)


class HistoryFetcher:
    """
    历史数据批量下载器

    支持从 Binance Public Data 下载历史 K 线数据
    特性:
    - 月级/日级数据下载
    - 断点续传
    - 可选校验和验证
    - 速率限制
    """

    # Binance 时间框架映射
    BINANCE_TF_MAP = {
        "1m": "1m",
        "3m": "3m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "2h": "2h",
        "4h": "4h",
        "6h": "6h",
        "8h": "8h",
        "12h": "12h",
        "1d": "1d",
        "3d": "3d",
        "1w": "1w",
        "1M": "1mo",
    }

    def __init__(
        self,
        data_dir: Path | str = "./data",
        exchange: str = "binance",
        market_type: Literal["spot", "um", "cm"] = "spot",
        retry_config: RetryConfig | None = None,
        request_delay: float = 0.2,
        verify_checksum: bool = True,
        save_raw: bool = False,
    ):
        """
        初始化下载器

        Args:
            data_dir: 数据目录
            exchange: 交易所 (binance, okx)
            market_type: 市场类型 (spot=现货, um=U本位合约, cm=币本位合约)
            retry_config: 重试配置
            request_delay: 请求间隔（秒）
            verify_checksum: 是否验证校验和
            save_raw: 是否保存原始文件
        """
        self.data_dir = Path(data_dir)
        self.exchange = exchange.lower()
        self.market_type = market_type
        self.retry_config = retry_config or RetryConfig()
        self.request_delay = request_delay
        self.verify_checksum = verify_checksum
        self.save_raw = save_raw

        # 目录结构
        self.raw_dir = self.data_dir / "raw" / self.exchange
        self.parquet_dir = self.data_dir / "parquet"

        if self.save_raw:
            self.raw_dir.mkdir(parents=True, exist_ok=True)

        # 断点续传
        self.checkpoint = CheckpointStore(self.data_dir)

        # HTTP 会话
        self._session: aiohttp.ClientSession | None = None

        logger.info(
            "history_fetcher_initialized",
            exchange=self.exchange,
            market_type=self.market_type,
            data_dir=str(self.data_dir),
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=120, connect=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "HistoryFetcher":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    def _get_binance_base_path(self) -> str:
        """获取 Binance 数据路径前缀"""
        if self.market_type == "spot":
            return "spot/monthly/klines"
        elif self.market_type == "um":
            return "futures/um/monthly/klines"
        else:
            return "futures/cm/monthly/klines"

    async def _download_with_retry(
        self,
        url: str,
    ) -> tuple[bytes | None, int]:
        """
        带重试的下载

        Returns:
            (内容, HTTP状态码)
        """
        session = await self._get_session()
        last_error = None

        for attempt in range(self.retry_config.max_retries):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        return content, 200
                    elif response.status == 404:
                        return None, 404
                    else:
                        last_error = f"HTTP {response.status}"

            except TimeoutError:
                last_error = "Timeout"
            except aiohttp.ClientError as e:
                last_error = str(e)
            except Exception as e:
                last_error = str(e)

            # 等待重试
            if attempt < self.retry_config.max_retries - 1:
                delay = self.retry_config.get_delay(attempt)
                logger.warning(
                    "download_retry",
                    url=url,
                    attempt=attempt + 1,
                    delay=delay,
                    error=last_error,
                )
                await asyncio.sleep(delay)

        logger.error(
            "download_failed",
            url=url,
            attempts=self.retry_config.max_retries,
            last_error=last_error,
        )
        return None, 0

    async def _fetch_checksum(self, zip_url: str) -> str | None:
        """获取校验和文件"""
        checksum_url = zip_url + ".CHECKSUM"
        content, status = await self._download_with_retry(checksum_url)

        if content and status == 200:
            try:
                # 格式: hash  filename
                text = content.decode("utf-8").strip()
                return text.split()[0]
            except Exception:
                pass
        return None

    def _verify_checksum(self, content: bytes, expected: str) -> bool:
        """验证 SHA256 校验和"""
        actual = hashlib.sha256(content).hexdigest()
        return actual.lower() == expected.lower()

    def _parse_binance_klines(
        self, content: bytes, is_zip: bool = True
    ) -> pd.DataFrame:
        """解析 Binance K 线数据"""
        try:
            if is_zip:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    csv_name = zf.namelist()[0]
                    with zf.open(csv_name) as f:
                        # 使用 str dtype 避免 pandas 自动推断导致 nanosecond 溢出
                        df = pd.read_csv(f, header=None, dtype=str)
            else:
                # gzip 格式
                with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
                    df = pd.read_csv(gz, header=None, dtype=str)

            # Binance K 线格式: 可能 12 列(spot) 或更少
            # open_time, open, high, low, close, volume, close_time,
            # quote_volume, trades, taker_buy_base, taker_buy_quote, ignore
            expected_cols = [
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "trades",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ]
            # 只取前 N 列（部分 zip 列数不同）
            if len(df.columns) >= 6:
                df.columns = expected_cols[: len(df.columns)]
            else:
                logger.error("parse_klines_bad_columns", ncols=len(df.columns))
                return pd.DataFrame()

            # 转换类型 — 自动检测时间戳精度 (ms / us / s)
            ts_vals = pd.to_numeric(df["timestamp"], errors="coerce")
            df["timestamp"] = ts_vals
            df = df.dropna(subset=["timestamp"])
            if df.empty:
                return pd.DataFrame()

            sample_ts = df["timestamp"].iloc[0]
            if sample_ts > 1e15:  # 微秒 (16+ 位)
                ts_unit = "us"
            elif sample_ts > 1e12:  # 毫秒 (13 位)
                ts_unit = "ms"
            else:  # 秒 (10 位)
                ts_unit = "s"

            df["timestamp"] = pd.to_datetime(
                df["timestamp"], unit=ts_unit, utc=True, errors="coerce"
            )
            df = df.dropna(subset=["timestamp"])

            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

            return df[["timestamp", "open", "high", "low", "close", "volume"]]

        except Exception as e:
            logger.error("parse_klines_error", error=str(e))
            return pd.DataFrame()

    async def download_month(
        self,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        skip_existing: bool = True,
    ) -> tuple[pd.DataFrame, bool, int]:
        """
        下载单月数据

        Args:
            symbol: 交易对 (如 BTCUSDT)
            timeframe: 时间框架
            year: 年份
            month: 月份
            skip_existing: 是否跳过已完成的

        Returns:
            (DataFrame, is_new_download, file_size_bytes)
        """
        # 格式化
        symbol_upper = symbol.replace("/", "").upper()
        interval = self.BINANCE_TF_MAP.get(timeframe, timeframe)

        # 检查: 仅当 parquet 文件实际存在时才跳过
        if skip_existing and self.checkpoint.is_completed(
            self.exchange, symbol_upper, timeframe, year, month
        ):
            # 验证 parquet 文件确实存在
            from src.data.storage.parquet_store import ParquetStore

            _pq = ParquetStore(base_path=self.parquet_dir)
            if symbol_upper.endswith("USDT"):
                _base, _quote = symbol_upper[:-4], "USDT"
            elif symbol_upper.endswith("BUSD"):
                _base, _quote = symbol_upper[:-4], "BUSD"
            else:
                _base, _quote = symbol_upper[:-3], symbol_upper[-3:]
            _sym = Symbol(exchange=Exchange.BINANCE, base=_base, quote=_quote)
            _tf = Timeframe(timeframe)
            _path = _pq._get_partition_path(_sym, _tf, year, month)
            if (_path / "data.parquet").exists():
                logger.debug(
                    "month_skipped",
                    symbol=symbol_upper,
                    timeframe=timeframe,
                    year=year,
                    month=month,
                )
                return pd.DataFrame(), False, 0
            # Parquet 文件不存在 → 需要重新下载
            logger.info(
                "month_checkpoint_stale",
                symbol=symbol_upper,
                year=year,
                month=month,
                msg="checkpoint says completed but parquet missing, re-downloading",
            )
            self.checkpoint.mark_pending(
                self.exchange, symbol_upper, timeframe, year, month
            )

        # 构建 URL
        base_path = self._get_binance_base_path()
        filename = f"{symbol_upper}-{interval}-{year}-{month:02d}.zip"
        url = f"{BINANCE_DATA_VISION_URL}/{base_path}/{symbol_upper}/{interval}/{filename}"

        # 下载
        content, status = await self._download_with_retry(url)

        if status == 404:
            # 尝试日级别数据
            df = await self._download_daily_fallback(
                symbol_upper, interval, year, month, base_path
            )
            if df.empty:
                self.checkpoint.mark_failed(
                    self.exchange,
                    symbol_upper,
                    timeframe,
                    year,
                    month,
                    error_message="404 Not Found",
                )
                return pd.DataFrame(), False, 0
        elif content is None:
            self.checkpoint.mark_failed(
                self.exchange,
                symbol_upper,
                timeframe,
                year,
                month,
                error_message="Download failed",
            )
            return pd.DataFrame(), False, 0
        else:
            # 校验和验证
            if self.verify_checksum:
                expected_checksum = await self._fetch_checksum(url)
                if expected_checksum:
                    if not self._verify_checksum(content, expected_checksum):
                        logger.warning(
                            "checksum_mismatch",
                            symbol=symbol_upper,
                            year=year,
                            month=month,
                        )
                        # 继续处理但记录警告
                else:
                    logger.debug(
                        "checksum_not_available",
                        symbol=symbol_upper,
                        year=year,
                        month=month,
                    )

            # 保存原始文件
            if self.save_raw:
                raw_path = self.raw_dir / symbol_upper / interval / filename
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(content)

            # 解析（CPU/IO 密集，放到线程中避免阻塞事件循环）
            df = await asyncio.to_thread(self._parse_binance_klines, content)

        if not df.empty:
            logger.info(
                "month_downloaded",
                symbol=symbol_upper,
                timeframe=timeframe,
                year=year,
                month=month,
                rows=len(df),
            )

        await asyncio.sleep(self.request_delay)
        return df, True, len(content) if content else 0

    async def _download_daily_fallback(
        self,
        symbol: str,
        interval: str,
        year: int,
        month: int,
        base_path: str,
    ) -> pd.DataFrame:
        """日级别数据回退下载"""
        from calendar import monthrange

        all_data = []
        days_in_month = monthrange(year, month)[1]

        # 改用日级别路径
        daily_base = base_path.replace("/monthly/", "/daily/")

        for day in range(1, days_in_month + 1):
            # 检查日期是否超过当前
            date = datetime(year, month, day, tzinfo=UTC)
            if date > datetime.now(UTC):
                break

            filename = f"{symbol}-{interval}-{year}-{month:02d}-{day:02d}.zip"
            url = (
                f"{BINANCE_DATA_VISION_URL}/{daily_base}/{symbol}/{interval}/{filename}"
            )

            content, status = await self._download_with_retry(url)

            if content and status == 200:
                # 解析（CPU/IO 密集，放到线程中避免阻塞事件循环）
                df = await asyncio.to_thread(self._parse_binance_klines, content)
                if not df.empty:
                    all_data.append(df)

            await asyncio.sleep(self.request_delay / 2)

        if all_data:
            # 合并排序在后台线程中执行，减少事件循环阻塞
            def _merge_daily_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
                merged = pd.concat(frames, ignore_index=True)
                merged = merged.drop_duplicates(subset=["timestamp"])
                return merged.sort_values("timestamp").reset_index(drop=True)

            return await asyncio.to_thread(_merge_daily_frames, all_data)

        return pd.DataFrame()

    async def download_range(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        skip_existing: bool = True,
        progress_callback: Callable | None = None,
    ) -> AsyncIterator[tuple[int, int, pd.DataFrame]]:
        """
        下载日期范围内的数据

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start_date: 开始日期
            end_date: 结束日期
            skip_existing: 是否跳过已完成
            progress_callback: 进度回调 (completed, total, stats)

        Yields:
            (year, month, DataFrame)
        """
        symbol_upper = symbol.replace("/", "").upper()

        # 计算需要下载的月份
        start_year, start_month = start_date.year, start_date.month
        end_year, end_month = end_date.year, end_date.month

        # 获取待下载列表
        if skip_existing:
            pending = self.checkpoint.get_pending_periods(
                self.exchange,
                symbol_upper,
                timeframe,
                start_year,
                start_month,
                end_year,
                end_month,
            )
        else:
            # 生成所有月份
            pending = []
            y, m = start_year, start_month
            while (y, m) <= (end_year, end_month):
                pending.append((y, m))
                if m == 12:
                    y += 1
                    m = 1
                else:
                    m += 1

        total = len(pending)
        completed = 0

        logger.info(
            "download_range_start",
            symbol=symbol_upper,
            timeframe=timeframe,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            pending_months=total,
        )

        for year, month in pending:
            df, is_new, _fsize = await self.download_month(
                symbol_upper, timeframe, year, month, skip_existing=False
            )
            completed += 1

            if progress_callback:
                progress_callback(completed, total, None)

            if not df.empty:
                yield year, month, df

        logger.info(
            "download_range_complete",
            symbol=symbol_upper,
            timeframe=timeframe,
            completed_months=completed,
        )

    async def download_and_save(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        skip_existing: bool = True,
        progress_callback: Callable | None = None,
    ) -> DownloadStats:
        """
        下载并保存到 Parquet

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start_date: 开始日期
            end_date: 结束日期
            skip_existing: 是否跳过已完成

        Returns:
            下载统计
        """
        from src.data.storage.parquet_store import ParquetStore

        symbol_upper = symbol.replace("/", "").upper()

        # 解析为 Symbol 对象
        if symbol_upper.endswith("USDT"):
            base = symbol_upper[:-4]
            quote = "USDT"
        elif symbol_upper.endswith("BUSD"):
            base = symbol_upper[:-4]
            quote = "BUSD"
        else:
            base = symbol_upper[:-3]
            quote = symbol_upper[-3:]

        sym = Symbol(exchange=Exchange.BINANCE, base=base, quote=quote)
        tf = Timeframe(timeframe)

        # Parquet 存储
        store = ParquetStore(base_path=self.parquet_dir)

        stats = DownloadStats()

        # 计算总月份数
        y, m = start_date.year, start_date.month
        while (y, m) <= (end_date.year, end_date.month):
            stats.total_months += 1
            if m == 12:
                y += 1
                m = 1
            else:
                m += 1

        async for year, month, df in self.download_range(
            symbol_upper,
            timeframe,
            start_date,
            end_date,
            skip_existing,
            progress_callback=progress_callback,
        ):
            if df.empty:
                stats.failed_months += 1
                continue

            # 过滤时间范围 - 确保时间戳比较正确
            start_ts = (
                pd.Timestamp(start_date).tz_convert("UTC")
                if start_date.tzinfo
                else pd.Timestamp(start_date).tz_localize("UTC")
            )
            end_ts = (
                pd.Timestamp(end_date).tz_convert("UTC")
                if end_date.tzinfo
                else pd.Timestamp(end_date).tz_localize("UTC")
            )
            df = df[(df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)]

            if not df.empty:
                # 写入 Parquet（CPU/IO 密集，放到线程中避免阻塞事件循环）
                rows = await asyncio.to_thread(store.write, sym, tf, df)
                stats.total_rows += rows
                stats.completed_months += 1

                # Parquet 写入成功后才标记 checkpoint 完成
                self.checkpoint.mark_completed(
                    self.exchange,
                    symbol_upper,
                    timeframe,
                    year,
                    month,
                    rows_count=len(df),
                    file_size=0,
                )

                # 更新元数据
                self.checkpoint.update_metadata(
                    self.exchange,
                    symbol_upper,
                    timeframe,
                    earliest_date=df["timestamp"].min().to_pydatetime(),
                    latest_date=df["timestamp"].max().to_pydatetime(),
                    total_rows=len(df),
                )

        # 统计跳过的
        stats.skipped_months = (
            stats.total_months - stats.completed_months - stats.failed_months
        )

        logger.info(
            "download_and_save_complete",
            symbol=symbol_upper,
            timeframe=timeframe,
            stats={
                "total": stats.total_months,
                "completed": stats.completed_months,
                "skipped": stats.skipped_months,
                "failed": stats.failed_months,
                "total_rows": stats.total_rows,
                "elapsed": str(stats.elapsed),
            },
        )

        return stats

    async def download_multiple(
        self,
        symbols: list[str],
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        skip_existing: bool = True,
        concurrency: int = 1,
    ) -> dict[str, DownloadStats]:
        """
        下载多个交易对

        Args:
            symbols: 交易对列表
            timeframe: 时间框架
            start_date: 开始日期
            end_date: 结束日期
            skip_existing: 是否跳过已完成
            concurrency: 并发数 (建议为 1 以遵守速率限制)

        Returns:
            {symbol: DownloadStats}
        """
        results = {}

        # 串行下载以遵守速率限制
        for symbol in symbols:
            logger.info(
                "downloading_symbol",
                symbol=symbol,
                timeframe=timeframe,
            )

            stats = await self.download_and_save(
                symbol, timeframe, start_date, end_date, skip_existing
            )
            results[symbol] = stats

            # 交易对之间的间隔
            await asyncio.sleep(1.0)

        return results
