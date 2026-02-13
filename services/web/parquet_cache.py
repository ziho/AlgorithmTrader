"""
Parquet 文件统计缓存

避免每次页面加载都扫描 452K+ 文件。
使用 TTL（10 分钟）缓存统计结果，首次懒加载+异步刷新。
"""

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.ops.logging import get_logger

logger = get_logger(__name__)

# 缓存有效期 (秒)
CACHE_TTL = 600  # 10 分钟

# A股相关目录名列表
A_SHARE_DIRS = {"a_tushare", "a_tushare_fundamentals", "a_tushare_meta"}

# 加密货币目录名列表
CRYPTO_DIRS = {"binance", "okx"}


@dataclass
class ParquetStats:
    """Parquet 统计结果"""

    file_count: int = 0
    total_size: int = 0  # bytes
    datasets: int = 0  # exchange/symbol/tf
    symbols: int = 0
    computed_at: float = 0  # time.time()

    @property
    def size_str(self) -> str:
        if self.total_size >= 1024**3:
            return f"{self.total_size / 1024**3:.2f} GB"
        elif self.total_size >= 1024**2:
            return f"{self.total_size / 1024**2:.1f} MB"
        elif self.total_size > 0:
            return f"{self.total_size / 1024:.1f} KB"
        return "0"

    @property
    def is_valid(self) -> bool:
        return self.computed_at > 0 and (time.time() - self.computed_at) < CACHE_TTL


class _ParquetStatsCache:
    """全局 Parquet 统计缓存（线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._crypto_stats: ParquetStats = ParquetStats()
        self._a_share_stats: ParquetStats = ParquetStats()
        self._all_stats: ParquetStats = ParquetStats()
        self._computing = False

    def get_crypto_stats(self, parquet_dir: Path) -> ParquetStats:
        """获取加密货币 Parquet 统计（binance + okx）"""
        with self._lock:
            if self._crypto_stats.is_valid:
                return self._crypto_stats
        stats = self._scan_dirs(parquet_dir, CRYPTO_DIRS)
        with self._lock:
            self._crypto_stats = stats
        return stats

    def get_a_share_stats(self, parquet_dir: Path) -> ParquetStats:
        """获取 A 股 Parquet 统计（a_tushare*）"""
        with self._lock:
            if self._a_share_stats.is_valid:
                return self._a_share_stats
        stats = self._scan_dirs(parquet_dir, A_SHARE_DIRS)
        with self._lock:
            self._a_share_stats = stats
        return stats

    def get_all_stats(self, parquet_dir: Path) -> ParquetStats:
        """获取所有 Parquet 统计"""
        with self._lock:
            if self._all_stats.is_valid:
                return self._all_stats

        # 如果 crypto 和 a_share 都有缓存，直接合并
        with self._lock:
            if self._crypto_stats.is_valid and self._a_share_stats.is_valid:
                merged = ParquetStats(
                    file_count=self._crypto_stats.file_count
                    + self._a_share_stats.file_count,
                    total_size=self._crypto_stats.total_size
                    + self._a_share_stats.total_size,
                    datasets=self._crypto_stats.datasets + self._a_share_stats.datasets,
                    symbols=self._crypto_stats.symbols + self._a_share_stats.symbols,
                    computed_at=min(
                        self._crypto_stats.computed_at, self._a_share_stats.computed_at
                    ),
                )
                self._all_stats = merged
                return merged

        # 否则全量扫描
        stats = self._scan_dirs(parquet_dir, None)
        with self._lock:
            self._all_stats = stats
        return stats

    def get_all_stats_fast(self, parquet_dir: Path) -> ParquetStats:
        """快速获取所有 Parquet 统计 — 优先用缓存，否则用最快方式估算"""
        with self._lock:
            if self._all_stats.is_valid:
                return self._all_stats
            # 尝试合并已有缓存
            if self._crypto_stats.is_valid and self._a_share_stats.is_valid:
                merged = ParquetStats(
                    file_count=self._crypto_stats.file_count
                    + self._a_share_stats.file_count,
                    total_size=self._crypto_stats.total_size
                    + self._a_share_stats.total_size,
                    datasets=self._crypto_stats.datasets + self._a_share_stats.datasets,
                    symbols=self._crypto_stats.symbols + self._a_share_stats.symbols,
                    computed_at=min(
                        self._crypto_stats.computed_at, self._a_share_stats.computed_at
                    ),
                )
                self._all_stats = merged
                return merged
            # 如果有 crypto 缓存，只需要扫 a_share
            if self._crypto_stats.is_valid:
                a_stats = self._scan_dirs_fast(parquet_dir, A_SHARE_DIRS)
                with self._lock:
                    self._a_share_stats = a_stats
                merged = ParquetStats(
                    file_count=self._crypto_stats.file_count + a_stats.file_count,
                    total_size=self._crypto_stats.total_size + a_stats.total_size,
                    datasets=self._crypto_stats.datasets + a_stats.datasets,
                    symbols=self._crypto_stats.symbols + a_stats.symbols,
                    computed_at=min(
                        self._crypto_stats.computed_at, a_stats.computed_at
                    ),
                )
                self._all_stats = merged
                return merged

        # 全量快速扫描
        stats = self._scan_dirs_fast(parquet_dir, None)
        with self._lock:
            self._all_stats = stats
        return stats

    def invalidate(self):
        """清除所有缓存"""
        with self._lock:
            self._crypto_stats = ParquetStats()
            self._a_share_stats = ParquetStats()
            self._all_stats = ParquetStats()

    def _scan_dirs(
        self, parquet_dir: Path, dir_filter: set[str] | None
    ) -> ParquetStats:
        """扫描指定目录的 Parquet 文件统计"""
        if not parquet_dir.exists():
            return ParquetStats(computed_at=time.time())

        datasets: set[str] = set()
        symbols: set[str] = set()
        total_size = 0
        file_count = 0

        for ex_dir in parquet_dir.iterdir():
            if not ex_dir.is_dir():
                continue
            if dir_filter is not None and ex_dir.name not in dir_filter:
                continue

            for pf in ex_dir.rglob("*.parquet"):
                total_size += pf.stat().st_size
                file_count += 1
                parts = pf.relative_to(parquet_dir).parts
                if len(parts) >= 3:
                    datasets.add(f"{parts[0]}/{parts[1]}/{parts[2]}")
                if len(parts) >= 2:
                    symbols.add(parts[1])

        return ParquetStats(
            file_count=file_count,
            total_size=total_size,
            datasets=len(datasets),
            symbols=len(symbols),
            computed_at=time.time(),
        )

    def _scan_dirs_fast(
        self, parquet_dir: Path, dir_filter: set[str] | None
    ) -> ParquetStats:
        """快速扫描 — 只统计文件数和目录数，不逐文件 stat() 以节省时间"""
        if not parquet_dir.exists():
            return ParquetStats(computed_at=time.time())

        symbols: set[str] = set()
        datasets: set[str] = set()
        file_count = 0
        # 用 os.walk 比 pathlib.rglob 快很多
        parquet_str = str(parquet_dir)

        for ex_dir in os.scandir(parquet_dir):
            if not ex_dir.is_dir():
                continue
            if dir_filter is not None and ex_dir.name not in dir_filter:
                continue

            for root, dirs, files in os.walk(ex_dir.path):
                for f in files:
                    if f.endswith(".parquet"):
                        file_count += 1
                # 提取 symbol 和 dataset
                rel = os.path.relpath(root, parquet_str)
                parts = rel.split(os.sep)
                if len(parts) >= 2:
                    symbols.add(parts[1])
                if len(parts) >= 3:
                    datasets.add(f"{parts[0]}/{parts[1]}/{parts[2]}")

        return ParquetStats(
            file_count=file_count,
            total_size=0,  # fast 模式不计算大小
            datasets=len(datasets),
            symbols=len(symbols),
            computed_at=time.time(),
        )


# 全局单例
_cache = _ParquetStatsCache()


def get_parquet_cache() -> _ParquetStatsCache:
    return _cache
