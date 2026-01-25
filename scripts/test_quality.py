#!/usr/bin/env python
"""测试 Data Quality Checker - 数据质量检查"""

import asyncio
import sys
import json

# 添加项目根目录到 Python 路径
sys.path.insert(0, "/app")

from src.core.instruments import Symbol, Exchange
from src.core.timeframes import Timeframe
from src.data.quality import DataQualityChecker, check_all_data_quality


def main():
    print("=" * 60)
    print("测试 Data Quality Checker - 数据质量检查")
    print("=" * 60)
    
    # 1. 创建 Quality Checker
    print("\n1. 创建 Quality Checker...")
    
    checker = DataQualityChecker()
    
    # 2. 检查 BTC/USDT 数据质量
    print("\n2. 检查 BTC/USDT 15m 数据质量...")
    
    symbol = Symbol(exchange=Exchange.OKX, base="BTC", quote="USDT")
    timeframe = Timeframe.M15
    
    report = checker.generate_report(symbol, timeframe)
    
    print(f"   总 Bar 数: {report.total_bars}")
    print(f"   期望 Bar 数: {report.expected_bars}")
    print(f"   数据完整度: {report.completeness:.2%}")
    print(f"   缺口数量: {report.gap_count}")
    print(f"   错误数量: {report.error_count}")
    print(f"   数据健康: {'✓' if report.is_healthy else '✗'}")
    
    if report.issues:
        print(f"\n   问题列表 (显示前 5 个):")
        for issue in report.issues[:5]:
            print(f"   - [{issue.severity}] {issue.issue_type}: {issue.description}")
    
    # 3. 检查所有数据
    print("\n3. 检查所有配置的数据...")
    
    all_reports = check_all_data_quality()
    
    print(f"\n   共检查 {len(all_reports)} 个数据源:")
    for key, r in all_reports.items():
        status = "✓ 健康" if r.is_healthy else f"✗ {r.error_count} 错误"
        print(f"   - {key}: {r.total_bars} bars, 完整度 {r.completeness:.1%}, {status}")
    
    # 4. 导出报告
    print("\n4. 导出报告为 JSON...")
    
    report_dict = report.to_dict()
    print(json.dumps(report_dict, indent=2, ensure_ascii=False, default=str)[:500] + "...")
    
    print("\n" + "=" * 60)
    print("Data Quality Checker 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
