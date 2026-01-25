"""
数据验证器

职责:
- 缺口检测 (连续 bar 时间间隔)
- 异常值检测 (价格跳变)
- 时区标准化检查
- 生成质量报告
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

from src.core.instruments import Symbol
from src.core.timeframes import Timeframe
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import get_logger

logger = get_logger(__name__)


@dataclass
class QualityIssue:
    """数据质量问题"""
    
    issue_type: str  # gap, invalid_ohlc, outlier, missing_field
    severity: str  # warning, error, critical
    timestamp: datetime
    description: str
    details: dict = field(default_factory=dict)


@dataclass
class QualityReport:
    """数据质量报告"""
    
    symbol: Symbol
    timeframe: Timeframe
    start: datetime
    end: datetime
    total_bars: int
    expected_bars: int
    issues: list[QualityIssue] = field(default_factory=list)
    
    @property
    def completeness(self) -> float:
        """数据完整度 (0-1)"""
        if self.expected_bars == 0:
            return 1.0
        return min(1.0, self.total_bars / self.expected_bars)
    
    @property
    def gap_count(self) -> int:
        """缺口数量"""
        return sum(1 for i in self.issues if i.issue_type == "gap")
    
    @property
    def error_count(self) -> int:
        """错误数量"""
        return sum(1 for i in self.issues if i.severity in ("error", "critical"))
    
    @property
    def is_healthy(self) -> bool:
        """数据是否健康"""
        return self.error_count == 0 and self.completeness >= 0.99
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "symbol": str(self.symbol),
            "timeframe": self.timeframe.value,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "total_bars": self.total_bars,
            "expected_bars": self.expected_bars,
            "completeness": self.completeness,
            "gap_count": self.gap_count,
            "error_count": self.error_count,
            "is_healthy": self.is_healthy,
            "issues": [
                {
                    "type": i.issue_type,
                    "severity": i.severity,
                    "timestamp": i.timestamp.isoformat(),
                    "description": i.description,
                    "details": i.details,
                }
                for i in self.issues
            ],
        }


class DataQualityChecker:
    """数据质量检查器"""
    
    # 价格变化阈值（超过此比例认为是异常）
    PRICE_CHANGE_THRESHOLD = 0.2  # 20%
    
    # 成交量异常倍数（超过均值 N 倍认为异常）
    VOLUME_OUTLIER_MULTIPLIER = 10.0
    
    def __init__(self, parquet_store: Optional[ParquetStore] = None):
        """
        初始化质量检查器
        
        Args:
            parquet_store: Parquet 存储实例
        """
        self._store = parquet_store
    
    def _get_store(self) -> ParquetStore:
        """获取存储实例"""
        if self._store is None:
            self._store = ParquetStore()
        return self._store
    
    def check_ohlc_validity(self, df: pd.DataFrame) -> list[QualityIssue]:
        """
        检查 OHLC 数据有效性
        
        规则:
        - high >= low
        - high >= open, close
        - low <= open, close
        - 价格 > 0
        - 成交量 >= 0
        """
        issues = []
        
        for idx, row in df.iterrows():
            ts = row["timestamp"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            
            o, h, l, c, v = row["open"], row["high"], row["low"], row["close"], row["volume"]
            
            # high >= low
            if h < l:
                issues.append(QualityIssue(
                    issue_type="invalid_ohlc",
                    severity="error",
                    timestamp=ts,
                    description=f"High ({h}) < Low ({l})",
                    details={"open": o, "high": h, "low": l, "close": c},
                ))
            
            # high >= open, close
            if h < o or h < c:
                issues.append(QualityIssue(
                    issue_type="invalid_ohlc",
                    severity="error",
                    timestamp=ts,
                    description=f"High ({h}) < Open ({o}) or Close ({c})",
                    details={"open": o, "high": h, "low": l, "close": c},
                ))
            
            # low <= open, close
            if l > o or l > c:
                issues.append(QualityIssue(
                    issue_type="invalid_ohlc",
                    severity="error",
                    timestamp=ts,
                    description=f"Low ({l}) > Open ({o}) or Close ({c})",
                    details={"open": o, "high": h, "low": l, "close": c},
                ))
            
            # 价格 > 0
            if any(p <= 0 for p in [o, h, l, c]):
                issues.append(QualityIssue(
                    issue_type="invalid_ohlc",
                    severity="error",
                    timestamp=ts,
                    description="Price <= 0",
                    details={"open": o, "high": h, "low": l, "close": c},
                ))
            
            # 成交量 >= 0
            if v < 0:
                issues.append(QualityIssue(
                    issue_type="invalid_ohlc",
                    severity="error",
                    timestamp=ts,
                    description=f"Negative volume: {v}",
                    details={"volume": v},
                ))
        
        return issues
    
    def check_price_outliers(self, df: pd.DataFrame) -> list[QualityIssue]:
        """
        检查价格异常值（突然大幅变动）
        """
        issues = []
        
        if len(df) < 2:
            return issues
        
        df = df.sort_values("timestamp").reset_index(drop=True)
        
        for i in range(1, len(df)):
            prev_close = df.iloc[i - 1]["close"]
            curr = df.iloc[i]
            
            ts = curr["timestamp"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            
            # 计算变化率
            if prev_close > 0:
                change_pct = abs(curr["close"] - prev_close) / prev_close
                
                if change_pct > self.PRICE_CHANGE_THRESHOLD:
                    issues.append(QualityIssue(
                        issue_type="outlier",
                        severity="warning",
                        timestamp=ts,
                        description=f"Large price change: {change_pct:.2%}",
                        details={
                            "prev_close": prev_close,
                            "curr_close": curr["close"],
                            "change_pct": change_pct,
                        },
                    ))
        
        return issues
    
    def check_volume_outliers(self, df: pd.DataFrame) -> list[QualityIssue]:
        """
        检查成交量异常值
        """
        issues = []
        
        if len(df) < 10:
            return issues
        
        mean_vol = df["volume"].mean()
        
        for idx, row in df.iterrows():
            ts = row["timestamp"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            
            if row["volume"] > mean_vol * self.VOLUME_OUTLIER_MULTIPLIER:
                issues.append(QualityIssue(
                    issue_type="outlier",
                    severity="warning",
                    timestamp=ts,
                    description=f"Volume outlier: {row['volume']:.2f} (mean: {mean_vol:.2f})",
                    details={
                        "volume": row["volume"],
                        "mean_volume": mean_vol,
                        "multiplier": row["volume"] / mean_vol if mean_vol > 0 else 0,
                    },
                ))
        
        return issues
    
    def check_gaps(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[QualityIssue]:
        """
        检查数据缺口
        """
        store = self._get_store()
        gaps = store.detect_gaps(symbol, timeframe, start, end)
        
        issues = []
        for gap_start, gap_end in gaps:
            # 计算缺失的 bar 数量
            gap_duration = (gap_end - gap_start).total_seconds()
            missing_bars = int(gap_duration / timeframe.seconds)
            
            issues.append(QualityIssue(
                issue_type="gap",
                severity="error" if missing_bars > 10 else "warning",
                timestamp=gap_start,
                description=f"Data gap: {missing_bars} bars missing",
                details={
                    "gap_start": gap_start.isoformat(),
                    "gap_end": gap_end.isoformat(),
                    "missing_bars": missing_bars,
                },
            ))
        
        return issues
    
    def generate_report(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> QualityReport:
        """
        生成完整的质量报告
        
        Args:
            symbol: 交易对
            timeframe: 时间框架
            start: 开始时间
            end: 结束时间
            
        Returns:
            质量报告
        """
        store = self._get_store()
        
        # 获取数据范围
        data_range = store.get_data_range(symbol, timeframe)
        
        if data_range is None:
            if start is None:
                start = datetime.now(timezone.utc) - timedelta(days=7)
            if end is None:
                end = datetime.now(timezone.utc)
            
            return QualityReport(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                total_bars=0,
                expected_bars=int((end - start).total_seconds() / timeframe.seconds),
                issues=[QualityIssue(
                    issue_type="missing_data",
                    severity="critical",
                    timestamp=start,
                    description="No data available",
                    details={},
                )],
            )
        
        # 使用数据范围或传入的范围
        if start is None:
            start = data_range[0]
        if end is None:
            end = data_range[1]
        
        # 读取数据
        df = store.read(symbol, timeframe, start, end)
        
        # 计算期望的 bar 数量
        expected_bars = int((end - start).total_seconds() / timeframe.seconds)
        
        # 收集所有问题
        issues: list[QualityIssue] = []
        
        # 1. OHLC 有效性检查
        issues.extend(self.check_ohlc_validity(df))
        
        # 2. 价格异常值检查
        issues.extend(self.check_price_outliers(df))
        
        # 3. 成交量异常值检查
        issues.extend(self.check_volume_outliers(df))
        
        # 4. 缺口检查
        issues.extend(self.check_gaps(symbol, timeframe, start, end))
        
        # 按时间排序
        issues.sort(key=lambda x: x.timestamp)
        
        report = QualityReport(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            total_bars=len(df),
            expected_bars=expected_bars,
            issues=issues,
        )
        
        logger.info(
            "quality_report_generated",
            symbol=str(symbol),
            timeframe=timeframe.value,
            total_bars=report.total_bars,
            completeness=f"{report.completeness:.2%}",
            issues=len(issues),
            is_healthy=report.is_healthy,
        )
        
        return report


def check_all_data_quality(
    symbols: Optional[list[Symbol]] = None,
    timeframes: Optional[list[Timeframe]] = None,
) -> dict[str, QualityReport]:
    """
    检查所有数据的质量
    
    Args:
        symbols: 交易对列表
        timeframes: 时间框架列表
        
    Returns:
        质量报告字典
    """
    from src.core.instruments import Exchange
    
    if symbols is None:
        symbols = [
            Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT"),
            Symbol(exchange=Exchange.OKX, base="ETH", quote="USDT"),
        ]
    
    if timeframes is None:
        timeframes = [Timeframe.M15, Timeframe.H1]
    
    checker = DataQualityChecker()
    reports = {}
    
    for symbol in symbols:
        for timeframe in timeframes:
            key = f"{symbol}_{timeframe.value}"
            reports[key] = checker.generate_report(symbol, timeframe)
    
    return reports
