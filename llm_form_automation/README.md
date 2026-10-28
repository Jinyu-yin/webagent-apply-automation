# LLM 表单自动化模块

智能表单分析、字段匹配和自动填充的核心模块。

## 模块结构

```
llm_form_automation/
├── core/                       # 核心逻辑
│   ├── application_api.py      # 申请流程 API 封装
│   ├── application_pipeline.py # 申请流程管道
│   ├── application_state_machine.py  # 状态机管理
│   ├── field_extractor.py      # 字段提取器
│   ├── field_matcher.py        # 字段匹配器
│   ├── filling_executor.py     # 填充执行器
│   └── response_status.py      # 响应状态定义
│
├── form_filler/                # 表单填充模块
│   ├── form_filler.py          # 核心填写逻辑 (LLMFormFiller)
│   ├── payload_manager.py      # Payload 数据管理
│   ├── element_finder.py       # LLM 动态元素查找
│   ├── field_handlers.py       # 特殊字段处理
│   ├── validators.py           # 验证和隐私过滤
│   ├── intervention.py         # 人工干预和提交检测
│   ├── login_handler.py        # 登录处理
│   ├── site_configs.py         # 站点特定配置
│   ├── browser_use_integration.py  # Browser-Use 整合
│   └── cli.py                  # 命令行接口
│
├── services/                   # 服务层
│   ├── smart_field_matcher.py  # 智能字段匹配
│   ├── smart_field_matcher_universal.py  # 通用字段匹配
│   └── error_handler.py        # 错误处理
│
├── scripts/                    # 脚本工具
│   ├── 01_crawl_pages.py       # 页面爬取和字段提取
│   └── 03_evaluate_agent.py    # 评价 Agent
│
└── data/                       # 数据目录
    └── crawled_pages/          # 爬取的页面数据
        ├── screenshots/        # 页面截图
        ├── html/               # HTML 文件
        └── page_index.json     # 页面索引
```

## 核心组件

### 1. Core 模块

- **ApplicationStateMachine**: 申请流程状态机，管理状态转换
- **ApplicationAPI**: 对外 API 封装，处理申请请求
- **ApplicationPipeline**: 完整的申请流程管道
- **FieldExtractor**: 从 HTML 提取表单字段
- **FieldMatcher**: 将用户数据匹配到表单字段
- **FillingExecutor**: 执行表单填充操作

### 2. Form Filler 模块

- **LLMFormFiller**: 核心填写逻辑，支持多种字段类型
- **PayloadManager**: 管理填充数据
- **ElementFinder**: 使用 LLM 动态查找页面元素
- **LoginHandler**: 处理登录流程
- **SiteConfig**: 站点特定配置（如 Berkeley、MIT）

### 3. Services 模块

- **SmartFieldMatcher**: 智能字段匹配，支持 LLM 辅助
- **ErrorHandler**: 统一错误处理和日志

## 使用方式

### 作为模块导入

```python
from llm_form_automation.core import (
    ApplicationPipeline,
    FillingExecutor,
    FieldExtractor,
    FieldMatcher
)

from llm_form_automation.form_filler import (
    LLMFormFiller,
    PayloadManager,
    LoginHandler
)

from llm_form_automation.services import (
    SmartFieldMatcher,
    ErrorClassifier
)
```

### 运行页面爬取

```bash
python llm_form_automation/scripts/01_crawl_pages.py \
  --email your@email.com \
  --password yourpassword \
  --url "https://gradapp.berkeley.edu/account/login" \
  --uni-id berkeley \
  --save-to-db
```

### 状态流转

```
analyzing → need_input → ready_to_fill → filling → fill_completed
                ↓                           ↓
           (用户补充)                    (失败) → need_iteration → iterating
                                                        ↓
                                                  pending_review → completed
```

## 配置

环境变量：

```bash
# LLM 配置
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选

# 或使用 OpenRouter
OPENROUTER_API_KEY=your-openrouter-key
LLM_MODEL=anthropic/claude-3.5-sonnet
VLM_MODEL=anthropic/claude-3.5-sonnet
```

## 与 Backend 的关系

此模块被 `backend/services/` 调用：

- `backend/services/application_service.py` → 使用 `core/` 模块
- `backend/services/form_fill_service.py` → 使用 `form_filler/` 模块
