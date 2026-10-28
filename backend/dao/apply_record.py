"""
apply_record 表的数据访问对象
"""

import uuid
from typing import Optional, List, Dict, Any
from supabase import Client


class ApplyRecordDao:
    """申请记录表"""

    __tablename__ = "apply_record"

    @classmethod
    def get_by_id(cls, db: Client, record_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取申请记录"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("id", record_id)
            .execute()
        )
        return res.data[0] if res.data else None

    @classmethod
    def get_by_email(cls, db: Client, email: str) -> Optional[Dict[str, Any]]:
        """根据邮箱获取申请记录"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("email", email)
            .execute()
        )
        return res.data[0] if res.data else None

    @classmethod
    def get_by_user_id(cls, db: Client, user_id: str) -> List[Dict[str, Any]]:
        """根据用户 ID 获取所有申请记录"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        return res.data or []

    @classmethod
    def create(
        cls,
        db: Client,
        user_id: str,
        email: str,
        password: str,
        application_url: str,
        prog_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """创建申请记录

        Args:
            prog_id: 项目 ID (UUID 格式)，如果不传则自动生成
            group_id: 分组 ID (UUID 格式)，可选
        """
        data = {
            "user_id": user_id,
            "email": email,
            "password": password,
            "application_url": application_url,
            "status": "待注册",
            # prog_id 是 NOT NULL，如果未提供则生成新 UUID
            "prog_id": prog_id if prog_id else str(uuid.uuid4()),
        }
        # group_id 可以为 NULL
        if group_id:
            data["group_id"] = group_id
        res = db.table(cls.__tablename__).insert(data).execute()
        return res.data[0] if res.data else None

    @classmethod
    def update_status(cls, db: Client, record_id: int, status: str) -> bool:
        """更新申请状态"""
        res = (
            db.table(cls.__tablename__)
            .update({"status": status})
            .eq("id", record_id)
            .execute()
        )
        return len(res.data) > 0

    @classmethod
    def update_register_status(cls, db: Client, record_id: int, status: str) -> bool:
        """更新注册状态"""
        res = (
            db.table(cls.__tablename__)
            .update({"register_status": status})
            .eq("id", record_id)
            .execute()
        )
        return len(res.data) > 0

    @classmethod
    def get_register_status(cls, db: Client, record_id: int) -> Optional[str]:
        """获取注册状态"""
        res = (
            db.table(cls.__tablename__)
            .select("register_status")
            .eq("id", record_id)
            .execute()
        )
        if res.data:
            return res.data[0].get("register_status")
        return None
