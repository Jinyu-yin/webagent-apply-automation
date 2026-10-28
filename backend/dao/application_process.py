"""
application_process 表的数据访问对象
"""

from typing import Optional, Dict, Any
from supabase import Client


class ApplicationProcessDao:
    """申请流程表"""

    __tablename__ = "application_process"

    @classmethod
    def get_by_apply_id(cls, db: Client, apply_record_id: int) -> Optional[Dict[str, Any]]:
        """根据申请记录 ID 获取流程"""
        res = (
            db.table(cls.__tablename__)
            .select("*")
            .eq("apply_record_id", apply_record_id)
            .execute()
        )
        return res.data[0] if res.data else None

    @classmethod
    def create(cls, db: Client, apply_record_id: int, uni_id: str = '') -> Dict[str, Any]:
        """创建流程记录"""
        data = {
            "apply_record_id": apply_record_id,
            "uni_id": uni_id,
            "process_status": "created",  # 数据库字段名是 process_status
        }
        res = db.table(cls.__tablename__).insert(data).execute()
        return res.data[0] if res.data else None

    @classmethod
    def update_status(
        cls,
        db: Client,
        apply_record_id: int,
        status: str,
        message: str = ''
    ) -> bool:
        """更新流程状态"""
        data = {"process_status": status}  # 数据库字段名是 process_status
        if message:
            data["status_message"] = message  # 数据库字段名是 status_message

        res = (
            db.table(cls.__tablename__)
            .update(data)
            .eq("apply_record_id", apply_record_id)
            .execute()
        )
        return len(res.data) > 0

    @classmethod
    def update_fill_result(
        cls,
        db: Client,
        apply_record_id: int,
        filled: int,
        failed: int,
        fill_result: Dict[str, Any]
    ) -> bool:
        """更新填充结果"""
        # 注意：数据库没有 fields_failed 字段，只有 fields_filled
        data = {
            "fields_filled": filled,
            "fill_result": fill_result,
        }
        res = (
            db.table(cls.__tablename__)
            .update(data)
            .eq("apply_record_id", apply_record_id)
            .execute()
        )
        return len(res.data) > 0

    @classmethod
    def get_fill_result(cls, db: Client, apply_record_id: int) -> Dict[str, Any]:
        """获取填充结果"""
        res = (
            db.table(cls.__tablename__)
            .select("fill_result")
            .eq("apply_record_id", apply_record_id)
            .execute()
        )
        if res.data and res.data[0].get("fill_result"):
            return res.data[0]["fill_result"]
        return {}

    @classmethod
    def update_uni_id(cls, db: Client, apply_record_id: int, uni_id: str) -> bool:
        """更新学校 ID"""
        res = (
            db.table(cls.__tablename__)
            .update({"uni_id": uni_id})
            .eq("apply_record_id", apply_record_id)
            .execute()
        )
        return len(res.data) > 0

