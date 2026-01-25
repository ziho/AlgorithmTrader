#!/usr/bin/env python
"""测试 Data Collector - 采集并存储数据"""

import asyncio
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, "/app")

from datetime import datetime, timezone, timedelta

from src.core.instruments import Symbol, Exchange
from src.core.timeframes import Timeframe
from services.collector.main import DataCollector


async def main():
    print("=" * 60)
    print("测试 Data Collector - 采集并存储数据")
    print("=" * 60)
    
    # 1. 创建 Collector
    print("\n1. 创建 Data Collector...")
    
    symbols = [
        Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT"),
    ]
    timeframes = [Timeframe.M15]
    
    collector = DataCollector(
        symbols=symbols,
        timeframes=timeframes,
        influx_url="http://influxdb:8086",
        influx_token="algorithmtrader-dev-token",
    )
    
    print(f"   交易对: {[str(s) for s in symbols]}")
    print(f"   时间框架: {[tf.value for tf in timeframes]}")
    
    # 2. 采集最新数据
    print("\n2. 采集最新 K 线数据...")
    
    for symbol in symbols:
        for timeframe in timeframes:
            rows = await collector.collect_bars(symbol, timeframe, limit=10)
            print(f"   {symbol} {timeframe.value}: 写入 {rows} 行")
    
    # 3. 采集所有配置
    print("\n3. 批量采集所有配置...")
    
    results = await collector.collect_all()
    for key, rows in results.items():
        print(f"   {key}: {rows} 行")
    
    # 4. 回填历史数据（最近 2 小时）
    print("\n4. 回填历史数据 (最近 2 小时)...")
    
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    
    for symbol in symbols:
        for timeframe in timeframes:
            rows = await collector.backfill(symbol, timeframe, start)
            print(f"   {symbol} {timeframe.value}: 回填 {rows} 行")
    
    # 5. 检测数据缺口
    print("\n5. 检测数据缺口...")
    
    for symbol in symbols:
        for timeframe in timeframes:
            filled = await collector.detect_and_fill_gaps(symbol, timeframe)
            if filled > 0:
                print(f"   {symbol} {timeframe.value}: 补全 {filled} 行缺口")
            else:
                print(f"   {symbol} {timeframe.value}: 无缺口")
    
    # 6. 关闭资源
    await collector.close()
    
    print("\n" + "=" * 60)
    print("Data Collector 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
