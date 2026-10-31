"""
MongoDB Asynchronous Connection Manager.
Built on Motor (AsyncIOMotorClient) with connection pooling and automated index provisioning.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import pymongo

logger = logging.getLogger("DatabaseManager")


class MongoDBManager:
    """
    Singleton connection lifecycle manager for MongoDB.
    Supports graceful offline fallback, connection pooling, and automatic index creation.
    """
    _client: Optional[AsyncIOMotorClient] = None
    _db: Optional[AsyncIOMotorDatabase] = None
    _is_connected: bool = False

    @classmethod
    async def connect(cls, uri: Optional[str] = None, db_name: Optional[str] = None) -> bool:
        """
        Initializes asynchronous connection pool to MongoDB.
        """
        mongo_uri = uri or os.getenv("MONGO_URI", "").strip()
        database_name = db_name or os.getenv("MONGO_DB_NAME", "telegram_admin_bot").strip()

        if not mongo_uri:
            print("[DATABASE] No MONGO_URI configured. Running in pure local in-memory cache mode.")
            cls._is_connected = False
            return False

        try:
            print(f"[DATABASE] Connecting to MongoDB instance ({database_name})...")
            cls._client = AsyncIOMotorClient(
                mongo_uri,
                maxPoolSize=100,
                minPoolSize=10,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000,
            )
            # Verify connectivity via ping
            await cls._client.admin.command("ping")
            cls._db = cls._client[database_name]
            cls._is_connected = True
            print("[DATABASE] Connection established successfully with connection pooling active.")

            # Create essential production indexes
            await cls._provision_indexes()
            return True

        except Exception as e:
            print(f"[DATABASE WARNING] Could not connect to MongoDB: {e}")
            print("[DATABASE] Bot will continue operating in ultra-fast local in-memory cache mode.")
            cls._is_connected = False
            cls._client = None
            cls._db = None
            return False

    @classmethod
    async def _provision_indexes(cls) -> None:
        """
        Idempotently provisions compound, unique, and query-optimized indexes.
        """
        if not cls._is_connected or cls._db is None:
            return

        try:
            # 1. Chat Settings: Primary unique lookup by chat_id
            await cls._db.chat_settings.create_index(
                [("chat_id", pymongo.ASCENDING)],
                unique=True,
                name="idx_chat_settings_chat_id_unique"
            )

            # 2. User Warnings: Compound unique index on (chat_id, user_id)
            await cls._db.user_warnings.create_index(
                [("chat_id", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING)],
                unique=True,
                name="idx_user_warnings_chat_user_unique"
            )

            # 3. Moderation Audit Logs: Compound index for fast chronological group history
            await cls._db.moderation_audit_logs.create_index(
                [("chat_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)],
                name="idx_audit_logs_chat_time"
            )

            # 4. Reports: Query index for pending/resolved reports
            await cls._db.reports.create_index(
                [("chat_id", pymongo.ASCENDING), ("status", pymongo.ASCENDING)],
                name="idx_reports_chat_status"
            )
            await cls._db.reports.create_index(
                [("report_id", pymongo.ASCENDING)],
                unique=True,
                name="idx_reports_id_unique"
            )

            print("[DATABASE] Production database indexes successfully provisioned.")
        except Exception as e:
            print(f"[DATABASE] Index creation notice: {e}")

    @classmethod
    async def disconnect(cls) -> None:
        """Closes the client connection pool gracefully."""
        if cls._client:
            cls._client.close()
            cls._is_connected = False
            print("[DATABASE] MongoDB client connection pool closed cleanly.")

    @classmethod
    def get_database(cls) -> Optional[AsyncIOMotorDatabase]:
        """Returns the active Motor database instance or None."""
        return cls._db

    @classmethod
    def is_connected(cls) -> bool:
        """Checks if active MongoDB connection is verified."""
        return cls._is_connected


def get_db() -> Optional[AsyncIOMotorDatabase]:
    """Helper shortcut to access the MongoDB database handle."""
    return MongoDBManager.get_database()
