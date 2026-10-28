"""
站点配置模块

仅保留通用配置，不做任何站点特定的硬编码逻辑。
所有填写逻辑都应该：
1. 由 payload 数据驱动
2. 由 LLM 动态识别元素
"""

from typing import Dict, List
from urllib.parse import urlparse
from playwright.async_api import Page


class SiteConfig:
    """
    站点配置基类
    
    注意：不应该在这里硬编码任何站点特定的选择器或默认值！
    所有字段值都应该来自用户的 payload 数据。
    """
    
    async def pre_fill_hooks(self, page: Page) -> None:
        """
        填充前的钩子
        
        默认不做任何操作。如果某些页面需要特殊处理（如展开折叠区域），
        应该通过 LLM 动态识别，而不是硬编码。
        """
        pass
    
    async def post_fill_hooks(self, page: Page) -> None:
        """
        填充后的钩子
        
        默认不做任何操作。
        """
        pass
    
    def validation_error_selectors(self) -> List[str]:
        """
        返回通用的验证错误选择器
        
        这些是大多数网站通用的错误提示元素选择器。
        """
        return [
            '.error',
            '.validation-error',
            '.field-error',
            '.alert-danger',
            '.alert-error',
            '[role="alert"]',
            '.invalid-feedback',
            '[aria-invalid="true"]',
            '.form-error',
            '.error-message',
        ]


# 只使用通用配置，不做站点特定处理
# 所有站点都使用相同的通用逻辑
def get_site_config(url: str) -> SiteConfig:
    """
    获取站点配置
    
    所有站点都返回通用配置。
    不再根据域名返回不同配置 - 所有逻辑都应该由 payload 和 LLM 驱动。
    """
    return SiteConfig()
