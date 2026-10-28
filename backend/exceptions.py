"""
统一异常定义

@description:
    定义项目中使用的所有自定义异常类

@usage:
    from backend.exceptions import (
        WebAgentException,
        DatabaseError,
        ValidationError,
    )

    raise ValidationError("申请记录ID不能为空")
"""

from typing import Optional, Dict, Any


class WebAgentException(Exception):
    """WebAgent 基础异常类"""

    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，用于 API 响应"""
        return {
            "error": True,
            "code": self.code,
            "message": self.message,
            "details": self.details
        }


class DatabaseError(WebAgentException):
    """数据库操作异常"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "DATABASE_ERROR", details)


class RecordNotFoundError(DatabaseError):
    """记录不存在"""
    def __init__(self, table: str, record_id: Any):
        super().__init__(
            f"记录不存在: {table}#{record_id}",
            {"table": table, "record_id": record_id}
        )
        self.code = "RECORD_NOT_FOUND"


class ValidationError(WebAgentException):
    """参数验证异常"""
    def __init__(self, message: str, field: Optional[str] = None):
        details = {"field": field} if field else {}
        super().__init__(message, "VALIDATION_ERROR", details)


class MissingFieldError(ValidationError):
    """必填字段缺失"""
    def __init__(self, field: str):
        super().__init__(f"缺少必填字段: {field}", field)
        self.code = "MISSING_FIELD"


class AuthenticationError(WebAgentException):
    """认证异常"""
    def __init__(self, message: str = "认证失败"):
        super().__init__(message, "AUTHENTICATION_ERROR")


class LoginFailedError(AuthenticationError):
    """登录失败"""
    def __init__(self, reason: str = "用户名或密码错误"):
        super().__init__(f"登录失败: {reason}")
        self.code = "LOGIN_FAILED"


class ApplicationError(WebAgentException):
    """申请流程异常"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "APPLICATION_ERROR", details)


class InvalidStateError(ApplicationError):
    """无效的状态转换"""
    def __init__(self, current_state: str, target_state: str):
        super().__init__(
            f"无法从状态 '{current_state}' 转换到 '{target_state}'",
            {"current_state": current_state, "target_state": target_state}
        )
        self.code = "INVALID_STATE"


class FormFillError(WebAgentException):
    """表单填充异常"""
    def __init__(self, message: str, page: Optional[int] = None, field: Optional[str] = None):
        details = {}
        if page is not None:
            details["page"] = page
        if field is not None:
            details["field"] = field
        super().__init__(message, "FORM_FILL_ERROR", details)


class FieldNotFoundError(FormFillError):
    """字段未找到"""
    def __init__(self, field: str, page: int):
        super().__init__(f"字段未找到: {field}", page, field)
        self.code = "FIELD_NOT_FOUND"


class NavigationError(FormFillError):
    """页面导航异常"""
    def __init__(self, message: str, page: Optional[int] = None):
        super().__init__(message, page)
        self.code = "NAVIGATION_ERROR"


class ExternalServiceError(WebAgentException):
    """外部服务调用异常"""
    def __init__(self, service: str, message: str):
        super().__init__(
            f"{service} 服务异常: {message}",
            "EXTERNAL_SERVICE_ERROR",
            {"service": service}
        )


class LLMError(ExternalServiceError):
    """LLM 调用异常"""
    def __init__(self, message: str):
        super().__init__("LLM", message)
        self.code = "LLM_ERROR"


class BrowserError(ExternalServiceError):
    """浏览器操作异常"""
    def __init__(self, message: str):
        super().__init__("Browser", message)
        self.code = "BROWSER_ERROR"


def handle_exception(e: Exception) -> Dict[str, Any]:
    """统一异常处理函数"""
    if isinstance(e, WebAgentException):
        return e.to_dict()

    return {
        "error": True,
        "code": "INTERNAL_ERROR",
        "message": "服务器内部错误",
        "details": {"original_error": str(e)}
    }

