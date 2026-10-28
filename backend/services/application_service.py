"""
申请服务层

核心职责：
1. 状态判断 - 根据当前状态决定下一步操作
2. 业务协调 - 调用不同的算法/服务
3. 事务管理 - 保证数据一致性
"""

import asyncio
from typing import Any, Dict, List, Optional
from enum import Enum

from backend.db import get_db
from backend.config import settings
from backend.logger import get_service_logger
from backend.dao import (
    ApplyRecordDao,
    ApplicationProcessDao,
    UniversityFieldsDao,
    MissingFieldsDao,
    UserApplicationInfoDao,
    ApplicationPayloadDao
)

logger = get_service_logger("ApplicationService")


class ProcessStatus(str, Enum):
    """申请状态枚举"""
    CREATED = 'created'           # 刚创建
    ANALYZING = 'analyzing'       # 分析中（爬取字段）
    NEED_INPUT = 'need_input'     # 等待用户补充信息
    READY_TO_FILL = 'ready'       # 准备填写
    FILLING = 'filling'           # 填写中
    PENDING_REVIEW = 'pending'    # 等待用户审核
    COMPLETED = 'completed'       # 完成
    FAILED = 'failed'             # 失败


class ApplicationService:
    """
    申请业务服务

    负责：
    - 状态流转控制
    - 业务逻辑协调
    - 直接使用 DAO 层操作数据库
    - 不直接执行算法（通过 FormFillService）
    """

    def __init__(self):
        self.db = get_db()

    # ==================== 基础操作 ====================

    def get_record(self, apply_record_id: int) -> Optional[Dict]:
        """获取申请记录"""
        return ApplyRecordDao.get_by_id(self.db, apply_record_id)

    def get_process(self, apply_record_id: int) -> Optional[Dict]:
        """获取流程信息"""
        return ApplicationProcessDao.get_by_apply_id(self.db, apply_record_id)

    def get_process_status(self, apply_record_id: int) -> str:
        """获取流程状态"""
        process = self.get_process(apply_record_id)
        return process.get('process_status', 'created') if process else 'created'

    def update_process_status(self, apply_record_id: int, status: ProcessStatus, message: str = '') -> bool:
        """更新状态"""
        status_str = status.value if isinstance(status, ProcessStatus) else status
        return ApplicationProcessDao.update_status(self.db, apply_record_id, status_str, message)

    def get_university_fields(self, apply_record_id_or_uni_id) -> List[Dict]:
        """
        获取学校字段

        Args:
            apply_record_id_or_uni_id: 可以是 apply_record_id (int) 或 uni_id (str)
        """
        if isinstance(apply_record_id_or_uni_id, int):
            # 通过 apply_record_id 获取
            process = self.get_process(apply_record_id_or_uni_id)
            if not process:
                return []
            uni_id = process.get('uni_id', '')
            if not uni_id:
                return []
            return UniversityFieldsDao.get_by_uni_id(self.db, uni_id)
        else:
            # 直接通过 uni_id 获取
            return UniversityFieldsDao.get_by_uni_id(self.db, apply_record_id_or_uni_id)

    def save_university_fields(self, uni_id: str, fields: List[Dict]) -> int:
        """保存学校字段"""
        return UniversityFieldsDao.save(self.db, uni_id, fields)

    def get_missing_fields(self, apply_record_id: int) -> List[Dict]:
        """获取缺失字段"""
        return MissingFieldsDao.get_by_apply_id(self.db, apply_record_id, only_unresolved=True)

    def save_missing_fields(self, apply_record_id: int, fields: List[Dict]) -> int:
        """保存缺失字段"""
        return MissingFieldsDao.add_batch(self.db, apply_record_id, fields)

    def get_user_info_by_apply_id(self, apply_record_id: int) -> Optional[Dict]:
        """获取用户信息（通过 apply_record 获取 user_id，再查询用户信息）"""
        # 先获取申请记录以获取 user_id
        apply_record = ApplyRecordDao.get_by_id(self.db, apply_record_id)
        if not apply_record:
            return None
        user_id = apply_record.get('user_id')
        if not user_id:
            return None
        return UserApplicationInfoDao.get_by_user_id(self.db, user_id)

    def get_fill_result(self, apply_record_id: int) -> Dict:
        """获取填充结果"""
        return ApplicationProcessDao.get_fill_result(self.db, apply_record_id)

    # ==================== 状态查询 ====================

    def get_status(self, apply_record_id: int) -> Dict[str, Any]:
        """
        获取申请当前状态

        返回:
        {
            "status": "ready",
            "message": "准备填写",
            "progress": {"current_page": 3, "filled": 17, "total": 29},
            "next_action": "wait"
        }
        """
        process = self.get_process(apply_record_id)

        if not process:
            return {
                "status": "not_found",
                "message": "流程记录不存在",
                "progress": {},
                "next_action": "start"
            }

        status = process.get('process_status', 'created')

        return {
            "status": status,
            "message": process.get('status_message', ''),
            "progress": {
                "current_page": process.get('current_page', 0),
                "filled": process.get('fields_filled', 0),
                "total": process.get('fields_total', 0)
            },
            "next_action": self._get_next_action(status)
        }

    def _get_next_action(self, status: str) -> Optional[str]:
        """根据状态返回用户需要的下一步操作"""
        action_map: Dict[str, Optional[str]] = {
            ProcessStatus.CREATED.value: "start",
            ProcessStatus.ANALYZING.value: "wait",
            ProcessStatus.NEED_INPUT.value: "provide_input",
            ProcessStatus.READY_TO_FILL.value: "wait",
            ProcessStatus.FILLING.value: "wait",
            ProcessStatus.PENDING_REVIEW.value: "review",
            ProcessStatus.COMPLETED.value: None,
            ProcessStatus.FAILED.value: "retry"
        }
        return action_map.get(status, "wait")

    # ==================== 状态流转 ====================

    def start(self, apply_record_id: int) -> Dict[str, Any]:
        """
        启动申请流程

        状态: CREATED -> ANALYZING
        """
        status = self.get_process_status(apply_record_id)

        if status != ProcessStatus.CREATED.value:
            return {"success": False, "error": f"当前状态 {status} 无法启动"}

        # 获取申请记录
        record = self.get_record(apply_record_id)
        if not record:
            return {"success": False, "error": "申请记录不存在"}

        # 提取学校 ID
        url = record.get('application_url', '')
        uni_id = self._extract_uni_id(url)

        # 创建或更新流程记录
        process = self.get_process(apply_record_id)
        if not process:
            ApplicationProcessDao.create(self.db, apply_record_id, uni_id)
        else:
            ApplicationProcessDao.update_uni_id(self.db, apply_record_id, uni_id)

        # 更新状态
        self.update_process_status(apply_record_id, ProcessStatus.ANALYZING, "开始分析学校表单")

        return {
            "success": True,
            "status": ProcessStatus.ANALYZING.value,
            "uni_id": uni_id,
            "message": "已启动，进入分析阶段"
        }

    async def run_analysis(self, apply_record_id: int) -> Dict[str, Any]:
        """
        执行分析阶段

        1. 爬取学校页面
        2. 提取表单字段
        3. 与用户信息匹配
        4. 生成缺失字段列表

        状态: ANALYZING -> NEED_INPUT 或 READY
        """
        record = self.get_record(apply_record_id)
        if not record:
            return {"success": False, "error": "申请记录不存在"}

        url = record.get('application_url', '')
        email = record.get('email', '')
        password = record.get('password', '')
        uni_id = self._extract_uni_id(url)

        try:
            # 1. 检查是否已有学校字段
            existing_fields = self.get_university_fields(uni_id)

            if not existing_fields:
                # 调用爬取算法
                fields = await self._crawl_and_extract(url, email, password, uni_id)

                if not fields:
                    self.update_process_status(
                        apply_record_id,
                        ProcessStatus.FAILED,
                        "无法提取表单字段"
                    )
                    return {"success": False, "error": "无法提取表单字段"}

                # 保存字段
                self.save_university_fields(uni_id, fields)
            else:
                fields = existing_fields

            # 2. 获取用户信息
            user_info = self.get_user_info_by_apply_id(apply_record_id)

            # 3. 使用 LLM 智能匹配字段
            missing_fields, matched_fields = await self._find_missing_fields(fields, user_info)

            # 4. 把匹配成功的字段写入 payload（字段名和 university_fields 保持一致）
            matched_count = 0
            if matched_fields:
                # 构建 field_id -> field_info 映射
                field_map = {f.get('field_id'): f for f in fields}

                for field_id, value in matched_fields.items():
                    if value and field_id in field_map:
                        field_info = field_map[field_id]
                        ApplicationPayloadDao.upsert(
                            db=self.db,
                            apply_record_id=apply_record_id,
                            field_id=field_id,  # 使用 university_fields 的 field_id
                            value=str(value),
                            source='llm_matched',
                            field_label=field_info.get('field_label', ''),
                            field_type=field_info.get('field_type', 'text'),
                            options=field_info.get('options')
                        )
                        matched_count += 1

                logger.info(f"已将 {matched_count} 个匹配字段写入 payload")

            if missing_fields:
                # 保存缺失字段
                saved_missing = self.save_missing_fields(apply_record_id, missing_fields)
                self.update_process_status(
                    apply_record_id,
                    ProcessStatus.NEED_INPUT,
                    f"发现 {len(missing_fields)} 个缺失字段"
                )
                return {
                    "success": True,
                    "status": ProcessStatus.NEED_INPUT.value,
                    "operations": {
                        "university_fields": len(fields),
                        "payload_added": matched_count,
                        "missing_added": saved_missing,
                    },
                    "fields_count": len(fields),
                    "matched_count": matched_count,
                    "missing_count": len(missing_fields),
                    "message": f"学校字段: {len(fields)} | Payload 写入: {matched_count} (source=llm_matched) | Missing 写入: {saved_missing} | 状态: need_input"
                }
            else:
                self.update_process_status(
                    apply_record_id,
                    ProcessStatus.READY_TO_FILL,
                    "分析完成，准备填写"
                )
                return {
                    "success": True,
                    "status": ProcessStatus.READY_TO_FILL.value,
                    "operations": {
                        "university_fields": len(fields),
                        "payload_added": matched_count,
                        "missing_added": 0,
                    },
                    "fields_count": len(fields),
                    "matched_count": matched_count,
                    "missing_count": 0,
                    "message": f"学校字段: {len(fields)} | Payload 写入: {matched_count} (全部匹配成功) | 状态: ready"
                }

        except Exception as e:
            self.update_process_status(apply_record_id, ProcessStatus.FAILED, str(e))
            return {"success": False, "error": str(e)}

    async def _crawl_and_extract(
        self,
        url: str,
        email: str,
        password: str,
        uni_id: str
    ) -> List[Dict]:
        """爬取并提取字段"""
        from playwright.async_api import async_playwright  # type: ignore

        fields = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(url, timeout=30000)
                await asyncio.sleep(3)

                # 遍历页面提取字段
                for page_num in range(1, settings.max_form_pages + 1):
                    try:
                        html = await page.content()
                        page_fields = self._extract_fields_from_html(html, page_num)
                        fields.extend(page_fields)

                        # 尝试点击下一页
                        next_btn = await page.query_selector('button:has-text("Next"), button:has-text("Continue")')
                        if next_btn:
                            await next_btn.click()
                            await asyncio.sleep(2)
                        else:
                            break
                    except Exception:
                        break

            finally:
                await browser.close()

        return fields

    def _extract_fields_from_html(self, html: str, page_num: int) -> List[Dict]:
        """从 HTML 中提取字段"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        fields = []

        # 提取 input 字段
        for inp in soup.find_all(['input', 'select', 'textarea']):
            field_id = inp.get('id') or inp.get('name')
            if not field_id:
                continue

            field_type = inp.get('type', 'text')
            if inp.name == 'select':
                field_type = 'select-one'
            elif inp.name == 'textarea':
                field_type = 'textarea'

            # 获取 label
            label = ''
            label_el = soup.find('label', {'for': field_id})
            if label_el:
                label = label_el.get_text(strip=True)

            fields.append({
                'field_id': field_id,
                'field_name': inp.get('name', ''),  # university_fields 表需要
                'field_label': label,
                'field_type': field_type,
                'is_required': inp.get('required') is not None,
                'page_number': page_num
            })

        return fields

    async def _find_missing_fields(
        self,
        fields: List[Dict],
        user_info: Optional[Dict]
    ) -> tuple[List[Dict], Dict[str, str]]:
        """使用 LLM 智能匹配字段，找出缺失字段

        逻辑：
        1. 遍历所有学校字段（不管是否必填）
        2. 使用 LLM 智能匹配用户信息
        3. 无法匹配到值的字段标记为缺失

        Returns:
            (missing_fields, matched_fields)
            - missing_fields: 缺失字段列表
            - matched_fields: 匹配成功的字段 {field_id: value}
        """
        user_info = user_info or {}

        # 过滤掉系统字段
        user_data = {k: v for k, v in user_info.items()
                     if v and k not in ['id', 'user_id', 'created_at', 'updated_at']}

        if not user_data:
            # 没有用户信息，所有字段都是缺失的
            missing = [
                {
                    'field_id': f.get('field_id', ''),
                    'field_label': f.get('field_label', ''),
                    'field_type': f.get('field_type', 'text'),
                    'is_required': f.get('is_required', False),
                    'options': f.get('options'),
                }
                for f in fields
            ]
            return missing, {}

        # 使用 LLM 批量匹配
        matched_fields = await self._llm_match_fields(fields, user_data)

        # 找出未匹配的字段
        missing = []
        for field in fields:
            field_id = field.get('field_id', '')
            if field_id not in matched_fields:
                missing.append({
                    'field_id': field_id,
                    'field_label': field.get('field_label', ''),
                    'field_type': field.get('field_type', 'text'),
                    'is_required': field.get('is_required', False),
                    'options': field.get('options'),
                })

        return missing, matched_fields

    async def _llm_match_fields(self, fields: List[Dict], user_data: Dict) -> Dict[str, str]:
        """使用 LLM 智能匹配字段和用户信息

        Args:
            fields: 学校表单字段列表
            user_data: 用户信息

        Returns:
            匹配结果 {field_id: matched_value}
        """
        from langchain_openai import ChatOpenAI
        import json
        import os

        # 准备字段信息（简化，避免 prompt 过长）
        fields_info = []
        for f in fields:
            field_info = {
                'id': f.get('field_id', ''),
                'label': f.get('field_label', '')[:100],  # 截断过长的 label
                'type': f.get('field_type', 'text'),
            }
            # 如果有选项，添加选项
            if f.get('options'):
                options = f.get('options')
                if isinstance(options, list) and len(options) <= 10:
                    field_info['options'] = [
                        opt.get('value') if isinstance(opt, dict) else opt
                        for opt in options[:10]
                    ]
            fields_info.append(field_info)

        # 分批处理（每批最多 30 个字段）
        batch_size = 30
        all_matched = {}

        for i in range(0, len(fields_info), batch_size):
            batch = fields_info[i:i + batch_size]

            try:
                llm = ChatOpenAI(
                    model='gpt-4o-mini',
                    api_key=os.getenv('OPENAI_API_KEY', ''),  # type: ignore
                    base_url=os.getenv('OPENAI_BASE_URL'),
                    temperature=0,
                )

                prompt = f"""你是一个智能表单填充助手。请根据用户信息，为表单字段匹配合适的值。

用户信息:
{json.dumps(user_data, ensure_ascii=False, indent=2)}

表单字段:
{json.dumps(batch, ensure_ascii=False, indent=2)}

请为每个能匹配到值的字段返回匹配结果。返回 JSON 格式:
{{
    "field_id_1": "匹配的值",
    "field_id_2": "匹配的值"
}}

匹配规则:
1. 根据字段 label 的语义理解匹配用户信息
2. 如果字段有 options，返回的值必须是 options 中的一个
3. 对于日期字段，格式化为 YYYY-MM-DD
4. 对于文件类型字段，如果用户有对应的文档 ID，返回文档 ID
5. 如果无法确定匹配，不要返回该字段
6. 只返回有把握的匹配，不要猜测

只返回 JSON，不要其他内容。"""

                response = await llm.ainvoke(prompt)
                # 确保 content 是字符串
                raw_content = response.content
                if isinstance(raw_content, str):
                    content = raw_content
                else:
                    content = str(raw_content)

                # 解析 JSON
                json_str = content
                if '```json' in content:
                    json_str = content.split('```json')[1].split('```')[0]
                elif '```' in content:
                    json_str = content.split('```')[1].split('```')[0]

                batch_matched = json.loads(json_str.strip())
                all_matched.update(batch_matched)

            except Exception as e:
                logger.warning(f"LLM 匹配第 {i//batch_size + 1} 批失败: {e}")
                continue

        logger.info(f"LLM 智能匹配完成: {len(all_matched)}/{len(fields)} 个字段匹配成功")
        return all_matched

    def _extract_uni_id(self, url: str) -> str:
        """从 URL 提取学校 ID"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        if 'berkeley' in domain:
            return 'berkeley'
        elif 'mit' in domain:
            return 'mit'
        elif 'stanford' in domain:
            return 'stanford'

        return domain.split('.')[0]

    # ==================== 填充控制 ====================

    def start_filling(self, apply_record_id: int) -> Dict[str, Any]:
        """开始填充

        前置条件检查：
        1. 状态必须是 ready
        2. 不能有未解决的缺失字段
        """
        status = self.get_process_status(apply_record_id)

        # 检查状态
        if status not in [ProcessStatus.READY_TO_FILL.value, 'ready']:
            return {"success": False, "error": f"当前状态 {status} 无法开始填充"}

        # 检查是否有未解决的缺失字段
        unresolved_missing = self.get_missing_fields(apply_record_id)
        if unresolved_missing:
            # 状态应该是 need_input，修正它
            self.update_process_status(
                apply_record_id,
                ProcessStatus.NEED_INPUT,
                f"还有 {len(unresolved_missing)} 个缺失字段需要补充"
            )
            return {
                "success": False,
                "error": f"还有 {len(unresolved_missing)} 个缺失字段需要补充",
                "missing_count": len(unresolved_missing),
                "status": ProcessStatus.NEED_INPUT.value
            }

        self.update_process_status(apply_record_id, ProcessStatus.FILLING, "开始填充表单")
        return {"success": True, "status": ProcessStatus.FILLING.value}

    def complete_filling(self, apply_record_id: int, filled: int, failed: int) -> Dict[str, Any]:
        """完成填充"""
        fill_result = {
            "filled": filled,
            "failed": failed,
            "fields_filled": [],
            "fields_failed": [],
            "fields_no_value": []
        }

        ApplicationProcessDao.update_fill_result(self.db, apply_record_id, filled, failed, fill_result)

        if failed > 0:
            self.update_process_status(apply_record_id, ProcessStatus.PENDING_REVIEW, f"填充完成，{failed} 个失败")
        else:
            self.update_process_status(apply_record_id, ProcessStatus.PENDING_REVIEW, "填充完成，请审核")

        return {"success": True, "filled": filled, "failed": failed}

    def confirm_review(self, apply_record_id: int) -> Dict[str, Any]:
        """确认审核"""
        self.update_process_status(apply_record_id, ProcessStatus.COMPLETED, "申请已完成")
        return {"success": True, "status": ProcessStatus.COMPLETED.value, "message": "申请已完成"}

    def retry(self, apply_record_id: int) -> Dict[str, Any]:
        """重试"""
        self.update_process_status(apply_record_id, ProcessStatus.READY_TO_FILL, "准备重试")
        return {"success": True, "status": ProcessStatus.READY_TO_FILL.value, "message": "准备重试"}
