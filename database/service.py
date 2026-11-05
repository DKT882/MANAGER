"""
High-Performance Asynchronous Data Access Layer (Service / DAO).
Bridges RAM in-memory caches with persistent MongoDB storage without introducing latency.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional
from .connection import MongoDBManager, get_db
from .models import (
    ChatSettingsModel,
    ModerationAuditLogModel,
    ReportRecordModel,
    WarnIncident,
    migrate_chat_settings_document,
)


class DatabaseService:
    """
    Asynchronous Service layer managing data hydration, write-behind persistence,
    and schema migrations.
    """

    # --------------------------------------------------------------------------
    # 1. Cache Hydration (Bot Startup)
    # --------------------------------------------------------------------------
    @staticmethod
    async def hydrate_settings_cache(
        cache_dict: Dict[int, Dict[str, Any]],
        chat_titles_dict: Optional[Dict[int, str]] = None
    ) -> int:
        """
        Loads all group configurations from MongoDB into the bot's runtime memory cache.
        Guarantees 0ms read operations for incoming Telegram events.
        """
        db = get_db()
        if db is None:
            return 0

        count = 0
        try:
            # Low-memory projection: omit MongoDB internal _id field
            cursor = db.chat_settings.find({}, {"_id": 0})
            async for doc in cursor:
                chat_id = doc.get("chat_id")
                if not chat_id:
                    continue

                # Run progressive migration if schema version is older
                migrated_doc = migrate_chat_settings_document(doc)
                try:
                    model = ChatSettingsModel.model_validate(migrated_doc)
                    cache_dict[chat_id] = model.to_in_memory_dict()
                    if chat_titles_dict is not None and doc.get("chat_title"):
                        chat_titles_dict[chat_id] = str(doc["chat_title"])
                    count += 1
                except Exception as parse_err:
                    print(f"[DATABASE] Error parsing settings for chat {chat_id}: {parse_err}")

            print(f"[DATABASE] Hydrated {count} chat configurations into in-memory cache.")
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to hydrate settings from database: {e}")

        return count

    @staticmethod
    async def hydrate_warn_cache(warn_cache_dict: Dict[int, Dict[int, int]]) -> int:
        """
        Loads active user warning counters from MongoDB into the bot's runtime warn cache.
        """
        db = get_db()
        if db is None:
            return 0

        count = 0
        try:
            # Bandwidth & RAM optimized projection: load strictly active counters
            cursor = db.user_warnings.find(
                {"warn_count": {"$gt": 0}},
                {"_id": 0, "chat_id": 1, "user_id": 1, "warn_count": 1}
            )
            async for doc in cursor:
                chat_id = doc.get("chat_id")
                user_id = doc.get("user_id")
                warn_count = doc.get("warn_count", 0)

                if chat_id and user_id:
                    warn_cache_dict[chat_id][user_id] = warn_count
                    count += 1

            print(f"[DATABASE] Hydrated {count} active user warnings into memory cache.")
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to hydrate warnings: {e}")

        return count

    # --------------------------------------------------------------------------
    # 2. Write-Behind Persistence (Chat Settings)
    # --------------------------------------------------------------------------
    @classmethod
    def save_settings_background(cls, chat_id: int, chat_title: str, mem_dict: Dict[str, Any]) -> None:
        """
        Schedules non-blocking async write to MongoDB.
        Executes in background so Telegram message handling is NOT delayed.
        """
        if not MongoDBManager.is_connected():
            return

        asyncio.create_task(cls._persist_settings_worker(chat_id, chat_title, mem_dict))

    @staticmethod
    async def _persist_settings_worker(chat_id: int, chat_title: str, mem_dict: Dict[str, Any]) -> None:
        db = get_db()
        if db is None:
            return

        try:
            model = ChatSettingsModel.from_in_memory_dict(chat_id, chat_title, mem_dict)
            model.metadata.updated_at = datetime.now(timezone.utc)
            doc = model.model_dump(mode="json")

            await db.chat_settings.update_one(
                {"chat_id": chat_id},
                {"$set": doc},
                upsert=True
            )
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to persist chat {chat_id} settings: {e}")

    # --------------------------------------------------------------------------
    # 3. Warnings Persistence
    # --------------------------------------------------------------------------
    @classmethod
    def record_warn_background(
        cls,
        chat_id: int,
        user_id: int,
        warned_by_id: int,
        reason: str,
        current_count: int
    ) -> None:
        """Schedules non-blocking warn recording in MongoDB."""
        if not MongoDBManager.is_connected():
            return
        asyncio.create_task(cls._record_warn_worker(chat_id, user_id, warned_by_id, reason, current_count))

    @staticmethod
    async def _record_warn_worker(
        chat_id: int,
        user_id: int,
        warned_by_id: int,
        reason: str,
        current_count: int
    ) -> None:
        db = get_db()
        if db is None:
            return

        try:
            incident = WarnIncident(
                reason=reason,
                warned_by_id=warned_by_id,
                warned_at=datetime.now(timezone.utc)
            ).model_dump(mode="json")

            now = datetime.now(timezone.utc)
            await db.user_warnings.update_one(
                {"chat_id": chat_id, "user_id": user_id},
                {
                    "$set": {
                        "warn_count": current_count,
                        "last_warned_at": now,
                        "updated_at": now,
                    },
                    "$push": {
                        "incidents": {
                            "$each": [incident],
                            "$slice": -20
                        }
                    }
                },
                upsert=True
            )
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to record warn: {e}")

    @classmethod
    def reset_warn_background(cls, chat_id: int, user_id: int) -> None:
        """Schedules warning reset in MongoDB."""
        if not MongoDBManager.is_connected():
            return
        asyncio.create_task(cls._reset_warn_worker(chat_id, user_id))

    @staticmethod
    async def _reset_warn_worker(chat_id: int, user_id: int) -> None:
        db = get_db()
        if db is None:
            return

        try:
            await db.user_warnings.update_one(
                {"chat_id": chat_id, "user_id": user_id},
                {"$set": {"warn_count": 0, "updated_at": datetime.now(timezone.utc)}}
            )
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to reset warn: {e}")

    @classmethod
    def cancel_warn_background(cls, chat_id: int, user_id: int, new_count: int) -> None:
        """Schedules warning decrement / cancellation in MongoDB."""
        if not MongoDBManager.is_connected():
            return
        asyncio.create_task(cls._cancel_warn_worker(chat_id, user_id, new_count))

    @staticmethod
    async def _cancel_warn_worker(chat_id: int, user_id: int, new_count: int) -> None:
        db = get_db()
        if db is None:
            return

        try:
            await db.user_warnings.update_one(
                {"chat_id": chat_id, "user_id": user_id},
                {
                    "$set": {"warn_count": max(0, new_count), "updated_at": datetime.now(timezone.utc)},
                    "$pop": {"incidents": 1}
                }
            )
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to cancel warn: {e}")

    # --------------------------------------------------------------------------
    # 4. Moderation Audit Trail
    # --------------------------------------------------------------------------
    @classmethod
    def log_moderation_background(
        cls,
        chat_id: int,
        admin_id: int,
        target_id: Optional[int],
        action: str,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Non-blocking background logging for administrative actions."""
        if not MongoDBManager.is_connected():
            return
        asyncio.create_task(cls._log_moderation_worker(chat_id, admin_id, target_id, action, reason, metadata))

    @staticmethod
    async def _log_moderation_worker(
        chat_id: int,
        admin_id: int,
        target_id: Optional[int],
        action: str,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        db = get_db()
        if db is None:
            return

        try:
            log_entry = ModerationAuditLogModel(
                chat_id=chat_id,
                admin_id=admin_id,
                target_id=target_id,
                action=action,
                reason=reason,
                metadata=metadata or {},
                timestamp=datetime.now(timezone.utc)
            ).model_dump(mode="json")

            await db.moderation_audit_logs.insert_one(log_entry)
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to log audit trail: {e}")

    # --------------------------------------------------------------------------
    # 5. Incident & Report Tracking
    # --------------------------------------------------------------------------
    @classmethod
    def record_report_background(
        cls,
        report_id: str,
        chat_id: int,
        target_user_id: int,
        reporter_user_id: int,
        message_id: int,
        message_snippet: str,
        reason: str
    ) -> None:
        """Records incoming member report in database."""
        if not MongoDBManager.is_connected():
            return
        asyncio.create_task(
            cls._record_report_worker(
                report_id, chat_id, target_user_id, reporter_user_id, message_id, message_snippet, reason
            )
        )

    @staticmethod
    async def _record_report_worker(
        report_id: str,
        chat_id: int,
        target_user_id: int,
        reporter_user_id: int,
        message_id: int,
        message_snippet: str,
        reason: str
    ) -> None:
        db = get_db()
        if db is None:
            return

        try:
            report_doc = ReportRecordModel(
                report_id=report_id,
                chat_id=chat_id,
                target_user_id=target_user_id,
                reporter_user_id=reporter_user_id,
                message_id=message_id,
                message_snippet=message_snippet,
                reason=reason,
                status="pending",
                created_at=datetime.now(timezone.utc)
            ).model_dump(mode="json")

            await db.reports.insert_one(report_doc)
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to record report: {e}")

    @classmethod
    def resolve_report_background(
        cls,
        chat_id: int,
        message_id: int,
        resolved_by: int,
        action_taken: str
    ) -> None:
        """Updates report status upon admin resolution."""
        if not MongoDBManager.is_connected():
            return
        asyncio.create_task(cls._resolve_report_worker(chat_id, message_id, resolved_by, action_taken))

    @staticmethod
    async def _resolve_report_worker(
        chat_id: int,
        message_id: int,
        resolved_by: int,
        action_taken: str
    ) -> None:
        db = get_db()
        if db is None:
            return

        try:
            now = datetime.now(timezone.utc)
            await db.reports.update_one(
                {"chat_id": chat_id, "message_id": message_id, "status": "pending"},
                {
                    "$set": {
                        "status": "resolved" if action_taken != "dismissed" else "dismissed",
                        "resolved_by": resolved_by,
                        "action_taken": action_taken,
                        "resolved_at": now,
                    }
                }
            )
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to resolve report in database: {e}")

    # --------------------------------------------------------------------------
    # 6. Global Accepted Members Entity & Broadcast DAL
    # --------------------------------------------------------------------------
    @classmethod
    def record_accepted_member_background(
        cls,
        user_id: int,
        first_name: str,
        last_name: Optional[str],
        username: Optional[str],
        full_name: str,
        chat_id: int,
        chat_title: str,
        bio: Optional[str] = None
    ) -> None:
        """Schedules non-blocking async persistence of accepted member into global entity."""
        if not MongoDBManager.is_connected():
            return
        asyncio.create_task(cls._persist_accepted_member_worker(
            user_id, first_name, last_name, username, full_name, chat_id, chat_title, bio
        ))

    @staticmethod
    async def _persist_accepted_member_worker(
        user_id: int,
        first_name: str,
        last_name: Optional[str],
        username: Optional[str],
        full_name: str,
        chat_id: int,
        chat_title: str,
        bio: Optional[str] = None
    ) -> None:
        db = get_db()
        if db is None:
            return

        try:
            now = datetime.now(timezone.utc)
            await db.accepted_members.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "user_id": user_id,
                        "first_name": first_name or "",
                        "last_name": last_name or None,
                        "username": username.lower() if username else None,
                        "full_name": full_name or first_name or f"User {user_id}",
                        "last_accepted_at": now,
                        "status": "active",
                        "bio": bio,
                    },
                    "$setOnInsert": {
                        "first_accepted_at": now,
                    },
                    "$addToSet": {
                        "chat_ids": chat_id,
                        "chat_titles": chat_title,
                    },
                    "$inc": {
                        "accept_count": 1,
                    }
                },
                upsert=True
            )
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to record accepted member {user_id}: {e}", flush=True)

    @staticmethod
    async def hydrate_accepted_members_cache(cache_dict: Dict[int, Dict[str, Any]]) -> int:
        """Loads all globally accepted members from MongoDB into local memory cache on startup."""
        db = get_db()
        if db is None:
            return 0

        count = 0
        try:
            cursor = db.accepted_members.find({}, {"_id": 0})
            async for doc in cursor:
                uid = doc.get("user_id")
                if uid:
                    if isinstance(doc.get("last_accepted_at"), (datetime, date)):
                        doc["last_accepted_at"] = doc["last_accepted_at"].isoformat()
                    if isinstance(doc.get("first_accepted_at"), (datetime, date)):
                        doc["first_accepted_at"] = doc["first_accepted_at"].isoformat()
                    cache_dict[uid] = doc
                    count += 1
            print(f"[DATABASE] Hydrated {count} globally accepted members into memory cache.")
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to hydrate accepted members: {e}")
        return count

    @staticmethod
    async def get_accepted_members(chat_id: Optional[int] = None, limit: int = 1000) -> list[Dict[str, Any]]:
        """Retrieves accepted members list, optionally filtered by group chat ID."""
        db = get_db()
        if db is None:
            return []

        query = {}
        if chat_id is not None:
            query = {"chat_ids": chat_id}

        try:
            cursor = db.accepted_members.find(query, {"_id": 0}).sort("last_accepted_at", -1).limit(limit)
            raw_list = await cursor.to_list(length=limit)
            for doc in raw_list:
                if isinstance(doc.get("last_accepted_at"), (datetime, date)):
                    doc["last_accepted_at"] = doc["last_accepted_at"].isoformat()
                if isinstance(doc.get("first_accepted_at"), (datetime, date)):
                    doc["first_accepted_at"] = doc["first_accepted_at"].isoformat()
            return raw_list
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to fetch accepted members: {e}")
            return []

    @staticmethod
    async def get_accepted_members_count(chat_id: Optional[int] = None) -> int:
        """Returns total count of accepted members in global entity or specific group."""
        db = get_db()
        if db is None:
            return 0

        query = {}
        if chat_id is not None:
            query = {"chat_ids": chat_id}

        try:
            return await db.accepted_members.count_documents(query)
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to count accepted members: {e}")
            return 0
