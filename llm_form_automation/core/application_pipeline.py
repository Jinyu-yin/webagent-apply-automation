"""
申请处理管道 - 整合所有步骤的主控制器

流程：
1. 创建申请 → 状态: analyzing
2. 预分析/爬取字段 → 存入 university_fields
3. 字段比对 → 状态: pending_user_input (如有缺失)
4. 用户补充 → 状态: ready
5. 生成 Payload → 状态: filling
6. 自动填写 → 支持断点续传
7. 完成 → 状态: completed / 保存快照
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from llm_form_automation.core.field_extractor import FieldExtractor
from llm_form_automation.core.field_matcher import FieldMatcher, MappingReport


class ApplicationStatus(Enum):
    """申请状态"""
    CREATED = "created"                      # 刚创建
    ANALYZING = "analyzing"                  # 正在分析字段
    PENDING_USER_INPUT = "pending_user_input"  # 等待用户补充
    READY = "ready"                          # 准备就绪
    FILLING = "filling"                      # 正在填写
    PAUSED = "paused"                        # 暂停（遇到问题）
    COMPLETED = "completed"                  # 完成
    FAILED = "failed"                        # 失败


@dataclass
class PipelineContext:
    """管道上下文"""
    apply_record_id: int
    user_id: str
    uni_id: str
    prog_id: str
    process_id: Optional[str] = None
    status: ApplicationStatus = ApplicationStatus.CREATED
    current_page: int = 0
    total_pages: int = 0
    fields_total: int = 0
    fields_filled: int = 0
    payload: Optional[Dict] = None
    match_report: Optional[MappingReport] = None
    error_message: Optional[str] = None


class ApplicationPipeline:
    """申请处理管道"""
    
    def __init__(self, db):
        """
        Args:
            db: SupabaseDB 实例
        """
        self.db = db
        self.field_extractor = FieldExtractor(db)
        self.field_matcher = FieldMatcher(db)
        self.context: Optional[PipelineContext] = None
        
        # 事件回调
        self.on_status_change: Optional[Callable[[ApplicationStatus, str], None]] = None
        self.on_missing_field: Optional[Callable[[Dict], None]] = None
        self.on_progress: Optional[Callable[[int, int, int, int], None]] = None
    
    def initialize(self, apply_record_id: int) -> PipelineContext:
        """
        初始化申请管道
        
        Args:
            apply_record_id: apply_record 表的 ID
            
        Returns:
            PipelineContext
        """
        # 获取申请记录
        apply_record = self.db.get_apply_record(apply_record_id)
        if not apply_record:
            raise ValueError(f"Apply record {apply_record_id} not found")
        
        user_id = apply_record.get("user_id") or ""
        prog_id = apply_record.get("prog_id") or ""
        
        # 创建/获取 application_process 记录
        process = self.db.initialize_application_process(apply_record_id)
        
        # 获取 uni_id - 优先使用 application_process 中的值
        uni_id = process.get("uni_id") or ""
        
        # 如果 application_process 中没有 uni_id，尝试从 program 表获取
        if not uni_id and prog_id:
            program = self.db.get_program(prog_id)
            if program:
                uni_id = program.get("uni_id") or ""
        
        self.context = PipelineContext(
            apply_record_id=apply_record_id,
            user_id=user_id,
            uni_id=uni_id,
            prog_id=prog_id,
            process_id=process.get("id"),
            status=ApplicationStatus(process.get("process_status", "created")),
            current_page=process.get("current_page", 0),
            total_pages=process.get("total_pages", 0),
        )
        
        return self.context
    
    def _update_status(self, status: ApplicationStatus, message: str = ""):
        """更新状态"""
        if not self.context:
            return
        
        self.context.status = status
        self.context.error_message = message if status == ApplicationStatus.FAILED else None
        
        # 更新数据库
        self.db.update_application_process_status(
            self.context.process_id,
            status.value,
            message
        )
        
        # 触发回调
        if self.on_status_change:
            self.on_status_change(status, message)
    
    def _update_progress(self):
        """更新进度"""
        if not self.context:
            return
        
        self.db.update_application_progress(
            self.context.process_id,
            current_page=self.context.current_page,
            total_pages=self.context.total_pages,
            fields_total=self.context.fields_total,
            fields_filled=self.context.fields_filled,
        )
        
        if self.on_progress:
            self.on_progress(
                self.context.current_page,
                self.context.total_pages,
                self.context.fields_filled,
                self.context.fields_total,
            )
    
    # ==================== 阶段 1: 字段分析 ====================
    
    def analyze_fields_from_html(self, html_files: List[Path]) -> int:
        """
        从 HTML 文件分析字段
        
        Args:
            html_files: HTML 文件列表 (按页面顺序)
            
        Returns:
            提取的字段总数
        """
        if not self.context:
            raise ValueError("Pipeline not initialized")
        
        self._update_status(ApplicationStatus.ANALYZING, "正在分析表单字段...")
        
        total_fields = 0
        
        for page_num, html_path in enumerate(html_files, start=1):
            try:
                with open(html_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                fields = self.field_extractor.extract_from_html(html_content, page_num)
                total_fields += len(fields)
                
                print(f"📄 Page {page_num}: 提取 {len(fields)} 个字段")
                
            except Exception as e:
                print(f"⚠️ 解析 {html_path} 失败: {e}")
        
        # 保存到数据库
        if self.context.uni_id:
            saved = self.field_extractor.save_to_database(self.context.uni_id)
            print(f"💾 保存 {saved} 个字段到数据库")
        
        self.context.total_pages = len(html_files)
        self.context.fields_total = total_fields
        
        return total_fields
    
    # ==================== 阶段 2: 字段比对 ====================
    
    async def match_fields(self) -> MappingReport:
        """
        比对用户信息和学校字段
        
        Returns:
            MappingReport
        """
        if not self.context:
            raise ValueError("Pipeline not initialized")
        
        # 获取用户信息
        user_info = self.db.get_user_application_info(self.context.user_id) or {}
        
        # 获取学校字段
        university_fields = self.db.get_university_fields(self.context.uni_id)
        
        # 比对 (async)
        report = await self.field_matcher.match_fields(user_info, university_fields)
        self.context.match_report = report
        
        # 保存需要用户提供的字段
        if report.needs_user:
            self.field_matcher.save_needs_user_fields(
                self.context.apply_record_id,
                report
            )
            
            # 更新状态
            self._update_status(
                ApplicationStatus.PENDING_USER_INPUT,
                f"需要补充 {len(report.needs_user)} 个字段"
            )
        else:
            self._update_status(ApplicationStatus.READY, "字段匹配完成，可以开始填写")
        
        return report
    
    # ==================== 阶段 3: 用户补充 ====================
    
    def get_missing_fields(self) -> List[Dict]:
        """
        获取待补充的缺失字段
        
        Returns:
            缺失字段列表
        """
        if not self.context:
            raise ValueError("Pipeline not initialized")
        
        return self.db.get_unresolved_missing_fields(self.context.apply_record_id)
    
    def resolve_missing_field(self, field_id: str, value: str) -> bool:
        """
        解决一个缺失字段
        
        Args:
            field_id: 字段 ID
            value: 用户提供的值
            
        Returns:
            是否成功
        """
        if not self.context:
            raise ValueError("Pipeline not initialized")
        
        try:
            self.db.resolve_missing_field(
                self.context.apply_record_id,
                field_id,
                value
            )
            return True
        except Exception as e:
            print(f"❌ 解决字段 {field_id} 失败: {e}")
            return False
    
    def check_ready(self) -> bool:
        """
        检查是否所有必填字段都已补充
        
        Returns:
            是否准备就绪
        """
        if not self.context:
            return False
        
        missing = self.db.get_unresolved_missing_fields(self.context.apply_record_id)
        required_missing = [f for f in missing if f.get("priority") == "required"]
        
        if not required_missing:
            self._update_status(ApplicationStatus.READY, "所有必填字段已补充")
            return True
        
        return False
    
    # ==================== 阶段 4: 生成 Payload ====================
    
    def generate_payload(self) -> Dict[str, Any]:
        """
        生成填表 Payload
        
        Returns:
            Payload 字典
        """
        if not self.context:
            raise ValueError("Pipeline not initialized")
        
        if not self.context.match_report:
            raise ValueError("需要先调用 match_fields()")
        
        # 获取用户补充的数据
        resolved_fields = self.db.get_resolved_missing_fields(self.context.apply_record_id)
        user_provided = {f["field_id"]: f["resolved_value"] for f in resolved_fields}
        
        # 生成 payload
        payload = self.field_matcher.generate_payload(
            self.context.match_report,
            user_provided
        )
        self.context.payload = payload
        
        # 更新状态
        self._update_status(ApplicationStatus.FILLING, "Payload 已生成，开始填写")
        
        return payload
    
    # ==================== 阶段 5: 断点保存/恢复 ====================
    
    def save_checkpoint(
        self,
        page_number: int,
        page_url: str,
        filled_fields: List[str],
        pending_fields: List[str],
        cookies: Optional[str] = None
    ):
        """
        保存断点
        
        Args:
            page_number: 当前页码
            page_url: 当前页面 URL
            filled_fields: 已填写的字段 ID 列表
            pending_fields: 待填写的字段 ID 列表
            cookies: 浏览器 cookies (可选)
        """
        if not self.context:
            return
        
        checkpoint_data = {
            "page_number": page_number,
            "page_url": page_url,
            "filled_fields": filled_fields,
            "pending_fields": pending_fields,
            "cookies": cookies,
            "saved_at": datetime.now().isoformat(),
        }
        
        self.context.current_page = page_number
        self.context.fields_filled = len(filled_fields)
        
        self.db.save_checkpoint(
            self.context.process_id,
            checkpoint_data,
            current_page=page_number,
            fields_filled=len(filled_fields),
        )
        
        self._update_progress()
    
    def load_checkpoint(self) -> Optional[Dict]:
        """
        加载断点
        
        Returns:
            断点数据 (如果有)
        """
        if not self.context:
            return None
        
        process = self.db.get_application_process(self.context.apply_record_id)
        if not process:
            return None
        
        checkpoint = process.get("checkpoint_data", {})
        if checkpoint:
            self.context.current_page = checkpoint.get("page_number", 0)
            self.context.fields_filled = len(checkpoint.get("filled_fields", []))
        
        return checkpoint
    
    # ==================== 阶段 6: 填写过程中发现缺失 ====================
    
    def add_discovered_missing_field(
        self,
        field_id: str,
        field_label: Optional[str],
        field_type: str,
        page_number: int,
        hint: Optional[str] = None
    ):
        """
        添加填写过程中发现的缺失字段
        
        Args:
            field_id: 字段 ID
            field_label: 字段标签
            field_type: 字段类型
            page_number: 页码
            hint: 提示信息
        """
        if not self.context:
            return
        
        self.db.add_missing_field(
            apply_record_id=self.context.apply_record_id,
            process_id=self.context.process_id,
            field_id=field_id,
            field_label=field_label,
            field_type=field_type,
            page_number=page_number,
            reason="discovered_during_fill",
            priority="required",
            hint=hint or f"填写过程中发现缺失: {field_label or field_id}",
        )
        
        # 更新状态为暂停
        self._update_status(
            ApplicationStatus.PAUSED,
            f"发现缺失字段: {field_label or field_id}"
        )
        
        # 触发回调
        if self.on_missing_field:
            self.on_missing_field({
                "field_id": field_id,
                "field_label": field_label,
                "field_type": field_type,
                "page_number": page_number,
                "hint": hint,
            })
    
    # ==================== 阶段 7: 完成 ====================
    
    def complete(self, save_snapshot: bool = True):
        """
        标记申请完成
        
        Args:
            save_snapshot: 是否保存快照
        """
        if not self.context:
            return
        
        self._update_status(ApplicationStatus.COMPLETED, "申请填写完成")
        
        # 更新 apply_record
        self.db.update_apply_record_status(self.context.apply_record_id, "已完成")
        
        # 保存快照
        if save_snapshot and self.context.payload:
            self._save_snapshot()
    
    def _save_snapshot(self):
        """保存快照到数据库"""
        if not self.context:
            return
        
        # 获取所有解决的字段
        resolved_fields = self.db.get_resolved_missing_fields(self.context.apply_record_id)
        
        snapshot_data = {
            "payload": self.context.payload,
            "resolved_fields": resolved_fields,
            "completed_at": datetime.now().isoformat(),
            "pages": self.context.total_pages,
            "fields_total": self.context.fields_total,
        }
        
        # 这里可以存入一个 snapshot 表或者作为 checkpoint_data 的一部分
        self.db.save_checkpoint(
            self.context.process_id,
            {"final_snapshot": snapshot_data},
        )
    
    def fail(self, error_message: str):
        """
        标记申请失败
        
        Args:
            error_message: 错误信息
        """
        self._update_status(ApplicationStatus.FAILED, error_message)


# ==================== 便捷函数 ====================

def create_pipeline(db, apply_record_id: int) -> ApplicationPipeline:
    """
    创建并初始化管道
    
    Args:
        db: SupabaseDB 实例
        apply_record_id: 申请记录 ID
        
    Returns:
        初始化后的 ApplicationPipeline
    """
    pipeline = ApplicationPipeline(db)
    pipeline.initialize(apply_record_id)
    return pipeline


if __name__ == "__main__":
    print("Application Pipeline Module")
    print("=" * 50)
    print("""
使用方式:

1. 初始化管道:
   pipeline = create_pipeline(db, apply_record_id)

2. 分析字段:
   pipeline.analyze_fields_from_html([html_file1, html_file2, ...])

3. 字段比对:
   report = pipeline.match_fields()
   if report.missing_required:
       # 通知前端补充

4. 用户补充后:
   pipeline.resolve_missing_field(field_id, value)
   pipeline.check_ready()

5. 生成 Payload:
   payload = pipeline.generate_payload()

6. 填写过程:
   # 定期保存断点
   pipeline.save_checkpoint(page, url, filled, pending)
   
   # 发现新缺失
   pipeline.add_discovered_missing_field(...)

7. 完成:
   pipeline.complete()
""")

