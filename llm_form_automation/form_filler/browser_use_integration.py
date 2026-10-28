"""
Browser-Use 整合模块

将 browser-use 库的 Agent 能力与表单填写整合，提供：
1. 智能任务执行（通过 Agent）
2. DOM 解析和元素定位（通过 DomService）
3. 表单填写的智能增强
"""

from __future__ import annotations

import os
import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable, TYPE_CHECKING
from pathlib import Path

from playwright.async_api import Page

# Browser-Use imports
HAS_BROWSER_USE = False
Agent = None
Browser = None
BrowserConfig = None
BrowserSession = None
Controller = None
DomService = None
ChatOpenAI = None
ChatAnthropic = None

try:
    from browser_use import (
        Agent,
        Browser,
        BrowserConfig,
        BrowserSession,
        Controller,
        DomService,
    )
    from browser_use.llm import ChatOpenAI, ChatAnthropic
    HAS_BROWSER_USE = True
except ImportError:
    pass

from .payload_manager import PayloadManager
from .element_finder import ElementFinder, get_element_finder


logger = logging.getLogger(__name__)


class BrowserUseFormFiller:
    """
    基于 Browser-Use 的智能表单填写器
    
    结合 browser-use 的 Agent 能力和自定义表单填写逻辑
    """
    
    def __init__(
        self,
        payload_path: Path,
        llm_provider: str = "openai",
        model: str = None,
        headless: bool = False,
    ):
        """
        初始化
        
        Args:
            payload_path: Payload 文件路径
            llm_provider: LLM 提供商 (openai, anthropic)
            model: 模型名称
            headless: 是否无头模式
        """
        if not HAS_BROWSER_USE:
            raise ImportError("browser-use 库未安装，请运行 pip install browser-use")
        
        self.payload_path = Path(payload_path)
        self.payload_manager = PayloadManager(self.payload_path)
        self.payload_data = self.payload_manager.get_all_fields()
        
        self.llm_provider = llm_provider
        self.model = model
        self.headless = headless
        
        # 元素查找器
        self.element_finder = get_element_finder()
        
        # Browser-Use 组件（延迟初始化）
        self._browser_session = None  # BrowserSession
        self._llm = None
        self._controller = None
        
        # 填写记录
        self.fill_history: List[Dict] = []
        self.missing_fields: List[Dict] = []
    
    def _get_llm(self):
        """获取 LLM 实例"""
        if self._llm is not None:
            return self._llm
        
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        
        if self.llm_provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY") or api_key
            self._llm = ChatAnthropic(
                model=self.model or "claude-3-5-sonnet-20241022",
                api_key=api_key,
            )
        else:
            # OpenAI 兼容（包括 OpenRouter）
            base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
            self._llm = ChatOpenAI(
                model=self.model or "gpt-4o",
                api_key=api_key,
                base_url=base_url,
            )
        
        return self._llm
    
    async def _get_browser_session(self):
        """获取 Browser Session"""
        if self._browser_session is not None:
            return self._browser_session
        
        browser = Browser(
            config=BrowserConfig(
                headless=self.headless,
            )
        )
        self._browser_session = await browser.new_session()
        return self._browser_session
    
    async def close(self):
        """关闭资源"""
        if self._browser_session:
            await self._browser_session.close()
            self._browser_session = None
    
    async def run_agent_task(
        self,
        task: str,
        url: str = None,
        max_steps: int = 20,
        on_step: Callable[[Dict], None] = None,
    ) -> Dict[str, Any]:
        """
        运行 Agent 任务
        
        Args:
            task: 任务描述
            url: 起始 URL
            max_steps: 最大步数
            on_step: 步骤回调
        
        Returns:
            {"success": bool, "result": str, "history": list}
        """
        llm = self._get_llm()
        session = await self._get_browser_session()
        
        # 如果指定了 URL，先导航
        if url:
            page = await session.get_current_page()
            await page.goto(url, wait_until='networkidle')
        
        # 创建 Agent
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=session,
            max_actions_per_step=5,
        )
        
        # 运行
        result = await agent.run(max_steps=max_steps)
        
        return {
            "success": result.is_done(),
            "result": result.final_result() if result.is_done() else None,
            "history": result.history if hasattr(result, 'history') else [],
        }
    
    async def fill_form_with_agent(
        self,
        url: str,
        additional_instructions: str = "",
    ) -> Dict[str, Any]:
        """
        使用 Agent 智能填写表单
        
        Args:
            url: 表单页面 URL
            additional_instructions: 额外指令
        
        Returns:
            填写结果
        """
        # 构建任务描述
        payload_summary = self._summarize_payload()
        
        task = f"""填写网页表单。

用户信息：
{payload_summary}

要求：
1. 根据用户信息填写表单中的对应字段
2. 如果某个字段找不到对应的用户信息，跳过该字段
3. 不要编造任何信息
4. 填写完成后点击保存或下一步按钮
{additional_instructions}

请开始填写表单。"""
        
        return await self.run_agent_task(task, url)
    
    def _summarize_payload(self) -> str:
        """生成 payload 摘要"""
        lines = []
        for field_id, field_data in self.payload_data.items():
            if isinstance(field_data, dict):
                value = field_data.get("value", "")
                label = field_data.get("label", field_id)
            else:
                value = field_data
                label = field_id
            
            if value:
                # 隐藏敏感信息
                if any(kw in label.lower() for kw in ['password', 'ssn', 'secret']):
                    value = "***"
                lines.append(f"- {label}: {value}")
        
        return "\n".join(lines[:50])  # 最多 50 个字段
    
    async def get_dom_state(self, page: Page) -> Dict[str, Any]:
        """
        使用 DomService 获取页面 DOM 状态
        
        Returns:
            {"elements": list, "selector_map": dict}
        """
        dom_service = DomService(page)
        dom_state = await dom_service.get_clickable_elements(
            highlight_elements=False,
            viewport_expansion=0,
        )
        
        return {
            "element_tree": dom_state.element_tree,
            "selector_map": dom_state.selector_map,
        }
    
    async def smart_fill_field(
        self,
        page: Page,
        field_description: str,
        value: str,
    ) -> bool:
        """
        智能填写单个字段（使用 LLM 定位）
        
        Args:
            page: 浏览器页面
            field_description: 字段描述
            value: 要填写的值
        
        Returns:
            是否成功
        """
        # 使用 ElementFinder 定位字段
        result = await self.element_finder.find_element(
            page, 
            field_description, 
            element_type="input"
        )
        
        if not result:
            logger.warning(f"未找到字段: {field_description}")
            return False
        
        selector = result["selector"]
        
        try:
            elem = await page.query_selector(selector)
            if elem:
                await elem.fill(value)
                logger.info(f"✅ 填写: {field_description} = {value[:20]}...")
                return True
        except Exception as e:
            logger.error(f"填写失败: {field_description} - {e}")
        
        return False
    
    async def smart_click(
        self,
        page: Page,
        button_description: str,
    ) -> bool:
        """
        智能点击按钮（使用 LLM 定位）
        
        Args:
            page: 浏览器页面
            button_description: 按钮描述
        
        Returns:
            是否成功
        """
        return await self.element_finder.click_element(page, button_description)
    
    async def fill_page_smart(
        self,
        page: Page,
        page_num: int = 1,
    ) -> Dict[str, Any]:
        """
        智能填写当前页面
        
        结合 ElementFinder 的 LLM 定位和 payload 匹配
        
        Returns:
            填写报告
        """
        report = {
            "page_num": page_num,
            "page_url": page.url,
            "fields_filled": [],
            "fields_no_value": [],
            "fields_failed": [],
        }
        
        # 获取页面字段
        fields = await self.element_finder.find_form_fields(page)
        
        logger.info(f"📋 页面 {page_num} 字段数: {len(fields)}")
        
        for field in fields:
            field_id = field.get('id') or field.get('name')
            field_label = field.get('label', '')
            
            if not field_id:
                continue
            
            # 匹配 payload
            value = self._match_payload(field_id, field_label)
            
            if value:
                # 尝试填写
                success = await self._fill_single_field(page, field, value)
                
                record = {
                    "field_id": field_id,
                    "field_label": field_label,
                    "value": value,
                }
                
                if success:
                    report["fields_filled"].append(record)
                else:
                    record["error"] = "Fill failed"
                    report["fields_failed"].append(record)
            else:
                report["fields_no_value"].append({
                    "field_id": field_id,
                    "field_label": field_label,
                })
        
        # 统计
        logger.info(f"✅ 填写: {len(report['fields_filled'])}")
        logger.info(f"⚠️ 无值: {len(report['fields_no_value'])}")
        logger.info(f"❌ 失败: {len(report['fields_failed'])}")
        
        return report
    
    def _match_payload(self, field_id: str, field_label: str) -> Optional[str]:
        """匹配 payload 值"""
        # 精确匹配
        if field_id in self.payload_data:
            data = self.payload_data[field_id]
            if isinstance(data, dict):
                return data.get("value")
            return data
        
        # 标签匹配
        field_label_lower = field_label.lower()
        for key, data in self.payload_data.items():
            if isinstance(data, dict):
                payload_label = (data.get("label") or "").lower()
                if payload_label and (
                    field_label_lower in payload_label or 
                    payload_label in field_label_lower
                ):
                    return data.get("value")
        
        return None
    
    async def _fill_single_field(self, page: Page, field: Dict, value: str) -> bool:
        """填写单个字段"""
        field_id = field.get('id') or field.get('name')
        field_type = field.get('type', 'text')
        
        try:
            selector = f"#{field_id}" if field.get('id') else f"[name='{field_id}']"
            elem = await page.query_selector(selector)
            
            if not elem:
                return False
            
            if field_type in ['text', 'email', 'tel', 'textarea', 'password', 'number']:
                await elem.fill(str(value))
            elif field_type in ['select', 'select-one']:
                try:
                    await elem.select_option(value=str(value))
                except:
                    await elem.select_option(label=str(value))
            elif field_type == 'checkbox':
                should_check = str(value).lower() in ['true', 'yes', '1']
                if should_check:
                    await elem.check()
                else:
                    await elem.uncheck()
            elif field_type == 'radio':
                radios = await page.query_selector_all(f"input[type='radio'][name='{field_id}']")
                for radio in radios:
                    radio_value = await radio.get_attribute('value')
                    if radio_value and radio_value.lower() == str(value).lower():
                        await radio.check()
                        break
            else:
                await elem.fill(str(value))
            
            return True
        
        except Exception as e:
            logger.error(f"填写字段 {field_id} 失败: {e}")
            return False


class HybridFormFiller:
    """
    混合表单填写器
    
    结合：
    1. 精确填写（基于 payload 匹配）
    2. LLM 动态元素定位
    3. Browser-Use Agent 智能补充
    """
    
    def __init__(
        self,
        payload_path: Path,
        use_agent_fallback: bool = True,
        headless: bool = False,
    ):
        self.payload_path = Path(payload_path)
        self.use_agent_fallback = use_agent_fallback
        self.headless = headless
        
        # 组件
        self.payload_manager = PayloadManager(self.payload_path)
        self.element_finder = get_element_finder()
        
        # Browser-Use 填写器（可选）
        self._bu_filler: Optional[BrowserUseFormFiller] = None
        if use_agent_fallback and HAS_BROWSER_USE:
            self._bu_filler = BrowserUseFormFiller(
                payload_path=payload_path,
                headless=headless,
            )
    
    async def fill_page(
        self,
        page: Page,
        page_num: int = 1,
        use_agent_for_failures: bool = False,
    ) -> Dict[str, Any]:
        """
        填写页面（混合策略）
        
        1. 先用精确匹配填写
        2. 对失败的字段用 LLM 重试定位
        3. 可选：用 Agent 处理剩余字段
        """
        from .form_filler import LLMFormFiller
        
        # 阶段 1：精确填写
        filler = LLMFormFiller(
            payload_path=self.payload_path,
            start_url=page.url,
        )
        
        report = await filler.fill_page_from_payload(page, page_num)
        
        # 阶段 2：对失败的字段用 LLM 重试
        if report["fields_failed"]:
            logger.info(f"🔄 重试 {len(report['fields_failed'])} 个失败字段...")
            
            for field in report["fields_failed"]:
                field_label = field.get("field_label") or field.get("field_id")
                value = field.get("value")
                
                if value and field_label:
                    success = await self._bu_filler.smart_fill_field(
                        page, field_label, value
                    ) if self._bu_filler else False
                    
                    if success:
                        # 移动到成功列表
                        report["fields_filled"].append(field)
                        report["fields_failed"].remove(field)
        
        # 阶段 3：Agent 智能补充（可选）
        if use_agent_for_failures and self._bu_filler and report["fields_no_value"]:
            logger.info(f"🤖 Agent 尝试处理 {len(report['fields_no_value'])} 个无值字段...")
            # 这里可以调用 Agent 来尝试理解和填写
            # 但要注意：不能编造用户信息
        
        return report
    
    async def click_next(self, page: Page) -> bool:
        """智能点击下一页按钮"""
        return await self.element_finder.click_element(
            page, 
            "下一页/继续/保存并继续按钮"
        )
    
    async def close(self):
        """关闭资源"""
        if self._bu_filler:
            await self._bu_filler.close()

