#!/usr/bin/env python3
"""
统一异常处理和错误分类模块

错误分类:
1. ExecutionError - 执行失败，可立即重试
2. AgentError - Agent操作失误，需要提供错误信息后重试
3. SystemError - 系统/网络问题，需要刷新/重连/等待后重试
4. UserDataError - 用户数据缺失，需要返回给前端让用户补充
"""

import logging
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class ErrorCategory(Enum):
    """错误类别"""
    EXECUTION = "execution"     # 执行失败 - 立即重试
    AGENT = "agent"            # Agent操作失误 - 带错误信息重试
    SYSTEM = "system"          # 系统/网络问题 - 刷新/重连/等待后重试
    USER_DATA = "user_data"    # 用户数据缺失 - 返回前端让用户补充
    UNKNOWN = "unknown"        # 未知错误


class RetryStrategy(Enum):
    """重试策略"""
    IMMEDIATE = "immediate"           # 立即重试
    WITH_ERROR_INFO = "with_info"     # 带错误信息重试
    REFRESH_AND_RETRY = "refresh"     # 刷新页面后重试
    RECONNECT = "reconnect"           # 重新连接后重试
    WAIT_AND_RETRY = "wait"           # 等待一段时间后重试
    NO_RETRY = "no_retry"             # 不重试，返回用户


@dataclass
class FormAutomationError:
    """表单自动化错误"""
    category: ErrorCategory
    message: str
    details: Optional[str] = None
    field_id: Optional[str] = None
    retry_strategy: RetryStrategy = RetryStrategy.NO_RETRY
    max_retries: int = 3
    retry_delay_seconds: int = 1
    user_action_required: bool = False
    missing_fields: Optional[List[Dict[str, Any]]] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（供API返回）"""
        return {
            "category": self.category.value,
            "message": self.message,
            "details": self.details,
            "field_id": self.field_id,
            "retry_strategy": self.retry_strategy.value,
            "user_action_required": self.user_action_required,
            "missing_fields": self.missing_fields,
            "timestamp": self.timestamp.isoformat()
        }


class ErrorClassifier:
    """错误分类器"""
    
    # 执行失败的关键词
    EXECUTION_PATTERNS = [
        "timeout", "click failed", "element not found",
        "selector not found", "navigation failed"
    ]
    
    # Agent 操作失误的关键词
    AGENT_PATTERNS = [
        "wrong element", "invalid input", "format error",
        "validation failed", "incorrect value"
    ]
    
    # 系统/网络问题的关键词
    SYSTEM_PATTERNS = [
        "connection", "network", "refused", "unreachable",
        "502", "503", "504", "server error", "database",
        "session expired", "login required"
    ]
    
    # 用户数据缺失的关键词
    USER_DATA_PATTERNS = [
        "missing field", "required field", "empty value",
        "user data missing", "incomplete data"
    ]
    
    @classmethod
    def classify(cls, error: Exception, context: Optional[Dict] = None) -> FormAutomationError:
        """分类错误并返回结构化的错误对象"""
        error_message = str(error).lower()
        
        # 检查用户数据缺失
        if any(p in error_message for p in cls.USER_DATA_PATTERNS):
            return FormAutomationError(
                category=ErrorCategory.USER_DATA,
                message="用户数据缺失",
                details=str(error),
                retry_strategy=RetryStrategy.NO_RETRY,
                user_action_required=True,
                missing_fields=context.get("missing_fields") if context else None
            )
        
        # 检查系统/网络问题
        if any(p in error_message for p in cls.SYSTEM_PATTERNS):
            return FormAutomationError(
                category=ErrorCategory.SYSTEM,
                message="系统或网络问题",
                details=str(error),
                retry_strategy=RetryStrategy.WAIT_AND_RETRY,
                max_retries=3,
                retry_delay_seconds=30
            )
        
        # 检查 Agent 操作失误
        if any(p in error_message for p in cls.AGENT_PATTERNS):
            return FormAutomationError(
                category=ErrorCategory.AGENT,
                message="Agent 操作失误",
                details=str(error),
                retry_strategy=RetryStrategy.WITH_ERROR_INFO,
                max_retries=2,
                retry_delay_seconds=1
            )
        
        # 检查执行失败
        if any(p in error_message for p in cls.EXECUTION_PATTERNS):
            return FormAutomationError(
                category=ErrorCategory.EXECUTION,
                message="执行失败",
                details=str(error),
                retry_strategy=RetryStrategy.IMMEDIATE,
                max_retries=3,
                retry_delay_seconds=1
            )
        
        # 未知错误
        return FormAutomationError(
            category=ErrorCategory.UNKNOWN,
            message="未知错误",
            details=str(error),
            retry_strategy=RetryStrategy.REFRESH_AND_RETRY,
            max_retries=1
        )


class FormAutomationLogger:
    """表单自动化日志记录器"""
    
    def __init__(self, name: str = "FormAutomation"):
        self.logger = logging.getLogger(name)
        self.operations = []
        self.errors = []
    
    def info(self, message: str, **kwargs):
        """记录信息"""
        self.logger.info(message)
        self._record_operation("info", message, kwargs)
    
    def debug(self, message: str, **kwargs):
        """记录调试信息"""
        self.logger.debug(message)
        self._record_operation("debug", message, kwargs)
    
    def warning(self, message: str, **kwargs):
        """记录警告"""
        self.logger.warning(message)
        self._record_operation("warning", message, kwargs)
    
    def error(self, message: str, error: Optional[Exception] = None, **kwargs):
        """记录错误"""
        self.logger.error(message, exc_info=error is not None)
        error_record = {
            "message": message,
            "error": str(error) if error else None,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.errors.append(error_record)
        self._record_operation("error", message, kwargs)
    
    def field_fill(self, field_id: str, value: Any, success: bool, source: str = "payload"):
        """记录字段填写"""
        self.logger.info(f"填写字段 {field_id}: {'✓' if success else '✗'} (来源: {source})")
        self._record_operation("field_fill", f"{field_id}={value}", {
            "field_id": field_id,
            "value": str(value)[:50],
            "success": success,
            "source": source
        })
    
    def page_navigation(self, from_page: int, to_page: int, success: bool):
        """记录页面导航"""
        status = "成功" if success else "失败"
        self.logger.info(f"页面导航: {from_page} → {to_page} ({status})")
        self._record_operation("navigation", f"{from_page}->{to_page}", {
            "from_page": from_page,
            "to_page": to_page,
            "success": success
        })
    
    def missing_field_report(self, fields: List[Dict]):
        """记录缺失字段"""
        self.logger.warning(f"发现 {len(fields)} 个缺失字段:")
        for f in fields:
            self.logger.warning(f"  - {f.get('field_id')}: {f.get('field_label')} ({f.get('reason')})")
        self._record_operation("missing_fields", f"{len(fields)} fields missing", {
            "fields": fields
        })
    
    def _record_operation(self, op_type: str, message: str, data: Dict):
        """记录操作"""
        self.operations.append({
            "type": op_type,
            "message": message,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_summary(self) -> Dict[str, Any]:
        """获取日志摘要"""
        return {
            "total_operations": len(self.operations),
            "total_errors": len(self.errors),
            "operations_by_type": self._count_by_type(),
            "recent_errors": self.errors[-5:] if self.errors else []
        }
    
    def _count_by_type(self) -> Dict[str, int]:
        """按类型统计操作"""
        counts = {}
        for op in self.operations:
            op_type = op["type"]
            counts[op_type] = counts.get(op_type, 0) + 1
        return counts
    
    def export_log(self, filepath: str):
        """导出日志到文件"""
        import json
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                "operations": self.operations,
                "errors": self.errors,
                "summary": self.get_summary()
            }, f, ensure_ascii=False, indent=2)


# 创建默认日志记录器
default_logger = FormAutomationLogger()


def create_user_data_error(missing_fields: List[Dict]) -> FormAutomationError:
    """创建用户数据缺失错误"""
    return FormAutomationError(
        category=ErrorCategory.USER_DATA,
        message="用户数据缺失，需要补充以下字段",
        missing_fields=missing_fields,
        retry_strategy=RetryStrategy.NO_RETRY,
        user_action_required=True
    )


def create_execution_error(message: str, details: str = None) -> FormAutomationError:
    """创建执行错误"""
    return FormAutomationError(
        category=ErrorCategory.EXECUTION,
        message=message,
        details=details,
        retry_strategy=RetryStrategy.IMMEDIATE,
        max_retries=3
    )


def create_agent_error(message: str, details: str = None) -> FormAutomationError:
    """创建 Agent 错误"""
    return FormAutomationError(
        category=ErrorCategory.AGENT,
        message=message,
        details=details,
        retry_strategy=RetryStrategy.WITH_ERROR_INFO,
        max_retries=2
    )


def create_system_error(message: str, details: str = None) -> FormAutomationError:
    """创建系统错误"""
    return FormAutomationError(
        category=ErrorCategory.SYSTEM,
        message=message,
        details=details,
        retry_strategy=RetryStrategy.WAIT_AND_RETRY,
        retry_delay_seconds=30
    )

