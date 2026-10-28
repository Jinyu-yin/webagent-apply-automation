"""
Payload 数据管理器

中心化管理所有 payload 数据交互
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional


class PayloadManager:
    """
    中心化的 Payload 管理器
    
    所有的数据操作都经过这个模块，确保 payload 始终保持一致性：
    - 字段发现和添加
    - 生成文件的追踪
    - 隐藏表单字段的记录
    - 嵌套表单进度跟踪
    """
    
    def __init__(self, payload_path: Path):
        self.payload_path = Path(payload_path)
        self.payload = self._load_payload()
    
    def _load_payload(self) -> Dict:
        """加载 payload 文件"""
        if not self.payload_path.exists():
            print(f"⚠️ Payload 文件不存在，创建空 payload: {self.payload_path}")
            return {"data": {}, "fields": {}, "assets": {}, "metadata": {}}
        
        with open(self.payload_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def save(self) -> bool:
        """保存 payload 到文件"""
        try:
            self.payload_path.parent.mkdir(parents=True, exist_ok=True)
            self.update_metadata()
            
            with open(self.payload_path, 'w', encoding='utf-8') as f:
                json.dump(self.payload, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"❌ 保存 payload 失败: {e}")
            return False
    
    # ===== 字段数据操作 =====
    
    def get_field_value(self, field_id: str) -> Any:
        """
        获取字段值（兼容新旧格式）
        
        新格式: fields: {field_id: {value, label, type, source}}
        旧格式: data: {field_id: value}
        """
        fields = self.payload.get("fields", {})
        if isinstance(fields, dict) and field_id in fields:
            field_data = fields[field_id]
            if isinstance(field_data, dict):
                return field_data.get("value")
            return field_data
        return self.payload.get("data", {}).get(field_id)
    
    def get_field_data(self, field_id: str) -> Optional[Dict]:
        """获取字段完整数据（包括 value, label, type, source）"""
        fields = self.payload.get("fields", {})
        if isinstance(fields, dict) and field_id in fields:
            field_data = fields[field_id]
            if isinstance(field_data, dict):
                return field_data
            return {"value": field_data}
        
        value = self.payload.get("data", {}).get(field_id)
        if value is not None:
            return {"value": value}
        return None
    
    def set_field_value(self, field_id: str, value: Any, **kwargs) -> bool:
        """设置字段值（使用新格式）"""
        if "fields" not in self.payload:
            self.payload["fields"] = {}
        
        if field_id in self.payload["fields"] and isinstance(self.payload["fields"][field_id], dict):
            self.payload["fields"][field_id]["value"] = value
            self.payload["fields"][field_id].update(kwargs)
        else:
            self.payload["fields"][field_id] = {"value": value, **kwargs}
        return True
    
    def get_all_fields(self) -> Dict:
        """
        获取所有字段数据 {field_id: {value, label, type, source} 或 value}
        
        兼容新旧格式
        """
        result = {}
        
        # 新格式
        fields = self.payload.get("fields", {})
        if isinstance(fields, dict):
            result.update(fields)
        
        # 旧格式（补充缺失的）
        data = self.payload.get("data", {})
        if isinstance(data, dict):
            for field_id, value in data.items():
                if field_id not in result:
                    result[field_id] = value
        
        return result
    
    def get_all_values(self) -> Dict[str, Any]:
        """获取所有字段值 {field_id: value}（提取 value）"""
        result = {}
        all_fields = self.get_all_fields()
        
        for field_id, field_data in all_fields.items():
            if isinstance(field_data, dict):
                result[field_id] = field_data.get("value")
            else:
                result[field_id] = field_data
        
        return result
    
    # ===== 资产管理 =====
    
    def register_generated_file(self, field_id: str, file_path: str, file_type: str) -> bool:
        """注册生成的文件"""
        if "assets" not in self.payload:
            self.payload["assets"] = {}
        
        if "generated_files" not in self.payload["assets"]:
            self.payload["assets"]["generated_files"] = {}
        
        file_info = {
            "path": file_path,
            "type": file_type,
            "size": self._get_file_size(file_path),
            "created": datetime.now().isoformat(),
            "field_id": field_id
        }
        
        self.payload["assets"]["generated_files"][field_id] = file_info
        return True
    
    def get_generated_file(self, field_id: str) -> Optional[str]:
        """获取字段对应的生成文件路径"""
        generated_files = self.payload.get("assets", {}).get("generated_files", {})
        file_info = generated_files.get(field_id)
        return file_info.get("path") if file_info else None
    
    # ===== 发现历史记录 =====
    
    def log_field_discovery(
        self, 
        field_id: str, 
        field_label: str, 
        source: str, 
        value: str = None
    ) -> bool:
        """记录字段发现历史"""
        if "assets" not in self.payload:
            self.payload["assets"] = {}
        
        if "field_discovery_log" not in self.payload["assets"]:
            self.payload["assets"]["field_discovery_log"] = []
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "field_id": field_id,
            "label": field_label,
            "source": source,
            "value": value
        }
        
        self.payload["assets"]["field_discovery_log"].append(entry)
        return True
    
    def get_discovery_history(self, limit: int = 10) -> List[Dict]:
        """获取发现历史（最新 N 条）"""
        history = self.payload.get("assets", {}).get("field_discovery_log", [])
        return history[-limit:] if limit > 0 else history
    
    # ===== 元数据管理 =====
    
    def update_metadata(self) -> bool:
        """更新元数据"""
        if "metadata" not in self.payload:
            self.payload["metadata"] = {}
        
        self.payload["metadata"]["last_updated"] = datetime.now().isoformat()
        self.payload["metadata"]["fields_count"] = len(self.payload.get("fields", {}))
        self.payload["metadata"]["data_fields_count"] = len(self.payload.get("data", {}))
        
        return True
    
    # ===== 统计 =====
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        fields = self.payload.get("fields", {})
        data = self.payload.get("data", {})
        assets = self.payload.get("assets", {})
        
        # 计算有值的字段数
        fields_with_values = 0
        for field_id, field_data in fields.items():
            if isinstance(field_data, dict):
                if field_data.get("value"):
                    fields_with_values += 1
            elif field_data:
                fields_with_values += 1
        
        return {
            "total_fields": len(fields),
            "fields_with_values": fields_with_values,
            "fields_empty": len(fields) - fields_with_values,
            "legacy_data_fields": len(data),
            "generated_files_count": len(assets.get("generated_files", {})),
            "discovery_log_entries": len(assets.get("field_discovery_log", []))
        }
    
    def print_stats(self):
        """打印统计信息"""
        stats = self.get_stats()
        print("\n【Payload 统计】")
        print("=" * 50)
        print(f"总字段数: {stats['total_fields']}")
        print(f"有值字段: {stats['fields_with_values']}")
        print(f"空字段: {stats['fields_empty']}")
        print(f"生成的文件: {stats['generated_files_count']}")
        print(f"发现历史记录: {stats['discovery_log_entries']}")
    
    # ===== 辅助方法 =====
    
    @staticmethod
    def _get_file_size(file_path: str) -> int:
        """获取文件大小"""
        try:
            return Path(file_path).stat().st_size
        except:
            return 0

