"""
时间框架定义

支持的时间框架:
- 1m, 5m, 15m, 30m: 分钟级
- 1h, 4h: 小时级
- 1d, 1w: 日/周级

设计原则:
- 统一时区处理 (UTC)
- 支持不同交易所格式转换
"""

from datetime import datetime, timedelta, timezone
from enum import Enum


class Timeframe(str, Enum):
    """时间框架枚举"""

    M1 = "1m"  # 1分钟
    M5 = "5m"  # 5分钟
    M15 = "15m"  # 15分钟
    M30 = "30m"  # 30分钟
    H1 = "1h"  # 1小时
    H4 = "4h"  # 4小时
    D1 = "1d"  # 日线
    W1 = "1w"  # 周线

    @property
    def seconds(self) -> int:
        """返回时间框架对应的秒数"""
        _seconds_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
            "1w": 604800,
        }
        return _seconds_map[self.value]

    @property
    def minutes(self) -> int:
        """返回时间框架对应的分钟数"""
        return self.seconds // 60

    @property
    def timedelta(self) -> timedelta:
        """返回时间框架对应的 timedelta"""
        return timedelta(seconds=self.seconds)

    def floor(self, dt: datetime) -> datetime:
        """
        将时间向下取整到该时间框架

        Args:
            dt: 输入时间

        Returns:
            取整后的时间
        """
        # 确保是 UTC 时间
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        # 按秒数取整
        timestamp = dt.timestamp()
        floored_ts = (timestamp // self.seconds) * self.seconds
        return datetime.fromtimestamp(floored_ts, tz=timezone.utc)

    def ceil(self, dt: datetime) -> datetime:
        """
        将时间向上取整到该时间框架

        Args:
            dt: 输入时间

        Returns:
            取整后的时间
        """
        floored = self.floor(dt)
        if floored == dt:
            return dt
        return floored + self.timedelta

    def next_bar_time(self, dt: datetime) -> datetime:
        """
        获取下一根 bar 的时间

        Args:
            dt: 当前时间

        Returns:
            下一根 bar 的开始时间
        """
        return self.ceil(dt)

    def bars_between(self, start: datetime, end: datetime) -> int:
        """
        计算两个时间点之间的 bar 数量

        Args:
            start: 开始时间
            end: 结束时间

        Returns:
            bar 数量
        """
        diff = (end - start).total_seconds()
        return int(diff // self.seconds)

    @classmethod
    def from_string(cls, value: str) -> "Timeframe":
        """
        从字符串解析时间框架

        Args:
            value: 如 "15m", "1h"

        Returns:
            Timeframe 实例
        """
        value = value.lower().strip()
        for tf in cls:
            if tf.value == value:
                return tf
        raise ValueError(f"Unknown timeframe: {value}")

    def to_ccxt(self) -> str:
        """
        转换为 CCXT 格式

        Returns:
            CCXT 格式的时间框架
        """
        return self.value

    def to_okx(self) -> str:
        """
        转换为 OKX API 格式

        OKX 使用不同的格式:
        1m -> 1m, 1h -> 1H, 1d -> 1D
        """
        mapping = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1H",
            "4h": "4H",
            "1d": "1D",
            "1w": "1W",
        }
        return mapping.get(self.value, self.value)


# 中低频交易常用时间框架
TRADING_TIMEFRAMES = [Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1]


# 导出
__all__ = [
    "Timeframe",
    "TRADING_TIMEFRAMES",
]
