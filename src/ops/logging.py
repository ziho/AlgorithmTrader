"""
统一日志模块

使用 structlog 实现结构化日志:
- JSON 格式输出 (便于 Loki 采集)
- Console + File 双输出
- 统一日志格式与级别
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from structlog.types import Processor

from src.core.config import get_settings


def add_timestamp(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """添加 ISO 格式 UTC 时间戳"""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_service_info(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
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


# 导入 logging.handlers 用于 RotatingFileHandler
import logging.handlers
