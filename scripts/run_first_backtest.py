#!/usr/bin/env python3
"""
🚀 第一次回测 - 端到端演示

这个脚本会：
1. 从 OKX 采集 BTC/USDT 1小时K线数据（最近3个月）
2. 使用双均线策略运行回测
3. 生成报告（JSON/HTML）
4. 将结果写入 InfluxDB（Grafana 可视化）

使用方式:
    python scripts/run_first_backtest.py

    # 指定时间范围
    python scripts/run_first_backtest.py --days 90

    # 跳过数据采集（使用已有数据）
    python scripts/run_first_backtest.py --skip-collect
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def print_banner():
    """打印欢迎横幅"""
    print("\n" + "=" * 60)
    print("🚀 AlgorithmTrader - 第一次回测")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)


def print_step(step: int, total: int, title: str):
    """打印步骤"""
    print(f"\n[{step}/{total}] {title}")
    print("-" * 40)


async def collect_data(symbol_str: str, timeframe: str, days: int) -> pd.DataFrame:
    """
    从 OKX 采集历史数据
    
    OKX 公共 API 限制：每次最多 100 条，免费无需 API Key
    1小时K线，3个月 ≈ 2160 条，需要分批拉取
    """
    from src.core.instruments import Exchange, Symbol
    from src.core.timeframes import Timeframe
    from src.data.connectors.okx import OKXConnector
    from src.data.storage.parquet_store import ParquetStore
    
    print(f"  交易对: {symbol_str}")
    print(f"  时间框架: {timeframe}")
    print(f"  时间范围: 最近 {days} 天")
    
    # 解析交易对
    base, quote = symbol_str.split("/")
    symbol = Symbol(exchange=Exchange.OKX, base=base, quote=quote)
    tf = Timeframe(timeframe)
    
    # 时间范围
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(days=days)
    
    print(f"  开始时间: {start_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  结束时间: {end_time.strftime('%Y-%m-%d %H:%M')}")
    
    # 初始化连接器和存储
    connector = OKXConnector()
    parquet_store = ParquetStore()
    
    # 分批拉取数据
    all_data = []
    current_start = start_time
    batch_size = 100
    
    print("\n  开始采集数据...")
    
    while current_start < end_time:
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
            
            # 更新进度
            last_ts = df["timestamp"].max()
            progress = (last_ts.timestamp() - start_time.timestamp()) / \
                      (end_time.timestamp() - start_time.timestamp()) * 100
            progress = min(progress, 100)
            
            bars = sum(len(d) for d in all_data)
            print(f"  📊 进度: {progress:.1f}% | 已采集 {bars} 条 | 最新: {last_ts.strftime('%Y-%m-%d %H:%M')}")
            
            # 移动到下一批
            current_start = last_ts.to_pydatetime() + timedelta(hours=1)
            
            # 避免限频（OKX 限制）
            await asyncio.sleep(0.3)
            
        except Exception as e:
            print(f"  ❌ 采集错误: {e}")
            break
    
    if not all_data:
        print("  ❌ 未采集到任何数据！")
        return pd.DataFrame()
    
    # 合并数据
    df = pd.concat(all_data, ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    
    # 尝试保存到 Parquet（可能因权限失败）
    try:
        rows = parquet_store.write(symbol, tf, df)
        print(f"\n  ✅ 采集完成: {len(df)} 条数据")
        print(f"  ✅ 已保存到 Parquet: {rows} 行")
    except PermissionError:
        print(f"\n  ⚠️ Parquet 写入权限不足，跳过保存（数据在内存中可用）")
        print(f"  💡 提示: 运行 'sudo chown -R $USER data/parquet/' 修复权限")
        print(f"  ✅ 采集完成: {len(df)} 条数据")
    
    return df


def load_data(symbol_str: str, timeframe: str, days: int) -> pd.DataFrame:
    """从 Parquet 加载数据"""
    from src.core.instruments import Exchange, Symbol
    from src.core.timeframes import Timeframe
    from src.data.storage.parquet_store import ParquetStore
    
    base, quote = symbol_str.split("/")
    symbol = Symbol(exchange=Exchange.OKX, base=base, quote=quote)
    tf = Timeframe(timeframe)
    
    store = ParquetStore()
    
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(days=days)
    
    df = store.read(symbol, tf, start=start_time, end=end_time)
    
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
    
    print(f"  策略: 双均线交叉 (DualMA)")
    print(f"  参数: fast_period=10, slow_period=30")
    print(f"  初始资金: 100,000 USDT")
    print(f"  手续费: 0.1%, 滑点: 0.05%")
    
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
    print("\n  📈 回测结果:")
    print(f"     总收益率: {summary.total_return:.2%}")
    print(f"     年化收益: {summary.annualized_return:.2%}")
    print(f"     夏普比率: {summary.sharpe_ratio:.2f}")
    print(f"     最大回撤: {summary.max_drawdown:.2%}")
    print(f"     总交易数: {summary.total_trades}")
    print(f"     最终权益: {result.final_equity:,.2f} USDT")
    
    return result


def generate_reports(result, output_dir: Path) -> dict:
    """生成报告"""
    from src.backtest.reports import ReportConfig, ReportGenerator
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成运行ID
    run_id = f"btc_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
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
        {
            "x": ep.timestamp.isoformat(),
            "y": float(ep.equity),
        }
        for ep in result.equity_curve
    ]
    
    # 回撤数据
    drawdown_data = [
        {
            "x": ep.timestamp.isoformat(),
            "y": float(ep.drawdown_pct) * 100,
        }
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
        h1 {{ 
            text-align: center; 
            color: #00d4ff; 
            margin-bottom: 30px;
            font-size: 2.5em;
        }}
        .subtitle {{
            text-align: center;
            color: #888;
            margin-bottom: 40px;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        .metric-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 25px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
            transition: transform 0.3s;
        }}
        .metric-card:hover {{ transform: translateY(-5px); }}
        .metric-value {{
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 8px;
        }}
        .metric-value.positive {{ color: #00ff88; }}
        .metric-value.negative {{ color: #ff4444; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .chart-container {{
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 30px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .chart-title {{
            color: #00d4ff;
            margin-bottom: 20px;
            font-size: 1.3em;
        }}
        .footer {{
            text-align: center;
            color: #666;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid rgba(255,255,255,0.1);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 BTC/USDT 回测报告</h1>
        <p class="subtitle">双均线交叉策略 | 1小时K线 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        
        <div class="metrics">
            <div class="metric-card">
                <div class="metric-value {'positive' if summary.total_return >= 0 else 'negative'}">
                    {summary.total_return:+.2%}
                </div>
                <div class="metric-label">总收益率</div>
            </div>
            <div class="metric-card">
                <div class="metric-value {'positive' if summary.annualized_return >= 0 else 'negative'}">
                    {summary.annualized_return:+.2%}
                </div>
                <div class="metric-label">年化收益</div>
            </div>
            <div class="metric-card">
                <div class="metric-value {'positive' if summary.sharpe_ratio >= 1 else 'negative' if summary.sharpe_ratio < 0 else ''}">
                    {summary.sharpe_ratio:.2f}
                </div>
                <div class="metric-label">夏普比率</div>
            </div>
            <div class="metric-card">
                <div class="metric-value negative">
                    {summary.max_drawdown:.2%}
                </div>
                <div class="metric-label">最大回撤</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">
                    {summary.total_trades}
                </div>
                <div class="metric-label">总交易数</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">
                    {float(result.final_equity):,.0f}
                </div>
                <div class="metric-label">最终权益 (USDT)</div>
            </div>
        </div>
        
        <div class="chart-container">
            <h3 class="chart-title">💰 权益曲线</h3>
            <canvas id="equityChart" height="300"></canvas>
        </div>
        
        <div class="chart-container">
            <h3 class="chart-title">📉 回撤曲线</h3>
            <canvas id="drawdownChart" height="200"></canvas>
        </div>
        
        <div class="footer">
            <p>AlgorithmTrader - 个人量化交易系统</p>
        </div>
    </div>
    
    <script>
        const equityData = {json.dumps(equity_data)};
        const drawdownData = {json.dumps(drawdown_data)};
        
        // 权益曲线图
        new Chart(document.getElementById('equityChart'), {{
            type: 'line',
            data: {{
                datasets: [{{
                    label: '权益',
                    data: equityData,
                    borderColor: '#00d4ff',
                    backgroundColor: 'rgba(0, 212, 255, 0.1)',
                    fill: true,
                    tension: 0.1,
                    pointRadius: 0,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{
                        type: 'time',
                        time: {{ unit: 'day' }},
                        grid: {{ color: 'rgba(255,255,255,0.1)' }},
                        ticks: {{ color: '#888' }}
                    }},
                    y: {{
                        grid: {{ color: 'rgba(255,255,255,0.1)' }},
                        ticks: {{ color: '#888' }}
                    }}
                }},
                plugins: {{
                    legend: {{ display: false }}
                }}
            }}
        }});
        
        // 回撤图
        new Chart(document.getElementById('drawdownChart'), {{
            type: 'line',
            data: {{
                datasets: [{{
                    label: '回撤 %',
                    data: drawdownData,
                    borderColor: '#ff4444',
                    backgroundColor: 'rgba(255, 68, 68, 0.2)',
                    fill: true,
                    tension: 0.1,
                    pointRadius: 0,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{
                        type: 'time',
                        time: {{ unit: 'day' }},
                        grid: {{ color: 'rgba(255,255,255,0.1)' }},
                        ticks: {{ color: '#888' }}
                    }},
                    y: {{
                        reverse: true,
                        grid: {{ color: 'rgba(255,255,255,0.1)' }},
                        ticks: {{ color: '#888' }}
                    }}
                }},
                plugins: {{
                    legend: {{ display: false }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def write_to_influxdb(result, run_id: str):
    """写入 InfluxDB（Grafana 可视化）"""
    try:
        from src.data.storage.influx_store import InfluxStore
        
        store = InfluxStore()
        
        # 写入权益曲线（使用内置方法）
        points_written = store.write_backtest_equity(
            run_id=run_id,
            equity_curve=result.equity_curve,
            sample_rate=1,  # 写入所有点
        )
        
        print(f"  ✅ 已写入 InfluxDB: {points_written} 个数据点")
        print(f"     Grafana 查看: http://localhost:3000")
        print(f"     Bucket: trading, Measurement: backtest_equity")
        
        return True
    except Exception as e:
        print(f"  ⚠️ InfluxDB 写入失败: {e}")
        print(f"     (这不影响回测结果，可能是 InfluxDB 未启动)")
        return False


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="BTC 回测演示")
    parser.add_argument("--days", type=int, default=90, help="回测天数 (默认90天)")
    parser.add_argument("--skip-collect", action="store_true", help="跳过数据采集")
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对")
    parser.add_argument("--timeframe", default="1h", help="时间框架")
    args = parser.parse_args()
    
    print_banner()
    
    symbol = args.symbol
    timeframe = args.timeframe
    days = args.days
    
    # 使用项目目录下的 reports 文件夹
    project_root = Path(__file__).parent.parent
    output_dir = project_root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  📁 报告输出目录: {output_dir}")
    
    total_steps = 4 if not args.skip_collect else 3
    step = 0
    
    # Step 1: 数据采集
    if not args.skip_collect:
        step += 1
        print_step(step, total_steps, "📥 采集历史数据")
        df = await collect_data(symbol, timeframe, days)
        
        if df.empty:
            print("\n❌ 数据采集失败，无法继续")
            return 1
    else:
        step += 1
        print_step(step, total_steps, "📂 加载已有数据")
        df = load_data(symbol, timeframe, days)
        
        if df.empty:
            print("\n❌ 没有找到数据，请先运行采集")
            print("   命令: python scripts/run_first_backtest.py")
            return 1
    
    # Step 2: 运行回测
    step += 1
    print_step(step, total_steps, "⚡ 运行回测")
    result = run_backtest(df, symbol, timeframe)
    
    # Step 3: 生成报告
    step += 1
    print_step(step, total_steps, "📝 生成报告")
    report_info = generate_reports(result, output_dir)
    
    # Step 4: 写入 InfluxDB
    step += 1
    print_step(step, total_steps, "📊 写入 InfluxDB (Grafana)")
    write_to_influxdb(result, report_info["run_id"])
    
    # 完成
    print("\n" + "=" * 60)
    print("✅ 回测完成！")
    print("=" * 60)
    print(f"\n📁 报告位置: {report_info['path']}")
    print(f"🌐 HTML 报告: file://{report_info['path'].absolute()}/report.html")
    print(f"📊 Grafana: http://localhost:3000 (如已启动)")
    print(f"🖥️  Web 界面: 运行 'python -m services.web.main' 后访问")
    print("\n" + "-" * 60)
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
