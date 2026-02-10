"""
数据获取模块集成测试

测试真实网络请求（需要网络连接）:
- 从 Binance API 获取数据
- 断点续传与恢复
- 缺口检测与补齐
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# 标记为集成测试（需要网络）
pytestmark = pytest.mark.integration


@pytest.fixture
def temp_data_dir():
    """创建临时数据目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestBinanceDataFetch:
    """Binance 数据获取集成测试"""

    @pytest.mark.asyncio
    async def test_fetch_recent_klines(self, temp_data_dir):
        """测试获取最近的 K 线数据"""
        from src.data.fetcher.realtime import RealtimeSyncer

        syncer = RealtimeSyncer(
            symbols=["BTCUSDT"],
            timeframes=["1m"],
            exchange="binance",
            data_dir=str(temp_data_dir),
        )

        try:
            df = await syncer.fetch_latest_bars("BTCUSDT", "1m", limit=10)

            assert not df.empty
            assert len(df) <= 10
            assert list(df.columns) == [
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
            assert df["timestamp"].dtype.name.startswith("datetime64")

            print(f"\n获取到 {len(df)} 条 K 线数据:")
            print(df.tail())

        finally:
            await syncer.close()

    @pytest.mark.asyncio
    async def test_sync_to_latest(self, temp_data_dir):
        """测试同步到最新"""
        from src.data.fetcher.realtime import RealtimeSyncer

        syncer = RealtimeSyncer(
            symbols=["BTCUSDT"],
            timeframes=["1m"],
            exchange="binance",
            data_dir=str(temp_data_dir),
        )

        try:
            # 初始同步
            rows = await syncer.sync_to_latest("BTCUSDT", "1m")

            print(f"\n同步了 {rows} 行数据")
            assert rows >= 0

            # 验证数据已保存
            from src.core.instruments import Exchange, Symbol
            from src.core.timeframes import Timeframe

            sym = Symbol(exchange=Exchange.BINANCE, base="BTC", quote="USDT")
            data_range = syncer._parquet_store.get_data_range(sym, Timeframe.M1)

            if rows > 0:
                assert data_range is not None
                print(f"数据范围: {data_range}")

        finally:
            await syncer.close()


class TestHistoryDownload:
    """历史数据下载集成测试"""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_download_single_month(self, temp_data_dir):
        """测试下载单月数据"""
        from src.data.fetcher.history import HistoryFetcher

        fetcher = HistoryFetcher(
            data_dir=temp_data_dir,
            exchange="binance",
            verify_checksum=False,  # 加速测试
        )

        try:
            # 下载最近一个完整月份
            now = datetime.now(UTC)
            if now.month == 1:
                year, month = now.year - 1, 12
            else:
                year, month = now.year, now.month - 1

            df, is_new = await fetcher.download_month(
                symbol="BTCUSDT",
                timeframe="1m",
                year=year,
                month=month,
            )

            if not df.empty:
                print(f"\n下载了 {year}-{month:02d} 的 {len(df)} 条数据")
                print(df.head())

                # 验证断点
                assert fetcher.checkpoint.is_completed(
                    "binance", "BTCUSDT", "1m", year, month
                )
            else:
                print(f"\n{year}-{month:02d} 无数据可用")

        finally:
            await fetcher.close()

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_checkpoint_resume(self, temp_data_dir):
        """测试断点续传"""
        from src.data.fetcher.history import HistoryFetcher

        # 第一次下载
        fetcher1 = HistoryFetcher(data_dir=temp_data_dir, verify_checksum=False)

        try:
            now = datetime.now(UTC)
            if now.month <= 2:
                year, month = now.year - 1, 11
            else:
                year, month = now.year, now.month - 2

            df1, is_new1 = await fetcher1.download_month("BTCUSDT", "1m", year, month)

            if df1.empty:
                pytest.skip("No data available for this month")

            assert is_new1

        finally:
            await fetcher1.close()

        # 第二次下载（应跳过）
        fetcher2 = HistoryFetcher(data_dir=temp_data_dir, verify_checksum=False)

        try:
            df2, is_new2 = await fetcher2.download_month(
                "BTCUSDT",
                "1m",
                year,
                month,
                skip_existing=True,
            )

            # 应该跳过，返回空 DataFrame
            assert df2.empty
            assert not is_new2

            print(f"\n断点续传正常: {year}-{month:02d} 已跳过")

        finally:
            await fetcher2.close()


class TestDataManager:
    """数据管理器集成测试"""

    def test_get_history_empty(self, temp_data_dir):
        """测试获取空数据"""
        from src.data.fetcher.manager import DataManager

        manager = DataManager(data_dir=temp_data_dir)

        df = manager.get_history(
            "binance", "BTCUSDT", "2024-01-01", "2024-01-31", tf="1m"
        )

        assert df.empty or len(df) == 0

    @pytest.mark.asyncio
    async def test_full_workflow(self, temp_data_dir):
        """测试完整工作流: 下载 -> 读取 -> 聚合"""
        from src.data.fetcher.history import HistoryFetcher
        from src.data.fetcher.manager import DataManager

        # 1. 下载数据
        fetcher = HistoryFetcher(data_dir=temp_data_dir, verify_checksum=False)

        try:
            now = datetime.now(UTC)
            if now.month <= 1:
                year, month = now.year - 1, 11
            else:
                year, month = now.year, now.month - 2

            df, _ = await fetcher.download_month("BTCUSDT", "1m", year, month)

            if df.empty:
                pytest.skip("No data available")

        finally:
            await fetcher.close()

        # 2. 使用 DataManager 读取
        manager = DataManager(data_dir=temp_data_dir)

        start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(seconds=1)
        else:
            end = datetime(year, month + 1, 1, tzinfo=UTC) - timedelta(seconds=1)

        result = manager.get_history("binance", "BTCUSDT", start, end, tf="1m")

        assert not result.empty
        print(f"\n读取到 {len(result)} 条数据")

        # 3. 聚合到 1h
        hourly = manager.aggregate_to_higher_tf(result, "1m", "1h")

        assert len(hourly) < len(result)
        print(f"聚合后 {len(hourly)} 条小时数据")


class TestGapHandling:
    """缺口处理集成测试"""

    @pytest.mark.asyncio
    async def test_gap_detection_and_fill(self, temp_data_dir):
        """测试缺口检测和修复"""
        from src.data.fetcher.realtime import RealtimeSyncer

        syncer = RealtimeSyncer(
            symbols=["BTCUSDT"],
            timeframes=["1m"],
            exchange="binance",
            data_dir=str(temp_data_dir),
        )

        try:
            # 先同步一些数据
            await syncer.sync_to_latest("BTCUSDT", "1m")

            # 检查缺口
            gaps = await syncer.check_and_fill_gaps("BTCUSDT", "1m")
            print(f"\n检测并修复了 {gaps} 条缺口数据")

        finally:
            await syncer.close()


if __name__ == "__main__":
    # 运行测试
    pytest.main(
        [
            __file__,
            "-v",
            "-m",
            "not slow",  # 默认跳过慢速测试
            "--tb=short",
        ]
    )
