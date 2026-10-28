"""
API 路由定义

职责：
- 接收 HTTP 请求
- 验证参数
- 调用服务层
- 返回响应

不应该包含：
- 业务逻辑
- 状态判断
- 数据库操作
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, EmailStr, HttpUrl, validator
from typing import Optional, Dict, List, Any

from backend.services import ApplicationService, FormFillService, RegisterService
from backend.exceptions import ValidationError


router = APIRouter(prefix="/api/v2", tags=["Application API v2"])


# ==================== 请求模型 ====================

class StartRequest(BaseModel):
    apply_record_id: int = Field(..., gt=0, description="申请记录 ID，必须大于 0")


class SubmitFieldsRequest(BaseModel):
    apply_record_id: int = Field(..., gt=0, description="申请记录 ID，必须大于 0")
    fields: Dict[str, str] = Field(..., description="字段数据，至少包含一个字段")

    @validator('fields')
    def validate_fields(cls, v):
        if not v or len(v) == 0:
            raise ValueError('fields 不能为空，至少包含一个字段')
        return v


class FillRequest(BaseModel):
    apply_record_id: int = Field(..., gt=0, description="申请记录 ID，必须大于 0")
    pages: Optional[List[int]] = Field(None, description="要填充的页码列表")
    headless: bool = Field(True, description="是否无头模式")

    @validator('pages')
    def validate_pages(cls, v):
        if v is not None:
            for page in v:
                if page < 1:
                    raise ValueError('页码必须大于 0')
        return v


class ReviewRequest(BaseModel):
    apply_record_id: int = Field(..., gt=0, description="申请记录 ID，必须大于 0")
    action: str = Field(..., description="操作类型")

    @validator('action')
    def validate_action(cls, v):
        allowed = ['confirm', 'retry']
        if v not in allowed:
            raise ValueError(f'action 必须是以下之一: {", ".join(allowed)}')
        return v


# 注册请求模型
class RegisterRequest(BaseModel):
    """注册请求"""
    apply_record_id: int = Field(..., gt=0, description="申请记录 ID，必须大于 0")
    email: EmailStr = Field(..., description="注册邮箱")
    password: str = Field(..., min_length=8, max_length=100, description="注册密码，至少8位")
    url: HttpUrl = Field(..., description="注册页面 URL")
    uni_id: Optional[str] = Field('', max_length=50, description="学校 ID")
    user_data: Optional[Dict[str, Any]] = Field(None, description="用户附加数据")
    headless: bool = Field(True, description="是否无头模式")

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('密码至少需要8个字符')
        return v


# 创建申请记录请求模型
class CreateApplyRecordRequest(BaseModel):
    """创建申请记录"""
    user_id: str = Field(..., min_length=1, max_length=100, description="用户 ID")
    email: EmailStr = Field(..., description="注册邮箱")
    password: str = Field(..., min_length=8, max_length=100, description="注册密码，至少8位")
    application_url: HttpUrl = Field(..., description="申请系统 URL")
    prog_id: Optional[str] = Field(None, max_length=100, description="项目 ID (UUID 格式)")
    group_id: Optional[str] = Field(None, max_length=100, description="分组 ID (UUID 格式)")

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('密码至少需要8个字符')
        return v


# ==================== API 端点 ====================

# ==================== 创建申请记录 ====================

@router.post("/apply-record")
async def create_apply_record(request: CreateApplyRecordRequest):
    """
    创建申请记录

    这是整个申请流程的入口点，创建后获得 apply_record_id

    请求体:
    - user_id: 用户 ID
    - email: 注册邮箱
    - password: 注册密码
    - application_url: 申请系统 URL
    - prog_id: 项目 ID (可选)
    - group_id: 分组 ID (可选)

    返回:
    - apply_record_id: 创建的申请记录 ID
    - status: 初始状态 (待注册)
    """
    from backend.db import get_db
    from backend.dao import ApplyRecordDao

    db = get_db()

    # 检查是否已存在相同邮箱的记录
    existing = ApplyRecordDao.get_by_email(db, request.email)
    if existing:
        # 如果已存在，返回已有记录
        return {
            "success": True,
            "apply_record_id": existing.get("id"),
            "status": existing.get("status", "待注册"),
            "message": "该邮箱已存在申请记录",
            "is_existing": True
        }

    # 创建新记录
    record = ApplyRecordDao.create(
        db=db,
        user_id=request.user_id,
        email=str(request.email),  # EmailStr 转 str
        password=request.password,
        application_url=str(request.application_url),  # HttpUrl 转 str
        prog_id=request.prog_id if request.prog_id else None,
        group_id=request.group_id if request.group_id else None,
    )

    if not record:
        raise HTTPException(status_code=500, detail="创建申请记录失败")

    return {
        "success": True,
        "apply_record_id": record.get("id"),
        "status": record.get("status", "待注册"),
        "message": "申请记录创建成功",
        "is_existing": False
    }


@router.get("/apply-record/{apply_record_id}")
async def get_apply_record(apply_record_id: int):
    """
    获取申请记录详情
    """
    from backend.db import get_db
    from backend.dao import ApplyRecordDao

    db = get_db()
    record = ApplyRecordDao.get_by_id(db, apply_record_id)

    if not record:
        raise HTTPException(status_code=404, detail="申请记录不存在")

    # 隐藏密码
    record_safe = {k: v for k, v in record.items() if k != 'password'}
    record_safe['has_password'] = bool(record.get('password'))

    return record_safe


@router.get("/apply-records/user/{user_id}")
async def get_user_apply_records(user_id: str):
    """
    获取用户的所有申请记录
    """
    from backend.db import get_db
    from backend.dao import ApplyRecordDao

    db = get_db()
    records = ApplyRecordDao.get_by_user_id(db, user_id)

    # 隐藏密码
    safe_records = []
    for r in records:
        record_safe = {k: v for k, v in r.items() if k != 'password'}
        record_safe['has_password'] = bool(r.get('password'))
        safe_records.append(record_safe)

    return {
        "records": safe_records,
        "count": len(safe_records)
    }


# ==================== 状态查询 ====================

@router.get("/status/{apply_record_id}")
async def get_status(apply_record_id: int):
    """
    获取申请状态

    返回当前状态、进度、下一步操作
    """
    service = ApplicationService()
    return service.get_status(apply_record_id)


@router.post("/start")
async def start_application(request: StartRequest):
    """
    启动申请流程

    状态: created -> analyzing
    """
    service = ApplicationService()
    result = service.start(request.apply_record_id)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.post("/analyze")
async def run_analysis(request: StartRequest):
    """
    执行分析阶段

    1. 爬取学校页面，提取字段
    2. 与用户信息匹配
    3. 生成缺失字段列表

    状态: analyzing -> need_input 或 ready

    算法调用:
    - PageCrawler: 页面爬取
    - FieldExtractor: 字段提取
    - FieldMatcher: 字段匹配
    """
    service = ApplicationService()
    result = await service.run_analysis(request.apply_record_id)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.get("/university-fields/{apply_record_id}")
async def get_university_fields(apply_record_id: int):
    """
    获取学校字段列表

    用于查看已爬取的学校表单字段
    """
    service = ApplicationService()
    fields = service.get_university_fields(apply_record_id)
    return {"fields": fields, "count": len(fields)}


@router.get("/missing-fields/{apply_record_id}")
async def get_missing_fields(apply_record_id: int):
    """
    获取缺失字段列表

    用于前端显示需要用户补充的字段
    """
    service = ApplicationService()
    fields = service.get_missing_fields(apply_record_id)
    return {"fields": fields, "count": len(fields)}


# 新增：插入缺失字段请求模型
class AddMissingFieldsRequest(BaseModel):
    apply_record_id: int
    fields: List[Dict[str, Any]]  # [{field_id, field_label, field_type, is_required, options}]


@router.post("/missing-fields")
async def add_missing_fields(request: AddMissingFieldsRequest):
    """
    手动插入缺失字段

    用途：
    1. 填充失败后发现的新缺失字段
    2. 手动添加需要用户补充的字段

    请求体:
    {
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
    }
    """
    from backend.db import get_db
    from backend.dao import MissingFieldsDao

    db = get_db()

    # 插入缺失字段
    inserted = MissingFieldsDao.add_batch(db, request.apply_record_id, request.fields)

    return {
        "success": True,
        "inserted": inserted,
        "message": f"已添加 {inserted} 个缺失字段"
    }


@router.post("/submit-fields")
async def submit_missing_fields(request: SubmitFieldsRequest):
    """
    提交缺失字段的值（方案B：更新 payload 表，删除 missing_fields）

    流程:
    1. 将用户提交的值插入 application_payload 表（source='user_supplement'）
    2. 从 missing_fields 表删除已补充的字段
    3. 如果全部补充完成，状态变为 ready

    状态: need_input -> ready (如果全部补充)
    """
    from backend.db import get_db
    from backend.dao import MissingFieldsDao, ApplicationPayloadDao, ApplicationProcessDao

    db = get_db()
    apply_record_id = request.apply_record_id

    # 获取提交前的 missing_fields 数量
    missing_before = MissingFieldsDao.get_by_apply_id(db, apply_record_id, only_unresolved=True)
    missing_before_count = len(missing_before)

    # 获取 missing_fields 的详细信息（用于获取 field_label, field_type 等）
    missing_fields_data = MissingFieldsDao.get_by_apply_id(db, apply_record_id, only_unresolved=False)
    missing_fields_map = {f['field_id']: f for f in missing_fields_data}

    # 1. 将用户提交的值插入 payload 表
    payload_count = 0
    deleted_missing_count = 0
    for field_id, value in request.fields.items():
        if value and str(value).strip():
            # 获取字段详细信息
            field_info = missing_fields_map.get(field_id, {})

            ApplicationPayloadDao.add_from_user_supplement(
                db=db,
                apply_record_id=apply_record_id,
                field_id=field_id,
                value=str(value),
                field_label=field_info.get('field_label', ''),
                field_type=field_info.get('field_type', 'text'),
                options=field_info.get('options')
            )
            payload_count += 1

            # 2. 从 missing_fields 删除该字段
            if MissingFieldsDao.delete_field(db, apply_record_id, field_id):
                deleted_missing_count += 1

    # 3. 检查是否还有未补充的缺失字段
    remaining = MissingFieldsDao.get_by_apply_id(db, apply_record_id, only_unresolved=True)

    # 4. 获取当前 payload 总数
    payload_stats = ApplicationPayloadDao.count(db, apply_record_id)

    status_changed = False
    if len(remaining) == 0:
        # 全部补充完成，状态变为 ready
        ApplicationProcessDao.update_status(db, apply_record_id, 'ready', '所有字段已补充完成，可以开始填充')
        new_status = 'ready'
        status_changed = True
    else:
        new_status = 'need_input'

    # 构建详细的返回信息
    message_parts = [
        f"Payload: 新增 {payload_count} 条 (总计 {payload_stats['total']} 条)",
        f"Missing: 删除 {deleted_missing_count} 条 (剩余 {len(remaining)} 条)",
    ]
    if status_changed:
        message_parts.append(f"状态: 已更新为 {new_status}")

    return {
        "success": True,
        "operations": {
            "payload_added": payload_count,
            "payload_total": payload_stats['total'],
            "missing_deleted": deleted_missing_count,
            "missing_before": missing_before_count,
            "missing_remaining": len(remaining),
            "status_changed": status_changed,
        },
        "updated_payload": payload_count,
        "remaining_missing": len(remaining),
        "status": new_status,
        "message": " | ".join(message_parts)
    }


# ==================== Payload 管理接口 ====================

@router.get("/payload/{apply_record_id}")
async def get_payload(apply_record_id: int):
    """
    获取完整 Payload（用于审核/预览）

    返回 application_payload 表中的所有数据
    """
    from backend.db import get_db
    from backend.dao import ApplicationPayloadDao

    db = get_db()
    fields = ApplicationPayloadDao.get_by_apply_id(db, apply_record_id)
    stats = ApplicationPayloadDao.count(db, apply_record_id)

    return {
        "apply_record_id": apply_record_id,
        "fields": fields,
        "stats": stats,
        "message": f"共 {stats['total']} 个字段，{stats['with_value']} 个有值"
    }


@router.get("/payload/{apply_record_id}/fill-format")
async def get_payload_fill_format(apply_record_id: int):
    """
    获取填充格式的 Payload

    返回格式: {field_id: {value, type, label, source}}
    """
    from backend.db import get_db
    from backend.dao import ApplicationPayloadDao

    db = get_db()
    payload = ApplicationPayloadDao.to_fill_payload(db, apply_record_id)

    return {
        "apply_record_id": apply_record_id,
        "payload": payload,
        "count": len(payload)
    }


class UpdatePayloadRequest(BaseModel):
    apply_record_id: int
    fields: Dict[str, str]  # {field_id: value}


@router.put("/payload")
async def update_payload(request: UpdatePayloadRequest):
    """
    批量更新 Payload 字段值

    用户审核后修改某些字段的值
    """
    from backend.db import get_db
    from backend.dao import ApplicationPayloadDao

    db = get_db()
    updated = ApplicationPayloadDao.update_batch(db, request.apply_record_id, request.fields)

    return {
        "success": True,
        "updated": updated,
        "message": f"已更新 {updated} 个字段"
    }


class AddPayloadFieldRequest(BaseModel):
    apply_record_id: int
    field_id: str
    value: str
    field_label: str = ''
    field_type: str = 'text'
    source: str = 'user_supplement'
    options: Optional[List[Dict[str, Any]]] = None


@router.post("/payload/field")
async def add_payload_field(request: AddPayloadFieldRequest):
    """
    添加单个 Payload 字段
    """
    from backend.db import get_db
    from backend.dao import ApplicationPayloadDao

    db = get_db()
    result = ApplicationPayloadDao.upsert(
        db=db,
        apply_record_id=request.apply_record_id,
        field_id=request.field_id,
        value=request.value,
        source=request.source,
        field_label=request.field_label,
        field_type=request.field_type,
        options=request.options
    )

    return {
        "success": True,
        "field": result
    }


@router.delete("/payload/{apply_record_id}/field/{field_id}")
async def delete_payload_field(apply_record_id: int, field_id: str):
    """
    删除单个 Payload 字段
    """
    from backend.db import get_db
    from backend.dao import ApplicationPayloadDao

    db = get_db()
    ApplicationPayloadDao.delete_field(db, apply_record_id, field_id)

    return {
        "success": True,
        "message": f"已删除字段 {field_id}"
    }


class InitPayloadRequest(BaseModel):
    apply_record_id: int
    from_user_info: bool = True  # 是否从 user_application_info 初始化
    from_llm_match: bool = False  # 是否从 LLM 匹配结果初始化（需要先执行 analyze）


@router.post("/payload/init")
async def init_payload(request: InitPayloadRequest):
    """
    初始化 Payload（已废弃，payload 应该在 analyze 阶段自动初始化）

    注意：直接从 user_info 初始化会导致 field_id 不匹配问题
    正确流程是通过 /analyze 接口，让 LLM 匹配用户信息到学校字段
    """
    from backend.db import get_db
    from backend.dao import ApplicationPayloadDao

    db = get_db()

    # 检查是否已有 payload 数据
    stats = ApplicationPayloadDao.count(db, request.apply_record_id)

    if stats['total'] > 0:
        return {
            "success": True,
            "added": 0,
            "stats": stats,
            "message": f"Payload 已存在 {stats['total']} 个字段，无需重新初始化。如需重置，请先删除后重新执行 /analyze"
        }

    return {
        "success": False,
        "error": "Payload 为空，请先执行 /analyze 接口进行字段分析和匹配",
        "hint": "正确流程: /start -> /analyze -> /submit-fields -> /fill"
    }


# ==================== 表单填充接口 ====================

@router.post("/fill")
async def fill_form(request: FillRequest):
    """
    执行表单填充（从 application_payload 表读取数据）

    状态: ready -> filling -> pending_review
    """
    app_service = ApplicationService()
    fill_service = FormFillService()

    # 先更新状态为 filling
    start_result = app_service.start_filling(request.apply_record_id)
    if not start_result.get("success"):
        raise HTTPException(status_code=400, detail=start_result.get("error"))

    # 执行填充
    fill_result = await fill_service.fill_form(
        request.apply_record_id,
        pages=request.pages,
        headless=request.headless
    )

    if not fill_result.get("success"):
        raise HTTPException(status_code=500, detail=fill_result.get("error"))

    # 更新状态
    app_service.complete_filling(
        request.apply_record_id,
        fill_result.get("filled", 0),
        fill_result.get("failed", 0)
    )

    return fill_result


@router.get("/fill-result/{apply_record_id}")
async def get_fill_result(apply_record_id: int):
    """
    获取填充结果

    返回成功/失败/无值字段列表
    """
    service = ApplicationService()
    result = service.get_fill_result(apply_record_id)

    return {
        "filled": len(result.get("fields_filled", [])),
        "failed": len(result.get("fields_failed", [])),
        "no_value": len(result.get("fields_no_value", [])),
        "details": result
    }


# ==================== 已填字段管理 ====================

@router.get("/filled-fields/{apply_record_id}")
async def get_filled_fields(apply_record_id: int):
    """
    获取已填充的字段（供用户审核修改）

    返回填充成功的字段列表，包含当前值
    """
    service = ApplicationService()
    result = service.get_fill_result(apply_record_id)

    fields_filled = result.get("fields_filled", [])

    return {
        "apply_record_id": apply_record_id,
        "fields": fields_filled,
        "count": len(fields_filled),
        "message": "这些字段已成功填充，您可以修改后重新提交"
    }


# 修改已填字段请求模型
class UpdateFilledFieldsRequest(BaseModel):
    apply_record_id: int
    fields: Dict[str, str]  # {field_id: new_value}


@router.put("/filled-fields")
async def update_filled_fields(request: UpdateFilledFieldsRequest):
    """
    修改已填充字段的值

    用户审核后修改某些字段的值，下次填充时使用新值

    请求体:
    {
        "apply_record_id": 22,
        "fields": {
            "form_xxx": "新值1",
            "form_yyy": "新值2"
        }
    }
    """
    from backend.db import get_db
    from backend.dao import MissingFieldsDao

    db = get_db()
    updated_count = 0

    # 将修改的字段更新到 missing_fields 表（作为用户补充值）
    for field_id, new_value in request.fields.items():
        try:
            MissingFieldsDao.update_value(db, request.apply_record_id, field_id, new_value)
            updated_count += 1
        except Exception:
            # 如果字段不存在于 missing_fields，则插入
            MissingFieldsDao.add_batch(db, request.apply_record_id, [{
                'field_id': field_id,
                'field_label': '',
                'field_type': 'text',
                'is_required': False,
                'resolved_value': new_value,
                'is_resolved': True
            }])
            updated_count += 1

    return {
        "success": True,
        "updated": updated_count,
        "message": f"已更新 {updated_count} 个字段"
    }


# ==================== 失败字段处理 ====================

@router.post("/failed-to-missing/{apply_record_id}")
async def convert_failed_to_missing(apply_record_id: int):
    """
    将填充失败的字段转为缺失字段

    用途：填充失败的字段需要用户重新提供值

    流程：
    1. 从 fill_result.fields_failed 获取失败字段
    2. 插入到 missing_fields 表
    3. 状态变为 need_input
    """
    from backend.db import get_db
    from backend.dao import MissingFieldsDao, ApplicationProcessDao

    db = get_db()
    service = ApplicationService()

    # 获取失败字段
    result = service.get_fill_result(apply_record_id)
    failed_fields = result.get("fields_failed", [])

    if not failed_fields:
        return {
            "success": True,
            "converted": 0,
            "message": "没有失败的字段需要转换"
        }

    # 转换为缺失字段格式
    # 注意：数据库 missing_fields 表没有 error_reason 字段
    missing_fields = []
    for f in failed_fields:
        missing_fields.append({
            'field_id': f.get('field_id'),
            'field_label': f.get('field_label', ''),
            'field_type': f.get('field_type', 'text'),
            'is_required': True,
            'options': f.get('options'),
        })

    # 插入到 missing_fields
    inserted = MissingFieldsDao.add_batch(db, apply_record_id, missing_fields)

    # 更新状态为 need_input
    ApplicationProcessDao.update_status(db, apply_record_id, 'need_input',
                                        f'{len(failed_fields)} 个字段填充失败，需要用户补充')

    return {
        "success": True,
        "converted": inserted,
        "failed_fields": [f.get('field_id') for f in failed_fields],
        "message": f"已将 {inserted} 个失败字段转为缺失字段，请用户补充"
    }


@router.get("/failed-fields/{apply_record_id}")
async def get_failed_fields(apply_record_id: int):
    """
    获取填充失败的字段

    返回填充失败的字段列表，包含错误原因
    """
    service = ApplicationService()
    result = service.get_fill_result(apply_record_id)

    fields_failed = result.get("fields_failed", [])

    return {
        "apply_record_id": apply_record_id,
        "fields": fields_failed,
        "count": len(fields_failed),
        "message": "这些字段填充失败，可以转为缺失字段让用户补充"
    }


@router.post("/review")
async def submit_review(request: ReviewRequest):
    """
    提交审核结果

    action = "confirm": pending_review -> completed
    action = "retry": failed -> ready
    """
    service = ApplicationService()

    if request.action == "confirm":
        result = service.confirm_review(request.apply_record_id)
    elif request.action == "retry":
        result = service.retry(request.apply_record_id)
    else:
        raise HTTPException(status_code=400, detail=f"未知操作: {request.action}")

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.post("/fill-failed")
async def fill_failed_fields(request: FillRequest):
    """
    重试填充失败的字段（已废弃，请用 /fill-targeted）
    """
    fill_service = FormFillService()
    result = await fill_service.fill_failed_fields(
        request.apply_record_id,
        headless=request.headless
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    return result


class FillTargetedRequest(BaseModel):
    apply_record_id: int
    field_ids: Optional[List[str]] = None  # 要重填的字段ID列表，None表示重填所有失败字段
    headless: bool = True


@router.post("/fill-targeted")
async def fill_targeted_fields(request: FillTargetedRequest):
    """
    定向填充指定字段

    用途：重填"有值但填写失败"的字段

    输入：
    {
        "apply_record_id": 22,
        "field_ids": ["form_xxx", "form_yyy"],  // 可选，不传则重填所有失败字段
        "headless": true
    }

    返回：
    {
        "success": true,
        "targeted": 12,           // 尝试重填的字段数
        "newly_filled": 8,        // 本次成功的
        "still_failed": 4,        // 仍然失败的
        "results": [...]          // 每个字段的详细结果
    }
    """
    fill_service = FormFillService()

    # 如果没有指定字段，获取所有失败字段
    field_ids = request.field_ids
    if not field_ids:
        app_service = ApplicationService()
        fill_result = app_service.get_fill_result(request.apply_record_id)
        failed_fields = fill_result.get("fields_failed", [])
        field_ids = [f.get("field_id") for f in failed_fields]

    if not field_ids:
        return {
            "success": True,
            "targeted": 0,
            "newly_filled": 0,
            "still_failed": 0,
            "message": "没有需要重填的字段"
        }

    result = await fill_service.fill_targeted_fields(
        request.apply_record_id,
        field_ids,
        headless=request.headless
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    return result


# ==================== 一键申请（完整流程） ====================

@router.post("/apply-full")
async def apply_full(request: FillRequest):
    """
    一键完成整个申请流程

    1. 启动 (created -> analyzing)
    2. 分析字段
    3. 等待用户补充（如果需要）
    4. 填充表单
    5. 返回审核状态
    """
    app_service = ApplicationService()
    fill_service = FormFillService()

    # 1. 获取当前状态
    status_info = app_service.get_status(request.apply_record_id)
    current_status = status_info.get("status")

    # 2. 根据状态执行对应操作
    if current_status == "created":
        # 启动并分析
        start_result = app_service.start(request.apply_record_id)
        if not start_result.get("success"):
            raise HTTPException(status_code=400, detail=start_result.get("error"))

        # 执行分析（爬取字段 + 匹配）
        analyze_result = await app_service.run_analysis(request.apply_record_id)
        return analyze_result

    elif current_status == "analyzing":
        # 继续分析
        analyze_result = await app_service.run_analysis(request.apply_record_id)
        return analyze_result

    elif current_status == "need_input":
        # 返回缺失字段
        missing = app_service.get_missing_fields(request.apply_record_id)
        return {
            "status": "need_input",
            "message": f"需要补充 {len(missing)} 个字段",
            "missing_fields": missing
        }

    elif current_status in ["ready", "ready_to_fill"]:
        # 执行填充
        app_service.start_filling(request.apply_record_id)

        result = await fill_service.fill_form(
            request.apply_record_id,
            pages=request.pages,
            headless=request.headless
        )

        app_service.complete_filling(
            request.apply_record_id,
            result.get("filled", 0),
            result.get("failed", 0)
        )

        return {
            "status": "pending_review",
            "message": "填充完成，请审核",
            "result": result
        }

    elif current_status == "pending_review":
        # 返回审核信息
        fill_result = app_service.get_fill_result(request.apply_record_id)
        return {
            "status": "pending_review",
            "message": "等待用户审核",
            "fill_result": fill_result
        }

    elif current_status == "completed":
        return {"status": "completed", "message": "申请已完成"}

    elif current_status == "failed":
        return {"status": "failed", "message": "填充失败，可以重试"}

    else:
        return {"status": current_status, "message": "请等待"}


# ==================== 注册 API ====================

@router.post("/register")
async def register_account(request: RegisterRequest):
    """
    注册账号

    使用浏览器自动化进行账号注册，并保存结果到数据库

    Args:
        apply_record_id: 申请记录 ID（必填）
        email: 注册邮箱
        password: 注册密码
        url: 注册页面 URL
        uni_id: 学校 ID（可选，用于选择注册模板）
        user_data: 用户数据（可选）
        headless: 是否无头模式

    Returns:
        {
            "success": bool,
            "status": "completed" | "failed",
            "message": str,
            "missing_fields": list,
            "apply_record_id": int
        }
    """
    register_service = RegisterService()

    result = await register_service.register(
        apply_record_id=request.apply_record_id,
        email=str(request.email),  # EmailStr 转 str
        password=request.password,
        url=str(request.url),  # HttpUrl 转 str
        uni_id=request.uni_id or '',
        user_data=request.user_data or {},
        headless=request.headless
    )

    # 无论成功失败都返回完整结果，让调用方决定如何处理
    return result


@router.get("/register-status/{apply_record_id}")
async def get_register_status(apply_record_id: int):
    """
    获取注册状态
    """
    from backend.db import get_db
    from backend.dao import ApplyRecordDao

    db = get_db()
    status = ApplyRecordDao.get_register_status(db, apply_record_id)

    return {
        "apply_record_id": apply_record_id,
        "register_status": status or "unknown"
    }

