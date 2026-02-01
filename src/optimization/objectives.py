"""
优化目标函数

定义用于评估策略性能的目标函数
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.backtest.metrics import PerformanceMetrics


class Objective(ABC):
    """优化目标基类"""
    
    name: str = "objective"
    minimize: bool = False  # True=最小化，False=最大化
    
    @abstractmethod
    def evaluate(self, metrics: PerformanceMetrics) -> float:
        """
        评估回测结果
        
        Args:
            metrics: 回测性能指标
            
        Returns:
            目标函数值
        """
        pass
    
    def is_better(self, value1: float, value2: float) -> bool:
        """判断 value1 是否优于 value2"""
        if self.minimize:
            return value1 < value2
        return value1 > value2


class MaximizeSharpe(Objective):
    """最大化夏普比率"""
    
    name = "sharpe_ratio"
    minimize = False
    
    def __init__(self, risk_free_rate: float = 0.0):
        self.risk_free_rate = risk_free_rate
    
    def evaluate(self, metrics: PerformanceMetrics) -> float:
        return metrics.sharpe_ratio


class MaximizeReturn(Objective):
    """最大化总收益率"""
    
    name = "total_return"
    minimize = False
    
    def evaluate(self, metrics: PerformanceMetrics) -> float:
        return metrics.total_return


class MinimizeDrawdown(Objective):
    """最小化最大回撤"""
    
    name = "max_drawdown"
    minimize = True
    
    def evaluate(self, metrics: PerformanceMetrics) -> float:
        return metrics.max_drawdown


class MaximizeCalmar(Objective):
    """最大化 Calmar 比率 (年化收益/最大回撤)"""
    
    name = "calmar_ratio"
    minimize = False
    
    def evaluate(self, metrics: PerformanceMetrics) -> float:
        return metrics.calmar_ratio


class MaximizeProfitFactor(Objective):
    """最大化盈亏比"""
    
    name = "profit_factor"
    minimize = False
    
    def evaluate(self, metrics: PerformanceMetrics) -> float:
        return metrics.trade_stats.profit_factor


class MaximizeWinRate(Objective):
    """最大化胜率"""
    
    name = "win_rate"
    minimize = False
    
    def evaluate(self, metrics: PerformanceMetrics) -> float:
        return metrics.trade_stats.win_rate


@dataclass
class WeightedObjective:
    """带权重的目标"""
    objective: Objective
    weight: float = 1.0


class MultiObjective(Objective):
    """
    多目标优化
    
    将多个目标函数加权组合成单一目标
    """
    
    name = "multi_objective"
    minimize = False
    
    def __init__(self, objectives: list[WeightedObjective]):
        """
        Args:
            objectives: 带权重的目标列表
        """
        self.objectives = objectives
        self._validate()
    
    def _validate(self):
        """验证目标配置"""
        if not self.objectives:
            raise ValueError("至少需要一个目标")
        
        total_weight = sum(o.weight for o in self.objectives)
        if total_weight <= 0:
            raise ValueError("权重和必须大于 0")
    
    def evaluate(self, metrics: PerformanceMetrics) -> float:
        """
        计算加权目标值
        
        对于需要最小化的目标，取负值后再加权
        """
        total = 0.0
        total_weight = sum(o.weight for o in self.objectives)
        
        for wo in self.objectives:
            value = wo.objective.evaluate(metrics)
            
            # 归一化处理
            # 最小化目标取负值，使其变为"越大越好"
            if wo.objective.minimize:
                value = -value
            
            total += value * wo.weight
        
        return total / total_weight
    
    def get_individual_scores(self, metrics: PerformanceMetrics) -> dict[str, float]:
        """获取各目标的单独评分"""
        return {
            wo.objective.name: wo.objective.evaluate(metrics)
            for wo in self.objectives
        }


# 预定义组合目标
def create_balanced_objective() -> MultiObjective:
    """
    创建平衡目标
    
    夏普比率 (50%) + 收益率 (25%) + 回撤 (25%)
    """
    return MultiObjective([
        WeightedObjective(MaximizeSharpe(), weight=0.5),
        WeightedObjective(MaximizeReturn(), weight=0.25),
        WeightedObjective(MinimizeDrawdown(), weight=0.25),
    ])


def create_conservative_objective() -> MultiObjective:
    """
    创建保守目标
    
    优先考虑风险控制
    """
    return MultiObjective([
        WeightedObjective(MinimizeDrawdown(), weight=0.5),
        WeightedObjective(MaximizeSharpe(), weight=0.3),
        WeightedObjective(MaximizeWinRate(), weight=0.2),
    ])


def create_aggressive_objective() -> MultiObjective:
    """
    创建激进目标
    
    优先考虑收益
    """
    return MultiObjective([
        WeightedObjective(MaximizeReturn(), weight=0.5),
        WeightedObjective(MaximizeCalmar(), weight=0.3),
        WeightedObjective(MaximizeSharpe(), weight=0.2),
    ])
