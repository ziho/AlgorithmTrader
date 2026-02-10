"""
Binance 数据连接器

支持两种数据源:
1. Binance API (实时数据)
2. Binance Public Data (历史数据下载: https://data.binance.vision/)

特点:
- 无需 API Key 获取公开数据
- 支持下载历史 Kline 数据 (日/月级别)
- 支持实时 WebSocket 数据流
"""

import asyncio
import io
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import aiohttp
import pandas as pd

from src.core.instruments import Symbol
from src.core.timeframes import Timeframe
from src.ops.logging import get_logger

logger = get_logger(__name__)


# Binance Public Data 基础 URL
BINANCE_DATA_VISION_URL = "https://data.binance.vision/data"

# Timeframe 映射
BINANCE_TIMEFRAME_MAP = {
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


class BinanceConnector:
    """
    Binance 交易所数据连接器

    支持:
    - 公开数据: OHLCV K线 (无需 API key)
    - 历史数据下载: 从 data.binance.vision 批量下载
    """

    # Binance API 基础 URL
    BASE_URL = "https://api.binance.com"

    def __init__(self) -> None:
        """初始化连接器"""
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """关闭连接"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "BinanceConnector":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ============================================
    # 实时 API 数据
    # ============================================

    async def fetch_ohlcv(
        self,
        symbol: Symbol | str,
        timeframe: Timeframe | str,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        从 Binance API 拉取 K 线数据

        Args:
            symbol: 交易对 (如 BTC/USDT)
            timeframe: 时间框架
            since: 开始时间
            limit: 数量限制 (最大 1000)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        session = await self._get_session()

        # 转换 symbol
        if isinstance(symbol, Symbol):
            binance_symbol = f"{symbol.base}{symbol.quote}"
        else:
            binance_symbol = symbol.replace("/", "")

        # 转换 timeframe
        if isinstance(timeframe, Timeframe):
            interval = BINANCE_TIMEFRAME_MAP.get(timeframe.value, "1h")
        else:
            interval = BINANCE_TIMEFRAME_MAP.get(timeframe, "1h")

        # 构建请求参数
        params: dict[str, Any] = {
            "symbol": binance_symbol,
            "interval": interval,
            "limit": min(limit, 1000),
        }

        if since:
            params["startTime"] = int(since.timestamp() * 1000)

        # 发送请求
        url = f"{self.BASE_URL}/api/v3/klines"

        async with session.get(url, params=params) as response:
            response.raise_for_status()
            data = await response.json()

        if not data:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        # 解析数据
        df = pd.DataFrame(
            data,
            columns=[
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
            ],
        )

        # 转换类型
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].apply(lambda x: Decimal(str(x)))

        return df[["timestamp", "open", "high", "low", "close", "volume"]]

    async def fetch_ticker(self, symbol: Symbol | str) -> dict[str, Any]:
        """拉取最新行情"""
        session = await self._get_session()

        if isinstance(symbol, Symbol):
            binance_symbol = f"{symbol.base}{symbol.quote}"
        else:
            binance_symbol = symbol.replace("/", "")

        url = f"{self.BASE_URL}/api/v3/ticker/24hr"
        params = {"symbol": binance_symbol}

        async with session.get(url, params=params) as response:
            response.raise_for_status()
            return await response.json()

    # ============================================
    # 历史数据下载 (data.binance.vision)
    # ============================================

    async def download_historical_klines(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        market_type: Literal["spot", "um", "cm"] = "spot",
        output_dir: Path | None = None,
    ) -> pd.DataFrame:
        """
        从 Binance Public Data 下载历史 K 线数据

        数据源: https://data.binance.vision/

        Args:
            symbol: 交易对 (如 BTCUSDT)
            timeframe: 时间框架 (1m, 5m, 15m, 1h, 4h, 1d 等)
            start_date: 开始日期
            end_date: 结束日期
            market_type: 市场类型 (spot=现货, um=U本位合约, cm=币本位合约)
            output_dir: 可选，保存下载的原始文件

        Returns:
            合并后的 DataFrame
        """
        session = await self._get_session()

        # 格式化 symbol
        binance_symbol = symbol.replace("/", "").upper()
        interval = BINANCE_TIMEFRAME_MAP.get(timeframe, timeframe)

        # 确定数据路径
        if market_type == "spot":
            base_path = "spot/monthly/klines"
        elif market_type == "um":
            base_path = "futures/um/monthly/klines"
        else:
            base_path = "futures/cm/monthly/klines"

        all_data = []
        current = start_date.replace(day=1)

        logger.info(
            "binance_download_start",
            symbol=binance_symbol,
            timeframe=interval,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
        )

        downloaded_months = 0
        failed_months = []

        while current <= end_date:
            year_month = current.strftime("%Y-%m")
            filename = f"{binance_symbol}-{interval}-{year_month}.zip"
            url = f"{BINANCE_DATA_VISION_URL}/{base_path}/{binance_symbol}/{interval}/{filename}"

            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        content = await response.read()

                        # 解压 ZIP 文件
                        with zipfile.ZipFile(io.BytesIO(content)) as zf:
                            csv_name = zf.namelist()[0]
                            with zf.open(csv_name) as f:
                                df = pd.read_csv(f, header=None)

                        # Binance 历史数据格式
                        df.columns = [
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

                        all_data.append(df)
                        downloaded_months += 1
                        logger.debug(
                            "binance_month_downloaded", month=year_month, rows=len(df)
                        )

                    elif response.status == 404:
                        # 尝试日级别数据
                        daily_df = await self._download_daily_klines(
                            session,
                            binance_symbol,
                            interval,
                            current,
                            min(
                                current.replace(month=current.month % 12 + 1, day=1)
                                - timedelta(days=1),
                                end_date,
                            ),
                            base_path,
                        )
                        if not daily_df.empty:
                            all_data.append(daily_df)
                            downloaded_months += 1
                        else:
                            failed_months.append(year_month)
                    else:
                        failed_months.append(year_month)

            except Exception as e:
                logger.warning("binance_download_error", month=year_month, error=str(e))
                failed_months.append(year_month)

            # 下一个月
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

            # 避免请求过快
            await asyncio.sleep(0.2)

        if not all_data:
            logger.warning("binance_no_data_downloaded", symbol=binance_symbol)
            return pd.DataFrame()

        # 合并数据
        result = pd.concat(all_data, ignore_index=True)
        result["timestamp"] = pd.to_datetime(result["timestamp"], unit="ms", utc=True)

        # 过滤时间范围
        result = result[
            (result["timestamp"] >= pd.Timestamp(start_date, tz="UTC"))
            & (result["timestamp"] <= pd.Timestamp(end_date, tz="UTC"))
        ]

        # 转换类型
        for col in ["open", "high", "low", "close", "volume"]:
            result[col] = result[col].apply(lambda x: Decimal(str(x)))

        # 去重和排序
        result = (
            result.drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        logger.info(
            "binance_download_complete",
            symbol=binance_symbol,
            total_rows=len(result),
            downloaded_months=downloaded_months,
            failed_months=len(failed_months),
        )

        return result[["timestamp", "open", "high", "low", "close", "volume"]]

    async def _download_daily_klines(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        base_path: str,
    ) -> pd.DataFrame:
        """下载日级别 K 线数据"""
        all_data = []
        current = start_date

        while current <= end_date:
            date_str = current.strftime("%Y-%m-%d")
            filename = f"{symbol}-{interval}-{date_str}.zip"
            url = (
                f"{BINANCE_DATA_VISION_URL}/{base_path}/{symbol}/{interval}/{filename}"
            )

            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        content = await response.read()
                        with zipfile.ZipFile(io.BytesIO(content)) as zf:
                            csv_name = zf.namelist()[0]
                            with zf.open(csv_name) as f:
                                df = pd.read_csv(f, header=None)

                        df.columns = [
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
                        all_data.append(df)
            except Exception:
                pass

            current += timedelta(days=1)
            await asyncio.sleep(0.1)

        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()


class BinanceDataDownloader:
    """
    Binance 历史数据批量下载器

    用于一次性下载大量历史数据
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        market_type: Literal["spot", "um", "cm"] = "spot",
    ):
        self.output_dir = output_dir or Path("data/binance_raw")
        self.market_type = market_type
        self.connector = BinanceConnector()

    async def download_symbol(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """
        下载单个交易对的历史数据

        Args:
            symbol: 交易对 (如 BTCUSDT 或 BTC/USDT)
            timeframe: 时间框架
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame
        """
        async with self.connector:
            return await self.connector.download_historical_klines(
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                market_type=self.market_type,
                output_dir=self.output_dir,
            )

    async def download_multiple(
        self,
        symbols: list[str],
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, pd.DataFrame]:
        """
        下载多个交易对的历史数据

        Args:
            symbols: 交易对列表
            timeframe: 时间框架
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            {symbol: DataFrame} 字典
        """
        results = {}

        async with self.connector:
            for symbol in symbols:
                try:
                    df = await self.connector.download_historical_klines(
                        symbol=symbol,
                        timeframe=timeframe,
                        start_date=start_date,
                        end_date=end_date,
                        market_type=self.market_type,
                    )
                    results[symbol] = df
                    logger.info("symbol_download_complete", symbol=symbol, rows=len(df))
                except Exception as e:
                    logger.error("symbol_download_failed", symbol=symbol, error=str(e))
                    results[symbol] = pd.DataFrame()

        return results
