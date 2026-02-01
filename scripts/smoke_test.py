#!/usr/bin/env python3
"""
一键本地烟雾测试脚本

功能:
1. 生成模拟测试数据
2. 运行单个策略回测
3. 生成报告
4. 验证核心模块可用

使用方式:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --verbose
    python scripts/smoke_test.py --skip-collect
"""

import argparse
import sys
import traceback
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd


def print_step(step: int, title: str, status: str = "⏳"):
    """打印步骤状态"""
    print(f"\n{'='*60}")
    print(f"Step {step}: {title} {status}")
    print("=" * 60)


def print_result(success: bool, message: str):
    """打印结果"""
    status = "✅" if success else "❌"
    print(f"{status} {message}")


def generate_test_data(
    symbol: str = "BTC/USDT",
    days: int = 30,
    timeframe_minutes: int = 15,
) -> pd.DataFrame:
    """
    生成模拟 OHLCV 测试数据

    Args:
        symbol: 交易对
        days: 天数
        timeframe_minutes: 时间框架（分钟）

    Returns:
        DataFrame with OHLCV data
    """
    # 计算数据点数量
    bars_per_day = 24 * 60 // timeframe_minutes
    total_bars = days * bars_per_day

    # 生成时间序列
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(days=days)
    timestamps = pd.date_range(start=start_time, periods=total_bars, freq=f"{timeframe_minutes}min")

    # 生成随机价格（模拟真实走势）
    np.random.seed(42)  # 可重复性

    # 使用几何布朗运动模拟价格
    initial_price = 50000  # 初始价格
    mu = 0.0001  # 漂移率
    sigma = 0.02  # 波动率

    returns = np.random.normal(mu, sigma, total_bars)
    prices = initial_price * np.exp(np.cumsum(returns))

    # 生成 OHLCV
    data = []
    for i, (ts, close) in enumerate(zip(timestamps, prices)):
        # 模拟日内波动
        high = close * (1 + abs(np.random.normal(0, 0.005)))
        low = close * (1 - abs(np.random.normal(0, 0.005)))
        open_price = prices[i - 1] if i > 0 else close * (1 + np.random.normal(0, 0.002))

        # 确保 OHLC 逻辑正确
        high = max(high, open_price, close)
        low = min(low, open_price, close)

        volume = abs(np.random.normal(1000, 300))

        data.append({
            "timestamp": ts,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    df = pd.DataFrame(data)
    return df


def test_data_generation() -> tuple[bool, pd.DataFrame | None]:
    """测试数据生成"""
    try:
        df = generate_test_data(days=10)

        # 验证数据结构
        required_columns = ["timestamp", "open", "high", "low", "close", "volume"]
        assert all(col in df.columns for col in required_columns), "Missing columns"
        assert len(df) > 100, f"Not enough data: {len(df)}"
        assert (df["high"] >= df["low"]).all(), "Invalid OHLC: high < low"
        assert (df["high"] >= df["close"]).all(), "Invalid OHLC: high < close"
        assert (df["low"] <= df["close"]).all(), "Invalid OHLC: low > close"

        return True, df
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False, None


def test_strategy_import() -> tuple[bool, type | None]:
    """测试策略导入"""
    try:
        from src.strategy.examples.trend_following import DualMAStrategy

        # 验证策略类
        assert hasattr(DualMAStrategy, "on_bar"), "Missing on_bar method"
        assert hasattr(DualMAStrategy, "initialize"), "Missing initialize method"

        return True, DualMAStrategy
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False, None


def test_backtest_engine(df: pd.DataFrame, strategy_class: type) -> tuple[bool, object | None]:
    """测试回测引擎"""
    try:
        from src.backtest.engine import BacktestConfig, BacktestEngine
        from src.strategy.base import StrategyConfig

        # 创建配置
        config = BacktestConfig(
            initial_capital=Decimal("100000"),
            slippage_pct=Decimal("0.0005"),
            commission_rate=Decimal("0.001"),
        )

        # 创建策略
        strategy_config = StrategyConfig(
            name="test_dual_ma",
            symbols=["BTC/USDT"],
            params={"fast_period": 5, "slow_period": 20},
        )
        strategy = strategy_class(config=strategy_config)

        # 创建引擎并运行
        engine = BacktestEngine(config=config)
        result = engine.run_with_data(
            strategy=strategy,
            data={"BTC/USDT": df},
            timeframe="15m",
        )

        # 验证结果
        assert result is not None, "Result is None"
        assert result.final_equity > 0, "Final equity is 0"
        assert len(result.equity_curve) > 0, "Empty equity curve"

        # 验证 summary 属性
        summary = result.summary
        assert summary is not None, "Summary is None"
        assert hasattr(summary, "total_return"), "Missing total_return"
        assert hasattr(summary, "sharpe_ratio"), "Missing sharpe_ratio"

        return True, result
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False, None


def test_metrics_calculation(result) -> bool:
    """测试指标计算"""
    try:
        from src.backtest.metrics import MetricsCalculator

        import numpy as np

        # 提取权益曲线
        equity_values = np.array([float(ep.equity) for ep in result.equity_curve])
        timestamps = [ep.timestamp for ep in result.equity_curve]

        # 计算指标
        calculator = MetricsCalculator()
        metrics = calculator.calculate_all(
            equity_values=equity_values,
            timestamps=timestamps,
        )

        # 验证指标
        assert metrics is not None, "Metrics is None"
        assert metrics.trading_days > 0, "No trading days"
        assert not np.isnan(metrics.sharpe_ratio), "Sharpe is NaN"

        return True
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False


def test_report_generation(result) -> bool:
    """测试报告生成"""
    try:
        from src.backtest.reports import ReportConfig, ReportGenerator

        # 创建临时输出目录
        output_dir = Path("reports/smoke_test")
        output_dir.mkdir(parents=True, exist_ok=True)

        # 生成报告
        config = ReportConfig(
            output_dir=str(output_dir),
            save_json=True,
            save_parquet=True,
            write_to_influx=False,
        )
        generator = ReportGenerator(config=config)
        report = generator.generate_report(result, run_id="smoke_test")

        # 验证报告
        assert report is not None, "Report is None"
        assert "summary" in report, "Missing summary"
        assert "saved_files" in report, "Missing saved_files"

        # 验证文件存在
        summary_file = output_dir / "smoke_test" / "summary.json"
        assert summary_file.exists(), f"Summary file not created: {summary_file}"

        return True
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False


def test_feature_engine() -> bool:
    """测试特征引擎"""
    try:
        from src.features.feature_engine import FeatureEngine, get_feature_engine

        # 获取默认引擎
        engine = get_feature_engine()

        # 生成测试数据
        df = generate_test_data(days=5)

        # 计算特征
        sma = engine.calculate("sma", df, {"period": 10})
        rsi = engine.calculate("rsi", df, {"period": 14})

        # 验证
        assert len(sma) == len(df), "SMA length mismatch"
        assert len(rsi) == len(df), "RSI length mismatch"

        # 批量计算
        result_df = engine.calculate_all(df, features=["sma", "ema", "rsi"])
        assert "sma" in result_df.columns, "Missing sma column"
        assert "rsi" in result_df.columns, "Missing rsi column"

        return True
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False


def test_optimization_engine(df: pd.DataFrame, strategy_class: type) -> bool:
    """测试优化引擎（快速验证）"""
    try:
        from src.backtest.engine import BacktestConfig
        from src.optimization.engine import OptimizationConfig, OptimizationEngine
        from src.optimization.methods import GridSearch, ParameterSpace, ParameterSpec
        from src.optimization.objectives import MaximizeSharpe

        # 创建小规模参数空间
        param_space = ParameterSpace()
        param_space.add("fast_period", ParameterSpec(min_val=5, max_val=10, step=5))
        param_space.add("slow_period", ParameterSpec(min_val=15, max_val=20, step=5))

        # 配置优化
        opt_config = OptimizationConfig(
            strategy_class=strategy_class,
            strategy_name="test_opt",
            param_space=param_space,
            objective=MaximizeSharpe(),
            search_method=GridSearch(),
            n_jobs=1,
            min_trades=0,  # 放宽限制以通过测试
        )

        engine = OptimizationEngine(opt_config)

        # 运行优化（使用数据字典）
        result = engine.run(
            data={"BTC/USDT": df},
            backtest_config=BacktestConfig(
                initial_capital=Decimal("100000"),
            ),
        )

        # 验证
        assert result is not None, "Result is None"
        assert result.total_trials > 0, "No trials executed"

        return True
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="AlgorithmTrader 烟雾测试")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--skip-opt", action="store_true", help="跳过优化测试")
    args = parser.parse_args()

    print("\n🚀 AlgorithmTrader 烟雾测试")
    print(f"时间: {datetime.now()}")
    print("-" * 60)

    results = {}
    df = None
    strategy_class = None
    backtest_result = None

    # Step 1: 数据生成
    print_step(1, "测试数据生成")
    success, df = test_data_generation()
    results["data_generation"] = success
    print_result(success, f"生成 {len(df) if df is not None else 0} 条测试数据")

    if not success:
        print("\n❌ 数据生成失败，终止测试")
        return 1

    # Step 2: 策略导入
    print_step(2, "测试策略导入")
    success, strategy_class = test_strategy_import()
    results["strategy_import"] = success
    print_result(success, f"导入策略: {strategy_class.__name__ if strategy_class else 'None'}")

    if not success:
        print("\n❌ 策略导入失败，终止测试")
        return 1

    # Step 3: 回测引擎
    print_step(3, "测试回测引擎")
    success, backtest_result = test_backtest_engine(df, strategy_class)
    results["backtest_engine"] = success
    if success and backtest_result:
        summary = backtest_result.summary
        print_result(success, f"回测完成: 收益率={summary.total_return:.2%}, 夏普={summary.sharpe_ratio:.2f}")
    else:
        print_result(success, "回测失败")

    if not success:
        print("\n❌ 回测引擎测试失败，终止测试")
        return 1

    # Step 4: 指标计算
    print_step(4, "测试指标计算")
    success = test_metrics_calculation(backtest_result)
    results["metrics"] = success
    print_result(success, "指标计算模块正常")

    # Step 5: 报告生成
    print_step(5, "测试报告生成")
    success = test_report_generation(backtest_result)
    results["reports"] = success
    print_result(success, "报告生成模块正常")

    # Step 6: 特征引擎
    print_step(6, "测试特征引擎")
    success = test_feature_engine()
    results["features"] = success
    print_result(success, "特征引擎正常")

    # Step 7: 优化引擎（可选）
    if not args.skip_opt:
        print_step(7, "测试优化引擎")
        success = test_optimization_engine(df, strategy_class)
        results["optimization"] = success
        print_result(success, "优化引擎正常")

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed

    for name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {name}: {status}")

    print("-" * 60)
    print(f"总计: {passed}/{total} 通过")

    if failed > 0:
        print(f"\n❌ {failed} 个测试失败")
        return 1
    else:
        print("\n✅ 所有测试通过！")
        return 0


if __name__ == "__main__":
    sys.exit(main())
