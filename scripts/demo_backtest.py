#!/usr/bin/env python3
"""
回测演示脚本

功能:
- 从 Parquet 加载数据
- 使用示例策略 (双均线交叉)
- 运行回测
- 打印核心指标 (夏普、最大回撤、胜率)
- 生成 HTML 报告

使用方式:
    python scripts/demo_backtest.py
    python scripts/demo_backtest.py --strategy dual_ma --fast 5 --slow 20
    python scripts/demo_backtest.py --days 30 --capital 50000
"""

import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.reports import (
    ReportConfig,
    ReportGenerator,
    generate_markdown_report,
    generate_text_report,
)
from src.core.instruments import Exchange, Symbol
from src.core.timeframes import Timeframe
from src.data.storage.parquet_store import ParquetStore
from src.ops.logging import get_logger
from src.strategy.base import StrategyConfig
from src.strategy.examples.trend_following import (
    DonchianBreakoutStrategy,
    DualMAStrategy,
)

logger = get_logger(__name__)


def generate_html_report(summary, equity_curve, trades) -> str:
    """
    生成 HTML 格式报告

    Args:
        summary: 回测摘要
        equity_curve: 权益曲线
        trades: 成交记录

    Returns:
        HTML 报告内容
    """
    # 生成权益曲线数据
    equity_data = []
    for ep in equity_curve:
        equity_data.append({
            "timestamp": ep.timestamp.isoformat(),
            "equity": float(ep.equity),
            "drawdown_pct": float(ep.drawdown_pct) * 100,
        })

    # 生成成交记录数据
    trades_data = []
    for t in trades[:100]:  # 最多显示 100 条
        trades_data.append({
            "timestamp": t.timestamp.isoformat() if hasattr(t.timestamp, 'isoformat') else str(t.timestamp),
            "symbol": t.symbol,
            "side": t.side.value if hasattr(t.side, 'value') else str(t.side),
            "quantity": str(t.quantity),
            "price": str(t.price),
            "commission": str(t.commission),
        })

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>回测报告 - {summary.strategy_name}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ text-align: center; color: #2c3e50; margin-bottom: 30px; }}
        h2 {{ color: #34495e; margin: 20px 0 15px; padding-bottom: 10px; border-bottom: 2px solid #3498db; }}
        .card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .metric {{
            text-align: center;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
        }}
        .metric-label {{ font-size: 12px; color: #666; margin-bottom: 5px; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
        .metric-value.positive {{ color: #27ae60; }}
        .metric-value.negative {{ color: #e74c3c; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        tr:hover {{ background: #f8f9fa; }}
        .chart-container {{ height: 400px; margin: 20px 0; }}
        .footer {{ text-align: center; color: #666; margin-top: 30px; font-size: 12px; }}
        .info-table td:first-child {{ font-weight: 500; color: #666; width: 150px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 回测报告</h1>

        <div class="card">
            <h2>📋 基本信息</h2>
            <table class="info-table">
                <tr><td>策略名称</td><td>{summary.strategy_name}</td></tr>
                <tr><td>运行ID</td><td>{summary.run_id}</td></tr>
                <tr><td>交易对</td><td>{', '.join(summary.symbols)}</td></tr>
                <tr><td>时间框架</td><td>{summary.timeframe}</td></tr>
                <tr><td>回测区间</td><td>{summary.start_date} ~ {summary.end_date}</td></tr>
                <tr><td>运行耗时</td><td>{summary.run_duration_seconds:.2f} 秒</td></tr>
            </table>
        </div>

        <div class="card">
            <h2>💰 资金概览</h2>
            <div class="metrics-grid">
                <div class="metric">
                    <div class="metric-label">初始资金</div>
                    <div class="metric-value">{summary.initial_capital:,.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">最终权益</div>
                    <div class="metric-value">{summary.final_equity:,.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">总盈亏</div>
                    <div class="metric-value {'positive' if summary.total_pnl >= 0 else 'negative'}">{summary.total_pnl:+,.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">总收益率</div>
                    <div class="metric-value {'positive' if summary.total_return >= 0 else 'negative'}">{summary.total_return * 100:+.2f}%</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>📈 绩效指标</h2>
            <div class="metrics-grid">
                <div class="metric">
                    <div class="metric-label">年化收益</div>
                    <div class="metric-value {'positive' if summary.metrics.annualized_return >= 0 else 'negative'}">{summary.metrics.annualized_return * 100:.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">年化波动</div>
                    <div class="metric-value">{summary.metrics.volatility * 100:.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">夏普比率</div>
                    <div class="metric-value {'positive' if summary.metrics.sharpe_ratio >= 0 else 'negative'}">{summary.metrics.sharpe_ratio:.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">最大回撤</div>
                    <div class="metric-value negative">{summary.metrics.max_drawdown * 100:.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">索提诺比率</div>
                    <div class="metric-value">{summary.metrics.sortino_ratio:.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">卡尔玛比率</div>
                    <div class="metric-value">{summary.metrics.calmar_ratio:.2f}</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>📊 交易统计</h2>
            <div class="metrics-grid">
                <div class="metric">
                    <div class="metric-label">总交易次数</div>
                    <div class="metric-value">{summary.metrics.trade_stats.total_trades}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">胜率</div>
                    <div class="metric-value">{summary.metrics.trade_stats.win_rate * 100:.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">盈亏比</div>
                    <div class="metric-value">{summary.metrics.trade_stats.profit_factor:.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">总手续费</div>
                    <div class="metric-value">{summary.metrics.trade_stats.total_commission:,.2f}</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>📈 权益曲线</h2>
            <div class="chart-container">
                <canvas id="equityChart"></canvas>
            </div>
        </div>

        <div class="card">
            <h2>📉 回撤曲线</h2>
            <div class="chart-container">
                <canvas id="drawdownChart"></canvas>
            </div>
        </div>

        <div class="card">
            <h2>📝 成交记录 (最近 {min(len(trades_data), 100)} 条)</h2>
            <table>
                <thead>
                    <tr>
                        <th>时间</th>
                        <th>交易对</th>
                        <th>方向</th>
                        <th>数量</th>
                        <th>价格</th>
                        <th>手续费</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(f'<tr><td>{t["timestamp"][:19]}</td><td>{t["symbol"]}</td><td>{t["side"]}</td><td>{t["quantity"]}</td><td>{t["price"]}</td><td>{t["commission"]}</td></tr>' for t in trades_data)}
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>生成时间: {summary.run_timestamp} | AlgorithmTrader</p>
        </div>
    </div>

    <script>
        // 权益曲线数据
        const equityData = {equity_data};

        // 权益曲线图表
        const equityCtx = document.getElementById('equityChart').getContext('2d');
        new Chart(equityCtx, {{
            type: 'line',
            data: {{
                labels: equityData.map(d => d.timestamp.substring(0, 16)),
                datasets: [{{
                    label: '权益',
                    data: equityData.map(d => d.equity),
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    fill: true,
                    tension: 0.1,
                    pointRadius: 0,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: true }} }},
                scales: {{
                    x: {{ display: true, title: {{ display: true, text: '时间' }} }},
                    y: {{ display: true, title: {{ display: true, text: '权益' }} }}
                }}
            }}
        }});

        // 回撤曲线图表
        const ddCtx = document.getElementById('drawdownChart').getContext('2d');
        new Chart(ddCtx, {{
            type: 'line',
            data: {{
                labels: equityData.map(d => d.timestamp.substring(0, 16)),
                datasets: [{{
                    label: '回撤 (%)',
                    data: equityData.map(d => -d.drawdown_pct),
                    borderColor: '#e74c3c',
                    backgroundColor: 'rgba(231, 76, 60, 0.1)',
                    fill: true,
                    tension: 0.1,
                    pointRadius: 0,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: true }} }},
                scales: {{
                    x: {{ display: true, title: {{ display: true, text: '时间' }} }},
                    y: {{ display: true, title: {{ display: true, text: '回撤 (%)' }} }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    return html


def run_backtest(
    symbols: list[str],
    days: int,
    capital: float,
    strategy_name: str,
    fast_period: int,
    slow_period: int,
    output_dir: str,
) -> None:
    """
    运行回测

    Args:
        symbols: 交易对列表
        days: 回测天数
        capital: 初始资金
        strategy_name: 策略名称
        fast_period: 快线周期
        slow_period: 慢线周期
        output_dir: 报告输出目录
    """
    print("=" * 60)
    print("AlgorithmTrader 回测演示")
    print("=" * 60)

    # 解析交易对
    symbol_list: list[Symbol] = []
    for s in symbols:
        parts = s.split("/")
        if len(parts) == 2:
            symbol_list.append(Symbol(exchange=Exchange.OKX, base=parts[0], quote=parts[1]))
        else:
            print(f"警告: 无效的交易对格式 '{s}'，跳过")

    if not symbol_list:
        print("错误: 没有有效的交易对")
        return

    # 时间范围
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    print(f"\n配置:")
    print(f"  交易对: {', '.join(str(s) for s in symbol_list)}")
    print(f"  策略: {strategy_name}")
    print(f"  参数: fast={fast_period}, slow={slow_period}")
    print(f"  初始资金: {capital:,.2f}")
    print(f"  时间范围: {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} ({days} 天)")

    # 检查数据是否存在
    parquet_store = ParquetStore()
    timeframe = Timeframe.M15

    print(f"\n检查数据...")
    for symbol in symbol_list:
        df = parquet_store.read(symbol, timeframe, start, end)
        if df.empty:
            print(f"  ⚠️  {symbol}: 无数据，请先运行 demo_collect.py")
        else:
            print(f"  ✓ {symbol}: {len(df):,} 条记录")

    # 创建策略
    print(f"\n初始化策略...")
    strategy_config = StrategyConfig(
        name=strategy_name,
        symbols=[str(s) for s in symbol_list],
        timeframe=timeframe.value,
        params={
            "fast_period": fast_period,
            "slow_period": slow_period,
            "position_size": 0.1,  # 每次交易 10% 仓位
        },
    )

    if strategy_name == "donchian":
        strategy = DonchianBreakoutStrategy(config=strategy_config)
    else:
        strategy = DualMAStrategy(config=strategy_config)

    # 创建回测引擎
    backtest_config = BacktestConfig(
        initial_capital=Decimal(str(capital)),
        slippage_pct=Decimal("0.0005"),
        commission_rate=Decimal("0.001"),
        start_date=start,
        end_date=end,
        lookback_bars=max(fast_period, slow_period) + 10,
    )

    engine = BacktestEngine(config=backtest_config, parquet_store=parquet_store)

    # 运行回测
    print(f"\n运行回测...")
    result = engine.run(
        strategy=strategy,
        symbols=symbol_list,
        timeframe=timeframe,
    )

    # 生成报告
    print(f"\n生成报告...")
    report_generator = ReportGenerator(
        config=ReportConfig(
            output_dir=output_dir,
            write_to_influx=False,
            save_parquet=True,
            save_json=True,
        ),
    )

    summary = report_generator.generate_summary(result)

    # 打印文本报告
    print("\n" + generate_text_report(summary))

    # 保存 HTML 报告
    output_path = Path(output_dir) / summary.run_id
    output_path.mkdir(parents=True, exist_ok=True)

    html_report = generate_html_report(summary, result.equity_curve, result.trades)
    html_path = output_path / "report.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_report)

    # 保存 Markdown 报告
    md_report = generate_markdown_report(summary)
    md_path = output_path / "report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)

    # 保存其他文件
    report_generator.generate_report(result, summary.run_id)

    print(f"\n📁 报告已保存到: {output_path}")
    print(f"  - HTML 报告: {html_path}")
    print(f"  - Markdown 报告: {md_path}")

    # 核心指标汇总
    print("\n" + "=" * 60)
    print("📊 核心指标汇总")
    print("=" * 60)
    print(f"  总收益率: {summary.total_return * 100:+.2f}%")
    print(f"  夏普比率: {summary.metrics.sharpe_ratio:.2f}")
    print(f"  最大回撤: {summary.metrics.max_drawdown * 100:.2f}%")
    print(f"  胜率: {summary.metrics.trade_stats.win_rate * 100:.2f}%")
    print(f"  总交易次数: {summary.metrics.trade_stats.total_trades}")
    print("=" * 60)


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="AlgorithmTrader 回测演示",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT",
        help="交易对列表，逗号分隔 (默认: BTC/USDT)",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="回测天数 (默认: 7)",
    )

    parser.add_argument(
        "--capital",
        type=float,
        default=100000,
        help="初始资金 (默认: 100000)",
    )

    parser.add_argument(
        "--strategy",
        type=str,
        default="dual_ma",
        choices=["dual_ma", "donchian"],
        help="策略名称 (默认: dual_ma)",
    )

    parser.add_argument(
        "--fast",
        type=int,
        default=10,
        help="快线/入场周期 (默认: 10)",
    )

    parser.add_argument(
        "--slow",
        type=int,
        default=30,
        help="慢线/出场周期 (默认: 30)",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="reports",
        help="报告输出目录 (默认: reports)",
    )

    args = parser.parse_args()

    # 解析交易对
    symbols = [s.strip() for s in args.symbols.split(",")]

    # 运行回测
    run_backtest(
        symbols=symbols,
        days=args.days,
        capital=args.capital,
        strategy_name=args.strategy,
        fast_period=args.fast,
        slow_period=args.slow,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()
