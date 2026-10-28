#!/usr/bin/env python3
"""
LLM Form Automation Services
"""

from .smart_field_matcher import (
    SmartFieldMatcher, 
    FieldMatcher, 
    ChoiceFieldHandler,
    FieldCategory,
    MissingField,
    FieldMatchResult,
)

# 兼容旧版本的类名
from .smart_field_matcher import ChoiceFieldHandler as ValueGenerator

from .smart_field_matcher_universal import SmartFieldMatcher as SmartFieldMatcherUniversal

from .error_handler import (
    ErrorCategory,
    RetryStrategy,
    FormAutomationError,
    ErrorClassifier,
    FormAutomationLogger,
    default_logger,
    create_user_data_error,
    create_execution_error,
    create_agent_error,
    create_system_error,
)

__all__ = [
    # Field Matching
    'SmartFieldMatcher',
    'SmartFieldMatcherUniversal', 
    'FieldMatcher',
    'ChoiceFieldHandler',
    'ValueGenerator',  # 兼容旧版本
    'FieldCategory',
    'MissingField',
    'FieldMatchResult',
    # Error Handling
    'ErrorCategory',
    'RetryStrategy',
    'FormAutomationError',
    'ErrorClassifier',
    'FormAutomationLogger',
    'default_logger',
    'create_user_data_error',
    'create_execution_error',
    'create_agent_error',
    'create_system_error',
]
