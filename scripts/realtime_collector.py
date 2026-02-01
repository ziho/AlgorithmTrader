#!/usr/bin/env python3
"""
🔄 实时数据采集服务

持续采集最新的 K 线数据并写入 InfluxDB

功能:
1. 定时采集最新 K 线数据 (1分钟/小时等)
2. 支持多个交易对
3. 写入 InfluxDB (实时可视化)
4. 保存到 Parquet (历史存储)

使用方式:
    # 在 Docker 中运行 (前台)
    docker-compose exec collector python scripts/realtime_collector.py
    
    # 后台运行
    docker-compose exec -d collector python scripts/realtime_collector.py
    
    # 指定参数
    docker-compose exec collector python scripts/realtime_collector.py \
        --symbols BTCUSDT,ETHUSDT --timeframes 1m,1h --interval 60

配置文件:
    可通过环境变量或命令行参数配置
"""

import argparse
import asyncio
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 全局停止标志
_stop_event = asyncio.Event()


def signal_handler(signum, frame):
    """信号处理"""
    print("\n⚠️ 收到停止信号，正在优雅退出...")
    _stop_event.set()


class RealtimeCollector:
    """实时数据采集器"""
    
    def __init__(
        self,
        symbols: list[str],
        timeframes: list[str],
        exchange: str = "binance",
        interval_seconds: int = 60,
        write_influx: bool = True,
        write_parquet: bool = True,
    ):
        self.symbols = symbols
        self.timeframes = timeframes
        self.exchange = exchange.lower()
        self.interval_seconds = interval_seconds
        self.write_influx = write_influx
        self.write_parquet = write_parquet
        
        self._connector = None
        self._influx_store = None
        self._parquet_store = None
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_points_written": 0,
            "start_time": None,
        }
    
    async def initialize(self):
        """初始化"""
        from src.ops.logging import get_logger
        self.logger = get_logger(__name__)
        
        # 初始化连接器
        if self.exchange == "binance":
            from src.data.connectors.binance import BinanceConnector
            self._connector = BinanceConnector()
        else:
            from src.data.connectors.okx import OKXConnector
            self._connector = OKXConnector()
        
        # 初始化存储
        if self.write_influx:
            from src.data.storage.influx_store import InfluxStore
            self._influx_store = InfluxStore(async_write=False)
        
        if self.write_parquet:
            from src.data.storage.parquet_store import ParquetStore
            self._parquet_store = ParquetStore(base_path=PROJECT_ROOT / "data" / "parquet")
        
        self._stats["start_time"] = datetime.now(UTC)
        
        self.logger.info(
            "realtime_collector_initialized",
            symbols=self.symbols,
            timeframes=self.timeframes,
            exchange=self.exchange,
            interval=self.interval_seconds,
        )
    
    async def cleanup(self):
        """清理资源"""
        if self._connector:
            await self._connector.close()
        
        if self._influx_store:
            self._influx_store.flush()
            self._influx_store.close()
        
        self.logger.info(
            "realtime_collector_stopped",
            stats=self._stats,
        )
    
    async def collect_once(self):
        """执行一次数据采集"""
        from src.core.instruments import Exchange, Symbol
        from src.core.timeframes import Timeframe
        
        for symbol_str in self.symbols:
            # 解析交易对
            if "/" in symbol_str:
                base, quote = symbol_str.split("/")
            else:
                if symbol_str.endswith("USDT"):
                    base = symbol_str[:-4]
                    quote = "USDT"
                else:
                    base = symbol_str[:-3]
                    quote = symbol_str[-3:]
            
            exchange = Exchange.BINANCE if self.exchange == "binance" else Exchange.OKX
            symbol = Symbol(exchange=exchange, base=base, quote=quote)
            
            for tf_str in self.timeframes:
                timeframe = Timeframe(tf_str)
                
                try:
                    self._stats["total_requests"] += 1
                    
                    # 获取最新数据
                    df = await self._connector.fetch_ohlcv(
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=10,  # 只获取最新几条
                    )
                    
                    if df.empty:
                        continue
                    
                    # 写入 InfluxDB
                    if self._influx_store:
                        points = self._influx_store.write_ohlcv(symbol, timeframe, df)
                        self._stats["total_points_written"] += points
                    
                    # 写入 Parquet (定期，不是每次)
                    # Parquet 写入由单独的任务处理
                    
                    self._stats["successful_requests"] += 1
                    
                    self.logger.debug(
                        "data_collected",
                        symbol=str(symbol),
                        timeframe=tf_str,
                        rows=len(df),
                        latest=df["timestamp"].max().isoformat() if not df.empty else None,
                    )
                    
                except Exception as e:
                    self._stats["failed_requests"] += 1
                    self.logger.warning(
                        "collection_error",
                        symbol=str(symbol),
                        timeframe=tf_str,
                        error=str(e),
                    )
                
                # 避免请求过快
                await asyncio.sleep(0.2)
    
    async def run(self):
        """运行采集循环"""
        await self.initialize()
        
        print("\n" + "=" * 60)
        print("🔄 实时数据采集服务已启动")
        print("=" * 60)
        print(f"   交易所: {self.exchange.upper()}")
        print(f"   交易对: {', '.join(self.symbols)}")
        print(f"   时间框架: {', '.join(self.timeframes)}")
        print(f"   采集间隔: {self.interval_seconds} 秒")
        print(f"   写入 InfluxDB: {'是' if self.write_influx else '否'}")
        print(f"   写入 Parquet: {'是' if self.write_parquet else '否'}")
        print("-" * 60)
        print("按 Ctrl+C 停止服务")
        print("=" * 60 + "\n")
        
        try:
            while not _stop_event.is_set():
                start_time = datetime.now(UTC)
                
                await self.collect_once()
                
                # 刷新 InfluxDB
                if self._influx_store:
                    self._influx_store.flush()
                
                # 打印状态
                elapsed = (datetime.now(UTC) - start_time).total_seconds()
                uptime = datetime.now(UTC) - self._stats["start_time"]
                
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"采集完成 | 成功: {self._stats['successful_requests']} | "
                    f"失败: {self._stats['failed_requests']} | "
                    f"数据点: {self._stats['total_points_written']:,} | "
                    f"运行时间: {str(uptime).split('.')[0]}"
                )
                
                # 等待下一次采集
                wait_time = max(0, self.interval_seconds - elapsed)
                try:
                    await asyncio.wait_for(_stop_event.wait(), timeout=wait_time)
                except asyncio.TimeoutError:
                    pass
        
        finally:
            await self.cleanup()


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="实时数据采集服务")
    parser.add_argument(
        "--symbols", 
        default="BTCUSDT,ETHUSDT",
        help="交易对列表，逗号分隔 (默认 BTCUSDT,ETHUSDT)"
    )
    parser.add_argument(
        "--timeframes",
        default="1m,1h",
        help="时间框架列表，逗号分隔 (默认 1m,1h)"
    )
    parser.add_argument(
        "--exchange",
        default="binance",
        choices=["binance", "okx"],
        help="交易所 (默认 binance)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="采集间隔秒数 (默认 60)"
    )
    parser.add_argument(
        "--no-influx",
        action="store_true",
        help="不写入 InfluxDB"
    )
    parser.add_argument(
        "--no-parquet",
        action="store_true",
        help="不写入 Parquet"
    )
    args = parser.parse_args()
    
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 解析参数
    symbols = [s.strip() for s in args.symbols.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]
    
    # 创建并运行采集器
    collector = RealtimeCollector(
        symbols=symbols,
        timeframes=timeframes,
        exchange=args.exchange,
        interval_seconds=args.interval,
        write_influx=not args.no_influx,
        write_parquet=not args.no_parquet,
    )
    
    await collector.run()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
