"""
Database package for High-Speed Telegram Admin Engine.
Enterprise-grade asynchronous MongoDB layer using Motor and Pydantic v2.
"""

from .connection import MongoDBManager, get_db
from .models import (
    AntiFloodSettings,
    ChatSettingsModel,
    LinkRestrictionSettings,
    MediaRestrictionSettings,
    ModerationAuditLogModel,
    ReportRecordModel,
    UserWarningsModel,
    WarnSettings,
    AcceptedMemberModel,
)
from .service import DatabaseService

__all__ = [
    "MongoDBManager",
    "get_db",
    "DatabaseService",
    "ChatSettingsModel",
    "MediaRestrictionSettings",
    "LinkRestrictionSettings",
    "AntiFloodSettings",
    "WarnSettings",
    "UserWarningsModel",
    "ModerationAuditLogModel",
    "ReportRecordModel",
    "AcceptedMemberModel",
]
