"""
服务心跳模块

每个服务定期写入心跳文件到共享日志目录，
Web 服务读取这些文件来判断各服务的运行状态。

心跳文件存储在 logs/.heartbeat/<service>.json
"""

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 心跳文件默认超时(秒)，超过此时间认为服务不健康
HEARTBEAT_STALE_SECONDS = 180  # 3 分钟


@dataclass
class Heartbeat:
    """心跳数据"""

    service: str
    status: str = "running"  # running, starting, stopping, error
    pid: int = 0
    timestamp: str = ""
    uptime_seconds: float = 0
    details: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"


def _heartbeat_dir() -> Path:
    """获取心跳目录（兼容容器内和宿主机路径）"""
    # 容器内: /app/logs/.heartbeat
    # 宿主机: ./logs/.heartbeat
    log_dir = os.environ.get("LOG_DIR", "./logs")
    hb_dir = Path(log_dir) / ".heartbeat"
    hb_dir.mkdir(parents=True, exist_ok=True)
    return hb_dir


def write_heartbeat(
    service: str,
    status: str = "running",
    details: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> None:
    """
    写入心跳文件

    Args:
        service: 服务名称 (collector, trader, scheduler, notifier)
        status: 服务状态
        details: 额外信息
        started_at: 服务启动时间
    """
    try:
        now = datetime.now(UTC)
        uptime = (now - started_at).total_seconds() if started_at else 0

        hb = Heartbeat(
            service=service,
            status=status,
            pid=os.getpid(),
            timestamp=now.isoformat(),
            uptime_seconds=uptime,
            details=details or {},
        )

        hb_file = _heartbeat_dir() / f"{service}.json"

        # 原子写入: 先写临时文件再重命名
        tmp_file = hb_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(asdict(hb), ensure_ascii=False, indent=2))
        tmp_file.rename(hb_file)

    except Exception:
        pass  # 心跳写入失败不应影响服务运行


def read_heartbeat(service: str) -> Heartbeat | None:
    """
    读取心跳文件

    Args:
        service: 服务名称

    Returns:
        Heartbeat 或 None
    """
    try:
        hb_file = _heartbeat_dir() / f"{service}.json"
        if not hb_file.exists():
            return None

        data = json.loads(hb_file.read_text())
        return Heartbeat(**data)

    except Exception:
        return None


def read_all_heartbeats() -> dict[str, Heartbeat]:
    """读取所有心跳文件"""
    heartbeats: dict[str, Heartbeat] = {}
    try:
        hb_dir = _heartbeat_dir()
        for hb_file in hb_dir.glob("*.json"):
            try:
                data = json.loads(hb_file.read_text())
                hb = Heartbeat(**data)
                heartbeats[hb.service] = hb
            except Exception:
                continue
    except Exception:
        pass
    return heartbeats


def is_heartbeat_stale(
    hb: Heartbeat, max_age_seconds: float = HEARTBEAT_STALE_SECONDS
) -> bool:
    """检查心跳是否过期"""
    try:
        ts = datetime.fromisoformat(hb.timestamp)
        age = (datetime.now(UTC) - ts).total_seconds()
        return age > max_age_seconds
    except Exception:
        return True


def remove_heartbeat(service: str) -> None:
    """移除心跳文件（服务停止时调用）"""
    try:
        hb_file = _heartbeat_dir() / f"{service}.json"
        if hb_file.exists():
            hb_file.unlink()
    except Exception:
        pass


class HeartbeatWriter:
    """
    后台心跳写入器

    在后台线程中定期写入心跳，不阻塞主服务。

    用法:
        writer = HeartbeatWriter("trader")
        writer.start()
        ...
        writer.stop()
    """

    def __init__(
        self,
        service: str,
        interval: float = 30.0,
        details_func: Any = None,
    ):
        """
        Args:
            service: 服务名称
            interval: 心跳间隔（秒）
            details_func: 可选的回调函数，返回 dict 作为心跳 details
        """
        self.service = service
        self.interval = interval
        self.details_func = details_func
        self._started_at = datetime.now(UTC)
        self._status = "starting"
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """启动心跳写入"""
        self._status = "running"
        self._started_at = datetime.now(UTC)

        # 立即写入一次
        self._write()

        # 启动后台线程
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=f"heartbeat-{self.service}",
        )
        self._thread.start()

    def stop(self) -> None:
        """停止心跳写入并移除心跳文件"""
        self._status = "stopping"
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        # 写入最终状态后移除
        write_heartbeat(
            service=self.service,
            status="stopped",
            started_at=self._started_at,
        )
        remove_heartbeat(self.service)

    def update_status(self, status: str) -> None:
        """更新状态"""
        self._status = status
        self._write()

    def _loop(self) -> None:
        """后台写入循环"""
        while not self._stop_event.is_set():
            self._stop_event.wait(self.interval)
            if not self._stop_event.is_set():
                self._write()

    def _write(self) -> None:
        """执行一次心跳写入"""
        details = {}
        if self.details_func:
            try:
                details = self.details_func()
            except Exception:
                pass

        write_heartbeat(
            service=self.service,
            status=self._status,
            details=details,
            started_at=self._started_at,
        )
