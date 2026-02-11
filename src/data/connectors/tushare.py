"""
Tushare A 股数据连接器

通过 Tushare Pro API 获取 A 股市场数据：
- 交易日历 (trade_cal)
- 日线行情 (daily)
- 每日指标 (daily_basic)
- 复权因子 (adj_factor)
- 业绩预告 (forecast)
- 财务指标 (fina_indicator)

特点:
- 同步 API（Tushare 本身是同步的，通过 asyncio.to_thread 包装）
- 限速控制（默认 200 次/分钟）
- 失败重试 + 日志记录
"""

import asyncio
import time
from datetime import datetime
from typing import Any

import pandas as pd

from src.core.config.settings import get_settings
from src.core.instruments import AssetType, Exchange, Symbol
from src.ops.logging import get_logger

logger = get_logger(__name__)

# Tushare 日线数据列映射 → 统一 OHLCV 格式
DAILY_COLUMNS_MAP = {
    "trade_date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "vol": "volume",  # Tushare 的 vol 单位是手（100股），需转换
    "amount": "amount",  # 成交额（千元）
    "pre_close": "pre_close",  # 昨收价（用于涨跌停判断）
}


class TushareConnector:
    """
    Tushare Pro A 股数据连接器

    支持:
    - 全市场日线 OHLCV 数据
    - 每日基本面指标
    - 复权因子
    - 业绩预告
    - 财务指标
    - 交易日历
    """

    def __init__(self, token: str | None = None) -> None:
        """
        初始化连接器

        Args:
            token: Tushare Pro API token，为空则从配置读取
        """
        settings = get_settings()
        self._token = token or settings.tushare.token.get_secret_value()
        if not self._token:
            raise ValueError("Tushare token 未配置。请在 .env 中设置 TUSHARE_TOKEN")

        self._api: Any = None  # tushare.pro_api 实例
        self._requests_per_minute = settings.tushare.requests_per_minute
        self._last_request_time: float = 0.0
        self._request_interval = 60.0 / self._requests_per_minute

    def _get_api(self) -> Any:
        """懒加载 Tushare API 实例"""
        if self._api is None:
            try:
                import tushare as ts

                self._api = ts.pro_api(self._token)
            except ImportError as e:
                raise ImportError("tushare 未安装。请运行: pip install tushare") from e
        return self._api

    async def _rate_limit(self) -> None:
        """限速控制"""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._request_interval:
            await asyncio.sleep(self._request_interval - elapsed)
        self._last_request_time = time.monotonic()

    async def _call_api(
        self,
        api_name: str,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """
        调用 Tushare API（带限速和重试）

        Args:
            api_name: API 名称，如 'daily', 'trade_cal'
            max_retries: 最大重试次数
            **kwargs: API 参数

        Returns:
            pd.DataFrame
        """
        api = self._get_api()
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                await self._rate_limit()
                # Tushare 是同步 API，用 to_thread 包装
                api_func = getattr(api, api_name)
                df = await asyncio.to_thread(api_func, **kwargs)
                if df is None:
                    return pd.DataFrame()
                return df
            except Exception as e:
                last_error = e
                wait_time = 2**attempt
                logger.warning(
                    "tushare_api_error",
                    api=api_name,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                    wait_time=wait_time,
                )
                await asyncio.sleep(wait_time)

        logger.error(
            "tushare_api_failed",
            api=api_name,
            params=kwargs,
            error=str(last_error),
        )
        raise RuntimeError(
            f"Tushare API '{api_name}' 在 {max_retries} 次重试后失败: {last_error}"
        )

    # ============================================
    # 交易日历
    # ============================================

    async def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "",
    ) -> list[str]:
        """
        获取交易日历

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            exchange: 交易所 (SSE/SZSE)，为空返回全部

        Returns:
            交易日列表 ['20180102', '20180103', ...]
        """
        df = await self._call_api(
            "trade_cal",
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            is_open="1",
        )
        if df.empty:
            return []
        return sorted(df["cal_date"].tolist())

    # ============================================
    # 日线行情
    # ============================================

    async def fetch_daily(
        self,
        trade_date: str | None = None,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """
        获取日线行情

        按 trade_date 获取全市场某一天数据，
        或按 ts_code 获取单个股票的历史数据。

        Args:
            trade_date: 交易日 YYYYMMDD（全市场模式）
            ts_code: 股票代码（单股模式）
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            DataFrame with columns:
            ts_code, trade_date, open, high, low, close, pre_close,
            change, pct_chg, vol, amount
        """
        kwargs: dict[str, Any] = {}
        if trade_date:
            kwargs["trade_date"] = trade_date
        if ts_code:
            kwargs["ts_code"] = ts_code
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date

        return await self._call_api("daily", **kwargs)

    async def fetch_daily_as_ohlcv(
        self,
        trade_date: str | None = None,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """
        获取日线行情并转换为统一 OHLCV 格式

        Returns:
            DataFrame with columns:
            timestamp, open, high, low, close, volume
            (+ pre_close 用于涨跌停判断)
        """
        df = await self.fetch_daily(
            trade_date=trade_date,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        if df.empty:
            return df

        return self.normalize_daily_to_ohlcv(df)

    @staticmethod
    def normalize_daily_to_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """
        将 Tushare daily 数据标准化为 OHLCV 格式

        - trade_date → timestamp (Asia/Shanghai 00:00 → UTC)
        - vol (手) → volume (股)
        - 保留 pre_close 用于涨跌停判断
        """
        result = df.copy()

        # 转换日期为 UTC 时间戳
        result["timestamp"] = (
            pd.to_datetime(result["trade_date"], format="%Y%m%d")
            .dt.tz_localize("Asia/Shanghai")
            .dt.tz_convert("UTC")
        )

        # vol 单位从手转为股（1手 = 100股）
        result["volume"] = result["vol"] * 100

        # 选择并重命名列
        columns = {
            "timestamp": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }

        # 保留 pre_close（如果存在）
        if "pre_close" in result.columns:
            columns["pre_close"] = "pre_close"

        # 保留 ts_code（如果存在，用于多股票拆分）
        if "ts_code" in result.columns:
            columns["ts_code"] = "ts_code"

        result = result[list(columns.keys())].rename(columns=columns)

        # 按时间排序
        result = result.sort_values("timestamp").reset_index(drop=True)

        # 转换数值类型
        for col in ["open", "high", "low", "close", "volume"]:
            result[col] = pd.to_numeric(result[col], errors="coerce")

        return result

    # ============================================
    # 基本面数据
    # ============================================

    async def fetch_daily_basic(
        self,
        trade_date: str | None = None,
        ts_code: str | None = None,
    ) -> pd.DataFrame:
        """
        获取每日指标：市值、换手率、PE、PB 等

        Args:
            trade_date: 交易日 YYYYMMDD
            ts_code: 股票代码

        Returns:
            DataFrame with daily_basic fields
        """
        kwargs: dict[str, Any] = {}
        if trade_date:
            kwargs["trade_date"] = trade_date
        if ts_code:
            kwargs["ts_code"] = ts_code

        return await self._call_api("daily_basic", **kwargs)

    async def fetch_adj_factor(
        self,
        trade_date: str | None = None,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """
        获取复权因子

        Args:
            trade_date: 交易日
            ts_code: 股票代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            DataFrame with ts_code, trade_date, adj_factor
        """
        kwargs: dict[str, Any] = {}
        if trade_date:
            kwargs["trade_date"] = trade_date
        if ts_code:
            kwargs["ts_code"] = ts_code
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date

        return await self._call_api("adj_factor", **kwargs)

    async def fetch_forecast(
        self,
        ann_date: str | None = None,
        ts_code: str | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        """
        获取业绩预告

        Args:
            ann_date: 公告日期
            ts_code: 股票代码
            period: 报告期

        Returns:
            DataFrame with forecast fields
        """
        kwargs: dict[str, Any] = {}
        if ann_date:
            kwargs["ann_date"] = ann_date
        if ts_code:
            kwargs["ts_code"] = ts_code
        if period:
            kwargs["period"] = period

        return await self._call_api("forecast", **kwargs)

    async def fetch_fina_indicator(
        self,
        ts_code: str | None = None,
        ann_date: str | None = None,
        period: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """
        获取财务指标

        Args:
            ts_code: 股票代码
            ann_date: 公告日期
            period: 报告期
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            DataFrame with fina_indicator fields
        """
        kwargs: dict[str, Any] = {}
        if ts_code:
            kwargs["ts_code"] = ts_code
        if ann_date:
            kwargs["ann_date"] = ann_date
        if period:
            kwargs["period"] = period
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date

        return await self._call_api("fina_indicator", **kwargs)

    async def fetch_stock_basic(
        self,
        list_status: str = "L",
    ) -> pd.DataFrame:
        """
        获取股票基本信息（用于获取全市场股票列表）

        Args:
            list_status: 上市状态 L=上市 D=退市 P=暂停

        Returns:
            DataFrame with ts_code, symbol, name, area, industry, ...
        """
        return await self._call_api(
            "stock_basic",
            exchange="",
            list_status=list_status,
            fields="ts_code,symbol,name,area,industry,list_date,market,is_hs",
        )

    # ============================================
    # 辅助方法
    # ============================================

    @staticmethod
    def ts_code_to_symbol(ts_code: str) -> Symbol:
        """
        将 Tushare ts_code 转换为 Symbol

        Args:
            ts_code: 如 '600519.SH'

        Returns:
            Symbol(exchange=A_TUSHARE, base='600519.SH', quote='CNY', asset_type=STOCK)
        """
        return Symbol(
            exchange=Exchange.A_TUSHARE,
            base=ts_code,
            quote="CNY",
            asset_type=AssetType.STOCK,
        )

    @staticmethod
    def symbol_to_ts_code(symbol: Symbol) -> str:
        """
        将 Symbol 转换为 Tushare ts_code

        Args:
            symbol: Symbol 实例

        Returns:
            ts_code 如 '600519.SH'
        """
        return symbol.base

    @staticmethod
    def date_to_str(dt: datetime) -> str:
        """datetime → YYYYMMDD 字符串"""
        return dt.strftime("%Y%m%d")

    @staticmethod
    def str_to_date(date_str: str) -> datetime:
        """YYYYMMDD 字符串 → datetime"""
        return datetime.strptime(date_str, "%Y%m%d")

    async def close(self) -> None:
        """关闭连接器（Tushare 无需显式关闭）"""
        self._api = None

    async def __aenter__(self) -> "TushareConnector":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
