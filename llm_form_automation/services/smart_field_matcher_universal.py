#!/usr/bin/env python3
"""
通用智能字段匹配模块 (兼容层)

此文件是对 smart_field_matcher.py 的兼容包装，
用于向后兼容旧的 import 路径。

所有实际逻辑都在 smart_field_matcher.py 中实现。
"""

# 从生产版本导入所有类
from llm_form_automation.services.smart_field_matcher import (
    FieldCategory,
    MissingField,
    FieldMatchResult,
    FieldMatcher,
    ChoiceFieldHandler,
    SmartFieldMatcher,
    # 兼容旧版本的类名
    ChoiceFieldHandler as ValueGenerator,
)

__all__ = [
    'FieldCategory',
    'MissingField', 
    'FieldMatchResult',
    'FieldMatcher',
    'ChoiceFieldHandler',
    'SmartFieldMatcher',
    'ValueGenerator',  # 兼容旧版本
]
