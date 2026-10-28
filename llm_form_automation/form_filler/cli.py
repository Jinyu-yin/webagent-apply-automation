#!/usr/bin/env python3
"""
LLM 表单填写 - 统一 CLI 入口

支持多种模式：
1. payload: 从 Payload 精确填写
2. hybrid: 混合模式（精确 + LLM 定位 + Agent 补充）
3. agent: 纯 Agent 模式（使用 browser-use）
4. retry: 定向重填失败字段
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import async_playwright


async def run_payload_mode(args):
    """Payload 精确填写模式"""
    from llm_form_automation.form_filler import (
        LLMFormFiller,
        LoginHandler,
        SubmissionChecker,
    )
    
    payload_path = Path(args.payload)
    
    if not payload_path.exists():
        print(f"❌ Payload 文件不存在: {payload_path}")
        return
    
    if not args.url:
        print("❌ 需要 --url 参数")
        return
    
    # 加载 payload
    with open(payload_path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    
    payload_fields = payload.get("fields", payload.get("data", {}))
    apply_record_id = args.apply_record_id or payload.get("apply_record_id")
    
    print("\n" + "=" * 70)
    print("🎯 Payload 精确填写模式")
    print("=" * 70)
    print(f"📦 Payload: {payload_path}")
    print(f"📋 字段数: {len(payload_fields)}")
    print(f"🌐 目标URL: {args.url}")
    print("=" * 70)
    
    # 初始化数据库连接
    db = None
    if apply_record_id:
        try:
            from backend.db import get_db
            db = get_db()
            print("✅ 数据库连接成功")
        except Exception as e:
            print(f"⚠️ 数据库连接失败: {e}")
    
    # 初始化填写器
    filler = LLMFormFiller(payload_path=payload_path, start_url=args.url)
    
    if db and apply_record_id:
        filler.set_db_connection(db, apply_record_id)
    
    all_reports = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        try:
            filler.log(f"访问: {args.url}", "INFO")
            await page.goto(args.url, wait_until='networkidle', timeout=30000)
            
            # 登录
            if args.email and args.password:
                filler.log("开始登录...", "INFO")
                await LoginHandler.login_if_needed(page, args.email, args.password)
            
            await asyncio.sleep(2)
            
            # 主循环
            page_num = 1
            max_pages = args.max_pages
            
            while page_num <= max_pages:
                report = await filler.fill_page_from_payload(page, page_num)
                all_reports.append(report)
                
                if args.page > 0 and page_num >= args.page:
                    break
                
                # 尝试下一页
                from llm_form_automation.form_filler import get_element_finder
                finder = get_element_finder()
                
                if not await finder.click_element(page, "下一页/继续/保存并继续按钮"):
                    filler.log("无法找到下一页按钮，停止", "WARN")
                    break
                
                await asyncio.sleep(2)
                page_num += 1
            
            # 验证
            submission_result = await SubmissionChecker.check_submission_success(page)
            
            # 汇总
            summary = {
                "timestamp": datetime.now().isoformat(),
                "pages_processed": len(all_reports),
                "total_filled": sum(len(r.get("fields_filled", [])) for r in all_reports),
                "total_no_value": sum(len(r.get("fields_no_value", [])) for r in all_reports),
                "total_failed": sum(len(r.get("fields_failed", [])) for r in all_reports),
                "submission": submission_result,
            }
            
            filler.save_fill_report({"summary": summary, "pages": all_reports})
            
            print("\n" + "=" * 70)
            print("✅ 完成！")
            print(f"✅ 已填写: {summary['total_filled']}")
            print(f"⚠️ 无匹配值: {summary['total_no_value']}")
            print(f"❌ 失败: {summary['total_failed']}")
            print("=" * 70)
        
        except Exception as e:
            print(f"❌ 错误: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await browser.close()


async def run_hybrid_mode(args):
    """混合模式：精确填写 + LLM 定位 + Agent 补充"""
    from llm_form_automation.form_filler import (
        HybridFormFiller,
        LoginHandler,
        HAS_BROWSER_USE,
    )
    
    if not HAS_BROWSER_USE:
        print("⚠️ browser-use 未安装，回退到 payload 模式")
        return await run_payload_mode(args)
    
    payload_path = Path(args.payload)
    
    if not payload_path.exists():
        print(f"❌ Payload 文件不存在: {payload_path}")
        return
    
    if not args.url:
        print("❌ 需要 --url 参数")
        return
    
    print("\n" + "=" * 70)
    print("🔄 混合填写模式")
    print("=" * 70)
    print(f"📦 Payload: {payload_path}")
    print(f"🌐 目标URL: {args.url}")
    print("=" * 70)
    
    filler = HybridFormFiller(
        payload_path=payload_path,
        use_agent_fallback=True,
        headless=args.headless,
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        
        try:
            await page.goto(args.url, wait_until='networkidle', timeout=30000)
            
            if args.email and args.password:
                await LoginHandler.login_if_needed(page, args.email, args.password)
            
            await asyncio.sleep(2)
            
            # 主循环
            page_num = 1
            all_reports = []
            
            while page_num <= args.max_pages:
                report = await filler.fill_page(
                    page, 
                    page_num,
                    use_agent_for_failures=args.use_agent,
                )
                all_reports.append(report)
                
                if args.page > 0 and page_num >= args.page:
                    break
                
                if not await filler.click_next(page):
                    print("无法找到下一页按钮，停止")
                    break
                
                await asyncio.sleep(2)
                page_num += 1
            
            # 汇总
            total_filled = sum(len(r.get("fields_filled", [])) for r in all_reports)
            total_no_value = sum(len(r.get("fields_no_value", [])) for r in all_reports)
            total_failed = sum(len(r.get("fields_failed", [])) for r in all_reports)
            
            print("\n" + "=" * 70)
            print("✅ 混合模式完成！")
            print(f"✅ 已填写: {total_filled}")
            print(f"⚠️ 无匹配值: {total_no_value}")
            print(f"❌ 失败: {total_failed}")
            print("=" * 70)
        
        except Exception as e:
            print(f"❌ 错误: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await filler.close()
            await browser.close()


async def run_agent_mode(args):
    """纯 Agent 模式（使用 browser-use）"""
    from llm_form_automation.form_filler import (
        BrowserUseFormFiller,
        HAS_BROWSER_USE,
    )
    
    if not HAS_BROWSER_USE:
        print("❌ browser-use 未安装")
        print("请运行: pip install browser-use")
        return
    
    payload_path = Path(args.payload)
    
    if not payload_path.exists():
        print(f"❌ Payload 文件不存在: {payload_path}")
        return
    
    if not args.url:
        print("❌ 需要 --url 参数")
        return
    
    print("\n" + "=" * 70)
    print("🤖 Agent 智能填写模式")
    print("=" * 70)
    print(f"📦 Payload: {payload_path}")
    print(f"🌐 目标URL: {args.url}")
    print("=" * 70)
    
    filler = BrowserUseFormFiller(
        payload_path=payload_path,
        llm_provider=args.llm_provider,
        model=args.model,
        headless=args.headless,
    )
    
    try:
        # 可以指定额外指令
        additional = ""
        if args.email:
            additional += f"\n登录邮箱: {args.email}"
        if args.password:
            additional += f"\n登录密码: {args.password}"
        
        result = await filler.fill_form_with_agent(
            url=args.url,
            additional_instructions=additional,
        )
        
        print("\n" + "=" * 70)
        if result["success"]:
            print("✅ Agent 任务完成！")
            print(f"结果: {result.get('result', 'N/A')}")
        else:
            print("⚠️ Agent 任务未完成")
        print("=" * 70)
    
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await filler.close()


async def run_retry_mode(args):
    """定向重填失败字段模式"""
    from llm_form_automation.form_filler import (
        LLMFormFiller,
        LoginHandler,
    )
    
    if not args.apply_record_id:
        print("❌ --retry 模式需要 --apply-record-id 参数")
        return
    
    payload_path = Path(args.payload)
    apply_record_id = args.apply_record_id
    
    # 数据库连接
    try:
        from backend.db import get_db
        db = get_db()
        print("✅ 数据库连接成功")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return
    
    # 获取失败字段
    fill_result = db.get_fill_result(apply_record_id)
    if not fill_result:
        print("❌ 未找到填写结果")
        return
    
    fields_failed = fill_result.get("fields_failed", [])
    checkpoint = db.get_checkpoint(apply_record_id)
    
    if not fields_failed:
        print("✅ 没有失败的字段")
        return
    
    print("\n" + "=" * 70)
    print("🔄 定向重填模式")
    print("=" * 70)
    print(f"❌ 待重填: {len(fields_failed)} 个字段")
    print("=" * 70)
    
    # 构建重填 payload
    retry_payload = {}
    if payload_path.exists():
        with open(payload_path, 'r', encoding='utf-8') as f:
            original = json.load(f)
        original_fields = original.get("fields", original.get("data", {}))
        
        for f in fields_failed:
            field_id = f.get("field_id")
            if field_id and field_id in original_fields:
                retry_payload[field_id] = original_fields[field_id]
    
    start_url = args.url or (checkpoint.get("page_url") if checkpoint else None)
    if not start_url:
        print("❌ 需要 --url 参数或 checkpoint 中的 page_url")
        return
    
    filler = LLMFormFiller(payload_path=payload_path, start_url=start_url)
    filler.set_db_connection(db, apply_record_id)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        
        try:
            await page.goto(start_url, wait_until='networkidle', timeout=30000)
            
            if args.email and args.password:
                await LoginHandler.login_if_needed(page, args.email, args.password)
            
            await asyncio.sleep(2)
            
            # 重填
            from llm_form_automation.form_filler import get_element_finder
            finder = get_element_finder()
            
            success_count = 0
            for f in fields_failed:
                field_id = f.get("field_id")
                field_label = f.get("field_label") or field_id
                
                if field_id not in retry_payload:
                    continue
                
                data = retry_payload[field_id]
                value = data.get("value") if isinstance(data, dict) else data
                
                if not value:
                    continue
                
                # 使用 LLM 定位并填写
                result = await finder.find_element(page, field_label, "input")
                if result:
                    try:
                        elem = await page.query_selector(result["selector"])
                        if elem:
                            await elem.fill(str(value))
                            print(f"✅ 重填成功: {field_label}")
                            success_count += 1
                    except:
                        print(f"❌ 重填失败: {field_label}")
            
            print("\n" + "=" * 70)
            print(f"✅ 重填完成: {success_count}/{len(fields_failed)}")
            print("=" * 70)
        
        except Exception as e:
            print(f"❌ 错误: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await browser.close()


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="LLM 智能表单填写 - 统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
模式说明：
  payload  从 Payload 精确填写（默认）
  hybrid   混合模式（精确 + LLM 定位 + Agent 补充）
  agent    纯 Agent 模式（使用 browser-use）
  retry    定向重填失败字段

示例：
  # Payload 模式
  python -m llm_form_automation.form_filler.cli \\
    --mode payload --payload payload.json --url https://example.com
  
  # 混合模式
  python -m llm_form_automation.form_filler.cli \\
    --mode hybrid --payload payload.json --url https://example.com --use-agent
  
  # Agent 模式
  python -m llm_form_automation.form_filler.cli \\
    --mode agent --payload payload.json --url https://example.com
  
  # 重填模式
  python -m llm_form_automation.form_filler.cli \\
    --mode retry --payload payload.json --apply-record-id 123
        """
    )
    
    # 模式选择
    parser.add_argument(
        "--mode", 
        type=str, 
        default="payload",
        choices=["payload", "hybrid", "agent", "retry"],
        help="填写模式"
    )
    
    # 通用参数
    parser.add_argument("--payload", type=str, required=True, help="Payload 文件路径")
    parser.add_argument("--url", type=str, help="起始 URL")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--page", type=int, default=0, help="指定页码（0=全部）")
    parser.add_argument("--max-pages", type=int, default=20, help="最大页数")
    
    # 登录参数
    parser.add_argument("--email", type=str, help="登录邮箱")
    parser.add_argument("--password", type=str, help="登录密码")
    
    # 数据库参数
    parser.add_argument("--apply-record-id", type=int, help="申请记录 ID")
    
    # Agent 参数
    parser.add_argument("--use-agent", action="store_true", help="启用 Agent 补充填写")
    parser.add_argument("--llm-provider", type=str, default="openai", help="LLM 提供商")
    parser.add_argument("--model", type=str, help="模型名称")
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("🤖 LLM 智能表单填写")
    print("=" * 70)
    
    if args.mode == "payload":
        await run_payload_mode(args)
    elif args.mode == "hybrid":
        await run_hybrid_mode(args)
    elif args.mode == "agent":
        await run_agent_mode(args)
    elif args.mode == "retry":
        await run_retry_mode(args)
    else:
        print(f"❌ 未知模式: {args.mode}")


if __name__ == "__main__":
    asyncio.run(main())
