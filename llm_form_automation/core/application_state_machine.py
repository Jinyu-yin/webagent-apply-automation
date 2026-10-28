"""
申请状态机

根据数据库中的状态自动进入对应处理阶段，避免重复操作

状态流转:
  
  ┌────────────────────────────────────────────────────────────────────┐
  │                        申请状态流转图                              │
  └────────────────────────────────────────────────────────────────────┘
  
  [created] ───► [analyzing] ───┬───► [need_input_pre] ───► [ready_to_fill]
                                │                                │
                                └─────────────────────────────────┘
                                                                  │
                                                                  ▼
                                                             [filling]
                                                                  │
                        ┌────────────────┬────────────────────────┤
                        ▼                │                        ▼
                [need_iteration] ◄───────┤              [pending_review]
                        │                │                    │   │
                        ▼                │                    │   ▼
                [need_input_iter]        │                    │ [completed]
                        │                │                    │
                        ▼                │                    ▼
                  [iterating] ───────────┘              [user_modified]
                        │                                     │
                        └─────────────► [pending_review] ◄────┘

等待用户的状态: need_input_pre, need_input_iter, pending_review
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass


class ProcessStatus(Enum):
    """申请流程状态 - 对应 application_process.process_status"""
    
    # 初始状态
    CREATED = "created"
    
    # 阶段一：预分析
    ANALYZING = "analyzing"
    NEED_INPUT_PRE = "need_input_pre"         # 预分析发现缺失，等待用户补充
    READY_TO_FILL = "ready_to_fill"
    
    # 阶段二：填写
    FILLING = "filling"
    FILL_COMPLETED = "fill_completed"         # 填写完成，待后处理
    
    # 阶段三：定向迭代
    NEED_INPUT_ITER = "need_input_iter"       # 迭代时发现新缺失，等待用户补充
    NEED_ITERATION = "need_iteration"         # 有失败字段，需要迭代
    ITERATING = "iterating"
    
    # 阶段四：Review
    PENDING_REVIEW = "pending_review"
    USER_MODIFIED = "user_modified"           # 用户修改了，需要应用
    
    # 完成/失败
    COMPLETED = "completed"
    FAILED = "failed"
    
    @classmethod
    def waiting_user_states(cls) -> List['ProcessStatus']:
        """需要等待用户输入的状态"""
        return [cls.NEED_INPUT_PRE, cls.NEED_INPUT_ITER, cls.PENDING_REVIEW]
    
    @classmethod
    def is_waiting_user(cls, status: 'ProcessStatus') -> bool:
        """判断是否在等待用户"""
        return status in cls.waiting_user_states()


# 状态转换规则
STATE_TRANSITIONS = {
    ProcessStatus.CREATED: [ProcessStatus.ANALYZING],
    ProcessStatus.ANALYZING: [ProcessStatus.NEED_INPUT_PRE, ProcessStatus.READY_TO_FILL],
    ProcessStatus.NEED_INPUT_PRE: [ProcessStatus.READY_TO_FILL],
    ProcessStatus.READY_TO_FILL: [ProcessStatus.FILLING],
    ProcessStatus.FILLING: [ProcessStatus.FILL_COMPLETED, ProcessStatus.NEED_ITERATION, ProcessStatus.PENDING_REVIEW],
    ProcessStatus.FILL_COMPLETED: [ProcessStatus.NEED_ITERATION, ProcessStatus.PENDING_REVIEW],
    ProcessStatus.NEED_ITERATION: [ProcessStatus.NEED_INPUT_ITER, ProcessStatus.ITERATING],
    ProcessStatus.NEED_INPUT_ITER: [ProcessStatus.ITERATING],
    ProcessStatus.ITERATING: [ProcessStatus.NEED_ITERATION, ProcessStatus.PENDING_REVIEW],
    ProcessStatus.PENDING_REVIEW: [ProcessStatus.USER_MODIFIED, ProcessStatus.COMPLETED],
    ProcessStatus.USER_MODIFIED: [ProcessStatus.PENDING_REVIEW],
}


class ApplicationStateMachine:
    """
    申请状态机
    
    使用方式:
    ```python
    machine = ApplicationStateMachine(db, apply_record_id)
    
    # 获取当前状态
    status = machine.get_current_status()
    
    # 更新状态
    machine.update_status(ProcessStatus.FILLING, "开始填写")
    
    # 检查是否在等待用户
    if machine.is_waiting_user():
        return machine.get_waiting_info()
    ```
    """
    
    def __init__(self, db, apply_record_id: int):
        self.db = db
        self.apply_record_id = apply_record_id
        self._current_status = None
        self._process_data = None
    
    def get_current_status(self) -> ProcessStatus:
        """获取当前状态"""
        if self._current_status is None:
            self._load_process_data()
        return self._current_status
    
    def _load_process_data(self):
        """从数据库加载流程数据"""
        process = self.db.get_application_process(self.apply_record_id)
        if process:
            status_str = process.get("process_status", "created")
            try:
                self._current_status = ProcessStatus(status_str)
            except ValueError:
                self._current_status = ProcessStatus.CREATED
            self._process_data = process
        else:
            # 创建新的 application_process 记录
            self._current_status = ProcessStatus.CREATED
            self._process_data = self._create_process_record()
    
    def _create_process_record(self) -> Dict:
        """创建 application_process 记录"""
        # 获取 apply_record 信息
        apply_record = self.db.get_apply_record(self.apply_record_id)
        if not apply_record:
            raise ValueError(f"Apply record {self.apply_record_id} not found")
        
        user_id = apply_record.get("user_id", "")
        prog_id = apply_record.get("prog_id", "")
        
        # 尝试获取 uni_id
        uni_id = ""
        if prog_id:
            program = self.db.get_program(prog_id)
            if program:
                uni_id = program.get("uni_id", "")
        
        # 如果还没有 uni_id，尝试从 URL 推断
        if not uni_id:
            url = apply_record.get("application_url", "")
            if "berkeley" in url.lower():
                uni_id = "berkeley"
        
        # 创建记录
        process = self.db.create_application_process(
            apply_record_id=self.apply_record_id,
            user_id=user_id,
            uni_id=uni_id or "unknown",
            prog_id=prog_id
        )
        return process
    
    def refresh(self):
        """刷新状态"""
        self._current_status = None
        self._process_data = None
        self._load_process_data()
    
    def update_status(self, new_status: ProcessStatus, message: str = None):
        """更新状态"""
        # 检查状态转换是否合法（可选，允许跳过某些状态）
        # if not self.can_transition_to(new_status):
        #     raise ValueError(f"Cannot transition from {self._current_status} to {new_status}")
        
        self.db.update_process_status(
            self.apply_record_id,
            new_status.value,
            message
        )
        self._current_status = new_status
    
    def can_transition_to(self, new_status: ProcessStatus) -> bool:
        """检查是否可以转换到新状态"""
        current = self.get_current_status()
        allowed = STATE_TRANSITIONS.get(current, [])
        return new_status in allowed
    
    def is_waiting_user(self) -> bool:
        """检查当前状态是否在等待用户"""
        return ProcessStatus.is_waiting_user(self.get_current_status())
    
    def get_process_data(self) -> Dict:
        """获取流程数据"""
        if self._process_data is None:
            self._load_process_data()
        return self._process_data or {}
    
    def get_fill_result(self) -> Dict:
        """获取填写结果"""
        return self.get_process_data().get("fill_result", {})
    
    def get_checkpoint(self) -> Dict:
        """获取断点数据"""
        return self.get_process_data().get("checkpoint_data", {})
    
    def get_next_action(self) -> Dict[str, Any]:
        """
        根据当前状态返回下一步操作
        
        Returns:
            {
                "status": str,          # 当前状态
                "action": str,          # 需要执行的动作
                "wait_for": str | None, # "user" / "system" / None
                "message": str,         # 提示信息
                "data": Dict            # 相关数据（可选）
            }
        """
        status = self.get_current_status()
        process = self.get_process_data()
        fill_result = process.get("fill_result", {})
        
        # 基础响应
        base = {
            "status": status.value,
            "apply_record_id": self.apply_record_id
        }
        
        action_map = {
            ProcessStatus.CREATED: {
                "action": "start_analysis",
                "wait_for": None,
                "message": "开始预分析"
            },
            ProcessStatus.ANALYZING: {
                "action": "run_analysis",
                "wait_for": "system",
                "message": "正在分析表单字段..."
            },
            ProcessStatus.NEED_INPUT_PRE: {
                "action": "wait_user_input",
                "wait_for": "user",
                "message": "请补充缺失字段",
                "data": {
                    "stage": "pre_analysis",
                    "missing_fields": self._get_missing_fields_safe()
                }
            },
            ProcessStatus.READY_TO_FILL: {
                "action": "start_filling",
                "wait_for": None,
                "message": "准备开始填写"
            },
            ProcessStatus.FILLING: {
                "action": "run_filling",
                "wait_for": "system",
                "message": f"填写中 (第 {process.get('current_page', 0)} 页)",
                "data": {
                    "current_page": process.get("current_page", 0),
                    "total_pages": process.get("total_pages"),
                    "fields_filled": process.get("fields_filled", 0),
                    "fields_total": process.get("fields_total")
                }
            },
            ProcessStatus.FILL_COMPLETED: {
                "action": "process_fill_result",
                "wait_for": None,
                "message": "填写完成，处理结果中..."
            },
            ProcessStatus.NEED_INPUT_ITER: {
                "action": "wait_user_input",
                "wait_for": "user",
                "message": "发现新的缺失字段，请补充",
                "data": {
                    "stage": "iteration",
                    "missing_fields": self._get_missing_fields_safe(only_unresolved=True)
                }
            },
            ProcessStatus.NEED_ITERATION: {
                "action": "start_iteration",
                "wait_for": None,
                "message": "准备定向迭代",
                "data": {
                    "failed_fields": fill_result.get("fields_failed", []),
                    "new_missing": fill_result.get("fields_no_value", [])
                }
            },
            ProcessStatus.ITERATING: {
                "action": "run_iteration",
                "wait_for": "system",
                "message": "正在重试失败字段..."
            },
            ProcessStatus.PENDING_REVIEW: {
                "action": "wait_user_review",
                "wait_for": "user",
                "message": "请审核填写结果",
                "data": {
                    "filled_fields": fill_result.get("fields_filled", []),
                    "review": self._get_fill_review_safe()
                }
            },
            ProcessStatus.USER_MODIFIED: {
                "action": "apply_modifications",
                "wait_for": None,
                "message": "正在应用修改...",
                "data": {
                    "modifications": self._get_modifications_safe()
                }
            },
            ProcessStatus.COMPLETED: {
                "action": "none",
                "wait_for": None,
                "message": "申请已完成！",
                "data": {
                    "summary": fill_result.get("summary", {})
                }
            },
            ProcessStatus.FAILED: {
                "action": "retry_or_abort",
                "wait_for": "user",
                "message": process.get("status_message", "申请失败"),
                "data": {
                    "error": process.get("status_message"),
                    "recoverable": True
                }
            }
        }
        
        result = action_map.get(status, {
            "action": "unknown",
            "wait_for": None,
            "message": f"未知状态: {status.value}"
        })
        
        return {**base, **result}
    
    def _get_missing_fields_safe(self, only_unresolved: bool = False) -> List[Dict]:
        """安全获取缺失字段"""
        try:
            return self.db.get_missing_fields(
                self.apply_record_id,
                only_unresolved=only_unresolved
            )
        except Exception:
            return []
    
    def _get_fill_review_safe(self) -> Optional[Dict]:
        """安全获取 fill_review"""
        try:
            return self.db.get_fill_review(self.apply_record_id)
        except Exception:
            return None
    
    def _get_modifications_safe(self) -> List[Dict]:
        """安全获取用户修改"""
        try:
            return self.db.get_modified_fields(self.apply_record_id)
        except Exception:
            return []
    
    def handle_user_action(self, user_action: str, user_data: Dict = None) -> bool:
        """
        处理用户动作，更新状态
        
        Args:
            user_action: 用户动作类型
                - "submit_missing": 用户提交了缺失字段
                - "confirm_review": 用户确认了 review
                - "submit_modifications": 用户提交了修改
                - "retry": 用户请求重试
            user_data: 用户提交的数据
        
        Returns:
            是否成功处理
        """
        status = self.get_current_status()
        
        if user_action == "submit_missing":
            # 用户补充了缺失字段
            if status in [ProcessStatus.NEED_INPUT_PRE, ProcessStatus.NEED_INPUT_ITER]:
                # 先保存用户数据
                if user_data and "fields" in user_data:
                    for field_id, value in user_data["fields"].items():
                        self.db.resolve_missing_field(
                            self.apply_record_id,
                            field_id,
                            value
                        )
                
                # 检查是否还有未解决的
                unresolved = self._get_missing_fields_safe(only_unresolved=True)
                if not unresolved:
                    if status == ProcessStatus.NEED_INPUT_PRE:
                        self.update_status(ProcessStatus.READY_TO_FILL, "缺失字段已补充")
                    else:
                        self.update_status(ProcessStatus.ITERATING, "准备重试")
                    return True
            return False
        
        elif user_action == "confirm_review":
            # 用户确认了 review（无修改）
            if status == ProcessStatus.PENDING_REVIEW:
                self.update_status(ProcessStatus.COMPLETED, "用户确认，申请完成")
                return True
            return False
        
        elif user_action == "submit_modifications":
            # 用户提交了修改
            if status == ProcessStatus.PENDING_REVIEW:
                if user_data and "modifications" in user_data:
                    for mod in user_data["modifications"]:
                        self.db.update_field_review(
                            self.apply_record_id,
                            mod["field_id"],
                            "modify",
                            mod["new_value"]
                        )
                self.update_status(ProcessStatus.USER_MODIFIED, "用户提交了修改")
                return True
            return False
        
        elif user_action == "retry":
            # 用户请求重试
            if status == ProcessStatus.FAILED:
                self.update_status(ProcessStatus.CREATED, "重新开始")
                return True
            return False
        
        return False


# ==================== 便捷函数 ====================

def get_current_stage(db, apply_record_id: int) -> Dict[str, Any]:
    """
    获取当前阶段信息
    
    使用方式:
    ```python
    from llm_form_automation.core.application_state_machine import get_current_stage
    
    stage = get_current_stage(db, 22)
    print(stage["status"])      # "need_input_pre"
    print(stage["wait_for"])    # "user"
    print(stage["message"])     # "请补充缺失字段"
    ```
    """
    machine = ApplicationStateMachine(db, apply_record_id)
    return machine.get_next_action()


def is_waiting_for_user(db, apply_record_id: int) -> bool:
    """检查是否在等待用户输入"""
    machine = ApplicationStateMachine(db, apply_record_id)
    return machine.is_waiting_user()


def get_expected_user_action(status: str) -> Optional[str]:
    """
    根据状态返回期望的用户动作
    
    Returns:
        期望的 user_action 值，如 "submit_missing", "confirm_review" 等
    """
    action_map = {
        "need_input_pre": "submit_missing",
        "need_input_iter": "submit_missing",
        "pending_review": "confirm_review",  # 或 "submit_modifications"
        "failed": "retry",
    }
    return action_map.get(status)

