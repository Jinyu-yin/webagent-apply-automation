"""
LLM 表单填写器核心模块

优化版：
- 批量操作减少 DOM 交互
- 异步 LLM 调用
- 并行填充不相关字段
- 预获取选项信息
"""

import os
import re
import json
import asyncio
import aiohttp
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from playwright.async_api import Page  # type: ignore

from .payload_manager import PayloadManager
from .validators import PrivacyFilter, ValidationChecker
from .intervention import HumanIntervention, SubmissionChecker
from .field_handlers import SpecialFieldHandler, CollapsibleHandler
from .site_configs import get_site_config
from .login_handler import LoginHandler


def _get_llm_config() -> Dict[str, str]:
    """获取 LLM 配置"""
    return {
        "api_key": os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
        "base_url": os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        "llm_model": os.getenv("LLM_MODEL", "anthropic/claude-3.5-sonnet"),
        "vlm_model": os.getenv("VLM_MODEL", "anthropic/claude-3.5-sonnet"),
    }


async def _call_llm_async(api_key: str, base_url: str, model: str, prompt: str, max_tokens: int = 100) -> str:
    """异步调用 LLM 进行智能匹配"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"LLM 异步调用失败: {e}")
    return ""


def _call_llm_for_match(api_key: str, base_url: str, model: str, prompt: str, max_tokens: int = 100) -> str:
    """同步调用 LLM（兼容旧代码）"""
    import requests
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0
            },
            timeout=15
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"LLM 调用失败: {e}")
    return ""


async def _batch_match_options_with_llm_async(
    api_key: str,
    base_url: str,
    model: str,
    fields_to_match: List[Dict]
) -> Dict[str, str]:
    """
    异步批量用 LLM 匹配选项（优化版）

    Args:
        fields_to_match: [{"field_id": str, "value": str, "options": [{"value": str, "text": str}]}]

    Returns:
        {"field_id": "matched_option_value", ...}
    """
    if not fields_to_match:
        return {}

    # 构建批量匹配 prompt
    prompt_parts = [
        "为以下每个字段选择最匹配的选项。",
        "重要：返回JSON格式 {\"field_id\": \"option_value\"}，option_value 必须是选项的 value 值。\n"
    ]

    for f in fields_to_match[:30]:  # 增加到30个字段
        fid = f["field_id"]
        value = f["value"]
        options = f["options"][:15]  # 增加到15个选项
        opt_str = ", ".join([f"{o['value']}({o['text'][:25]})" for o in options])
        prompt_parts.append(f"- {fid}: \"{value}\" -> [{opt_str}]")

    prompt = "\n".join(prompt_parts)

    try:
        # 使用异步调用
        result = await _call_llm_async(api_key, base_url, model, prompt, max_tokens=1200)
        json_match = re.search(r'\{[^{}]+\}', result, re.DOTALL)
        if json_match:
            matched = json.loads(json_match.group())
            result_dict = {}
            for fid, matched_val in matched.items():
                field = next((f for f in fields_to_match if f["field_id"] == fid), None)
                if field:
                    for opt in field["options"]:
                        if matched_val == opt["text"]:
                            result_dict[fid] = opt["value"]
                            break
                        elif matched_val == opt["value"]:
                            result_dict[fid] = matched_val
                            break
                    else:
                        result_dict[fid] = matched_val
                else:
                    result_dict[fid] = matched_val
            return result_dict
    except Exception as e:
        print(f"批量LLM匹配失败: {e}")

    return {}


class LLMFormFiller:
    """LLM 智能表单填写器 - 精简版"""
    
    def __init__(self, payload_path: Path, start_url: str, output_dir: Optional[Path] = None):
        """
        初始化表单填写器
        
        Args:
            payload_path: Payload 文件路径
            start_url: 起始 URL
            output_dir: 输出目录
        """
        if not payload_path:
            raise ValueError("payload_path 是必填参数")
        if not start_url:
            raise ValueError("start_url 是必填参数")
        
        self.payload_path = Path(payload_path)
        self.start_url = start_url
        self.output_dir = output_dir or Path(__file__).parent.parent / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # LLM 配置
        self._llm_config = _get_llm_config()
        
        # Payload 管理
        self.payload_manager = PayloadManager(self.payload_path)
        self.payload_data = self.payload_manager.get_all_fields()
        
        # 填写记录
        self.fill_history: List[Dict] = []
        self.missing_fields: List[Dict] = []
        
        # 站点配置
        self.site_config = get_site_config(start_url)
        
        # 可折叠区域处理器
        self.collapsible_handler = CollapsibleHandler()
        
        # 数据库连接（可选）
        self.db = None
        self.apply_record_id = None
        
        # LLM 缓存
        self._llm_cache: Dict[str, str] = {}
        self._llm_match_cache: Dict[str, str] = {}  # 批量匹配缓存
        
        print(f"📦 加载 Payload: {len(self.payload_data)} 个字段")
        print(f"🌐 站点配置: {self.site_config.__class__.__name__}")
        
        if not self._llm_config["api_key"]:
            print("⚠️ 警告: 未设置 LLM API Key，LLM 功能将不可用")
    
    def set_db_connection(self, db, apply_record_id: int):
        """设置数据库连接"""
        self.db = db
        self.apply_record_id = apply_record_id
        self.log(f"📊 数据库连接已设置，apply_record_id={apply_record_id}", "INFO")
    
    def log(self, message: str, level: str = "INFO"):
        """打印日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "ERROR": "❌",
            "WARN": "⚠️",
            "DEBUG": "📝",
            "LLM": "🤖",
            "FILL": "✏️",
        }.get(level, "→")
        print(f"[{timestamp}] {prefix} {message}")
    
    # ==================== Payload 匹配 ====================
    
    def match_field_to_payload(self, field: dict) -> Tuple[Optional[str], str]:
        """
        将表单字段匹配到 payload 数据
        
        核心原则：
        - 只匹配用户已提供的真实数据
        - 不生成任何虚假数据
        - 匹配失败时返回 None
        
        Returns:
            (value, source) - 值和来源
        """
        field_id = field.get('id', '')
        field_name = field.get('name', '')
        field_label = field.get('label', '')
        
        def extract_value(data):
            """从 payload 数据中提取值和来源"""
            if isinstance(data, dict):
                return data.get('value'), data.get('source', 'payload')
            return data, 'payload'
        
        # 1. 精确匹配 field_id
        for key in [field_id, field_name]:
            if key and key in self.payload_data:
                data = self.payload_data[key]
                value, source = extract_value(data)
                if value not in [None, "", []]:
                    return value, source
        
        # 2. 标准化匹配
        normalized_id = re.sub(r'[_\-\s]', '', field_id).lower()
        normalized_name = re.sub(r'[_\-\s]', '', field_name).lower()
        
        for payload_key, payload_data in self.payload_data.items():
            value, source = extract_value(payload_data)
            if value in [None, "", []]:
                continue
            normalized_payload_key = re.sub(r'[_\-\s]', '', payload_key).lower()
            if normalized_payload_key in [normalized_id, normalized_name]:
                return value, source
        
        # 3. 标签匹配
        if field_label:
            field_label_lower = field_label.lower().strip()
            for payload_key, payload_data in self.payload_data.items():
                value, source = extract_value(payload_data)
                if value in [None, "", []]:
                    continue
                
                if isinstance(payload_data, dict):
                    payload_label = (payload_data.get('label') or '').lower().strip()
                    if payload_label and (
                        field_label_lower in payload_label or 
                        payload_label in field_label_lower
                    ):
                        return value, source
        
        # 4. 语义搜索
        combined = f"{field_id} {field_name} {field_label}".lower()
        search_terms = self._extract_search_terms(combined)
        
        for term in search_terms:
            for payload_key, payload_data in self.payload_data.items():
                value, source = extract_value(payload_data)
                if value in [None, "", []]:
                    continue
                if term in payload_key.lower():
                    return value, source
        
        return None, "none"
    
    def _extract_search_terms(self, text: str) -> List[str]:
        """从文本中提取搜索关键词"""
        terms = []
        mappings = {
            'first': ['firstname', 'first_name', 'given_name'],
            'last': ['lastname', 'last_name', 'surname', 'family_name'],
            'email': ['email', 'email_address'],
            'phone': ['phone', 'telephone', 'mobile'],
            'address': ['address', 'street'],
            'city': ['city'],
            'state': ['state', 'province'],
            'zip': ['zip', 'postal', 'postal_code'],
            'country': ['country'],
            'birth': ['birth_date', 'dob', 'date_of_birth'],
            'gender': ['gender'],
        }
        
        for key, related in mappings.items():
            if key in text:
                terms.extend(related)
        
        return terms
    
    # ==================== 字段填写（优化版）====================

    async def fill_field(self, page: Page, field: dict, value: str) -> Dict:
        """
        填写单个字段（优化版）

        优化点：
        1. 使用预获取的选项，减少 DOM 查询
        2. 减少 sleep 时间
        3. 使用异步 LLM 调用

        Returns:
            {"success": bool, "error": str or None}
        """
        field_id = field.get('id', '')
        field_name = field.get('name', '')
        field_type = field.get('type', 'text')
        field_label = field.get('label', field_id or field_name)[:50]
        pre_fetched_options = field.get('options', [])  # 使用预获取的选项

        result = {"success": False, "error": None}

        try:
            # 构建选择器
            selector = None
            if field_id:
                selector = f'#{field_id}'
            elif field_name:
                selector = f'[name="{field_name}"]'

            if not selector:
                result["error"] = "无法构建选择器"
                return result

            # 查找元素
            elem = await page.query_selector(selector)
            if not elem:
                result["error"] = f"未找到元素: {selector}"
                return result

            # 滚动到视图（减少等待时间）
            try:
                await elem.scroll_into_view_if_needed()
            except:
                pass

            # 根据类型填写
            if field_type in ['text', 'email', 'tel', 'textarea', 'password', 'number']:
                await elem.fill(str(value))
                await elem.evaluate("""elem => {
                    elem.dispatchEvent(new Event('input', { bubbles: true }));
                    elem.dispatchEvent(new Event('change', { bubbles: true }));
                }""")
                result["success"] = True

            elif field_type in ['select', 'select-one']:
                # 优先使用预获取的选项
                options = pre_fetched_options
                if not options:
                    # 仅在没有预获取时才查询
                    options = await elem.evaluate("""elem => {
                        return Array.from(elem.options).map(o => ({
                            value: o.value,
                            text: o.textContent.trim()
                        }));
                    }""")

                matched = False

                # 0. 优先使用批量 LLM 预匹配结果
                if field_id in self._llm_match_cache:
                    matched_value = self._llm_match_cache[field_id]
                    try:
                        await elem.select_option(value=matched_value, timeout=1000)
                        result["success"] = True
                        matched = True
                    except:
                        pass

                # 1. 精确匹配 (value 或 text)
                if not matched:
                    for opt in options:
                        if opt['value'] == str(value) or opt['text'].lower() == str(value).lower():
                            try:
                                await elem.select_option(value=opt['value'], timeout=500)
                                result["success"] = True
                                matched = True
                                break
                            except:
                                pass

                # 2. 异步 LLM 智能匹配 (兜底)
                if not matched and options and self._llm_config["api_key"]:
                    option_texts = [f"{i+1}. {o['text']}" for i, o in enumerate(options) if o['text']]
                    if option_texts:
                        prompt = f"选择最匹配'{value}'的选项，只返回数字:\n" + "\n".join(option_texts[:15])
                        # 使用异步 LLM 调用
                        llm_result = await _call_llm_async(
                            self._llm_config["api_key"],
                            self._llm_config["base_url"],
                            self._llm_config["llm_model"],
                            prompt
                        )
                        try:
                            nums = re.findall(r'\d+', llm_result)
                            if nums:
                                idx = int(nums[0]) - 1
                                if 0 <= idx < len(options):
                                    await elem.select_option(value=options[idx]['value'], timeout=500)
                                    result["success"] = True
                                    matched = True
                        except:
                            pass

                if not matched:
                    result["error"] = f"Select 无匹配选项"

            elif field_type == 'radio':
                base_name = re.sub(r'_\d+$', '', field_name or field_id)
                base_id = re.sub(r'_\d+$', '', field_id) if field_id else base_name

                # 优先使用预获取的选项
                radio_options_data = pre_fetched_options

                # 如果没有预获取，才查询 DOM
                if not radio_options_data:
                    radios = await page.query_selector_all(f'input[type="radio"][name="{base_name}"]')
                    if not radios and field_id:
                        radios = await page.query_selector_all(f'input[type="radio"][id^="{base_id}"]')

                    # 批量获取 radio 信息（优化：使用 JavaScript 一次性获取）
                    radio_options_data = await page.evaluate("""(baseName) => {
                        const radios = document.querySelectorAll(`input[type="radio"][name="${baseName}"]`);
                        return Array.from(radios).map(r => {
                            let labelText = '';
                            if (r.id) {
                                const label = document.querySelector(`label[for="${r.id}"]`);
                                if (label) labelText = label.textContent.trim();
                            }
                            if (!labelText) {
                                const parent = r.closest('label, .radio-option');
                                if (parent) labelText = parent.textContent.trim();
                            }
                            return { value: r.value || '', text: labelText.substring(0, 50) || r.value || '' };
                        });
                    }""", base_name)

                matched = False

                # 0. 优先使用批量 LLM 预匹配结果
                llm_matched_value = self._llm_match_cache.get(field_id) or self._llm_match_cache.get(base_name)
                if llm_matched_value and radio_options_data:
                    for opt in radio_options_data:
                        if opt['value'] == llm_matched_value:
                            # 使用 JavaScript 点击
                            clicked = await page.evaluate("""(data) => {
                                const radio = document.querySelector(`input[type="radio"][name="${data.name}"][value="${data.value}"]`);
                                if (radio) { radio.click(); return true; }
                                return false;
                            }""", {"name": base_name, "value": llm_matched_value})
                            if clicked:
                                result["success"] = True
                                matched = True
                            break

                # 1. 精确匹配 (value 或 text)
                if not matched:
                    for opt in radio_options_data:
                        if opt['value'].lower() == str(value).lower() or opt['text'].lower() == str(value).lower():
                            clicked = await page.evaluate("""(data) => {
                                const radio = document.querySelector(`input[type="radio"][name="${data.name}"][value="${data.value}"]`);
                                if (radio) { radio.click(); return true; }
                                return false;
                            }""", {"name": base_name, "value": opt['value']})
                            if clicked:
                                result["success"] = True
                                matched = True
                            break

                # 2. 异步 LLM 智能匹配 (兜底)
                if not matched and radio_options_data and self._llm_config["api_key"]:
                    option_texts = [f"{i+1}. {o['text'] or o['value']}" for i, o in enumerate(radio_options_data)]
                    if option_texts:
                        prompt = f"选择最匹配'{value}'的选项，只返回数字:\n" + "\n".join(option_texts[:10])
                        llm_result = await _call_llm_async(
                            self._llm_config["api_key"],
                            self._llm_config["base_url"],
                            self._llm_config["llm_model"],
                            prompt
                        )
                        try:
                            nums = re.findall(r'\d+', llm_result)
                            if nums:
                                idx = int(nums[0]) - 1
                                if 0 <= idx < len(radio_options_data):
                                    clicked = await page.evaluate("""(data) => {
                                        const radio = document.querySelector(`input[type="radio"][name="${data.name}"][value="${data.value}"]`);
                                        if (radio) { radio.click(); return true; }
                                        return false;
                                    }""", {"name": base_name, "value": radio_options_data[idx]['value']})
                                    if clicked:
                                        result["success"] = True
                                        matched = True
                        except:
                            pass

                if not matched:
                    result["error"] = f"Radio 无匹配选项"
            
            elif field_type == 'checkbox':
                should_check = str(value).lower() in ['true', 'yes', '1', 'checked', 'on']
                if should_check:
                    await elem.check()
                else:
                    await elem.uncheck()
                result["success"] = True
            
            elif field_type == 'file':
                if value and os.path.exists(value):
                    await elem.set_input_files(value)
                    result["success"] = True
                else:
                    result["error"] = f"文件不存在: {value}"

            else:
                # 默认作为文本处理
                await elem.fill(str(value))
                result["success"] = True

        except Exception as e:
            result["error"] = str(e)[:100]

        return result

    # ==================== 批量填充优化方法 ====================

    async def _batch_fill_text_fields(self, page: Page, fields: List[Dict]) -> Dict[str, List]:
        """
        批量填充文本类字段（优化版）

        使用 JavaScript 一次性填充多个字段，减少 Python-Browser 交互
        """
        result = {"filled": [], "failed": []}

        if not fields:
            return result

        # 构建批量填充数据
        fill_data = []
        for f in fields:
            field_id = f.get('id', '') or f.get('name', '')
            value = f.get('matched_value', '')
            fill_data.append({
                "id": field_id,
                "value": str(value),
                "selector": f"#{field_id}" if f.get('id') else f"[name=\"{field_id}\"]"
            })

        # 使用 JavaScript 批量填充
        fill_results = await page.evaluate("""(fillData) => {
            const results = [];
            for (const item of fillData) {
                try {
                    const elem = document.querySelector(item.selector);
                    if (elem) {
                        elem.value = item.value;
                        elem.dispatchEvent(new Event('input', { bubbles: true }));
                        elem.dispatchEvent(new Event('change', { bubbles: true }));
                        results.push({ id: item.id, success: true });
                    } else {
                        results.push({ id: item.id, success: false, error: '元素未找到' });
                    }
                } catch (e) {
                    results.push({ id: item.id, success: false, error: e.message });
                }
            }
            return results;
        }""", fill_data)

        # 处理结果
        field_map = {f.get('id', '') or f.get('name', ''): f for f in fields}
        for r in fill_results:
            field_id = r.get('id', '')
            field = field_map.get(field_id, {})
            field_record = {
                "field_id": field_id,
                "field_label": field.get('label', ''),
                "field_type": field.get('type', 'text'),
                "value": field.get('matched_value', ''),
                "source": field.get('matched_source', ''),
            }

            if r.get('success'):
                result["filled"].append(field_record)
            else:
                field_record["error"] = r.get('error', 'Unknown')
                result["failed"].append(field_record)

        self.log(f"   批量填充完成: 成功 {len(result['filled'])}, 失败 {len(result['failed'])}", "INFO")
        return result

    async def _fill_single_field_async(self, page: Page, field_data: Dict, report: Dict):
        """
        异步填充单个字段（用于并行填充）
        """
        field_id = field_data.get('id', '') or field_data.get('name', '')
        field_label = field_data.get('label', '')
        field_type = field_data.get('type', 'text')
        value = field_data.get('matched_value', '')
        source = field_data.get('matched_source', '')

        # 检查日期下拉框组合
        if field_type == 'select':
            try:
                if await SpecialFieldHandler.detect_date_select_group(page, field_id):
                    success = await SpecialFieldHandler.fill_date_select_group(page, field_id, value)
                    if success:
                        report["fields_filled"].append({
                            "field_id": field_id,
                            "field_label": field_label,
                            "field_type": "date_group",
                            "value": value,
                            "source": source
                        })
                        return
            except:
                pass

        # 尝试填写
        fill_result = await self.fill_field(page, field_data, value)

        field_record = {
            "field_id": field_id,
            "field_label": field_label,
            "field_type": field_type,
            "value": value,
            "source": source,
        }

        if fill_result["success"]:
            report["fields_filled"].append(field_record)
        else:
            field_record["error"] = fill_result.get("error", "Unknown")
            report["fields_failed"].append(field_record)
            self.log(f"❌ 填写失败: {field_id} - {fill_result.get('error', '')}", "ERROR")

    # ==================== 页面字段提取（优化版）====================

    async def extract_page_fields(self, page: Page) -> List[Dict]:
        """
        提取页面上的所有表单字段（优化版）

        优化点：
        1. 一次性获取所有字段信息，包括 SELECT 和 RADIO 的选项
        2. 减少后续 DOM 查询
        """
        fields = await page.evaluate("""() => {
            const fields = [];
            const processedRadioGroups = new Set();

            const inputs = document.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea'
            );

            inputs.forEach((elem, index) => {
                const field = {
                    index: index,
                    id: elem.id || '',
                    name: elem.name || '',
                    type: elem.type || elem.tagName.toLowerCase(),
                    label: '',
                    value: elem.value || '',
                    required: elem.required || false,
                    visible: elem.offsetParent !== null,
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
                    const parent = elem.closest('.form_question, .form-group, .field-wrapper');
                    if (parent) {
                        const labelElem = parent.querySelector('label, .form_label, .field-label');
                        if (labelElem) {
                            field.label = labelElem.textContent.trim().substring(0, 100);
                        }
                    }
                }

                // 获取 SELECT 选项（预获取）
                if (elem.tagName === 'SELECT') {
                    field.options = Array.from(elem.options).slice(0, 30).map(opt => ({
                        value: opt.value,
                        text: opt.text.trim()
                    }));
                }

                // 获取 RADIO 选项（预获取，避免重复）
                if (elem.type === 'radio') {
                    const radioName = elem.name;
                    if (radioName && !processedRadioGroups.has(radioName)) {
                        processedRadioGroups.add(radioName);

                        const radios = document.querySelectorAll(`input[type="radio"][name="${radioName}"]`);
                        field.options = Array.from(radios).map(r => {
                            let labelText = '';
                            // 尝试通过 for 属性获取 label
                            if (r.id) {
                                const label = document.querySelector(`label[for="${r.id}"]`);
                                if (label) {
                                    labelText = label.textContent.trim();
                                }
                            }
                            // 尝试从父元素获取
                            if (!labelText) {
                                const parent = r.closest('label, .radio-option, .form-check');
                                if (parent) {
                                    labelText = parent.textContent.trim();
                                }
                            }
                            return {
                                value: r.value || '',
                                text: labelText.substring(0, 50) || r.value || ''
                            };
                        });
                        field.isRadioGroup = true;
                    } else if (radioName && processedRadioGroups.has(radioName)) {
                        // 已处理过的 radio 组，跳过
                        field.skipFill = true;
                    }
                }

                fields.push(field);
            });

            return fields;
        }""")

        return fields
    
    # ==================== 页面填写 ====================
    
    async def fill_page_from_payload(
        self,
        page: Page,
        page_num: int = 1
    ) -> Dict[str, Any]:
        """
        从 Payload 填写当前页面
        
        Returns:
            填写报告
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "page_num": page_num,
            "page_url": page.url,
            "page_title": await page.title(),
            "fields_on_page": 0,
            "fields_filled": [],
            "fields_no_value": [],
            "fields_failed": [],
        }
        
        self.log(f"\n{'='*60}", "INFO")
        self.log(f"📄 填写第 {page_num} 页: {report['page_title']}", "INFO")
        self.log(f"{'='*60}", "INFO")
        
        # 检测 CAPTCHA/2FA (只记录，不阻塞)
        if await HumanIntervention.detect_captcha(page):
            self.log("⚠️ 检测到 CAPTCHA，跳过此页", "WARN")
            if self.db and self.apply_record_id:
                self.db.add_fill_error(self.apply_record_id, page_num, "captcha", "CAPTCHA detected - skipped")
            # 跳过等待，直接返回空报告
            return report
        
        if await HumanIntervention.detect_2fa(page):
            self.log("⚠️ 检测到 2FA，跳过此页", "WARN")
            if self.db and self.apply_record_id:
                self.db.add_fill_error(self.apply_record_id, page_num, "2fa", "2FA required - skipped")
            # 跳过等待，直接返回空报告
            return report
        
        # 展开可折叠区域
        expanded = await self.collapsible_handler.expand_all_sections(page)
        if expanded > 0:
            self.log(f"展开了 {expanded} 个折叠区域", "SUCCESS")
            await asyncio.sleep(0.2)  # 减少等待时间
        
        # 执行站点预填充钩子
        if hasattr(self.site_config, 'pre_fill_hooks'):
            try:
                await self.site_config.pre_fill_hooks(page)
            except Exception as e:
                self.log(f"预填充钩子执行失败: {e}", "WARN")
        
        # 提取页面字段
        page_fields = await self.extract_page_fields(page)
        report["fields_on_page"] = len(page_fields)
        
        self.log(f"📋 页面字段数: {len(page_fields)}", "INFO")
        
        # ===== 批量 LLM 预匹配 Select/Radio（优化版：使用预获取的选项）=====
        llm_match_cache = {}
        if self._llm_config["api_key"]:
            fields_need_llm = []
            processed_radio_names = set()

            for field in page_fields:
                # 跳过已处理的 radio
                if field.get('skipFill'):
                    continue

                field_id = field.get('id', '') or field.get('name', '')
                field_type = field.get('type', 'text')
                options = field.get('options', [])  # 使用预获取的选项

                if field_type in ['select', 'select-one'] and options:
                    value, _ = self.match_field_to_payload(field)
                    if value:
                        fields_need_llm.append({
                            "field_id": field_id,
                            "value": str(value),
                            "options": options
                        })

                elif field_type == 'radio' and options:
                    base_name = re.sub(r'_\d+$', '', field.get('name', '') or field_id)
                    if base_name in processed_radio_names:
                        continue
                    processed_radio_names.add(base_name)

                    value, _ = self.match_field_to_payload(field)
                    if value:
                        fields_need_llm.append({
                            "field_id": base_name,
                            "value": str(value),
                            "options": options
                        })

            if fields_need_llm:
                self.log(f"🤖 异步批量 LLM 匹配 {len(fields_need_llm)} 个选择字段...", "LLM")
                # 使用异步版本
                llm_match_cache = await _batch_match_options_with_llm_async(
                    self._llm_config["api_key"],
                    self._llm_config["base_url"],
                    self._llm_config["llm_model"],
                    fields_need_llm
                )
                self.log(f"🤖 LLM 匹配结果: {len(llm_match_cache)} 个字段", "LLM")

        # 保存到实例变量供 fill_field 使用
        self._llm_match_cache = llm_match_cache

        # ===== 并行填充优化 =====
        # 将字段分组：text 类字段可以批量填充，select/radio 需要单独处理
        text_fields = []
        select_radio_fields = []
        other_fields = []

        for field in page_fields:
            if field.get('skipFill'):
                continue
            field_id = field.get('id', '') or field.get('name', '')
            if not field_id:
                continue

            field_type = field.get('type', 'text')
            value, source = self.match_field_to_payload(field)

            if not value:
                # 无匹配值
                field_label = field.get('label', '')
                self.log(f"⚠️ 无匹配值: [{field_type}] {field_label or field_id}", "WARN")
                report["fields_no_value"].append({
                    "field_id": field_id,
                    "field_label": field_label,
                    "field_type": field_type,
                    "is_required": field.get('required', False),
                })
                continue

            field_data = {**field, "matched_value": value, "matched_source": source}

            if field_type in ['text', 'email', 'tel', 'textarea', 'password', 'number']:
                text_fields.append(field_data)
            elif field_type in ['select', 'select-one', 'radio']:
                select_radio_fields.append(field_data)
            else:
                other_fields.append(field_data)

        # 1. 批量填充 text 类字段（使用 JavaScript 一次性填充）
        if text_fields:
            self.log(f"⚡ 批量填充 {len(text_fields)} 个文本字段...", "INFO")
            batch_result = await self._batch_fill_text_fields(page, text_fields)
            report["fields_filled"].extend(batch_result["filled"])
            report["fields_failed"].extend(batch_result["failed"])

        # 2. 并行填充 select/radio 字段（使用 asyncio.gather）
        if select_radio_fields:
            self.log(f"⚡ 并行填充 {len(select_radio_fields)} 个选择字段...", "INFO")
            tasks = []
            for field_data in select_radio_fields:
                tasks.append(self._fill_single_field_async(page, field_data, report))

            # 并行执行，但限制并发数避免冲突
            semaphore = asyncio.Semaphore(3)  # 最多 3 个并发

            async def fill_with_semaphore(task):
                async with semaphore:
                    return await task

            await asyncio.gather(*[fill_with_semaphore(t) for t in tasks])

        # 3. 顺序填充其他字段
        for field_data in other_fields:
            await self._fill_single_field_async(page, field_data, report)
        
        # 检测并尝试修复验证错误
        verify_result = await self._verify_and_fix_errors(page, page_fields)
        if verify_result["has_errors"]:
            report["validation_errors"] = verify_result["errors"]
            report["errors_fixed"] = verify_result["fixed_count"]
            for err in verify_result["errors"]:
                self.log(f"   ⚠️ 未解决: {err.get('error_message', '')[:80]}", "WARN")

        # 尝试保存当前页面
        saved = await self._try_save_page(page)
        if saved:
            self.log(f"💾 页面已保存", "SUCCESS")
            report["page_saved"] = True
        else:
            self.log(f"📝 未找到独立保存按钮（可能点击下一页时自动保存）", "DEBUG")
            report["page_saved"] = False

        # 执行站点后填充钩子
        if hasattr(self.site_config, 'post_fill_hooks'):
            try:
                await self.site_config.post_fill_hooks(page)
            except Exception as e:
                self.log(f"后填充钩子执行失败: {e}", "WARN")
        
        # 保存进度到数据库
        if self.db and self.apply_record_id:
            try:
                self.db.update_process_progress(
                    apply_record_id=self.apply_record_id,
                    current_page=page_num,
                    fields_filled=len(report["fields_filled"]),
                    fields_total=report["fields_on_page"]
                )
                
                self.db.save_checkpoint(self.apply_record_id, {
                    "page_number": page_num,
                    "page_url": page.url,
                    "page_title": report["page_title"],
                })
                
                self.db.update_fill_result(
                    apply_record_id=self.apply_record_id,
                    fields_filled=[{**f, "page": page_num} for f in report["fields_filled"]],
                    fields_no_value=[{**f, "page": page_num} for f in report["fields_no_value"]],
                    fields_failed=[{**f, "page": page_num} for f in report["fields_failed"]],
                    append=True
                )
            except Exception as e:
                self.log(f"保存进度失败: {e}", "WARN")
        
        # 打印统计
        self.log(f"\n📊 第 {page_num} 页统计:", "INFO")
        self.log(f"  ✅ 已填写: {len(report['fields_filled'])}", "SUCCESS")
        self.log(f"  ⚠️ 无匹配值: {len(report['fields_no_value'])}", "WARN")
        self.log(f"  ❌ 填写失败: {len(report['fields_failed'])}", "ERROR")
        
        return report
    
    # ==================== 报告生成 ====================
    
    def save_fill_report(self, report: Dict, filename: Optional[str] = None) -> str:
        """保存填写报告"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"fill_report_{timestamp}.json"
        
        output_path = self.output_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        self.log(f"📄 报告已保存: {output_path}", "SUCCESS")
        return str(output_path)
    
    def get_missing_fields(self) -> List[Dict]:
        """获取所有缺失字段"""
        return self.missing_fields
    
    async def _try_save_page(self, page: Page) -> bool:
        """
        尝试保存当前页面

        策略：
        1. 先尝试点击 Save 按钮
        2. 如果没有 Save 按钮，尝试 Ctrl+S
        3. 等待保存完成

        Returns:
            是否成功触发保存
        """
        # 保存按钮选择器（不包含 Next/Continue）
        save_selectors = [
            'button:has-text("Save"):not(:has-text("Continue")):not(:has-text("Next"))',
            'button:has-text("保存")',
            'input[value="Save"]',
            'a:has-text("Save"):not(:has-text("Continue"))',
            '[data-action="save"]',
            '.btn-save',
            '#save-btn',
            'button[name="save"]',
        ]

        for selector in save_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click(timeout=2000)
                    self.log(f"   点击保存按钮: {selector}", "DEBUG")

                    # 等待可能的加载完成（减少超时时间）
                    try:
                        await page.wait_for_load_state('networkidle', timeout=3000)
                    except:
                        await asyncio.sleep(0.5)

                    return True
            except:
                continue

        # 如果没有找到保存按钮，尝试 Ctrl+S
        try:
            await page.keyboard.press('Control+s')
            self.log(f"   尝试 Ctrl+S 保存", "DEBUG")
            await asyncio.sleep(0.5)
            return True
        except:
            pass

        return False

    async def _verify_and_fix_errors(self, page: Page, page_fields: List[Dict]) -> Dict[str, Any]:
        """
        校验页面并尝试修复错误

        Returns:
            {
                "has_errors": bool,
                "errors": List[Dict],
                "fixed_count": int
            }
        """
        result = {
            "has_errors": False,
            "errors": [],
            "fixed_count": 0
        }

        # 检测验证错误
        validation_errors = await ValidationChecker.check_for_errors(page)
        if not validation_errors:
            return result

        result["has_errors"] = True
        result["errors"] = validation_errors
        self.log(f"🔍 检测到 {len(validation_errors)} 个验证错误，尝试修复...", "WARN")

        # 尝试定位并修复错误字段
        for error in validation_errors:
            error_msg = error.get("error_message", "").lower()

            # 查找关联的字段
            try:
                # 查找带有 aria-invalid 的字段
                invalid_fields = await page.query_selector_all('[aria-invalid="true"]')
                for field in invalid_fields:
                    field_id = await field.get_attribute('id') or await field.get_attribute('name')
                    if not field_id:
                        continue

                    # 尝试从 payload 重新获取值并填充
                    field_info = {'id': field_id, 'name': field_id}
                    value, source = self.match_field_to_payload(field_info)

                    if value:
                        try:
                            await field.fill('')
                            await field.fill(str(value))
                            result["fixed_count"] += 1
                            self.log(f"   ✓ 修复字段: {field_id}", "SUCCESS")
                        except:
                            pass
            except:
                continue

        # 重新检测错误
        remaining_errors = await ValidationChecker.check_for_errors(page)
        result["errors"] = remaining_errors
        result["has_errors"] = len(remaining_errors) > 0

        if result["fixed_count"] > 0:
            self.log(f"🔧 修复了 {result['fixed_count']} 个字段", "SUCCESS")

        if result["has_errors"]:
            self.log(f"⚠️ 仍有 {len(remaining_errors)} 个错误未解决", "WARN")

        return result

    async def click_next_page(self, page: Page) -> bool:
        """
        智能点击下一页按钮，处理遮挡问题

        Returns:
            是否成功点击
        """
        # 等待可能的加载遮罩消失
        try:
            await page.wait_for_selector('.progress_box, .progress_div, .loading, .spinner', 
                                         state='hidden', timeout=5000)
        except:
            pass
        
        # 下一页按钮选择器
        next_selectors = [
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("Save and Continue")',
            'input[value="Next"]',
            'input[value="Continue"]',
            'a:has-text("Next")',
            '.btn-next',
            '[data-action="next"]',
        ]
        
        for selector in next_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    # 尝试用 force 强制点击（绕过遮挡）
                    try:
                        await btn.click(force=True, timeout=3000)
                        self.log(f"➡️ 点击下一页成功", "SUCCESS")
                        # 等待页面导航完成
                        try:
                            await page.wait_for_load_state('domcontentloaded', timeout=5000)
                        except:
                            await asyncio.sleep(0.5)
                        return True
                    except:
                        # 用 JS 点击
                        try:
                            await btn.evaluate("el => el.click()")
                            self.log(f"➡️ JS点击下一页成功", "SUCCESS")
                            try:
                                await page.wait_for_load_state('domcontentloaded', timeout=5000)
                            except:
                                await asyncio.sleep(0.5)
                            return True
                        except:
                            continue
            except:
                continue

        self.log(f"⚠️ 未找到下一页按钮", "WARN")
        return False

