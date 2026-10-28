"""
表单填充服务

核心职责：
1. 协调填充流程
2. 从 application_payload 表读取数据
3. 调用 llm_form_automation 中的 LLMFormFiller 执行填充
4. 记录填充结果

直接集成 llm_form_automation/form_filler/form_filler.py 中的 LLMFormFiller
"""

import asyncio
import json
import tempfile
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime

from backend.db import get_db
from backend.config import settings
from backend.logger import get_service_logger
from backend.dao import (
    ApplicationPayloadDao,
    ApplyRecordDao,
    ApplicationProcessDao,
)

logger = get_service_logger("FormFillService")


class DatabaseAdapter:
    """
    数据库适配器

    将 LLMFormFiller 期望的接口映射到 backend/dao 的实际方法
    """

    def __init__(self, db, apply_record_id: int):
        self.db = db
        self.apply_record_id = apply_record_id
        self._fill_result = {
            "fields_filled": [],
            "fields_failed": [],
            "fields_no_value": []
        }

    def update_process_progress(
        self,
        apply_record_id: int,
        current_page: int,
        fields_filled: int,
        fields_total: int
    ):
        """更新填充进度"""
        try:
            self.db.table("application_process").update({
                "current_page": current_page,
                "fields_filled": fields_filled,
            }).eq("apply_record_id", apply_record_id).execute()
            logger.info(f"进度更新: 第{current_page}页, 已填{fields_filled}/{fields_total}")
        except Exception as e:
            logger.warning(f"更新进度失败: {e}")

    def save_checkpoint(self, apply_record_id: int, checkpoint_data: Dict):
        """保存检查点"""
        try:
            # 将检查点数据保存到 application_process 的 checkpoint 字段
            self.db.table("application_process").update({
                "checkpoint": checkpoint_data
            }).eq("apply_record_id", apply_record_id).execute()
            logger.info(f"检查点已保存: 第{checkpoint_data.get('page_number')}页")
        except Exception as e:
            logger.warning(f"保存检查点失败: {e}")

    def update_fill_result(
        self,
        apply_record_id: int,
        fields_filled: List[Dict],
        fields_no_value: List[Dict],
        fields_failed: List[Dict],
        append: bool = False
    ):
        """更新填充结果"""
        try:
            if append:
                # 追加模式：累加结果
                self._fill_result["fields_filled"].extend(fields_filled)
                self._fill_result["fields_failed"].extend(fields_failed)
                self._fill_result["fields_no_value"].extend(fields_no_value)
            else:
                # 覆盖模式
                self._fill_result = {
                    "fields_filled": fields_filled,
                    "fields_failed": fields_failed,
                    "fields_no_value": fields_no_value
                }

            # 保存到数据库
            self.db.table("application_process").update({
                "fill_result": self._fill_result,
                "fields_filled": len(self._fill_result["fields_filled"])
            }).eq("apply_record_id", apply_record_id).execute()

            logger.info(
                f"填充结果已更新: 成功{len(self._fill_result['fields_filled'])}, "
                f"失败{len(self._fill_result['fields_failed'])}, "
                f"无值{len(self._fill_result['fields_no_value'])}"
            )
        except Exception as e:
            logger.warning(f"更新填充结果失败: {e}")

    def add_fill_error(self, apply_record_id: int, page_num: int, error_type: str, message: str):
        """添加填充错误记录"""
        logger.warning(f"填充错误 [第{page_num}页] {error_type}: {message}")


class FormFillService:
    """
    表单填充服务

    负责：
    - 从 application_payload 表读取填充数据
    - 调用 LLMFormFiller 执行浏览器自动化填充
    - 记录填充结果
    """

    def __init__(self):
        self.db = get_db()

    # ==================== Payload 转换 ====================

    def _prepare_payload_file(self, apply_record_id: int) -> Optional[Path]:
        """
        将数据库中的 payload 转换为 LLMFormFiller 需要的 JSON 文件格式

        PayloadManager 期望的格式:
        {
            "fields": {
                "field_id": {"value": "xxx", "label": "xxx", "source": "xxx"}
            },
            "data": {},  // 旧格式兼容
            "metadata": {}
        }

        Returns:
            临时 payload 文件路径
        """
        # 获取 payload 数据
        payload_list = ApplicationPayloadDao.get_by_apply_id(self.db, apply_record_id)
        if not payload_list:
            return None

        # 转换为 LLMFormFiller/PayloadManager 需要的格式
        fields_dict = {}
        for item in payload_list:
            field_id = item.get('field_id', '')
            if field_id:
                fields_dict[field_id] = {
                    "value": item.get('value', ''),
                    "label": item.get('field_label', ''),
                    "source": item.get('source', 'payload'),
                    "type": item.get('field_type', 'text'),
                }

        # PayloadManager 期望的完整格式
        payload_data = {
            "fields": fields_dict,
            "data": {},  # 旧格式兼容，留空
            "metadata": {
                "apply_record_id": apply_record_id,
                "fields_count": len(fields_dict),
                "generated_at": datetime.now().isoformat()
            }
        }

        # 写入临时文件
        temp_file = Path(tempfile.mktemp(suffix='.json', prefix='payload_'))
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(payload_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Payload 文件已生成: {temp_file} ({len(fields_dict)} 个字段)")
        return temp_file

    # ==================== 全量填充 ====================

    async def fill_form(
        self,
        apply_record_id: int,
        pages: Optional[List[int]] = None,
        headless: bool = True
    ) -> Dict[str, Any]:
        """
        执行表单填充（调用 LLMFormFiller）

        Args:
            apply_record_id: 申请记录 ID
            pages: 要填充的页码列表，None 表示全部
            headless: 是否无头模式

        Returns:
            {
                "success": bool,
                "filled": int,
                "failed": int,
                "no_value": int,
                "message": str,
                "details": {...}
            }
        """
        # 1. 获取申请记录
        record = ApplyRecordDao.get_by_id(self.db, apply_record_id)
        if not record:
            return {"success": False, "error": "申请记录不存在"}

        url = record.get('application_url', '')
        email = record.get('email', '')
        password = record.get('password', '')

        # 2. 准备 Payload 文件
        payload_file = self._prepare_payload_file(apply_record_id)
        if not payload_file:
            return {"success": False, "error": "Payload 为空，请先执行分析"}

        # 3. 调用 LLMFormFiller
        try:
            result = await self._execute_fill_with_llm_filler(
                apply_record_id=apply_record_id,
                url=url,
                email=email,
                password=password,
                payload_file=payload_file,
                pages=pages,
                headless=headless
            )
            return result
        except Exception as e:
            logger.error(f"填充执行失败: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # 清理临时文件
            if payload_file and payload_file.exists():
                payload_file.unlink()

    async def _execute_fill_with_llm_filler(
        self,
        apply_record_id: int,
        url: str,
        email: str,
        password: str,
        payload_file: Path,
        pages: Optional[List[int]],
        headless: bool
    ) -> Dict[str, Any]:
        """使用 LLMFormFiller 执行填充"""
        from playwright.async_api import async_playwright  # type: ignore
        from llm_form_automation.form_filler.form_filler import LLMFormFiller
        from llm_form_automation.form_filler.login_handler import LoginHandler

        # 初始化 LLMFormFiller
        filler = LLMFormFiller(
            payload_path=payload_file,
            start_url=url,
            output_dir=Path("logs/fill_reports")
        )

        # 设置数据库连接（使用适配器）
        db_adapter = DatabaseAdapter(self.db, apply_record_id)
        filler.set_db_connection(db_adapter, apply_record_id)

        # 统计
        total_filled = 0
        total_failed = 0
        total_no_value = 0
        all_reports = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # 1. 打开页面
                logger.info(f"打开页面: {url}")
                await page.goto(url, timeout=60000)
                await asyncio.sleep(2)

                # 2. 登录
                logger.info(f"尝试登录: {email}")
                login_success = await LoginHandler.login_if_needed(page, email, password)

                if login_success:
                    logger.info("登录成功")
                    await asyncio.sleep(3)
                else:
                    logger.warning("登录可能失败，继续尝试填充")

                # 3. 确定要填充的页面
                max_pages = pages[-1] if pages else settings.max_form_pages
                page_list = pages or list(range(1, max_pages + 1))

                # 4. 遍历页面填充
                for page_num in page_list:
                    logger.info(f"开始填充第 {page_num} 页")

                    # 调用 LLMFormFiller 的页面填充方法
                    report = await filler.fill_page_from_payload(page, page_num)
                    all_reports.append(report)

                    # 统计
                    total_filled += len(report.get("fields_filled", []))
                    total_failed += len(report.get("fields_failed", []))
                    total_no_value += len(report.get("fields_no_value", []))

                    # 点击下一页
                    if page_num < max_pages:
                        clicked = await filler.click_next_page(page)
                        if not clicked:
                            logger.info(f"无法继续到下一页，停止在第 {page_num} 页")
                            break
                        await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"填充过程异常: {e}")
                raise
            finally:
                await browser.close()

        # 保存填充报告
        report_path = filler.save_fill_report({
            "apply_record_id": apply_record_id,
            "url": url,
            "timestamp": datetime.now().isoformat(),
            "pages": all_reports,
            "summary": {
                "total_filled": total_filled,
                "total_failed": total_failed,
                "total_no_value": total_no_value,
            }
        })

        # 判断是否成功
        is_success = total_filled > 0 and (total_failed == 0 or total_filled >= total_failed)

        return {
            "success": is_success,
            "filled": total_filled,
            "failed": total_failed,
            "no_value": total_no_value,
            "message": f"填充完成: 成功{total_filled}, 失败{total_failed}, 无值{total_no_value}",
            "report_path": report_path,
            "details": {
                "fields_filled": [f for r in all_reports for f in r.get("fields_filled", [])],
                "fields_failed": [f for r in all_reports for f in r.get("fields_failed", [])],
                "fields_no_value": [f for r in all_reports for f in r.get("fields_no_value", [])],
            }
        }

    # ==================== 定向填充 ====================

    async def fill_targeted_fields(
        self,
        apply_record_id: int,
        field_ids: List[str],
        headless: bool = True
    ) -> Dict[str, Any]:
        """
        定向填充指定字段（调用 LLMFormFiller）

        Args:
            apply_record_id: 申请记录 ID
            field_ids: 要填充的字段 ID 列表
            headless: 是否无头模式
        """
        if not field_ids:
            return {
                "success": True,
                "targeted": 0,
                "newly_filled": 0,
                "still_failed": 0,
                "message": "没有需要重填的字段"
            }

        # 获取申请记录
        record = ApplyRecordDao.get_by_id(self.db, apply_record_id)
        if not record:
            return {"success": False, "error": "申请记录不存在"}

        url = record.get('application_url', '')
        email = record.get('email', '')
        password = record.get('password', '')

        # 准备只包含指定字段的 Payload
        payload_list = ApplicationPayloadDao.get_by_apply_id(self.db, apply_record_id)
        fields_dict = {}
        for item in payload_list:
            field_id = item.get('field_id', '')
            if field_id in field_ids:
                fields_dict[field_id] = {
                    "value": item.get('value', ''),
                    "label": item.get('field_label', ''),
                    "source": item.get('source', 'payload'),
                    "type": item.get('field_type', 'text'),
                }

        if not fields_dict:
            return {
                "success": True,
                "targeted": 0,
                "newly_filled": 0,
                "message": "指定字段没有 payload 数据"
            }

        # PayloadManager 期望的完整格式
        payload_data = {
            "fields": fields_dict,
            "data": {},
            "metadata": {
                "apply_record_id": apply_record_id,
                "fields_count": len(fields_dict),
                "targeted_fill": True
            }
        }

        # 写入临时文件
        temp_file = Path(tempfile.mktemp(suffix='.json', prefix='targeted_payload_'))
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(payload_data, f, ensure_ascii=False, indent=2)

        try:
            result = await self._execute_targeted_fill(
                apply_record_id=apply_record_id,
                url=url,
                email=email,
                password=password,
                payload_file=temp_file,
                field_ids=field_ids,
                headless=headless
            )
            return result
        finally:
            if temp_file.exists():
                temp_file.unlink()

    async def _execute_targeted_fill(
        self,
        apply_record_id: int,
        url: str,
        email: str,
        password: str,
        payload_file: Path,
        field_ids: List[str],
        headless: bool
    ) -> Dict[str, Any]:
        """执行定向填充"""
        from playwright.async_api import async_playwright  # type: ignore
        from llm_form_automation.form_filler.form_filler import LLMFormFiller
        from llm_form_automation.form_filler.login_handler import LoginHandler

        # 初始化 LLMFormFiller
        filler = LLMFormFiller(
            payload_path=payload_file,
            start_url=url,
            output_dir=Path("logs/fill_reports")
        )
        db_adapter = DatabaseAdapter(self.db, apply_record_id)
        filler.set_db_connection(db_adapter, apply_record_id)

        filled_count = 0
        failed_count = 0
        results = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()

            try:
                # 登录
                await page.goto(url, timeout=60000)
                await asyncio.sleep(2)

                await LoginHandler.login_if_needed(page, email, password)
                await asyncio.sleep(3)

                # 遍历页面查找并填充指定字段
                for page_num in range(1, settings.max_form_pages + 1):
                    # 提取当前页面字段
                    page_fields = await filler.extract_page_fields(page)

                    # 查找需要填充的字段
                    for field in page_fields:
                        field_id = field.get('id', '') or field.get('name', '')
                        if field_id not in field_ids:
                            continue

                        # 匹配 payload
                        value, source = filler.match_field_to_payload(field)
                        if value:
                            fill_result = await filler.fill_field(page, field, value)
                            if fill_result.get("success"):
                                filled_count += 1
                                results.append({
                                    "field_id": field_id,
                                    "value": value,
                                    "status": "filled"
                                })
                            else:
                                failed_count += 1
                                results.append({
                                    "field_id": field_id,
                                    "error": fill_result.get("error"),
                                    "status": "failed"
                                })

                    # 点击下一页
                    clicked = await filler.click_next_page(page)
                    if not clicked:
                        break
                    await asyncio.sleep(2)

            finally:
                await browser.close()

        return {
            "success": filled_count > 0,
            "targeted": len(field_ids),
            "newly_filled": filled_count,
            "still_failed": failed_count,
            "results": results,
            "message": f"定向填充完成: 目标{len(field_ids)}, 成功{filled_count}, 失败{failed_count}"
        }

    # ==================== 失败字段重填 ====================

    async def fill_failed_fields(
        self,
        apply_record_id: int,
        headless: bool = True
    ) -> Dict[str, Any]:
        """重试填充失败的字段"""
        # 获取失败字段
        fill_result = ApplicationProcessDao.get_fill_result(self.db, apply_record_id)
        failed_fields = fill_result.get("fields_failed", [])

        if not failed_fields:
            return {
                "success": True,
                "targeted": 0,
                "newly_filled": 0,
                "message": "没有失败的字段需要重填"
            }

        field_ids = [f.get("field_id") for f in failed_fields if f.get("field_id")]
        return await self.fill_targeted_fields(apply_record_id, field_ids, headless)
