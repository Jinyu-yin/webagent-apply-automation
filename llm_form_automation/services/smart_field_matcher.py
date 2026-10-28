#!/usr/bin/env python3
"""
智能字段匹配模块 (生产版本)

核心原则:
- 只使用用户提供的真实数据
- 缺失的用户信息字段必须标记为缺失，返回给前端让用户补充
- 绝不随机生成用户的个人信息（姓名、邮箱、电话、地址等）
- 选择框类字段可以智能选择安全选项（如 "No", "Prefer not to answer"）
"""

import re
import json
import os
import base64
import requests
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum


class FieldCategory(Enum):
    """字段类别 - 用于区分必须由用户提供的字段和可以自动处理的字段"""
    USER_REQUIRED = "user_required"  # 必须由用户提供的个人信息
    CHOICE_FIELD = "choice_field"    # 选择框类字段，可以智能选择
    OPTIONAL = "optional"            # 可选字段


@dataclass
class MissingField:
    """缺失字段信息"""
    field_id: str
    field_label: str
    field_type: str
    category: FieldCategory
    reason: str = ""


@dataclass 
class FieldMatchResult:
    """字段匹配结果"""
    matched_fields: Dict[str, Any] = field(default_factory=dict)
    missing_fields: List[MissingField] = field(default_factory=list)
    skipped_fields: List[str] = field(default_factory=list)
    statistics: Dict[str, int] = field(default_factory=dict)


class FieldMatcher:
    """字段匹配器 - 将 HTML 字段与 Payload 数据匹配"""
    
    def __init__(self, payload_data: Dict[str, Any], verbose: bool = True):
        """
        初始化匹配器
        
        Args:
            payload_data: Payload 中的 "data" 部分 {field_id: value}
            verbose: 是否打印详细日志
        """
        self.payload_data = payload_data or {}
        self.verbose = verbose
        self.normalized_fields = self._normalize_field_names()
    
    def log(self, message: str, level: str = "INFO"):
        """打印日志"""
        if not self.verbose:
            return
        
        prefix = {
            "INFO": "ℹ️",
            "DEBUG": "📝",
            "MATCH": "✓",
            "NOMATCH": "✗",
            "ERROR": "❌",
            "WARN": "⚠️",
        }.get(level, "→")
        print(f"    {prefix} [FieldMatcher] {message}")
    
    def _normalize_field_names(self) -> Dict[str, str]:
        """将 payload 中的字段名标准化"""
        normalized = {}
        for field_id, value in self.payload_data.items():
            normalized_id = re.sub(r'[_\-\s]', '', field_id).lower()
            normalized[normalized_id] = field_id
        return normalized
    
    def match_field(self, html_field_id: str, html_label: str = "") -> Tuple[bool, Optional[str], Optional[Any]]:
        """
        匹配单个 HTML 字段与 Payload 中的数据
        
        Returns:
            (是否匹配, payload_field_id, payload_value)
        """
        # 方法 1: 直接匹配
        if html_field_id in self.payload_data:
            value = self.payload_data[html_field_id]
            if value not in [None, "", []]:
                self.log(f"直接匹配: {html_field_id}", "MATCH")
                return True, html_field_id, value
        
        # 方法 2: 标准化匹配
        normalized_html_id = re.sub(r'[_\-\s]', '', html_field_id).lower()
        if normalized_html_id in self.normalized_fields:
            payload_field_id = self.normalized_fields[normalized_html_id]
            value = self.payload_data[payload_field_id]
            if value not in [None, "", []]:
                self.log(f"标准化匹配: {html_field_id} → {payload_field_id}", "MATCH")
                return True, payload_field_id, value
        
        # 方法 3: 标签文本匹配
        if html_label:
            label_normalized = re.sub(r'[_\-\s*]', '', html_label).lower()
            for normalized_id, payload_field_id in self.normalized_fields.items():
                if normalized_id in label_normalized or label_normalized in normalized_id:
                    value = self.payload_data[payload_field_id]
                    if value not in [None, "", []]:
                        self.log(f"标签匹配: {html_label} → {payload_field_id}", "MATCH")
                        return True, payload_field_id, value
        
        # 方法 4: 语义匹配（在 payload 中搜索相关字段）
        search_terms = self._extract_search_terms(html_field_id, html_label)
        for term in search_terms:
            for payload_field_id, value in self.payload_data.items():
                if term in payload_field_id.lower() and value not in [None, "", []]:
                    self.log(f"语义匹配 ({term}): {html_field_id} → {payload_field_id}", "MATCH")
                    return True, payload_field_id, value
        
        self.log(f"未找到匹配: {html_field_id}", "NOMATCH")
        return False, None, None
    
    def _extract_search_terms(self, field_id: str, field_label: str) -> List[str]:
        """提取用于搜索的关键词"""
        combined = f"{field_id} {field_label}".lower()
        terms = []
        
        # 常见字段映射
        mappings = {
            'first': ['firstname', 'first_name', 'given_name', 'givenname'],
            'last': ['lastname', 'last_name', 'surname', 'family_name'],
            'email': ['email', 'email_address', 'mail'],
            'phone': ['phone', 'telephone', 'tel', 'mobile', 'phone_number'],
            'address': ['address', 'street', 'street_address'],
            'city': ['city'],
            'state': ['state', 'province', 'region'],
            'zip': ['zip', 'zipcode', 'postal', 'postal_code'],
            'country': ['country', 'nation'],
            'birth': ['birth_date', 'birthday', 'dob', 'date_of_birth'],
            'gender': ['gender', 'sex'],
        }
        
        for key, related in mappings.items():
            if key in combined:
                terms.extend(related)
        
        return terms


class ChoiceFieldHandler:
    """选择框字段处理器 - 仅处理选择框类字段"""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
    
    def log(self, message: str, level: str = "INFO"):
        if not self.verbose:
            return
        prefix = {"INFO": "ℹ️", "DEBUG": "📝", "CHOICE": "☑️"}.get(level, "→")
        print(f"    {prefix} [ChoiceHandler] {message}")
    
    def handle_choice_field(
        self, 
        field_id: str, 
        field_label: str, 
        field_type: str, 
        options: List[Dict] = None
    ) -> Tuple[Optional[str], str]:
        """
        处理选择框类字段
        
        策略:
        1. 对于敏感问题，选择安全选项（No, Prefer not to answer 等）
        2. 对于必须勾选的同意框，选择同意
        3. 其他情况返回 None，标记为需要用户选择
        
        Returns:
            (value, reason) - 值和选择原因，value 为 None 表示需要用户选择
        """
        field_lower = f"{field_id} {field_label}".lower()
        
        # 1. 确认/同意类复选框 - 必须勾选
        if field_type == 'checkbox':
            agree_keywords = [
                'agree', 'accept', 'acknowledge', 'confirm', 'consent',
                'understand', 'certify', 'terms', 'condition', 'declaration',
                'authorization', 'policy', 'privacy'
            ]
            for kw in agree_keywords:
                if kw in field_lower:
                    self.log(f"同意类复选框: {field_id} → true", "CHOICE")
                    return 'true', 'agreement_checkbox'
            # 其他复选框默认不勾选
            return 'false', 'default_unchecked'
        
        # 2. 敏感问题 - 选择 No 或安全选项
        sensitive_keywords = [
            'felony', 'conviction', 'criminal', 'disciplinary', 'expelled',
            'suspended', 'violation', 'disability', 'accommodation', 'veteran',
            'military', 'armed forces', 'transgender'
        ]
        for kw in sensitive_keywords:
            if kw in field_lower:
                safe_value = self._find_safe_option(options, ['no', 'false', 'none'])
                if safe_value:
                    self.log(f"敏感问题: {field_id} → {safe_value}", "CHOICE")
                    return safe_value, 'sensitive_question_safe_answer'
        
        # 3. 隐私相关问题 - 选择不提供
        privacy_keywords = [
            'sexual orientation', 'gender identity', 'race', 'ethnicity',
            'religion', 'political', 'income', 'salary', 'marital'
        ]
        for kw in privacy_keywords:
            if kw in field_lower:
                prefer_not = self._find_safe_option(
                    options, 
                    ['prefer not', 'decline', 'not to answer', 'not specified', 'n/a']
                )
                if prefer_not:
                    self.log(f"隐私问题: {field_id} → {prefer_not}", "CHOICE")
                    return prefer_not, 'privacy_question_decline'
        
        # 4. 有选项列表但不是敏感问题 - 返回 None，需要用户选择
        if options and len(options) > 0:
            return None, 'requires_user_selection'
        
        return None, 'unknown_choice_field'
    
    def _find_safe_option(self, options: List[Dict], keywords: List[str]) -> Optional[str]:
        """在选项中查找安全选项"""
        if not options:
            return None
        
        for opt in options:
            opt_text = (opt.get('text') or opt.get('data_text') or opt.get('value') or '').lower()
            for kw in keywords:
                if kw in opt_text:
                    return opt.get('value') or opt.get('text') or opt.get('data_text')
        return None


class SmartFieldMatcher:
    """
    智能字段匹配器 (生产版本)
    
    核心原则:
    - 只匹配用户已提供的数据
    - 缺失的用户信息必须返回给前端让用户补充
    - 绝不生成虚假的用户个人信息
    """
    
    # 必须由用户提供的字段类型（不能自动生成）
    USER_REQUIRED_PATTERNS = [
        'first', 'last', 'name', 'given', 'surname', 'family',  # 姓名
        'email', 'mail',  # 邮箱
        'phone', 'tel', 'mobile',  # 电话
        'address', 'street', 'city', 'state', 'province', 'zip', 'postal', 'country',  # 地址
        'birth', 'dob', 'birthday',  # 出生日期
        'passport', 'visa', 'ssn', 'social security',  # 证件
        'gpa', 'score', 'test',  # 成绩
        'school', 'university', 'college', 'institution',  # 学校
        'degree', 'major', 'program',  # 学位
        'employer', 'company', 'work', 'job',  # 工作
    ]
    
    def __init__(
        self, 
        payload_data: Dict[str, Any], 
        verbose: bool = True,
        use_llm: bool = True,
        llm_api_key: Optional[str] = None,
        llm_model: str = "anthropic/claude-3.5-sonnet",
        vlm_model: str = "anthropic/claude-3.5-sonnet",
        persist_generated: bool = False,
        payload_file_path: Optional[str] = None
    ):
        self.payload_data = payload_data or {}
        self.verbose = verbose
        self.llm_api_key = llm_api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        self.use_llm = use_llm and bool(self.llm_api_key)
        self.llm_base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        self.llm_model = llm_model
        self.vlm_model = vlm_model
        self.persist_generated = persist_generated
        self.payload_file_path = Path(payload_file_path) if payload_file_path else None

        self.matcher = FieldMatcher(payload_data, verbose)
        self.choice_handler = ChoiceFieldHandler(verbose)
        
        # 统计
        self.matched_count = 0
        self.missing_count = 0
        self.choice_count = 0
        self.llm_matched_count = 0
        
        # 缺失字段列表
        self.missing_fields: List[MissingField] = []
        
        # LLM 缓存
        self._llm_cache = {}
        
        if self.use_llm:
            self.log(f"✅ LLM 智能匹配已启用 (模型: {self.llm_model})", "INFO")
        else:
            self.log("⚠️ LLM 智能匹配未启用", "INFO")
    
    def log(self, message: str, level: str = "INFO"):
        if not self.verbose:
            return
        prefix = {
            "INFO": "ℹ️", "SUMMARY": "📊", "LLM": "🤖",
            "WARN": "⚠️", "ERROR": "❌", "MISSING": "🚨"
        }.get(level, "→")
        print(f"  {prefix} {message}")
    
    def _is_user_required_field(self, field_id: str, field_label: str) -> bool:
        """判断是否是必须由用户提供的字段"""
        combined = f"{field_id} {field_label}".lower()
        return any(pattern in combined for pattern in self.USER_REQUIRED_PATTERNS)
    
    def _is_choice_field(self, field_type: str) -> bool:
        """判断是否是选择框类字段"""
        return field_type in ['radio', 'checkbox', 'select', 'select-one']
    
    def _use_llm_for_matching(self, html_fields: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """使用 LLM 进行智能字段匹配"""
        if not self.use_llm or not self.llm_api_key:
            return None
        
        try:
            self.log("正在使用 LLM 进行智能匹配...", "LLM")
            
            system_prompt = """你是一个专家表单字段分析器。将 HTML 表单字段与 Payload 数据进行语义匹配。

重要规则：
1. 只匹配 Payload 中已存在的字段
2. 如果找不到匹配，返回 null（不要编造值）
3. 基于语义含义匹配，而非精确文本

返回 JSON 格式:
{
  "matches": {"html_field_id": "payload_field_id 或 null"},
  "confidence": 0.0-1.0
}"""
            
            user_prompt = f"""匹配字段：

HTML 表单字段：
{json.dumps(html_fields, ensure_ascii=False, indent=2)}

Payload 可用字段和值：
{json.dumps(self.payload_data, ensure_ascii=False, indent=2)}

为每个 HTML 字段找到最匹配的 Payload 字段。如果没有匹配，返回 null。"""
            
            response = requests.post(
                self.llm_base_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.llm_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 2000
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    llm_result = json.loads(content[start:end])
                    matches = llm_result.get("matches", {})
                    self.log(f"LLM 匹配完成", "LLM")
                    return matches
        
        except Exception as e:
            self.log(f"LLM 匹配失败: {e}", "ERROR")
        
        return None
    
    def process_fields(self, html_fields: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        处理 HTML 字段
        
        返回:
            {
                "values": {field_id: value},  # 成功匹配的字段值
                "missing_fields": [MissingField],  # 缺失的必填字段
                "statistics": {...}
            }
        """
        self.log("开始字段匹配...", "INFO")
        self.matched_count = 0
        self.missing_count = 0
        self.choice_count = 0
        self.missing_fields = []
        
        final_values = {}
        
        # 第 1 步: 尝试 LLM 匹配
        llm_matches = {}
        if self.use_llm:
            llm_matches = self._use_llm_for_matching(html_fields) or {}
        
        # 第 2 步: 处理每个字段
        for field in html_fields:
            field_id = field.get('id') or field.get('name') or ""
            field_label = field.get('label') or ""
            field_type = field.get('type') or ""
            field_options = field.get('options', [])
            
            if not field_id:
                continue
            
            value = None
            source = None
            
            # 2.1 尝试从 LLM 匹配结果获取
            if field_id in llm_matches and llm_matches[field_id]:
                payload_key = llm_matches[field_id]
                if payload_key in self.payload_data:
                    value = self.payload_data[payload_key]
                    if value not in [None, "", []]:
                        source = "llm_match"
                        self.llm_matched_count += 1
            
            # 2.2 尝试规则匹配
            if value is None:
                matched, _, matched_value = self.matcher.match_field(field_id, field_label)
                if matched and matched_value not in [None, "", []]:
                    value = matched_value
                    source = "rule_match"
            
            # 2.3 处理未匹配的字段
            if value is None:
                if self._is_choice_field(field_type):
                    # 选择框类字段 - 尝试智能选择
                    choice_value, reason = self.choice_handler.handle_choice_field(
                        field_id, field_label, field_type, field_options
                    )
                    if choice_value is not None:
                        value = choice_value
                        source = f"auto_choice:{reason}"
                        self.choice_count += 1
                    else:
                        # 需要用户选择
                        self.missing_fields.append(MissingField(
                            field_id=field_id,
                            field_label=field_label,
                            field_type=field_type,
                            category=FieldCategory.CHOICE_FIELD,
                            reason=reason
                        ))
                        self.missing_count += 1
                        self.log(f"🚨 需要用户选择: {field_id} ({field_label})", "MISSING")
                
                elif self._is_user_required_field(field_id, field_label):
                    # 用户必填字段 - 标记为缺失
                    self.missing_fields.append(MissingField(
                        field_id=field_id,
                        field_label=field_label,
                        field_type=field_type,
                        category=FieldCategory.USER_REQUIRED,
                        reason="用户必填信息缺失"
                    ))
                    self.missing_count += 1
                    self.log(f"🚨 用户信息缺失: {field_id} ({field_label})", "MISSING")
                
                else:
                    # 可选字段 - 留空
                    self.log(f"可选字段留空: {field_id}", "INFO")
            
            # 记录匹配成功的字段
            if value is not None:
                final_values[field_id] = value
                self.matched_count += 1
                self.log(f"✓ {field_id} = {str(value)[:50]} ({source})", "INFO")
        
        # 第 3 步: 统计报告
        self.log(
            f"处理完成: {self.matched_count} 匹配, {self.choice_count} 自动选择, "
            f"{self.missing_count} 缺失",
            "SUMMARY"
        )
        
        if self.missing_fields:
            self.log(f"⚠️ 有 {len(self.missing_fields)} 个字段需要用户提供", "WARN")
        
        return final_values
    
    def get_missing_fields(self) -> List[Dict[str, Any]]:
        """获取缺失字段列表（供前端展示）"""
        return [
            {
                "field_id": f.field_id,
                "field_label": f.field_label,
                "field_type": f.field_type,
                "category": f.category.value,
                "reason": f.reason
            }
            for f in self.missing_fields
        ]
    
    def has_missing_required_fields(self) -> bool:
        """检查是否有必须由用户提供的缺失字段"""
        return any(
            f.category == FieldCategory.USER_REQUIRED 
            for f in self.missing_fields
        )


# 兼容旧版本的类名
ValueGenerator = ChoiceFieldHandler


if __name__ == "__main__":
    # 测试用例
    demo_payload = {
        "first_name": "张",
        "last_name": "三",
        "email": "zhangsan@example.com",
        "phone": "+86-138-0000-0000",
    }
    
    demo_fields = [
        {"id": "firstName", "label": "First Name", "type": "text"},
        {"id": "lastName", "label": "Last Name", "type": "text"},
        {"id": "email_address", "label": "Email", "type": "email"},
        {"id": "phone_number", "label": "Phone", "type": "tel"},
        {"id": "city", "label": "City", "type": "text"},  # 缺失
        {"id": "agree_terms", "label": "I agree to terms", "type": "checkbox"},
        {"id": "veteran_status", "label": "Are you a veteran?", "type": "radio", 
         "options": [{"value": "yes", "text": "Yes"}, {"value": "no", "text": "No"}]},
    ]
    
    matcher = SmartFieldMatcher(demo_payload, use_llm=False)
    results = matcher.process_fields(demo_fields)
    
    print("\n=== 匹配结果 ===")
    for field_id, value in results.items():
        print(f"  {field_id}: {value}")
    
    print("\n=== 缺失字段 ===")
    for missing in matcher.get_missing_fields():
        print(f"  {missing['field_id']}: {missing['reason']}")
    
    print(f"\n需要用户补充: {matcher.has_missing_required_fields()}")
