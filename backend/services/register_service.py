"""
注册服务层

核心职责：
1. 处理用户注册流程
2. 调用浏览器自动化进行注册
3. 管理注册状态和回调
4. 保存注册结果到数据库
"""

import asyncio
from typing import Any, Dict, Optional

from backend.db import get_db
from backend.config import settings
from backend.logger import get_service_logger
from backend.dao import ApplyRecordDao

logger = get_service_logger("RegisterService")


class RegisterService:
    """
    注册服务

    负责：
    - 账号注册自动化
    - 注册状态管理
    - 保存注册结果到数据库
    """

    def __init__(self):
        self.db = get_db()

    # ==================== 注册流程 ====================

    async def register(
        self,
        apply_record_id: int,
        email: str,
        password: str,
        url: str,
        uni_id: str = '',
        user_data: Optional[Dict[str, Any]] = None,
        headless: bool = True
    ) -> Dict[str, Any]:
        """
        执行注册流程

        Args:
            apply_record_id: 申请记录 ID
            email: 注册邮箱
            password: 注册密码
            url: 注册页面 URL
            uni_id: 学校 ID（用于选择注册模板）
            user_data: 用户数据（姓名等）
            headless: 是否无头模式

        Returns:
            {
                "success": bool,
                "status": "completed" | "failed",
                "message": str,
                "missing_fields": list,
                "apply_record_id": int
            }
        """
        from browser_use import Agent  # type: ignore
        from langchain_openai import ChatOpenAI
        import os

        # 更新状态为 "进行中"
        ApplyRecordDao.update_register_status(self.db, apply_record_id, "registering")

        try:
            # 1. 构建注册任务描述（包含 URL）
            task = self._build_register_task(email, password, url, uni_id, user_data)

            # 2. 创建 LLM (使用 langchain_openai)
            api_key = os.getenv('OPENAI_API_KEY', '')
            base_url = os.getenv('OPENAI_BASE_URL')
            llm = ChatOpenAI(
                model='gpt-4o',
                api_key=api_key,  # type: ignore
                base_url=base_url,
            )

            # 3. 创建 Agent (browser-use 0.1.48 API)
            agent = Agent(
                task=f"请先访问 {url}，然后执行以下任务：{task}",
                llm=llm,
            )

            # 4. 执行注册
            logger.info(f"开始注册: {email} @ {url}")
            history = await agent.run()

            # 提取最终结果
            final_result = ''
            if history:
                if hasattr(history, 'final_result'):
                    final_result = history.final_result()
                else:
                    final_result = str(history)

            # 4. 使用 LLM 解析结果
            result = await self._parse_register_result(final_result)

            # 5. 保存注册状态到数据库
            db_status = "success" if result["success"] else "failed"
            ApplyRecordDao.update_register_status(self.db, apply_record_id, db_status)

            logger.info(f"注册完成: {result['status']}, 已保存到数据库")

            result["apply_record_id"] = apply_record_id
            return result

        except Exception as e:
            logger.error(f"注册失败: {e}")

            # 保存失败状态到数据库
            ApplyRecordDao.update_register_status(self.db, apply_record_id, "failed")

            return {
                "success": False,
                "status": "failed",
                "message": str(e),
                "missing_fields": [],
                "apply_record_id": apply_record_id
            }

    def _build_register_task(
        self,
        email: str,
        password: str,
        url: str,
        uni_id: str,
        user_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        构建注册任务描述

        根据 uni_id 选择不同的注册模板
        """
        # 默认注册任务模板
        base_task = f"""
进行账号注册，注册信息如下：
- 邮箱: {email}
- 密码: {password}
- 注册页面: {url}

请按以下步骤操作：
1. 打开注册页面
2. 填写邮箱和密码
3. 填写其他必要信息
4. 点击注册/提交按钮
5. 如果需要邮箱验证，请记录下来

注意事项：
- 填写完当前页面所有可填写元素后向下滚动
- 不要重复操作同一个元素
- 如果遇到验证码或需要人工干预的情况，请记录下来
- 任务完成后返回总结，说明注册是否成功
"""

        # 添加用户数据
        if user_data:
            base_task += f"\n用户其他信息: {user_data}"

        # 特定学校的注册模板
        uni_templates = self._get_uni_register_templates()
        if uni_id in uni_templates:
            return uni_templates[uni_id].format(
                email=email,
                password=password,
                data=user_data or {}
            )

        return base_task

    def _get_uni_register_templates(self) -> Dict[str, str]:
        """获取各学校的注册任务模板"""
        return {
            # Berkeley
            'berkeley': """
进行账号注册，我的邮箱是{email}，密码是{password}。
请访问 Berkeley 研究生申请系统，完成以下步骤：
1. 点击 Create Account 或 Register
2. 填写邮箱、密码、确认密码
3. 填写基本信息（姓名等）
4. 同意服务条款
5. 点击提交

用户信息: {data}
任务完成后返回总结。
""",
            # 可以添加更多学校的模板
        }

    async def _parse_register_result(self, agent_result: Any) -> Dict[str, Any]:
        """使用 LLM 分析 Agent 执行结果"""
        from langchain_openai import ChatOpenAI
        import os
        import json

        result_str = str(agent_result) if agent_result else ""

        if not result_str:
            return {
                "success": False,
                "status": "failed",
                "message": "无返回信息",
                "missing_fields": []
            }

        # 使用 LLM 分析结果
        try:
            llm = ChatOpenAI(
                model='gpt-4o-mini',  # 用更快更便宜的模型分析
                api_key=os.getenv('OPENAI_API_KEY', ''),  # type: ignore
                base_url=os.getenv('OPENAI_BASE_URL'),
            )

            analysis_prompt = f"""分析以下注册操作的执行结果，判断注册是否成功。

执行结果:
{result_str[:2000]}

请以 JSON 格式返回分析结果，格式如下:
{{
    "success": true/false,
    "reason": "简要说明判断依据",
    "missing_fields": ["缺失字段1", "缺失字段2"]  // 如果有缺失字段
}}

判断标准:
- 如果账号成功创建、注册完成、收到确认邮件等，返回 success: true
- 如果遇到网络错误、连接失败、页面无法访问、注册被拒绝等，返回 success: false
- 如果结果不明确或无法判断，返回 success: false

只返回 JSON，不要其他内容。"""

            response = await llm.ainvoke(analysis_prompt)
            # 确保 response_text 是字符串
            if hasattr(response, 'content'):
                content = response.content
                response_text = content if isinstance(content, str) else str(content)
            else:
                response_text = str(response)

            # 解析 JSON
            # 尝试提取 JSON 部分
            json_str = response_text
            if '```json' in response_text:
                json_str = response_text.split('```json')[1].split('```')[0]
            elif '```' in response_text:
                json_str = response_text.split('```')[1].split('```')[0]

            analysis = json.loads(json_str.strip())

            return {
                "success": analysis.get("success", False),
                "status": "completed" if analysis.get("success") else "failed",
                "message": f"{analysis.get('reason', '')} | 原始结果: {result_str[:300]}",
                "missing_fields": analysis.get("missing_fields", [])
            }

        except Exception as e:
            logger.warning(f"LLM 分析失败，回退到关键词匹配: {e}")
            # 回退到关键词匹配
            return self._parse_register_result_fallback(result_str)

    def _parse_register_result_fallback(self, result_str: str) -> Dict[str, Any]:
        """关键词匹配作为后备方案"""
        result_lower = result_str.lower()

        # 失败关键词优先检测
        fail_keywords = [
            '失败', 'failed', 'error', '错误', 'err_', 'unable to',
            'unsuccessful', 'could not', 'cannot', 'connection',
            'timeout', '超时', '无法访问', 'inaccessible', 'closed'
        ]
        # 成功关键词
        success_keywords = [
            '成功', 'success', '注册完成', 'account created',
            'registration complete', 'registered successfully',
            'verification email sent', '验证邮件已发送'
        ]

        is_failed = any(kw in result_lower for kw in fail_keywords)
        is_success = any(kw in result_lower for kw in success_keywords)

        # 有失败标志就是失败，除非有明确成功标志且无失败标志
        if is_failed:
            success = False
        elif is_success:
            success = True
        else:
            # 不确定时默认失败
            success = False

        return {
            "success": success,
            "status": "completed" if success else "failed",
            "message": result_str[:500] if result_str else "无返回信息",
            "missing_fields": self._extract_missing_fields(result_str)
        }

    def _extract_missing_fields(self, result_str: str) -> list:
        """从结果中提取缺失字段"""
        missing = []

        # 简单的关键词匹配
        if '缺少' in result_str or 'missing' in result_str.lower():
            # 尝试提取字段名
            import re
            patterns = [
                r'缺少[：:]\s*([^，。\n]+)',
                r'missing[：:]\s*([^,.\n]+)',
                r'需要填写[：:]\s*([^，。\n]+)'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, result_str, re.IGNORECASE)
                missing.extend(matches)

        return list(set(missing))

    # ==================== 同步版本 ====================

    def register_sync(
        self,
        apply_record_id: int,
        email: str,
        password: str,
        url: str,
        uni_id: str = '',
        user_data: Optional[Dict[str, Any]] = None,
        headless: bool = True
    ) -> Dict[str, Any]:
        """同步版本的注册方法"""
        return asyncio.run(self.register(
            apply_record_id, email, password, url, uni_id, user_data, headless
        ))
