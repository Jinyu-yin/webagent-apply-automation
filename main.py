"""
WebAgent 主入口

职责：
1. 创建 FastAPI 应用
2. 注册 API 路由
3. 配置中间件和日志
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 加载环境变量
load_dotenv()

# 统一配置和日志
from backend.config import settings, get_settings
from backend.logger import setup_logging, get_logger
from backend.exceptions import WebAgentException, handle_exception

# 初始化日志系统
setup_logging(level=settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时验证配置
    try:
        settings.validate_required()
        logger.info("配置验证通过")
    except ValueError as e:
        logger.error(f"配置验证失败: {e}")
        raise

    logger.info(f"WebAgent 服务启动中... (版本: {app.version})")
    logger.info(f"调试模式: {settings.debug}")
    logger.info(f"CORS 来源: {settings.cors_origins}")
    yield
    logger.info("WebAgent 服务关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="WebAgent API",
    description="留学申请自动化服务",
    version="2.0.0",
    lifespan=lifespan
)

# 配置 CORS（从配置读取）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 统一异常处理
@app.exception_handler(WebAgentException)
async def webagent_exception_handler(request: Request, exc: WebAgentException):
    """统一处理 WebAgent 自定义异常"""
    return JSONResponse(
        status_code=400,
        content=exc.to_dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """处理其他未捕获的异常"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    error_response = handle_exception(exc)
    status_code = 500 if not settings.debug else 500
    return JSONResponse(
        status_code=status_code,
        content=error_response
    )

# 注册 API 路由 (v2)
# 注意：routes.py 中已定义 prefix="/api/v2"，这里不再重复
from backend.api.routes import router as api_v2_router
app.include_router(api_v2_router)


# ==================== 健康检查 ====================

@app.get("/health")
async def health_check():
    """
    健康检查

    返回服务状态和关键组件健康状态
    """
    from backend.db import get_db
    from datetime import datetime

    health_status = {
        "status": "healthy",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "checks": {}
    }

    # 检查数据库连接
    try:
        db = get_db()
        # 简单查询测试连接
        db.table("apply_record").select("id").limit(1).execute()
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["checks"]["database"] = f"error: {str(e)[:50]}"
        health_status["status"] = "degraded"

    # 检查 LLM 配置
    if settings.openai_api_key:
        health_status["checks"]["llm_config"] = "ok"
    else:
        health_status["checks"]["llm_config"] = "warning: no API key"

    return health_status


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "WebAgent",
        "version": "2.0.0",
        "docs": "/docs",
        "api_prefix": "/api/v2"
    }


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn

    logger.info(f"启动服务: http://{settings.host}:{settings.port}")
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower()
    )
