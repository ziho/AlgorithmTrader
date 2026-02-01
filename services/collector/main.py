"""
数据采集服务

职责:
- 定时从 OKX 拉取 OHLCV 数据（15m / 1h）
- 同时写入 Parquet (历史归档) 和 InfluxDB (实时监控)
- 支持缺口检测和自动补全
- 使用 APScheduler 调度

运行方式:
    python -m services.collector.main
"""

import asyncio
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import get_settings
from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.data.connectors.okx import OKXConnector
from src.data.storage.influx_store import InfluxStore
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import get_logger

logger = get_logger(__name__)


class DataCollector:
    """
    数据采集器

    特点:
    - 支持多交易对、多时间框架
    - Bar close 后延迟采集（避免数据未完全落地）
    - 自动缺口检测和补全
    - 双写: Parquet + InfluxDB
    """

    # 默认采集配置
    DEFAULT_SYMBOLS = [
        Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT"),
        Symbol(exchange=Exchange.OKX, base="ETH", quote="USDT"),
    ]

    DEFAULT_TIMEFRAMES = [Timeframe.M15, Timeframe.H1]

    def __init__(
        self,
        symbols: list[Symbol] | None = None,
        timeframes: list[Timeframe] | None = None,
        bar_close_delay: int = 10,
        parquet_store: ParquetStore | None = None,
        influx_store: InfluxStore | None = None,
        influx_url: str | None = None,
        influx_token: str | None = None,
    ):
        """
        初始化数据采集器

        Args:
            symbols: 要采集的交易对列表
            timeframes: 要采集的时间框架列表
            bar_close_delay: Bar close 后的延迟秒数
            parquet_store: Parquet 存储实例
            influx_store: InfluxDB 存储实例
            influx_url: InfluxDB URL（如果不提供 influx_store）
            influx_token: InfluxDB Token
        """
        settings = get_settings()

        self.symbols = symbols or self.DEFAULT_SYMBOLS
        self.timeframes = timeframes or self.DEFAULT_TIMEFRAMES
        self.bar_close_delay = bar_close_delay or settings.bar_close_delay

        # 存储
        self._parquet_store = parquet_store
        self._influx_store = influx_store
        self._influx_url = influx_url
        self._influx_token = influx_token

        # OKX 连接器（惰性初始化）
        self._connector: OKXConnector | None = None

        # 调度器
        self._scheduler = AsyncIOScheduler()

        # 运行状态
        self._running = False

        logger.info(
            "collector_initialized",
            symbols=[str(s) for s in self.symbols],
            timeframes=[tf.value for tf in self.timeframes],
            bar_close_delay=self.bar_close_delay,
        )

    async def _get_connector(self) -> OKXConnector:
        """获取 OKX 连接器"""
        if self._connector is None:
            self._connector = OKXConnector()
        return self._connector

    def _get_parquet_store(self) -> ParquetStore:
        """获取 Parquet 存储"""
        if self._parquet_store is None:
            self._parquet_store = ParquetStore()
        return self._parquet_store

    def _get_influx_store(self) -> InfluxStore:
        """获取 InfluxDB 存储"""
        if self._influx_store is None:
            self._influx_store = InfluxStore(
                url=self._influx_url,
                token=self._influx_token,
            )
        return self._influx_store

    async def collect_bars(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        limit: int = 10,
    ) -> int:
        """
        采集 K 线数据

        Args:
            symbol: 交易对
            timeframe: 时间框架
            limit: 获取的 K 线数量

        Returns:
            写入的行数
        """
        try:
            connector = await self._get_connector()

            # 拉取数据
            df = await connector.fetch_ohlcv(symbol, timeframe, limit=limit)

            if df.empty:
                logger.warning(
                    "collect_empty_result",
                    symbol=str(symbol),
                    timeframe=timeframe.value,
                )
                return 0

            # 写入 Parquet
            parquet_store = self._get_parquet_store()
            parquet_rows = parquet_store.write(symbol, timeframe, df)

            # 写入 InfluxDB（只写最新几根）
            influx_store = self._get_influx_store()
            latest_df = df.tail(3)  # 最新 3 根
            influx_points = influx_store.write_ohlcv(symbol, timeframe, latest_df)

            logger.info(
                "bars_collected",
                symbol=str(symbol),
                timeframe=timeframe.value,
                parquet_rows=parquet_rows,
                influx_points=influx_points,
                latest_close=float(df.iloc[-1]["close"]),
            )

            return parquet_rows

        except Exception as e:
            logger.error(
                "collect_failed",
                symbol=str(symbol),
                timeframe=timeframe.value,
                error=str(e),
            )
            return 0

    async def collect_all(self) -> dict[str, int]:
        """
        采集所有配置的交易对和时间框架

        Returns:
            采集结果 {symbol_timeframe: rows}
        """
        results = {}

        for symbol in self.symbols:
            for timeframe in self.timeframes:
                key = f"{symbol}_{timeframe.value}"
                rows = await self.collect_bars(symbol, timeframe)
                results[key] = rows

        return results

    async def backfill(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: datetime,
        end: datetime | None = None,
    ) -> int:
        """
        补全历史数据

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start: 开始时间
            end: 结束时间，默认为当前

        Returns:
            写入的总行数
        """
        if end is None:
            end = datetime.now(UTC)

        logger.info(
            "backfill_start",
            symbol=str(symbol),
            timeframe=timeframe.value,
            start=start.isoformat(),
            end=end.isoformat(),
        )

        connector = await self._get_connector()
        parquet_store = self._get_parquet_store()

        total_rows = 0
        current_start = start
        batch_size = 100

        while current_start < end:
            # 拉取数据
            df = await connector.fetch_ohlcv(
                symbol,
                timeframe,
                since=current_start,
                limit=batch_size,
            )

            if df.empty:
                break

            # 写入 Parquet
            rows = parquet_store.write(symbol, timeframe, df)
            total_rows += rows

            # 更新游标：使用最新的时间戳 + 1个周期
            newest_ts = df["timestamp"].max()
            if newest_ts.tzinfo is None:
                newest_ts = newest_ts.replace(tzinfo=UTC)

            # 移动到下一个周期
            current_start = newest_ts.to_pydatetime() + timeframe.timedelta

            logger.debug(
                "backfill_batch",
                symbol=str(symbol),
                timeframe=timeframe.value,
                rows=len(df),
                newest=newest_ts.isoformat(),
            )

            # 如果获取的数据少于请求的，说明到达末尾
            if len(df) < batch_size:
                break

            # 避免请求过快
            await asyncio.sleep(0.1)

        logger.info(
            "backfill_complete",
            symbol=str(symbol),
            timeframe=timeframe.value,
            total_rows=total_rows,
        )

        return total_rows

    async def detect_and_fill_gaps(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
    ) -> int:
        """
        检测并补全数据缺口

        Args:
            symbol: 交易对
            timeframe: 时间框架

        Returns:
            补全的行数
        """
        parquet_store = self._get_parquet_store()
        gaps = parquet_store.detect_gaps(symbol, timeframe)

        if not gaps:
            return 0

        logger.info(
            "gaps_detected",
            symbol=str(symbol),
            timeframe=timeframe.value,
            gap_count=len(gaps),
        )

        total_filled = 0

        for gap_start, gap_end in gaps:
            rows = await self.backfill(symbol, timeframe, gap_start, gap_end)
            total_filled += rows

        return total_filled

    def _create_cron_trigger(self, timeframe: Timeframe) -> CronTrigger:
        """
        为时间框架创建 cron 触发器

        在 bar close 后 N 秒触发
        """
        delay_seconds = self.bar_close_delay
        delay_minutes = delay_seconds // 60
        delay_in_minute = delay_seconds % 60

        if timeframe == Timeframe.M15:
            # 每15分钟: 0, 15, 30, 45 分 + 延迟
            return CronTrigger(minute="0,15,30,45", second=delay_in_minute)

        elif timeframe == Timeframe.M30:
            # 每30分钟: 0, 30 分 + 延迟
            return CronTrigger(minute="0,30", second=delay_in_minute)

        elif timeframe == Timeframe.H1:
            # 每小时: 0 分 + 延迟
            return CronTrigger(minute=delay_minutes, second=delay_in_minute)

        elif timeframe == Timeframe.H4:
            # 每4小时: 0, 4, 8, 12, 16, 20 时
            return CronTrigger(
                hour="0,4,8,12,16,20", minute=delay_minutes, second=delay_in_minute
            )

        elif timeframe == Timeframe.D1:
            # 每天 00:00 + 延迟
            return CronTrigger(hour=0, minute=delay_minutes, second=delay_in_minute)

        else:
            # 默认每分钟
            return CronTrigger(second=delay_in_minute)

    async def _scheduled_collect(self, symbol: Symbol, timeframe: Timeframe):
        """调度任务回调"""
        await self.collect_bars(symbol, timeframe, limit=5)

    async def _scheduled_collect_funding_rate(self, symbol: Symbol):
        """资金费率采集回调"""
        await self.collect_funding_rate(symbol)

    async def collect_funding_rate(self, symbol: Symbol) -> bool:
        """
        采集资金费率

        Args:
            symbol: 交易对 (永续合约)

        Returns:
            是否成功
        """
        try:
            connector = await self._get_connector()

            # 拉取当前资金费率
            funding_data = await connector.fetch_funding_rate(symbol)

            if not funding_data:
                logger.warning(
                    "funding_rate_empty",
                    symbol=str(symbol),
                )
                return False

            # 解析数据
            funding_rate = float(funding_data.get("fundingRate", 0) or 0)
            funding_ts = funding_data.get("timestamp")
            next_funding_ts = funding_data.get("fundingTimestamp")

            # 转换时间戳
            import pandas as pd

            funding_time = None
            if funding_ts:
                funding_time = pd.to_datetime(
                    funding_ts, unit="ms", utc=True
                ).to_pydatetime()

            next_funding_time = None
            if next_funding_ts:
                next_funding_time = pd.to_datetime(
                    next_funding_ts, unit="ms", utc=True
                ).to_pydatetime()

            # 写入 InfluxDB
            influx_store = self._get_influx_store()
            influx_store.write_funding_rate(
                symbol=symbol,
                funding_rate=funding_rate,
                funding_timestamp=funding_time,
                next_funding_time=next_funding_time,
            )

            logger.info(
                "funding_rate_collected",
                symbol=str(symbol),
                funding_rate=funding_rate,
            )

            return True

        except Exception as e:
            logger.error(
                "collect_funding_rate_failed",
                symbol=str(symbol),
                error=str(e),
            )
            return False

    async def collect_all_funding_rates(self) -> dict[str, bool]:
        """
        采集所有交易对的资金费率

        Returns:
            采集结果 {symbol: success}
        """
        results = {}

        for symbol in self.symbols:
            success = await self.collect_funding_rate(symbol)
            results[str(symbol)] = success

        return results

    async def backfill_funding_rates(
        self,
        symbol: Symbol,
        since: datetime,
        limit: int = 100,
    ) -> int:
        """
        回填资金费率历史

        Args:
            symbol: 交易对
            since: 开始时间
            limit: 数量限制

        Returns:
            写入的记录数
        """
        try:
            connector = await self._get_connector()

            # 拉取历史资金费率
            df = await connector.fetch_funding_rate_history(
                symbol=symbol,
                since=since,
                limit=limit,
            )

            if df.empty:
                logger.warning(
                    "funding_rate_history_empty",
                    symbol=str(symbol),
                )
                return 0

            # 写入 InfluxDB
            influx_store = self._get_influx_store()
            points = influx_store.write_funding_rates_batch(symbol, df)

            logger.info(
                "funding_rates_backfilled",
                symbol=str(symbol),
                points=points,
            )

            return points

        except Exception as e:
            logger.error(
                "backfill_funding_rates_failed",
                symbol=str(symbol),
                error=str(e),
            )
            return 0

    def start(self):
        """启动调度器"""
        if self._running:
            return

        # 为每个交易对和时间框架添加 K 线采集任务
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                trigger = self._create_cron_trigger(timeframe)
                job_id = f"collect_{symbol}_{timeframe.value}"

                self._scheduler.add_job(
                    self._scheduled_collect,
                    trigger=trigger,
                    id=job_id,
                    args=[symbol, timeframe],
                    replace_existing=True,
                )

                logger.info(
                    "job_scheduled",
                    job_id=job_id,
                    trigger=str(trigger),
                )

            # 为每个交易对添加资金费率采集任务 (每8小时，与结算周期对齐)
            funding_trigger = CronTrigger(hour="0,8,16", minute=1, second=0)
            funding_job_id = f"funding_{symbol}"

            self._scheduler.add_job(
                self._scheduled_collect_funding_rate,
                trigger=funding_trigger,
                id=funding_job_id,
                args=[symbol],
                replace_existing=True,
            )

            logger.info(
                "funding_job_scheduled",
                job_id=funding_job_id,
                trigger=str(funding_trigger),
            )

        self._scheduler.start()
        self._running = True

        logger.info("collector_started")

    def stop(self):
        """停止调度器"""
        if not self._running:
            return

        self._scheduler.shutdown()
        self._running = False

        logger.info("collector_stopped")

    async def close(self):
        """关闭所有资源"""
        self.stop()

        if self._connector:
            await self._connector.close()

        if self._parquet_store:
            self._parquet_store.close()

        if self._influx_store:
            self._influx_store.close()


async def run_collector(
    symbols: list[Symbol] | None = None,
    timeframes: list[Timeframe] | None = None,
    initial_backfill_hours: int = 24,
    influx_url: str | None = None,
    influx_token: str | None = None,
):
    """
    运行数据采集服务

    Args:
        symbols: 交易对列表
        timeframes: 时间框架列表
        initial_backfill_hours: 初始回填小时数
        influx_url: InfluxDB URL
        influx_token: InfluxDB Token
    """
    collector = DataCollector(
        symbols=symbols,
        timeframes=timeframes,
        influx_url=influx_url,
        influx_token=influx_token,
    )

    try:
        # 初始回填
        if initial_backfill_hours > 0:
            start = datetime.now(UTC) - timedelta(hours=initial_backfill_hours)

            for symbol in collector.symbols:
                for timeframe in collector.timeframes:
                    await collector.backfill(symbol, timeframe, start)

        # 启动定时采集
        collector.start()

        # 保持运行
        while True:
            await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("collector_interrupted")
    finally:
        await collector.close()


def main():
    """Collector 服务主入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Data Collector Service")
    parser.add_argument(
        "--backfill-hours",
        type=int,
        default=24,
        help="Initial backfill hours (default: 24)",
    )
    parser.add_argument(
        "--influx-url",
        type=str,
        default="http://influxdb:8086",
        help="InfluxDB URL",
    )
    parser.add_argument(
        "--influx-token",
        type=str,
        default="algorithmtrader-dev-token",
        help="InfluxDB Token",
    )

    args = parser.parse_args()

    asyncio.run(
        run_collector(
            initial_backfill_hours=args.backfill_hours,
            influx_url=args.influx_url,
            influx_token=args.influx_token,
        )
    )


if __name__ == "__main__":
    main()
