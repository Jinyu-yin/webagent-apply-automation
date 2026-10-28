"""
LLM 动态元素查找模块

使用 LLM 解析 DOM 树，动态查找匹配的元素，而不是硬编码选择器。
支持：
1. 查找按钮（下一页、保存、提交等）
2. 查找表单字段
3. 查找弹窗触发器
"""

import os
import json
import requests
from typing import Dict, List, Any, Optional
from playwright.async_api import Page


def _get_llm_config() -> Dict[str, str]:
    """获取 LLM 配置"""
    return {
        "api_key": os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
        "base_url": os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        "llm_model": os.getenv("LLM_MODEL", "anthropic/claude-3.5-sonnet"),
    }


class ElementFinder:
    """
    LLM 动态元素查找器
    
    通过 LLM 分析 DOM 结构，智能匹配目标元素
    """
    
    def __init__(self):
        self._llm_config = _get_llm_config()
        self._cache: Dict[str, str] = {}  # 缓存查找结果
    
    async def extract_simplified_dom(self, page: Page, max_elements: int = 200) -> str:
        """
        提取简化的 DOM 结构，用于 LLM 分析
        
        只保留交互元素：button, a, input, select, textarea
        """
        dom_info = await page.evaluate(f"""() => {{
            const elements = [];
            const selectors = 'button, a, input:not([type="hidden"]), select, textarea, [role="button"], [onclick], [type="submit"]';
            const nodes = document.querySelectorAll(selectors);
            
            let count = 0;
            nodes.forEach((elem, idx) => {{
                if (count >= {max_elements}) return;
                
                // 检查可见性
                const rect = elem.getBoundingClientRect();
                const isVisible = rect.width > 0 && rect.height > 0 && 
                                  window.getComputedStyle(elem).display !== 'none' &&
                                  window.getComputedStyle(elem).visibility !== 'hidden';
                
                if (!isVisible) return;
                
                const info = {{
                    idx: count,
                    tag: elem.tagName.toLowerCase(),
                    id: elem.id || null,
                    name: elem.name || null,
                    type: elem.type || null,
                    text: (elem.textContent || '').trim().substring(0, 50),
                    value: elem.value || null,
                    placeholder: elem.placeholder || null,
                    ariaLabel: elem.getAttribute('aria-label') || null,
                    href: elem.href || null,
                    classes: elem.className ? elem.className.split(' ').slice(0, 3).join(' ') : null,
                }};
                
                // 清理空值
                Object.keys(info).forEach(k => {{
                    if (info[k] === null || info[k] === '') delete info[k];
                }});
                
                elements.push(info);
                count++;
            }});
            
            return JSON.stringify(elements, null, 2);
        }}""")
        
        return dom_info
    
    async def find_element(
        self, 
        page: Page, 
        description: str,
        element_type: str = "any"
    ) -> Optional[Dict[str, Any]]:
        """
        根据描述查找元素
        
        Args:
            page: 浏览器页面
            description: 元素描述（如 "下一页按钮"、"保存按钮"、"邮箱输入框"）
            element_type: 元素类型过滤（button, input, link, any）
        
        Returns:
            {"selector": str, "confidence": float, "element_info": dict} or None
        """
        # 检查缓存
        cache_key = f"{page.url}:{description}:{element_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        if not self._llm_config["api_key"]:
            print(f"⚠️ LLM API Key 未设置，使用回退选择器")
            return self._fallback_find(description, element_type)
        
        # 提取简化 DOM
        dom_info = await self.extract_simplified_dom(page)
        
        # 调用 LLM
        result = await self._llm_find_element(dom_info, description, element_type)
        
        if result:
            self._cache[cache_key] = result
        
        return result
    
    async def _llm_find_element(
        self, 
        dom_info: str, 
        description: str, 
        element_type: str
    ) -> Optional[Dict[str, Any]]:
        """使用 LLM 查找元素"""
        
        system_prompt = """你是一个网页元素定位专家。根据用户的描述和页面 DOM 结构，找出最匹配的元素。

规则：
1. 仔细分析元素的 text、id、name、placeholder、aria-label 等属性
2. 考虑语义相近（如 "Next" ≈ "Continue" ≈ "下一步"）
3. 考虑多语言（如 "Save" ≈ "保存"）
4. 只返回 JSON，不要解释

返回格式：
{
    "found": true/false,
    "idx": 元素索引（从 DOM 列表中）,
    "selector": "CSS 选择器或 XPath",
    "confidence": 0.0-1.0,
    "reason": "匹配原因"
}

如果找不到合适的元素，返回：
{"found": false, "reason": "原因"}"""

        user_prompt = f"""目标：找到 "{description}"
元素类型：{element_type}

页面 DOM 元素列表：
{dom_info}

请分析并返回最匹配的元素。"""

        try:
            response = requests.post(
                self._llm_config["base_url"].rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._llm_config['api_key']}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self._llm_config["llm_model"],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 500
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                
                # 提取 JSON
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    
                    if data.get("found"):
                        return {
                            "selector": data.get("selector"),
                            "confidence": data.get("confidence", 0.5),
                            "element_info": data,
                        }
            
            return None
        
        except Exception as e:
            print(f"⚠️ LLM 元素查找失败: {e}")
            return None
    
    def _fallback_find(self, description: str, element_type: str) -> Optional[Dict[str, Any]]:
        """回退到常见选择器模式"""
        description_lower = description.lower()
        
        # 按钮类
        button_patterns = {
            "next": [
                'button:has-text("Next")', 'button:has-text("Continue")',
                'button:has-text("下一步")', 'a:has-text("Next")'
            ],
            "save": [
                'button:has-text("Save")', 'button:has-text("保存")',
                'button[type="submit"]:has-text("Save")'
            ],
            "submit": [
                'button:has-text("Submit")', 'button:has-text("提交")',
                'button[type="submit"]', 'input[type="submit"]'
            ],
            "add": [
                'button:has-text("Add")', 'a:has-text("Add New")',
                'button:has-text("添加")', '[class*="add"]'
            ],
            "login": [
                'button:has-text("Login")', 'button:has-text("Sign in")',
                'button:has-text("登录")', 'button[type="submit"]'
            ],
        }
        
        for key, selectors in button_patterns.items():
            if key in description_lower:
                return {
                    "selector": selectors[0],
                    "alternatives": selectors[1:],
                    "confidence": 0.3,
                    "element_info": {"fallback": True}
                }
        
        return None
    
    async def find_button(
        self, 
        page: Page, 
        button_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        查找特定类型的按钮
        
        Args:
            page: 浏览器页面
            button_type: 按钮类型（next, save, submit, add, cancel, close）
        
        Returns:
            {"selector": str, "confidence": float} or None
        """
        descriptions = {
            "next": "下一页/继续按钮（Next、Continue、Save and Continue）",
            "save": "保存按钮（Save、保存）",
            "submit": "提交按钮（Submit、提交、Apply）",
            "add": "添加按钮（Add、Add New、添加）",
            "cancel": "取消按钮（Cancel、取消、Close）",
            "close": "关闭按钮（Close、X、关闭）",
        }
        
        desc = descriptions.get(button_type, f"{button_type} 按钮")
        return await self.find_element(page, desc, "button")
    
    async def click_element(
        self, 
        page: Page, 
        description: str,
        timeout: int = 5000
    ) -> bool:
        """
        查找并点击元素
        
        Args:
            page: 浏览器页面
            description: 元素描述
            timeout: 超时时间（毫秒）
        
        Returns:
            是否成功点击
        """
        result = await self.find_element(page, description)
        
        if not result:
            print(f"⚠️ 未找到元素: {description}")
            return False
        
        selector = result["selector"]
        alternatives = result.get("alternatives", [])
        
        # 尝试主选择器
        try:
            elem = await page.query_selector(selector)
            if elem and await elem.is_visible():
                await elem.click()
                print(f"✅ 点击: {description} (selector: {selector})")
                return True
        except:
            pass
        
        # 尝试备选选择器
        for alt_selector in alternatives:
            try:
                elem = await page.query_selector(alt_selector)
                if elem and await elem.is_visible():
                    await elem.click()
                    print(f"✅ 点击: {description} (alt: {alt_selector})")
                    return True
            except:
                continue
        
        print(f"❌ 点击失败: {description}")
        return False
    
    async def find_form_fields(self, page: Page) -> List[Dict[str, Any]]:
        """
        查找页面上所有表单字段（带 LLM 增强标签识别）
        
        Returns:
            字段列表，每个字段包含 id、name、type、label 等信息
        """
        # 基础字段提取
        fields = await page.evaluate("""() => {
            const fields = [];
            const inputs = document.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea'
            );
            
            inputs.forEach((elem, idx) => {
                const rect = elem.getBoundingClientRect();
                const isVisible = rect.width > 0 && rect.height > 0;
                
                if (!isVisible) return;
                
                const field = {
                    idx: idx,
                    id: elem.id || '',
                    name: elem.name || '',
                    type: elem.type || elem.tagName.toLowerCase(),
                    label: '',
                    placeholder: elem.placeholder || '',
                    required: elem.required || false,
                    value: elem.value || '',
                    options: []
                };
                
                // 获取 label
                if (elem.id) {
                    const label = document.querySelector(`label[for="${elem.id}"]`);
                    if (label) {
                        field.label = label.textContent.trim().substring(0, 100);
                    }
                }
                
                // 如果没有 label，尝试从父元素获取
                if (!field.label) {
                    const parent = elem.closest('.form_question, .form-group, .field-wrapper, .question');
                    if (parent) {
                        const labelElem = parent.querySelector('label, .form_label, .field-label, .question-text');
                        if (labelElem) {
                            field.label = labelElem.textContent.trim().substring(0, 100);
                        }
                    }
                }
                
                // 获取 select 选项
                if (elem.tagName === 'SELECT') {
                    field.options = Array.from(elem.options).slice(0, 20).map(opt => ({
                        value: opt.value,
                        text: opt.text.trim()
                    }));
                }
                
                fields.push(field);
            });
            
            return fields;
        }""")
        
        return fields
    
    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()


# 全局单例
_element_finder: Optional[ElementFinder] = None


def get_element_finder() -> ElementFinder:
    """获取全局 ElementFinder 实例"""
    global _element_finder
    if _element_finder is None:
        _element_finder = ElementFinder()
    return _element_finder

