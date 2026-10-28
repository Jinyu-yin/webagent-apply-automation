#!/usr/bin/env python3
"""
第三阶段：评价Agent - 验证填写结果并支持纠错

功能：
1. 验证每次操作的结果
2. 检测错误（如页面跳转错误、填写失败）
3. 支持回退和重试
4. 提供操作建议

用法：
    在 02_llm_fill_forms.py 中集成使用
    或独立运行进行批量验证

设计理念：
    EvaluateAgent 作为独立的评价模块，可以：
    1. 实时评价：每次操作后立即验证
    2. 批量评价：对已完成的填写历史进行回溯验证
    3. 提供纠错建议：当发现问题时给出修复方案
"""

import sys
import os
import json
import asyncio
import base64
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import Page

# LLM 配置 - 延迟加载，仅在需要时从环境变量获取
def _get_llm_config():
    """获取 LLM 配置（延迟加载）"""
    return {
        'api_key': os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"),
        'base_url': os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        'llm_model': os.getenv("LLM_MODEL", "anthropic/claude-3.5-sonnet"),
        'vlm_model': os.getenv("VLM_MODEL", "anthropic/claude-3.5-sonnet"),
    }


class ActionResult(Enum):
    """操作结果枚举"""
    SUCCESS = "success"
    PARTIAL = "partial"  # 部分成功
    FAILED = "failed"
    ERROR = "error"  # 系统错误
    NEEDS_RETRY = "needs_retry"
    NEEDS_ROLLBACK = "needs_rollback"


class EvaluateAgent:
    """
    评价Agent - 验证操作结果并提供纠错支持
    
    职责：
    1. 验证填写操作是否成功
    2. 检测页面状态是否正确
    3. 提供纠错建议
    4. 支持回退操作
    """
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.evaluation_history = []
        self.error_count = 0
        self.success_count = 0
        
        # 页面状态快照（用于回退）
        self.page_snapshots = []
        self.max_snapshots = 5
        
        # LLM 配置（延迟加载）
        self._llm_config = None
    
    @property
    def llm_config(self):
        """获取 LLM 配置（延迟加载）"""
        if self._llm_config is None:
            self._llm_config = _get_llm_config()
        return self._llm_config
    
    def log(self, message: str, level: str = "INFO"):
        """打印日志"""
        if not self.verbose:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "ERROR": "❌",
            "WARN": "⚠️",
            "EVAL": "🔍",
            "FIX": "🔧",
        }.get(level, "→")
        print(f"[{timestamp}] {prefix} [评价Agent] {message}")
    
    async def save_snapshot(self, page: Page, label: str = "snapshot"):
        """保存页面快照（用于可能的回退）"""
        try:
            snapshot = {
                "label": label,
                "timestamp": datetime.now().isoformat(),
                "url": page.url,
                "title": await page.title(),
                "html": await page.evaluate("() => document.documentElement.outerHTML"),
            }
            
            self.page_snapshots.append(snapshot)
            
            # 保持最大数量
            if len(self.page_snapshots) > self.max_snapshots:
                self.page_snapshots.pop(0)
            
            self.log(f"快照已保存: {label}", "INFO")
        except Exception as e:
            self.log(f"保存快照失败: {e}", "WARN")
    
    async def evaluate_fill_action(
        self, 
        page: Page, 
        field_id: str, 
        expected_value: str,
        field_type: str = "text"
    ) -> Dict[str, Any]:
        """
        评价单个填写操作
        
        Args:
            page: 浏览器页面
            field_id: 字段ID或选择器
            expected_value: 期望填入的值
            field_type: 字段类型
            
        Returns:
            {
                "result": ActionResult,
                "actual_value": str,
                "message": str,
                "suggestion": str
            }
        """
        try:
            # 构建选择器
            selector = f'#{field_id}' if not field_id.startswith('[') else field_id
            
            # 查找元素
            elem = await page.query_selector(selector)
            if not elem:
                # 尝试用name查找
                elem = await page.query_selector(f'[name="{field_id}"]')
            
            if not elem:
                return {
                    "result": ActionResult.FAILED,
                    "actual_value": None,
                    "message": f"未找到字段: {field_id}",
                    "suggestion": "检查字段ID是否正确，或字段是否可见"
                }
            
            # 获取实际值
            actual_value = ""
            if field_type in ['text', 'email', 'tel', 'textarea', 'password', 'date']:
                actual_value = await elem.input_value()
            elif field_type == 'select':
                actual_value = await elem.input_value()
            elif field_type == 'checkbox':
                actual_value = "true" if await elem.is_checked() else "false"
            elif field_type == 'radio':
                actual_value = "true" if await elem.is_checked() else "false"
            
            # 比较值
            if actual_value == expected_value:
                self.success_count += 1
                return {
                    "result": ActionResult.SUCCESS,
                    "actual_value": actual_value,
                    "message": f"字段 {field_id} 填写正确",
                    "suggestion": None
                }
            elif actual_value and actual_value != expected_value:
                return {
                    "result": ActionResult.PARTIAL,
                    "actual_value": actual_value,
                    "message": f"字段 {field_id} 值不匹配: 期望 '{expected_value}', 实际 '{actual_value}'",
                    "suggestion": "重新填写该字段"
                }
            else:
                self.error_count += 1
                return {
                    "result": ActionResult.FAILED,
                    "actual_value": actual_value,
                    "message": f"字段 {field_id} 填写失败",
                    "suggestion": "检查字段是否可编辑，或尝试清除后重新填写"
                }
        
        except Exception as e:
            self.error_count += 1
            return {
                "result": ActionResult.ERROR,
                "actual_value": None,
                "message": f"评价失败: {e}",
                "suggestion": "检查页面状态是否正常"
            }
    
    async def evaluate_navigation(
        self, 
        page: Page, 
        expected_page_indicator: str,
        previous_url: str
    ) -> Dict[str, Any]:
        """
        评价页面导航操作
        
        Args:
            page: 浏览器页面
            expected_page_indicator: 期望的页面标识（如标题、URL片段）
            previous_url: 导航前的URL
            
        Returns:
            {
                "result": ActionResult,
                "current_url": str,
                "current_title": str,
                "message": str,
                "suggestion": str
            }
        """
        try:
            current_url = page.url
            current_title = await page.title()
            
            # 检查URL是否变化
            if current_url == previous_url:
                # URL没变，可能是同页面弹窗或错误
                error_messages = await page.query_selector_all('.error, .alert-danger, .validation-error')
                if error_messages:
                    error_text = await error_messages[0].text_content()
                    return {
                        "result": ActionResult.FAILED,
                        "current_url": current_url,
                        "current_title": current_title,
                        "message": f"页面导航失败，检测到错误: {error_text[:100]}",
                        "suggestion": "检查表单验证错误，填写必填字段"
                    }
                
                return {
                    "result": ActionResult.NEEDS_RETRY,
                    "current_url": current_url,
                    "current_title": current_title,
                    "message": "页面URL未变化",
                    "suggestion": "重新点击导航按钮或检查是否有弹窗"
                }
            
            # 检查是否导航到了期望的页面
            if expected_page_indicator:
                if expected_page_indicator.lower() in current_url.lower() or \
                   expected_page_indicator.lower() in current_title.lower():
                    self.success_count += 1
                    return {
                        "result": ActionResult.SUCCESS,
                        "current_url": current_url,
                        "current_title": current_title,
                        "message": "页面导航成功",
                        "suggestion": None
                    }
            
            # URL变化但不确定是否正确
            return {
                "result": ActionResult.PARTIAL,
                "current_url": current_url,
                "current_title": current_title,
                "message": f"页面已跳转到: {current_title}",
                "suggestion": "确认是否到达目标页面"
            }
        
        except Exception as e:
            return {
                "result": ActionResult.ERROR,
                "current_url": None,
                "current_title": None,
                "message": f"导航评价失败: {e}",
                "suggestion": "检查浏览器状态"
            }
    
    async def evaluate_page_state_with_vlm(
        self, 
        page: Page, 
        expected_state: str
    ) -> Dict[str, Any]:
        """
        使用VLM评价页面整体状态
        
        Args:
            page: 浏览器页面
            expected_state: 期望的页面状态描述
            
        Returns:
            {
                "result": ActionResult,
                "analysis": str,
                "issues": [str],
                "suggestions": [str]
            }
        """
        config = self.llm_config
        if not config['api_key']:
            return {
                "result": ActionResult.PARTIAL,
                "analysis": "VLM不可用，跳过视觉评价",
                "issues": [],
                "suggestions": []
            }
        
        try:
            # 截图
            screenshot_bytes = await page.screenshot()
            image_data = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            # 获取页面信息
            page_info = await page.evaluate("""() => {
                return {
                    title: document.title,
                    url: window.location.href,
                    errors: Array.from(document.querySelectorAll('.error, .alert-danger, .validation-error'))
                        .map(el => el.innerText.trim()).slice(0, 5),
                    emptyRequired: Array.from(document.querySelectorAll('[required]'))
                        .filter(el => !el.value).map(el => el.name || el.id).slice(0, 10)
                };
            }""")
            
            self.log("使用VLM评价页面状态...", "EVAL")
            
            system_prompt = """你是一个网页表单评价专家。请分析提供的表单页面截图，评价当前状态。

检查项目：
1. 是否有未填写的必填字段（通常标有 * 或红色边框）
2. 是否有错误提示信息
3. 页面是否正常加载
4. 表单是否可以继续提交

返回JSON格式（只返回JSON）：
{
    "state": "good/warning/error",
    "filled_percentage": 0-100,
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"],
    "can_proceed": true/false,
    "analysis": "整体分析"
}"""
            
            user_content = [
                {"type": "text", "text": f"""请评价这个表单页面的当前状态：

期望状态: {expected_state}
页面标题: {page_info.get('title', '')}
检测到的错误: {json.dumps(page_info.get('errors', []), ensure_ascii=False)}
空必填字段: {json.dumps(page_info.get('emptyRequired', []), ensure_ascii=False)}

请分析截图并给出评价。"""},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}}
            ]
            
            response = requests.post(
                config['base_url'].rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": config['vlm_model'],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 1500
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                
                # 解析JSON
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    analysis = json.loads(content[start:end])
                    
                    state = analysis.get("state", "warning")
                    result_enum = {
                        "good": ActionResult.SUCCESS,
                        "warning": ActionResult.PARTIAL,
                        "error": ActionResult.FAILED
                    }.get(state, ActionResult.PARTIAL)
                    
                    return {
                        "result": result_enum,
                        "analysis": analysis.get("analysis", ""),
                        "issues": analysis.get("issues", []),
                        "suggestions": analysis.get("suggestions", []),
                        "can_proceed": analysis.get("can_proceed", True),
                        "filled_percentage": analysis.get("filled_percentage", 0)
                    }
        
        except Exception as e:
            self.log(f"VLM评价失败: {e}", "ERROR")
        
        return {
            "result": ActionResult.PARTIAL,
            "analysis": "VLM评价失败",
            "issues": [],
            "suggestions": []
        }
    
    async def suggest_fix_action(
        self, 
        page: Page, 
        failed_action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        为失败的操作提供修复建议
        
        Args:
            page: 浏览器页面
            failed_action: 失败的操作信息
            
        Returns:
            {
                "fix_type": str,  # retry, alternative, skip, rollback
                "fix_action": dict,  # 修复操作的详细信息
                "reason": str
            }
        """
        action_type = failed_action.get("type", "fill")
        field_id = failed_action.get("field_id", "")
        error_message = failed_action.get("message", "")
        
        # 检查字段当前状态
        if action_type == "fill" and field_id:
            try:
                selector = f'#{field_id}' if not field_id.startswith('[') else field_id
                elem = await page.query_selector(selector)
                
                if not elem:
                    # 字段不存在 - 可能需要展开隐藏区域
                    return {
                        "fix_type": "alternative",
                        "fix_action": {
                            "action": "expand_hidden",
                            "description": "尝试展开隐藏的表单区域"
                        },
                        "reason": "字段可能在隐藏区域中"
                    }
                
                is_visible = await elem.is_visible()
                if not is_visible:
                    return {
                        "fix_type": "alternative",
                        "fix_action": {
                            "action": "scroll_and_retry",
                            "selector": selector
                        },
                        "reason": "字段不可见，需要滚动到视图中"
                    }
                
                is_disabled = await elem.is_disabled()
                if is_disabled:
                    return {
                        "fix_type": "skip",
                        "fix_action": {
                            "action": "skip_field",
                            "field_id": field_id
                        },
                        "reason": "字段被禁用，跳过填写"
                    }
                
                # 默认重试
                return {
                    "fix_type": "retry",
                    "fix_action": {
                        "action": "clear_and_fill",
                        "selector": selector
                    },
                    "reason": "清除字段后重新填写"
                }
            
            except Exception as e:
                self.log(f"分析修复方案失败: {e}", "WARN")
        
        # 导航失败
        if action_type == "navigate":
            # 检查是否有验证错误
            errors = await page.query_selector_all('.error, .validation-error')
            if errors:
                return {
                    "fix_type": "fix_validation",
                    "fix_action": {
                        "action": "fix_errors",
                        "description": "修复验证错误后重试"
                    },
                    "reason": "存在表单验证错误"
                }
            
            return {
                "fix_type": "retry",
                "fix_action": {
                    "action": "retry_navigation"
                },
                "reason": "重试页面导航"
            }
        
        # 默认建议
        return {
            "fix_type": "skip",
            "fix_action": {"action": "continue"},
            "reason": "无法确定修复方案，继续执行"
        }
    
    async def execute_rollback(self, page: Page, steps: int = 1) -> bool:
        """
        执行回退操作
        
        Args:
            page: 浏览器页面
            steps: 回退步数
            
        Returns:
            是否成功回退
        """
        try:
            for _ in range(steps):
                await page.go_back()
                await page.wait_for_load_state('networkidle', timeout=10000)
            
            self.log(f"已回退 {steps} 步", "FIX")
            return True
        except Exception as e:
            self.log(f"回退失败: {e}", "ERROR")
            return False
    
    def get_summary(self) -> Dict[str, Any]:
        """获取评价摘要"""
        total = self.success_count + self.error_count
        success_rate = self.success_count / total if total > 0 else 0
        
        return {
            "total_evaluations": total,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate": f"{success_rate:.1%}",
            "history_count": len(self.evaluation_history)
        }
    
    def record_evaluation(self, action: str, result: Dict[str, Any]):
        """记录评价结果"""
        self.evaluation_history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "result": result
        })


# 独立运行时的测试代码
async def test_evaluate_agent():
    """测试评价Agent"""
    from playwright.async_api import async_playwright
    
    agent = EvaluateAgent(verbose=True)
    
    print("\n" + "="*60)
    print("🔍 评价Agent测试")
    print("="*60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # 访问测试页面
        await page.goto("https://gradapp.berkeley.edu/account/login?r=https%3a%2f%2fgradapp.berkeley.edu%2fapply%2ffrm%3fab12670f-99d2-4f68-9c45-b76f0f51175a")
        await asyncio.sleep(3)
        
        # 测试页面状态评价
        result = await agent.evaluate_page_state_with_vlm(page, "登录页面")
        print(f"\n页面状态评价结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        
        # 获取摘要
        summary = agent.get_summary()
        print(f"\n评价摘要:")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_evaluate_agent())
