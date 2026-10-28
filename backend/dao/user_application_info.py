"""
user_application_info 表的数据访问对象

注意：此表通过 user_id 关联，不是 apply_record_id
"""

from typing import Optional, Dict, Any
from supabase import Client


class UserApplicationInfoDao:
    """用户申请信息表"""

    __tablename__ = "user_application_info"

    @classmethod
    def get_by_user_id(cls, db: Client, user_id: str) -> Optional[Dict[str, Any]]:
        """根据用户 ID 获取用户信息"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    @classmethod
    def create(cls, db: Client, user_id: str, user_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """创建用户信息"""
        user_info["user_id"] = user_id
        res = db.table(cls.__tablename__).insert(user_info).execute()
        return res.data[0] if res.data else None

    @classmethod
    def update(cls, db: Client, user_id: str, user_info: Dict[str, Any]) -> bool:
        """更新用户信息"""
        res = (
            db.table(cls.__tablename__)
            .update(user_info)
            .eq("user_id", user_id)
            .execute()
        )
        return len(res.data) > 0

    @classmethod
    def upsert(cls, db: Client, user_id: str, user_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """插入或更新用户信息"""
        user_info["user_id"] = user_id
        res = db.table(cls.__tablename__).upsert(
            user_info,
            on_conflict="user_id"
        ).execute()
        return res.data[0] if res.data else None
