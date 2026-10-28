# WebAgent - 留学申请自动化服务

基于 LLM 和浏览器自动化的留学申请表单填充系统，支持自动注册、字段分析、智能匹配和表单填充。

> **仓库说明**
> 本仓库为源码发布版本，已剔除以下内容：
> - `.env`（真实密钥）、`payloads.ndjson`（含真实账号口令）、运行日志与虚拟环境；
> - `llm_form_automation/data/crawled_pages/`（爬取页面快照，含院校表单截图）；
> - `.github/workflows/`（上游 browser-use 的 CI 配置，与本项目业务无关）。
>
> 首次使用请从 `.env.example` 复制出 `.env` 并填入自己的配置。

---

## 系统架构

```
                    ┌──────────────────────────────────────┐
   HTTP 请求  ───▶  │  FastAPI  (main.py / api/routes.py)   │
                    └───────────────┬──────────────────────┘
                                    │
                    ┌───────────────▼──────────────────────┐
                    │  Services 层                          │
                    │  register / application / form_fill   │
                    └───────────────┬──────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐         ┌──────────────────┐        ┌────────────────┐
│  DAO 层        │         │ llm_form_        │        │ Supabase       │
│  apply_record │         │ automation       │        │ (PostgreSQL)   │
│  process      │         │  ├ core          │        │ 申请记录/字段   │
│  payload      │         │  ├ form_filler   │        └────────────────┘
│  missing      │         │  └ services      │
└───────────────┘         └────────┬─────────┘
                                   │ Playwright / browser-use
                                   ▼
                          ┌──────────────────┐
                          │  院校申请系统     │
                          └──────────────────┘
```

核心是一个**状态机**驱动的流程：先爬取表单页面提取字段，再由 LLM 把申请人信息映射到字段上，缺什么就回问用户，补齐后执行浏览器填充，最后人工审核。

## 功能特性

- ✅ **自动化账号注册** - 使用 browser-use 自动完成学校申请系统注册
- ✅ **智能字段分析** - 爬取学校表单页面，提取所有字段信息
- ✅ **LLM 字段匹配** - 使用 GPT-4 将用户信息智能匹配到表单字段
- ✅ **自动表单填充** - 基于 Playwright 的浏览器自动化填充
- ✅ **缺失字段管理** - 识别并提示用户补充缺失信息
- ✅ **失败重试机制** - 支持定向重填失败字段
- ✅ **RESTful API** - 完整的 v2 API 接口
- ✅ **Supabase 数据库** - 持久化存储申请记录和字段数据

## 项目结构

```
WebAgent/
├── main.py                 # FastAPI 主入口
├── backend/
│   ├── api/routes.py       # API 路由定义 (v2)
│   ├── services/           # 业务逻辑层
│   │   ├── application_service.py   # 申请流程服务
│   │   ├── form_fill_service.py     # 表单填充服务
│   │   └── register_service.py      # 注册服务
│   ├── dao/                # 数据访问层
│   │   ├── apply_record.py          # 申请记录
│   │   ├── application_process.py   # 申请流程状态
│   │   ├── application_payload.py   # 填充数据
│   │   ├── missing_fields.py        # 缺失字段
│   │   └── university_fields.py     # 学校字段
│   ├── db/                 # 数据库连接
│   ├── config.py           # 统一配置管理
│   ├── logger.py           # 统一日志系统
│   └── exceptions.py       # 统一异常处理
├── llm_form_automation/    # LLM 表单自动化核心模块
│   ├── core/               # 核心逻辑
│   ├── form_filler/        # 表单填充器
│   ├── services/           # 服务模块
│   └── scripts/            # 脚本工具
├── docs/                   # 文档
│   ├── API_TEST_REPORT.md  # API 详细文档
│   └── REGISTER_SERVICE_GUIDE.md
└── logs/                   # 日志目录
```

## 快速开始

### 1. 环境准备

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium --with-deps
```

### 2. 配置环境变量

创建 `.env` 文件：

```bash
# 数据库配置 (Supabase)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# LLM 配置
OPENAI_API_KEY=your-openai-api-key
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选，使用代理时配置

# 服务配置 (可选)
HOST=0.0.0.0
PORT=8080
LOG_LEVEL=INFO
DEBUG=false
CORS_ORIGINS=*
```

### 3. 启动服务

```bash
# 直接运行
python main.py

# 或使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

服务启动后访问：
- API 文档: http://localhost:8080/docs
- 健康检查: http://localhost:8080/health

## API 概览

**基础 URL**: `http://localhost:8080/api/v2`

### 核心接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/apply-record` | 创建申请记录 |
| POST | `/register` | 自动注册账号 |
| POST | `/start` | 启动申请流程 |
| POST | `/analyze` | 执行字段分析 |
| GET | `/missing-fields/{id}` | 获取缺失字段 |
| POST | `/submit-fields` | 提交缺失字段 |
| POST | `/fill` | 执行表单填充 |
| POST | `/review` | 审核确认/重试 |
| GET | `/status/{id}` | 查询申请状态 |

### 完整流程示例

```bash
# 1. 创建申请记录
curl -X POST http://localhost:8080/api/v2/apply-record \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user001",
    "email": "test@example.com",
    "password": "SecurePass123",
    "application_url": "https://gradapp.berkeley.edu/account/login"
  }'

# 2. 注册账号
curl -X POST http://localhost:8080/api/v2/register \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 1,
    "email": "test@example.com",
    "password": "SecurePass123",
    "url": "https://gradapp.berkeley.edu/account/login",
    "headless": false
  }'

# 3. 启动并分析
curl -X POST http://localhost:8080/api/v2/start \
  -H "Content-Type: application/json" \
  -d '{"apply_record_id": 1}'

curl -X POST http://localhost:8080/api/v2/analyze \
  -H "Content-Type: application/json" \
  -d '{"apply_record_id": 1}'

# 4. 查看缺失字段
curl http://localhost:8080/api/v2/missing-fields/1

# 5. 提交缺失字段
curl -X POST http://localhost:8080/api/v2/submit-fields \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 1,
    "fields": {"field_xxx": "value1", "field_yyy": "value2"}
  }'

# 6. 执行填充
curl -X POST http://localhost:8080/api/v2/fill \
  -H "Content-Type: application/json" \
  -d '{"apply_record_id": 1, "headless": true}'

# 7. 查看结果并确认
curl http://localhost:8080/api/v2/fill-result/1

curl -X POST http://localhost:8080/api/v2/review \
  -H "Content-Type: application/json" \
  -d '{"apply_record_id": 1, "action": "confirm"}'
```

## 配置说明

应用使用 `backend/config.py` 统一管理配置，支持从环境变量和 `.env` 文件加载。

### 主要配置项

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `SUPABASE_URL` | Supabase 数据库 URL | 必填 |
| `SUPABASE_KEY` | Supabase API Key | 必填 |
| `OPENAI_API_KEY` | OpenAI API Key | 必填 |
| `OPENAI_BASE_URL` | OpenAI API Base URL | - |
| `HOST` | 服务监听地址 | 0.0.0.0 |
| `PORT` | 服务监听端口 | 8080 |
| `LOG_LEVEL` | 日志级别 | INFO |
| `DEBUG` | 调试模式 | false |
| `CORS_ORIGINS` | CORS 允许来源 | * |
| `MAX_FORM_PAGES` | 表单最大页数 | 15 |
| `BROWSER_HEADLESS` | 浏览器无头模式 | true |

## 申请状态流转

```
created → analyzing → need_input → ready → filling → pending_review → completed
                         ↓                    ↓
                      (用户补充)            (失败) → failed → retry → ready
```

| 状态 | 说明 | 下一步操作 |
|------|------|-----------|
| `created` | 刚创建 | 调用 `/start` |
| `analyzing` | 分析中 | 等待 |
| `need_input` | 需要用户输入 | 调用 `/submit-fields` |
| `ready` | 准备填写 | 调用 `/fill` |
| `filling` | 填写中 | 等待 |
| `pending_review` | 等待审核 | 调用 `/review` |
| `completed` | 已完成 | - |
| `failed` | 失败 | 调用 `/review` (retry) |

## 错误处理

服务使用统一的异常处理机制：

```json
{
  "error": true,
  "code": "VALIDATION_ERROR",
  "message": "请求参数验证失败",
  "details": {"field": "email", "reason": "格式不正确"}
}
```

### 错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| `VALIDATION_ERROR` | 400 | 参数验证失败 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `DATABASE_ERROR` | 500 | 数据库错误 |
| `LLM_ERROR` | 500 | LLM 调用失败 |
| `BROWSER_ERROR` | 500 | 浏览器自动化错误 |

## 详细文档

- [API 完整文档](docs/API_TEST_REPORT.md) - 所有接口的详细说明和示例
- [注册服务指南](docs/REGISTER_SERVICE_GUIDE.md) - 注册功能的使用说明

## 故障排除

### 常见问题

1. **端口被占用**
   ```bash
   lsof -i :8080
   kill -9 <PID>
   ```

2. **浏览器启动失败**
   ```bash
   playwright install chromium --with-deps
   ```

3. **数据库连接失败**
   - 检查 `SUPABASE_URL` 和 `SUPABASE_KEY` 是否正确
   - 确认网络可以访问 Supabase

4. **LLM 调用失败**
   - 检查 `OPENAI_API_KEY` 是否有效
   - 如使用代理，确认 `OPENAI_BASE_URL` 配置正确

### 查看日志

```bash
# 查看服务日志
tail -f logs/main_service.log

# 查看 API 日志
tail -f logs/api_webagent.log
```

## 技术栈

- **后端框架**: FastAPI
- **浏览器自动化**: Playwright, browser-use
- **LLM**: OpenAI GPT-4
- **数据库**: Supabase (PostgreSQL)
- **配置管理**: pydantic-settings
- **日志**: Python logging + colorlog

## License

MIT
