#!/usr/bin/env python3
"""
📊 数据查询工具

查询已下载的历史数据，支持导出和统计

使用方式:
    # 查看可用数据
    python -m scripts.data_query --list
    
    # 查询特定交易对
    python -m scripts.data_query --symbol BTCUSDT --from 2024-01-01 --to 2024-12-31
    
    # 导出为 CSV
    python -m scripts.data_query --symbol BTCUSDT --tf 1h --from 2024-01-01 --export btc_1h.csv
    
    # 检测缺口
    python -m scripts.data_query --symbol BTCUSDT --gaps
    
    # 聚合到更高周期
    python -m scripts.data_query --symbol BTCUSDT --tf 1m --aggregate 1h
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_banner():
    """打印横幅"""
    print("\n" + "=" * 70)
    print("📊 AlgorithmTrader - 数据查询工具")
    print("=" * 70)


def format_size(bytes_size: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="数据查询工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用数据",
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
        help="交易对 (如 BTCUSDT)",
    )
    parser.add_argument(
        "--tf",
        type=str,
        default="1m",
        help="时间框架 (默认: 1m)",
    )
    parser.add_argument(
        "--from",
        dest="start_date",
        type=str,
        help="开始日期 (如 2024-01-01)",
    )
    parser.add_argument(
        "--to",
        dest="end_date",
        type=str,
        help="结束日期 (如 2024-12-31)",
    )
    parser.add_argument(
        "--gaps",
        action="store_true",
        help="检测数据缺口",
    )
    parser.add_argument(
        "--aggregate",
        type=str,
        help="聚合到更高周期 (如 --tf 1m --aggregate 1h)",
    )
    parser.add_argument(
        "--export",
        type=str,
        help="导出为 CSV 文件",
    )
    parser.add_argument(
        "--head",
        type=int,
        default=10,
        help="显示前 N 行 (默认: 10)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        help="显示后 N 行",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="数据目录 (默认: data)",
    )
    
    args = parser.parse_args()
    
    print_banner()
    
    from src.data.fetcher.manager import DataManager
    
    manager = DataManager(data_dir=args.data_dir)
    
    # 列出可用数据
    if args.list:
        print("\n📁 可用数据:")
        print("-" * 70)
        
        data_list = manager.list_available_data(exchange=args.exchange)
        
        if not data_list:
            print("  (无数据)")
            return
        
        print(f"{'交易所':<10} {'交易对':<12} {'周期':<6} {'开始':<12} {'结束':<12}")
        print("-" * 70)
        
        for item in data_list:
            range_str = ""
            if item["range"]:
                start, end = item["range"]
                range_str = f"{start.strftime('%Y-%m-%d'):<12} {end.strftime('%Y-%m-%d'):<12}"
            else:
                range_str = "N/A"
            
            print(f"{item['exchange']:<10} {item['symbol']:<12} {item['timeframe']:<6} {range_str}")
        
        print("-" * 70)
        print(f"共 {len(data_list)} 个数据集")
        return
    
    # 需要指定 symbol
    if not args.symbol:
        print("❌ 请指定 --symbol 或使用 --list 查看可用数据")
        return
    
    symbol = args.symbol.upper()
    
    # 检测缺口
    if args.gaps:
        print(f"\n🔍 检测 {symbol}/{args.tf} 缺口...")
        
        start = None
        end = None
        if args.start_date:
            start = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.end_date:
            end = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=UTC)
        
        gaps = manager.detect_gaps(args.exchange, symbol, args.tf, start, end)
        
        if not gaps:
            print("  ✅ 无缺口")
        else:
            print(f"\n  发现 {len(gaps)} 个缺口:")
            for i, (gap_start, gap_end) in enumerate(gaps, 1):
                duration = gap_end - gap_start
                print(f"  {i}. {gap_start.strftime('%Y-%m-%d %H:%M')} ~ "
                      f"{gap_end.strftime('%Y-%m-%d %H:%M')} ({duration})")
        return
    
    # 查询数据
    print(f"\n📊 查询 {args.exchange.upper()}/{symbol}/{args.tf}")
    
    # 获取数据范围
    data_range = manager.get_data_range(args.exchange, symbol, args.tf)
    
    if not data_range:
        print("  ❌ 无数据")
        return
    
    earliest, latest = data_range
    print(f"  数据范围: {earliest.strftime('%Y-%m-%d %H:%M')} ~ {latest.strftime('%Y-%m-%d %H:%M')}")
    
    # 确定查询范围
    if args.start_date:
        start = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    else:
        start = earliest
    
    if args.end_date:
        end = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=UTC)
    else:
        end = latest
    
    print(f"  查询范围: {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}")
    
    # 读取数据
    df = manager.get_history(args.exchange, symbol, start, end, args.tf)
    
    if df.empty:
        print("  ❌ 查询范围无数据")
        return
    
    print(f"  数据行数: {len(df):,}")
    
    # 聚合
    if args.aggregate:
        print(f"\n📈 聚合 {args.tf} -> {args.aggregate}...")
        df = manager.aggregate_to_higher_tf(df, args.tf, args.aggregate)
        print(f"  聚合后行数: {len(df):,}")
    
    # 导出
    if args.export:
        export_path = Path(args.export)
        df.to_csv(export_path, index=False)
        size = export_path.stat().st_size
        print(f"\n💾 已导出到: {export_path} ({format_size(size)})")
    
    # 显示数据
    print("\n" + "-" * 70)
    
    if args.tail:
        print(f"最后 {args.tail} 行:")
        print(df.tail(args.tail).to_string())
    else:
        print(f"前 {args.head} 行:")
        print(df.head(args.head).to_string())
    
    print("-" * 70)
    
    # 统计
    print("\n📊 统计:")
    print(f"  开盘价范围: {df['open'].min():.2f} ~ {df['open'].max():.2f}")
    print(f"  最高价最大: {df['high'].max():.2f}")
    print(f"  最低价最小: {df['low'].min():.2f}")
    print(f"  收盘价范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")
    print(f"  总成交量: {df['volume'].sum():,.2f}")


if __name__ == "__main__":
    main()
