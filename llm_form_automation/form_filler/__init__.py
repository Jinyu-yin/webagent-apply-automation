"""
LLM Form Filler - 智能表单填写模块

模块结构：
- payload_manager: Payload 数据管理
- validators: 验证和隐私过滤
- intervention: 人工干预和提交检测
- field_handlers: 特殊字段处理
- site_configs: 站点特定配置
- login_handler: 登录处理
- form_filler: 核心填写逻辑
- element_finder: LLM 动态元素查找
- browser_use_integration: Browser-Use 整合
"""

from .payload_manager import PayloadManager
from .validators import PrivacyFilter, ValidationChecker
from .intervention import HumanIntervention, SubmissionChecker
from .field_handlers import SpecialFieldHandler, CollapsibleHandler
from .site_configs import SiteConfig, get_site_config
from .login_handler import LoginHandler
from .form_filler import LLMFormFiller
from .element_finder import ElementFinder, get_element_finder

# Browser-Use 整合（可选）
try:
    from .browser_use_integration import (
        BrowserUseFormFiller,
        HybridFormFiller,
        HAS_BROWSER_USE,
    )
except ImportError:
    HAS_BROWSER_USE = False
    BrowserUseFormFiller = None
    HybridFormFiller = None

__all__ = [
    # 核心组件
    'PayloadManager',
    'LLMFormFiller',
    
    # 验证和检测
    'PrivacyFilter',
    'ValidationChecker',
    'HumanIntervention',
    'SubmissionChecker',
    
    # 字段处理
    'SpecialFieldHandler',
    'CollapsibleHandler',
    
    # 站点配置
    'SiteConfig',
    'get_site_config',
    
    # 登录
    'LoginHandler',
    
    # LLM 元素查找
    'ElementFinder',
    'get_element_finder',
    
    # Browser-Use 整合
    'BrowserUseFormFiller',
    'HybridFormFiller',
    'HAS_BROWSER_USE',
]
