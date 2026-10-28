"""
人工干预和提交检测模块

包含：
- HumanIntervention: 处理需要人工介入的情况（CAPTCHA、2FA）
- SubmissionChecker: 检测申请是否成功提交
"""

import re
import signal
import asyncio
from typing import Dict, Any, List
from playwright.async_api import Page

from .validators import ValidationChecker


class HumanIntervention:
    """处理需要人工介入的情况（CAPTCHA、2FA 等）"""
    
    @staticmethod
    async def wait_for_manual_action(
        page: Page,
        prompt: str = "需要人工操作，请在浏览器中完成后按 Enter 继续...",
        timeout_seconds: int = 300
    ) -> bool:
        """
        暂停自动化，等待用户完成手动操作
        
        Args:
            page: 浏览器页面
            prompt: 提示信息
            timeout_seconds: 超时时间（秒）
        
        Returns:
            True 如果用户按了 Enter，False 如果超时或中断
        """
        print("\n" + "=" * 60)
        print("⏸️  自动化已暂停 - 需要人工干预")
        print("=" * 60)
        print(prompt)
        print("=" * 60)
        print(f"\n浏览器将保持打开状态。完成操作后按 Enter 继续... (超时: {timeout_seconds}秒)")
        
        def timeout_handler(signum, frame):
            raise TimeoutError("人工干预超时")
        
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
        
        try:
            input()
            print("✅ 继续自动化...\n")
            return True
        except KeyboardInterrupt:
            print("\n❌ 用户取消操作")
            return False
        except TimeoutError:
            print(f"\n⏱️ 超时 ({timeout_seconds}秒)，继续自动化...")
            return False
        finally:
            signal.alarm(0)
    
    @staticmethod
    async def wait_for_captcha(page: Page) -> bool:
        """等待用户解决 CAPTCHA"""
        return await HumanIntervention.wait_for_manual_action(
            page,
            "检测到 CAPTCHA，请在浏览器中完成验证。",
            timeout_seconds=300
        )
    
    @staticmethod
    async def wait_for_2fa(page: Page) -> bool:
        """等待用户完成 2FA"""
        return await HumanIntervention.wait_for_manual_action(
            page,
            "需要双因素认证(2FA)，请在浏览器中输入验证码。",
            timeout_seconds=300
        )
    
    @staticmethod
    async def detect_captcha(page: Page) -> bool:
        """检测页面是否有 CAPTCHA"""
        captcha_indicators = [
            'captcha', 'recaptcha', 'hcaptcha', 'cloudflare', 'challenge'
        ]
        
        try:
            page_text = await page.evaluate(
                "() => document.body ? document.body.innerText.toLowerCase() : ''"
            )
            
            for indicator in captcha_indicators:
                if indicator in page_text:
                    return True
            
            # 检查 CAPTCHA iframe
            captcha_iframes = await page.query_selector_all(
                "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='captcha']"
            )
            if len(captcha_iframes) > 0:
                return True
        except:
            pass
        
        return False
    
    @staticmethod
    async def detect_2fa(page: Page) -> bool:
        """检测页面是否需要 2FA"""
        twofa_indicators = [
            'verification code', 'two-factor', '2fa', 'authenticator',
            'enter code', 'security code', 'verify your identity'
        ]
        
        try:
            page_text = await page.evaluate(
                "() => document.body ? document.body.innerText.toLowerCase() : ''"
            )
            
            for indicator in twofa_indicators:
                if indicator in page_text:
                    return True
        except:
            pass
        
        return False


class SubmissionChecker:
    """检测申请是否成功提交"""
    
    # 成功提交的关键词
    SUCCESS_INDICATORS = [
        'submitted', 'submission complete', 'application received',
        'thank you for applying', 'confirmation', 'confirmed',
        'successfully submitted', 'application complete',
        'your application has been', 'we have received your application'
    ]
    
    # 确认号的正则模式
    CONFIRMATION_PATTERNS = [
        r'confirmation\s*(?:number|#|id|code)[\s:]*([A-Z0-9\-]+)',
        r'application\s*(?:number|#|id)[\s:]*([A-Z0-9\-]+)',
        r'reference\s*(?:number|#|id)[\s:]*([A-Z0-9\-]+)',
        r'tracking\s*(?:number|#|id)[\s:]*([A-Z0-9\-]+)',
    ]
    
    @classmethod
    async def check_submission_success(cls, page: Page) -> Dict[str, Any]:
        """
        检测申请是否成功提交
        
        Returns:
            {
                "success": bool,
                "confidence": float,  # 0-1
                "confirmation_number": str or None,
                "indicators_found": [str],
                "page_url": str,
                "page_title": str
            }
        """
        result = {
            "success": False,
            "confidence": 0.0,
            "confirmation_number": None,
            "indicators_found": [],
            "page_url": page.url,
            "page_title": await page.title()
        }
        
        try:
            page_text = await page.evaluate(
                "() => document.body ? document.body.innerText.toLowerCase() : ''"
            )
            
            # 1. 检查成功关键词
            for indicator in cls.SUCCESS_INDICATORS:
                if indicator in page_text:
                    result["indicators_found"].append(indicator)
            
            # 2. 检查 URL 是否包含成功标识
            url_lower = page.url.lower()
            if any(kw in url_lower for kw in ['confirm', 'success', 'complete', 'submitted', 'thank']):
                result["indicators_found"].append(f"url:{url_lower[:50]}")
            
            # 3. 尝试提取确认号
            for pattern in cls.CONFIRMATION_PATTERNS:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    result["confirmation_number"] = match.group(1)
                    result["indicators_found"].append(f"confirmation:{result['confirmation_number']}")
                    break
            
            # 4. 检查是否还有表单
            forms = await page.query_selector_all('form')
            visible_inputs = await page.query_selector_all('input:visible:not([type="hidden"])')
            if len(forms) == 0 and len(visible_inputs) < 3:
                result["indicators_found"].append("no_visible_form")
            
            # 5. 计算置信度
            if result["confirmation_number"]:
                result["confidence"] = 0.95
                result["success"] = True
            elif len(result["indicators_found"]) >= 3:
                result["confidence"] = 0.85
                result["success"] = True
            elif len(result["indicators_found"]) >= 2:
                result["confidence"] = 0.7
                result["success"] = True
            elif len(result["indicators_found"]) >= 1:
                result["confidence"] = 0.5
                result["success"] = True
        
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    @classmethod
    async def wait_for_submission_result(
        cls, 
        page: Page, 
        timeout_seconds: int = 30
    ) -> Dict[str, Any]:
        """等待并检测提交结果"""
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout_seconds:
            result = await cls.check_submission_success(page)
            
            if result["success"] and result["confidence"] >= 0.7:
                return result
            
            # 检查是否有错误
            errors = await ValidationChecker.check_for_errors(page)
            if errors:
                return {
                    "success": False,
                    "confidence": 0.9,
                    "errors": errors,
                    "page_url": page.url,
                    "page_title": await page.title()
                }
            
            await asyncio.sleep(1)
        
        # 超时
        return {
            "success": False,
            "confidence": 0.0,
            "timeout": True,
            "page_url": page.url,
            "page_title": await page.title()
        }

