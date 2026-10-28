"""
Backend 模块

@description:
    提供后端核心功能，包括：
    - 配置管理 (config)
    - 日志系统 (logger)
    - 异常处理 (exceptions)
    - 数据库访问 (db, dao)
    - 业务服务 (services)
    - 数据模型 (models)
"""

# 配置
from backend.config import settings, get_settings

# 日志
from backend.logger import get_logger, get_service_logger, setup_logging

# 异常
from backend.exceptions import (
    WebAgentException,
    DatabaseError,
    RecordNotFoundError,
    ValidationError,
    MissingFieldError,
    AuthenticationError,
    LoginFailedError,
    ApplicationError,
    InvalidStateError,
    FormFillError,
    FieldNotFoundError,
    NavigationError,
    ExternalServiceError,
    LLMError,
    BrowserError,
    handle_exception,
)

__all__ = [
    # 配置
    "settings",
    "get_settings",
    # 日志
    "get_logger",
    "get_service_logger",
    "setup_logging",
    # 异常
    "WebAgentException",
    "DatabaseError",
    "RecordNotFoundError",
    "ValidationError",
    "MissingFieldError",
    "AuthenticationError",
    "LoginFailedError",
    "ApplicationError",
    "InvalidStateError",
    "FormFillError",
    "FieldNotFoundError",
    "NavigationError",
    "ExternalServiceError",
    "LLMError",
    "BrowserError",
    "handle_exception",
]
