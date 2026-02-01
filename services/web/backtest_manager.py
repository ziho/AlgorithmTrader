"""
回测结果管理

提供回测结果的存储和查询
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class BacktestRecord:
    """回测记录"""

    id: str
    strategy_class: str
    strategy_params: dict = field(default_factory=dict)

    # 数据设置
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"
    start_date: str = ""
    end_date: str = ""

    # 回测设置
    initial_capital: float = 100000.0

    # 状态
    status: str = "pending"  # pending, running, completed, failed
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    # 结果
    metrics: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategy_class": self.strategy_class,
            "strategy_params": self.strategy_params,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": self.initial_capital,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metrics": self.metrics,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BacktestRecord":
        return cls(
            id=data.get("id", ""),
            strategy_class=data.get("strategy_class", ""),
            strategy_params=data.get("strategy_params", {}),
            symbol=data.get("symbol", "BTC/USDT"),
            timeframe=data.get("timeframe", "15m"),
            start_date=data.get("start_date", ""),
            end_date=data.get("end_date", ""),
            initial_capital=data.get("initial_capital", 100000.0),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            metrics=data.get("metrics", {}),
            error=data.get("error"),
        )


class BacktestResultManager:
    """
    回测结果管理器

    存储和查询回测记录
    """

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or Path("config/backtests.json")
        self._records: list[BacktestRecord] = []
        self.load()

    def load(self):
        """加载回测记录"""
        if not self.config_path.exists():
            self._records = []
            return

        try:
            data = json.loads(self.config_path.read_text())
            self._records = [
                BacktestRecord.from_dict(r) for r in data.get("backtests", [])
            ]
        except Exception:
            self._records = []

    def save(self):
        """保存回测记录"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "backtests": [r.to_dict() for r in self._records],
            "updated_at": datetime.now().isoformat(),
        }

        self.config_path.write_text(json.dumps(data, indent=2, default=str))

    def get_all(self) -> list[BacktestRecord]:
        """获取所有回测记录"""
        return self._records.copy()

    def get(self, record_id: str) -> BacktestRecord | None:
        """获取指定回测记录"""
        for record in self._records:
            if record.id == record_id:
                return record
        return None

    def add(self, record: BacktestRecord):
        """添加回测记录"""
        self._records.append(record)
        self.save()

    def update(self, record_id: str, **kwargs) -> bool:
        """更新回测记录"""
        for record in self._records:
            if record.id == record_id:
                for key, value in kwargs.items():
                    if hasattr(record, key):
                        setattr(record, key, value)
                self.save()
                return True
        return False

    def delete(self, record_id: str) -> bool:
        """删除回测记录"""
        for i, record in enumerate(self._records):
            if record.id == record_id:
                del self._records[i]
                self.save()
                return True
        return False

    def filter(
        self,
        strategy: str | None = None,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[BacktestRecord]:
        """筛选回测记录"""
        results = self._records

        if strategy:
            results = [r for r in results if r.strategy_class == strategy]
        if status:
            results = [r for r in results if r.status == status]
        if symbol:
            results = [r for r in results if r.symbol == symbol]

        return results

    def get_recent(self, n: int = 10) -> list[BacktestRecord]:
        """获取最近的 n 条回测记录"""
        sorted_records = sorted(
            self._records,
            key=lambda r: r.created_at,
            reverse=True,
        )
        return sorted_records[:n]
