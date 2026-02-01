#!/usr/bin/env python3
"""
数据采集演示脚本

功能:
- 采集 BTC/USDT 和 ETH/USDT 的 15m K线
- 采集最近 7 天历史数据
- 同时存储到 Parquet 和 InfluxDB
- 显示进度和结果

使用方式:
    python scripts/demo_collect.py
    python scripts/demo_collect.py --days 14
    python scripts/demo_collect.py --symbols BTC/USDT,ETH/USDT,SOL/USDT
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.data.connectors.okx import OKXConnector
from src.data.storage.influx_store import InfluxStore
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import get_logger

logger = get_logger(__name__)


async def collect_symbol_data(
    connector: OKXConnector,
    symbol: Symbol,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    parquet_store: ParquetStore,
    influx_store: InfluxStore | None,
) -> int:
    """
    采集单个交易对的历史数据

    Args:
        connector: OKX 连接器
        symbol: 交易对
        timeframe: 时间框架
        start: 开始时间
        end: 结束时间
        parquet_store: Parquet 存储
        influx_store: InfluxDB 存储（可选）

    Returns:
        采集的行数
    """
    total_rows = 0
    current_start = start
    batch_size = 100

    print(f"  采集 {symbol} {timeframe.value}...")

    while current_start < end:
        try:
            # 拉取数据
            df = await connector.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=current_start,
                limit=batch_size,
            )

            if df.empty:
                break

            # 写入 Parquet
            rows = parquet_store.write(symbol, timeframe, df)
            total_rows += rows

            # 写入 InfluxDB
            if influx_store is not None:
                try:
                    influx_store.write_ohlcv(symbol, timeframe, df)
                except Exception as e:
                    logger.warning(f"InfluxDB 写入失败: {e}")

            # 更新进度
            last_ts = df["timestamp"].max()
            progress = (last_ts.timestamp() - start.timestamp()) / (end.timestamp() - start.timestamp()) * 100
            print(f"    进度: {progress:.1f}% ({last_ts.strftime('%Y-%m-%d %H:%M')})")

            # 移动到下一批
            current_start = last_ts.to_pydatetime() + timedelta(minutes=1)

            # 避免限频
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"采集失败: {e}")
            break

    return total_rows


async def run_demo(
    symbols: list[str],
    days: int,
    influx_url: str | None,
    influx_token: str | None,
) -> None:
    """
    运行数据采集演示

    Args:
        symbols: 交易对列表
        days: 采集的历史天数
        influx_url: InfluxDB URL
        influx_token: InfluxDB Token
    """
    print("=" * 60)
    print("AlgorithmTrader 数据采集演示")
    print("=" * 60)

    # 解析交易对
    symbol_list: list[Symbol] = []
    for s in symbols:
        parts = s.split("/")
        if len(parts) == 2:
            symbol_list.append(Symbol(exchange=Exchange.OKX, base=parts[0], quote=parts[1]))
        else:
            print(f"警告: 无效的交易对格式 '{s}'，跳过")

    if not symbol_list:
        print("错误: 没有有效的交易对")
        return

    # 时间范围
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    print(f"\n配置:")
    print(f"  交易对: {', '.join(str(s) for s in symbol_list)}")
    print(f"  时间框架: 15m")
    print(f"  时间范围: {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} ({days} 天)")
    print()

    # 初始化存储
    parquet_store = ParquetStore()
    
    influx_store: InfluxStore | None = None
    if influx_url and influx_token:
        try:
            influx_store = InfluxStore(
                url=influx_url,
                token=influx_token,
            )
            print(f"  InfluxDB: {influx_url}")
        except Exception as e:
            print(f"  InfluxDB 连接失败: {e}")
            influx_store = None
    else:
        print("  InfluxDB: 未配置")

    print(f"  Parquet: {parquet_store.base_path}")
    print()

    # 采集数据
    results: dict[str, int] = {}
    timeframe = Timeframe.M15

    async with OKXConnector() as connector:
        for symbol in symbol_list:
            rows = await collect_symbol_data(
                connector=connector,
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                parquet_store=parquet_store,
                influx_store=influx_store,
            )
            results[str(symbol)] = rows

    # 输出结果
    print()
    print("=" * 60)
    print("采集结果:")
    print("-" * 60)

    total = 0
    for symbol, rows in results.items():
        print(f"  {symbol}: {rows:,} 行")
        total += rows

    print("-" * 60)
    print(f"  总计: {total:,} 行")
    print("=" * 60)

    # 验证数据
    print("\n验证已存储的数据:")
    for symbol in symbol_list:
        df = parquet_store.read(symbol, timeframe, start, end)
        print(f"  {symbol}: {len(df):,} 行 (Parquet)")
        if not df.empty:
            print(f"    时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")

    print("\n完成!")


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="AlgorithmTrader 数据采集演示",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT,ETH/USDT",
        help="交易对列表，逗号分隔 (默认: BTC/USDT,ETH/USDT)",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="采集的历史天数 (默认: 7)",
    )

    parser.add_argument(
        "--influx-url",
        type=str,
        default="http://localhost:8086",
        help="InfluxDB URL (默认: http://localhost:8086)",
    )

    parser.add_argument(
        "--influx-token",
        type=str,
        default="algorithmtrader-dev-token",
        help="InfluxDB Token",
    )

    parser.add_argument(
        "--no-influx",
        action="store_true",
        help="不写入 InfluxDB",
    )

    args = parser.parse_args()

    # 解析交易对
    symbols = [s.strip() for s in args.symbols.split(",")]

    # InfluxDB 配置
    influx_url = None if args.no_influx else args.influx_url
    influx_token = None if args.no_influx else args.influx_token

    # 运行
    asyncio.run(run_demo(
        symbols=symbols,
        days=args.days,
        influx_url=influx_url,
        influx_token=influx_token,
    ))


if __name__ == "__main__":
    main()
