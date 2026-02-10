"""
实时数据追赶与同步器

支持:
- 从最新落盘时间戳开始追赶
- REST API 补齐缺口
- WebSocket 实时流
- 多交易对并发监听
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import aiohttp
import pandas as pd

from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SyncStats:
    """同步统计"""

    symbol: str
    timeframe: str
    gaps_found: int = 0
    gaps_filled: int = 0
    bars_written: int = 0
    last_sync: datetime | None = None
    errors: list = field(default_factory=list)


class RealtimeSyncer:
    """
    实时数据追赶与同步器

    特点:
    - 启动时自动检测并补齐缺口
    - 支持 WebSocket 实时更新
    - 定期与 REST 快照对比纠偏
    - 多交易对并发支持
    """

    # Binance WebSocket 端点
    BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
    BINANCE_API_URL = "https://api.binance.com"

    # 时间框架映射
    WS_INTERVALS = {
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
        "1w": "1w",
    }

    def __init__(
        self,
        symbols: list[str],
        timeframes: list[str],
        exchange: str = "binance",
        parquet_store: ParquetStore | None = None,
        data_dir: str = "./data",
        gap_check_interval: int = 300,  # 5 分钟检查一次缺口
        on_bar_callback: Callable | None = None,
    ):
        """
        初始化同步器

        Args:
            symbols: 交易对列表 (如 ["BTCUSDT", "ETHUSDT"])
            timeframes: 时间框架列表 (如 ["1m", "1h"])
            exchange: 交易所
            parquet_store: Parquet 存储实例
            data_dir: 数据目录
            gap_check_interval: 缺口检查间隔（秒）
            on_bar_callback: 新 bar 回调函数
        """
        self.symbols = [s.replace("/", "").upper() for s in symbols]
        self.timeframes = timeframes
        self.exchange = exchange.lower()
        self.gap_check_interval = gap_check_interval
        self.on_bar_callback = on_bar_callback

        # 存储
        self._parquet_store = parquet_store or ParquetStore(
            base_path=f"{data_dir}/parquet"
        )

        # HTTP/WS 会话
        self._http_session: aiohttp.ClientSession | None = None
        self._ws_connections: dict[str, aiohttp.ClientWebSocketResponse] = {}

        # 运行状态
        self._running = False
        self._tasks: list[asyncio.Task] = []

        # 统计
        self._stats: dict[str, SyncStats] = {}

        # 最近的 bar 缓存 (用于检测重复)
        self._last_bars: dict[str, datetime] = {}

        logger.info(
            "realtime_syncer_initialized",
            symbols=self.symbols,
            timeframes=self.timeframes,
            exchange=self.exchange,
        )

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """获取 HTTP 会话"""
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._http_session = aiohttp.ClientSession(timeout=timeout)
        return self._http_session

    async def close(self) -> None:
        """关闭所有连接"""
        self._running = False

        # 取消任务
        for task in self._tasks:
            task.cancel()

        # 关闭 WebSocket
        for ws in self._ws_connections.values():
            await ws.close()
        self._ws_connections.clear()

        # 关闭 HTTP
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

        logger.info("realtime_syncer_closed")

    async def __aenter__(self) -> "RealtimeSyncer":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    def _get_symbol_obj(self, symbol: str) -> Symbol:
        """转换为 Symbol 对象"""
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            quote = "USDT"
        elif symbol.endswith("BUSD"):
            base = symbol[:-4]
            quote = "BUSD"
        else:
            base = symbol[:-3]
            quote = symbol[-3:]

        exchange = Exchange.BINANCE if self.exchange == "binance" else Exchange.OKX
        return Symbol(exchange=exchange, base=base, quote=quote)

    async def fetch_latest_bars(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        从 REST API 获取最新 K 线

        Args:
            symbol: 交易对
            timeframe: 时间框架
            limit: 数量限制

        Returns:
            DataFrame
        """
        session = await self._get_http_session()
        interval = self.WS_INTERVALS.get(timeframe, timeframe)

        url = f"{self.BINANCE_API_URL}/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000),
        }

        try:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(
                        "fetch_klines_error",
                        symbol=symbol,
                        status=response.status,
                    )
                    return pd.DataFrame()

                data = await response.json()

                if not data:
                    return pd.DataFrame()

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

                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = df[col].astype(float)

                return df[["timestamp", "open", "high", "low", "close", "volume"]]

        except Exception as e:
            logger.error(
                "fetch_klines_exception",
                symbol=symbol,
                error=str(e),
            )
            return pd.DataFrame()

    async def backfill_gap(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """
        回填缺口

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start: 缺口开始
            end: 缺口结束

        Returns:
            写入的行数
        """
        logger.info(
            "backfill_gap_start",
            symbol=symbol,
            timeframe=timeframe,
            start=start.isoformat(),
            end=end.isoformat(),
        )

        session = await self._get_http_session()
        interval = self.WS_INTERVALS.get(timeframe, timeframe)
        sym = self._get_symbol_obj(symbol)
        tf = Timeframe(timeframe)

        all_data = []
        current = start

        while current < end:
            url = f"{self.BINANCE_API_URL}/api/v3/klines"
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": int(current.timestamp() * 1000),
                "limit": 1000,
            }

            try:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        break

                    data = await response.json()
                    if not data:
                        break

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

                    df["timestamp"] = pd.to_datetime(
                        df["timestamp"], unit="ms", utc=True
                    )
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = df[col].astype(float)

                    all_data.append(
                        df[["timestamp", "open", "high", "low", "close", "volume"]]
                    )

                    # 更新 current
                    last_ts = df["timestamp"].max()
                    current = last_ts.to_pydatetime() + tf.timedelta

            except Exception as e:
                logger.error("backfill_error", error=str(e))
                break

            await asyncio.sleep(0.2)

        if all_data:
            result = pd.concat(all_data, ignore_index=True)
            result = result[
                (result["timestamp"] >= pd.Timestamp(start, tz="UTC"))
                & (result["timestamp"] <= pd.Timestamp(end, tz="UTC"))
            ]
            result = result.drop_duplicates(subset=["timestamp"])

            rows = self._parquet_store.write(sym, tf, result)

            logger.info(
                "backfill_gap_complete",
                symbol=symbol,
                rows=rows,
            )
            return rows

        return 0

    async def check_and_fill_gaps(
        self,
        symbol: str,
        timeframe: str,
    ) -> int:
        """
        检查并填充缺口

        Returns:
            填充的行数
        """
        sym = self._get_symbol_obj(symbol)
        tf = Timeframe(timeframe)

        # 检测缺口
        gaps = self._parquet_store.detect_gaps(sym, tf)

        if not gaps:
            return 0

        key = f"{symbol}_{timeframe}"
        if key not in self._stats:
            self._stats[key] = SyncStats(symbol=symbol, timeframe=timeframe)

        self._stats[key].gaps_found += len(gaps)

        total_filled = 0
        for gap_start, gap_end in gaps:
            rows = await self.backfill_gap(symbol, timeframe, gap_start, gap_end)
            total_filled += rows
            self._stats[key].gaps_filled += 1

        return total_filled

    async def sync_to_latest(
        self,
        symbol: str,
        timeframe: str,
    ) -> int:
        """
        同步到最新

        Args:
            symbol: 交易对
            timeframe: 时间框架

        Returns:
            写入的行数
        """
        sym = self._get_symbol_obj(symbol)
        tf = Timeframe(timeframe)

        # 获取本地最新时间
        data_range = self._parquet_store.get_data_range(sym, tf)

        if data_range:
            _, latest_local = data_range
            # 从最新时间开始补齐
            start = latest_local + tf.timedelta
        else:
            # 没有数据，从最近 7 天开始
            start = datetime.now(UTC) - timedelta(days=7)

        end = datetime.now(UTC)

        if start >= end:
            logger.debug(
                "already_up_to_date",
                symbol=symbol,
                timeframe=timeframe,
            )
            return 0

        logger.info(
            "syncing_to_latest",
            symbol=symbol,
            timeframe=timeframe,
            from_time=start.isoformat(),
        )

        # 获取最新数据
        df = await self.fetch_latest_bars(symbol, timeframe, limit=1000)

        if df.empty:
            return 0

        # 过滤只保留新数据
        df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]

        if df.empty:
            return 0

        # 写入
        rows = self._parquet_store.write(sym, tf, df)

        key = f"{symbol}_{timeframe}"
        if key not in self._stats:
            self._stats[key] = SyncStats(symbol=symbol, timeframe=timeframe)
        self._stats[key].bars_written += rows
        self._stats[key].last_sync = datetime.now(UTC)

        logger.info(
            "sync_complete",
            symbol=symbol,
            timeframe=timeframe,
            rows=rows,
        )

        return rows

    async def _ws_kline_handler(
        self,
        symbol: str,
        timeframe: str,
    ) -> None:
        """WebSocket K 线处理器"""
        interval = self.WS_INTERVALS.get(timeframe, timeframe)
        stream = f"{symbol.lower()}@kline_{interval}"
        ws_url = f"{self.BINANCE_WS_URL}/{stream}"

        key = f"{symbol}_{timeframe}"
        sym = self._get_symbol_obj(symbol)
        tf = Timeframe(timeframe)

        while self._running:
            try:
                session = await self._get_http_session()

                async with session.ws_connect(ws_url) as ws:
                    self._ws_connections[key] = ws
                    logger.info(
                        "ws_connected",
                        symbol=symbol,
                        timeframe=timeframe,
                    )

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.json()

                            if "k" in data:
                                kline = data["k"]

                                # 只处理已关闭的 K 线
                                if kline.get("x", False):
                                    ts = pd.Timestamp(kline["t"], unit="ms", tz="UTC")

                                    # 检查重复
                                    last_key = f"{symbol}_{timeframe}"
                                    if (
                                        last_key in self._last_bars
                                        and ts <= self._last_bars[last_key]
                                    ):
                                        continue

                                    self._last_bars[last_key] = ts

                                    # 构建 DataFrame
                                    bar_df = pd.DataFrame(
                                        [
                                            {
                                                "timestamp": ts,
                                                "open": float(kline["o"]),
                                                "high": float(kline["h"]),
                                                "low": float(kline["l"]),
                                                "close": float(kline["c"]),
                                                "volume": float(kline["v"]),
                                            }
                                        ]
                                    )

                                    # 写入
                                    rows = self._parquet_store.write(sym, tf, bar_df)

                                    if key not in self._stats:
                                        self._stats[key] = SyncStats(
                                            symbol=symbol, timeframe=timeframe
                                        )
                                    self._stats[key].bars_written += rows
                                    self._stats[key].last_sync = datetime.now(UTC)

                                    # 回调
                                    if self.on_bar_callback:
                                        try:
                                            self.on_bar_callback(
                                                symbol, timeframe, bar_df
                                            )
                                        except Exception as e:
                                            logger.error("callback_error", error=str(e))

                                    logger.debug(
                                        "ws_bar_received",
                                        symbol=symbol,
                                        timeframe=timeframe,
                                        timestamp=ts.isoformat(),
                                        close=float(kline["c"]),
                                    )

                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(
                                "ws_error",
                                symbol=symbol,
                                error=str(ws.exception()),
                            )
                            break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "ws_connection_error",
                    symbol=symbol,
                    timeframe=timeframe,
                    error=str(e),
                )

                if self._running:
                    await asyncio.sleep(5)  # 重连延迟

        self._ws_connections.pop(key, None)
        logger.info(
            "ws_disconnected",
            symbol=symbol,
            timeframe=timeframe,
        )

    async def _gap_check_loop(self) -> None:
        """缺口检查循环"""
        while self._running:
            try:
                for symbol in self.symbols:
                    for timeframe in self.timeframes:
                        # 同步到最新
                        await self.sync_to_latest(symbol, timeframe)

                        # 检查缺口
                        await self.check_and_fill_gaps(symbol, timeframe)

                        await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("gap_check_error", error=str(e))

            await asyncio.sleep(self.gap_check_interval)

    async def start(self) -> None:
        """启动同步器"""
        self._running = True

        logger.info(
            "realtime_syncer_starting",
            symbols=self.symbols,
            timeframes=self.timeframes,
        )

        # 初始同步
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                await self.sync_to_latest(symbol, timeframe)
                await self.check_and_fill_gaps(symbol, timeframe)

        # 启动 WebSocket
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                task = asyncio.create_task(self._ws_kline_handler(symbol, timeframe))
                self._tasks.append(task)

        # 启动缺口检查
        gap_task = asyncio.create_task(self._gap_check_loop())
        self._tasks.append(gap_task)

        logger.info(
            "realtime_syncer_started",
            ws_streams=len(self._tasks) - 1,
        )

    async def run_forever(self) -> None:
        """运行直到停止"""
        await self.start()

        try:
            # 等待所有任务
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        finally:
            await self.close()

    def get_stats(self) -> dict[str, SyncStats]:
        """获取统计信息"""
        return self._stats.copy()
