#!/usr/bin/env python3
"""
🔄 实时数据追赶与同步服务

持续同步最新的 K 线数据，支持断点追赶和 WebSocket 实时更新

特点:
- 启动时自动检测并补齐缺口
- WebSocket 实时接收新 bar
- 定期与 REST API 对比纠偏
- 支持多交易对并发

使用方式:
    # 启动实时同步 (默认 6 个主流币种)
    python -m scripts.realtime_sync
    
    # 指定交易对
    python -m scripts.realtime_sync --symbols BTCUSDT,ETHUSDT --timeframes 1m,1h
    
    # Docker 中运行
    docker-compose exec collector python -m scripts.realtime_sync
    
    # 后台运行
    nohup python -m scripts.realtime_sync > logs/realtime_sync.log 2>&1 &

信号处理:
    - SIGINT (Ctrl+C): 优雅关闭
    - SIGTERM: 优雅关闭
"""

import argparse
import asyncio
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# 全局停止事件
_stop_event = asyncio.Event()


def signal_handler(signum, frame):
    """信号处理"""
    print("\n⚠️ 收到停止信号，正在优雅关闭...")
    _stop_event.set()


def print_banner():
    """打印横幅"""
    print("\n" + "=" * 70)
    print("🔄 AlgorithmTrader - 实时数据同步服务")
    print("=" * 70)
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 70)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="实时数据追赶与同步服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--exchange",
        type=str,
        default="binance",
        help="交易所 (默认: binance)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT",
        help="交易对列表，逗号分隔 (默认: 6 个主流币种)",
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        default="1m",
        help="时间框架列表，逗号分隔 (默认: 1m)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="数据目录 (默认: data)",
    )
    parser.add_argument(
        "--gap-check-interval",
        type=int,
        default=300,
        help="缺口检查间隔秒数 (默认: 300)",
    )
    parser.add_argument(
        "--no-websocket",
        action="store_true",
        help="禁用 WebSocket，仅使用 REST 轮询",
    )
    
    args = parser.parse_args()
    
    print_banner()
    
    # 解析参数
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    timeframes = [tf.strip() for tf in args.timeframes.split(",")]
    
    print(f"📊 交易对: {', '.join(symbols)}")
    print(f"⏰ 时间框架: {', '.join(timeframes)}")
    print(f"🔌 交易所: {args.exchange}")
    print(f"📁 数据目录: {args.data_dir}")
    print(f"🔄 缺口检查间隔: {args.gap_check_interval}s")
    print(f"📡 WebSocket: {'禁用' if args.no_websocket else '启用'}")
    print("-" * 70)
    
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 导入模块
    from src.data.fetcher.realtime import RealtimeSyncer
    
    def on_bar(symbol: str, timeframe: str, df):
        """新 bar 回调"""
        row = df.iloc[0]
        print(f"  📊 {symbol}/{timeframe}: {row['timestamp']} | "
              f"O:{row['open']:.2f} H:{row['high']:.2f} L:{row['low']:.2f} "
              f"C:{row['close']:.2f} V:{row['volume']:.2f}")
    
    # 创建同步器
    syncer = RealtimeSyncer(
        symbols=symbols,
        timeframes=timeframes,
        exchange=args.exchange,
        data_dir=args.data_dir,
        gap_check_interval=args.gap_check_interval,
        on_bar_callback=on_bar if not args.no_websocket else None,
    )
    
    try:
        print("\n🚀 正在启动...")
        
        # 初始同步
        print("\n📥 初始同步中...")
        
        for symbol in symbols:
            for tf in timeframes:
                rows = await syncer.sync_to_latest(symbol, tf)
                if rows > 0:
                    print(f"  ✅ {symbol}/{tf}: 同步 {rows} 条")
                
                gaps_filled = await syncer.check_and_fill_gaps(symbol, tf)
                if gaps_filled > 0:
                    print(f"  🔧 {symbol}/{tf}: 补齐缺口 {gaps_filled} 条")
        
        if args.no_websocket:
            # REST 轮询模式
            print("\n🔄 REST 轮询模式运行中... (Ctrl+C 退出)")
            
            while not _stop_event.is_set():
                for symbol in symbols:
                    for tf in timeframes:
                        try:
                            rows = await syncer.sync_to_latest(symbol, tf)
                            if rows > 0:
                                print(f"  📊 {symbol}/{tf}: +{rows} 条")
                        except Exception as e:
                            print(f"  ⚠️ {symbol}/{tf}: {e}")
                
                # 等待下一轮或停止信号
                try:
                    await asyncio.wait_for(
                        _stop_event.wait(),
                        timeout=60.0
                    )
                    break
                except asyncio.TimeoutError:
                    pass
        else:
            # WebSocket 模式
            print("\n📡 WebSocket 模式运行中... (Ctrl+C 退出)")
            print("  接收到的新 bar 将显示在下方:")
            print("-" * 70)
            
            await syncer.start()
            
            # 等待停止信号
            await _stop_event.wait()
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        raise
    finally:
        print("\n正在关闭...")
        await syncer.close()
        
        # 打印统计
        stats = syncer.get_stats()
        if stats:
            print("\n📊 统计信息:")
            for key, s in stats.items():
                print(f"  {key}:")
                print(f"    缺口发现: {s.gaps_found}")
                print(f"    缺口修复: {s.gaps_filled}")
                print(f"    写入 bars: {s.bars_written}")
                if s.last_sync:
                    print(f"    最后同步: {s.last_sync.strftime('%Y-%m-%d %H:%M:%S')}")
        
        print("\n✅ 已安全关闭")


if __name__ == "__main__":
    asyncio.run(main())
