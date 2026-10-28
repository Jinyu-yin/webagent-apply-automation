"""
统一日志配置

@description:
    提供结构化日志记录功能

@usage:
    from backend.logger import get_logger

    logger = get_logger(__name__)
    logger.info("操作成功")
"""

import logging
import sys
import os
from typing import Optional


# 日志格式
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_loggers = {}
_initialized = False


def setup_logging(level: str = "INFO") -> None:
    """初始化日志系统"""
    global _initialized
    if _initialized:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, DATE_FORMAT))
    root_logger.addHandler(console_handler)

    # 降低第三方库的日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器"""
    if not _initialized:
        setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)

    return _loggers[name]


class ServiceLogger:
    """服务层专用日志记录器"""

    def __init__(self, service_name: str):
        self.logger = get_logger(f"backend.services.{service_name}")
        self.service_name = service_name

    def info(self, message: str, **kwargs):
        self.logger.info(f"[{self.service_name}] {message}", extra=kwargs)

    def debug(self, message: str, **kwargs):
        self.logger.debug(f"[{self.service_name}] {message}", extra=kwargs)

    def warning(self, message: str, **kwargs):
        self.logger.warning(f"[{self.service_name}] {message}", extra=kwargs)

    def error(self, message: str, exc_info: bool = False, **kwargs):
        self.logger.error(f"[{self.service_name}] {message}", exc_info=exc_info, extra=kwargs)


def get_service_logger(service_name: str) -> ServiceLogger:
    """获取服务层日志记录器"""
    return ServiceLogger(service_name)

