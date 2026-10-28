"""
登录处理模块

自动处理登录流程
"""

import asyncio
from playwright.async_api import Page

from .intervention import HumanIntervention


class LoginHandler:
    """自动登录处理"""
    
    @staticmethod
    async def login_if_needed(page: Page, email: str, password: str) -> bool:
        """
        如果需要登录则自动登录
        
        Returns:
            是否成功登录或已经登录
        """
        current_url = page.url.lower()
        
        # 检查是否在登录页面
        if not any(kw in current_url for kw in ['login', 'signin', 'auth']):
            print("✓ 不在登录页面，已登录或表单为公开")
            return True
        
        print(f"📝 检测到登录页面，尝试自动登录...")
        
        try:
            # 查找并填写邮箱
            email_selectors = [
                'input[type="email"]',
                'input[name*="email"]',
                'input[id*="email"]',
                'input[placeholder*="email" i]'
            ]
            
            for selector in email_selectors:
                email_input = await page.query_selector(selector)
                if email_input:
                    await email_input.fill(email)
                    print(f"  ✓ 填充邮箱: {email}")
                    break
            
            # 查找并填写密码
            password_input = await page.query_selector('input[type="password"]')
            if password_input:
                await password_input.fill(password)
                print(f"  ✓ 填充密码")
            
            # 查找并点击登录按钮
            login_selectors = [
                'button:has-text("Sign in")',
                'button:has-text("Login")',
                'button:has-text("Log in")',
                'button[type="submit"]',
                'input[type="submit"]'
            ]
            
            for selector in login_selectors:
                login_btn = await page.query_selector(selector)
                if login_btn and await login_btn.is_visible():
                    await login_btn.click()
                    print(f"  ✓ 点击登录按钮")
                    break
            
            # 等待登录完成
            await page.wait_for_load_state('networkidle', timeout=15000)
            await asyncio.sleep(2)
            
            # 检查是否需要人工干预
            if await HumanIntervention.detect_captcha(page):
                print("  ⚠️ 检测到 CAPTCHA")
                await HumanIntervention.wait_for_captcha(page)
            
            if await HumanIntervention.detect_2fa(page):
                print("  ⚠️ 检测到 2FA")
                await HumanIntervention.wait_for_2fa(page)
            
            print("✓ 登录完成")
            return True
        
        except Exception as e:
            print(f"  ✗ 登录异常: {e}")
            return False

