"""
字段提取器 - 从 HTML 页面提取表单字段

功能：
1. 解析 HTML 提取所有表单字段
2. 正确处理 radio/checkbox（合并为一个字段，选项存入 options）
3. 存入 university_fields 表
"""

import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import defaultdict
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class FieldExtractor:
    """表单字段提取器"""
    
    def __init__(self, db=None):
        self.db = db
        self.extracted_fields: List[Dict] = []
    
    def extract_from_html(self, html_content: str, page_number: int = 1) -> List[Dict]:
        """从 HTML 内容提取表单字段"""
        soup = BeautifulSoup(html_content, 'html.parser')
        fields = []
        
        # 1. 提取普通 input 字段（text, email, date, file 等）
        for input_elem in soup.find_all('input'):
            input_type = input_elem.get('type', 'text').lower()
            
            # radio/checkbox 单独处理
            if input_type in ['radio', 'checkbox']:
                continue
            
            field = self._parse_input_element(input_elem, page_number)
            if field:
                fields.append(field)
        
        # 2. 提取 radio 字段（按 name 分组合并）
        radio_fields = self._parse_radio_checkbox_group(soup, 'radio', page_number)
        fields.extend(radio_fields)
        
        # 3. 提取 checkbox 字段（按 name 分组合并）
        checkbox_fields = self._parse_radio_checkbox_group(soup, 'checkbox', page_number)
        fields.extend(checkbox_fields)
        
        # 4. 提取 select 字段
        for select_elem in soup.find_all('select'):
            field = self._parse_select_element(select_elem, page_number)
            if field:
                fields.append(field)
        
        # 5. 提取 textarea 字段
        for textarea_elem in soup.find_all('textarea'):
            field = self._parse_textarea_element(textarea_elem, page_number)
            if field:
                fields.append(field)
        
        # 6. 去重
        seen_ids = set()
        unique_fields = []
        for f in fields:
            if f['field_id'] not in seen_ids:
                seen_ids.add(f['field_id'])
                unique_fields.append(f)
        
        self.extracted_fields.extend(unique_fields)
        return unique_fields
    
    def _parse_radio_checkbox_group(
        self, 
        soup: BeautifulSoup, 
        input_type: str, 
        page_number: int
    ) -> List[Dict]:
        """
        解析 radio/checkbox 组
        
        关键：同一个 name 的所有选项合并为一个字段
        """
        fields = []
        
        # 按 name 分组
        elements = soup.find_all('input', {'type': input_type})
        groups = defaultdict(list)
        
        for elem in elements:
            name = elem.get('name', '')
            if name:
                groups[name].append(elem)
        
        # 每个组生成一个字段
        for name, elems in groups.items():
            if not elems:
                continue
            
            first_elem = elems[0]
            
            # 获取问题的 label（通常在 fieldset/legend 或上级元素中）
            question_label = self._find_group_label(first_elem, soup)
            
            # 收集所有选项
            options = []
            for elem in elems:
                value = elem.get('value', '')
                # 选项的 label
                option_label = self._find_label(elem) or value
                if value or option_label:
                    options.append({
                        'value': value,
                        'text': option_label
                    })
            
            # 判断是否必填
            is_required = any(
                elem.get('required') is not None or 
                elem.get('aria-required') == 'true'
                for elem in elems
            )
            
            fields.append({
                'field_id': name,  # 使用 name 作为字段 ID
                'field_name': name,
                'field_label': question_label,
                'field_type': input_type,
                'placeholder': '',
                'page_number': page_number,
                'is_required': is_required,
                'options': options if options else None,
            })
        
        return fields
    
    def _find_group_label(self, elem, soup: BeautifulSoup) -> Optional[str]:
        """查找 radio/checkbox 组的问题标签"""
        # 方式1: 查找包含的 fieldset > legend
        fieldset = elem.find_parent('fieldset')
        if fieldset:
            legend = fieldset.find('legend')
            if legend:
                return legend.get_text(strip=True)
        
        # 方式2: 查找同级或上级的 label/span/div 包含问题文本
        for parent in elem.parents:
            # 查找 class 包含 label/question 的元素
            label_elem = parent.find(class_=re.compile(r'label|question|title', re.I))
            if label_elem and label_elem.get_text(strip=True):
                text = label_elem.get_text(strip=True)
                # 排除选项文本（通常很短）
                if len(text) > 10:
                    return text
            
            # 限制查找深度
            if parent.name in ['form', 'body']:
                break
        
        # 方式3: 使用 aria-label
        aria = elem.get('aria-label') or elem.get('aria-labelledby')
        if aria:
            return aria
        
        return None
    
    def _parse_input_element(self, elem, page_number: int) -> Optional[Dict]:
        """解析普通 input 元素（非 radio/checkbox）"""
        input_type = elem.get('type', 'text').lower()
        
        # 跳过隐藏字段和按钮
        if input_type in ['hidden', 'submit', 'button', 'reset', 'image', 'radio', 'checkbox']:
            return None
        
        field_id = elem.get('id') or elem.get('name') or ''
        if not field_id:
            return None
        
        label = self._find_label(elem)
        
        is_required = (
            elem.get('required') is not None or
            elem.get('aria-required') == 'true' or
            '*' in (label or '')
        )
        
        # 映射字段类型
        field_type = 'text'
        if input_type == 'email':
            field_type = 'email'
        elif input_type == 'date':
            field_type = 'date'
        elif input_type == 'file':
            field_type = 'file'
        elif input_type == 'number':
            field_type = 'number'
        
        return {
            'field_id': field_id,
            'field_name': elem.get('name', ''),
            'field_label': label,
            'field_type': field_type,
            'placeholder': elem.get('placeholder', ''),
            'page_number': page_number,
            'is_required': is_required,
            'options': None,
        }
    
    def _parse_select_element(self, elem, page_number: int) -> Optional[Dict]:
        """解析 select 元素"""
        field_id = elem.get('id') or elem.get('name') or ''
        if not field_id:
            return None
        
        label = self._find_label(elem)
        
        options = []
        for option in elem.find_all('option'):
            value = option.get('value', '')
            text = option.get_text(strip=True)
            if value or text:
                options.append({'value': value, 'text': text})
        
        is_required = (
            elem.get('required') is not None or
            elem.get('aria-required') == 'true' or
            '*' in (label or '')
        )
        
        return {
            'field_id': field_id,
            'field_name': elem.get('name', ''),
            'field_label': label,
            'field_type': 'select',
            'placeholder': '',
            'page_number': page_number,
            'is_required': is_required,
            'options': options if options else None,
        }
    
    def _parse_textarea_element(self, elem, page_number: int) -> Optional[Dict]:
        """解析 textarea 元素"""
        field_id = elem.get('id') or elem.get('name') or ''
        if not field_id:
            return None
        
        label = self._find_label(elem)
        
        is_required = (
            elem.get('required') is not None or
            '*' in (label or '')
        )
        
        return {
            'field_id': field_id,
            'field_name': elem.get('name', ''),
            'field_label': label,
            'field_type': 'textarea',
            'placeholder': elem.get('placeholder', ''),
            'page_number': page_number,
            'is_required': is_required,
            'options': None,
        }
    
    def _find_label(self, elem) -> Optional[str]:
        """查找元素的 label"""
        elem_id = elem.get('id')
        
        # 方式1: 通过 for 属性关联的 label
        if elem_id:
            for parent in elem.parents:
                label = parent.find('label', {'for': elem_id})
                if label:
                    return label.get_text(strip=True)
                if parent.name in ['form', 'body']:
                    break
        
        # 方式2: 包裹的 label
        parent_label = elem.find_parent('label')
        if parent_label:
            return parent_label.get_text(strip=True)
        
        # 方式3: aria-label
        aria_label = elem.get('aria-label')
        if aria_label:
            return aria_label
        
        # 方式4: placeholder
        placeholder = elem.get('placeholder')
        if placeholder:
            return placeholder
        
        return None
    
    def save_to_database(self, uni_id: str, page_title: Optional[str] = None) -> int:
        """保存提取的字段到数据库"""
        if not self.db:
            raise ValueError("Database not configured")
        
        saved_count = 0
        for field in self.extracted_fields:
            try:
                field_data = {
                    'uni_id': uni_id,
                    'field_id': field['field_id'],
                    'field_name': field.get('field_name'),
                    'field_label': field.get('field_label'),
                    'field_type': field.get('field_type'),
                    'placeholder': field.get('placeholder'),
                    'page_number': field.get('page_number'),
                    'page_title': page_title,
                    'is_required': field.get('is_required', False),
                    'options': field.get('options'),
                }
                
                self.db.upsert_university_field(uni_id, field_data)
                saved_count += 1
                
            except Exception as e:
                print(f"⚠️ 保存字段 {field['field_id']} 失败: {e}")
        
        return saved_count
    
    def get_summary(self) -> Dict:
        """获取提取结果摘要"""
        total = len(self.extracted_fields)
        by_type = {}
        required = 0
        
        for field in self.extracted_fields:
            ftype = field.get('field_type', 'unknown')
            by_type[ftype] = by_type.get(ftype, 0) + 1
            
            if field.get('is_required'):
                required += 1
        
        return {
            'total': total,
            'by_type': by_type,
            'required': required,
        }
    
    def to_json(self) -> str:
        """导出为 JSON"""
        return json.dumps(self.extracted_fields, ensure_ascii=False, indent=2)


def extract_fields_from_html_file(html_path: Path, page_number: int = 1) -> List[Dict]:
    """从 HTML 文件提取字段"""
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    extractor = FieldExtractor()
    return extractor.extract_from_html(html_content, page_number)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="从 HTML 提取表单字段")
    parser.add_argument("html_file", type=str, help="HTML 文件路径")
    parser.add_argument("--page", type=int, default=1, help="页码")
    args = parser.parse_args()
    
    html_path = Path(args.html_file)
    if not html_path.exists():
        print(f"❌ 文件不存在: {html_path}")
        sys.exit(1)
    
    fields = extract_fields_from_html_file(html_path, args.page)
    
    print(f"\n✅ 提取到 {len(fields)} 个字段:\n")
    for f in fields:
        req = "*" if f.get('is_required') else " "
        opts = f"({len(f['options'])}选项)" if f.get('options') else ""
        print(f"  {req} {f['field_type']:10} {opts:10} | {f.get('field_label', '')[:50]}")
