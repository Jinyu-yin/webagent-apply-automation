# 注册服务接入指南

## 一、服务概述

注册服务使用 `browser-use` 库实现自动化注册流程，通过 LLM 智能识别页面元素并完成表单填写。

### 当前测试结果 (2024-12-10)

**✅ 已验证功能：**
- 自动导航到登录/注册页面
- 智能识别注册入口（即使 URL 不精确）
- 自动填写邮箱、姓名、生日等信息
- 自动选择下拉选项
- 状态同步到数据库 (`apply_record.register_status`)

**⏸️ 需要人工/模块介入：**
- 邮箱验证码提取（需要接入邮箱模块）

---

## 二、服务启动方式

### 1. 环境准备

```bash
cd /Users/liuqi/code/WebAgent

# 确保 .env 文件包含以下配置
cat .env
# SUPABASE_URL=https://xxx.supabase.co
# SUPABASE_KEY=xxx
# OPENAI_API_KEY=xxx
# OPENAI_BASE_URL=https://openrouter.ai/api/v1  # 可选
```

### 2. 依赖版本

```bash
# 重要：使用 browser-use 0.1.48 版本（新版本有 CDP 连接问题）
pip install browser-use==0.1.48
pip install langchain-openai
```

### 3. 启动服务

```bash
cd /Users/liuqi/code/WebAgent

# 方式一：直接启动（推荐）
python -c "
from dotenv import load_dotenv
load_dotenv()
import uvicorn
uvicorn.run('main:app', host='0.0.0.0', port=8080)
"

# 方式二：使用 uvicorn 命令
python -m dotenv run uvicorn main:app --host 0.0.0.0 --port 8080
```

### 4. 测试注册 API

```bash
# 调用注册接口
curl -X POST http://127.0.0.1:8080/api/v2/register \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "email": "your_email@example.com",
    "password": "your_password",
    "url": "https://gradapp.berkeley.edu/account/login",
    "headless": false
  }'

# 查询注册状态
curl http://127.0.0.1:8080/api/v2/register-status/22
```

---

## 三、邮箱验证码模块接入点

### 接入位置

**文件：** `backend/services/register_service.py`

**位置：** `RegisterService.register()` 方法中，第 95-103 行附近

```python
# 当前代码 (第 95 行)
history = await agent.run()

# 提取最终结果
final_result = ''
if history:
    if hasattr(history, 'final_result'):
        final_result = history.final_result()
    else:
        final_result = str(history)
```

### 接入方案

在 `agent.run()` 完成后，检测是否需要邮箱验证码，如果需要则调用邮箱模块：

```python
# ========== 建议的接入代码 ==========

# 5. 执行注册
logger.info(f"开始注册: {email} @ {url}")
history = await agent.run()

# 提取最终结果
final_result = ''
if history:
    if hasattr(history, 'final_result'):
        final_result = history.final_result()
    else:
        final_result = str(history)

# ⬇️ 新增：检测是否需要邮箱验证码
if self._needs_email_verification(final_result):
    logger.info("检测到需要邮箱验证码，等待邮箱模块...")
    
    # 调用邮箱模块获取验证码
    verification_code = await self._get_verification_code_from_email(
        email=email,
        timeout=120,  # 等待 2 分钟
        subject_keywords=["verification", "PIN", "code", "验证"]
    )
    
    if verification_code:
        logger.info(f"获取到验证码: {verification_code}")
        
        # 继续自动化流程，填写验证码
        agent_step2 = Agent(
            task=f"在当前页面找到验证码输入框，输入验证码 {verification_code}，然后点击提交/验证按钮",
            llm=llm,
        )
        history2 = await agent_step2.run()
        final_result = history2.final_result() if hasattr(history2, 'final_result') else str(history2)
    else:
        logger.warning("未能获取邮箱验证码")
        final_result += "\n\n[需要手动输入邮箱验证码]"
```

### 需要实现的方法

```python
def _needs_email_verification(self, result_text: str) -> bool:
    """检测是否需要邮箱验证码"""
    keywords = [
        'email verification',
        'temporary PIN',
        'verification code',
        '验证码',
        'check your email',
        'sent to your email'
    ]
    result_lower = result_text.lower()
    return any(kw.lower() in result_lower for kw in keywords)

async def _get_verification_code_from_email(
    self,
    email: str,
    timeout: int = 120,
    subject_keywords: list = None
) -> str:
    """
    从邮箱获取验证码
    
    TODO: 接入邮箱服务模块
    参考：/Users/liuqi/code/email/ 项目
    
    Args:
        email: 接收验证码的邮箱
        timeout: 等待超时时间（秒）
        subject_keywords: 邮件主题关键词
    
    Returns:
        验证码字符串，未找到返回空字符串
    """
    # 示例实现（需要替换为真实邮箱模块）
    from email_service import EmailService  # 假设的邮箱模块
    
    email_svc = EmailService(email)
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        # 获取最新邮件
        latest_email = await email_svc.get_latest_email(
            subject_keywords=subject_keywords,
            since_minutes=5
        )
        
        if latest_email:
            # 提取验证码（通常是 4-8 位数字）
            import re
            code_match = re.search(r'\b(\d{4,8})\b', latest_email.body)
            if code_match:
                return code_match.group(1)
        
        await asyncio.sleep(5)  # 每 5 秒检查一次
    
    return ""
```

---

## 四、数据库状态说明

### apply_record 表

| 字段 | 说明 |
|------|------|
| `register_status` | 注册状态：`""` (未开始), `"registering"` (进行中), `"success"` (成功), `"failed"` (失败) |
| `email` | 注册邮箱 |
| `password` | 注册密码 |
| `application_url` | 申请系统 URL |

### 状态流转

```
[空] → registering → success
                  ↘ failed
```

---

## 五、API 接口说明

### POST /api/v2/register

**请求体：**
```json
{
    "apply_record_id": 22,          // 必填：申请记录 ID
    "email": "user@example.com",    // 必填：注册邮箱
    "password": "password123",      // 必填：注册密码
    "url": "https://...",           // 必填：注册页面 URL
    "uni_id": "berkeley",           // 可选：学校 ID（用于选择特定模板）
    "user_data": {...},             // 可选：额外用户信息
    "headless": false               // 可选：是否无头模式（默认 true）
}
```

**响应：**
```json
{
    "success": true,
    "status": "completed",
    "message": "Registration completed...",
    "missing_fields": [],
    "apply_record_id": 22
}
```

### GET /api/v2/register-status/{apply_record_id}

**响应：**
```json
{
    "apply_record_id": 22,
    "register_status": "success"
}
```

---

## 六、注意事项

1. **browser-use 版本**：必须使用 `0.1.48`，新版本（0.10.x, 0.11.x）存在 CDP 连接问题

2. **浏览器模式**：测试时建议使用 `headless: false`，方便观察自动化过程

3. **网络环境**：确保能访问目标学校网站和 OpenAI API

4. **邮箱模块**：接入时需要考虑：
   - 邮箱登录认证（IMAP/POP3 或 API）
   - 验证码邮件识别
   - 超时处理
   - 重试机制

5. **错误处理**：当前 Agent 失败会自动重试 3 次

---

## 七、相关文件

| 文件 | 说明 |
|------|------|
| `backend/services/register_service.py` | 注册服务核心逻辑 |
| `backend/api/routes.py` | API 路由定义 |
| `backend/dao/apply_record.py` | 数据库操作 |
| `main.py` | 服务入口 |

---

*文档更新日期：2024-12-10*

