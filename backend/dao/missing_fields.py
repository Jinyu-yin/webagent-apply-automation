"""
missing_fields 表的数据访问对象
"""

from typing import Optional, List, Dict, Any
from supabase import Client


class MissingFieldsDao:
    """缺失字段表"""

    __tablename__ = "missing_fields"

    @classmethod
    def get_by_apply_id(
        cls,
        db: Client,
        apply_record_id: int,
        only_unresolved: bool = True
    ) -> List[Dict[str, Any]]:
        """获取申请的缺失字段"""
        query = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("apply_record_id", apply_record_id)
        )

        if only_unresolved:
            query = query.eq("is_resolved", False)

        res = query.execute()
        return res.data or []

    @classmethod
    def add(cls, db: Client, apply_record_id: int, field_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """添加缺失字段"""
        field_data["apply_record_id"] = apply_record_id
        field_data["is_resolved"] = False
        res = db.table(cls.__tablename__).insert(field_data).execute()
        return res.data[0] if res.data else None

    @classmethod
    def add_batch(cls, db: Client, apply_record_id: int, fields: List[Dict[str, Any]]) -> int:
        """批量添加缺失字段"""
        if not fields:
            return 0

        for field in fields:
            field["apply_record_id"] = apply_record_id
            if "is_resolved" not in field:
                field["is_resolved"] = False

        res = db.table(cls.__tablename__).insert(fields).execute()
        return len(res.data) if res.data else 0

    @classmethod
    def update_value(
        cls,
        db: Client,
        apply_record_id: int,
        field_id: str,
        value: str
    ) -> bool:
        """更新字段值"""
        res = (
            db.table(cls.__tablename__)
            .update({"resolved_value": value, "is_resolved": True})
            .eq("apply_record_id", apply_record_id)
            .eq("field_id", field_id)
            .execute()
        )
        return len(res.data) > 0

    @classmethod
    def delete_field(cls, db: Client, apply_record_id: int, field_id: str) -> bool:
        """删除字段"""
        res = (
            db.table(cls.__tablename__)
            .delete()
            .eq("apply_record_id", apply_record_id)
            .eq("field_id", field_id)
            .execute()
        )
        return len(res.data) > 0

    @classmethod
    def delete_all(cls, db: Client, apply_record_id: int) -> int:
        """删除所有缺失字段"""
        res = (
            db.table(cls.__tablename__)
            .delete()
            .eq("apply_record_id", apply_record_id)
            .execute()
        )
        return len(res.data) if res.data else 0
