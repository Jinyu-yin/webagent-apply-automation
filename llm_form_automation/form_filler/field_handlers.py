"""
特殊字段处理模块

处理特殊类型的表单字段：
- 日期下拉框组合（月/日/年分离）
- Radio 组
- 可折叠区域
"""

import asyncio
import re
from typing import Optional, Tuple
from playwright.async_api import Page


class SpecialFieldHandler:
    """处理特殊类型的表单字段"""
    
    # 月份名称映射
    MONTH_NAMES = {
        '01': 'january', '02': 'february', '03': 'march',
        '04': 'april', '05': 'may', '06': 'june',
        '07': 'july', '08': 'august', '09': 'september',
        '10': 'october', '11': 'november', '12': 'december',
        '1': 'january', '2': 'february', '3': 'march',
        '4': 'april', '5': 'may', '6': 'june',
        '7': 'july', '8': 'august', '9': 'september'
    }
    
    @classmethod
    def parse_date(cls, date_str: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        解析日期字符串
        
        支持格式: MM/DD/YYYY, YYYY-MM-DD, DD-MM-YYYY
        
        Returns:
            (month, day, year) 或 (None, None, None)
        """
        try:
            date_str = date_str.strip()
            
            # 格式1: MM/DD/YYYY
            if '/' in date_str:
                parts = date_str.split('/')
                if len(parts) == 3:
                    month, day, year = parts
                    return month.zfill(2), day.zfill(2), year
            
            # 格式2: YYYY-MM-DD
            if '-' in date_str:
                parts = date_str.split('-')
                if len(parts) == 3 and len(parts[0]) == 4:
                    year, month, day = parts
                    return month.zfill(2), day.zfill(2), year
                # 格式3: DD-MM-YYYY
                elif len(parts) == 3:
                    day, month, year = parts
                    return month.zfill(2), day.zfill(2), year
            
            # 尝试智能解析 - 查找4位年份
            year_match = re.search(r'\b(19|20)\d{2}\b', date_str)
            if year_match:
                year = year_match.group()
                nums = re.findall(r'\b\d{1,2}\b', date_str)
                if len(nums) >= 2:
                    month, day = nums[0].zfill(2), nums[1].zfill(2)
                    return month, day, year
            
            return None, None, None
        except:
            return None, None, None
    
    @classmethod
    async def fill_date_select_group(cls, page: Page, base_id: str, date_value: str) -> bool:
        """
        填充日期下拉框组合（月/日/年分离的 select）
        
        HTML 示例:
        <select id="form_xxx_m">  <!-- 月份 -->
        <select id="form_xxx_d">  <!-- 日期 -->
        <select id="form_xxx_y">  <!-- 年份 -->
        """
        month, day, year = cls.parse_date(date_value)
        if not all([month, day, year]):
            print(f"    ⚠️ 日期解析失败: {date_value}")
            return False
        
        # 去除可能的后缀
        for suffix in ['_m', '_d', '_y', '_month', '_day', '_year']:
            base_id = base_id.replace(suffix, '')
        
        success = True
        
        # 填充月份
        month_select = await page.query_selector(f'#{base_id}_m')
        if month_select:
            success &= await cls._fill_date_select_part(page, month_select, month, "月份")
        
        # 填充日期
        day_select = await page.query_selector(f'#{base_id}_d')
        if day_select:
            success &= await cls._fill_date_select_part(page, day_select, day, "日期")
        
        # 填充年份
        year_select = await page.query_selector(f'#{base_id}_y')
        if year_select:
            success &= await cls._fill_date_select_part(page, year_select, year, "年份")
        
        return success
    
    @classmethod
    async def _fill_date_select_part(cls, page: Page, select_elem, value: str, part_name: str) -> bool:
        """填充单个日期 select"""
        try:
            options = await select_elem.query_selector_all('option')
            value_str = str(value).strip()
            
            # 如果是月份，尝试月份名称匹配
            if part_name == "月份" and value_str in cls.MONTH_NAMES:
                target_month = cls.MONTH_NAMES[value_str]
                for opt in options:
                    opt_text = await opt.text_content()
                    opt_value = await opt.get_attribute('value')
                    if opt_text:
                        opt_text_lower = opt_text.strip().lower()
                        if target_month == opt_text_lower or value_str == opt_value:
                            if opt_value:
                                await select_elem.select_option(value=opt_value)
                            else:
                                await select_elem.select_option(label=opt_text.strip())
                            print(f"    ✓ {part_name}: {opt_text.strip()}")
                            return True
            
            # 1. 精确值匹配
            for opt in options:
                opt_value = await opt.get_attribute('value')
                if opt_value and opt_value == value_str:
                    await select_elem.select_option(value=opt_value)
                    print(f"    ✓ {part_name}: {value_str}")
                    return True
            
            # 2. 精确文本匹配
            for opt in options:
                opt_text = await opt.text_content()
                if opt_text and opt_text.strip() == value_str:
                    opt_value = await opt.get_attribute('value')
                    if opt_value:
                        await select_elem.select_option(value=opt_value)
                    else:
                        await select_elem.select_option(label=opt_text.strip())
                    print(f"    ✓ {part_name}: {value_str}")
                    return True
            
            # 3. 去除前导零匹配
            value_int = value_str.lstrip('0') or '0'
            for opt in options:
                opt_value = await opt.get_attribute('value') or ''
                opt_text = await opt.text_content()
                opt_text = opt_text.strip() if opt_text else ''
                if opt_value == value_int or opt_text == value_int:
                    if opt_value:
                        await select_elem.select_option(value=opt_value)
                    else:
                        await select_elem.select_option(label=opt_text)
                    print(f"    ✓ {part_name}: {value_int}")
                    return True
            
            print(f"    ⚠️ 未找到{part_name}选项: {value_str}")
            return False
        
        except Exception as e:
            print(f"    ❌ {part_name}填充异常: {e}")
            return False
    
    @classmethod
    async def detect_date_select_group(cls, page: Page, field_id: str) -> bool:
        """检测是否是日期下拉框组合"""
        try:
            base_id = field_id
            for suffix in ['_m', '_d', '_y', '_month', '_day', '_year']:
                base_id = base_id.replace(suffix, '')
            
            month_select = await page.query_selector(f'#{base_id}_m, #{base_id}_month')
            day_select = await page.query_selector(f'#{base_id}_d, #{base_id}_day')
            year_select = await page.query_selector(f'#{base_id}_y, #{base_id}_year')
            
            return bool(month_select and day_select and year_select)
        except:
            return False
    
    @classmethod
    async def fill_radio_group_by_label(cls, page: Page, container_selector: str, target_value: str) -> bool:
        """通过标签文本填充 Radio 组"""
        try:
            container = await page.query_selector(container_selector)
            if not container:
                return False
            
            radios = await container.query_selector_all('input[type="radio"], input[type="checkbox"]')
            target_lower = target_value.lower().strip()
            
            for radio in radios:
                radio_id = await radio.get_attribute('id')
                if radio_id:
                    label = await page.query_selector(f'label[for="{radio_id}"]')
                    if label:
                        label_text = await label.text_content()
                        if label_text:
                            label_lower = label_text.strip().lower()
                            if target_lower == label_lower or target_lower in label_lower:
                                await radio.check()
                                print(f"    ✓ 选择: {label_text.strip()}")
                                return True
            
            return False
        
        except Exception as e:
            print(f"    ❌ Radio 组填充异常: {e}")
            return False


class CollapsibleHandler:
    """处理可折叠表单区域"""
    
    def __init__(self):
        self._clicked_buttons = set()
    
    async def expand_all_sections(self, page: Page) -> int:
        """
        展开所有可折叠区域
        
        Returns:
            展开的区域数量
        """
        expanded_count = 0
        
        patterns = [
            ("button[aria-expanded='false']", "aria-expanded"),
            ("button[data-toggle='collapse']", "data-toggle"),
            ("div[role='button'][aria-expanded='false']", "aria-expanded"),
            ("a[role='button'][aria-expanded='false']", "aria-expanded"),
            (".accordion-button.collapsed", "class"),
            (".collapsible:not(.active)", "class"),
            ("[data-expandable='true']", "data-expandable"),
        ]
        
        for selector, attr in patterns:
            try:
                elements = await page.query_selector_all(selector)
                
                for elem in elements:
                    try:
                        label = await elem.text_content() or ""
                        label = label.strip()[:50]
                        
                        # 跳过 "Add New" 类型的按钮
                        if any(kw in label.lower() for kw in ['add', 'new', 'modal', 'dialog']):
                            continue
                        
                        elem_id = await elem.get_attribute('id') or label
                        section_id = f"{selector}_{elem_id}"
                        
                        if section_id not in self._clicked_buttons:
                            await elem.click()
                            self._clicked_buttons.add(section_id)
                            await asyncio.sleep(0.5)
                            expanded_count += 1
                            print(f"  ✓ 展开区域: {label}")
                    except:
                        continue
            except:
                continue
        
        return expanded_count

