#!/usr/bin/env python
"""测试 InfluxDB Store - 存储和查询实时数据"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta

# 添加项目根目录到 Python 路径
sys.path.insert(0, "/app")

import pandas as pd

from src.core.instruments import Symbol, Exchange
from src.core.timeframes import Timeframe
from src.data.connectors.okx import OKXConnector
from src.data.storage.influx_store import InfluxStore


async def main():
    print("=" * 60)
    print("测试 InfluxDB Store - 存储和查询实时数据")
    print("=" * 60)
    
    # 创建 Symbol
    symbol = Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT")
    timeframe = Timeframe.M15
    
    # 1. 检查 InfluxDB 连接
    print("\n1. 检查 InfluxDB 连接...")
    
    # 使用 Docker 网络内部地址和初始 token
    store = InfluxStore(
        url="http://influxdb:8086",
        token="algorithmtrader-dev-token",  # docker-compose 中设置的 token
        org="algorithmtrader",
        bucket="trading",
        async_write=False,  # 同步写入便于测试
    )
    
    if store.health_check():
        print("   InfluxDB 连接正常!")
    else:
        print("   InfluxDB 连接失败!")
        return
    
    # 2. 从 OKX 拉取数据
    print(f"\n2. 从 OKX 拉取 {symbol} {timeframe.value} K 线...")
    
    async with OKXConnector() as connector:
        df = await connector.fetch_ohlcv(symbol, timeframe, limit=20)
    
    print(f"   获取到 {len(df)} 根 K 线")
    
    # 3. 写入 InfluxDB
    print("\n3. 写入 InfluxDB...")
    
    points = store.write_ohlcv(symbol, timeframe, df)
    store.flush()  # 确保数据写入
    print(f"   写入 {points} 个数据点")
    
    # 4. 写入单根 K 线
    print("\n4. 写入单根 K 线...")
    
    store.write_bar(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=datetime.now(timezone.utc),
        open_=89000.0,
        high=89500.0,
        low=88500.0,
        close=89200.0,
        volume=100.0,
    )
    store.flush()
    print("   单根 K 线写入成功")
    
    # 5. 写入风控指标
    print("\n5. 写入风控指标...")
    
    store.write_risk_metric(
        metric_name="drawdown",
        value=-0.05,
        strategy="test_strategy",
    )
    store.write_risk_metric(
        metric_name="leverage",
        value=2.5,
    )
    store.flush()
    print("   风控指标写入成功")
    
    # 6. 写入交易信号
    print("\n6. 写入交易信号...")
    
    store.write_trade_signal(
        symbol=symbol,
        signal_type="buy",
        price=89000.0,
        quantity=0.1,
        strategy="test_strategy",
        reason="突破信号",
    )
    store.flush()
    print("   交易信号写入成功")
    
    # 7. 查询数据
    print("\n7. 查询最近 1 小时的 OHLCV 数据...")
    
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    result_df = store.query_ohlcv(symbol, timeframe, start)
    print(f"   查询到 {len(result_df)} 行数据")
    if not result_df.empty:
        print(result_df.head())
    
    # 8. 查询最新 K 线
    print("\n8. 查询最新 K 线...")
    
    latest = store.query_latest_bar(symbol, timeframe)
    if latest:
        print(f"   时间: {latest['timestamp']}")
        print(f"   收盘价: {latest['close']}")
    else:
        print("   没有数据")
    
    # 关闭连接
    store.close()
    
    print("\n" + "=" * 60)
    print("InfluxDB Store 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
