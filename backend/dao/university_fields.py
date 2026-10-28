"""
university_fields 表的数据访问对象
"""

from typing import List, Dict, Any
from supabase import Client


class UniversityFieldsDao:
    """学校字段表"""

    __tablename__ = "university_fields"

    @classmethod
    def get_by_uni_id(cls, db: Client, uni_id: str) -> List[Dict[str, Any]]:
        """根据学校 ID 获取字段列表"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("uni_id", uni_id)
            .execute()
        )
        return res.data or []

    @classmethod
    def save(cls, db: Client, uni_id: str, fields: List[Dict[str, Any]]) -> int:
        """保存学校字段"""
        if not fields:
            return 0

        # 先删除旧数据
        db.table(cls.__tablename__).delete().eq("uni_id", uni_id).execute()

        # 添加 uni_id 到每个字段
        for field in fields:
            field["uni_id"] = uni_id

        res = db.table(cls.__tablename__).insert(fields).execute()
        return len(res.data) if res.data else 0

    @classmethod
    def count(cls, db: Client, uni_id: str) -> int:
        """统计字段数量"""
        res = (
            db.table(cls.__tablename__)
            .select("id", count="exact")
            .eq("uni_id", uni_id)
            .execute()
        )
        return res.count or 0
