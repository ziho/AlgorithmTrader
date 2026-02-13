#!/usr/bin/env python3
"""
A 股数据批量下载命令行工具

支持:
- daily: 全市场日线 OHLCV
- daily_basic: 每日指标（市值/换手率/PE/PB）
- adj_factor: 复权因子

用法:
    # 下载 daily_basic (增量，从上次断点续传)
    python scripts/backfill_a_share.py daily_basic

    # 下载 adj_factor
    python scripts/backfill_a_share.py adj_factor

    # 指定日期范围
    python scripts/backfill_a_share.py daily_basic --start 20210714 --end 20260212

    # 增量更新（自动检测上次下载到哪里）
    python scripts/backfill_a_share.py daily --incremental

    # 查看当前数据状态
    python scripts/backfill_a_share.py status
"""

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_latest_completed_date(data_dir: Path, timeframe: str) -> str | None:
    """从 checkpoint DB 查询某个 timeframe 最后完成的日期"""
    db_path = data_dir / "fetch_checkpoint.db"
    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT MAX(year * 10000 + month * 100 + day)
            FROM download_progress
            WHERE exchange = 'a_tushare'
              AND symbol = '__ALL__'
              AND timeframe = ?
              AND status = 'completed'
            """,
            (timeframe,),
        )
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
        return None
    finally:
        conn.close()


def get_status(data_dir: Path) -> dict:
    """获取所有数据类型的状态"""
    db_path = data_dir / "fetch_checkpoint.db"
    status = {}

    if not db_path.exists():
        return {"1d": None, "daily_basic": None, "adj_factor": None}

    conn = sqlite3.connect(db_path)
    try:
        for tf in ["1d", "daily_basic", "adj_factor"]:
            cur = conn.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed'),
                    COUNT(*) FILTER (WHERE status = 'failed'),
                    MIN(year * 10000 + month * 100 + day) FILTER (WHERE status = 'completed'),
                    MAX(year * 10000 + month * 100 + day) FILTER (WHERE status = 'completed')
                FROM download_progress
                WHERE exchange = 'a_tushare'
                  AND symbol = '__ALL__'
                  AND timeframe = ?
                """,
                (tf,),
            )
            row = cur.fetchone()
            status[tf] = {
                "completed_days": row[0] or 0,
                "failed_days": row[1] or 0,
                "first_date": str(row[2]) if row[2] else None,
                "last_date": str(row[3]) if row[3] else None,
            }
    finally:
        conn.close()

    return status


def print_status(data_dir: Path) -> None:
    """打印数据状态"""
    status = get_status(data_dir)
    today = datetime.now().strftime("%Y%m%d")

    print("=" * 60)
    print("A 股数据状态总览")
    print(f"今日: {today}")
    print("=" * 60)

    name_map = {
        "1d": "日线 OHLCV (daily)",
        "daily_basic": "每日指标 (daily_basic)",
        "adj_factor": "复权因子 (adj_factor)",
    }

    for tf, info in status.items():
        name = name_map.get(tf, tf)
        print(f"\n📊 {name}")

        if info["completed_days"] == 0:
            print("   ❌ 未下载任何数据")
            continue

        print(f"   ✅ 已完成: {info['completed_days']:,} 个交易日")
        if info["failed_days"] > 0:
            print(f"   ⚠️  失败: {info['failed_days']} 个交易日")
        print(f"   📅 范围: {info['first_date']} → {info['last_date']}")

        # 检查是否需要增量更新
        if info["last_date"] and info["last_date"] < today:
            print(f"   🔄 待更新: {info['last_date']} → {today}")
        elif info["last_date"] == today:
            print("   ✅ 已是最新")

    print("\n" + "=" * 60)


async def run_backfill(
    data_type: str,
    start_date: str,
    end_date: str,
    data_dir: Path,
) -> None:
    """执行下载"""
    from src.data.fetcher.tushare_history import TushareHistoryFetcher

    fetcher = TushareHistoryFetcher(data_dir=data_dir)

    # 进度回调
    last_pct = [-1.0]

    def on_progress(stats):
        pct = stats.progress
        # 每 1% 打印一次
        if int(pct) > int(last_pct[0]):
            last_pct[0] = pct
            eta_str = ""
            if stats.eta_seconds is not None:
                mins = stats.eta_seconds / 60
                if mins > 60:
                    eta_str = f" ETA {mins / 60:.1f}h"
                else:
                    eta_str = f" ETA {mins:.0f}min"

            done = stats.completed_days + stats.skipped_days
            print(
                f"\r  [{pct:5.1f}%] {done}/{stats.total_days} "
                f"rows={stats.total_rows:,} "
                f"fail={stats.failed_days}"
                f"{eta_str}",
                end="",
                flush=True,
            )

    fetcher.set_progress_callback(on_progress)

    print(f"开始下载 {data_type}: {start_date} → {end_date}")
    print(f"数据目录: {data_dir}")
    print("-" * 50)

    try:
        if data_type == "daily":
            stats = await fetcher.backfill_daily(
                start_date=start_date, end_date=end_date
            )
        elif data_type == "daily_basic":
            stats = await fetcher.backfill_daily_basic(
                start_date=start_date, end_date=end_date
            )
        elif data_type == "adj_factor":
            stats = await fetcher.backfill_adj_factor(
                start_date=start_date, end_date=end_date
            )
        else:
            print(f"❌ 未知数据类型: {data_type}")
            return

        print()  # newline after progress
        print("-" * 50)
        print("✅ 下载完成!")
        print(f"   完成: {stats.completed_days} 日")
        print(f"   跳过: {stats.skipped_days} 日 (断点续传)")
        print(f"   失败: {stats.failed_days} 日")
        print(f"   总行数: {stats.total_rows:,}")
        print(f"   耗时: {stats.elapsed_seconds:.1f} 秒")

    except KeyboardInterrupt:
        print("\n⚠️ 用户中断，已保存进度（支持断点续传）")
    finally:
        await fetcher.close()


def main():
    parser = argparse.ArgumentParser(
        description="A 股数据批量下载工具 (Tushare)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s status                           # 查看数据状态
  %(prog)s daily_basic                      # 下载 daily_basic (全量)
  %(prog)s adj_factor                       # 下载 adj_factor  (全量)
  %(prog)s daily --incremental              # 增量更新日线 (自动续传)
  %(prog)s daily_basic --start 20210714     # 从指定日期开始
  %(prog)s daily_basic --incremental        # 增量更新 daily_basic
""",
    )

    parser.add_argument(
        "type",
        choices=["daily", "daily_basic", "adj_factor", "status"],
        help="数据类型: daily(日线), daily_basic(每日指标), adj_factor(复权因子), status(查看状态)",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="开始日期 YYYYMMDD (默认 20180101)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="结束日期 YYYYMMDD (默认今天)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="增量模式: 自动从上次下载的最后日期开始",
    )
    parser.add_argument(
        "--data-dir",
        default=str(PROJECT_ROOT / "data"),
        help="数据目录 (默认 PROJECT_ROOT/data)",
    )

    args = parser.parse_args()
    data_dir = Path(args.data_dir)

    if args.type == "status":
        print_status(data_dir)
        return

    # 确定日期范围
    end_date = args.end or datetime.now().strftime("%Y%m%d")

    if args.incremental:
        # checkpoint timeframe key: 1d for daily, else same as type
        tf_key = "1d" if args.type == "daily" else args.type
        latest = get_latest_completed_date(data_dir, tf_key)
        if latest:
            # 从最后完成日期的下一天开始
            from datetime import timedelta

            last_dt = datetime.strptime(latest, "%Y%m%d")
            next_dt = last_dt + timedelta(days=1)
            start_date = next_dt.strftime("%Y%m%d")
            print(f"🔄 增量模式: 上次完成到 {latest}, 从 {start_date} 开始")

            if start_date > end_date:
                print("✅ 数据已是最新，无需更新")
                return
        else:
            start_date = args.start or "20180101"
            print(f"📦 首次下载，从 {start_date} 开始")
    else:
        start_date = args.start or "20180101"

    asyncio.run(run_backfill(args.type, start_date, end_date, data_dir))


if __name__ == "__main__":
    main()
