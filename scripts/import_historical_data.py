#!/usr/bin/env python3
"""
📥 历史数据导入脚本

从 Binance 下载历史 K 线数据并写入 InfluxDB

功能:
1. 从 data.binance.vision 下载历史数据
2. 保存到 Parquet 存储
3. 写入 InfluxDB (供 Grafana 可视化)

使用方式:
    # 在 Docker 中运行
    docker-compose exec collector python scripts/import_historical_data.py
    
    # 指定参数
    docker-compose exec collector python scripts/import_historical_data.py \
        --symbol BTCUSDT --timeframe 1h --start 2024-01-01 --end 2025-12-31
    
    # 导入多个交易对
    docker-compose exec collector python scripts/import_historical_data.py \
        --symbols BTCUSDT,ETHUSDT,BNBUSDT --timeframe 1m

数据源:
    https://data.binance.vision/
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


def print_banner():
    """打印横幅"""
    print("\n" + "=" * 70)
    print("📥 AlgorithmTrader - 历史数据导入")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据源: Binance (data.binance.vision)")
    print("-" * 70)


def print_step(step: int, total: int, title: str):
    """打印步骤"""
    print(f"\n{'='*70}")
    print(f"[{step}/{total}] {title}")
    print("-" * 70)


async def download_data(
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """从 Binance 下载数据"""
    from src.data.connectors.binance import BinanceConnector
    
    print(f"  📊 交易对: {symbol}")
    print(f"  ⏰ 时间框架: {timeframe}")
    print(f"  📅 开始: {start_date.strftime('%Y-%m-%d')}")
    print(f"  📅 结束: {end_date.strftime('%Y-%m-%d')}")
    
    connector = BinanceConnector()
    
    try:
        df = await connector.download_historical_klines(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            market_type="spot",
        )
        
        if df.empty:
            print(f"  ⚠️ 无法从 Binance Vision 下载，尝试 API...")
            # 尝试使用 API 获取
            df = await _fetch_via_api(connector, symbol, timeframe, start_date, end_date)
        
        return df
    finally:
        await connector.close()


async def _fetch_via_api(
    connector,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """通过 Binance API 获取数据"""
    from src.core.instruments import Exchange, Symbol
    from src.core.timeframes import Timeframe
    
    # 解析交易对
    if "/" in symbol:
        base, quote = symbol.split("/")
    else:
        # 假设是 BTCUSDT 格式
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            quote = "USDT"
        elif symbol.endswith("BUSD"):
            base = symbol[:-4]
            quote = "BUSD"
        else:
            base = symbol[:-3]
            quote = symbol[-3:]
    
    sym = Symbol(exchange=Exchange.BINANCE, base=base, quote=quote)
    tf = Timeframe(timeframe)
    
    all_data = []
    current_start = start_date
    batch_count = 0
    
    print(f"\n  ⏳ 从 API 采集数据...")
    
    while current_start < end_date:
        try:
            df = await connector.fetch_ohlcv(
                symbol=sym,
                timeframe=tf,
                since=current_start,
                limit=1000,
            )
            
            if df.empty:
                break
            
            all_data.append(df)
            batch_count += 1
            
            last_ts = df["timestamp"].max()
            progress = (last_ts.timestamp() - start_date.timestamp()) / \
                      (end_date.timestamp() - start_date.timestamp()) * 100
            progress = min(progress, 100)
            
            if batch_count % 10 == 0:
                bars = sum(len(d) for d in all_data)
                print(f"  📊 进度: {progress:5.1f}% | 已采集 {bars:6d} 条")
            
            # 移动到下一批
            current_start = last_ts.to_pydatetime() + timedelta(minutes=1)
            
            await asyncio.sleep(0.2)  # 避免限频
            
        except Exception as e:
            print(f"  ⚠️ API 错误: {e}")
            await asyncio.sleep(1)
            continue
    
    if all_data:
        result = pd.concat(all_data, ignore_index=True)
        result = result.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return result
    
    return pd.DataFrame()


def save_to_parquet(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> int:
    """保存到 Parquet"""
    from src.core.instruments import Exchange, Symbol
    from src.core.timeframes import Timeframe
    from src.data.storage.parquet_store import ParquetStore
    
    # 解析交易对
    if "/" in symbol:
        base, quote = symbol.split("/")
    else:
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            quote = "USDT"
        else:
            base = symbol[:-3]
            quote = symbol[-3:]
    
    sym = Symbol(exchange=Exchange.BINANCE, base=base, quote=quote)
    tf = Timeframe(timeframe)
    
    store = ParquetStore(base_path=PROJECT_ROOT / "data" / "parquet")
    rows = store.write(sym, tf, df)
    
    print(f"  ✅ 已保存到 Parquet: {rows} 行")
    print(f"     路径: {PROJECT_ROOT / 'data' / 'parquet' / 'binance' / f'{base}_{quote}'}")
    
    return rows


def write_to_influxdb(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> int:
    """写入 InfluxDB"""
    from src.core.instruments import Exchange, Symbol
    from src.core.timeframes import Timeframe
    from src.data.storage.influx_store import InfluxStore
    
    # 解析交易对
    if "/" in symbol:
        base, quote = symbol.split("/")
    else:
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            quote = "USDT"
        else:
            base = symbol[:-3]
            quote = symbol[-3:]
    
    sym = Symbol(exchange=Exchange.BINANCE, base=base, quote=quote)
    tf = Timeframe(timeframe)
    
    store = InfluxStore(async_write=False)  # 同步写入确保数据写入
    
    try:
        points = store.write_ohlcv(sym, tf, df)
        store.flush()  # 确保刷新
        print(f"  ✅ 已写入 InfluxDB: {points} 个数据点")
        return points
    finally:
        store.close()


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="导入 Binance 历史数据")
    parser.add_argument("--symbol", default="BTCUSDT", help="交易对 (默认 BTCUSDT)")
    parser.add_argument("--symbols", help="多个交易对，逗号分隔 (如 BTCUSDT,ETHUSDT)")
    parser.add_argument("--timeframe", default="1h", help="时间框架 (默认 1h)")
    parser.add_argument("--start", default="2024-01-01", help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--skip-parquet", action="store_true", help="跳过 Parquet 保存")
    parser.add_argument("--skip-influx", action="store_true", help="跳过 InfluxDB 写入")
    args = parser.parse_args()
    
    print_banner()
    
    # 解析交易对
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        symbols = [args.symbol]
    
    timeframe = args.timeframe
    start_date = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
    end_date = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=UTC)
    
    # 如果结束日期在未来，调整为当前时间
    now = datetime.now(UTC)
    if end_date > now:
        end_date = now - timedelta(hours=1)  # 留一小时缓冲
        print(f"  ⚠️ 结束日期调整为: {end_date.strftime('%Y-%m-%d %H:%M')}")
    
    total_symbols = len(symbols)
    total_rows = 0
    total_influx_points = 0
    
    for i, symbol in enumerate(symbols, 1):
        print_step(i, total_symbols, f"处理 {symbol}")
        
        # 下载数据
        print("\n  📥 下载数据...")
        df = await download_data(symbol, timeframe, start_date, end_date)
        
        if df.empty:
            print(f"  ❌ 未获取到 {symbol} 的数据")
            continue
        
        print(f"\n  ✅ 下载完成: {len(df)} 条数据")
        print(f"     时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
        
        # 保存到 Parquet
        if not args.skip_parquet:
            print("\n  💾 保存到 Parquet...")
            try:
                save_to_parquet(df, symbol, timeframe)
            except Exception as e:
                print(f"  ⚠️ Parquet 保存失败: {e}")
        
        # 写入 InfluxDB
        if not args.skip_influx:
            print("\n  📊 写入 InfluxDB...")
            try:
                points = write_to_influxdb(df, symbol, timeframe)
                total_influx_points += points
            except Exception as e:
                print(f"  ⚠️ InfluxDB 写入失败: {e}")
        
        total_rows += len(df)
    
    # 完成
    print("\n" + "=" * 70)
    print("✅ 数据导入完成！")
    print("=" * 70)
    print(f"\n📊 统计:")
    print(f"   处理交易对: {total_symbols} 个")
    print(f"   总数据量: {total_rows:,} 条")
    print(f"   InfluxDB 数据点: {total_influx_points:,}")
    print(f"\n🔍 查看数据:")
    print(f"   Grafana: http://localhost:3000 (admin/algorithmtrader123)")
    print(f"   InfluxDB: http://localhost:8086 (admin/algorithmtrader123)")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
