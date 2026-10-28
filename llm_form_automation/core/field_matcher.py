"""
字段匹配器 - 使用 LLM 进行语义匹配

核心原则（留学申请）：
1. 所有填写的信息必须有可靠来源
2. 使用 LLM 进行语义匹配
3. LLM 判断结果只有两种：可填写 / 需用户提供
4. 不确定的一律归为"需用户提供"
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class FieldStatus(Enum):
    """字段状态（二分类）"""
    CAN_FILL = "can_fill"          # 可以直接填写
    NEEDS_USER = "needs_user"      # 需要用户提供


@dataclass
class FieldMapping:
    """单个字段的映射结果"""
    field_id: str
    field_label: Optional[str]
    field_type: str
    page_number: int
    is_required: bool
    
    status: FieldStatus
    
    # 可填写时的值
    value: Optional[str] = None
    source_field: Optional[str] = None  # 来源（用户信息中的字段名）
    
    # LLM 给出的理由
    reason: Optional[str] = None
    
    # 选择类字段的选项（供用户参考）
    options: Optional[List[Dict]] = None


@dataclass
class MappingReport:
    """映射报告"""
    total_fields: int = 0
    can_fill: List[FieldMapping] = field(default_factory=list)    # 可直接填写
    needs_user: List[FieldMapping] = field(default_factory=list)  # 需用户提供
    
    def to_dict(self) -> Dict:
        return {
            "total_fields": self.total_fields,
            "can_fill_count": len(self.can_fill),
            "needs_user_count": len(self.needs_user),
            "can_proceed": len(self.needs_user) == 0,
            "can_fill": [
                {
                    "field_id": f.field_id,
                    "field_label": f.field_label,
                    "value": f.value,
                    "source": f.source_field,
                    "reason": f.reason,
                }
                for f in self.can_fill
            ],
            "needs_user": [
                {
                    "field_id": f.field_id,
                    "field_label": f.field_label,
                    "field_type": f.field_type,
                    "is_required": f.is_required,
                    "options": f.options,
                    "reason": f.reason,
                }
                for f in self.needs_user
            ],
        }


class FieldMatcher:
    """
    字段匹配器
    
    使用 LLM 进行语义匹配，结果只有两种：可填写 / 需用户提供
    """
    
    # user_application_info 的字段说明
    USER_FIELD_DESCRIPTIONS = {
        "legal_first_name": "法定名（名字部分）",
        "legal_last_name": "法定姓（姓氏部分）",
        "legal_middle_name": "法定中间名",
        "legal_suffix": "姓名后缀（如 Jr., Sr.）",
        "lived_first_name": "常用名（名字部分）",
        "lived_last_name": "常用姓",
        "lived_middle_name": "常用中间名",
        "lived_suffix": "常用名后缀",
        "email": "电子邮箱",
        "phone": "电话号码",
        "birth_date": "出生日期",
        "birth_country": "出生国家",
        "birth_city": "出生城市",
        "citizenship": "国籍/公民身份",
        "dual_citizenship": "双重国籍",
        "visa_status_current": "当前签证状态",
        "visa_status_expected": "预期签证状态",
        "gender_identity": "性别认同",
        "pronouns": "人称代词",
        "gpa_major": "专业GPA",
        "gpa_advanced": "高级课程GPA",
        "gpa_major_field": "专业领域",
        "native_language": "母语",
        "doc_statement_of_purpose": "个人陈述",
        "doc_personal_history": "个人历史陈述",
        "doc_resume": "简历",
        "parent1_education": "父母1最高学历",
        "parent2_education": "父母2最高学历",
    }
    
    def __init__(self, db=None, llm_client=None):
        self.db = db
        self.llm_client = llm_client
    
    async def match_fields(
        self,
        user_info: Dict[str, Any],
        form_fields: List[Dict[str, Any]]
    ) -> MappingReport:
        """
        使用 LLM 进行字段映射
        
        返回：可填写的字段 + 需用户提供的字段
        """
        report = MappingReport(total_fields=len(form_fields))
        
        if not self.llm_client:
            # 没有 LLM，所有字段都需要用户提供
            for f in form_fields:
                report.needs_user.append(FieldMapping(
                    field_id=f.get('field_id', ''),
                    field_label=f.get('field_label'),
                    field_type=f.get('field_type', 'text'),
                    page_number=f.get('page_number', 0),
                    is_required=f.get('is_required', False),
                    status=FieldStatus.NEEDS_USER,
                    options=f.get('options'),
                    reason="LLM 不可用",
                ))
            return report
        
        # 调用 LLM
        prompt = self._build_prompt(user_info, form_fields)
        messages = [
            {"role": "system", "content": "你是表单填写助手。只输出 JSON。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            # 使用 requests 直接调用 API
            import requests
            
            headers = {
                "Authorization": f"Bearer {self.llm_client['api_key']}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": self.llm_client["model"],
                "messages": messages,
                "temperature": 0
            }
            
            response = requests.post(
                f"{self.llm_client['base_url']}/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                self._parse_response(content, form_fields, report)
            else:
                print(f"⚠️ API 调用失败: {response.status_code} - {response.text}")
                raise Exception(f"API Error: {response.status_code}")
                
        except Exception as e:
            print(f"⚠️ LLM 调用失败: {e}")
            for f in form_fields:
                report.needs_user.append(FieldMapping(
                    field_id=f.get('field_id', ''),
                    field_label=f.get('field_label'),
                    field_type=f.get('field_type', 'text'),
                    page_number=f.get('page_number', 0),
                    is_required=f.get('is_required', False),
                    status=FieldStatus.NEEDS_USER,
                    options=f.get('options'),
                    reason=f"LLM 错误: {str(e)}",
                ))
        
        return report
    
    def _build_prompt(
        self,
        user_info: Dict[str, Any],
        form_fields: List[Dict[str, Any]]
    ) -> str:
        """构建 LLM prompt"""
        
        # 用户信息
        user_text = "## 用户信息\n\n"
        has_info = False
        for name, value in user_info.items():
            if value and name not in ['id', 'user_id', 'created_at', 'updated_at', 'completeness_score']:
                desc = self.USER_FIELD_DESCRIPTIONS.get(name, name)
                user_text += f"- {name} ({desc}): `{value}`\n"
                has_info = True
        
        if not has_info:
            user_text += "（用户尚未提供任何信息）\n"
        
        # 表单字段
        fields_text = "## 表单字段\n\n"
        for i, f in enumerate(form_fields, 1):
            req = "**必填**" if f.get('is_required') else "可选"
            fields_text += f"\n### {i}. {f.get('field_label', '(无标签)')}\n"
            fields_text += f"- field_id: `{f.get('field_id')}`\n"
            fields_text += f"- type: {f.get('field_type')}, {req}\n"
            
            options = f.get('options', [])
            if options:
                # 数据库中 options 可能是 JSON 字符串
                if isinstance(options, str):
                    import json
                    try:
                        options = json.loads(options)
                    except:
                        options = []
                
                if options:
                    fields_text += "- options:\n"
                    for opt in options[:6]:
                        if isinstance(opt, dict):
                            fields_text += f"  - `{opt.get('value')}`: {opt.get('text')}\n"
                        else:
                            fields_text += f"  - `{opt}`\n"
                    if len(options) > 6:
                        fields_text += f"  - ...(共{len(options)}个)\n"
        
        return f"""请将用户信息映射到表单字段。

{user_text}

{fields_text}

## 规则

1. **只用用户提供的信息**，不能编造
2. **同义词可映射**：如 Male → Man、phone → Mobile Phone / Primary Phone
3. **一对多映射**：用户的一个字段可以填多个表单字段，如 phone 同时用于 Primary Phone 和 Mobile Phone
4. **语义理解**：理解字段含义，如 "phone" 可映射到任何电话相关字段
5. **不确定就标 needs_user**
6. **没有信息就标 needs_user**

## 输出 JSON

```json
[
  {{
    "field_id": "xxx",
    "can_fill": true或false,
    "value": "要填的值（can_fill=true时）",
    "source_field": "来源字段名（可选）",
    "reason": "简短说明"
  }}
]
```

can_fill=true: 可以直接填写
can_fill=false: 需要用户提供

开始："""
    
    def _parse_response(
        self,
        response: str,
        form_fields: List[Dict[str, Any]],
        report: MappingReport
    ) -> None:
        """解析 LLM 响应"""
        
        try:
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            else:
                json_str = response
            
            mappings = json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError) as e:
            print(f"⚠️ JSON 解析失败: {e}")
            for f in form_fields:
                report.needs_user.append(FieldMapping(
                    field_id=f.get('field_id', ''),
                    field_label=f.get('field_label'),
                    field_type=f.get('field_type', 'text'),
                    page_number=f.get('page_number', 0),
                    is_required=f.get('is_required', False),
                    status=FieldStatus.NEEDS_USER,
                    options=f.get('options'),
                    reason="解析失败",
                ))
            return
        
        # field_id → LLM结果
        llm_map = {m.get('field_id'): m for m in mappings}
        
        for f in form_fields:
            field_id = f.get('field_id', '')
            llm = llm_map.get(field_id, {})
            can_fill = llm.get('can_fill', False)
            
            mapping = FieldMapping(
                field_id=field_id,
                field_label=f.get('field_label'),
                field_type=f.get('field_type', 'text'),
                page_number=f.get('page_number', 0),
                is_required=f.get('is_required', False),
                status=FieldStatus.CAN_FILL if can_fill else FieldStatus.NEEDS_USER,
                value=llm.get('value') if can_fill else None,
                source_field=llm.get('source_field'),
                reason=llm.get('reason'),
                options=f.get('options'),
            )
            
            if can_fill:
                report.can_fill.append(mapping)
            else:
                report.needs_user.append(mapping)
    
    def generate_payload(
        self,
        report: MappingReport,
        user_provided: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        生成填表 Payload
        
        Args:
            report: 映射报告
            user_provided: 用户补充的数据
        """
        from datetime import datetime
        
        payload = {
            "data": {},
            "generated_at": datetime.now().isoformat(),
        }
        
        # 添加可填写的字段
        for m in report.can_fill:
            if m.value:
                payload["data"][m.field_id] = m.value
        
        # 添加用户补充的数据
        if user_provided:
            for field_id, value in user_provided.items():
                if value:
                    payload["data"][field_id] = value
        
        return payload
    
    def generate_full_payload(
        self,
        apply_record_id: int,
        report: MappingReport,
        save_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成完整填表 Payload（合并 LLM 映射结果 + 用户补充值）
        
        Args:
            apply_record_id: 申请记录ID
            report: 映射报告（包含 can_fill 字段）
            save_path: 保存路径（可选），如不指定则自动生成
        
        Returns:
            完整的 payload，包含所有可填写字段的值和文件路径
        """
        from datetime import datetime
        
        payload = {
            "apply_record_id": apply_record_id,
            "fields": {},  # {field_id: {value, label, type, source}}
            "generated_at": datetime.now().isoformat(),
            "stats": {
                "from_user_info": 0,
                "from_user_supplement": 0,
                "total": 0
            }
        }
        
        # 1. 添加 LLM 映射的字段（来自用户信息）
        for m in report.can_fill:
            if m.value:
                payload["fields"][m.field_id] = {
                    "value": m.value,
                    "label": m.field_label,
                    "type": m.field_type,
                    "source": m.source_field or "user_info"
                }
                payload["stats"]["from_user_info"] += 1
        
        # 2. 从数据库获取用户补充的缺失字段值
        if self.db:
            missing_fields = self.db.get_missing_fields(
                apply_record_id, 
                only_unresolved=False  # 获取所有，包括已填写的
            )
            
            for field in missing_fields:
                if field.get("is_resolved") and field.get("resolved_value"):
                    field_id = field["field_id"]
                    payload["fields"][field_id] = {
                        "value": field["resolved_value"],
                        "label": field.get("field_label"),
                        "type": field.get("field_type"),
                        "source": "user_supplement"
                    }
                    payload["stats"]["from_user_supplement"] += 1
        
        payload["stats"]["total"] = len(payload["fields"])
        
        # 3. 保存到文件
        if save_path is None:
            # 自动生成路径: payloads/apply_{id}_{timestamp}.json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = f"payloads/apply_{apply_record_id}_{timestamp}.json"
        
        # 确保目录存在
        save_dir = Path(save_path).parent
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        
        payload["payload_path"] = str(Path(save_path).absolute())
        
        return payload
    
    def save_needs_user_fields(
        self,
        apply_record_id: int,
        report: MappingReport
    ) -> int:
        """保存需要用户提供的字段到数据库（包含完整字段信息）"""
        if not self.db:
            return 0
        
        # 构建完整字段信息列表
        fields = []
        for m in report.needs_user:
            # 解析 options（可能是 JSON 字符串）
            options = m.options
            if options and isinstance(options, str):
                try:
                    options = json.loads(options)
                except:
                    options = None
            
            fields.append({
                "field_id": m.field_id,
                "field_label": m.field_label,
                "field_type": m.field_type,
                "is_required": m.is_required,
                "options": options
            })
        
        return self.db.add_missing_fields_batch(apply_record_id, fields)


def load_payload(payload_path: str) -> Dict[str, Any]:
    """
    加载 payload 文件
    
    Args:
        payload_path: payload 文件路径
    
    Returns:
        payload 数据
    """
    with open(payload_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# 便捷函数
async def match_fields(
    db,
    llm_client,
    user_id: str,
    uni_id: str
) -> Tuple[MappingReport, Dict]:
    """
    执行字段映射
    
    Returns:
        (映射报告, 用户信息)
    """
    user_info = db.get_user_application_info(user_id) or {}
    form_fields = db.get_university_fields(uni_id)
    
    matcher = FieldMatcher(db, llm_client)
    report = await matcher.match_fields(user_info, form_fields)
    
    return report, user_info


if __name__ == "__main__":
    print("""
字段映射器 - 二分类

LLM 判断结果只有两种：
  ✅ can_fill: 可以直接填写
  ❌ needs_user: 需要用户提供

原则：
  - 只用用户提供的信息
  - 同义词可映射（Male → Man）
  - 不确定 → needs_user
  - 无信息 → needs_user
""")
