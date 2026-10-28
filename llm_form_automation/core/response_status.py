"""
申请流程标准化返回状态

所有 API 返回都使用这些函数生成统一格式
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum


class ResponseStatus(Enum):
    """响应状态枚举"""
    # 阶段一：预分析
    ANALYZING = "analyzing"
    NEED_INPUT = "need_input"
    READY_TO_FILL = "ready_to_fill"
    
    # 阶段二：填写
    FILLING = "filling"
    FILL_COMPLETED = "fill_completed"
    
    # 阶段三：迭代
    NEED_ITERATION = "need_iteration"
    ITERATING = "iterating"
    
    # 阶段四：审核
    PENDING_REVIEW = "pending_review"
    USER_MODIFIED = "user_modified"
    
    # 终态
    COMPLETED = "completed"
    FAILED = "failed"
    ERROR = "error"


def _base_response(
    status: str,
    apply_record_id: int,
    message: str,
    **kwargs
) -> Dict[str, Any]:
    """基础响应结构"""
    return {
        "status": status,
        "apply_record_id": apply_record_id,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
        **kwargs
    }


# ==================== 阶段一：预分析 ====================

def analyzing(apply_record_id: int) -> Dict:
    """预分析中"""
    return _base_response(
        status="analyzing",
        apply_record_id=apply_record_id,
        message="正在分析申请表单字段...",
        wait_for="system"
    )


def need_input(
    apply_record_id: int,
    missing_fields: List[Dict],
    stage: str = "pre_analysis"
) -> Dict:
    """
    需要用户补充字段
    
    Args:
        apply_record_id: 申请记录 ID
        missing_fields: 缺失字段列表，每个包含:
            - field_id: 字段 ID
            - field_label: 字段标签
            - field_type: 字段类型
            - options: 选项列表（如有）
        stage: 所处阶段 (pre_analysis / iteration)
    """
    return _base_response(
        status="need_input",
        apply_record_id=apply_record_id,
        message=f"请补充 {len(missing_fields)} 个必填字段",
        wait_for="user",
        stage=stage,
        missing_fields=missing_fields,
        missing_count=len(missing_fields)
    )


def ready_to_fill(
    apply_record_id: int,
    total_fields: int,
    mapped_fields: int
) -> Dict:
    """准备就绪，可以开始填写"""
    return _base_response(
        status="ready_to_fill",
        apply_record_id=apply_record_id,
        message="所有字段已映射，准备开始填写",
        wait_for=None,
        total_fields=total_fields,
        mapped_fields=mapped_fields,
        coverage=f"{(mapped_fields/total_fields*100):.1f}%" if total_fields > 0 else "0%"
    )


# ==================== 阶段二：填写 ====================

def filling(
    apply_record_id: int,
    current_page: int = 0,
    total_pages: Optional[int] = None,
    fields_filled: int = 0,
    fields_total: Optional[int] = None
) -> Dict:
    """填写中"""
    return _base_response(
        status="filling",
        apply_record_id=apply_record_id,
        message=f"正在填写申请表单 (第 {current_page} 页)",
        wait_for="system",
        progress={
            "current_page": current_page,
            "total_pages": total_pages,
            "fields_filled": fields_filled,
            "fields_total": fields_total
        }
    )


def fill_completed(
    apply_record_id: int,
    filled_fields: List[Dict],
    failed_fields: List[Dict],
    no_value_fields: List[Dict]
) -> Dict:
    """填写阶段完成"""
    return _base_response(
        status="fill_completed",
        apply_record_id=apply_record_id,
        message="表单填写完成，等待后续处理",
        filled_count=len(filled_fields),
        failed_count=len(failed_fields),
        no_value_count=len(no_value_fields),
        filled_fields=filled_fields,
        failed_fields=failed_fields,
        no_value_fields=no_value_fields
    )


# ==================== 阶段三：迭代 ====================

def need_iteration(
    apply_record_id: int,
    new_missing: List[Dict],
    failed_fields: List[Dict]
) -> Dict:
    """
    需要迭代处理
    
    Args:
        new_missing: 新发现的缺失字段
        failed_fields: 填写失败的字段
    """
    has_new_missing = len(new_missing) > 0
    
    return _base_response(
        status="need_iteration",
        apply_record_id=apply_record_id,
        message="需要处理缺失/失败字段" if has_new_missing else "需要重试失败字段",
        wait_for="user" if has_new_missing else None,
        new_missing=new_missing,
        new_missing_count=len(new_missing),
        failed_fields=failed_fields,
        failed_count=len(failed_fields)
    )


def iterating(
    apply_record_id: int,
    retry_field_ids: List[str]
) -> Dict:
    """正在定向迭代"""
    return _base_response(
        status="iterating",
        apply_record_id=apply_record_id,
        message=f"正在重试 {len(retry_field_ids)} 个字段",
        wait_for="system",
        retry_fields=retry_field_ids
    )


# ==================== 阶段四：审核 ====================

def pending_review(
    apply_record_id: int,
    filled_fields: List[Dict]
) -> Dict:
    """
    等待用户审核
    
    Args:
        filled_fields: 已填写字段列表，每个包含:
            - field_id: 字段 ID
            - field_label: 字段标签
            - value: 填写的值
            - source: 数据来源
            - page: 所在页码
    """
    return _base_response(
        status="pending_review",
        apply_record_id=apply_record_id,
        message="请审核以下填写内容",
        wait_for="user",
        fields=filled_fields,
        total_count=len(filled_fields),
        actions=["confirm", "modify"]
    )


def user_modified(
    apply_record_id: int,
    modifications: List[Dict]
) -> Dict:
    """用户已修改，等待应用"""
    return _base_response(
        status="user_modified",
        apply_record_id=apply_record_id,
        message=f"正在应用 {len(modifications)} 项修改",
        wait_for="system",
        modifications=modifications
    )


# ==================== 终态 ====================

def completed(
    apply_record_id: int,
    filled_summary: Optional[Dict] = None
) -> Dict:
    """申请完成"""
    return _base_response(
        status="completed",
        apply_record_id=apply_record_id,
        message="申请已完成！",
        wait_for=None,
        summary=filled_summary or {}
    )


def error(
    apply_record_id: int,
    error_type: str,
    error_message: str,
    recoverable: bool = False,
    retry_action: Optional[str] = None
) -> Dict:
    """
    错误
    
    Args:
        error_type: 错误类型
            - validation_error: 验证错误
            - network_error: 网络错误
            - captcha_required: 需要验证码
            - login_expired: 登录过期
            - system_error: 系统错误
            - modification_failed: 修改应用失败
        error_message: 错误信息
        recoverable: 是否可恢复
        retry_action: 重试动作
    """
    return _base_response(
        status="error",
        apply_record_id=apply_record_id,
        message=error_message,
        wait_for="user" if recoverable else None,
        error={
            "type": error_type,
            "message": error_message,
            "recoverable": recoverable,
            "retry_action": retry_action
        }
    )


# ==================== 工具函数 ====================

def get_expected_user_action(status: str) -> Optional[str]:
    """
    获取某状态下期望的用户动作
    
    Returns:
        用户应该发送的 user_action 值
    """
    action_map = {
        "need_input": "submit_missing",
        "pending_review": "confirm_review",  # 或 "submit_modifications"
        "error": "retry",
    }
    return action_map.get(status)


def is_terminal_status(status: str) -> bool:
    """检查是否为终态"""
    return status in ["completed", "failed"]


def is_waiting_user(response: Dict) -> bool:
    """检查是否在等待用户输入"""
    return response.get("wait_for") == "user"
