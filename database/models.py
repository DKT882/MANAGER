"""
MongoDB Schemas & Models for High-Speed Telegram Admin Engine.
Engineered for ultra-fast async querying, high extensibility, and progressive schema migrations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

# Increment this whenever breaking structural changes are introduced.
CURRENT_SCHEMA_VERSION = 1


class ViolationAction(str, Enum):
    DELETE = "delete"
    MUTE = "mute"
    BAN = "ban"
    KICK = "kick"
    WARN = "warn"


class MediaRestrictionSettings(BaseModel):
    """
    Fine-grained media type restrictions.
    Designed with default fallbacks so new media types can be added without migrations.
    """
    model_config = ConfigDict(extra="allow")

    block_sticker: bool = Field(default=False, description="Block stickers sent by regular members")
    block_animation: bool = Field(default=False, description="Block GIF / animations")
    block_document: bool = Field(default=False, description="Block documents / files")
    block_audio: bool = Field(default=False, description="Block audio MP3 / music files")
    block_voice: bool = Field(default=False, description="Block voice messages")
    block_photo: bool = Field(default=False, description="Block standalone photos")
    block_video: bool = Field(default=False, description="Block video files")
    block_video_note: bool = Field(default=False, description="Block round video notes (telegrams)")
    block_contact: bool = Field(default=False, description="Block contact vCards")
    block_location: bool = Field(default=False, description="Block location shares")
    media_action: str = Field(default="delete", description="Punishment action: 'delete' or 'warn'")


class LinkRestrictionSettings(BaseModel):
    """
    In-chat URL, invite, and bio-link filtering configurations.
    """
    model_config = ConfigDict(extra="allow")

    block_links: bool = Field(default=False, description="Block in-chat links for non-admin members")
    admin_links_block: bool = Field(default=False, description="Strict rule: delete links even if sent by admins")
    block_channel_links: bool = Field(default=False, description="Block links pointing to Telegram channels / posts")
    block_telegram_invites: bool = Field(default=False, description="Block t.me/+ or joinchat invite links")
    whitelist_domains: List[str] = Field(default_factory=list, description="Approved domains that bypass link blocker")
    whitelist_channels: List[str] = Field(default_factory=list, description="Approved usernames/channels exempt from filters")
    link_action: str = Field(default="delete", description="Punishment action: 'delete' or 'warn'")


class AntiFloodSettings(BaseModel):
    """
    Windowed sliding-frequency anti-spam configurations.
    """
    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Master toggle for anti-flood engine")
    flood_window: float = Field(default=3.0, ge=0.5, le=60.0, description="Window time frame in seconds")
    flood_limit: int = Field(default=5, ge=1, le=100, description="Maximum messages allowed inside window")
    action: ViolationAction = Field(default=ViolationAction.MUTE, description="Automated enforcement action")
    mute_duration: int = Field(default=900, ge=60, description="Mute duration in seconds upon violation")


class WarnSettings(BaseModel):
    """
    Automated warning escalation thresholds.
    """
    model_config = ConfigDict(extra="allow")

    warn_limit: int = Field(default=3, ge=1, le=20, description="Threshold of warnings before punishment")
    warn_action: ViolationAction = Field(default=ViolationAction.MUTE, description="Ceiling enforcement action")
    warn_duration: int = Field(default=86400, ge=60, description="Penalty duration in seconds (e.g. 24h)")
    warn_decay_hours: int = Field(default=0, ge=0, description="Hours after which an unpunished warn expires (0 = no decay)")
    warn_cancel_btn: bool = Field(default=True, description="Attach inline cancel button to warn notices")
    custom_warn_msg: str = Field(default="", description="Custom template for warning notices configured via PM")
    auto_warn_enabled: bool = Field(default=True, description="Master toggle for automated violation warnings")
    warn_on_duplicate: bool = Field(default=True, description="Auto-warn on duplicate message repetitions")
    duplicate_limit: int = Field(default=2, ge=2, le=10, description="Repeated message threshold before violation")
    duplicate_window: int = Field(default=30, ge=5, le=300, description="Window in seconds for duplicate tracking")
    warn_on_flood: bool = Field(default=True, description="Auto-warn on message flood / frequency breach")


class ReportingSettings(BaseModel):
    """
    Community / show reporting configurations.
    """
    model_config = ConfigDict(extra="allow")

    public_report_enabled: bool = Field(default=True, description="Allow members to use /report in group")
    private_admin_report_enabled: bool = Field(default=True, description="Allow members to use /show to PM admins")
    log_channel_id: Optional[int] = Field(default=None, description="Optional dedicated Telegram channel ID for audit logs")
    excepted_admin_ids: List[int] = Field(default_factory=list, description="Explicit list of admin user IDs designated to receive reports")


class DocumentMetadata(BaseModel):
    """
    Operational metadata for tracking lifecycle and versioning.
    """
    model_config = ConfigDict(extra="allow")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# PRIMARY CHAT SETTINGS MODEL
# ==============================================================================

class ChatSettingsModel(BaseModel):
    """
    Master configuration document for Telegram groups/supergroups.
    Designed with the Document Versioning Pattern (schema_version) and Extensible
    Attributes Bag (feature_flags, custom_attributes) to support future features cleanly.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    chat_id: int = Field(..., description="Unique 64-bit Telegram chat identifier (Primary Key in business logic)")
    chat_title: str = Field(default="Unknown Group", description="Latest cached group title")
    chat_type: str = Field(default="supergroup", description="Group type ('group' or 'supergroup')")
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, description="Database schema version for migration orchestration")

    # Modular Settings Sub-documents
    media: MediaRestrictionSettings = Field(default_factory=MediaRestrictionSettings)
    links: LinkRestrictionSettings = Field(default_factory=LinkRestrictionSettings)
    flood: AntiFloodSettings = Field(default_factory=AntiFloodSettings)
    warnings: WarnSettings = Field(default_factory=WarnSettings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)
    clean_service_messages: bool = Field(default=True, description="Auto-delete join and group left service notifications")
    block_bots: bool = Field(default=False, description="Auto-ban bots added to the group chat")
    bot_action: str = Field(default="ban", description="Punishment when unauthorized bot joins: 'ban' or 'kick'")
    approval_auto: bool = Field(default=False, description="Auto-approve chat join requests")
    welcome_pm_enabled: bool = Field(default=False, description="Send private DM welcome greeting when member request is accepted")
    welcome_pm_msg: str = Field(default="👋 Hello {name}!\nYour request to join <b>{chat_title}</b> has been approved! Welcome to the group! 🎉", description="Custom private DM welcome template")
    antispam_enabled: bool = Field(default=True, description="Master toggle for all anti-spam restrictions")

    # Future-Proofing Extensibility Bags
    feature_flags: Dict[str, bool] = Field(
        default_factory=dict,
        description="Dynamic feature toggles for progressive canary rollouts without schema mutations"
    )
    custom_attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Schema-less metadata bag pattern for arbitrary future plugins, webhooks, or custom rules"
    )

    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)

    def to_in_memory_dict(self) -> Dict[str, Any]:
        """
        Flattens the document into the high-speed local dictionary structure
        used by bot.py's runtime engine to guarantee 0ms memory reads.
        """
        data = dict(self.custom_attributes) if self.custom_attributes else {}
        data.update({
            "block_sticker": self.media.block_sticker,
            "block_animation": self.media.block_animation,
            "block_document": self.media.block_document,
            "block_audio": self.media.block_audio,
            "block_voice": self.media.block_voice,
            "block_photo": self.media.block_photo,
            "block_video": self.media.block_video,
            "media_action": getattr(self.media, "media_action", "delete"),
            "block_links": self.links.block_links,
            "admin_links_block": self.links.admin_links_block,
            "block_channel_links": self.links.block_channel_links,
            "link_action": getattr(self.links, "link_action", "delete"),
            "flood_protection": self.flood.enabled,
            "flood_window": self.flood.flood_window,
            "flood_limit": self.flood.flood_limit,
            "flood_action": self.flood.action.value if hasattr(self.flood.action, "value") else str(self.flood.action),
            "flood_duration": self.flood.mute_duration,
            "warn_limit": self.warnings.warn_limit,
            "warn_action": self.warnings.warn_action.value if hasattr(self.warnings.warn_action, "value") else str(self.warnings.warn_action),
            "warn_duration": self.warnings.warn_duration,
            "warn_cancel_btn": getattr(self.warnings, "warn_cancel_btn", True),
            "custom_warn_msg": getattr(self.warnings, "custom_warn_msg", ""),
            "auto_warn_enabled": getattr(self.warnings, "auto_warn_enabled", True),
            "warn_on_duplicate": getattr(self.warnings, "warn_on_duplicate", True),
            "duplicate_limit": getattr(self.warnings, "duplicate_limit", 2),
            "duplicate_window": getattr(self.warnings, "duplicate_window", 30),
            "warn_on_flood": getattr(self.warnings, "warn_on_flood", True),
            "excepted_admins": list(self.reporting.excepted_admin_ids),
            "clean_service_messages": self.clean_service_messages,
            "block_bots": self.block_bots,
            "bot_action": getattr(self, "bot_action", "ban"),
            "approval_auto": getattr(self, "approval_auto", False),
            "welcome_pm_enabled": getattr(self, "welcome_pm_enabled", False),
            "welcome_pm_msg": getattr(self, "welcome_pm_msg", "👋 Hello {name}!\nYour request to join <b>{chat_title}</b> has been approved! Welcome to the group! 🎉"),
            "antispam_enabled": getattr(self, "antispam_enabled", True),
        })
        return data

    @classmethod
    def from_in_memory_dict(cls, chat_id: int, chat_title: str, mem_dict: Dict[str, Any]) -> ChatSettingsModel:
        """
        Constructs a full validated ChatSettingsModel from a flat memory dictionary.
        """
        media = MediaRestrictionSettings(
            block_sticker=mem_dict.get("block_sticker", False),
            block_animation=mem_dict.get("block_animation", False),
            block_document=mem_dict.get("block_document", False),
            block_audio=mem_dict.get("block_audio", False),
            block_voice=mem_dict.get("block_voice", False),
            block_photo=mem_dict.get("block_photo", False),
            block_video=mem_dict.get("block_video", False),
            media_action=mem_dict.get("media_action", "delete"),
        )
        links = LinkRestrictionSettings(
            block_links=mem_dict.get("block_links", False),
            admin_links_block=mem_dict.get("admin_links_block", False),
            block_channel_links=mem_dict.get("block_channel_links", False),
            link_action=mem_dict.get("link_action", "delete"),
        )
        flood_action_raw = mem_dict.get("flood_action", "mute")
        try:
            flood_action = ViolationAction(flood_action_raw)
        except ValueError:
            flood_action = ViolationAction.MUTE

        flood = AntiFloodSettings(
            enabled=mem_dict.get("flood_protection", True),
            flood_window=float(mem_dict.get("flood_window", 3.0)),
            flood_limit=int(mem_dict.get("flood_limit", 5)),
            action=flood_action,
            mute_duration=int(mem_dict.get("flood_duration", 900)),
        )
        warn_action_raw = mem_dict.get("warn_action", "mute")
        try:
            warn_action = ViolationAction(warn_action_raw)
        except ValueError:
            warn_action = ViolationAction.MUTE

        warnings = WarnSettings(
            warn_limit=int(mem_dict.get("warn_limit", 3)),
            warn_action=warn_action,
            warn_duration=int(mem_dict.get("warn_duration", 86400)),
            warn_cancel_btn=bool(mem_dict.get("warn_cancel_btn", True)),
            custom_warn_msg=str(mem_dict.get("custom_warn_msg", "")),
            auto_warn_enabled=bool(mem_dict.get("auto_warn_enabled", True)),
            warn_on_duplicate=bool(mem_dict.get("warn_on_duplicate", True)),
            duplicate_limit=int(mem_dict.get("duplicate_limit", 2)),
            duplicate_window=int(mem_dict.get("duplicate_window", 30)),
            warn_on_flood=bool(mem_dict.get("warn_on_flood", True)),
        )
        reporting = ReportingSettings(
            public_report_enabled=mem_dict.get("public_report_enabled", True),
            private_admin_report_enabled=mem_dict.get("private_admin_report_enabled", True),
            excepted_admin_ids=list(mem_dict.get("excepted_admins", [])),
        )

        custom_attrs = {k: v for k, v in mem_dict.items()}
        return cls(
            chat_id=chat_id,
            chat_title=chat_title,
            media=media,
            links=links,
            flood=flood,
            warnings=warnings,
            reporting=reporting,
            clean_service_messages=mem_dict.get("clean_service_messages", True),
            block_bots=mem_dict.get("block_bots", False),
            bot_action=mem_dict.get("bot_action", "ban"),
            approval_auto=mem_dict.get("approval_auto", False),
            welcome_pm_enabled=mem_dict.get("welcome_pm_enabled", False),
            welcome_pm_msg=mem_dict.get("welcome_pm_msg", "👋 Hello {name}!\nYour request to join <b>{chat_title}</b> has been approved! Welcome to the group! 🎉"),
            antispam_enabled=mem_dict.get("antispam_enabled", True),
            custom_attributes=custom_attrs,
        )


# ==============================================================================
# USER WARNINGS & AUDIT LOG MODELS
# ==============================================================================

class WarnIncident(BaseModel):
    """Specific warning incident record."""
    model_config = ConfigDict(extra="allow")

    reason: str = Field(default="Violation")
    warned_by_id: int = Field(..., description="Admin Telegram user ID who issued the warning")
    warned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserWarningsModel(BaseModel):
    """
    Persistent tracking of user warning state per group.
    Compound Unique Index: (chat_id, user_id)
    """
    model_config = ConfigDict(extra="allow")

    chat_id: int = Field(..., description="Target Telegram chat ID")
    user_id: int = Field(..., description="Target Telegram member user ID")
    warn_count: int = Field(default=0, ge=0, description="Current accumulated warning count")
    incidents: List[WarnIncident] = Field(default_factory=list, description="Historical record of warning events")
    last_warned_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModerationAuditLogModel(BaseModel):
    """
    Immutable audit log for security, oversight, and dispute resolution.
    Index: (chat_id, timestamp)
    """
    model_config = ConfigDict(extra="allow")

    chat_id: int = Field(..., description="Chat ID where action occurred")
    admin_id: int = Field(..., description="Administrator who initiated action")
    target_id: Optional[int] = Field(default=None, description="Target member affected")
    action: str = Field(..., description="Action type: mute, ban, warn, pin, clear, promote, demote")
    reason: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary parameters (duration, msg_ids, etc.)")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReportRecordModel(BaseModel):
    """
    Tracks community and private member reports.
    Index: (chat_id, status)
    """
    model_config = ConfigDict(extra="allow")

    report_id: str = Field(..., description="Unique UUID for this report incident")
    chat_id: int = Field(..., description="Group ID where report originated")
    target_user_id: int = Field(..., description="User being reported")
    reporter_user_id: int = Field(..., description="User filing the report")
    message_id: int = Field(..., description="Telegram message ID of reported content")
    message_snippet: str = Field(default="", description="Text or media preview of reported message")
    reason: str = Field(default="No reason provided")
    status: str = Field(default="pending", description="Status: pending, resolved, dismissed")
    resolved_by: Optional[int] = Field(default=None, description="Admin user ID who resolved this report")
    action_taken: Optional[str] = Field(default=None, description="Action taken: deleted, muted, banned, dismissed")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = Field(default=None)


class AcceptedMemberModel(BaseModel):
    """
    Global Unified Member Entity.
    Consolidated storage of all request-accepted members across all managed groups.
    Enables cross-group member auditing, historical tracking, and targeted broadcasts.
    Unique Index: user_id
    Index: chat_ids, last_accepted_at
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    user_id: int = Field(..., description="Unique 64-bit Telegram user ID")
    first_name: str = Field(default="", description="Telegram user first name")
    last_name: Optional[str] = Field(default=None, description="Telegram user last name")
    username: Optional[str] = Field(default=None, description="Telegram username without @ (lowercase)")
    full_name: str = Field(default="Member", description="Formatted full name")
    chat_ids: List[int] = Field(default_factory=list, description="All chat IDs where member's join request was accepted")
    chat_titles: List[str] = Field(default_factory=list, description="All chat titles where member was accepted")
    first_accepted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_accepted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    accept_count: int = Field(default=1, description="Number of times accepted across groups")
    bio: Optional[str] = Field(default=None, description="User bio at time of join request")
    status: str = Field(default="active", description="Member status: active, unsubscribed, blocked")


# ==============================================================================
# SCHEMA MIGRATION PIPELINE FOR FUTURE RELEASES
# ==============================================================================

def migrate_chat_settings_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Progressive schema migration engine.
    When future versions increment CURRENT_SCHEMA_VERSION, this pipeline migrates
    legacy database documents on-the-fly without requiring downtime or offline batch scripts.
    """
    version = doc.get("schema_version", 1)

    # Example future upgrade path:
    # if version < 2:
    #     doc["new_feature_block"] = {"new_toggle": True}
    #     doc["schema_version"] = 2
    #     version = 2

    doc["schema_version"] = CURRENT_SCHEMA_VERSION
    return doc
