"""
application_payload 表的数据访问对象
"""

from typing import Optional, List, Dict, Any
from supabase import Client


class ApplicationPayloadDao:
    """申请 Payload 表"""

    __tablename__ = "application_payload"

    @classmethod
    def get_by_apply_id(cls, db: Client, apply_record_id: int) -> List[Dict[str, Any]]:
        """获取申请的所有 Payload"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("apply_record_id", apply_record_id)
            .execute()
        )
        return res.data or []

    @classmethod
    def get_by_field_id(
        cls,
        db: Client,
        apply_record_id: int,
        field_id: str
    ) -> Optional[Dict[str, Any]]:
        """根据字段 ID 获取 Payload"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("apply_record_id", apply_record_id)
            .eq("field_id", field_id)
            .execute()
        )
        return res.data[0] if res.data else None

    @classmethod
    def upsert(
        cls,
        db: Client,
        apply_record_id: int,
        field_id: str,
        value: str,
        source: str = 'llm_match',
        field_label: str = '',
        field_type: str = 'text',
        options: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """插入或更新 Payload"""
        data = {
            "apply_record_id": apply_record_id,
            "field_id": field_id,
            "value": value,
            "source": source,
            "field_label": field_label,
            "field_type": field_type,
        }
        if options:
            data["options"] = options

        res = db.table(cls.__tablename__).upsert(
            data,
            on_conflict="apply_record_id,field_id"
        ).execute()
        return res.data[0] if res.data else None

    @classmethod
    def add_from_user_supplement(
        cls,
        db: Client,
        apply_record_id: int,
        field_id: str,
        value: str,
        field_label: str = '',
        field_type: str = 'text',
        options: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """从用户补充添加 Payload"""
        return cls.upsert(
            db=db,
            apply_record_id=apply_record_id,
            field_id=field_id,
            value=value,
            source='user_supplement',
            field_label=field_label,
            field_type=field_type,
            options=options
        )

    @classmethod
    def update_batch(
        cls,
        db: Client,
        apply_record_id: int,
        fields: Dict[str, str]
    ) -> int:
        """批量更新字段值"""
        updated = 0
        for field_id, value in fields.items():
            res = (
                db.table(cls.__tablename__)
                .update({"value": value})
                .eq("apply_record_id", apply_record_id)
                .eq("field_id", field_id)
                .execute()
            )
            if res.data:
                updated += 1
        return updated

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
    def count(cls, db: Client, apply_record_id: int) -> Dict[str, int]:
        """统计 Payload"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("apply_record_id", apply_record_id)
            .execute()
        )
        data = res.data or []
        with_value = sum(1 for d in data if d.get("value"))
        return {
            "total": len(data),
            "with_value": with_value,
            "without_value": len(data) - with_value
        }

    @classmethod
    def to_fill_payload(cls, db: Client, apply_record_id: int) -> Dict[str, Dict[str, Any]]:
        """转换为填充格式"""
        data = cls.get_by_apply_id(db, apply_record_id)
        result = {}
        for item in data:
            result[item["field_id"]] = {
                "value": item.get("value"),
                "type": item.get("field_type", "text"),
                "label": item.get("field_label", ""),
                "source": item.get("source", ""),
            }
        return result

