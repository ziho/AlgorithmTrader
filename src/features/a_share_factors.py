"""
A 股因子库

从 ParquetStore (OHLCV) 和 AShareFundamentalsStore (基本面) 读取数据，
计算适用于 A 股市场的高价值因子。

典型因子:
- 换手率 (turnover)
- 市值分位 (market_cap_rank)
- 动量 (momentum)
- 波动率 (volatility)
- 复权价格 (adjusted_price)
- 市盈率 (pe_ratio)
- 量价背离 (price_volume_divergence)

用法:
    engine = AShareFeatureEngine()
    # 单股因子
    df = engine.calculate_stock_factors("600519.SH", "20230101", "20231231")
    # 截面因子（全市场某天）
    rank_df = engine.calculate_cross_section_rank("20231229", "total_mv")
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.core.config import get_settings
from src.core.instruments import AssetType, Exchange, Symbol
from src.core.timeframes import Timeframe
from src.data.storage.a_share_store import AShareFundamentalsStore
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import get_logger

logger = get_logger(__name__)


# ============================================
# 独立因子计算函数
# ============================================


def momentum(close: pd.Series, period: int = 20) -> pd.Series:
    """
    动量因子: 过去 N 日收益率

    Args:
        close: 收盘价序列
        period: 回看天数

    Returns:
        动量值（百分比变化）
    """
    return close.pct_change(period)


def volatility(close: pd.Series, period: int = 20) -> pd.Series:
    """
    历史波动率: 过去 N 日收益率标准差（年化）

    Args:
        close: 收盘价序列
        period: 回看窗口

    Returns:
        年化波动率
    """
    returns = close.pct_change()
    return returns.rolling(window=period).std() * np.sqrt(252)


def turnover_ma(turnover_rate: pd.Series, period: int = 20) -> pd.Series:
    """
    换手率均值: 过去 N 日平均换手率

    Args:
        turnover_rate: 日换手率序列
        period: 均值窗口

    Returns:
        均值换手率
    """
    return turnover_rate.rolling(window=period).mean()


def price_volume_divergence(
    close: pd.Series,
    volume: pd.Series,
    period: int = 20,
) -> pd.Series:
    """
    量价背离因子: 价格变化方向与成交量变化方向的相关性

    负值表示量价背离（价涨量缩或价跌量增）

    Args:
        close: 收盘价序列
        volume: 成交量序列
        period: 滚动窗口

    Returns:
        量价相关系数
    """
    price_ret = close.pct_change()
    vol_ret = volume.pct_change()
    return price_ret.rolling(window=period).corr(vol_ret)


def adjusted_close(
    close: pd.Series,
    adj_factor: pd.Series,
) -> pd.Series:
    """
    前复权收盘价

    Args:
        close: 原始收盘价
        adj_factor: 复权因子序列（与 close 对齐）

    Returns:
        前复权价格
    """
    if adj_factor.empty:
        return close
    latest_factor = adj_factor.iloc[-1]
    if latest_factor == 0:
        return close
    return close * adj_factor / latest_factor


def amplitude(high: pd.Series, low: pd.Series, pre_close: pd.Series) -> pd.Series:
    """
    振幅因子: (最高 - 最低) / 昨收

    Args:
        high: 最高价
        low: 最低价
        pre_close: 前收盘价

    Returns:
        振幅比例
    """
    return (high - low) / pre_close.replace(0, np.nan)


def relative_strength(
    close: pd.Series, index_close: pd.Series, period: int = 20
) -> pd.Series:
    """
    相对强弱: 个股动量 / 指数动量

    Args:
        close: 个股收盘价
        index_close: 指数收盘价
        period: 回看天数

    Returns:
        相对强弱值（>1 表示跑赢指数）
    """
    stock_mom = close.pct_change(period)
    index_mom = index_close.pct_change(period)
    return (1 + stock_mom) / (1 + index_mom.replace(0, np.nan))


# ============================================
# A 股特征引擎
# ============================================


class AShareFeatureEngine:
    """
    A 股特征引擎

    整合 ParquetStore 和 AShareFundamentalsStore，
    提供单股时序因子与截面排序因子的计算能力。
    """

    def __init__(
        self,
        data_dir: Path | str | None = None,
    ) -> None:
        settings = get_settings()
        data_dir = Path(data_dir) if data_dir else Path(settings.data_dir)

        self._parquet_store = ParquetStore(data_dir / "parquet")
        self._fundamentals_store = AShareFundamentalsStore(
            data_dir / "parquet" / "a_tushare_fundamentals"
        )

    # ============================================
    # 单股时序因子
    # ============================================

    def calculate_stock_factors(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        factors: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        计算单个股票的所有时序因子

        Args:
            ts_code: 股票代码，如 '600519.SH'
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            factors: 指定因子列表，默认全部

        Returns:
            DataFrame，index 为日期，列为各因子值
        """
        # 读取 OHLCV
        symbol = self._ts_code_to_symbol(ts_code)
        ohlcv = self._parquet_store.read(symbol, Timeframe.D1)

        if ohlcv is None or ohlcv.empty:
            logger.warning("a_share_no_ohlcv", ts_code=ts_code)
            return pd.DataFrame()

        # 确保时间排序
        ohlcv = ohlcv.sort_values("timestamp").reset_index(drop=True)

        # 日期过滤 — 需要与 OHLCV timestamp 时区保持一致
        ts_tz = ohlcv["timestamp"].dt.tz
        if start_date:
            start_dt = pd.Timestamp(start_date, tz=ts_tz)
            ohlcv = ohlcv[ohlcv["timestamp"] >= start_dt]
        if end_date:
            end_dt = pd.Timestamp(end_date, tz=ts_tz)
            ohlcv = ohlcv[ohlcv["timestamp"] <= end_dt]

        if ohlcv.empty:
            return pd.DataFrame()

        # 读取基本面数据
        daily_basic = self._fundamentals_store.read_daily_basic(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        adj_df = self._fundamentals_store.read_adj_factor(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        # 构建结果 DataFrame
        result = ohlcv[["timestamp"]].copy()
        result = result.set_index("timestamp")

        all_factors = factors or self.list_factors()

        for factor_name in all_factors:
            try:
                values = self._compute_factor(factor_name, ohlcv, daily_basic, adj_df)
                if values is not None:
                    result[factor_name] = values.values
            except Exception as e:
                logger.warning(
                    "factor_calc_error",
                    factor=factor_name,
                    ts_code=ts_code,
                    error=str(e),
                )

        return result

    def _compute_factor(
        self,
        name: str,
        ohlcv: pd.DataFrame,
        daily_basic: pd.DataFrame,
        adj_df: pd.DataFrame,
    ) -> pd.Series | None:
        """分发因子计算"""
        close = ohlcv["close"]
        high = ohlcv["high"]
        low = ohlcv["low"]
        vol = ohlcv["volume"]

        if name == "momentum_5":
            return momentum(close, period=5)
        elif name == "momentum_20":
            return momentum(close, period=20)
        elif name == "momentum_60":
            return momentum(close, period=60)
        elif name == "volatility_20":
            return volatility(close, period=20)
        elif name == "volatility_60":
            return volatility(close, period=60)
        elif name == "price_volume_div":
            return price_volume_divergence(close, vol, period=20)
        elif name == "adjusted_close":
            adj_series = self._align_adj_factor(ohlcv, adj_df)
            return adjusted_close(close, adj_series)
        elif name == "amplitude":
            pre_close = close.shift(1)
            return amplitude(high, low, pre_close)
        elif name == "turnover_ma_5":
            turnover = self._align_daily_basic_col(ohlcv, daily_basic, "turnover_rate")
            if turnover is not None:
                return turnover_ma(turnover, period=5)
            return None
        elif name == "turnover_ma_20":
            turnover = self._align_daily_basic_col(ohlcv, daily_basic, "turnover_rate")
            if turnover is not None:
                return turnover_ma(turnover, period=20)
            return None
        elif name == "pe_ttm":
            return self._align_daily_basic_col(ohlcv, daily_basic, "pe_ttm")
        elif name == "total_mv":
            return self._align_daily_basic_col(ohlcv, daily_basic, "total_mv")
        elif name == "circ_mv":
            return self._align_daily_basic_col(ohlcv, daily_basic, "circ_mv")
        elif name == "pb":
            return self._align_daily_basic_col(ohlcv, daily_basic, "pb")
        elif name == "ps_ttm":
            return self._align_daily_basic_col(ohlcv, daily_basic, "ps_ttm")
        else:
            logger.debug("unknown_factor", name=name)
            return None

    def _align_adj_factor(
        self,
        ohlcv: pd.DataFrame,
        adj_df: pd.DataFrame,
    ) -> pd.Series:
        """将复权因子对齐到 OHLCV 的时间轴"""
        if adj_df.empty or "adj_factor" not in adj_df.columns:
            return pd.Series(dtype=float)

        # trade_date 是 YYYYMMDD 字符串，转为日期
        adj = adj_df[["trade_date", "adj_factor"]].copy()
        adj["date"] = pd.to_datetime(adj["trade_date"], format="%Y%m%d")
        adj = adj.set_index("date")["adj_factor"]

        # OHLCV timestamp 转日期
        dates = pd.to_datetime(ohlcv["timestamp"]).dt.normalize()
        return adj.reindex(dates).reset_index(drop=True)

    def _align_daily_basic_col(
        self,
        ohlcv: pd.DataFrame,
        daily_basic: pd.DataFrame,
        col: str,
    ) -> pd.Series | None:
        """将 daily_basic 的某列对齐到 OHLCV 时间轴"""
        if daily_basic.empty or col not in daily_basic.columns:
            return None

        basic = daily_basic[["trade_date", col]].copy()
        basic["date"] = pd.to_datetime(basic["trade_date"], format="%Y%m%d")
        basic = basic.drop_duplicates("date").set_index("date")[col]

        dates = pd.to_datetime(ohlcv["timestamp"]).dt.normalize()
        return basic.reindex(dates).reset_index(drop=True)

    # ============================================
    # 截面排序因子
    # ============================================

    def calculate_cross_section_rank(
        self,
        trade_date: str,
        rank_by: str = "total_mv",
        ascending: bool = True,
    ) -> pd.DataFrame:
        """
        计算截面排序因子（全市场某天的排名）

        Args:
            trade_date: 交易日 YYYYMMDD
            rank_by: 排序字段 (total_mv, circ_mv, turnover_rate, pe_ttm, pb)
            ascending: 是否升序排序

        Returns:
            DataFrame with columns: ts_code, value, rank, percentile
        """
        daily_basic = self._fundamentals_store.read_daily_basic(
            start_date=trade_date,
            end_date=trade_date,
        )

        if daily_basic.empty:
            logger.warning(
                "cross_section_no_data",
                trade_date=trade_date,
                rank_by=rank_by,
            )
            return pd.DataFrame()

        if rank_by not in daily_basic.columns:
            logger.warning(
                "cross_section_missing_col",
                col=rank_by,
                available=list(daily_basic.columns),
            )
            return pd.DataFrame()

        # 过滤有效数据
        df = daily_basic[["ts_code", rank_by]].dropna(subset=[rank_by]).copy()
        df = df.rename(columns={rank_by: "value"})

        # 排名
        df["rank"] = df["value"].rank(ascending=ascending, method="min").astype(int)
        total = len(df)
        df["percentile"] = df["rank"] / total

        return df.sort_values("rank").reset_index(drop=True)

    # ============================================
    # 辅助
    # ============================================

    @staticmethod
    def _ts_code_to_symbol(ts_code: str) -> Symbol:
        """将 ts_code 转换为 Symbol 对象"""
        return Symbol(
            exchange=Exchange.A_TUSHARE,
            base=ts_code,
            quote="CNY",
            asset_type=AssetType.STOCK,
        )

    @staticmethod
    def list_factors() -> list[str]:
        """列出所有可用因子"""
        return [
            # 动量类
            "momentum_5",
            "momentum_20",
            "momentum_60",
            # 波动率类
            "volatility_20",
            "volatility_60",
            # 量价类
            "price_volume_div",
            "turnover_ma_5",
            "turnover_ma_20",
            "amplitude",
            # 基本面类
            "pe_ttm",
            "pb",
            "ps_ttm",
            "total_mv",
            "circ_mv",
            # 复权价格
            "adjusted_close",
        ]

    @staticmethod
    def list_factor_groups() -> dict[str, list[str]]:
        """因子分组"""
        return {
            "动量": ["momentum_5", "momentum_20", "momentum_60"],
            "波动率": ["volatility_20", "volatility_60"],
            "量价": [
                "price_volume_div",
                "turnover_ma_5",
                "turnover_ma_20",
                "amplitude",
            ],
            "基本面": ["pe_ttm", "pb", "ps_ttm", "total_mv", "circ_mv"],
            "价格": ["adjusted_close"],
        }


# ============================================
# 便捷访问
# ============================================

_default_engine: AShareFeatureEngine | None = None


def get_a_share_feature_engine() -> AShareFeatureEngine:
    """获取默认 A 股特征引擎实例"""
    global _default_engine
    if _default_engine is None:
        _default_engine = AShareFeatureEngine()
    return _default_engine


__all__ = [
    "AShareFeatureEngine",
    "get_a_share_feature_engine",
    "momentum",
    "volatility",
    "turnover_ma",
    "price_volume_divergence",
    "adjusted_close",
    "amplitude",
    "relative_strength",
]
