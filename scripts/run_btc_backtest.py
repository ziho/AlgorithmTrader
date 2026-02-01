#!/usr/bin/env python3
"""
🚀 BTC 策略回测 - 完整演示

这个脚本会:
1. 从 OKX 采集 BTC/USDT 1小时K线历史数据 (2025年全年)
2. 保存到 Parquet 存储
3. 使用双均线策略运行回测
4. 生成报告到 reports/ 目录
5. 将结果写入 InfluxDB (供 Grafana 可视化)

使用方式 (在 Docker 容器中运行):
    docker-compose exec collector python scripts/run_btc_backtest.py
    
    # 跳过数据采集（使用已有数据）
    docker-compose exec collector python scripts/run_btc_backtest.py --skip-collect
    
    # 指定时间范围
    docker-compose exec collector python scripts/run_btc_backtest.py --start 2025-01-01 --end 2025-12-31
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
    """打印欢迎横幅"""
    print("\n" + "=" * 70)
    print("🚀 AlgorithmTrader - BTC 策略回测")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"项目目录: {PROJECT_ROOT}")
    print("-" * 70)


def print_step(step: int, total: int, title: str):
    """打印步骤"""
    print(f"\n{'='*70}")
    print(f"[{step}/{total}] {title}")
    print("-" * 70)


async def collect_historical_data(
    symbol_str: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """
    批量采集历史数据
    
    OKX 公共 API 每次最多 100 条
    1小时K线，1年 ≈ 8760 条，需要分批拉取
    """
    from src.core.instruments import Exchange, Symbol
    from src.core.timeframes import Timeframe
    from src.data.connectors.okx import OKXConnector
    from src.data.storage.parquet_store import ParquetStore
    
    print(f"  📊 交易对: {symbol_str}")
    print(f"  ⏰ 时间框架: {timeframe}")
    print(f"  📅 开始时间: {start_date.strftime('%Y-%m-%d')}")
    print(f"  📅 结束时间: {end_date.strftime('%Y-%m-%d')}")
    
    # 解析交易对
    base, quote = symbol_str.split("/")
    symbol = Symbol(exchange=Exchange.OKX, base=base, quote=quote)
    tf = Timeframe(timeframe)
    
    # 计算需要的 bar 数量
    tf_hours = {"1h": 1, "4h": 4, "15m": 0.25, "1d": 24}
    hours_per_bar = tf_hours.get(timeframe, 1)
    total_hours = (end_date - start_date).total_seconds() / 3600
    expected_bars = int(total_hours / hours_per_bar)
    print(f"  📈 预期数据量: ~{expected_bars} 条")
    
    # 初始化连接器和存储
    connector = OKXConnector()
    parquet_store = ParquetStore(base_path=PROJECT_ROOT / "data" / "parquet")
    
    # 分批拉取数据
    all_data = []
    current_start = start_date
    batch_size = 100
    batch_count = 0
    
    print("\n  ⏳ 开始采集数据...")
    print("  " + "-" * 50)
    
    while current_start < end_date:
        try:
            df = await connector.fetch_ohlcv(
                symbol=symbol,
                timeframe=tf,
                since=current_start,
                limit=batch_size,
            )
            
            if df.empty:
                print("  ⚠️ 没有更多数据")
                break
            
            all_data.append(df)
            batch_count += 1
            
            # 更新进度
            last_ts = df["timestamp"].max()
            progress = (last_ts.timestamp() - start_date.timestamp()) / \
                      (end_date.timestamp() - start_date.timestamp()) * 100
            progress = min(progress, 100)
            
            bars = sum(len(d) for d in all_data)
            
            # 每10批显示一次进度
            if batch_count % 10 == 0 or progress >= 99:
                print(f"  📊 进度: {progress:5.1f}% | 已采集 {bars:5d} 条 | 批次 {batch_count:3d} | 最新: {last_ts.strftime('%Y-%m-%d %H:%M')}")
            
            # 移动到下一批
            if timeframe == "1h":
                current_start = last_ts.to_pydatetime() + timedelta(hours=1)
            elif timeframe == "4h":
                current_start = last_ts.to_pydatetime() + timedelta(hours=4)
            elif timeframe == "15m":
                current_start = last_ts.to_pydatetime() + timedelta(minutes=15)
            elif timeframe == "1d":
                current_start = last_ts.to_pydatetime() + timedelta(days=1)
            else:
                current_start = last_ts.to_pydatetime() + timedelta(hours=1)
            
            # 避免限频（OKX 限制）
            await asyncio.sleep(0.2)
            
        except Exception as e:
            print(f"  ❌ 采集错误: {e}")
            await asyncio.sleep(1)  # 出错后等待一秒重试
            continue
    
    await connector.close()
    
    if not all_data:
        print("  ❌ 未采集到任何数据！")
        return pd.DataFrame()
    
    # 合并数据
    df = pd.concat(all_data, ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    
    # 过滤时间范围 - 使用 tz_localize 处理时区
    start_ts = pd.Timestamp(start_date.replace(tzinfo=None)).tz_localize('UTC')
    end_ts = pd.Timestamp(end_date.replace(tzinfo=None)).tz_localize('UTC')
    df = df[(df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)]
    
    print("  " + "-" * 50)
    print(f"\n  ✅ 采集完成!")
    print(f"     总批次: {batch_count}")
    print(f"     数据量: {len(df)} 条")
    print(f"     时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    
    # 保存到 Parquet
    try:
        rows = parquet_store.write(symbol, tf, df)
        print(f"  ✅ 已保存到 Parquet: {rows} 行")
        print(f"     存储位置: {PROJECT_ROOT / 'data' / 'parquet' / 'okx' / symbol_str.replace('/', '_')}")
    except Exception as e:
        print(f"  ⚠️ Parquet 写入失败: {e}")
        print(f"     数据保留在内存中，回测可继续")
    
    return df


def load_data(symbol_str: str, timeframe: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """从 Parquet 加载数据"""
    from src.core.instruments import Exchange, Symbol
    from src.core.timeframes import Timeframe
    from src.data.storage.parquet_store import ParquetStore
    
    base, quote = symbol_str.split("/")
    symbol = Symbol(exchange=Exchange.OKX, base=base, quote=quote)
    tf = Timeframe(timeframe)
    
    store = ParquetStore(base_path=PROJECT_ROOT / "data" / "parquet")
    
    df = store.read(symbol, tf, start=start_date, end=end_date)
    
    if df.empty:
        print(f"  ⚠️ 没有找到 {symbol_str} {timeframe} 的数据")
    else:
        print(f"  ✅ 加载 {len(df)} 条数据")
        print(f"     时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    
    return df


def run_backtest(df: pd.DataFrame, symbol_str: str, timeframe: str) -> object:
    """运行回测"""
    from src.backtest.engine import BacktestConfig, BacktestEngine
    from src.strategy.base import StrategyConfig
    from src.strategy.examples.trend_following import DualMAStrategy
    
    print(f"  🎯 策略: 双均线交叉 (DualMA)")
    print(f"  📊 参数: fast_period=10, slow_period=30")
    print(f"  💰 初始资金: 100,000 USDT")
    print(f"  💸 手续费: 0.1%, 滑点: 0.05%")
    print(f"  📈 数据条数: {len(df)}")
    
    # 回测配置
    bt_config = BacktestConfig(
        initial_capital=Decimal("100000"),
        slippage_pct=Decimal("0.0005"),
        commission_rate=Decimal("0.001"),
    )
    
    # 策略配置
    strategy_config = StrategyConfig(
        name="dual_ma_btc",
        symbols=[symbol_str],
        params={
            "fast_period": 10,
            "slow_period": 30,
        },
    )
    strategy = DualMAStrategy(config=strategy_config)
    
    # 运行回测
    print("\n  ⏳ 正在运行回测...")
    
    engine = BacktestEngine(config=bt_config)
    result = engine.run_with_data(
        strategy=strategy,
        data={symbol_str: df},
        timeframe=timeframe,
    )
    
    # 打印结果
    summary = result.summary
    print("\n  " + "=" * 50)
    print("  📈 回测结果摘要")
    print("  " + "-" * 50)
    print(f"     总收益率:   {summary.total_return:+.2%}")
    print(f"     年化收益:   {summary.annualized_return:+.2%}")
    print(f"     夏普比率:   {summary.sharpe_ratio:.2f}")
    print(f"     索提诺比率: {summary.sortino_ratio:.2f}")
    print(f"     最大回撤:   {summary.max_drawdown:.2%}")
    print(f"     卡玛比率:   {summary.calmar_ratio:.2f}")
    print(f"     胜率:       {summary.win_rate:.2%}")
    print(f"     盈亏比:     {summary.profit_factor:.2f}")
    print(f"     总交易数:   {summary.total_trades}")
    print(f"     总盈亏:     {summary.total_pnl:+,.2f} USDT")
    print(f"     最终权益:   {result.final_equity:,.2f} USDT")
    print("  " + "=" * 50)
    
    return result


def generate_reports(result, output_dir: Path, run_id: str) -> dict:
    """生成报告"""
    from src.backtest.reports import ReportConfig, ReportGenerator
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    config = ReportConfig(
        output_dir=str(output_dir),
        save_json=True,
        save_parquet=True,
        write_to_influx=False,  # 单独处理 InfluxDB
    )
    
    generator = ReportGenerator(config=config)
    report = generator.generate_report(result, run_id=run_id)
    
    print(f"  ✅ 报告已保存到: {output_dir / run_id}")
    
    # 生成 HTML 报告
    html_path = output_dir / run_id / "report.html"
    generate_html_report(result, html_path)
    print(f"  ✅ HTML 报告: {html_path}")
    
    return {"run_id": run_id, "path": output_dir / run_id}


def generate_html_report(result, output_path: Path):
    """生成 HTML 报告"""
    import json
    
    summary = result.summary
    
    # 权益曲线数据
    equity_data = [
        {"x": ep.timestamp.isoformat(), "y": float(ep.equity)}
        for ep in result.equity_curve
    ]
    
    # 回撤数据
    drawdown_data = [
        {"x": ep.timestamp.isoformat(), "y": float(ep.drawdown_pct) * 100}
        for ep in result.equity_curve
    ]
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BTC 回测报告 - 双均线策略</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ text-align: center; color: #00d4ff; margin-bottom: 10px; font-size: 2.5em; }}
        .subtitle {{ text-align: center; color: #888; margin-bottom: 40px; }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 40px;
        }}
        .metric-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; margin-bottom: 5px; }}
        .metric-value.positive {{ color: #00ff88; }}
        .metric-value.negative {{ color: #ff4444; }}
        .metric-label {{ color: #888; font-size: 0.85em; }}
        .chart-container {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 25px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .chart-title {{ color: #00d4ff; margin-bottom: 15px; font-size: 1.2em; }}
        .chart-wrapper {{ height: 350px; }}
        .footer {{ text-align: center; color: #666; margin-top: 40px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.1); }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 BTC/USDT 回测报告</h1>
        <p class="subtitle">双均线交叉策略 | 1小时K线 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        
        <div class="metrics">
            <div class="metric-card">
                <div class="metric-value {'positive' if summary.total_return >= 0 else 'negative'}">{summary.total_return:+.2%}</div>
                <div class="metric-label">总收益率</div>
            </div>
            <div class="metric-card">
                <div class="metric-value {'positive' if summary.annualized_return >= 0 else 'negative'}">{summary.annualized_return:+.2%}</div>
                <div class="metric-label">年化收益</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{summary.sharpe_ratio:.2f}</div>
                <div class="metric-label">夏普比率</div>
            </div>
            <div class="metric-card">
                <div class="metric-value negative">{summary.max_drawdown:.2%}</div>
                <div class="metric-label">最大回撤</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{summary.win_rate:.1%}</div>
                <div class="metric-label">胜率</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{summary.profit_factor:.2f}</div>
                <div class="metric-label">盈亏比</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{summary.total_trades}</div>
                <div class="metric-label">总交易数</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{float(result.final_equity):,.0f}</div>
                <div class="metric-label">最终权益</div>
            </div>
        </div>
        
        <div class="chart-container">
            <h3 class="chart-title">💰 权益曲线</h3>
            <div class="chart-wrapper"><canvas id="equityChart"></canvas></div>
        </div>
        
        <div class="chart-container">
            <h3 class="chart-title">📉 回撤曲线</h3>
            <div class="chart-wrapper"><canvas id="drawdownChart"></canvas></div>
        </div>
        
        <div class="footer">
            <p>🤖 AlgorithmTrader - 个人量化交易系统</p>
            <p style="margin-top: 5px; font-size: 0.9em;">报告目录: {output_path.parent}</p>
        </div>
    </div>
    
    <script>
        const equityData = {json.dumps(equity_data)};
        const drawdownData = {json.dumps(drawdown_data)};
        
        new Chart(document.getElementById('equityChart'), {{
            type: 'line',
            data: {{ datasets: [{{ label: '权益', data: equityData, borderColor: '#00d4ff', backgroundColor: 'rgba(0, 212, 255, 0.1)', fill: true, tension: 0.1, pointRadius: 0 }}] }},
            options: {{
                responsive: true, maintainAspectRatio: false,
                scales: {{
                    x: {{ type: 'time', time: {{ unit: 'month' }}, grid: {{ color: 'rgba(255,255,255,0.1)' }}, ticks: {{ color: '#888' }} }},
                    y: {{ grid: {{ color: 'rgba(255,255,255,0.1)' }}, ticks: {{ color: '#888' }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});
        
        new Chart(document.getElementById('drawdownChart'), {{
            type: 'line',
            data: {{ datasets: [{{ label: '回撤 %', data: drawdownData, borderColor: '#ff4444', backgroundColor: 'rgba(255, 68, 68, 0.2)', fill: true, tension: 0.1, pointRadius: 0 }}] }},
            options: {{
                responsive: true, maintainAspectRatio: false,
                scales: {{
                    x: {{ type: 'time', time: {{ unit: 'month' }}, grid: {{ color: 'rgba(255,255,255,0.1)' }}, ticks: {{ color: '#888' }} }},
                    y: {{ reverse: true, grid: {{ color: 'rgba(255,255,255,0.1)' }}, ticks: {{ color: '#888' }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});
    </script>
</body>
</html>
"""
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def write_to_influxdb(result, run_id: str) -> bool:
    """写入 InfluxDB（Grafana 可视化）"""
    try:
        from src.data.storage.influx_store import InfluxStore
        
        store = InfluxStore()
        
        # 写入权益曲线
        points_written = store.write_backtest_equity(
            run_id=run_id,
            equity_curve=result.equity_curve,
            sample_rate=1,
        )
        
        print(f"  ✅ 已写入 InfluxDB: {points_written} 个数据点")
        print(f"     📊 Grafana 查看: http://localhost:3000")
        print(f"     🗃️ Bucket: trading, Measurement: backtest_equity")
        print(f"     🔑 Run ID: {run_id}")
        
        return True
    except Exception as e:
        print(f"  ⚠️ InfluxDB 写入失败: {e}")
        return False


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="BTC 策略回测")
    parser.add_argument("--start", default="2025-01-01", help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--skip-collect", action="store_true", help="跳过数据采集")
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对")
    parser.add_argument("--timeframe", default="1h", help="时间框架")
    args = parser.parse_args()
    
    print_banner()
    
    symbol = args.symbol
    timeframe = args.timeframe
    
    # 解析日期
    start_date = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
    end_date = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=UTC)
    
    # 如果结束日期在未来，调整为当前时间
    now = datetime.now(UTC)
    if end_date > now:
        end_date = now
        print(f"  ⚠️ 结束日期调整为当前时间: {end_date.strftime('%Y-%m-%d')}")
    
    # 报告输出目录
    output_dir = PROJECT_ROOT / "reports"
    run_id = f"btc_{timeframe}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
    
    total_steps = 4 if not args.skip_collect else 3
    step = 0
    
    # Step 1: 数据采集
    if not args.skip_collect:
        step += 1
        print_step(step, total_steps, "📥 采集历史数据")
        df = await collect_historical_data(symbol, timeframe, start_date, end_date)
        
        if df.empty:
            print("\n❌ 数据采集失败，无法继续")
            return 1
    else:
        step += 1
        print_step(step, total_steps, "📂 加载已有数据")
        df = load_data(symbol, timeframe, start_date, end_date)
        
        if df.empty:
            print("\n❌ 没有找到数据，请先运行采集 (去掉 --skip-collect)")
            return 1
    
    # Step 2: 运行回测
    step += 1
    print_step(step, total_steps, "⚡ 运行回测")
    result = run_backtest(df, symbol, timeframe)
    
    # Step 3: 生成报告
    step += 1
    print_step(step, total_steps, "📝 生成报告")
    report_info = generate_reports(result, output_dir, run_id)
    
    # Step 4: 写入 InfluxDB
    step += 1
    print_step(step, total_steps, "📊 写入 InfluxDB (Grafana)")
    write_to_influxdb(result, run_id)
    
    # 完成
    print("\n" + "=" * 70)
    print("✅ 回测完成！")
    print("=" * 70)
    print(f"\n📊 结果摘要:")
    print(f"   收益率: {result.summary.total_return:+.2%}")
    print(f"   夏普比率: {result.summary.sharpe_ratio:.2f}")
    print(f"   最大回撤: {result.summary.max_drawdown:.2%}")
    print(f"\n📁 报告位置: {report_info['path']}")
    print(f"🌐 HTML 报告: file:///app/{report_info['path'].relative_to(PROJECT_ROOT)}/report.html")
    print(f"\n🔍 查看方式:")
    print(f"   1. Grafana: http://localhost:3000 (用户: admin, 密码: algorithmtrader123)")
    print(f"   2. Web 界面: http://localhost:8080")
    print(f"   3. HTML 报告: 在本地浏览器打开上述路径")
    print("\n" + "=" * 70)
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
