#!/usr/bin/env python3
"""
测试 OKX 数据连接器

拉取公开 K 线数据，不需要 API key
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.connectors.okx import OKXConnector


async def test_fetch_ohlcv():
    """测试拉取 K 线数据"""
    print("=" * 50)
    print("测试 OKX 数据连接器 - 拉取 K 线数据")
    print("=" * 50)

    async with OKXConnector() as connector:
        # 拉取 BTC/USDT 15分钟 K 线
        print("\n拉取 BTC/USDT 15m K 线 (最近 10 根)...")
        df = await connector.fetch_ohlcv(
            symbol="BTC/USDT",
            timeframe="15m",
            limit=10,
        )

        print(f"\n获取到 {len(df)} 根 K 线:")
        print(df.to_string())

        # 拉取 ETH/USDT 1小时 K 线
        print("\n\n拉取 ETH/USDT 1h K 线 (最近 5 根)...")
        df_eth = await connector.fetch_ohlcv(
            symbol="ETH/USDT",
            timeframe="1h",
            limit=5,
        )

        print(f"\n获取到 {len(df_eth)} 根 K 线:")
        print(df_eth.to_string())

        # 拉取最新行情
        print("\n\n拉取 BTC/USDT 最新行情...")
        ticker = await connector.fetch_ticker("BTC/USDT")
        print(f"最新价格: {ticker['last']}")
        print(f"24h 最高: {ticker['high']}")
        print(f"24h 最低: {ticker['low']}")
        print(f"24h 成交量: {ticker['baseVolume']}")

    print("\n" + "=" * 50)
    print("测试完成!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_fetch_ohlcv())
