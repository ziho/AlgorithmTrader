"""
风控引擎测试
"""

from decimal import Decimal

import pytest

from src.risk.engine import (
    MaxDailyLossRule,
    MaxDrawdownRule,
    MaxLeverageRule,
    MaxPositionRule,
    RiskAction,
    RiskCheckResult,
    RiskContext,
    RiskEngine,
    create_default_risk_engine,
)


class TestRiskCheckResult:
    """RiskCheckResult 测试"""

    def test_passed_when_pass(self) -> None:
        """测试 PASS 时 passed 为 True"""
        result = RiskCheckResult(action=RiskAction.PASS)
        assert result.passed is True
        assert result.rejected is False

    def test_passed_when_warn(self) -> None:
        """测试 WARN 时 passed 为 True"""
        result = RiskCheckResult(action=RiskAction.WARN)
        assert result.passed is True
        assert result.rejected is False

    def test_rejected_when_reject(self) -> None:
        """测试 REJECT 时 rejected 为 True"""
        result = RiskCheckResult(action=RiskAction.REJECT)
        assert result.passed is False
        assert result.rejected is True

    def test_to_dict(self) -> None:
        """测试转换为字典"""
        result = RiskCheckResult(
            action=RiskAction.WARN,
            rule_name="test_rule",
            message="Test warning",
            details={"key": "value"},
        )
        d = result.to_dict()

        assert d["action"] == "warn"
        assert d["rule_name"] == "test_rule"
        assert d["message"] == "Test warning"
        assert d["details"] == {"key": "value"}


class TestRiskContext:
    """RiskContext 测试"""

    def test_current_drawdown(self) -> None:
        """测试当前回撤计算"""
        context = RiskContext(
            total_equity=Decimal("9000"),
            peak_equity=Decimal("10000"),
        )
        assert float(context.current_drawdown) == pytest.approx(0.1)

    def test_current_drawdown_zero_peak(self) -> None:
        """测试峰值为零时回撤为零"""
        context = RiskContext(
            total_equity=Decimal("1000"),
            peak_equity=Decimal("0"),
        )
        assert context.current_drawdown == Decimal("0")

    def test_total_position_value(self) -> None:
        """测试总持仓价值"""
        context = RiskContext(
            position_values={
                "BTC/USDT": Decimal("5000"),
                "ETH/USDT": Decimal("3000"),
            }
        )
        assert context.total_position_value == Decimal("8000")


class TestMaxDailyLossRule:
    """MaxDailyLossRule 测试"""

    def test_pass_when_no_loss(self) -> None:
        """测试无亏损时通过"""
        rule = MaxDailyLossRule(max_loss_pct=0.05)
        context = RiskContext(
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("100"),
        )

        result = rule.check(context)
        assert result.action == RiskAction.PASS

    def test_warn_when_near_limit(self) -> None:
        """测试接近限制时警告"""
        rule = MaxDailyLossRule(max_loss_pct=0.05)
        context = RiskContext(
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("-450"),  # 4.5% 亏损
        )

        result = rule.check(context)
        assert result.action == RiskAction.WARN

    def test_reject_when_exceed_limit(self) -> None:
        """测试超过限制时拒绝"""
        rule = MaxDailyLossRule(max_loss_pct=0.05)
        context = RiskContext(
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("-600"),  # 6% 亏损
        )

        result = rule.check(context)
        assert result.action == RiskAction.REJECT
        assert "5.00%" in result.message


class TestMaxDrawdownRule:
    """MaxDrawdownRule 测试"""

    def test_pass_when_low_drawdown(self) -> None:
        """测试低回撤时通过"""
        rule = MaxDrawdownRule(max_drawdown_pct=0.20)
        context = RiskContext(
            total_equity=Decimal("9500"),
            peak_equity=Decimal("10000"),
        )

        result = rule.check(context)
        assert result.action == RiskAction.PASS

    def test_warn_when_near_limit(self) -> None:
        """测试接近限制时警告"""
        rule = MaxDrawdownRule(max_drawdown_pct=0.20)
        context = RiskContext(
            total_equity=Decimal("8200"),
            peak_equity=Decimal("10000"),
        )  # 18% 回撤

        result = rule.check(context)
        assert result.action == RiskAction.WARN

    def test_reject_when_exceed_limit(self) -> None:
        """测试超过限制时拒绝"""
        rule = MaxDrawdownRule(max_drawdown_pct=0.20)
        context = RiskContext(
            total_equity=Decimal("7500"),
            peak_equity=Decimal("10000"),
        )  # 25% 回撤

        result = rule.check(context)
        assert result.action == RiskAction.REJECT


class TestMaxPositionRule:
    """MaxPositionRule 测试"""

    def test_pass_when_within_limit(self) -> None:
        """测试在限制内时通过"""
        rule = MaxPositionRule(max_position_pct=0.30)
        context = RiskContext(
            total_equity=Decimal("10000"),
            position_values={"BTC/USDT": Decimal("2000")},  # 20%
        )

        result = rule.check(context)
        assert result.action == RiskAction.PASS

    def test_reject_when_exceed_limit(self) -> None:
        """测试超过限制时拒绝"""
        rule = MaxPositionRule(max_position_pct=0.30)
        context = RiskContext(
            total_equity=Decimal("10000"),
            position_values={"BTC/USDT": Decimal("4000")},  # 40%
        )

        result = rule.check(context)
        assert result.action == RiskAction.REJECT
        assert "BTC/USDT" in result.message


class TestMaxLeverageRule:
    """MaxLeverageRule 测试"""

    def test_pass_when_low_leverage(self) -> None:
        """测试低杠杆时通过"""
        rule = MaxLeverageRule(max_leverage=3.0)
        context = RiskContext(
            total_equity=Decimal("10000"),
            position_values={"BTC/USDT": Decimal("15000")},  # 1.5x
        )

        result = rule.check(context)
        assert result.action == RiskAction.PASS

    def test_reject_when_high_leverage(self) -> None:
        """测试高杠杆时拒绝"""
        rule = MaxLeverageRule(max_leverage=3.0)
        context = RiskContext(
            total_equity=Decimal("10000"),
            position_values={"BTC/USDT": Decimal("35000")},  # 3.5x
        )

        result = rule.check(context)
        assert result.action == RiskAction.REJECT


class TestRiskEngine:
    """RiskEngine 测试"""

    def test_add_and_remove_rule(self) -> None:
        """测试添加和移除规则"""
        engine = RiskEngine()
        rule = MaxDailyLossRule()

        engine.add_rule(rule)
        assert len(engine.get_rules()) == 1

        engine.remove_rule(rule.name)
        assert len(engine.get_rules()) == 0

    def test_clear_rules(self) -> None:
        """测试清空规则"""
        engine = RiskEngine()
        engine.add_rule(MaxDailyLossRule())
        engine.add_rule(MaxDrawdownRule())

        engine.clear_rules()
        assert len(engine.get_rules()) == 0

    def test_check_all_rules(self) -> None:
        """测试检查所有规则"""
        engine = RiskEngine()
        engine.add_rule(MaxDailyLossRule(max_loss_pct=0.05))
        engine.add_rule(MaxDrawdownRule(max_drawdown_pct=0.20))

        context = RiskContext(
            total_equity=Decimal("10000"),
            peak_equity=Decimal("10000"),
            daily_pnl=Decimal("0"),
        )

        results = engine.check(context)
        assert len(results) == 2
        assert all(r.action == RiskAction.PASS for r in results)

    def test_should_proceed_all_pass(self) -> None:
        """测试所有规则通过时继续"""
        engine = RiskEngine()
        engine.add_rule(MaxDailyLossRule(max_loss_pct=0.10))

        context = RiskContext(
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("-100"),  # 1% 亏损
        )

        should_proceed, results = engine.should_proceed(context)
        assert should_proceed is True

    def test_should_proceed_one_reject(self) -> None:
        """测试有规则拒绝时不继续"""
        engine = RiskEngine()
        engine.add_rule(MaxDailyLossRule(max_loss_pct=0.05))

        context = RiskContext(
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("-600"),  # 6% 亏损
        )

        should_proceed, results = engine.should_proceed(context)
        assert should_proceed is False
        assert any(r.rejected for r in results)

    def test_disabled_engine(self) -> None:
        """测试禁用的引擎"""
        engine = RiskEngine()
        engine.add_rule(MaxDailyLossRule(max_loss_pct=0.01))
        engine.disable()

        context = RiskContext(
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("-5000"),  # 50% 亏损
        )

        results = engine.check(context)
        assert len(results) == 1
        assert results[0].action == RiskAction.PASS  # 禁用后通过

    def test_enable_engine(self) -> None:
        """测试启用引擎"""
        engine = RiskEngine()
        engine.disable()
        engine.enable()

        assert engine.enabled is True


class TestCreateDefaultRiskEngine:
    """create_default_risk_engine 测试"""

    def test_creates_engine_with_default_rules(self) -> None:
        """测试创建带默认规则的引擎"""
        engine = create_default_risk_engine()
        rules = engine.get_rules()

        assert len(rules) == 4
        rule_names = [r.name for r in rules]
        assert "max_daily_loss" in rule_names
        assert "max_drawdown" in rule_names
        assert "max_position" in rule_names
        assert "max_leverage" in rule_names

    def test_custom_parameters(self) -> None:
        """测试自定义参数"""
        engine = create_default_risk_engine(
            max_daily_loss_pct=0.10,
            max_drawdown_pct=0.30,
        )

        # 验证参数被应用
        context = RiskContext(
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("-800"),  # 8% 亏损
        )

        should_proceed, _ = engine.should_proceed(context)
        assert should_proceed is True  # 10% 限制内
