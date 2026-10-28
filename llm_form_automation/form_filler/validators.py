"""
验证和检测模块

包含：
- PrivacyFilter: 隐私信息过滤
- ValidationChecker: 表单验证错误检测
"""

import re
from typing import Dict, List
from playwright.async_api import Page


class PrivacyFilter:
    """发送给 LLM 前过滤敏感信息"""
    
    # 敏感信息正则模式
    PATTERNS = [
        # 邮箱
        (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
        # 电话号码
        (r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b', '[PHONE]'),
        (r'\b\d{3}-\d{3}-\d{4}\b', '[PHONE]'),
        # SSN (社会安全号)
        (r'\b\d{3}-?\d{2}-?\d{4}\b', '[SSN]'),
        # 信用卡号
        (r'\b(?:\d{4}[-\s]?){3}\d{4}\b', '[CARD]'),
        # IP 地址
        (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[IP]'),
    ]
    
    @classmethod
    def filter_text(cls, text: str) -> str:
        """过滤文本中的敏感信息"""
        if not text:
            return text
        
        filtered = text
        for pattern, replacement in cls.PATTERNS:
            filtered = re.sub(pattern, replacement, filtered, flags=re.IGNORECASE)
        
        return filtered
    
    @classmethod
    def filter_html(cls, html: str) -> str:
        """过滤 HTML 中的敏感信息（保留结构）"""
        if not html:
            return html
        
        filtered = html
        for pattern, replacement in cls.PATTERNS:
            filtered = re.sub(pattern, replacement, filtered, flags=re.IGNORECASE)
        
        return filtered


class ValidationChecker:
    """检测页面上的验证错误"""
    
    # 常见验证错误选择器
    ERROR_SELECTORS = [
        '.validation-error',
        '.field-error',
        '.error-message',
        '.invalid-feedback',
        '.alert-danger',
        '.error',
        '[role="alert"]',
        '[aria-invalid="true"]',
        '.required-field-error',
        '.form-error',
    ]
    
    @classmethod
    async def check_for_errors(cls, page: Page) -> List[Dict[str, str]]:
        """
        检查页面上的验证错误
        
        Returns:
            [{"selector": str, "error_message": str}]
        """
        errors = []
        
        for selector in cls.ERROR_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
                
                for elem in elements:
                    if await elem.is_visible():
                        error_text = await elem.text_content()
                        if error_text and error_text.strip():
                            errors.append({
                                "selector": selector,
                                "error_message": error_text.strip()[:200]
                            })
            except:
                continue
        
        # 去重
        seen = set()
        unique_errors = []
        for error in errors:
            key = error["error_message"]
            if key not in seen:
                seen.add(key)
                unique_errors.append(error)
        
        return unique_errors
    
    @classmethod
    async def has_errors(cls, page: Page) -> bool:
        """快速检查是否有验证错误"""
        errors = await cls.check_for_errors(page)
        return len(errors) > 0

