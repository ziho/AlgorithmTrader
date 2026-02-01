#!/usr/bin/env python3
"""
📥 历史数据批量下载脚本

从 Binance Public Data (data.binance.vision) 下载历史 K 线数据

特点:
- 支持断点续传
- 可选校验和验证
- 自动保存到 Parquet

使用方式:
    # 下载 BTC 1分钟数据 (2017-2026)
    python -m scripts.fetch_history --symbol BTCUSDT --from 2017-01-01 --to 2026-02-01 --tf 1m
    
    # 下载多个交易对
    python -m scripts.fetch_history --symbols BTCUSDT,ETHUSDT,BNBUSDT --tf 1m
    
    # 指定输出目录
    python -m scripts.fetch_history --symbol BTCUSDT --tf 1h --dest data/raw
    
    # 强制重新下载（忽略断点）
    python -m scripts.fetch_history --symbol BTCUSDT --tf 1m --force
    
    # Docker 中运行
    docker-compose exec collector python -m scripts.fetch_history --symbol BTCUSDT --tf 1m

数据源:
    https://data.binance.vision/
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_banner():
    """打印横幅"""
    print("\n" + "=" * 70)
    print("📥 AlgorithmTrader - 历史数据批量下载器")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据源: Binance Public Data (data.binance.vision)")
    print("-" * 70)


def print_progress(completed: int, total: int, symbol: str):
    """打印进度"""
    pct = completed / total * 100 if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * completed / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {pct:5.1f}% ({completed}/{total}) - {symbol}", end="", flush=True)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="从 Binance 下载历史 K 线数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 下载 BTC 1分钟数据
  python -m scripts.fetch_history --symbol BTCUSDT --from 2020-01-01 --to 2024-12-31 --tf 1m
  
  # 下载多个交易对的小时数据
  python -m scripts.fetch_history --symbols BTCUSDT,ETHUSDT --tf 1h
  
  # 下载默认的 6 个主流币种
  python -m scripts.fetch_history --tf 1m --from 2020-01-01
        """,
    )
    
    parser.add_argument(
        "--exchange",
        type=str,
        default="binance",
        help="交易所 (默认: binance)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        help="单个交易对 (如 BTCUSDT)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        help="多个交易对，逗号分隔 (如 BTCUSDT,ETHUSDT,BNBUSDT)",
    )
    parser.add_argument(
        "--from",
        dest="start_date",
        type=str,
        default="2020-01-01",
        help="开始日期 (默认: 2020-01-01)",
    )
    parser.add_argument(
        "--to",
        dest="end_date",
        type=str,
        default=datetime.now(UTC).strftime("%Y-%m-%d"),
        help="结束日期 (默认: 今天)",
    )
    parser.add_argument(
        "--tf",
        type=str,
        default="1m",
        help="时间框架 (1m, 5m, 15m, 1h, 4h, 1d 等，默认: 1m)",
    )
    parser.add_argument(
        "--dest",
        type=str,
        default="data",
        help="数据目录 (默认: data)",
    )
    parser.add_argument(
        "--market",
        type=str,
        choices=["spot", "um", "cm"],
        default="spot",
        help="市场类型: spot=现货, um=U本位合约, cm=币本位合约 (默认: spot)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载，忽略断点",
    )
    parser.add_argument(
        "--no-checksum",
        action="store_true",
        help="跳过校验和验证",
    )
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="保存原始 ZIP 文件",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="请求间隔秒数 (默认: 0.2)",
    )
    
    args = parser.parse_args()
    
    print_banner()
    
    # 确定交易对列表
    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        # 默认 6 个主流币种
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    
    # 解析日期
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=UTC)
    
    print(f"📊 交易对: {', '.join(symbols)}")
    print(f"⏰ 时间框架: {args.tf}")
    print(f"📅 时间范围: {args.start_date} ~ {args.end_date}")
    print(f"📁 输出目录: {args.dest}")
    print(f"🔧 市场类型: {args.market}")
    print(f"🔄 断点续传: {'否 (强制重下)' if args.force else '是'}")
    print(f"✓ 校验和: {'否' if args.no_checksum else '是'}")
    print("-" * 70)
    
    # 导入模块
    from src.data.fetcher.history import HistoryFetcher
    
    # 创建下载器
    fetcher = HistoryFetcher(
        data_dir=args.dest,
        exchange=args.exchange,
        market_type=args.market,
        request_delay=args.delay,
        verify_checksum=not args.no_checksum,
        save_raw=args.save_raw,
    )
    
    # 如果强制重下，清除断点
    if args.force:
        for symbol in symbols:
            deleted = fetcher.checkpoint.reset(
                exchange=args.exchange,
                symbol=symbol,
                timeframe=args.tf,
            )
            if deleted:
                print(f"🗑️ 已清除 {symbol} 的 {deleted} 条断点记录")
    
    total_stats = {
        "symbols": len(symbols),
        "completed_months": 0,
        "skipped_months": 0,
        "failed_months": 0,
        "total_rows": 0,
        "start_time": datetime.now(UTC),
    }
    
    try:
        async with fetcher:
            for i, symbol in enumerate(symbols, 1):
                print(f"\n[{i}/{len(symbols)}] 📥 下载 {symbol}")
                print("-" * 50)
                
                stats = await fetcher.download_and_save(
                    symbol=symbol,
                    timeframe=args.tf,
                    start_date=start_date,
                    end_date=end_date,
                    skip_existing=not args.force,
                )
                
                total_stats["completed_months"] += stats.completed_months
                total_stats["skipped_months"] += stats.skipped_months
                total_stats["failed_months"] += stats.failed_months
                total_stats["total_rows"] += stats.total_rows
                
                print(f"\n  ✅ 完成: {stats.completed_months} 月")
                print(f"  ⏭️ 跳过: {stats.skipped_months} 月")
                print(f"  ❌ 失败: {stats.failed_months} 月")
                print(f"  📊 行数: {stats.total_rows:,}")
                
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断，进度已保存（可断点续传）")
    
    # 总结
    elapsed = datetime.now(UTC) - total_stats["start_time"]
    
    print("\n" + "=" * 70)
    print("📊 下载总结")
    print("=" * 70)
    print(f"  交易对数: {total_stats['symbols']}")
    print(f"  完成月数: {total_stats['completed_months']}")
    print(f"  跳过月数: {total_stats['skipped_months']}")
    print(f"  失败月数: {total_stats['failed_months']}")
    print(f"  总行数:   {total_stats['total_rows']:,}")
    print(f"  耗时:     {elapsed}")
    print("=" * 70)
    
    # 数据路径提示
    print(f"\n📁 数据已保存到: {args.dest}/parquet/binance/")
    print("\n示例读取代码:")
    print("  from src.data.fetcher import get_history")
    print(f'  df = get_history("binance", "{symbols[0]}", "{args.start_date}", "{args.end_date}", tf="{args.tf}")')
    print("  print(df.head())")


if __name__ == "__main__":
    asyncio.run(main())
