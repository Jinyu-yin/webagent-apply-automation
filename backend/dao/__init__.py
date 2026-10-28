"""
DAO 模块

提供数据库表的访问对象
"""

from .apply_record import ApplyRecordDao
from .application_process import ApplicationProcessDao
from .university_fields import UniversityFieldsDao
from .missing_fields import MissingFieldsDao
from .user_application_info import UserApplicationInfoDao
from .application_payload import ApplicationPayloadDao

__all__ = [
    'ApplyRecordDao',
    'ApplicationProcessDao',
    'UniversityFieldsDao',
    'MissingFieldsDao',
    'UserApplicationInfoDao',
    'ApplicationPayloadDao',
]
