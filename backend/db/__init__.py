"""
数据库连接模块

使用 Supabase 作为数据库
"""

from functools import lru_cache
from supabase import create_client, Client

from backend.config import settings


@lru_cache()
def get_db() -> Client:
    """
    获取数据库连接（单例模式）

    使用 lru_cache 确保只创建一次连接

    Returns:
        Supabase Client 实例
    """
    if not settings.supabase_url:
        raise ValueError("SUPABASE_URL 环境变量未设置，请在 .env 文件中配置")
    if not settings.supabase_key:
        raise ValueError("SUPABASE_KEY 环境变量未设置，请在 .env 文件中配置")

    return create_client(settings.supabase_url, settings.supabase_key)


def reset_db():
    """重置数据库连接（用于测试）"""
    get_db.cache_clear()

