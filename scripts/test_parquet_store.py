#!/usr/bin/env python
"""测试 Parquet Store - 存储和读取 OHLCV 数据"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta

# 添加项目根目录到 Python 路径
sys.path.insert(0, "/app")

import pandas as pd

from src.core.instruments import Symbol, Exchange
from src.core.timeframes import Timeframe
from src.data.connectors.okx import OKXConnector
from src.data.storage.parquet_store import ParquetStore


async def main():
    print("=" * 60)
    print("测试 Parquet Store - 存储和读取 OHLCV 数据")
    print("=" * 60)
    
    # 创建 Symbol
    symbol = Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT")
    timeframe = Timeframe.M15
    
    # 1. 从 OKX 拉取数据
    print(f"\n1. 从 OKX 拉取 {symbol} {timeframe.value} K 线...")
    
    async with OKXConnector() as connector:
        df = await connector.fetch_ohlcv(symbol, timeframe, limit=100)
    
    print(f"   获取到 {len(df)} 根 K 线")
    print(f"   时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    
    # 2. 写入 Parquet
    print("\n2. 写入 Parquet Store...")
    
    with ParquetStore() as store:
        rows_written = store.write(symbol, timeframe, df)
        print(f"   写入 {rows_written} 行数据")
        
        # 3. 读取数据
        print("\n3. 读取全部数据...")
        read_df = store.read(symbol, timeframe)
        print(f"   读取到 {len(read_df)} 行")
        print(read_df.head())
        
        # 4. 按时间范围读取
        print("\n4. 按时间范围读取 (最近 1 小时)...")
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=1)
        filtered_df = store.read(symbol, timeframe, start=start_time, end=end_time)
        print(f"   读取到 {len(filtered_df)} 行")
        
        # 5. 使用 Polars 读取
        print("\n5. 使用 Polars 读取...")
        pl_df = store.read_polars(symbol, timeframe)
        print(f"   Polars DataFrame: {pl_df.shape}")
        print(pl_df.head())
        
        # 6. 获取数据范围
        print("\n6. 获取数据时间范围...")
        data_range = store.get_data_range(symbol, timeframe)
        if data_range:
            print(f"   最早: {data_range[0]}")
            print(f"   最晚: {data_range[1]}")
        
        # 7. 检测数据缺口
        print("\n7. 检测数据缺口...")
        gaps = store.detect_gaps(symbol, timeframe)
        if gaps:
            print(f"   发现 {len(gaps)} 个缺口:")
            for gap in gaps[:5]:  # 最多显示 5 个
                print(f"     {gap[0]} ~ {gap[1]}")
        else:
            print("   没有发现缺口")
        
        # 8. 列出存储的交易对
        print("\n8. 列出存储的交易对...")
        symbols = store.list_symbols()
        for s in symbols:
            print(f"   - {s}")
    
    print("\n" + "=" * 60)
    print("Parquet Store 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
