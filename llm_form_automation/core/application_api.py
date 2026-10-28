"""
申请 API 统一入口

所有申请相关操作都通过这个模块进行，自动处理状态转换
"""

import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# LLM 客户端
try:
    import requests
    import json
    HAS_LLM = True
except ImportError:
    HAS_LLM = False

from llm_form_automation.core.application_state_machine import (
    ApplicationStateMachine,
    ProcessStatus
)
from llm_form_automation.core.response_status import (
    analyzing, need_input, ready_to_fill, filling,
    need_iteration, iterating, pending_review,
    user_modified, completed, error
)


class ApplicationAPI:
    """
    申请 API 统一入口
    
    所有前端请求都通过 process() 方法处理：
    
    ```python
    api = ApplicationAPI(db)
    result = await api.process(
        apply_record_id=22,
        user_action="submit_missing",  # 可选
        user_data={...}                # 可选
    )
    ```
    """
    
    def __init__(self, db):
        self.db = db
    
    def _create_llm_client(self):
        """创建 LLM 客户端（使用 requests）"""
        if not HAS_LLM:
            print("⚠️ requests 库未安装，字段匹配将使用简单逻辑")
            return None
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("⚠️ 未设置 OPENAI_API_KEY，字段匹配将使用简单逻辑")
            return None
        
        base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        
        # 返回一个简单的客户端配置
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": "gpt-4o"
        }
    
    async def process(
        self,
        apply_record_id: int,
        user_action: Optional[str] = None,
        user_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        处理申请请求
        
        Args:
            apply_record_id: 申请记录 ID
            user_action: 用户动作
                - None: 系统自动推进
                - "submit_missing": 用户提交了缺失字段
                - "confirm_review": 用户确认了审核
                - "submit_modifications": 用户提交了修改
                - "retry": 用户请求重试
            user_data: 用户提交的数据
        
        Returns:
            标准化返回结果
        """
        try:
            # 1. 获取状态机
            machine = ApplicationStateMachine(self.db, apply_record_id)
            current_status = machine.get_current_status()
            
            # 2. 根据用户动作更新状态
            if user_action:
                self._handle_user_action(machine, user_action, user_data)
                current_status = machine.get_current_status()
            
            # 3. 根据当前状态执行对应逻辑
            return await self._execute_stage(machine, current_status)
        
        except Exception as e:
            return error(
                apply_record_id=apply_record_id,
                error_type="system_error",
                error_message=str(e),
                recoverable=True
            )
    
    def _handle_user_action(
        self,
        machine: ApplicationStateMachine,
        user_action: str,
        user_data: Optional[Dict] = None
    ):
        """
        处理用户动作
        
        注意：每个动作都有状态校验，只有在正确状态下才能执行
        """
        status = machine.get_current_status()
        
        if user_action == "submit_missing":
            # 状态校验：只能在等待用户输入的状态
            if status not in [ProcessStatus.NEED_INPUT_PRE, ProcessStatus.NEED_INPUT_ITER]:
                return  # 忽略无效动作
            
            # 用户提交了缺失字段的值
            if user_data and "fields" in user_data:
                self.db.resolve_missing_fields_batch(
                    machine.apply_record_id,
                    user_data["fields"]
                )
            
            # 检查是否还有未解决的
            unresolved = self.db.get_missing_fields(
                machine.apply_record_id,
                only_unresolved=True
            )
            
            if not unresolved:
                if status == ProcessStatus.NEED_INPUT_PRE:
                    machine.update_status(ProcessStatus.READY_TO_FILL, "缺失字段已补充")
                elif status == ProcessStatus.NEED_INPUT_ITER:
                    machine.update_status(ProcessStatus.ITERATING, "准备重试")
        
        elif user_action == "confirm_review":
            # 状态校验：只能在等待审核状态
            if status != ProcessStatus.PENDING_REVIEW:
                return  # 忽略无效动作
            
            # 用户确认审核（无修改，直接通过）
            machine.update_status(ProcessStatus.COMPLETED, "用户确认，申请完成")
        
        elif user_action == "submit_modifications":
            # 状态校验：只能在等待审核状态
            if status != ProcessStatus.PENDING_REVIEW:
                return  # 忽略无效动作
            
            # 用户提交了修改
            if user_data and "modifications" in user_data:
                for mod in user_data["modifications"]:
                    self.db.update_field_review(
                        machine.apply_record_id,
                        mod["field_id"],
                        "modify",
                        mod["new_value"]
                    )
            machine.update_status(ProcessStatus.USER_MODIFIED, "修改已记录")
        
        elif user_action == "retry":
            # 状态校验：只能在失败状态
            if status != ProcessStatus.FAILED:
                return  # 忽略无效动作
            
            machine.update_status(ProcessStatus.CREATED, "重新开始")
    
    async def _execute_stage(
        self,
        machine: ApplicationStateMachine,
        status: ProcessStatus
    ) -> Dict[str, Any]:
        """根据状态执行对应阶段逻辑"""
        apply_record_id = machine.apply_record_id
        
        # ========== 阶段一：预分析 ==========
        if status == ProcessStatus.CREATED:
            # 开始分析
            machine.update_status(ProcessStatus.ANALYZING, "开始分析")
            return analyzing(apply_record_id)
        
        elif status == ProcessStatus.ANALYZING:
            # 执行预分析
            result = await self._run_pre_analysis(apply_record_id)
            
            if result["has_missing"]:
                machine.update_status(ProcessStatus.NEED_INPUT_PRE, "发现缺失字段")
                return need_input(
                    apply_record_id,
                    result["missing_fields"],
                    stage="pre_analysis"
                )
            else:
                machine.update_status(ProcessStatus.READY_TO_FILL, "准备填写")
                return ready_to_fill(
                    apply_record_id,
                    result["total_fields"],
                    result["mapped_fields"]
                )
        
        elif status == ProcessStatus.NEED_INPUT_PRE:
            # 等待用户补充
            missing = self.db.get_missing_fields(apply_record_id, only_unresolved=True)
            return need_input(apply_record_id, missing, stage="pre_analysis")
        
        elif status == ProcessStatus.READY_TO_FILL:
            # 开始填写
            machine.update_status(ProcessStatus.FILLING, "开始填写")
            return filling(apply_record_id, current_page=1)
        
        # ========== 阶段二：填写 ==========
        elif status == ProcessStatus.FILLING:
            # 执行填写
            result = await self._run_filling(apply_record_id)
            
            # 填写完成，转到 FILL_COMPLETED 处理结果
            machine.update_status(ProcessStatus.FILL_COMPLETED, "填写完成，处理结果中")
            # 直接进入结果处理
            return await self._execute_stage(machine, ProcessStatus.FILL_COMPLETED)
        
        elif status == ProcessStatus.FILL_COMPLETED:
            # 处理填写结果
            fill_result = self.db.get_fill_result(apply_record_id)
            new_missing = fill_result.get("fields_no_value", [])
            failed_fields = fill_result.get("fields_failed", [])
            filled_fields = fill_result.get("fields_filled", [])
            
            if new_missing or failed_fields:
                machine.update_status(ProcessStatus.NEED_ITERATION, "需要迭代")
                return need_iteration(
                    apply_record_id,
                    new_missing,
                    failed_fields
                )
            else:
                # 全部成功，进入 review
                machine.update_status(ProcessStatus.PENDING_REVIEW, "等待审核")
                return pending_review(
                    apply_record_id,
                    filled_fields
                )
        
        # ========== 阶段三：定向迭代 ==========
        elif status == ProcessStatus.NEED_ITERATION:
            # 检查是否有新的 missing 需要用户补充
            fill_result = self.db.get_fill_result(apply_record_id)
            new_missing = fill_result.get("fields_no_value", [])
            
            if new_missing:
                # 先要求用户补充
                machine.update_status(ProcessStatus.NEED_INPUT_ITER, "需要补充新字段")
                return need_input(apply_record_id, new_missing, stage="iteration")
            else:
                # 直接开始迭代
                machine.update_status(ProcessStatus.ITERATING, "开始迭代")
                return iterating(
                    apply_record_id,
                    [f["field_id"] for f in fill_result.get("fields_failed", [])]
                )
        
        elif status == ProcessStatus.NEED_INPUT_ITER:
            # 等待用户补充（迭代时）
            missing = self.db.get_missing_fields(apply_record_id, only_unresolved=True)
            return need_input(apply_record_id, missing, stage="iteration")
        
        elif status == ProcessStatus.ITERATING:
            # 执行定向迭代
            result = await self._run_iteration(apply_record_id)
            
            if result["still_failed"]:
                # 仍有失败，继续迭代
                machine.update_status(ProcessStatus.NEED_ITERATION, "仍有失败字段")
                return need_iteration(
                    apply_record_id,
                    result.get("new_missing", []),
                    result["still_failed"]
                )
            else:
                # 全部成功
                machine.update_status(ProcessStatus.PENDING_REVIEW, "等待审核")
                return pending_review(
                    apply_record_id,
                    result["filled_fields"]
                )
        
        # ========== 阶段四：Review ==========
        elif status == ProcessStatus.PENDING_REVIEW:
            # 等待用户审核
            review = self.db.get_fill_review(apply_record_id)
            if review:
                return pending_review(
                    apply_record_id,
                    review.get("fields_data", [])
                )
            else:
                # 没有 review 数据，从 fill_result 获取
                fill_result = self.db.get_fill_result(apply_record_id)
                return pending_review(
                    apply_record_id,
                    fill_result.get("fields_filled", [])
                )
        
        elif status == ProcessStatus.USER_MODIFIED:
            # 应用用户修改
            result = await self._apply_modifications(apply_record_id)
            
            if result["success"]:
                # 修改应用成功，重新进入 review
                machine.update_status(ProcessStatus.PENDING_REVIEW, "修改已应用")
                return pending_review(
                    apply_record_id,
                    result["updated_fields"]
                )
            else:
                return error(
                    apply_record_id,
                    "modification_failed",
                    result["error"]
                )
        
        # ========== 完成 ==========
        elif status == ProcessStatus.COMPLETED:
            # 获取完成信息
            fill_result = self.db.get_fill_result(apply_record_id)
            return completed(
                apply_record_id,
                filled_summary=fill_result.get("summary", {})
            )
        
        elif status == ProcessStatus.FAILED:
            process = self.db.get_application_process(apply_record_id)
            return error(
                apply_record_id,
                "application_failed",
                process.get("status_message", "Unknown error"),
                recoverable=True
            )
        
        else:
            return error(
                apply_record_id,
                "unknown_status",
                f"Unknown status: {status.value}"
            )
    
    # ========== 内部执行方法 ==========
    
    async def _run_pre_analysis(self, apply_record_id: int) -> Dict:
        """执行预分析
        
        流程：
        1. 检查数据库是否有该学校的字段数据
        2. 如果没有，自动爬取页面并提取字段
        3. 执行字段匹配
        """
        from llm_form_automation.core.application_pipeline import create_pipeline
        from llm_form_automation.core.field_matcher import FieldMatcher
        
        pipeline = create_pipeline(self.db, apply_record_id)
        if not pipeline or not pipeline.context:
            raise ValueError(f"Failed to create pipeline for apply_record_id {apply_record_id}")
        
        uni_id = pipeline.context.uni_id or "unknown"

        # 获取学校字段
        university_fields = self.db.get_university_fields(uni_id)

        # 如果没有字段数据，自动爬取
        if not university_fields:
            print(f"📥 university_fields 为空，开始爬取页面...")
            university_fields = await self._crawl_and_extract_fields(apply_record_id, uni_id)

        # 获取用户信息
        user_id = pipeline.context.user_id if pipeline.context else ""
        user_info = self.db.get_user_application_info(user_id) or {} if user_id else {}
        
        # 创建 LLM 客户端
        llm_client = self._create_llm_client()
        
        # 创建 matcher 并执行映射 (async)
        matcher = FieldMatcher(self.db, llm_client)
        report = await matcher.match_fields(user_info, university_fields)
        
        # 保存需要用户提供的字段
        if report.needs_user:
            matcher.save_needs_user_fields(apply_record_id, report)
        
        return {
            "has_missing": len(report.needs_user) > 0,
            "missing_fields": [
                {
                    "field_id": f.field_id,
                    "field_label": f.field_label,
                    "field_type": f.field_type,
                    "options": f.options
                }
                for f in report.needs_user
            ],
            "total_fields": report.total_fields,
            "mapped_fields": len(report.can_fill)
        }
    
    async def _crawl_and_extract_fields(self, apply_record_id: int, uni_id: str) -> List[Dict]:
        """爬取页面并提取字段
        
        调用 01_crawl_pages.py 中的 crawl_and_extract_fields 函数
        """
        # 动态导入，避免循环依赖（因为文件名以数字开头，需要特殊处理）
        import importlib.util
        from pathlib import Path
        
        script_path = Path(__file__).parent.parent / "scripts" / "01_crawl_pages.py"
        spec = importlib.util.spec_from_file_location("crawl_pages", script_path)
        if not spec or not spec.loader:
            raise ImportError(f"Failed to load crawl_pages module from {script_path}")
        crawl_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(crawl_module)
        
        # 获取申请记录信息
        apply_record = self.db.get_apply_record(apply_record_id)
        if not apply_record:
            raise ValueError(f"Apply record {apply_record_id} not found")
        
        start_url = apply_record.get("application_url", "")
        email = apply_record.get("email", "")
        password = apply_record.get("password", "")
        
        if not start_url:
            raise ValueError("申请 URL 为空")
        if not email or not password:
            raise ValueError("登录凭据为空")
        
        # 从 URL 自动提取学校名称作为 uni_id
        from urllib.parse import urlparse
        
        try:
            domain = urlparse(start_url).netloc.lower()
            # 提取主域名部分（去掉子域名）
            domain_parts = domain.split('.')
            if len(domain_parts) >= 2:
                # 取倒数第二个部分作为学校名称
                actual_uni_id = domain_parts[-2]
            else:
                actual_uni_id = domain.replace('.', '_')
            
            # 如果是常见的通用域名，尝试从子域名提取
            if actual_uni_id in ['edu', 'com', 'org', 'net']:
                if len(domain_parts) >= 3:
                    actual_uni_id = domain_parts[-3]
            
            print(f"  🏫 从 URL 提取学校名称: {actual_uni_id}")
            print(f"      原始域名: {domain}")
            
        except Exception as e:
            print(f"  ⚠️ URL 解析失败: {e}")
            actual_uni_id = uni_id or "unknown"
        
        # 调用爬取函数
        fields = await crawl_module.crawl_and_extract_fields(
            start_url=start_url,
            email=email,
            password=password,
            uni_id=actual_uni_id,  # 使用推断的学校名称
            db=self.db,
            max_pages=15,
            headless=True  # 使用 headless 模式避免界面卡顿
        )
        
        return fields
    
    async def _run_filling(self, apply_record_id: int) -> Dict:
        """执行填写"""
        from llm_form_automation.core.filling_executor import FillingExecutor
        
        executor = FillingExecutor(self.db, apply_record_id)
        result = await executor.execute_filling()
        
        return {
            "filled_fields": result.get("filled_fields", []),
            "new_missing": result.get("no_value_fields", []),
            "failed_fields": result.get("failed_fields", [])
        }
    
    async def _run_iteration(self, apply_record_id: int) -> Dict:
        """执行定向迭代"""
        from llm_form_automation.core.filling_executor import FillingExecutor
        
        # 获取需要重试的字段
        fill_result = self.db.get_fill_result(apply_record_id)
        failed_fields = fill_result.get("fields_failed", [])
        failed_ids = [f.get("field_id") for f in failed_fields]
        
        executor = FillingExecutor(self.db, apply_record_id)
        result = await executor.execute_iteration(failed_ids)
        
        return {
            "filled_fields": result.get("filled_fields", []),
            "still_failed": result.get("still_failed", []),
            "new_missing": []
        }
    
    async def _apply_modifications(self, apply_record_id: int) -> Dict:
        """应用用户修改"""
        from llm_form_automation.core.filling_executor import FillingExecutor
        
        modifications = self.db.get_modified_fields(apply_record_id)
        
        if not modifications:
            return {"success": True, "updated_fields": []}
        
        executor = FillingExecutor(self.db, apply_record_id)
        result = await executor.apply_modifications(modifications)
        
        if result.get("success"):
            # 获取更新后的字段
            review = self.db.get_fill_review(apply_record_id)
            return {
                "success": True,
                "updated_fields": review.get("fields_data", [])
            }
        else:
            return {
                "success": False,
                "error": f"Failed to apply {len(result.get('failed', []))} modifications"
            }


# ========== 便捷函数 ==========

async def handle_apply_request(
    db,
    apply_record_id: int,
    user_action: Optional[str] = None,
    user_data: Optional[Dict] = None
) -> Dict:
    """
    处理申请请求的便捷函数
    
    使用方式:
    ```python
    from llm_form_automation.core.application_api import handle_apply_request
    
    result = await handle_apply_request(
        db=get_db(),
        apply_record_id=22,
        user_action="submit_missing",
        user_data={"fields": {"gre_score": "330"}}
    )
    ```
    """
    api = ApplicationAPI(db)
    return await api.process(apply_record_id, user_action, user_data)

