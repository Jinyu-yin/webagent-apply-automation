#!/usr/bin/env python3
"""
第一阶段：页面遍历和数据采集脚本

功能：
1. 登录表单系统
2. 遍历所有页面
3. 截图保存每个页面
4. 保存HTML结构
5. 检测并展开隐藏表单
6. 生成页面索引
7. 提取表单字段并存入数据库（可选）

用法：
    python scripts/01_crawl_pages.py --email xxx --password xxx --url xxx [--uni-id berkeley] [--save-to-db]
"""

import sys
import os
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import async_playwright, Page, Browser  # type: ignore


# 默认输出目录（可在运行时覆盖）
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "crawled_pages"


class PageCrawler:
    """页面遍历器 - 遍历所有表单页面并保存截图和HTML"""
    
    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir if output_dir else DEFAULT_OUTPUT_DIR
        self.screenshots_dir = self.output_dir / "screenshots"
        self.html_dir = self.output_dir / "html"
        self.page_index = []
        self.current_page_num = 0
        
        # 创建输出目录
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.html_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"📁 输出目录: {self.output_dir}")
    
    def log(self, message: str, level: str = "INFO"):
        """打印日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "ERROR": "❌",
            "WARN": "⚠️",
            "DEBUG": "📝",
            "STEP": "→",
        }.get(level, "→")
        print(f"[{timestamp}] {prefix} {message}")
    
    async def login(self, page: Page, email: str, password: str) -> bool:
        """登录系统"""
        self.log("开始登录...", "STEP")
        
        try:
            # 等待登录表单
            await page.wait_for_selector('input[type="email"], input[name*="email"]', timeout=15000)
            
            # 填写邮箱
            email_input = await page.query_selector('input[type="email"]') or \
                          await page.query_selector('input[name*="email"]')
            if email_input:
                await email_input.fill(email)
                self.log(f"填写邮箱: {email}", "DEBUG")
            
            # 填写密码
            await page.wait_for_selector('input[type="password"]', timeout=5000)
            password_input = await page.query_selector('input[type="password"]')
            if password_input:
                await password_input.fill(password)
                self.log("填写密码", "DEBUG")
            
            # 点击登录按钮
            login_button = await page.query_selector('button:has-text("Login")') or \
                           await page.query_selector('button[type="submit"]')
            if login_button:
                await login_button.click()
                self.log("点击登录按钮", "DEBUG")
            
            # 等待页面跳转
            await page.wait_for_load_state('networkidle', timeout=15000)
            await asyncio.sleep(2)
            
            # 验证登录成功
            current_url = page.url
            if "apply" in current_url and "login" not in current_url.lower():
                self.log("登录成功!", "SUCCESS")
                return True
            else:
                self.log(f"登录可能失败，当前URL: {current_url}", "WARN")
                return True  # 继续尝试
                
        except Exception as e:
            self.log(f"登录失败: {e}", "ERROR")
            return False
    
    async def save_page_state(self, page: Page, page_num: int, state_name: str = "main") -> dict:
        """保存页面状态（截图+HTML）"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 文件名
        screenshot_name = f"page_{page_num:02d}_{state_name}_{timestamp}.png"
        html_name = f"page_{page_num:02d}_{state_name}_{timestamp}.html"
        
        screenshot_path = self.screenshots_dir / screenshot_name
        html_path = self.html_dir / html_name
        
        # 保存截图
        try:
            await page.screenshot(path=str(screenshot_path), full_page=True)
            self.log(f"截图: {screenshot_name}", "DEBUG")
        except Exception as e:
            self.log(f"截图失败: {e}", "WARN")
            screenshot_path = None
        
        # 保存HTML
        try:
            html_content = await page.evaluate("() => document.documentElement.outerHTML")
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.log(f"HTML: {html_name}", "DEBUG")
        except Exception as e:
            self.log(f"保存HTML失败: {e}", "WARN")
            html_path = None
        
        return {
            "screenshot": str(screenshot_path) if screenshot_path else None,
            "html": str(html_path) if html_path else None,
            "timestamp": timestamp
        }
    
    async def extract_page_info(self, page: Page) -> dict:
        """提取当前页面信息"""
        try:
            info = await page.evaluate("""() => {
                // 获取页面标题
                const titleElem = document.querySelector('h1, h2, .page-title, .form-title');
                const pageTitle = titleElem ? titleElem.innerText.trim() : document.title;
                
                // 获取表单字段数量
                const inputs = document.querySelectorAll('input:not([type="hidden"]), select, textarea');
                const visibleInputs = Array.from(inputs).filter(el => {
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && style.visibility !== 'hidden';
                });
                
                // 获取 Add/添加 按钮
                const addButtons = [];
                document.querySelectorAll('a, button').forEach(el => {
                    const text = el.innerText.trim().toLowerCase();
                    if (text.includes('add') || text.includes('添加') || text.includes('new')) {
                        addButtons.push({
                            tag: el.tagName,
                            text: el.innerText.trim().substring(0, 50),
                            href: el.getAttribute('href') || el.getAttribute('data-href') || '',
                            onclick: el.getAttribute('onclick') || ''
                        });
                    }
                });
                
                // 获取隐藏弹窗
                const popups = [];
                document.querySelectorAll('[data-href*="Popup"], [onclick*="Popup"], .modal, .popup').forEach(el => {
                    popups.push({
                        tag: el.tagName,
                        text: el.innerText.trim().substring(0, 50),
                        dataHref: el.getAttribute('data-href') || '',
                        id: el.id || ''
                    });
                });
                
                // 获取导航按钮
                const navButtons = [];
                document.querySelectorAll('button, input[type="submit"], a.btn').forEach(el => {
                    const text = el.innerText.trim().toLowerCase();
                    if (text.includes('next') || text.includes('save') || text.includes('continue') ||
                        text.includes('previous') || text.includes('back')) {
                        navButtons.push({
                            tag: el.tagName,
                            text: el.innerText.trim(),
                            type: el.type || '',
                            class: el.className || ''
                        });
                    }
                });
                
                return {
                    title: pageTitle,
                    url: window.location.href,
                    fieldCount: visibleInputs.length,
                    addButtons: addButtons,
                    popups: popups,
                    navButtons: navButtons
                };
            }""")
            return info
        except Exception as e:
            self.log(f"提取页面信息失败: {e}", "WARN")
            return {"title": "Unknown", "url": page.url, "fieldCount": 0}
    
    async def detect_and_expand_hidden_forms(self, page: Page, page_num: int) -> list:
        """检测并展开隐藏表单/弹窗"""
        expanded_states = []
        
        try:
            # 查找所有 Add 按钮
            add_buttons = await page.evaluate("""() => {
                const buttons = [];
                document.querySelectorAll('a[data-href*="Popup"], a[onclick*="Popup"], button:has-text("Add"), a:has-text("Add")').forEach((el, idx) => {
                    buttons.push({
                        index: idx,
                        text: el.innerText.trim().substring(0, 50),
                        selector: el.id ? '#' + el.id : null,
                        dataHref: el.getAttribute('data-href') || ''
                    });
                });
                return buttons;
            }""")
            
            self.log(f"发现 {len(add_buttons)} 个 Add/弹窗按钮", "DEBUG")
            
            for btn in add_buttons[:5]:  # 最多展开5个
                try:
                    # 尝试点击按钮
                    if btn.get('selector'):
                        await page.click(btn['selector'])
                    elif btn.get('dataHref'):
                        # 通过 data-href 查找
                        await page.click(f'[data-href="{btn["dataHref"]}"]')
                    else:
                        # 通过文本查找
                        await page.click(f'text="{btn["text"]}"')
                    
                    await asyncio.sleep(1)
                    
                    # 检查是否有弹窗出现
                    popup_visible = await page.evaluate("""() => {
                        const popup = document.querySelector('.modal.show, .popup:visible, [role="dialog"]:visible, .fancybox-container');
                        return popup !== null;
                    }""")
                    
                    if popup_visible:
                        self.log(f"展开弹窗: {btn['text']}", "DEBUG")
                        
                        # 保存弹窗状态
                        state = await self.save_page_state(page, page_num, f"popup_{btn['text'][:20]}")
                        state['popup_trigger'] = btn['text']
                        expanded_states.append(state)
                        
                        # 关闭弹窗
                        close_btn = await page.query_selector('.modal .close, .fancybox-close, [data-dismiss="modal"], button:has-text("Cancel")')
                        if close_btn:
                            await close_btn.click()
                            await asyncio.sleep(0.5)
                
                except Exception as e:
                    self.log(f"展开按钮失败 '{btn['text']}': {e}", "DEBUG")
                    continue
        
        except Exception as e:
            self.log(f"检测隐藏表单失败: {e}", "WARN")
        
        return expanded_states
    
    async def click_next_page(self, page: Page) -> bool:
        """点击下一页按钮"""
        try:
            # 查找下一页按钮
            next_selectors = [
                'button:has-text("Save and Continue")',
                'button:has-text("Next")',
                'button:has-text("Continue")',
                'input[value*="Continue"]',
                'input[value*="Next"]',
                'button[type="submit"]:has-text("Save")',
                '.btn-primary:has-text("Continue")',
            ]
            
            for selector in next_selectors:
                try:
                    btn = await page.query_selector(selector)
                    if btn and await btn.is_visible():
                        # 滚动到按钮位置
                        await btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        
                        # 记录当前URL
                        old_url = page.url
                        
                        # 点击
                        await btn.click()
                        self.log(f"点击: {selector}", "DEBUG")
                        
                        # 等待页面变化
                        await page.wait_for_load_state('networkidle', timeout=15000)
                        await asyncio.sleep(1)
                        
                        # 检查URL是否变化
                        new_url = page.url
                        if new_url != old_url or await self.page_content_changed(page):
                            return True
                        
                except Exception:
                    continue
            
            self.log("未找到下一页按钮或已到最后一页", "WARN")
            return False
            
        except Exception as e:
            self.log(f"点击下一页失败: {e}", "ERROR")
            return False
    
    async def page_content_changed(self, page: Page) -> bool:
        """检查页面内容是否变化"""
        try:
            # 简单检查：看标题或表单字段是否变化
            return True  # 暂时总是返回True
        except:
            return True
    
    async def crawl_all_pages(self, page: Page, max_pages: int = 20, start_page: int = 1) -> list:
        """遍历所有页面"""
        self.log(f"开始遍历页面 (最多 {max_pages} 页, 从第 {start_page} 页开始)", "INFO")
        
        pages_data = []
        self.current_page_num = start_page
        
        while self.current_page_num <= max_pages:
            self.log(f"\n{'='*60}", "INFO")
            self.log(f"处理第 {self.current_page_num} 页", "INFO")
            self.log(f"{'='*60}", "INFO")
            
            # 提取页面信息
            page_info = await self.extract_page_info(page)
            self.log(f"页面标题: {page_info.get('title', 'Unknown')}", "INFO")
            self.log(f"字段数量: {page_info.get('fieldCount', 0)}", "INFO")
            
            # 保存主页面状态
            main_state = await self.save_page_state(page, self.current_page_num, "main")
            
            # 检测并展开隐藏表单
            popup_states = await self.detect_and_expand_hidden_forms(page, self.current_page_num)
            
            # 记录页面数据
            page_data = {
                "page_num": self.current_page_num,
                "info": page_info,
                "main_state": main_state,
                "popup_states": popup_states,
                "timestamp": datetime.now().isoformat()
            }
            pages_data.append(page_data)
            self.page_index.append(page_data)
            
            # 尝试进入下一页
            if not await self.click_next_page(page):
                self.log("无法继续，停止遍历", "WARN")
                break
            
            self.current_page_num += 1
            await asyncio.sleep(1)
        
        # 保存索引文件
        self.save_index()
        
        return pages_data
    
    def save_index(self):
        """保存页面索引"""
        index_path = self.output_dir / "page_index.json"
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(self.page_index, f, ensure_ascii=False, indent=2)
        self.log(f"索引已保存: {index_path}", "SUCCESS")


def extract_fields_from_html(html_dir: Path, uni_id: str) -> List[Dict]:
    """从 HTML 文件中提取表单字段"""
    from llm_form_automation.core.field_extractor import FieldExtractor
    
    extractor = FieldExtractor()
    all_fields = []
    
    for html_file in sorted(html_dir.glob('*.html')):
        # 从文件名提取页码 (page_01_main_xxx.html -> 1)
        try:
            page_num = int(html_file.name.split('_')[1])
        except (IndexError, ValueError):
            page_num = 1
        
        print(f"  提取字段: {html_file.name} (第 {page_num} 页)")
        
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        fields = extractor.extract_from_html(html_content, page_number=page_num)
        
        for field in fields:
            field['uni_id'] = uni_id
        
        all_fields.extend(fields)
        print(f"    → {len(fields)} 个字段")
    
    return all_fields


def save_fields_to_database(fields: List[Dict], uni_id: str, db=None) -> int:
    """将字段保存到数据库
    
    Args:
        fields: 字段列表
        uni_id: 学校 ID
        db: 数据库连接（可选，如果不传则自动创建）
    """
    if db is None:
        from dotenv import load_dotenv
        load_dotenv()
        from backend.db import get_db
        db = get_db()
    
    # 删除旧数据
    try:
        db.table('university_fields').delete().eq('uni_id', uni_id).execute()
        print(f"  已删除 uni_id={uni_id} 的旧数据")
    except Exception as e:
        print(f"  删除旧数据时出错: {e}")
    
    # 插入新数据
    success_count = 0
    for field in fields:
        try:
            db.table('university_fields').insert({
                'uni_id': field['uni_id'],
                'field_id': field['field_id'],
                'field_name': (field.get('field_name') or '')[:200],
                'field_label': (field.get('field_label') or '')[:500],
                'field_type': field.get('field_type', 'text'),
                'page_number': field.get('page_number', 1),
                'is_required': field.get('is_required', False),
                'options': field.get('options'),
                'placeholder': (field.get('placeholder') or '')[:500],
            }).execute()
            success_count += 1
        except Exception as e:
            print(f"    插入失败 {field['field_id'][:30]}...: {e}")
    
    return success_count


async def crawl_and_extract_fields(
    start_url: str,
    email: str,
    password: str,
    uni_id: str,
    db=None,
    max_pages: int = 15,
    headless: bool = False
) -> List[Dict]:
    """
    爬取页面并提取字段（供外部调用）
    
    Args:
        start_url: 申请系统 URL
        email: 登录邮箱
        password: 登录密码
        uni_id: 学校 ID
        db: 数据库连接（可选）
        max_pages: 最大页数
        headless: 是否无头模式
    
    Returns:
        提取到的字段列表
    """
    from llm_form_automation.core.field_extractor import FieldExtractor
    
    print(f"\n📥 开始爬取页面并提取字段")
    print(f"  URL: {start_url[:60]}...")
    print(f"  登录: {email}")
    print(f"  uni_id: {uni_id}")
    
    all_fields = []
    extractor = FieldExtractor()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        try:
            # 访问页面
            print(f"  🌐 访问页面...")
            await page.goto(start_url, wait_until='networkidle', timeout=30000)
            
            # 登录
            print(f"  🔐 登录中...")
            await _do_login(page, email, password)
            
            # 遍历页面并提取字段
            page_num = 1
            
            while page_num <= max_pages:
                print(f"  📄 处理第 {page_num} 页...")
                print(f"      当前URL: {page.url}")
                
                # 等待页面加载
                print(f"      ⏳ 等待页面加载...")
                await asyncio.sleep(2)
                
                # 获取页面标题
                print(f"      🏷️ 获取页面标题...")
                try:
                    title = await page.evaluate("""() => {
                        const h = document.querySelector('h1, h2, .page-title');
                        return h ? h.innerText.trim() : 'Unknown';
                    }""")
                    print(f"      ✅ 页面标题: {title}")
                except Exception as e:
                    print(f"      ❌ 获取标题失败: {e}")
                    title = "Unknown"
                
                # 获取 HTML 并提取字段
                print(f"      📄 获取页面HTML...")
                try:
                    html_content = await page.evaluate("() => document.documentElement.outerHTML")
                    html_length = len(html_content)
                    print(f"      ✅ HTML获取成功，长度: {html_length} 字符")
                except Exception as e:
                    print(f"      ❌ HTML获取失败: {e}")
                    continue
                
                print(f"      🔍 提取表单字段...")
                try:
                    fields = extractor.extract_from_html(html_content, page_number=page_num)
                    print(f"      ✅ 字段提取成功: {len(fields)} 个")
                    
                    # 显示前几个字段
                    if fields:
                        print(f"      📋 前3个字段:")
                        for i, field in enumerate(fields[:3]):
                            print(f"        {i+1}. {field.get('field_label', field.get('field_id', 'Unknown'))}")
                    
                    # 设置 uni_id
                    for field in fields:
                        field['uni_id'] = uni_id
                    
                    all_fields.extend(fields)
                    print(f"      ✅ 累计字段数: {len(all_fields)}")
                    
                except Exception as e:
                    print(f"      ❌ 字段提取失败: {e}")
                    import traceback
                    traceback.print_exc()
                
                # 尝试点击下一页
                print(f"      🖱️ 尝试点击下一页...")
                if not await _click_next_page(page):
                    print("  ✅ 已到最后一页或无下一页按钮")
                    break
                else:
                    print(f"      ✅ 成功进入下一页")
                
                page_num += 1
                await asyncio.sleep(1)
            
        finally:
            await browser.close()
    
    # 去重
    unique_fields = {}
    for f in all_fields:
        key = f"{f['uni_id']}_{f['field_id']}"
        if key not in unique_fields:
            unique_fields[key] = f
    all_fields = list(unique_fields.values())
    
    print(f"\n  总共提取 {len(all_fields)} 个唯一字段")
    
    # 存入数据库
    if db is not None or uni_id:
        print(f"\n  💾 开始存入数据库...")
        print(f"      uni_id: {uni_id}")
        print(f"      字段数: {len(all_fields)}")
        
        if all_fields:
            print(f"      📋 字段示例:")
            for i, field in enumerate(all_fields[:3]):
                print(f"        {i+1}. ID: {field.get('field_id')}")
                print(f"           Label: {field.get('field_label')}")
                print(f"           Type: {field.get('field_type')}")
                print(f"           uni_id: {field.get('uni_id')}")
        
        success_count = save_fields_to_database(all_fields, uni_id, db)
        print(f"  ✅ 数据库存储完成: {success_count}/{len(all_fields)} 个字段成功")
    
    return all_fields


async def _do_login(page, email: str, password: str):
    """执行登录（内部函数）"""
    try:
        print(f"  🔐 开始登录流程...")
        print(f"      当前URL: {page.url}")
        
        # 等待登录表单
        print(f"  🔍 等待登录表单...")
        await page.wait_for_selector('input[type="email"], input[name*="email"]', timeout=10000)
        print(f"  ✅ 找到登录表单")
        
        # 填写邮箱
        print(f"  📧 填写邮箱: {email}")
        email_input = await page.query_selector('input[type="email"]') or \
                      await page.query_selector('input[name*="email"]')
        if email_input:
            await email_input.fill(email)
            print(f"  ✅ 邮箱填写完成")
        else:
            print(f"  ❌ 未找到邮箱输入框")
        
        # 填写密码
        print(f"  🔑 填写密码...")
        password_input = await page.query_selector('input[type="password"]')
        if password_input:
            await password_input.fill(password)
            print(f"  ✅ 密码填写完成")
        else:
            print(f"  ❌ 未找到密码输入框")
        
        # 点击登录
        print(f"  🖱️ 点击登录按钮...")
        login_btn = await page.query_selector('button:has-text("Login")') or \
                    await page.query_selector('button[type="submit"]')
        if login_btn:
            await login_btn.click()
            print(f"  ✅ 登录按钮点击完成")
        else:
            print(f"  ❌ 未找到登录按钮")
        
        print(f"  ⏳ 等待页面跳转...")
        await page.wait_for_load_state('networkidle', timeout=15000)
        await asyncio.sleep(2)
        
        print(f"  🎯 登录后URL: {page.url}")
        print(f"  ✅ 登录流程完成")
        
    except Exception as e:
        print(f"  ❌ 登录异常: {e}")
        print(f"      当前URL: {page.url}")
        import traceback
        traceback.print_exc()


async def _click_next_page(page) -> bool:
    """点击下一页（内部函数）"""
    next_selectors = [
        'button:has-text("Save and Continue")',
        'button:has-text("Continue")',
        'button:has-text("Next")',
    ]
    
    for selector in next_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_load_state('networkidle', timeout=15000)
                return True
        except:
            continue
    
    return False


async def main(start_url: str, email: str, password: str, headless: bool = False, 
               start_page: int = 1, max_pages: int = 20, output_dir: Optional[Path] = None,
               uni_id: Optional[str] = None, save_to_db: bool = False):
    """主函数
    
    Args:
        start_url: 起始 URL
        email: 登录邮箱
        password: 登录密码
        headless: 是否无头模式
        start_page: 起始页码
        max_pages: 最大页数
        output_dir: 输出目录
        uni_id: 学校 ID（用于存入数据库）
        save_to_db: 是否存入数据库
    """
    crawler = PageCrawler(output_dir=output_dir)
    
    print("\n" + "="*70)
    print("🔍 页面遍历和数据采集脚本")
    print("="*70)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        try:
            # 访问起始页
            crawler.log(f"访问: {start_url}", "INFO")
            await page.goto(start_url, wait_until='networkidle', timeout=30000)
            
            # 登录
            if not await crawler.login(page, email, password):
                crawler.log("登录失败，退出", "ERROR")
                return
            
            # 遍历所有页面
            pages_data = await crawler.crawl_all_pages(
                page, 
                max_pages=max_pages,
                start_page=start_page
            )
            
            print("\n" + "="*70)
            print(f"✅ 遍历完成！共处理 {len(pages_data)} 页")
            print(f"📁 数据保存在: {crawler.output_dir}")
            print("="*70)
            
        except Exception as e:
            crawler.log(f"发生错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
        
        finally:
            await browser.close()
    
    # ========== 提取字段并存入数据库 ==========
    if save_to_db and uni_id:
        print("\n" + "="*70)
        print("📥 提取字段并存入数据库")
        print("="*70)
        
        # 从 HTML 提取字段
        all_fields = extract_fields_from_html(crawler.html_dir, uni_id)
        print(f"\n总共提取到 {len(all_fields)} 个字段")
        
        # 存入数据库
        print(f"\n存入数据库 (uni_id={uni_id})...")
        success_count = save_fields_to_database(all_fields, uni_id)
        print(f"\n✅ 成功存入 {success_count}/{len(all_fields)} 个字段")
    elif save_to_db and not uni_id:
        print("\n⚠️ 需要指定 --uni-id 才能存入数据库")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="页面遍历和数据采集")
    parser.add_argument("--headless", action="store_true", help="无头模式运行")
    parser.add_argument("--start-page", type=int, default=1, help="起始页码")
    parser.add_argument("--max-pages", type=int, default=20, help="最大页数")
    parser.add_argument("--email", type=str, required=True, help="登录邮箱（必填）")
    parser.add_argument("--password", type=str, required=True, help="登录密码（必填）")
    parser.add_argument("--url", type=str, required=True, help="起始URL（必填）")
    parser.add_argument("--uni-id", type=str, help="学校ID，用于存入数据库（如 berkeley）")
    parser.add_argument("--save-to-db", action="store_true", help="提取字段后存入数据库")
    args = parser.parse_args()
    
    asyncio.run(main(
        start_url=args.url,
        email=args.email,
        password=args.password,
        headless=args.headless,
        start_page=args.start_page,
        max_pages=args.max_pages,
        uni_id=args.uni_id,
        save_to_db=args.save_to_db
    ))
