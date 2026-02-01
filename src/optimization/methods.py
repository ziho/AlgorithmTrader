"""
参数搜索方法

实现不同的参数空间搜索策略
"""

import itertools
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class ParameterSpec:
    """参数规格"""
    name: str
    type: str  # int, float, bool, choice
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    choices: list[Any] | None = None
    default: Any = None
    
    def generate_values(self, n_samples: int | None = None) -> list[Any]:
        """
        生成参数值列表
        
        Args:
            n_samples: 采样数量（用于随机搜索）
        """
        if self.type == "bool":
            return [True, False]
        
        if self.type == "choice":
            if self.choices is None:
                raise ValueError(f"choice 类型参数 {self.name} 需要指定 choices")
            return list(self.choices)
        
        if self.min_value is None or self.max_value is None:
            raise ValueError(f"参数 {self.name} 需要指定 min_value 和 max_value")
        
        if self.type == "int":
            step = int(self.step) if self.step else 1
            return list(range(int(self.min_value), int(self.max_value) + 1, step))
        
        if self.type == "float":
            if self.step:
                values = []
                v = self.min_value
                while v <= self.max_value:
                    values.append(round(v, 6))
                    v += self.step
                return values
            elif n_samples:
                # 均匀采样
                return [
                    round(self.min_value + i * (self.max_value - self.min_value) / (n_samples - 1), 6)
                    for i in range(n_samples)
                ]
            else:
                # 默认 10 个采样点
                return self.generate_values(n_samples=10)
        
        raise ValueError(f"未知参数类型: {self.type}")
    
    def random_value(self) -> Any:
        """生成随机值"""
        if self.type == "bool":
            return random.choice([True, False])
        
        if self.type == "choice":
            return random.choice(self.choices)
        
        if self.type == "int":
            return random.randint(int(self.min_value), int(self.max_value))
        
        if self.type == "float":
            return round(random.uniform(self.min_value, self.max_value), 6)
        
        raise ValueError(f"未知参数类型: {self.type}")


@dataclass
class ParameterSpace:
    """参数空间"""
    params: dict[str, ParameterSpec] = field(default_factory=dict)
    
    def add(self, spec: ParameterSpec):
        """添加参数"""
        self.params[spec.name] = spec
    
    def add_int(
        self,
        name: str,
        min_value: int,
        max_value: int,
        step: int = 1,
        default: int | None = None,
    ):
        """添加整数参数"""
        self.params[name] = ParameterSpec(
            name=name,
            type="int",
            min_value=min_value,
            max_value=max_value,
            step=step,
            default=default or min_value,
        )
    
    def add_float(
        self,
        name: str,
        min_value: float,
        max_value: float,
        step: float | None = None,
        default: float | None = None,
    ):
        """添加浮点参数"""
        self.params[name] = ParameterSpec(
            name=name,
            type="float",
            min_value=min_value,
            max_value=max_value,
            step=step,
            default=default or min_value,
        )
    
    def add_bool(self, name: str, default: bool = False):
        """添加布尔参数"""
        self.params[name] = ParameterSpec(
            name=name,
            type="bool",
            default=default,
        )
    
    def add_choice(self, name: str, choices: list[Any], default: Any = None):
        """添加选择参数"""
        self.params[name] = ParameterSpec(
            name=name,
            type="choice",
            choices=choices,
            default=default or choices[0],
        )
    
    def get_default_params(self) -> dict[str, Any]:
        """获取默认参数"""
        return {name: spec.default for name, spec in self.params.items()}
    
    @classmethod
    def from_dict(cls, param_spaces: dict[str, dict]) -> "ParameterSpace":
        """从字典创建参数空间"""
        space = cls()
        for name, spec in param_spaces.items():
            space.add(ParameterSpec(
                name=name,
                type=spec.get("type", "float"),
                min_value=spec.get("min"),
                max_value=spec.get("max"),
                step=spec.get("step"),
                choices=spec.get("choices"),
                default=spec.get("default"),
            ))
        return space


class SearchMethod(ABC):
    """搜索方法基类"""
    
    name: str = "search"
    
    @abstractmethod
    def generate(self, space: ParameterSpace) -> Iterator[dict[str, Any]]:
        """
        生成参数组合
        
        Args:
            space: 参数空间
            
        Yields:
            参数字典
        """
        pass
    
    @abstractmethod
    def estimate_total(self, space: ParameterSpace) -> int:
        """估算总组合数"""
        pass


class GridSearch(SearchMethod):
    """
    网格搜索
    
    穷举所有参数组合
    """
    
    name = "grid"
    
    def __init__(self, n_samples_per_float: int = 10):
        """
        Args:
            n_samples_per_float: 每个浮点参数的采样数
        """
        self.n_samples_per_float = n_samples_per_float
    
    def generate(self, space: ParameterSpace) -> Iterator[dict[str, Any]]:
        param_values = {}
        for name, spec in space.params.items():
            if spec.type == "float" and spec.step is None:
                param_values[name] = spec.generate_values(n_samples=self.n_samples_per_float)
            else:
                param_values[name] = spec.generate_values()
        
        # 生成笛卡尔积
        keys = list(param_values.keys())
        for values in itertools.product(*[param_values[k] for k in keys]):
            yield dict(zip(keys, values))
    
    def estimate_total(self, space: ParameterSpace) -> int:
        total = 1
        for name, spec in space.params.items():
            if spec.type == "float" and spec.step is None:
                total *= self.n_samples_per_float
            else:
                total *= len(spec.generate_values())
        return total


class RandomSearch(SearchMethod):
    """
    随机搜索
    
    从参数空间随机采样
    """
    
    name = "random"
    
    def __init__(self, n_iter: int = 100, seed: int | None = None):
        """
        Args:
            n_iter: 采样次数
            seed: 随机种子
        """
        self.n_iter = n_iter
        self.seed = seed
    
    def generate(self, space: ParameterSpace) -> Iterator[dict[str, Any]]:
        if self.seed is not None:
            random.seed(self.seed)
        
        seen = set()
        attempts = 0
        max_attempts = self.n_iter * 10
        
        while len(seen) < self.n_iter and attempts < max_attempts:
            params = {name: spec.random_value() for name, spec in space.params.items()}
            params_key = tuple(sorted(params.items()))
            
            if params_key not in seen:
                seen.add(params_key)
                yield params
            
            attempts += 1
    
    def estimate_total(self, space: ParameterSpace) -> int:
        return self.n_iter


class LatinHypercubeSearch(SearchMethod):
    """
    拉丁超立方采样
    
    在参数空间中更均匀地采样
    """
    
    name = "lhs"
    
    def __init__(self, n_samples: int = 100, seed: int | None = None):
        self.n_samples = n_samples
        self.seed = seed
    
    def generate(self, space: ParameterSpace) -> Iterator[dict[str, Any]]:
        if self.seed is not None:
            random.seed(self.seed)
        
        # 为每个参数创建分层采样
        param_samples = {}
        for name, spec in space.params.items():
            if spec.type in ("int", "float"):
                # 将范围分成 n_samples 个区间
                intervals = []
                for i in range(self.n_samples):
                    low = spec.min_value + i * (spec.max_value - spec.min_value) / self.n_samples
                    high = spec.min_value + (i + 1) * (spec.max_value - spec.min_value) / self.n_samples
                    # 在区间内随机采样
                    value = random.uniform(low, high)
                    if spec.type == "int":
                        value = int(round(value))
                    else:
                        value = round(value, 6)
                    intervals.append(value)
                random.shuffle(intervals)
                param_samples[name] = intervals
            else:
                # 对于离散参数，随机采样
                values = spec.generate_values()
                param_samples[name] = [random.choice(values) for _ in range(self.n_samples)]
        
        # 组合参数
        for i in range(self.n_samples):
            yield {name: samples[i] for name, samples in param_samples.items()}
    
    def estimate_total(self, space: ParameterSpace) -> int:
        return self.n_samples
