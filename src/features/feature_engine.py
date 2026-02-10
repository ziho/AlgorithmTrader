"""
特征计算引擎

职责:
- 因子计算调度
- 特征矩阵生成
- 批量计算与缓存
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from src.ops.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FeatureSpec:
    """特征规格"""

    name: str
    calculator: Callable[[pd.DataFrame], pd.Series]
    params: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class FeatureResult:
    """特征计算结果"""

    name: str
    values: pd.Series
    calculated_at: datetime = field(default_factory=datetime.now)
    params: dict[str, Any] = field(default_factory=dict)


class FeatureEngine:
    """
    特征计算引擎

    功能:
    - 注册因子计算函数
    - 批量计算特征
    - 依赖管理
    - 缓存管理
    """

    def __init__(self):
        self._features: dict[str, FeatureSpec] = {}
        self._cache: dict[str, FeatureResult] = {}
        self._built_in_features()

    def _built_in_features(self):
        """注册内置特征"""
        # 简单移动平均
        self.register(
            "sma",
            lambda df, period=20: df["close"].rolling(window=period).mean(),
            params={"period": 20},
        )

        # 指数移动平均
        self.register(
            "ema",
            lambda df, period=20: df["close"].ewm(span=period, adjust=False).mean(),
            params={"period": 20},
        )

        # 标准差
        self.register(
            "std",
            lambda df, period=20: df["close"].rolling(window=period).std(),
            params={"period": 20},
        )

        # 布林带
        self.register(
            "bb_upper",
            lambda df, period=20, std_dev=2: (
                df["close"].rolling(window=period).mean()
                + std_dev * df["close"].rolling(window=period).std()
            ),
            params={"period": 20, "std_dev": 2},
        )

        self.register(
            "bb_lower",
            lambda df, period=20, std_dev=2: (
                df["close"].rolling(window=period).mean()
                - std_dev * df["close"].rolling(window=period).std()
            ),
            params={"period": 20, "std_dev": 2},
        )

        # RSI
        self.register(
            "rsi",
            self._calculate_rsi,
            params={"period": 14},
        )

        # 真实波幅 (ATR)
        self.register(
            "atr",
            self._calculate_atr,
            params={"period": 14},
        )

        # 收益率
        self.register(
            "returns",
            lambda df: df["close"].pct_change(),
        )

        # 对数收益率
        self.register(
            "log_returns",
            lambda df: np.log(df["close"] / df["close"].shift(1)),
        )

        # Z-Score
        self.register(
            "zscore",
            lambda df, period=20: (
                (df["close"] - df["close"].rolling(window=period).mean())
                / df["close"].rolling(window=period).std()
            ),
            params={"period": 20},
        )

        # 历史波动率
        self.register(
            "volatility",
            lambda df, period=20: df["close"].pct_change().rolling(window=period).std()
            * np.sqrt(252),
            params={"period": 20},
        )

        # 最高价通道
        self.register(
            "highest",
            lambda df, period=20: df["high"].rolling(window=period).max(),
            params={"period": 20},
        )

        # 最低价通道
        self.register(
            "lowest",
            lambda df, period=20: df["low"].rolling(window=period).min(),
            params={"period": 20},
        )

    @staticmethod
    def _calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算 RSI"""
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.inf)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算 ATR (真实波幅)"""
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)

        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def register(
        self,
        name: str,
        calculator: Callable[[pd.DataFrame], pd.Series],
        params: dict[str, Any] | None = None,
        dependencies: list[str] | None = None,
    ):
        """
        注册特征计算函数

        Args:
            name: 特征名称
            calculator: 计算函数，接收 DataFrame 返回 Series
            params: 默认参数
            dependencies: 依赖的其他特征
        """
        self._features[name] = FeatureSpec(
            name=name,
            calculator=calculator,
            params=params or {},
            dependencies=dependencies or [],
        )
        logger.debug("feature_registered", name=name)

    def calculate(
        self,
        name: str,
        data: pd.DataFrame,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> pd.Series:
        """
        计算单个特征

        Args:
            name: 特征名称
            data: OHLCV 数据
            params: 覆盖默认参数
            use_cache: 是否使用缓存

        Returns:
            特征序列
        """
        if name not in self._features:
            raise ValueError(f"Unknown feature: {name}")

        spec = self._features[name]
        merged_params = {**spec.params, **(params or {})}

        # 检查缓存
        cache_key = f"{name}_{hash(str(merged_params))}_{len(data)}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key].values

        # 计算
        try:
            if merged_params:
                result = spec.calculator(data, **merged_params)
            else:
                result = spec.calculator(data)

            # 缓存结果
            if use_cache:
                self._cache[cache_key] = FeatureResult(
                    name=name,
                    values=result,
                    params=merged_params,
                )

            return result

        except Exception as e:
            logger.error("feature_calculation_failed", name=name, error=str(e))
            raise

    def calculate_all(
        self,
        data: pd.DataFrame,
        features: list[str] | None = None,
        params: dict[str, dict[str, Any]] | None = None,
    ) -> pd.DataFrame:
        """
        批量计算特征

        Args:
            data: OHLCV 数据
            features: 要计算的特征列表（默认全部）
            params: 每个特征的参数覆盖

        Returns:
            包含所有特征的 DataFrame
        """
        feature_names = features or list(self._features.keys())
        params = params or {}

        result = data.copy()

        for name in feature_names:
            try:
                feature_params = params.get(name, {})
                result[name] = self.calculate(name, data, feature_params)
            except Exception as e:
                logger.warning("feature_skipped", name=name, error=str(e))

        return result

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        logger.info("feature_cache_cleared")

    def list_features(self) -> list[str]:
        """列出所有已注册的特征"""
        return list(self._features.keys())

    def get_feature_info(self, name: str) -> dict[str, Any] | None:
        """获取特征信息"""
        if name not in self._features:
            return None

        spec = self._features[name]
        return {
            "name": spec.name,
            "params": spec.params,
            "dependencies": spec.dependencies,
        }


# 全局实例
_default_engine: FeatureEngine | None = None


def get_feature_engine() -> FeatureEngine:
    """获取默认特征引擎实例"""
    global _default_engine
    if _default_engine is None:
        _default_engine = FeatureEngine()
    return _default_engine


# 导出
__all__ = [
    "FeatureEngine",
    "FeatureSpec",
    "FeatureResult",
    "get_feature_engine",
]
