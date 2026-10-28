"""
统一配置管理

@description:
    使用 Pydantic Settings 管理所有配置
    支持从环境变量和 .env 文件加载配置

@usage:
    from backend.config import settings

    db_url = settings.supabase_url
    api_key = settings.openai_api_key
"""

from typing import Optional
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    应用配置

    所有配置项都可以通过环境变量覆盖
    环境变量名为大写形式，如 SUPABASE_URL
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # ==================== 数据库配置 ====================

    supabase_url: str = Field(
        default="",
        description="Supabase URL"
    )
    supabase_key: str = Field(
        default="",
        description="Supabase API Key"
    )

    # ==================== OpenAI 配置 ====================

    openai_api_key: str = Field(
        default="",
        description="OpenAI API Key"
    )
    openai_base_url: Optional[str] = Field(
        default=None,
        description="OpenAI API Base URL (可选，用于代理)"
    )
    openai_model: str = Field(
        default="gpt-4o",
        description="默认使用的 OpenAI 模型"
    )

    # ==================== 应用配置 ====================

    app_name: str = Field(
        default="WebAgent",
        description="应用名称"
    )
    debug: bool = Field(
        default=False,
        description="调试模式"
    )
    host: str = Field(
        default="0.0.0.0",
        description="服务器主机"
    )
    port: int = Field(
        default=8080,
        description="服务器端口"
    )

    # ==================== CORS 配置 ====================

    cors_origins: str = Field(
        default="*",
        description="CORS 允许的来源，逗号分隔，如: https://example.com,https://app.example.com"
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="CORS 是否允许凭证"
    )

    # ==================== 日志配置 ====================

    log_level: str = Field(
        default="INFO",
        description="日志级别"
    )
    log_to_file: bool = Field(
        default=False,
        description="是否写入日志文件"
    )
    log_dir: str = Field(
        default="logs",
        description="日志目录"
    )

    # ==================== 表单填充配置 ====================

    max_form_pages: int = Field(
        default=15,
        description="表单最大页数"
    )
    browser_timeout: int = Field(
        default=30000,
        description="浏览器操作超时时间 (ms)"
    )

    # ==================== 辅助方法 ====================

    @property
    def cors_origins_list(self) -> list:
        """获取 CORS 来源列表"""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]

    def validate_required(self) -> None:
        """验证必需的配置项"""
        errors = []
        if not self.supabase_url:
            errors.append("SUPABASE_URL")
        if not self.supabase_key:
            errors.append("SUPABASE_KEY")
        if errors:
            raise ValueError(f"缺少必需的环境变量: {', '.join(errors)}")


@lru_cache()
def get_settings() -> Settings:
    """
    获取配置单例

    使用 lru_cache 确保只创建一次
    """
    return Settings()


# 全局配置实例
settings = get_settings()

