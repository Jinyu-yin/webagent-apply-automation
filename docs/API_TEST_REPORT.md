# 申请系统 API 文档

> 更新日期: 2025-12-10  
> API 版本: v2  
> 基础 URL: http://127.0.0.1:8080/api/v2

---

## 目录

- [核心流程](#核心流程)
  - [0. 创建申请记录](#0-创建申请记录)
  - [1. 注册账号](#1-注册账号)
  - [2. 启动申请流程](#2-启动申请流程)
  - [3. 执行分析](#3-执行分析)
  - [4. 获取缺失字段](#4-获取缺失字段)
  - [5. 提交缺失字段](#5-提交缺失字段)
  - [6. 执行表单填充](#6-执行表单填充)
  - [7. 审核确认/重试](#7-审核确认重试)
- [Payload 管理](#payload-管理)
- [失败字段处理](#失败字段处理)
- [辅助接口](#辅助接口)
- [一键申请](#一键申请)
- [完整流程示例](#完整流程示例)

---

## 核心流程

### 0. 创建申请记录

#### POST /apply-record

**功能**: 创建新的申请记录，这是整个流程的入口点

**请求**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/apply-record \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user_berkeley",
    "email": "3769693464@qq.com",
    "password": "20020110.Lq1",
    "application_url": "https://gradapp.berkeley.edu/account/login"
  }'
```

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | ✅ | 用户唯一标识 |
| email | string | ✅ | 注册邮箱 |
| password | string | ✅ | 注册密码 |
| application_url | string | ✅ | 申请系统 URL |
| prog_id | string | ❌ | 项目 ID |
| group_id | string | ❌ | 分组 ID |

**响应 (新建)**:
```json
{
    "success": true,
    "apply_record_id": 42,
    "status": "待注册",
    "message": "申请记录创建成功",
    "is_existing": false
}
```

**响应 (已存在)**:
```json
{
    "success": true,
    "apply_record_id": 22,
    "status": "未开始",
    "message": "该邮箱已存在申请记录",
    "is_existing": true
}
```

#### GET /apply-records/user/{user_id}

**功能**: 获取用户的所有申请记录

**请求**:
```bash
curl http://127.0.0.1:8080/api/v2/apply-records/user/test_user_berkeley
```

**响应**:
```json
{
    "records": [
        {
            "id": 22,
            "user_id": "test_user_berkeley",
            "email": "3769693464@qq.com",
            "application_url": "https://gradapp.berkeley.edu/account/login",
            "status": "未开始",
            "register_status": "success",
            "has_password": true
        }
    ],
    "count": 1
}
```

---

### 1. 注册账号

#### POST /register

**功能**: 使用浏览器自动化进行账号注册

**请求**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/register \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "email": "3769693464@qq.com",
    "password": "20020110.Lq1",
    "url": "https://gradapp.berkeley.edu/account/login",
    "headless": false
  }'
```

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| apply_record_id | int | ✅ | 申请记录 ID |
| email | string | ✅ | 注册邮箱 |
| password | string | ✅ | 注册密码 |
| url | string | ✅ | 注册页面 URL |
| uni_id | string | ❌ | 学校 ID（用于选择模板） |
| user_data | object | ❌ | 用户额外数据 |
| headless | bool | ❌ | 是否无头模式（默认 true） |

**响应 (成功)**:
```json
{
    "success": true,
    "status": "completed",
    "message": "Registration completed successfully.",
    "missing_fields": [],
    "apply_record_id": 22
}
```

---

### 2. 启动申请流程

#### POST /start

**功能**: 启动申请流程，状态从 `created` 变为 `analyzing`

**请求**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/start \
  -H "Content-Type: application/json" \
  -d '{"apply_record_id": 22}'
```

**响应**:
```json
{
    "success": true,
    "status": "analyzing",
    "uni_id": "berkeley",
    "message": "已启动，进入分析阶段"
}
```

---

### 3. 执行分析

#### POST /analyze

**功能**: 爬取学校页面，提取字段，与用户信息匹配

**请求**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/analyze \
  -H "Content-Type: application/json" \
  -d '{"apply_record_id": 22}'
```

**响应 (有缺失字段)**:
```json
{
    "success": true,
    "status": "need_input",
    "fields_count": 129,
    "missing_count": 21,
    "message": "发现 21 个缺失字段，需要用户补充"
}
```

---

### 4. 获取缺失字段

#### GET /missing-fields/{apply_record_id}

**功能**: 获取需要用户补充的缺失字段列表

**请求**:
```bash
curl http://127.0.0.1:8080/api/v2/missing-fields/22
```

**响应**:
```json
{
    "fields": [
        {
            "field_id": "form_548998b9-d951-4758-b44a-6795fbea3edc_m",
            "field_label": "Month",
            "field_type": "select-one",
            "is_required": true,
            "options": ["January", "February", "March"]
        }
    ],
    "count": 21
}
```

#### POST /missing-fields

**功能**: 手动插入缺失字段

**请求**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/missing-fields \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "fields": [
        {
            "field_id": "form_xxx",
            "field_label": "Your Field",
            "field_type": "text",
            "is_required": true,
            "options": null
        }
    ]
  }'
```

**响应**:
```json
{
    "success": true,
    "inserted": 1,
    "message": "已添加 1 个缺失字段"
}
```

---

### 5. 提交缺失字段

#### POST /submit-fields

**功能**: 用户提交缺失字段的值

**请求**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/submit-fields \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "fields": {
      "form_548998b9-d951-4758-b44a-6795fbea3edc_m": "January",
      "form_8e68f10c-4407-4b1e-abf0-da56e6ed81df": "Xiao"
    }
  }'
```

**响应**:
```json
{
    "success": true,
    "updated_payload": 2,
    "remaining_missing": 19,
    "status": "need_input",
    "message": "已更新 2 个字段到 payload，还有 19 个待补充"
}
```

---

### 6. 执行表单填充

#### POST /fill

**功能**: 使用浏览器自动化执行表单填充

**请求**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/fill \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "pages": [1, 2, 3],
    "headless": true
  }'
```

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| apply_record_id | int | ✅ | 申请记录 ID |
| pages | array | ❌ | 指定填充的页码（默认全部） |
| headless | bool | ❌ | 是否无头模式（默认 true） |

**响应**:
```json
{
    "success": true,
    "filled": 44,
    "failed": 10,
    "no_value": 18,
    "message": "填充完成: 成功44, 失败10, 无值18"
}
```

#### GET /fill-result/{apply_record_id}

**功能**: 获取填充结果详情

**请求**:
```bash
curl http://127.0.0.1:8080/api/v2/fill-result/22
```

**响应**:
```json
{
    "filled": 44,
    "failed": 10,
    "no_value": 18,
    "details": {
        "fields_filled": [...],
        "fields_failed": [...],
        "fields_no_value": [...]
    }
}
```

---

### 7. 审核确认/重试

#### POST /review

**功能**: 用户审核填充结果，确认完成或请求重试

**请求 (确认)**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/review \
  -H "Content-Type: application/json" \
  -d '{"apply_record_id": 22, "action": "confirm"}'
```

**请求 (重试)**:
```bash
curl -X POST http://127.0.0.1:8080/api/v2/review \
  -H "Content-Type: application/json" \
  -d '{"apply_record_id": 22, "action": "retry"}'
```

**响应**:
```json
{
    "success": true,
    "status": "completed",
    "message": "申请已完成"
}
```

---

## Payload 管理

Payload 是表单填充的数据源，存储字段ID与值的映射。

### GET /payload/{apply_record_id}

**功能**: 获取完整 Payload（用于审核/预览）

```bash
curl http://127.0.0.1:8080/api/v2/payload/22
```

**响应**:
```json
{
    "apply_record_id": 22,
    "fields": [...],
    "stats": {"total": 129, "with_value": 108},
    "message": "共 129 个字段，108 个有值"
}
```

### GET /payload/{apply_record_id}/fill-format

**功能**: 获取填充格式的 Payload

```bash
curl http://127.0.0.1:8080/api/v2/payload/22/fill-format
```

### PUT /payload

**功能**: 批量更新 Payload 字段值

```bash
curl -X PUT http://127.0.0.1:8080/api/v2/payload \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "fields": {"form_xxx": "新值1", "form_yyy": "新值2"}
  }'
```

### POST /payload/field

**功能**: 添加单个 Payload 字段

```bash
curl -X POST http://127.0.0.1:8080/api/v2/payload/field \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "field_id": "form_xxx",
    "value": "测试值",
    "field_label": "Test Field",
    "field_type": "text",
    "source": "user_supplement"
  }'
```

### DELETE /payload/{apply_record_id}/field/{field_id}

**功能**: 删除单个 Payload 字段

```bash
curl -X DELETE http://127.0.0.1:8080/api/v2/payload/22/field/form_xxx
```

---

## 失败字段处理

### GET /failed-fields/{apply_record_id}

**功能**: 获取填充失败的字段

```bash
curl http://127.0.0.1:8080/api/v2/failed-fields/22
```

**响应**:
```json
{
    "apply_record_id": 22,
    "fields": [
        {
            "field_id": "form_dc8a607a-ebd7-4b64-bf91-ecb0532adeca",
            "field_label": "Email Address",
            "error": "ElementHandle.fill: Timeout 30000ms exceeded"
        }
    ],
    "count": 10
}
```

### POST /failed-to-missing/{apply_record_id}

**功能**: 将填充失败的字段转为缺失字段，让用户重新提供值

```bash
curl -X POST http://127.0.0.1:8080/api/v2/failed-to-missing/22
```

**响应**:
```json
{
    "success": true,
    "converted": 10,
    "failed_fields": ["form_xxx", "form_yyy"],
    "message": "已将 10 个失败字段转为缺失字段，请用户补充"
}
```

### POST /fill-targeted

**功能**: 定向填充指定字段（重填失败字段）

```bash
curl -X POST http://127.0.0.1:8080/api/v2/fill-targeted \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "field_ids": ["form_xxx", "form_yyy"],
    "headless": true
  }'
```

**响应**:
```json
{
    "success": true,
    "targeted": 12,
    "newly_filled": 8,
    "still_failed": 4,
    "results": [...]
}
```

### GET /filled-fields/{apply_record_id}

**功能**: 获取已填充的字段（供用户审核修改）

```bash
curl http://127.0.0.1:8080/api/v2/filled-fields/22
```

### PUT /filled-fields

**功能**: 修改已填充字段的值

```bash
curl -X PUT http://127.0.0.1:8080/api/v2/filled-fields \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "fields": {"form_xxx": "新值1", "form_yyy": "新值2"}
  }'
```

---

## 辅助接口

### GET /status/{apply_record_id}

**功能**: 查询当前申请状态

```bash
curl http://127.0.0.1:8080/api/v2/status/22
```

**响应**:
```json
{
    "status": "ready",
    "message": "准备填写",
    "progress": {"current_page": 3, "filled": 17, "total": 29},
    "next_action": "wait"
}
```

**状态值说明**:
| status | 说明 | next_action |
|--------|------|-------------|
| created | 刚创建 | start |
| analyzing | 分析中 | wait |
| need_input | 需要用户输入 | provide_input |
| ready | 准备填写 | wait |
| filling | 填写中 | wait |
| pending | 等待审核 | review |
| completed | 已完成 | null |
| failed | 失败 | retry |

### GET /apply-record/{apply_record_id}

**功能**: 获取申请记录详情

```bash
curl http://127.0.0.1:8080/api/v2/apply-record/22
```

### GET /university-fields/{apply_record_id}

**功能**: 获取学校表单字段列表

```bash
curl http://127.0.0.1:8080/api/v2/university-fields/22
```

### GET /register-status/{apply_record_id}

**功能**: 获取注册状态

```bash
curl http://127.0.0.1:8080/api/v2/register-status/22
```

---

## 一键申请

### POST /apply-full

**功能**: 一键完成整个申请流程

根据当前状态自动执行：
1. `created` → 启动并分析
2. `analyzing` → 继续分析
3. `need_input` → 返回缺失字段
4. `ready` → 执行填充
5. `pending_review` → 返回审核信息

```bash
curl -X POST http://127.0.0.1:8080/api/v2/apply-full \
  -H "Content-Type: application/json" \
  -d '{
    "apply_record_id": 22,
    "headless": true
  }'
```

---

## 完整流程示例

```bash
# 1. 创建申请记录
RECORD=$(curl -s -X POST http://127.0.0.1:8080/api/v2/apply-record \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user001", "email": "test@example.com", "password": "Pass123", "application_url": "https://example.edu/apply"}')
RECORD_ID=$(echo $RECORD | jq -r '.apply_record_id')
echo "Created record: $RECORD_ID"

# 2. 注册账号（如果需要）
curl -X POST http://127.0.0.1:8080/api/v2/register \
  -H "Content-Type: application/json" \
  -d "{\"apply_record_id\": $RECORD_ID, \"email\": \"test@example.com\", \"password\": \"Pass123\", \"url\": \"https://example.edu/register\"}"

# 3. 启动流程
curl -X POST http://127.0.0.1:8080/api/v2/start \
  -H "Content-Type: application/json" \
  -d "{\"apply_record_id\": $RECORD_ID}"

# 4. 执行分析
curl -X POST http://127.0.0.1:8080/api/v2/analyze \
  -H "Content-Type: application/json" \
  -d "{\"apply_record_id\": $RECORD_ID}"

# 5. 查看缺失字段
curl http://127.0.0.1:8080/api/v2/missing-fields/$RECORD_ID

# 6. 提交缺失字段
curl -X POST http://127.0.0.1:8080/api/v2/submit-fields \
  -H "Content-Type: application/json" \
  -d "{\"apply_record_id\": $RECORD_ID, \"fields\": {\"field_xxx\": \"value1\"}}"

# 7. 执行填充
curl -X POST http://127.0.0.1:8080/api/v2/fill \
  -H "Content-Type: application/json" \
  -d "{\"apply_record_id\": $RECORD_ID, \"headless\": true}"

# 8. 查看结果
curl http://127.0.0.1:8080/api/v2/fill-result/$RECORD_ID

# 9. 处理失败字段（如果有）
curl http://127.0.0.1:8080/api/v2/failed-fields/$RECORD_ID

# 10. 确认审核
curl -X POST http://127.0.0.1:8080/api/v2/review \
  -H "Content-Type: application/json" \
  -d "{\"apply_record_id\": $RECORD_ID, \"action\": \"confirm\"}"
```

---

*文档更新日期: 2025-12-10*
