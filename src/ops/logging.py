"""
统一日志模块

使用 structlog 实现结构化日志:
- JSON 格式输出 (便于 Loki 采集)
- Console + File 双输出
- 统一日志格式与级别
"""

import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from typing import Any

import structlog
from structlog.types import Processor

from src.core.config import get_settings


def add_timestamp(
    _logger: logging.Logger, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """添加 ISO 格式 UTC 时间戳"""
    event_dict["timestamp"] = datetime.now(UTC).isoformat()
    return event_dict


def add_service_info(
    _logger: logging.Logger, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """添加服务信息"""
    settings = get_settings()
    event_dict["env"] = settings.env.value
    return event_dict


def configure_logging(
    service_name: str = "algorithmtrader",
    log_level: str | None = None,
    log_to_file: bool = True,
) -> structlog.BoundLogger:
    """
    配置日志系统

    Args:
        service_name: 服务名称，用于标识日志来源
        log_level: 日志级别，默认从配置读取
        log_to_file: 是否输出到文件

    Returns:
        配置好的 logger 实例
    """
    settings = get_settings()
    level = log_level or settings.log_level

    # 确保日志目录存在
    if log_to_file:
        settings.log_dir.mkdir(parents=True, exist_ok=True)

    # 共享的处理器
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_timestamp,
        add_service_info,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # 开发环境使用彩色 Console 输出
    if settings.is_dev:
        console_processor = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # 生产环境使用 JSON 格式
        console_processor = structlog.processors.JSONRenderer()

    # 配置 structlog
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 配置标准 logging
    handlers: list[logging.Handler] = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=console_processor,
            foreign_pre_chain=shared_processors,
        )
    )
    handlers.append(console_handler)

    # File handler (JSON 格式)
    if log_to_file:
        log_file = settings.log_dir / f"{service_name}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
                foreign_pre_chain=shared_processors,
            )
        )
        handlers.append(file_handler)

    # 配置 root logger
    root_logger = logging.getLogger()
    root_logger.handlers = handlers
    root_logger.setLevel(getattr(logging, level.upper()))

    # 降低第三方库日志级别
    for logger_name in ["ccxt", "urllib3", "httpx", "asyncio"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # 返回配置好的 logger
    logger = structlog.get_logger(service_name)
    return logger


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """
    获取 logger 实例

    Args:
        name: logger 名称

    Returns:
        structlog.BoundLogger 实例
    """
    return structlog.get_logger(name)


# ======================================================================
# 日志目录管理
# ======================================================================

# 日志目录总大小上限 (默认 200MB)
LOG_DIR_MAX_SIZE_MB = 200


def get_log_dir_size_mb() -> float:
    """获取日志目录总大小 (MB)"""
    settings = get_settings()
    log_dir = settings.log_dir
    if not log_dir.exists():
        return 0.0
    total = sum(f.stat().st_size for f in log_dir.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def cleanup_old_logs(max_size_mb: float = LOG_DIR_MAX_SIZE_MB) -> dict:
    """
    清理旧日志文件，确保总大小不超过上限。

    策略:
    1. 先删除 .log.N 备份文件（从最旧开始）
    2. 如果仍超限，截断最大的活跃日志文件

    Returns:
        清理报告 dict
    """

    settings = get_settings()
    log_dir = settings.log_dir
    if not log_dir.exists():
        return {"status": "ok", "message": "日志目录不存在"}

    current_size = get_log_dir_size_mb()
    if current_size <= max_size_mb:
        return {
            "status": "ok",
            "size_mb": round(current_size, 1),
            "max_mb": max_size_mb,
            "cleaned": 0,
        }

    cleaned_count = 0
    cleaned_bytes = 0

    # 阶段1: 删除轮转备份 (.log.1, .log.2, ... 按修改时间排序)
    backup_files = sorted(
        log_dir.glob("*.log.*"),
        key=lambda f: f.stat().st_mtime,
    )
    for bf in backup_files:
        if get_log_dir_size_mb() <= max_size_mb * 0.8:  # 清到80%停止
            break
        try:
            size = bf.stat().st_size
            bf.unlink()
            cleaned_count += 1
            cleaned_bytes += size
        except Exception:
            pass

    # 阶段2: 如果仍然超限，截断最大的活跃日志
    if get_log_dir_size_mb() > max_size_mb:
        active_logs = sorted(
            log_dir.glob("*.log"),
            key=lambda f: f.stat().st_size,
            reverse=True,
        )
        for lf in active_logs:
            if get_log_dir_size_mb() <= max_size_mb * 0.8:
                break
            try:
                # 保留最后 1000 行
                lines = lf.read_text(encoding="utf-8", errors="ignore").split("\n")
                keep = lines[-1000:] if len(lines) > 1000 else lines
                lf.write_text("\n".join(keep), encoding="utf-8")
                cleaned_count += 1
            except Exception:
                pass

    final_size = get_log_dir_size_mb()
    return {
        "status": "cleaned",
        "size_mb": round(final_size, 1),
        "max_mb": max_size_mb,
        "cleaned": cleaned_count,
        "freed_mb": round((current_size - final_size), 1),
    }
