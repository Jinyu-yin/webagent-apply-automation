"""
填写执行器

提供可被 API 调用的填写逻辑，集成 EvaluateAgent 进行结果验证
"""

import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 导入评价 Agent（延迟导入以避免循环依赖）
def _get_evaluator():
    """获取 EvaluateAgent 实例"""
    try:
        from llm_form_automation.scripts.evaluate_agent import EvaluateAgent
        return EvaluateAgent(verbose=True)
    except ImportError:
        return None


def _get_form_filler():
    """获取 LLMFormFiller 实例（延迟导入）"""
    try:
        from llm_form_automation.form_filler import LLMFormFiller
        return LLMFormFiller
    except ImportError:
        return None


class FillingExecutor:
    """
    填写执行器
    
    负责执行实际的表单填写操作，并正确更新数据库状态
    集成 EvaluateAgent 进行填写结果验证
    """
    
    def __init__(self, db, apply_record_id: int):
        self.db = db
        self.apply_record_id = apply_record_id
        self._context = None
        
        # 初始化评价 Agent（延迟加载）
        self.evaluator = _get_evaluator()
    
    def _get_context(self) -> Dict:
        """获取申请上下文"""
        if self._context is None:
            apply_record = self.db.get_apply_record(self.apply_record_id)
            if not apply_record:
                raise ValueError(f"Apply record {self.apply_record_id} not found")
            
            user_id = apply_record.get("user_id", "")
            prog_id = apply_record.get("prog_id", "")
            
            # 获取 uni_id
            uni_id = ""
            if prog_id:
                program = self.db.get_program(prog_id)
                if program:
                    uni_id = program.get("uni_id", "")
            
            self._context = {
                "apply_record_id": self.apply_record_id,
                "user_id": user_id,
                "prog_id": prog_id,
                "uni_id": uni_id
            }
        return self._context
    
    async def execute_filling(self, payload_path: Optional[str] = None) -> Dict[str, Any]:
        """
        执行填写
        
        Args:
            payload_path: payload 文件路径，如果为 None 则自动生成
        
        Returns:
            {
                "success": bool,
                "filled_fields": List[Dict],
                "failed_fields": List[Dict],
                "no_value_fields": List[Dict],
                "errors": List[Dict]
            }
        """
        context = self._get_context()
        
        # 1. 准备 payload
        if payload_path is None:
            payload_path = await self._generate_payload()
        
        if not payload_path or not Path(payload_path).exists():
            return {
                "success": False,
                "error": "Payload file not found",
                "filled_fields": [],
                "failed_fields": [],
                "no_value_fields": []
            }
        
        # 2. 初始化 fill_result
        self.db.update_fill_result(self.apply_record_id, {
            "fields_filled": [],
            "fields_no_value": [],
            "fields_failed": [],
            "errors": [],
            "started_at": datetime.utcnow().isoformat()
        })
        
        # 3. 执行填写（调用实际的填写脚本，脚本内部会使用 EvaluateAgent）
        try:
            result = await self._run_filling_script(payload_path)
            
            # 4. 最终处理
            final_result = self.db.finalize_fill_result(self.apply_record_id)
            
            # 5. 检查是否有提交验证结果
            submission_verified = final_result.get("submission_verified", False)
            submission_analysis = final_result.get("submission_analysis", "")
            
            # 6. 获取评价摘要（如果 evaluator 可用）
            eval_summary = self.evaluator.get_summary() if self.evaluator else {}
            
            return {
                "success": True,
                "filled_fields": final_result.get("fields_filled", []),
                "failed_fields": final_result.get("fields_failed", []),
                "no_value_fields": final_result.get("fields_no_value", []),
                "errors": final_result.get("errors", []),
                "submission_verified": submission_verified,
                "submission_analysis": submission_analysis,
                "evaluation_summary": eval_summary
            }
        
        except Exception as e:
            self.db.add_fill_error(
                self.apply_record_id,
                error_type="execution_error",
                message=str(e)
            )
            return {
                "success": False,
                "error": str(e),
                "filled_fields": [],
                "failed_fields": [],
                "no_value_fields": []
            }
    
    async def _generate_payload(self) -> Optional[str]:
        """生成 payload 文件"""
        from llm_form_automation.core.field_matcher import FieldMatcher
        
        context = self._get_context()
        matcher = FieldMatcher(self.db)
        
        # 获取映射报告
        user_info = self.db.get_user_application_info(context["user_id"]) or {}
        university_fields = self.db.get_university_fields(context["uni_id"])
        
        report = await matcher.match_fields(user_info, university_fields)
        
        # 生成完整 payload
        payload = matcher.generate_full_payload(
            self.apply_record_id,
            report
        )
        
        return payload.get("payload_path")
    
    async def _run_filling_script(self, payload_path: str) -> Dict:
        """
        运行填写脚本
        
        调用新的 form_filler 模块执行实际填写
        """
        return await self._run_as_subprocess(payload_path)
    
    async def _run_as_subprocess(self, payload_path: str) -> Dict:
        """通过子进程运行填写模块"""
        context = self._get_context()
        
        # 使用新的 form_filler.cli 模块
        cli_module = "llm_form_automation.form_filler.cli"
        
        # 获取申请 URL
        apply_record = self.db.get_apply_record(self.apply_record_id)
        start_url = apply_record.get("application_url") or apply_record.get("url") or ""
        
        if not start_url:
            # 尝试从 program 获取
            program = self.db.get_program(context.get("prog_id", ""))
            if program:
                start_url = program.get("application_url", "")
        
        if not start_url:
            raise ValueError("无法获取申请 URL")
        
        # 获取登录凭据（从 apply_record 获取，这是申请系统的账号）
        email = apply_record.get("email", "")
        password = apply_record.get("password", "")
        
        cmd = [
            sys.executable,
            "-m", cli_module,
            "--mode", "payload",  # 精确填写模式
            "--payload", payload_path,
            "--apply-record-id", str(self.apply_record_id),
            "--url", start_url,
        ]
        
        # 添加登录凭据
        if email:
            cmd.extend(["--email", email])
        if password:
            cmd.extend(["--password", password])
        
        print(f"🚀 启动填写模块: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else stdout.decode()
            raise Exception(f"填写模块执行失败: {error_msg}")
        
        print(f"✅ 填写模块执行完成")
        return {"success": True}
    
    async def _run_inline_mock(self, payload_path: str) -> Dict:
        """
        模拟填写（仅用于测试）
        
        ⚠️ 这是测试用的模拟实现，不会实际操作浏览器
        """
        import json
        
        with open(payload_path, 'r') as f:
            payload = json.load(f)
        
        fields = payload.get("fields", {})
        
        # 模拟：所有字段都填写成功
        filled_fields = []
        for field_id, field_data in fields.items():
            filled_fields.append({
                "field_id": field_id,
                "field_label": field_data.get("label", ""),
                "value": field_data.get("value", ""),
                "source": field_data.get("source", ""),
                "page": 1
            })
        
        self.db.update_fill_result(self.apply_record_id, {
            "fields_filled": filled_fields,
            "fields_no_value": [],
            "fields_failed": []
        })
        
        return {"success": True, "filled_count": len(filled_fields)}
    
    async def execute_iteration(self, failed_field_ids: List[str]) -> Dict[str, Any]:
        """
        执行定向迭代 - 只重试失败的字段
        
        Args:
            failed_field_ids: 需要重试的字段 ID 列表
        
        Returns:
            {
                "success": bool,
                "filled_fields": List[Dict],
                "still_failed": List[Dict]
            }
        """
        fill_result = self.db.get_fill_result(self.apply_record_id)
        
        if not failed_field_ids:
            return {
                "success": True,
                "filled_fields": fill_result.get("fields_filled", []),
                "still_failed": []
            }
        
        # 调用新模块的 retry 模式
        context = self._get_context()
        cli_module = "llm_form_automation.form_filler.cli"
        
        # 获取申请 URL
        apply_record = self.db.get_apply_record(self.apply_record_id)
        start_url = apply_record.get("application_url") or apply_record.get("url") or ""
        
        if not start_url:
            program = self.db.get_program(context.get("prog_id", ""))
            if program:
                start_url = program.get("application_url", "")
        
        # 获取 payload 路径
        payload_path = PROJECT_ROOT / "generated_payloads" / f"apply_{self.apply_record_id}.json"
        
        cmd = [
            sys.executable,
            "-m", cli_module,
            "--mode", "retry",  # 定向重试模式
            "--payload", str(payload_path),
            "--apply-record-id", str(self.apply_record_id),
            "--url", start_url,
        ]
        
        print(f"🔄 启动定向重试: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else stdout.decode()
            print(f"⚠️ 定向重试失败: {error_msg}")
        
        # 获取更新后的结果
        updated_result = self.db.get_fill_result(self.apply_record_id)
        
        return {
            "success": process.returncode == 0,
            "filled_fields": updated_result.get("fields_filled", []),
            "still_failed": updated_result.get("fields_failed", [])
        }
    
    async def apply_modifications(self, modifications: List[Dict]) -> Dict[str, Any]:
        """
        应用用户修改
        
        流程：
        1. 将修改的字段标记为"失败"（需要重填）
        2. 更新 payload 中的值
        3. 调用 --retry-failed 模式重新填写
        
        Args:
            modifications: 修改列表，每个包含:
                - field_id: 字段 ID
                - new_value: 新值
                - page: 页码
        
        Returns:
            {
                "success": bool,
                "applied": List[Dict],
                "failed": List[Dict]
            }
        """
        if not modifications:
            return {"success": True, "applied": [], "failed": []}
        
        # 1. 获取当前 fill_result
        fill_result = self.db.get_fill_result(self.apply_record_id)
        fields_filled = fill_result.get("fields_filled", [])
        fields_failed = fill_result.get("fields_failed", [])
        
        # 2. 将要修改的字段从 filled 移到 failed，并更新值
        modified_field_ids = {m["field_id"] for m in modifications}
        mod_value_map = {m["field_id"]: m["new_value"] for m in modifications}
        
        new_filled = []
        for field in fields_filled:
            if field.get("field_id") in modified_field_ids:
                # 移到 failed 列表，带上新值
                fields_failed.append({
                    **field,
                    "value": mod_value_map[field["field_id"]],
                    "reason": "user_modification"
                })
            else:
                new_filled.append(field)
        
        # 3. 更新 fill_result
        self.db.update_fill_result(self.apply_record_id, {
            "fields_filled": new_filled,
            "fields_failed": fields_failed
        })
        
        # 4. 调用定向重试来应用修改
        result = await self.execute_iteration(list(modified_field_ids))
        
        # 5. 检查结果
        applied = []
        failed = []
        
        updated_result = self.db.get_fill_result(self.apply_record_id)
        updated_filled = updated_result.get("fields_filled", [])
        updated_failed = updated_result.get("fields_failed", [])
        
        for mod in modifications:
            field_id = mod["field_id"]
            # 检查是否在 filled 中
            is_filled = any(f.get("field_id") == field_id for f in updated_filled)
            if is_filled:
                applied.append({
                    "field_id": field_id,
                    "new_value": mod["new_value"],
                    "status": "applied"
                })
            else:
                failed.append({
                    "field_id": field_id,
                    "error": "填写失败"
                })
        
        # 6. 标记 review 已应用
        if applied:
            self.db.mark_review_applied(self.apply_record_id)
        
        return {
            "success": len(failed) == 0,
            "applied": applied,
            "failed": failed
        }


# 便捷函数
async def run_filling(db, apply_record_id: int, payload_path: Optional[str] = None) -> Dict:
    """执行填写"""
    executor = FillingExecutor(db, apply_record_id)
    return await executor.execute_filling(payload_path)


async def run_iteration(db, apply_record_id: int, failed_field_ids: List[str]) -> Dict:
    """执行定向迭代"""
    executor = FillingExecutor(db, apply_record_id)
    return await executor.execute_iteration(failed_field_ids)


async def apply_modifications(db, apply_record_id: int, modifications: List[Dict]) -> Dict:
    """应用用户修改"""
    executor = FillingExecutor(db, apply_record_id)
    return await executor.apply_modifications(modifications)

