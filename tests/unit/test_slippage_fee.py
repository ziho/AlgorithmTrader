"""
滑点与手续费模型单元测试
"""

from decimal import Decimal

from src.execution.slippage_fee import (
    CostCalculator,
    FeeConfig,
    FeeModel,
    FixedSlippage,
    OrderSide,
    PercentSlippage,
    VolumeImpactSlippage,
)


class TestFixedSlippage:
    """固定点数滑点测试"""

    def test_buy_slippage(self):
        """买入时价格向上滑点"""
        model = FixedSlippage(Decimal("10"))
        price = model.calculate_slippage(
            price=Decimal("50000"),
            quantity=Decimal("1"),
            side=OrderSide.BUY,
        )
        assert price == Decimal("50010")

    def test_sell_slippage(self):
        """卖出时价格向下滑点"""
        model = FixedSlippage(Decimal("10"))
        price = model.calculate_slippage(
            price=Decimal("50000"),
            quantity=Decimal("1"),
            side=OrderSide.SELL,
        )
        assert price == Decimal("49990")


class TestPercentSlippage:
    """百分比滑点测试"""

    def test_buy_slippage(self):
        """买入时价格向上滑点"""
        model = PercentSlippage(Decimal("0.001"))  # 0.1%
        price = model.calculate_slippage(
            price=Decimal("50000"),
            quantity=Decimal("1"),
            side=OrderSide.BUY,
        )
        assert price == Decimal("50050")  # 50000 + 50 = 50050

    def test_sell_slippage(self):
        """卖出时价格向下滑点"""
        model = PercentSlippage(Decimal("0.001"))  # 0.1%
        price = model.calculate_slippage(
            price=Decimal("50000"),
            quantity=Decimal("1"),
            side=OrderSide.SELL,
        )
        assert price == Decimal("49950")  # 50000 - 50 = 49950


class TestVolumeImpactSlippage:
    """成交量冲击滑点测试"""

    def test_no_volume_info(self):
        """没有成交量信息时使用基础滑点"""
        model = VolumeImpactSlippage(
            base_slippage_pct=Decimal("0.0001"),
            impact_factor=Decimal("0.1"),
        )
        price = model.calculate_slippage(
            price=Decimal("50000"),
            quantity=Decimal("1"),
            side=OrderSide.BUY,
        )
        # 只有基础滑点 0.01%
        assert price == Decimal("50005")  # 50000 * 0.0001 = 5

    def test_with_volume_impact(self):
        """有成交量信息时添加冲击"""
        model = VolumeImpactSlippage(
            base_slippage_pct=Decimal("0.0001"),  # 0.01%
            impact_factor=Decimal("0.1"),
        )
        # 订单占 bar 成交量的 10%
        price = model.calculate_slippage(
            price=Decimal("50000"),
            quantity=Decimal("10"),
            side=OrderSide.BUY,
            bar_volume=Decimal("100"),
        )
        # 滑点 = 0.0001 + 0.1 * 0.1 = 0.0101 = 1.01%
        expected = Decimal("50000") * (1 + Decimal("0.0101"))
        assert price == expected


class TestFeeModel:
    """手续费模型测试"""

    def test_taker_fee(self):
        """Taker 手续费"""
        config = FeeConfig(
            maker_rate=Decimal("0.0005"),
            taker_rate=Decimal("0.001"),
        )
        model = FeeModel(config)
        fee = model.calculate_fee(
            quantity=Decimal("1"),
            price=Decimal("50000"),
            is_maker=False,
        )
        assert fee == Decimal("50")  # 50000 * 0.001 = 50

    def test_maker_fee(self):
        """Maker 手续费"""
        config = FeeConfig(
            maker_rate=Decimal("0.0005"),
            taker_rate=Decimal("0.001"),
        )
        model = FeeModel(config)
        fee = model.calculate_fee(
            quantity=Decimal("1"),
            price=Decimal("50000"),
            is_maker=True,
        )
        assert fee == Decimal("25")  # 50000 * 0.0005 = 25

    def test_min_fee(self):
        """最低手续费"""
        config = FeeConfig(
            maker_rate=Decimal("0.0001"),
            taker_rate=Decimal("0.0001"),
            min_fee=Decimal("1"),
        )
        model = FeeModel(config)
        fee = model.calculate_fee(
            quantity=Decimal("0.001"),
            price=Decimal("100"),
            is_maker=False,
        )
        # 0.001 * 100 * 0.0001 = 0.00001，应返回最低 1
        assert fee == Decimal("1")

    def test_from_exchange(self):
        """从交易所创建费率模型"""
        model = FeeModel.from_exchange("okx")
        assert model.config.maker_rate == Decimal("0.0008")
        assert model.config.taker_rate == Decimal("0.001")


class TestCostCalculator:
    """交易成本计算器测试"""

    def test_calculate_buy(self):
        """计算买入成本"""
        calc = CostCalculator(
            slippage_model=PercentSlippage(Decimal("0.001")),
            fee_model=FeeModel(FeeConfig(taker_rate=Decimal("0.001"))),
        )
        cost = calc.calculate(
            price=Decimal("50000"),
            quantity=Decimal("1"),
            side=OrderSide.BUY,
        )
        assert cost.original_price == Decimal("50000")
        assert cost.filled_price == Decimal("50050")  # 滑点后
        assert cost.quantity == Decimal("1")
        assert cost.commission == Decimal("50.05")  # 50050 * 0.001
        assert cost.trade_value == Decimal("50050")

    def test_calculate_sell(self):
        """计算卖出成本"""
        calc = CostCalculator(
            slippage_model=PercentSlippage(Decimal("0.001")),
            fee_model=FeeModel(FeeConfig(taker_rate=Decimal("0.001"))),
        )
        cost = calc.calculate(
            price=Decimal("50000"),
            quantity=Decimal("1"),
            side=OrderSide.SELL,
        )
        assert cost.filled_price == Decimal("49950")  # 滑点后
        assert cost.slippage_cost == Decimal("50")  # (50000 - 49950) * 1

    def test_for_exchange(self):
        """为特定交易所创建计算器"""
        calc = CostCalculator.for_exchange("okx", slippage_pct=Decimal("0.0005"))
        cost = calc.calculate(
            price=Decimal("50000"),
            quantity=Decimal("1"),
            side=OrderSide.BUY,
        )
        # OKX taker 费率 0.1%
        assert cost.commission > 0
