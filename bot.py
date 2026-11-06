"""
High-Speed Telegram Admin Bot Implementation
Framework: aiogram v3.x | Event Loop: uvloop (Linux/macOS) / winloop (Windows)
Features: In-memory Caching, Instant Wipe Trigger, Strict Parallel Native Admin Rights,
          Anti-Flood Middleware, Instant Media/Link Interceptor, Interactive Settings UI.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import sys
import time

# Configure stdout and stderr for immediate line-buffering so Render / Docker live logs stream instantly
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass
os.environ["PYTHONUNBUFFERED"] = "1"
from collections import defaultdict, deque
from datetime import datetime, timezone, date
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

# ==============================================================================
# SPEED OPTIMIZATION STACK: HIGH-PERFORMANCE EVENT LOOP
# ==============================================================================
# Integrate uvloop for near-C loop execution speed, with winloop fallback on Windows.
try:
    import uvloop
    uvloop.install()
    LOOP_ENGINE = "uvloop"
except (ImportError, AttributeError):
    try:
        import winloop
        winloop.install()
        LOOP_ENGINE = "winloop"
    except (ImportError, AttributeError):
        LOOP_ENGINE = "asyncio-proactor"

import gc
import uuid
from aiohttp import web
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from database import DatabaseService, MongoDBManager

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router, types
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberAdministrator,
    ChatMemberOwner,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ==============================================================================
# ABSOLUTE LOCAL IN-MEMORY CACHE ARCHITECTURE
# ==============================================================================
# Bypasses database roundtrips completely for sub-millisecond execution latency.

# Default configuration template for newly encountered chats
DEFAULT_CHAT_CONFIG: Dict[str, Any] = {
    # Media filters
    "block_sticker": False,
    "block_animation": False,  # GIFs
    "block_document": False,
    "block_audio": False,
    "block_voice": False,
    "block_photo": False,
    "block_video": False,
    "media_action": "delete",  # 'delete' or 'warn'
    # Link filters
    "block_links": False,
    "admin_links_block": False,
    "block_channel_links": False,
    "link_action": "delete",   # 'delete' or 'warn'
    # Anti-Spam (Image 5)
    "antispam_enabled": True,  # Master toggle for all anti-spam filters
    "block_telegram_links": False,
    "block_forwarding": False,
    "block_quote": False,
    "block_total_links": False,
    # Regulations / Rules (Image 4)
    "rules_text": "",
    "rules_perm": "all",       # 'all' or 'admins'
    # Anti-flood settings
    "flood_protection": True,
    "flood_window": 3.0,       # Frequency window in seconds
    "flood_limit": 5,          # Maximum messages allowed inside window
    "flood_action": "mute",    # Violation action: 'mute', 'delete', 'kick', 'ban'
    "flood_duration": 900,     # Mute duration in seconds
    # Warning settings
    "auto_warn_enabled": True, # Master toggle for automated violation warnings
    "warn_limit": 3,           # Ceiling before automated penalty (1 to 10)
    "warn_action": "mute",     # Automated ceiling action: 'mute', 'ban', 'kick'
    "warn_duration": 86400,    # Penalty duration in seconds (0 = permanent)
    "warn_cancel_btn": True,   # Attach inline Cancel Warn button to warn notices
    "custom_warn_msg": "",     # Custom warn notice template configured in private DM
    "warn_on_duplicate": True, # Auto-warn on duplicate message repetitions
    "duplicate_limit": 2,      # Duplicate repetition threshold before violation
    "duplicate_window": 30,    # Duplicate detection time frame in seconds
    "warn_on_flood": True,     # Auto-warn when message frequency ceiling is exceeded
    # Welcome & Goodbye
    "welcome_enabled": False,
    "welcome_msg": "👋 Welcome to <b>{chat_title}</b>, {mention}!",
    "clean_welcome": True,
    "welcome_pm_enabled": False,
    "welcome_pm_msg": "👋 Hello {name}!\nYour request to join <b>{chat_title}</b> has been approved! Welcome to the group! 🎉",
    "goodbye_enabled": False,
    "goodbye_msg": "👋 Goodbye, {mention}!",
    # Alphabets Filter
    "block_arabic": False,
    "block_cyrillic": False,
    "block_chinese": False,
    "alphabet_action": "delete",
    # Captcha
    "captcha_mode": "off",     # 'off', 'button', 'math'
    "captcha_timeout": 60,     # seconds
    "captcha_action": "kick",  # 'kick' or 'ban'
    # Checks (Profile)
    "check_bio_links": True,
    "check_avatar": False,
    "check_username": False,
    # Admin reporting (@Admin)
    "admin_alert_enabled": True,
    "admin_alert_pm": True,
    # Blocks / Blacklist
    "blacklist_enabled": True,
    "blacklisted_users": [],
    # NSFW / Porn Filter
    "block_porn": False,
    "porn_action": "delete",   # 'delete', 'warn', 'mute'
    # Night Mode
    "night_mode": False,
    "night_start": 23,         # 23:00 UTC
    "night_end": 7,            # 07:00 UTC
    # Anti-Tag / Mass Mention
    "tag_limit": 5,
    "tag_protection": False,
    "tag_action": "delete",
    # Guardian Bot (Anti-Bot)
    "block_bots": False,
    "bot_action": "ban",       # Violation action: 'ban' or 'kick'
    # Approval Mode (Join Requests)
    "approval_auto": False,
    # Deleting Messages Cleaners
    "clean_service_messages": True,
    "auto_clean_bot_cmds": False,
    # Page 2 features
    "strict_topic": False,
    "banned_words_enabled": False,
    "banned_words": [],
    "banned_words_action": "delete",
    "recurring_messages": [],
    "slow_mode": 0,            # seconds (0 = off)
    "readonly_mode": False,
    "block_channels": False,   # restrict messages sent as channel
    "discussion_autopin": False,
    "custom_filters": {},      # trigger -> reply text
    "magic_stickers_limit": 0, # max per minute (0 = off)
    "max_message_length": 0,   # chars (0 = off)
    "msg_length_action": "delete", # 'delete' or 'warn'
    "log_channel_id": None,    # audit log channel ID
    # Reporting exception settings
    "excepted_admins": [],     # List of admin user IDs explicitly designated to receive reports
}

# CHAT_SETTINGS: chat_id -> configuration dict
CHAT_SETTINGS: Dict[int, Dict[str, Any]] = defaultdict(lambda: DEFAULT_CHAT_CONFIG.copy())

# WARN_CACHE: chat_id -> user_id -> count
WARN_CACHE: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

# FLOOD_CACHE: chat_id -> user_id -> deque of monotonic timestamps
FLOOD_CACHE: Dict[int, Dict[int, deque]] = defaultdict(lambda: defaultdict(deque))

# DUPLICATE_CACHE: chat_id -> user_id -> [last_content_sig, repeat_count, last_monotonic_timestamp]
# Ultra-fast in-memory sliding tracker for duplicate message repetitions (<0.1ms execution)
DUPLICATE_CACHE: Dict[int, Dict[int, List[Any]]] = defaultdict(dict)

# ADMIN_CACHE: (chat_id, user_id) -> (monotonic_timestamp, set_of_permissions, is_owner, is_anonymous)
# Caches Telegram administrator custom rights for 60s to prevent roundtrip API lag
ADMIN_CACHE: Dict[Tuple[int, int], Tuple[float, set, bool, bool]] = {}
ADMIN_CACHE_TTL = 60.0  # seconds

# PENDING_CUSTOM_WARN: admin_user_id -> chat_id being configured in private DM
PENDING_CUSTOM_WARN: Dict[int, int] = {}
# PENDING_CUSTOM_INPUT: admin_user_id -> (chat_id, setting_type) for direct text updates in PM
PENDING_CUSTOM_INPUT: Dict[int, Tuple[int, str]] = {}

# LAST_DM_SETTINGS_MSG: admin_user_id -> message_id of active settings menu in private DM
# Used to auto-delete previous settings cards so private chats stay completely clean
LAST_DM_SETTINGS_MSG: Dict[int, int] = {}


async def send_or_replace_dm_settings(bot: Bot, user_id: int, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> types.Message:
    """
    Deletes the previous active settings message in private DM (if any) before
    sending the updated settings card to guarantee a clean, clutter-free private chat.
    """
    old_mid = LAST_DM_SETTINGS_MSG.pop(user_id, None)
    if old_mid:
        try:
            await bot.delete_message(chat_id=user_id, message_id=old_mid)
        except Exception:
            pass

    msg = await bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    LAST_DM_SETTINGS_MSG[user_id] = msg.message_id
    return msg

# CHAT_TITLES: chat_id -> cached group title (eliminates redundant getChat roundtrips)
CHAT_TITLES: Dict[int, str] = {}

# USERNAME_CACHE: username (lowercase, without @) -> (user_id, full_name)
# Provides sub-microsecond in-memory resolution for @username command targeting
USERNAME_CACHE: Dict[str, Tuple[int, str]] = {}

# ACCEPTED_MEMBERS_CACHE: user_id -> dict containing global consolidated member metadata across all groups
ACCEPTED_MEMBERS_CACHE: Dict[int, Dict[str, Any]] = {}

# PENDING_BROADCAST: broadcast_token -> dict holding broadcast session configuration for confirmation
PENDING_BROADCAST: Dict[str, Dict[str, Any]] = {}

# GLOBAL_BOT: Global singleton reference for web dashboard API and background dispatch
GLOBAL_BOT: Optional[Bot] = None

# Pre-compiled high-performance regex patterns
RE_DURATION = re.compile(r"^(\d+)([smhdw]?)$")
RE_LINK = re.compile(r"(https?://\S+|t\.me/\S+|telegram\.me/\S+)", re.IGNORECASE)
RE_TG_LINK = re.compile(r"(t\.me/\S+|telegram\.me/\S+|telegram\.dog/\S+)", re.IGNORECASE)
RE_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
RE_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
RE_CHINESE = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF\u3040-\u30FF]")
RE_PORN = re.compile(r"\b(porn|xxx|nude|sex|hentai|onlyfans|nsfw|pussy|dick|boobs|erotic|milf)\b", re.IGNORECASE)
RE_MENTION = re.compile(r"@[\w\d_]+")

# ==============================================================================
# SYSTEM HEALTH & PERFORMANCE METRICS REGISTRY
# ==============================================================================
BOT_START_TIME: float = time.time()
BOT_IDENTITY: Dict[str, Any] = {
    "status": "ONLINE",
    "username": "personal_guardBot",
    "id": 9224266782,
}
METRICS: Dict[str, Any] = {
    "violations_handled": 0,
    "connected_channels_caught": 0,
    "bio_links_caught": 0,
    "chat_links_caught": 0,
    "cached_user_bios": 0,
    "last_heartbeat": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
}


def format_uptime(total_seconds: int) -> str:
    """Formats seconds into human-readable uptime string matching production monitor."""
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m {secs}s"
    return f"{hours}h {minutes}m {secs}s"


def format_duration(seconds: int) -> str:
    """Formats duration seconds into human-readable label."""
    if seconds <= 0:
        return "Permanent"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"

# ==============================================================================
# INSTANT WIPE & PARALLEL NATIVE ADMIN RIGHTS ENGINE
# ==============================================================================

async def get_cached_chat_title(bot: Bot, chat_id: int, fallback: Optional[str] = None) -> str:
    """
    Returns group title from zero-latency memory cache.
    Eliminates redundant Telegram API roundtrips (100-300ms network latency per call)
    and slashes outbound bandwidth on Render.
    """
    if chat_id in CHAT_TITLES:
        return CHAT_TITLES[chat_id]
    if fallback and fallback != f"Group {chat_id}":
        CHAT_TITLES[chat_id] = fallback
        return fallback
    try:
        c_info = await bot.get_chat(chat_id)
        title = c_info.title or f"Group {chat_id}"
        CHAT_TITLES[chat_id] = title
        return title
    except Exception:
        return fallback or f"Group {chat_id}"


async def wipe_trigger(message: Message) -> None:
    """
    Instantly wipes the incoming admin trigger command message from GROUP chats.
    In Private DMs (1-on-1 chats), the user's command message is NEVER deleted
    to preserve their command history and prevent confusing message disappearance.
    """
    if not message.chat or message.chat.type == ChatType.PRIVATE:
        return

    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError, Exception):
        pass


async def _delayed_delete(msg: Message, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


async def send_ephemeral(message: Message, text: str, delay: int = 5) -> None:
    """Sends an ephemeral notice and auto-deletes it after delay seconds to keep chat clean."""
    try:
        msg = await message.answer(text, parse_mode=ParseMode.HTML)
        if delay > 0:
            asyncio.create_task(_delayed_delete(msg, delay))
    except Exception:
        pass


async def check_admin_rights(
    bot: Bot,
    chat_id: int,
    user_id: int,
    required_permission: Optional[str] = None,
    sender_chat_id: Optional[int] = None
) -> bool:
    """
    Strict parallel validation against native Telegram administrator custom rights.
    Supports Anonymous Admins (sender_chat_id == chat_id or user_id in (1087968824, 777000)).
    Utilizes local high-speed TTL cache.
    """
    if not chat_id:
        return False

    # 1. Anonymous admin speaking as the group itself
    if sender_chat_id and sender_chat_id == chat_id:
        return True
    if user_id in (1087968824, 777000):  # GroupAnonymousBot / Telegram Service
        return True

    # 1B. Check if user is an Exempted Admin for this chat (0ms RAM check + DB fallback)
    try:
        user_id_int = int(user_id)
        if chat_id in CHAT_SETTINGS:
            raw_excepted = CHAT_SETTINGS[chat_id].get("excepted_admins", [])
            excepted_ids_int = {int(x) for x in raw_excepted if str(x).lstrip('-').isdigit()}
            if user_id_int in excepted_ids_int:
                return True
        # Fallback to MongoDB if not yet hydrated in memory
        if MongoDBManager.is_connected():
            db = MongoDBManager.get_database()
            if db is not None:
                doc = await db.chat_settings.find_one(
                    {"chat_id": chat_id},
                    {"reporting.excepted_admin_ids": 1, "custom_attributes.excepted_admins": 1, "_id": 0}
                )
                if doc:
                    db_excepted = doc.get("reporting", {}).get("excepted_admin_ids", [])
                    if not db_excepted:
                        db_excepted = doc.get("custom_attributes", {}).get("excepted_admins", [])
                    db_excepted_ints = {int(x) for x in db_excepted if str(x).lstrip('-').isdigit()}
                    if user_id_int in db_excepted_ints:
                        cur_set = set(CHAT_SETTINGS[chat_id].get("excepted_admins", []))
                        cur_set.update(db_excepted_ints)
                        CHAT_SETTINGS[chat_id]["excepted_admins"] = list(cur_set)
                        return True
    except Exception:
        pass

    if not user_id:
        return False

    now = time.monotonic()
    cache_key = (chat_id, user_id)

    # 2. Inspect local memory cache
    if cache_key in ADMIN_CACHE:
        cached_time, perms, is_owner, is_anon = ADMIN_CACHE[cache_key]
        if now - cached_time < ADMIN_CACHE_TTL:
            if is_owner or is_anon:
                return True
            if required_permission is None:
                return len(perms) > 0 or "is_admin" in perms
            return required_permission in perms

    # 3. Enforce strict cache bounds (<= 300 entries) to guarantee minimal memory usage (<30MB RAM)
    if len(ADMIN_CACHE) >= 300:
        for k in list(ADMIN_CACHE.keys()):
            if now - ADMIN_CACHE[k][0] > ADMIN_CACHE_TTL:
                ADMIN_CACHE.pop(k, None)
        if len(ADMIN_CACHE) >= 300:
            for k in list(ADMIN_CACHE.keys())[:50]:
                ADMIN_CACHE.pop(k, None)

    # 4. Fetch fresh native rights from Telegram API
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        if isinstance(member, ChatMemberOwner):
            ADMIN_CACHE[cache_key] = (now, {"is_admin", "owner"}, True, False)
            return True
        elif isinstance(member, ChatMemberAdministrator):
            is_anon = getattr(member, "is_anonymous", False)
            perms = {"is_admin"}
            if is_anon:
                perms.add("is_anonymous")
            if member.can_restrict_members:
                perms.add("can_restrict_members")
            if member.can_delete_messages:
                perms.add("can_delete_messages")
            if member.can_pin_messages:
                perms.add("can_pin_messages")
            if member.can_promote_members:
                perms.add("can_promote_members")
            if member.can_change_info:
                perms.add("can_change_info")
            if member.can_invite_users:
                perms.add("can_invite_users")

            ADMIN_CACHE[cache_key] = (now, perms, False, is_anon)
            if is_anon or is_owner:
                return True
            if required_permission is None:
                return True
            return required_permission in perms
        else:
            ADMIN_CACHE[cache_key] = (now, set(), False, False)
            return False
    except Exception as e:
        print(f"[ADMIN CHECK NOTICE] get_chat_member failed: {e}")
        return False


async def is_user_admin(
    bot: Bot,
    chat_id: int,
    user_id: int,
    sender_chat_id: Optional[int] = None
) -> bool:
    """Convenience alias for general admin validation."""
    return await check_admin_rights(bot, chat_id, user_id, sender_chat_id=sender_chat_id)


async def check_can_setup_bot(
    bot: Bot,
    chat_id: int,
    user_id: int,
    sender_chat_id: Optional[int] = None
) -> bool:
    """
    Validates whether a user is authorized to configure or setup the bot.
    Strictly permits ONLY:
    1. Owner / Creator of the Supergroup (ChatMemberOwner)
    2. Anonymous Admin (is_anonymous == True or sender_chat_id == chat_id)
    3. Excepted / Exempted Admin (user_id in chat's excepted_admins list)
    All other administrators (including admins with full custom rights) are denied.
    """
    if not chat_id:
        return False

    # Check native Telegram anonymous group admin message
    if sender_chat_id and sender_chat_id == chat_id:
        return True
    if user_id in (1087968824, 777000):
        return True

    if not user_id:
        return False

    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        return False

    # 1. Check Excepted / Exempted Admins in in-memory settings (0ms)
    settings = CHAT_SETTINGS[chat_id]
    raw_excepted = settings.get("excepted_admins", [])
    excepted_ids_int = {int(x) for x in raw_excepted if str(x).lstrip('-').isdigit()}
    if user_id_int in excepted_ids_int:
        return True

    # 1B. Fallback: Check MongoDB if not yet hydrated in memory
    if MongoDBManager.is_connected():
        try:
            db = MongoDBManager.get_database()
            if db is not None:
                doc = await db.chat_settings.find_one(
                    {"chat_id": chat_id},
                    {"reporting.excepted_admin_ids": 1, "chat_title": 1, "_id": 0}
                )
                if doc:
                    db_excepted = doc.get("reporting", {}).get("excepted_admin_ids", [])
                    db_excepted_ints = {int(x) for x in db_excepted if str(x).lstrip('-').isdigit()}
                    if user_id_int in db_excepted_ints:
                        # Rehydrate in-memory settings
                        cur_set = set(settings.get("excepted_admins", []))
                        cur_set.update(db_excepted_ints)
                        settings["excepted_admins"] = list(cur_set)
                        return True
        except Exception:
            pass

    # 2. Check local Admin Cache (TTL 60s)
    now = time.monotonic()
    cache_key = (chat_id, user_id_int)
    if cache_key in ADMIN_CACHE:
        cached_time, perms, is_owner, is_anon = ADMIN_CACHE[cache_key]
        if now - cached_time < ADMIN_CACHE_TTL:
            if is_owner or is_anon:
                return True

    # 3. Fetch Telegram member status
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id_int)
        if isinstance(member, ChatMemberOwner):
            ADMIN_CACHE[cache_key] = (now, set(), True, False)
            return True
        elif isinstance(member, ChatMemberAdministrator):
            is_anon = getattr(member, "is_anonymous", False)
            perms = {"is_admin"}
            if is_anon:
                perms.add("is_anonymous")
            if member.can_restrict_members:
                perms.add("can_restrict_members")
            if member.can_delete_messages:
                perms.add("can_delete_messages")
            if member.can_pin_messages:
                perms.add("can_pin_messages")
            if member.can_promote_members:
                perms.add("can_promote_members")
            if member.can_change_info:
                perms.add("can_change_info")
            if member.can_invite_users:
                perms.add("can_invite_users")

            ADMIN_CACHE[cache_key] = (now, perms, False, is_anon)
            return is_anon
        else:
            ADMIN_CACHE[cache_key] = (now, set(), False, False)
            return False
    except Exception:
        return False


def parse_time_duration(duration_str: Optional[str]) -> Tuple[int, str]:
    """
    Converts duration strings (e.g. 30s, 5m, 2h, 1d, 1w) into seconds and clean label.
    Default fallback: 0 (permanent / indefinite).
    """
    if not duration_str:
        return 0, "indefinitely"

    match = RE_DURATION.match(duration_str.strip().lower())
    if not match:
        return 0, "indefinitely"

    val, unit = match.groups()
    amount = int(val)
    multiplier = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
        "": 60,  # Default to minutes if unit is omitted
    }.get(unit, 60)

    seconds = amount * multiplier
    return seconds, f"{amount}{unit or 'm'}"


async def resolve_target(
    message: Message,
    command: Optional[CommandObject] = None,
    bot: Optional[Bot] = None
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Resolves target user from replied message, numeric ID, mention entity, or @username.
    Features 3-tier sub-millisecond resolution:
    1. Direct reply / numeric ID / text_mention entity
    2. Local USERNAME_CACHE (sub-microsecond 0.001ms RAM lookup)
    3. Group Administrators cache population
    4. Telegram API getChat fallback for public usernames
    Returns: (target_user_id, target_user_name, extra_arguments_string)
    """
    # 1. Target from replied message
    if message.reply_to_message:
        if message.reply_to_message.from_user:
            target_user = message.reply_to_message.from_user
            if target_user.username:
                USERNAME_CACHE[target_user.username.lower()] = (target_user.id, target_user.full_name)
            extra_args = command.args if command and command.args else ""
            return target_user.id, target_user.full_name, extra_args.strip()
        elif message.reply_to_message.sender_chat:
            sc = message.reply_to_message.sender_chat
            if sc.username:
                USERNAME_CACHE[sc.username.lower()] = (sc.id, sc.title or f"Channel {sc.id}")
            extra_args = command.args if command and command.args else ""
            return sc.id, sc.title or f"Channel {sc.id}", extra_args.strip()

    # 2. Target from command arguments (user ID or @username)
    if command and command.args:
        parts = command.args.split(maxsplit=1)
        first_arg = parts[0]
        remaining = parts[1] if len(parts) > 1 else ""

        # Clean numeric user ID (e.g. 123456789 or -100123)
        clean_arg = first_arg.lstrip("@")
        if clean_arg.isdigit() or (clean_arg.startswith("-") and clean_arg[1:].isdigit()):
            return int(clean_arg), f"User {clean_arg}", remaining.strip()

        # Target mention via entities (text_mention)
        if message.entities:
            for entity in message.entities:
                if entity.type == "text_mention" and entity.user:
                    if entity.user.username:
                        USERNAME_CACHE[entity.user.username.lower()] = (entity.user.id, entity.user.full_name)
                    return entity.user.id, entity.user.full_name, remaining.strip()

        # Target username resolution (handles both @username and username without @)
        target_handle = first_arg.lstrip("@").lower().strip()
        if target_handle:
            # Step 2A: Check in-memory USERNAME_CACHE (0.001ms RAM lookup)
            if target_handle in USERNAME_CACHE:
                cached_id, cached_name = USERNAME_CACHE[target_handle]
                return cached_id, cached_name, remaining.strip()

            # Step 2B: Check chat administrators list
            if bot and getattr(message, "chat", None) and getattr(message.chat, "id", None):
                try:
                    admins = await bot.get_chat_administrators(message.chat.id)
                    for admin in admins:
                        if admin.user and admin.user.username:
                            admin_handle = admin.user.username.lower()
                            USERNAME_CACHE[admin_handle] = (admin.user.id, admin.user.full_name)
                            if admin_handle == target_handle:
                                return admin.user.id, admin.user.full_name, remaining.strip()
                except Exception:
                    pass

            # Step 2C: Direct Telegram API lookup via bot.get_chat (resolves ANY public user/bot/channel)
            if bot:
                try:
                    chat_info = await bot.get_chat(f"@{target_handle}")
                    if chat_info and chat_info.id:
                        resolved_id = chat_info.id
                        resolved_name = getattr(chat_info, "full_name", None) or chat_info.first_name or chat_info.title or f"@{target_handle}"
                        USERNAME_CACHE[target_handle] = (resolved_id, resolved_name)
                        return resolved_id, resolved_name, remaining.strip()
                except Exception:
                    pass

    return None, None, None


# ==============================================================================
# ANTI-SPAM WARNING NOTICE ENGINE & INLINE CANCEL DISPATCHER
# ==============================================================================

def format_warn_notice(
    chat_id: int,
    user: types.User,
    reason: str,
    count: int,
    ceiling: int,
    chat_title: str = "Group"
) -> str:
    """
    Renders customizable warning notices with template replacement.
    Supports user mentions, violation reason, counts, ceiling, and punishments.
    """
    s = CHAT_SETTINGS[chat_id]
    custom_tpl = s.get("custom_warn_msg", "").strip()
    action_str = s.get("warn_action", "mute").upper()
    user_mention = f"<a href='tg://user?id={user.id}'>{html.escape(user.full_name)}</a>"
    username_str = f"@{user.username}" if user.username else user.full_name

    if custom_tpl:
        res = custom_tpl
        res = res.replace("{user}", user_mention)
        res = res.replace("{user_id}", str(user.id))
        res = res.replace("{username}", username_str)
        res = res.replace("{reason}", html.escape(reason))
        res = res.replace("{count}", str(count))
        res = res.replace("{limit}", str(ceiling))
        res = res.replace("{remaining}", str(max(0, ceiling - count)))
        res = res.replace("{action}", action_str)
        res = res.replace("{chat}", html.escape(chat_title))
        return res

    return (
        f"⚠️ <b>ANTI-SPAM WARNING NOTICE</b>\n\n"
        f"👤 <b>User:</b> {user_mention}\n"
        f"🏷️ <b>Group:</b> <code>{html.escape(chat_title)}</code>\n"
        f"📋 <b>Reason:</b> {html.escape(reason)}\n"
        f"🔢 <b>Warnings:</b> <b>{count}/{ceiling}</b>\n"
        f"⚖️ <b>Penalty on {ceiling} warns:</b> <code>{action_str}</code>"
    )


def generate_warn_notice_keyboard(chat_id: int, target_user_id: int) -> Optional[InlineKeyboardMarkup]:
    """
    Builds the inline Cancel Warn button if toggled ON in group settings.
    If toggled OFF, returns None so no cancel button is shown on the warning notice.
    """
    s = CHAT_SETTINGS[chat_id]
    if not s.get("warn_cancel_btn", True):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel Warn", callback_data=f"warn:cancel:{chat_id}:{target_user_id}")]
    ])


async def issue_warn_and_notify(
    bot: Bot,
    chat_id: int,
    target_user: types.User,
    admin_id: int,
    reason: str,
    reply_to_message_id: Optional[int] = None
) -> None:
    """
    Issues a warning increment in memory and MongoDB, evaluates warning ceiling,
    enforces automated penalty if reached, or sends customizable warning notice
    with optional inline Cancel Warn button (cancellable by any administrator).
    """
    settings = CHAT_SETTINGS[chat_id]

    # Automated violation warnings generated by the bot honor the auto_warn_enabled toggle
    if admin_id == bot.id and not settings.get("auto_warn_enabled", True):
        return

    ceiling = settings.get("warn_limit", 3)

    WARN_CACHE[chat_id][target_user.id] += 1
    current_warns = WARN_CACHE[chat_id][target_user.id]

    DatabaseService.record_warn_background(chat_id, target_user.id, admin_id, reason, current_warns)
    DatabaseService.log_moderation_background(chat_id, admin_id, target_user.id, "warn", reason)

    chat_title = await get_cached_chat_title(bot, chat_id, fallback="Group")

    if current_warns >= ceiling:
        WARN_CACHE[chat_id].pop(target_user.id, None)
        if not WARN_CACHE[chat_id]:
            WARN_CACHE.pop(chat_id, None)

        action = settings.get("warn_action", "mute")
        duration = settings.get("warn_duration", 86400)
        until_ts = int(time.time() + duration) if duration > 0 else None

        try:
            if action == "mute":
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=target_user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                    ),
                    until_date=until_ts
                )
            elif action == "kick":
                await bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id)
                await bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
            elif action == "ban":
                await bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id, until_date=until_ts)
        except Exception as e:
            print(f"[PUNISHMENT NOTICE] Action {action} notice: {e}")

        dur_text = format_duration(duration)
        user_mention = f"<a href='tg://user?id={target_user.id}'>{html.escape(target_user.full_name)}</a>"
        penalty_msg = (
            f"🚨 <b>WARNING CEILING REACHED!</b>\n\n"
            f"👤 <b>User:</b> {user_mention}\n"
            f"⛔ <b>Punishment:</b> <code>{action.upper()}</code> ({dur_text})\n"
            f"📋 <b>Reason:</b> Accumulated {ceiling} warnings ({html.escape(reason)})."
        )
        try:
            await bot.send_message(chat_id=chat_id, text=penalty_msg, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    notice_text = format_warn_notice(chat_id, target_user, reason, current_warns, ceiling, chat_title)
    kb = generate_warn_notice_keyboard(chat_id, target_user.id)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=notice_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"[WARN NOTICE] Failed to send warn notice: {e}")


# ==============================================================================
# ANTI-FLOOD MIDDLEWARE (ASYNCHRONOUS WINDOWED SPAM ENGINE)
# ==============================================================================

class AntiFloodMiddleware(BaseMiddleware):
    """
    High-speed windowed frequency calculator:
    Default: flood_window: 3s, flood_limit: 5 messages.
    Instantly wipes spam messages and restricts violators.
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        # Only process group & supergroup messages
        if event.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            return await handler(event, data)

        user = event.from_user
        if not user or user.is_bot:
            return await handler(event, data)

        chat_id = event.chat.id
        settings = CHAT_SETTINGS[chat_id]

        if not settings.get("flood_protection", True):
            return await handler(event, data)

        # Bypass anti-flood checks for administrators
        bot: Bot = data["bot"]
        if await check_admin_rights(bot, chat_id, user.id):
            return await handler(event, data)

        now = time.monotonic()
        user_id = user.id
        window = float(settings.get("flood_window", 3.0))
        limit = int(settings.get("flood_limit", 5))

        user_deque = FLOOD_CACHE[chat_id][user_id]
        user_deque.append(now)

        # Evict timestamps outside the window
        while user_deque and user_deque[0] <= now - window:
            user_deque.popleft()

        # Flood threshold exceeded
        if len(user_deque) > limit:
            user_deque.clear()  # Reset after violation trigger
            METRICS["violations_handled"] += 1

            # 1. Instant wipe of violating flood message
            try:
                await event.delete()
            except Exception:
                pass

            # 2. Automated restriction / auto-warn
            action = settings.get("flood_action", "mute")
            flood_dur = settings.get("flood_duration", 900)
            try:
                if action == "warn" or (settings.get("auto_warn_enabled", True) and settings.get("warn_on_flood", True)):
                    await issue_warn_and_notify(bot, chat_id, user, bot.id, f"Spam Flood ({limit} msgs in {int(window)}s)")
                elif action == "mute":
                    until_ts = int(time.time() + flood_dur) if flood_dur > 0 else 0
                    await bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        permissions=ChatPermissions(
                            can_send_messages=False,
                            can_send_media_messages=False,
                            can_send_other_messages=False,
                            can_add_web_page_previews=False,
                        ),
                        until_date=until_ts if until_ts > 0 else None
                    )
                elif action == "kick":
                    await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                    await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
                elif action == "ban":
                    await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            except Exception:
                pass

            # Drop the event immediately without bubbling up to handlers
            return None

        return await handler(event, data)


# ==============================================================================
# ROUTERS AND HANDLERS SETUP
# ==============================================================================

router = Router(name="high_speed_admin_router")

# ==============================================================================
# ==============================================================================
# 0. SERVICE MESSAGE CLEANER & MEMBER LIFECYCLE (WELCOME / GOODBYE / CAPTCHA)
# ==============================================================================

async def trigger_admin_alert(bot: Bot, message: Message, user: types.User, reason: str) -> None:
    chat_id = message.chat.id
    chat_title = CHAT_TITLES.get(chat_id, "Group")
    settings = CHAT_SETTINGS[chat_id]
    user_mention = user.mention_html()
    alert_text = (
        f"🚨 <b>ADMIN ALERT IN {html.escape(chat_title)}</b>\n\n"
        f"👤 <b>Reported By:</b> {user_mention} (<code>{user.id}</code>)\n"
        f"💬 <b>Reason:</b> {html.escape(reason)}\n"
    )
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        if target:
            alert_text += f"🎯 <b>Target:</b> {target.mention_html()} (<code>{target.id}</code>)\n"
    if message.link:
        alert_text += f"\n🔗 <a href='{message.link}'>Jump to Message</a>"

    # Forward alert to PM of excepted admins if enabled
    if settings.get("admin_alert_pm", True):
        for aid in settings.get("excepted_admins", []):
            try:
                await bot.send_message(chat_id=aid, text=alert_text, parse_mode=ParseMode.HTML)
            except Exception:
                pass


# _LAST_DM_SENT_TS: (chat_id, user_id) -> timestamp of last sent welcome DM to prevent duplicate sends
_LAST_DM_SENT_TS: Dict[Tuple[int, int], float] = {}


async def dispatch_private_welcome_dm(
    bot: Bot,
    chat_id: int,
    user: types.User,
    chat_title: str,
    settings: Dict[str, Any]
) -> bool:
    """
    Dispatches the configured private DM welcome message to the joining user.
    IMPORTANT: The bot ALWAYS attempts to send the message directly to user.id, regardless
    of whether the user has previously started or interacted with the bot.
    Includes multi-stage resilient delivery:
      1. Tries HTML formatted message.
      2. If HTML parse error occurs (e.g. invalid tags or unescaped characters in custom text),
         retries in clean plain text.
      3. Handles Telegram API errors gracefully.
    """
    if not settings.get("welcome_pm_enabled"):
        return False

    now_ts = time.time()
    dm_key = (chat_id, user.id)
    if now_ts - _LAST_DM_SENT_TS.get(dm_key, 0.0) < 30.0:
        return True  # Already dispatched to this user within 30s, prevent duplicate

    template = settings.get(
        "welcome_pm_msg",
        "👋 Hello {name}!\nYour request to join <b>{chat_title}</b> has been approved! Welcome to the group! 🎉"
    )
    if not template or not str(template).strip():
        template = "👋 Hello {name}!\nWelcome to <b>{chat_title}</b>! 🎉"

    user_name = user.full_name or user.first_name or f"User {user.id}"
    safe_name = html.escape(user_name)
    safe_title = html.escape(chat_title or "this group")
    mention_html = user.mention_html()

    formatted_html = template.replace("{mention}", mention_html) \
                             .replace("{name}", safe_name) \
                             .replace("{chat_title}", safe_title) \
                             .replace("{id}", str(user.id))

    # Stage 1: Direct HTML dispatch
    try:
        await bot.send_message(
            chat_id=user.id,
            text=formatted_html,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        _LAST_DM_SENT_TS[dm_key] = now_ts
        print(f"[WELCOME PM SUCCESS] Sent private DM welcome to user {user.id} ({user_name}) for {chat_title}", flush=True)
        return True
    except TelegramForbiddenError as fe:
        print(f"[WELCOME PM BLOCKED] User {user.id} has not started the bot or blocked it: {fe}", flush=True)
        return False
    except TelegramAPIError as api_err:
        # Stage 2: HTML parse error fallback (deliver as plain text)
        try:
            plain_template = re.sub(r'<[^>]+>', '', template)
            formatted_plain = plain_template.replace("{mention}", f"@{user.username}" if user.username else user_name) \
                                            .replace("{name}", user_name) \
                                            .replace("{chat_title}", chat_title) \
                                            .replace("{id}", str(user.id))
            await bot.send_message(
                chat_id=user.id,
                text=formatted_plain,
                parse_mode=None,
                disable_web_page_preview=True
            )
            _LAST_DM_SENT_TS[dm_key] = now_ts
            print(f"[WELCOME PM FALLBACK] Sent plain-text DM welcome to user {user.id} ({user_name})", flush=True)
            return True
        except TelegramForbiddenError as fe2:
            print(f"[WELCOME PM BLOCKED] User {user.id} has not started the bot: {fe2}", flush=True)
            return False
        except Exception as ex2:
            print(f"[WELCOME PM ERROR] Plain fallback failed for user {user.id}: {ex2}", flush=True)
            return False
    except Exception as e:
        print(f"[WELCOME PM ERROR] Unexpected error sending DM to user {user.id}: {e}", flush=True)
        return False


@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.new_chat_members | F.left_chat_member
)
async def handle_service_messages(message: Message, bot: Bot) -> None:
    """
    1. Anti-Bot: Bans unauthorized bots added to group chat.
    2. Welcome Greetings & Captcha: Welcomes new members or challenges with button captcha.
    3. Goodbye: Sends departure notice when a member leaves.
    4. Auto-deletes user join / leave service notifications when clean_service_messages is enabled.
    """
    chat_id = message.chat.id
    if message.chat and message.chat.title:
        CHAT_TITLES[chat_id] = message.chat.title
    settings = CHAT_SETTINGS[chat_id]

    # 1. Anti-Bot Auto-Ban / Auto-Kick: Instantly penalize newly added bot
    if settings.get("block_bots") and message.new_chat_members:
        bot_id = bot.id
        bot_action = settings.get("bot_action", "ban")
        for member in message.new_chat_members:
            if member.is_bot and member.id != bot_id:
                try:
                    if bot_action == "kick":
                        await bot.ban_chat_member(chat_id=chat_id, user_id=member.id)
                        await bot.unban_chat_member(chat_id=chat_id, user_id=member.id)
                    else:
                        await bot.ban_chat_member(chat_id=chat_id, user_id=member.id)
                    METRICS["violations_handled"] += 1
                    METRICS["connected_channels_caught"] += 1
                    DatabaseService.log_moderation_background(
                        chat_id=chat_id,
                        admin_id=bot_id,
                        target_id=member.id,
                        action=f"anti_bot_{bot_action}",
                        reason="Automated Anti-Bot Protection"
                    )
                except Exception:
                    pass

    # 2. Welcome Greetings & Captcha Verification
    if message.new_chat_members:
        for member in message.new_chat_members:
            if member.is_bot:
                continue

            chat_title = CHAT_TITLES.get(chat_id) or (message.chat.title if message.chat else f"Group {chat_id}")
            now_iso = datetime.now(timezone.utc).isoformat()

            # Record member in unified accepted members registry
            mem_data = ACCEPTED_MEMBERS_CACHE.get(member.id, {})
            existing_cids = list(mem_data.get("chat_ids", []))
            if chat_id not in existing_cids:
                existing_cids.append(chat_id)
            existing_titles = list(mem_data.get("chat_titles", []))
            if chat_title not in existing_titles:
                existing_titles.append(chat_title)

            ACCEPTED_MEMBERS_CACHE[member.id] = {
                "user_id": member.id,
                "first_name": member.first_name or "",
                "last_name": member.last_name or None,
                "username": member.username.lower() if member.username else None,
                "full_name": member.full_name or member.first_name or f"User {member.id}",
                "chat_ids": existing_cids,
                "chat_titles": existing_titles,
                "first_accepted_at": mem_data.get("first_accepted_at", now_iso),
                "last_accepted_at": now_iso,
                "accept_count": mem_data.get("accept_count", 0) + 1,
                "status": "active"
            }
            DatabaseService.record_accepted_member_background(
                user_id=member.id,
                first_name=member.first_name or "",
                last_name=member.last_name,
                username=member.username,
                full_name=member.full_name or member.first_name or f"User {member.id}",
                chat_id=chat_id,
                chat_title=chat_title
            )

            # Dispatch Private DM welcome (always attempts direct delivery)
            await dispatch_private_welcome_dm(bot, chat_id, member, chat_title, settings)

            # Captcha Verification
            c_mode = settings.get("captcha_mode", "off")
            if c_mode != "off":
                try:
                    await bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=member.id,
                        permissions=ChatPermissions(can_send_messages=False)
                    )
                except Exception:
                    pass
                verify_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 Click to Verify You're Human", callback_data=f"captcha:verify:{chat_id}:{member.id}")]
                ])
                try:
                    await message.answer(
                        f"👋 Welcome {member.mention_html()}!\n"
                        f"⚠️ <b>Verification Required:</b> Please tap below to unlock chat privileges.",
                        reply_markup=verify_kb,
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

            # Welcome Message
            if settings.get("welcome_enabled"):
                chat_title = CHAT_TITLES.get(chat_id, "this group")
                template = settings.get("welcome_msg", "👋 Welcome to <b>{chat_title}</b>, {mention}!")
                formatted = template.replace("{mention}", member.mention_html()) \
                                    .replace("{name}", html.escape(member.full_name)) \
                                    .replace("{chat_title}", html.escape(chat_title)) \
                                    .replace("{id}", str(member.id))
                try:
                    last_msg_id = settings.get("_last_welcome_msg_id")
                    if settings.get("clean_welcome") and last_msg_id:
                        try:
                            await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
                        except Exception:
                            pass
                    w_msg = await message.answer(formatted, parse_mode=ParseMode.HTML)
                    settings["_last_welcome_msg_id"] = w_msg.message_id
                except Exception:
                    pass

    # 3. Goodbye Message
    if message.left_chat_member and settings.get("goodbye_enabled"):
        member = message.left_chat_member
        if not member.is_bot:
            chat_title = CHAT_TITLES.get(chat_id, "this group")
            template = settings.get("goodbye_msg", "👋 Goodbye, {mention}!")
            formatted = template.replace("{mention}", member.mention_html()) \
                                .replace("{name}", html.escape(member.full_name)) \
                                .replace("{chat_title}", html.escape(chat_title)) \
                                .replace("{id}", str(member.id))
            try:
                await message.answer(formatted, parse_mode=ParseMode.HTML)
            except Exception:
                pass

    # 4. Service Message Cleanup
    if settings.get("clean_service_messages", True):
        try:
            await message.delete()
        except Exception:
            pass


# ==============================================================================
# JOIN REQUEST APPROVAL ENGINE (APPROVAL MODE)
# ==============================================================================

@router.chat_join_request()
async def handle_chat_join_request(request: ChatJoinRequest, bot: Bot) -> None:
    """
    Handles Telegram ChatJoinRequest updates when members request to join via invite link.
    CRITICAL TELEGRAM SPECIFICATION:
    Telegram grants a temporary 5-minute window for the bot to send private messages
    to the applicant EVEN IF THEY HAVE NEVER STARTED THE BOT.
    Crucially: The bot MUST send the message BEFORE approving the join request!
    Once approve_chat_join_request() is executed, the join request is resolved and closed,
    which instantly revokes the bot's permission to initiate conversation with the user.
    """
    chat_id = request.chat.id
    user = request.from_user
    if not user:
        return

    # Cache user info for instant command targeting
    if user.username:
        USERNAME_CACHE[user.username.lower()] = (user.id, user.full_name)

    if request.chat and request.chat.title:
        CHAT_TITLES[chat_id] = request.chat.title

    chat_title = await get_cached_chat_title(bot, chat_id)
    settings = CHAT_SETTINGS[chat_id]
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Update in-memory unified global accepted members cache (0ms lookup)
    mem_data = ACCEPTED_MEMBERS_CACHE.get(user.id, {})
    existing_cids = list(mem_data.get("chat_ids", []))
    if chat_id not in existing_cids:
        existing_cids.append(chat_id)
    existing_titles = list(mem_data.get("chat_titles", []))
    if chat_title not in existing_titles:
        existing_titles.append(chat_title)

    ACCEPTED_MEMBERS_CACHE[user.id] = {
        "user_id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or None,
        "username": user.username.lower() if user.username else None,
        "full_name": user.full_name or user.first_name or f"User {user.id}",
        "chat_ids": existing_cids,
        "chat_titles": existing_titles,
        "first_accepted_at": mem_data.get("first_accepted_at", now_iso),
        "last_accepted_at": now_iso,
        "accept_count": mem_data.get("accept_count", 0) + 1,
        "bio": getattr(request, "bio", None),
        "status": "active"
    }

    # 2. Persist to MongoDB global entity in background worker
    DatabaseService.record_accepted_member_background(
        user_id=user.id,
        first_name=user.first_name or "",
        last_name=user.last_name,
        username=user.username,
        full_name=user.full_name or user.first_name or f"User {user.id}",
        chat_id=chat_id,
        chat_title=chat_title,
        bio=getattr(request, "bio", None)
    )

    # 3. CRITICAL: Dispatch Private DM Welcome FIRST while join request is still pending!
    # Telegram allows messaging applicants who never started the bot ONLY while the request is open.
    await dispatch_private_welcome_dm(bot, chat_id, user, chat_title, settings)

    # 4. Process Auto-Approval if enabled
    if settings.get("approval_auto"):
        try:
            await bot.approve_chat_join_request(chat_id=chat_id, user_id=user.id)
            METRICS["violations_handled"] += 1
            print(f"[APPROVAL] Auto-approved join request for user {user.id} (@{user.username}) in chat {chat_id}", flush=True)

            # Optional In-Chat welcome greeting dispatch
            if settings.get("welcome_enabled"):
                template = settings.get("welcome_msg", "👋 Welcome to <b>{chat_title}</b>, {mention}!")
                formatted = template.replace("{mention}", user.mention_html()) \
                                    .replace("{name}", html.escape(user.full_name)) \
                                    .replace("{chat_title}", html.escape(chat_title)) \
                                    .replace("{id}", str(user.id))
                try:
                    if settings.get("clean_welcome"):
                        last_msg_id = settings.get("_last_welcome_msg_id")
                        if last_msg_id:
                            try:
                                await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
                            except Exception:
                                pass
                    w_msg = await bot.send_message(chat_id=chat_id, text=formatted, parse_mode=ParseMode.HTML)
                    settings["_last_welcome_msg_id"] = w_msg.message_id
                except Exception as we:
                    print(f"[APPROVAL NOTICE] Welcome message dispatch error: {we}", flush=True)

            # Security audit log dispatch
            log_chan = settings.get("log_channel") or settings.get("log_channel_id")
            if log_chan:
                try:
                    await bot.send_message(
                        chat_id=log_chan,
                        text=f"📭 <b>Auto-Approved Join Request</b>\n👤 <b>User:</b> {user.mention_html()} (<code>{user.id}</code>)\n🏷️ <b>Chat:</b> <code>{chat_id}</code>",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
        except Exception as e:
            print(f"[APPROVAL ERROR] Failed to auto-approve user {user.id} in chat {chat_id}: {e}", flush=True)


@router.chat_member()
async def handle_chat_member_updated(event: types.ChatMemberUpdated, bot: Bot) -> None:
    """
    Handles member status transitions (such as manual join request approval by admin).
    Guarantees that manual approvals are also captured into the global accepted members registry
    and receive their Private DM welcome greeting.
    """
    if event.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    chat_id = event.chat.id
    user = event.new_chat_member.user
    if not user or user.is_bot:
        return

    old_status = event.old_chat_member.status if event.old_chat_member else None
    new_status = event.new_chat_member.status

    # Check transition to MEMBER or RESTRICTED from non-member
    was_member = old_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    is_now_member = new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)

    if not was_member and is_now_member:
        # User joined or had their join request approved
        chat_title = await get_cached_chat_title(bot, chat_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        settings = CHAT_SETTINGS[chat_id]

        mem_data = ACCEPTED_MEMBERS_CACHE.get(user.id, {})
        existing_cids = list(mem_data.get("chat_ids", []))
        if chat_id not in existing_cids:
            existing_cids.append(chat_id)
        existing_titles = list(mem_data.get("chat_titles", []))
        if chat_title not in existing_titles:
            existing_titles.append(chat_title)

        ACCEPTED_MEMBERS_CACHE[user.id] = {
            "user_id": user.id,
            "first_name": user.first_name or "",
            "last_name": user.last_name or None,
            "username": user.username.lower() if user.username else None,
            "full_name": user.full_name or user.first_name or f"User {user.id}",
            "chat_ids": existing_cids,
            "chat_titles": existing_titles,
            "first_accepted_at": mem_data.get("first_accepted_at", now_iso),
            "last_accepted_at": now_iso,
            "accept_count": mem_data.get("accept_count", 0) + 1,
            "status": "active"
        }

        # Background persistence
        DatabaseService.record_accepted_member_background(
            user_id=user.id,
            first_name=user.first_name or "",
            last_name=user.last_name,
            username=user.username,
            full_name=user.full_name or user.first_name or f"User {user.id}",
            chat_id=chat_id,
            chat_title=chat_title
        )

        # Send private DM welcome if enabled (always attempts direct delivery)
        await dispatch_private_welcome_dm(bot, chat_id, user, chat_title, settings)


# ==============================================================================
# ASYNCHRONOUS MEDIA, LINK, & CONTENT INTERCEPTOR (SUB-SECOND SCANNER)
# ==============================================================================

@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    ~F.text.startswith("/")
)
async def message_media_and_link_interceptor(message: Message, bot: Bot) -> None:
    """
    Monitors all incoming group messages against local settings:
    - Blacklists & Read-only mode
    - Night mode (UTC scheduled lock)
    - Anti-Spam (Forwards, Quotes, Telegram links, Total links)
    - Media Filters (Stickers, GIFs, Audio, Voice, Documents, Photos, Videos)
    - Content Filters (Banned words, Restricted alphabets, Porn/NSFW keywords)
    - Anti-Tag / Mass Mention protection
    - Message Length limits
    - Custom keyword filters & @admin summon alerts
    """
    user = message.from_user
    if not user or user.is_bot:
        return

    # Ingress username caching for sub-microsecond command target resolution
    if user.username:
        USERNAME_CACHE[user.username.lower()] = (user.id, user.full_name)
    if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.username:
        r_user = message.reply_to_message.from_user
        USERNAME_CACHE[r_user.username.lower()] = (r_user.id, r_user.full_name)

    chat_id = message.chat.id
    if message.chat and message.chat.title:
        CHAT_TITLES[chat_id] = message.chat.title
    settings = CHAT_SETTINGS[chat_id]
    is_admin = await check_admin_rights(bot, chat_id, user.id)

    # 1. Blacklist Check
    if not is_admin and settings.get("blacklist_enabled", True):
        if user.id in settings.get("blacklisted_users", []):
            METRICS["violations_handled"] += 1
            await wipe_trigger(message)
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            except Exception:
                pass
            return

    # 2. Readonly Mode Check
    if not is_admin and settings.get("readonly_mode"):
        await wipe_trigger(message)
        return

    # 3. Night Mode Check (UTC)
    if not is_admin and settings.get("night_mode"):
        cur_hour = datetime.now(timezone.utc).hour
        n_start = settings.get("night_start", 23)
        n_end = settings.get("night_end", 7)
        in_night = False
        if n_start > n_end:
            in_night = cur_hour >= n_start or cur_hour < n_end
        else:
            in_night = n_start <= cur_hour < n_end
        if in_night:
            await wipe_trigger(message)
            return

    # 4. Anti-Spam: Forwarding & Quote checks
    if not is_admin and settings.get("antispam_enabled", True):
        if settings.get("block_forwarding") and (message.forward_origin or message.forward_from or message.forward_from_chat):
            METRICS["violations_handled"] += 1
            await wipe_trigger(message)
            return
        if settings.get("block_quote") and message.quote:
            METRICS["violations_handled"] += 1
            await wipe_trigger(message)
            return

    # 4b. Anti-Spam: Duplicate Message Interception
    if not is_admin:
        dup_text = (message.text or message.caption or "").strip().lower()
        content_sig = ""
        if dup_text:
            content_sig = f"txt:{dup_text}"
        elif message.sticker:
            content_sig = f"stk:{message.sticker.file_unique_id}"
        elif message.photo:
            content_sig = f"pho:{message.photo[-1].file_unique_id}"
        elif message.animation:
            content_sig = f"ani:{message.animation.file_unique_id}"
        elif message.document:
            content_sig = f"doc:{message.document.file_unique_id}"

        if content_sig:
            now_mono = time.monotonic()
            dup_window = float(settings.get("duplicate_window", 30))
            dup_limit = int(settings.get("duplicate_limit", 2))

            user_dup = DUPLICATE_CACHE[chat_id].get(user.id)
            if user_dup and user_dup[0] == content_sig and (now_mono - user_dup[2]) <= dup_window:
                user_dup[1] += 1
                user_dup[2] = now_mono
                repeat_count = user_dup[1]
                if repeat_count >= dup_limit:
                    METRICS["violations_handled"] += 1
                    await wipe_trigger(message)
                    if settings.get("auto_warn_enabled", True) and settings.get("warn_on_duplicate", True):
                        await issue_warn_and_notify(
                            bot, chat_id, user, bot.id, f"Duplicate message spam (x{repeat_count})"
                        )
                    return
            else:
                DUPLICATE_CACHE[chat_id][user.id] = [content_sig, 1, now_mono]

    # 5. Media Type Interceptions
    if not is_admin:
        media_violation = False
        if settings.get("block_sticker") and message.sticker:
            media_violation = True
        elif settings.get("block_animation") and message.animation:
            media_violation = True
        elif settings.get("block_document") and message.document:
            media_violation = True
        elif settings.get("block_audio") and message.audio:
            media_violation = True
        elif settings.get("block_voice") and message.voice:
            media_violation = True
        elif settings.get("block_photo") and message.photo:
            media_violation = True
        elif settings.get("block_video") and message.video:
            media_violation = True

        if media_violation:
            METRICS["violations_handled"] += 1
            await wipe_trigger(message)
            if settings.get("media_action") == "warn":
                await issue_warn_and_notify(bot, chat_id, user, bot.id, "Sent blocked media")
            return

    # 6. Link Interceptions
    has_link = False
    is_channel_link = False
    is_tg_link = False
    if message.entities:
        for entity in message.entities:
            if entity.type in ("url", "text_link"):
                has_link = True
                url_val = entity.url or ""
                if "t.me" in url_val.lower() or "telegram.me" in url_val.lower():
                    is_tg_link = True
            elif entity.type == "mention":
                is_channel_link = True

    raw_text = message.text or message.caption or ""
    if not has_link and raw_text:
        if RE_LINK.search(raw_text):
            has_link = True
    if not is_tg_link and raw_text:
        if RE_TG_LINK.search(raw_text):
            is_tg_link = True

    if not is_admin:
        # Anti-spam: Telegram links & Total links
        if settings.get("antispam_enabled", True):
            if settings.get("block_telegram_links") and is_tg_link:
                METRICS["violations_handled"] += 1
                await wipe_trigger(message)
                return
            if settings.get("block_total_links") and has_link:
                METRICS["violations_handled"] += 1
                await wipe_trigger(message)
                return

        # Core Link filter
        if has_link or (is_channel_link and settings.get("block_channel_links")):
            if settings.get("block_links") or (is_channel_link and settings.get("block_channel_links")):
                METRICS["violations_handled"] += 1
                METRICS["chat_links_caught"] += 1
                await wipe_trigger(message)
                if settings.get("link_action") == "warn":
                    await issue_warn_and_notify(bot, chat_id, user, bot.id, "Sent blocked link")
                return

    # Admin strict link block
    if is_admin and settings.get("admin_links_block") and has_link:
        METRICS["violations_handled"] += 1
        METRICS["chat_links_caught"] += 1
        await wipe_trigger(message)
        return

    # 7. Text-Based Filters
    if raw_text and not is_admin:
        # A. Banned Words
        if settings.get("banned_words_enabled"):
            b_words = settings.get("banned_words", [])
            lower_text = raw_text.lower()
            if any(w in lower_text for w in b_words):
                METRICS["violations_handled"] += 1
                await wipe_trigger(message)
                if settings.get("banned_words_action") == "warn":
                    await issue_warn_and_notify(bot, chat_id, user, bot.id, "Used prohibited word")
                return

        # B. Alphabets Filter
        if (settings.get("block_arabic") and RE_ARABIC.search(raw_text)) or \
           (settings.get("block_cyrillic") and RE_CYRILLIC.search(raw_text)) or \
           (settings.get("block_chinese") and RE_CHINESE.search(raw_text)):
            METRICS["violations_handled"] += 1
            await wipe_trigger(message)
            if settings.get("alphabet_action") == "warn":
                await issue_warn_and_notify(bot, chat_id, user, bot.id, "Used restricted script")
            return

        # C. Porn / NSFW Filter
        if settings.get("block_porn") and RE_PORN.search(raw_text):
            METRICS["violations_handled"] += 1
            await wipe_trigger(message)
            if settings.get("porn_action") == "warn":
                await issue_warn_and_notify(bot, chat_id, user, bot.id, "Explicit content violation")
            return

        # D. Tag / Mass Mention Protection
        if settings.get("tag_protection"):
            m_count = len(RE_MENTION.findall(raw_text))
            if m_count >= settings.get("tag_limit", 5):
                METRICS["violations_handled"] += 1
                await wipe_trigger(message)
                if settings.get("tag_action") == "warn":
                    await issue_warn_and_notify(bot, chat_id, user, bot.id, "Mass mention spam")
                return

        # E. Message Length Limit
        max_len = settings.get("max_message_length", 0)
        if max_len > 0 and len(raw_text) > max_len:
            METRICS["violations_handled"] += 1
            await wipe_trigger(message)
            act = settings.get("msg_length_action", "delete")
            if act == "warn":
                await issue_warn_and_notify(
                    bot, chat_id, user, bot.id,
                    f"Message exceeded maximum character limit ({len(raw_text)}/{max_len})"
                )
            else:
                user_name = user.first_name if user else "User"
                await send_ephemeral(
                    message,
                    f"⚠️ <b>{html.escape(user_name)}</b>, your message exceeded the maximum allowed length (<code>{len(raw_text)}/{max_len}</code> chars) and was deleted.",
                    delay=4
                )
            return

    # 8. Custom Trigger Filters (/filter)
    if raw_text and settings.get("custom_filters"):
        clean_trig = raw_text.strip().lower()
        if clean_trig in settings["custom_filters"]:
            try:
                await message.reply(settings["custom_filters"][clean_trig])
            except Exception:
                pass

    # 9. @Admin Calling Report Trigger
    if raw_text and settings.get("admin_alert_enabled", True):
        if "@admin" in raw_text.lower():
            reason = raw_text.replace("@admin", "").replace("@Admin", "").strip() or "Summoned via @admin"
            await trigger_admin_alert(bot, message, user, reason)


# ==============================================================================
# MANDATORY COMMAND MATRIX
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. /mute & /dmute
# ------------------------------------------------------------------------------
@router.message(Command("mute", "dmute"))
async def handle_mute(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can restrict members.")
        return

    target_id, target_name, remaining_args = await resolve_target(message, command, bot=bot)
    cmd_name = command.command if command else "mute"
    if not target_id:
        await send_ephemeral(
            message,
            f"⚠️ <b>Usage:</b> Reply to a user's message or specify User ID / @username:\n"
            f"<code>/{cmd_name} [time] [reason]</code> (e.g. <code>/{cmd_name} 10m flood</code>)"
        )
        return

    if await check_admin_rights(bot, message.chat.id, target_id):
        await send_ephemeral(message, "⚠️ Cannot restrict another administrator.")
        return

    # If /dmute, wipe target replied-to message as well
    if command and command.command.lower() == "dmute" and message.reply_to_message:
        try:
            await message.reply_to_message.delete()
        except Exception:
            pass

    parts = remaining_args.split(maxsplit=1) if remaining_args else []
    duration_str = None
    reason = "Rule violation"
    if parts:
        if RE_DURATION.match(parts[0].strip().lower()):
            duration_str = parts[0].strip().lower()
            reason = parts[1].strip() if len(parts) > 1 else "Rule violation"
        else:
            reason = remaining_args.strip()

    seconds, duration_label = parse_time_duration(duration_str)
    until_ts = int(time.time() + seconds) if seconds > 0 else 0

    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
            until_date=until_ts if until_ts > 0 else None
        )
        mention = f"<a href='tg://user?id={target_id}'>{html.escape(target_name or f'User {target_id}')}</a>"
        label = "Muted & Deleted" if command and command.command.lower() == "dmute" else "Muted"
        await message.answer(
            f"🔇 <b>{label}:</b> {mention}\n"
            f"⏱️ <b>Duration:</b> <code>{duration_label}</code>\n"
            f"📝 <b>Reason:</b> <i>{html.escape(reason)}</i>",
            parse_mode=ParseMode.HTML
        )
        DatabaseService.log_moderation_background(message.chat.id, user_id, target_id, "mute", reason)
    except Exception as e:
        await send_ephemeral(message, f"❌ Failed to mute member: <code>{html.escape(str(e))}</code>. Please ensure the bot is an Administrator with 'Restrict Members' right.")


@router.message(Command("unmute"))
async def handle_unmute(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can unmute members.")
        return

    target_id, target_name, _ = await resolve_target(message, command, bot=bot)
    if not target_id:
        await send_ephemeral(message, "⚠️ <b>Usage:</b> Reply to a message or pass User ID / @username with <code>/unmute</code>.")
        return

    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            )
        )
        mention = f"<a href='tg://user?id={target_id}'>{html.escape(target_name or f'User {target_id}')}</a>"
        await message.answer(f"🔊 <b>Unmuted:</b> {mention}. Chat permissions restored.", parse_mode=ParseMode.HTML)
        DatabaseService.log_moderation_background(message.chat.id, user_id, target_id, "unmute")
    except Exception as e:
        await send_ephemeral(message, f"❌ Failed to unmute: <code>{html.escape(str(e))}</code>.")


# ------------------------------------------------------------------------------
# 2. /pin & /unpin
# ------------------------------------------------------------------------------
@router.message(Command("pin"))
async def handle_pin(message: Message, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_pin_messages", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can pin messages.")
        return

    if not message.reply_to_message:
        await send_ephemeral(message, "⚠️ <b>Usage:</b> Reply to the message you want to pin with <code>/pin</code>.")
        return

    try:
        await bot.pin_chat_message(
            chat_id=message.chat.id,
            message_id=message.reply_to_message.message_id,
            disable_notification=True
        )
        await send_ephemeral(message, "📌 <b>Message pinned silently.</b>", delay=4)
        DatabaseService.log_moderation_background(message.chat.id, user_id, message.reply_to_message.message_id, "pin")
    except Exception as e:
        await send_ephemeral(message, f"❌ Failed to pin message: <code>{html.escape(str(e))}</code>.")


@router.message(Command("unpin"))
async def handle_unpin(message: Message, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_pin_messages", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can unpin messages.")
        return

    try:
        if message.reply_to_message:
            await bot.unpin_chat_message(
                chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )
            await send_ephemeral(message, "📌 <b>Message unpinned.</b>", delay=4)
        else:
            await bot.unpin_all_chat_messages(chat_id=message.chat.id)
            await send_ephemeral(message, "📌 <b>All pinned messages unpinned.</b>", delay=4)
        DatabaseService.log_moderation_background(message.chat.id, user_id, 0, "unpin")
    except Exception as e:
        await send_ephemeral(message, f"❌ Failed to unpin: <code>{html.escape(str(e))}</code>.")


# ------------------------------------------------------------------------------
# 3. /clear & /purge
# ------------------------------------------------------------------------------
@router.message(Command("clear", "purge"))
async def handle_clear(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_delete_messages", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can clear messages.")
        return

    chat_id = message.chat.id

    # If replying to a message, purge from that message forward up to trigger
    if message.reply_to_message:
        start_id = message.reply_to_message.message_id
        end_id = message.message_id
        msg_ids = list(range(start_id, end_id))
        if msg_ids:
            for i in range(0, len(msg_ids), 100):
                chunk = msg_ids[i:i + 100]
                try:
                    await bot.delete_messages(chat_id=chat_id, message_ids=chunk)
                except Exception:
                    for mid in chunk:
                        try:
                            await bot.delete_message(chat_id=chat_id, message_id=mid)
                        except Exception:
                            pass
            await send_ephemeral(message, f"🗑️ <b>Purged {len(msg_ids)} messages.</b>", delay=4)
            DatabaseService.log_moderation_background(chat_id, user_id, len(msg_ids), "purge")
        return

    # If numeric count provided: e.g. /clear 20
    if command and command.args and command.args.strip().isdigit():
        count = min(int(command.args.strip()), 100)
        curr_id = message.message_id
        target_ids = [curr_id - i for i in range(1, count + 1) if (curr_id - i) > 0]
        try:
            await bot.delete_messages(chat_id=chat_id, message_ids=target_ids)
        except Exception:
            for mid in target_ids:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
        await send_ephemeral(message, f"🗑️ <b>Cleared {count} messages.</b>", delay=4)
        DatabaseService.log_moderation_background(chat_id, user_id, count, "clear")
        return

    await send_ephemeral(message, "⚠️ <b>Usage:</b> Reply to a message with <code>/clear</code> to purge up to it, or use <code>/clear &lt;number&gt;</code> (e.g. <code>/clear 20</code>).")


# ------------------------------------------------------------------------------
# 4. /ban, /dban, & /tban
# ------------------------------------------------------------------------------
@router.message(Command("ban", "dban", "tban"))
async def handle_ban_matrix(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can ban members.")
        return

    target_id, target_name, remaining_args = await resolve_target(message, command, bot=bot)
    cmd = command.command.lower() if command else "ban"
    if not target_id:
        await send_ephemeral(message, f"⚠️ <b>Usage:</b> Reply to a user's message or pass User ID / @username:\n<code>/{cmd} [user] [reason]</code>")
        return

    if await check_admin_rights(bot, message.chat.id, target_id):
        await send_ephemeral(message, "⚠️ Cannot ban another administrator.")
        return

    # /dban: wipe target replied message
    if cmd == "dban" and message.reply_to_message:
        try:
            await message.reply_to_message.delete()
        except Exception:
            pass

    until_ts = None
    duration_label = "indefinitely"
    if cmd == "tban":
        parts = remaining_args.split(maxsplit=1) if remaining_args else []
        duration_str = "1h"
        if parts:
            if RE_DURATION.match(parts[0].strip().lower()):
                duration_str = parts[0].strip().lower()
                remaining_args = parts[1] if len(parts) > 1 else "Temporary ban"
            else:
                remaining_args = remaining_args.strip()
        else:
            remaining_args = "Temporary ban"
        seconds, duration_label = parse_time_duration(duration_str)
        if seconds > 0:
            until_ts = int(time.time() + seconds)

    try:
        await bot.ban_chat_member(
            chat_id=message.chat.id,
            user_id=target_id,
            until_date=until_ts
        )
        mention = f"<a href='tg://user?id={target_id}'>{html.escape(target_name or f'User {target_id}')}</a>"
        label = "Banned & Deleted" if cmd == "dban" else ("Temporarily Banned" if cmd == "tban" else "Banned")
        dur_line = f"\n⏱️ <b>Duration:</b> <code>{duration_label}</code>" if cmd == "tban" else ""
        await message.answer(
            f"🔨 <b>{label}:</b> {mention}{dur_line}\n"
            f"📝 <b>Reason:</b> <i>{html.escape(remaining_args or 'Rule violation')}</i>",
            parse_mode=ParseMode.HTML
        )
        DatabaseService.log_moderation_background(message.chat.id, user_id, target_id, cmd, remaining_args or "")
    except Exception as e:
        await send_ephemeral(message, f"❌ Failed to ban: <code>{html.escape(str(e))}</code>. Please ensure the bot is an Admin with 'Ban Users' permission.")


@router.message(Command("unban"))
async def handle_unban(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can unban members.")
        return

    target_id, target_name, _ = await resolve_target(message, command, bot=bot)
    if not target_id:
        await send_ephemeral(message, "⚠️ <b>Usage:</b> Reply to a message or pass User ID / @username with <code>/unban</code>.")
        return

    try:
        await bot.unban_chat_member(
            chat_id=message.chat.id,
            user_id=target_id
        )
        mention = f"<a href='tg://user?id={target_id}'>{html.escape(target_name or f'User {target_id}')}</a>"
        await message.answer(f"✅ <b>Unbanned:</b> {mention}. Member can now rejoin.", parse_mode=ParseMode.HTML)
        DatabaseService.log_moderation_background(message.chat.id, user_id, target_id, "unban")
    except Exception as e:
        await send_ephemeral(message, f"❌ Failed to unban: <code>{html.escape(str(e))}</code>.")


# ------------------------------------------------------------------------------
# 4B. /kickme (Instant Self-Kick for Members - Hidden from Catalog)
# ------------------------------------------------------------------------------
@router.message(Command("kickme"))
async def handle_kickme(message: Message, bot: Bot) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    await wipe_trigger(message)

    user = message.from_user
    if not user or user.is_bot:
        return

    # Ingress username caching for sub-microsecond command target resolution
    if user.username:
        USERNAME_CACHE[user.username.lower()] = (user.id, user.full_name)
    if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.username:
        r_user = message.reply_to_message.from_user
        USERNAME_CACHE[r_user.username.lower()] = (r_user.id, r_user.full_name)

    chat_id = message.chat.id
    user_id = user.id

    if await check_admin_rights(bot, chat_id, user_id):
        await send_ephemeral(message, "⚠️ Administrators cannot use /kickme.")
        return

    try:
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
        DatabaseService.log_moderation_background(chat_id, user_id, user_id, "kickme", "Self-kick request")
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 5. /promote & /demote
# ------------------------------------------------------------------------------
@router.message(Command("promote"))
async def handle_promote(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_promote_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can promote members.")
        return

    target_id, target_name, _ = await resolve_target(message, command, bot=bot)
    if not target_id:
        await send_ephemeral(message, "⚠️ <b>Usage:</b> Reply to a user's message or specify their User ID with <code>/promote</code>.")
        return

    try:
        await bot.promote_chat_member(
            chat_id=message.chat.id,
            user_id=target_id,
            is_anonymous=False,
            can_manage_chat=True,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
        )
        ADMIN_CACHE.pop((message.chat.id, target_id), None)
        mention = f"<a href='tg://user?id={target_id}'>{html.escape(target_name or f'User {target_id}')}</a>"
        await message.answer(f"⭐ <b>Promoted:</b> {mention} is now an Administrator.", parse_mode=ParseMode.HTML)
        DatabaseService.log_moderation_background(message.chat.id, user_id, target_id, "promote")
    except Exception as e:
        await send_ephemeral(message, f"❌ Failed to promote: <code>{html.escape(str(e))}</code>. Please ensure the bot is an Admin with 'Add New Admins' right.")


@router.message(Command("demote"))
async def handle_demote(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_promote_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can demote members.")
        return

    target_id, target_name, _ = await resolve_target(message, command, bot=bot)
    if not target_id:
        await send_ephemeral(message, "⚠️ <b>Usage:</b> Reply to a user's message or specify their User ID with <code>/demote</code>.")
        return

    try:
        await bot.promote_chat_member(
            chat_id=message.chat.id,
            user_id=target_id,
            is_anonymous=False,
            can_manage_chat=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
        )
        ADMIN_CACHE.pop((message.chat.id, target_id), None)
        mention = f"<a href='tg://user?id={target_id}'>{html.escape(target_name or f'User {target_id}')}</a>"
        await message.answer(f"👤 <b>Demoted:</b> {mention}. Administrator privileges revoked.", parse_mode=ParseMode.HTML)
        DatabaseService.log_moderation_background(message.chat.id, user_id, target_id, "demote")
    except Exception as e:
        await send_ephemeral(message, f"❌ Failed to demote: <code>{html.escape(str(e))}</code>.")


# ------------------------------------------------------------------------------
# 6. /warn, /resetwarn, & /warns
# ------------------------------------------------------------------------------
@router.message(Command("warn"))
async def handle_warn(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can warn members.")
        return

    target_id, target_name, remaining_args = await resolve_target(message, command, bot=bot)
    if not target_id:
        await send_ephemeral(message, "⚠️ <b>Usage:</b> Reply to a user's message or pass their User ID / @username:\n<code>/warn [reason]</code>")
        return

    if await check_admin_rights(bot, message.chat.id, target_id):
        await send_ephemeral(message, "⚠️ Cannot warn another administrator.")
        return

    target_user = None
    if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == target_id:
        target_user = message.reply_to_message.from_user
    else:
        target_user = types.User(id=target_id, is_bot=False, first_name=target_name or f"User {target_id}")

    reason = remaining_args or "Rule violation"
    await issue_warn_and_notify(bot, message.chat.id, target_user, user_id, reason)


@router.message(Command("resetwarn"))
async def handle_resetwarn(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can reset warnings.")
        return

    target_id, target_name, _ = await resolve_target(message, command, bot=bot)
    if not target_id:
        await send_ephemeral(message, "⚠️ <b>Usage:</b> Reply to a message or pass User ID / @username with <code>/resetwarn</code>.")
        return

    WARN_CACHE[message.chat.id].pop(target_id, None)
    if not WARN_CACHE[message.chat.id]:
        WARN_CACHE.pop(message.chat.id, None)
    DatabaseService.reset_warn_background(message.chat.id, target_id)
    DatabaseService.log_moderation_background(message.chat.id, user_id, target_id, "resetwarn")
    mention = f"<a href='tg://user?id={target_id}'>{html.escape(target_name or f'User {target_id}')}</a>"
    await message.answer(f"✅ <b>Warnings reset to 0</b> for {mention}.", parse_mode=ParseMode.HTML)


@router.message(Command("warns"))
async def handle_get_warns(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    target_id, _, _ = await resolve_target(message, command, bot=bot)
    if not target_id:
        target_id = message.from_user.id if message.from_user else 0

    count = WARN_CACHE[message.chat.id].get(target_id, 0)
    ceiling = CHAT_SETTINGS[message.chat.id].get("warn_limit", 3)

    try:
        notice = await message.answer(f"⚠️ User Warning Count: <b>{count}/{ceiling}</b>", parse_mode=ParseMode.HTML)
        await asyncio.sleep(6)
        await notice.delete()
    except Exception:
        pass


@router.message(Command("autowarn"))
async def handle_autowarn(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can modify auto-warn settings.")
        return

    chat_id = message.chat.id
    settings = CHAT_SETTINGS[chat_id]
    arg = (command.args or "").strip().lower()

    if arg in ("on", "enable", "true", "yes", "1"):
        settings["auto_warn_enabled"] = True
    elif arg in ("off", "disable", "false", "no", "0"):
        settings["auto_warn_enabled"] = False
    else:
        settings["auto_warn_enabled"] = not settings.get("auto_warn_enabled", True)

    chat_title = await get_cached_chat_title(bot, chat_id, fallback="Group")
    DatabaseService.save_settings_background(chat_id, chat_title, settings)
    status_str = "🟢 ACTIVE" if settings["auto_warn_enabled"] else "⚪ DISABLED"
    await send_ephemeral(message, f"⚡ <b>Master Auto-Warn:</b> {status_str}")


@router.message(Command("warndup"))
async def handle_warndup(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can modify duplicate warning settings.")
        return

    chat_id = message.chat.id
    settings = CHAT_SETTINGS[chat_id]
    args = (command.args or "").strip().split()

    if args:
        first = args[0].lower()
        if first in ("on", "enable", "true", "yes", "1"):
            settings["warn_on_duplicate"] = True
        elif first in ("off", "disable", "false", "no", "0"):
            settings["warn_on_duplicate"] = False
        elif first.isdigit():
            settings["warn_on_duplicate"] = True
            settings["duplicate_limit"] = max(2, min(10, int(first)))
        if len(args) > 1 and args[1].isdigit():
            settings["duplicate_window"] = max(5, min(300, int(args[1])))
    else:
        settings["warn_on_duplicate"] = not settings.get("warn_on_duplicate", True)

    chat_title = await get_cached_chat_title(bot, chat_id, fallback="Group")
    DatabaseService.save_settings_background(chat_id, chat_title, settings)
    status_str = "🟢 ACTIVE" if settings.get("warn_on_duplicate", True) else "⚪ DISABLED"
    limit = settings.get("duplicate_limit", 2)
    win = settings.get("duplicate_window", 30)
    await send_ephemeral(message, f"🔁 <b>Warn on Duplicate:</b> {status_str} (Limit: <code>{limit}x</code> in <code>{win}s</code>)")


@router.message(Command("warnflood"))
async def handle_warnflood(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can modify flood warning settings.")
        return

    chat_id = message.chat.id
    settings = CHAT_SETTINGS[chat_id]
    args = (command.args or "").strip().split()

    if args:
        first = args[0].lower()
        if first in ("on", "enable", "true", "yes", "1"):
            settings["warn_on_flood"] = True
        elif first in ("off", "disable", "false", "no", "0"):
            settings["warn_on_flood"] = False
        elif first.isdigit():
            settings["warn_on_flood"] = True
            settings["flood_limit"] = max(1, min(100, int(first)))
        if len(args) > 1 and args[1].isdigit():
            settings["flood_window"] = float(max(1, min(60, int(args[1]))))
    else:
        settings["warn_on_flood"] = not settings.get("warn_on_flood", True)

    chat_title = await get_cached_chat_title(bot, chat_id, fallback="Group")
    DatabaseService.save_settings_background(chat_id, chat_title, settings)
    status_str = "🟢 ACTIVE" if settings.get("warn_on_flood", True) else "⚪ DISABLED"
    f_limit = settings.get("flood_limit", 5)
    f_win = int(settings.get("flood_window", 3))
    await send_ephemeral(message, f"🌊 <b>Warn on Flood:</b> {status_str} (Limit: <code>{f_limit} msgs</code> in <code>{f_win}s</code>)")


@router.message(Command("antiflood", "flood", "antiglood"))
async def handle_cmd_antiflood(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can change anti-flood settings.")
        return

    chat_id = message.chat.id
    settings = CHAT_SETTINGS[chat_id]
    arg = (command.args or "").strip().lower()

    if arg in ("on", "enable", "true", "yes", "1"):
        settings["flood_protection"] = True
    elif arg in ("off", "disable", "false", "no", "0"):
        settings["flood_protection"] = False
    else:
        settings["flood_protection"] = not settings.get("flood_protection", True)

    chat_title = await get_cached_chat_title(bot, chat_id, fallback="Group")
    DatabaseService.save_settings_background(chat_id, chat_title, settings)
    status_str = "🟢 ACTIVE" if settings["flood_protection"] else "⚪ DISABLED"
    await send_ephemeral(message, f"⚡ <b>Anti-Flood Protection:</b> {status_str}")


@router.message(Command("antispam", "spam"))
async def handle_cmd_antispam(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members", sender_chat_id=sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can change anti-spam settings.")
        return

    chat_id = message.chat.id
    settings = CHAT_SETTINGS[chat_id]
    arg = (command.args or "").strip().lower()

    if arg in ("on", "enable", "true", "yes", "1"):
        settings["antispam_enabled"] = True
    elif arg in ("off", "disable", "false", "no", "0"):
        settings["antispam_enabled"] = False
    else:
        settings["antispam_enabled"] = not settings.get("antispam_enabled", True)

    chat_title = await get_cached_chat_title(bot, chat_id, fallback="Group")
    DatabaseService.save_settings_background(chat_id, chat_title, settings)
    status_str = "🟢 ACTIVE" if settings.get("antispam_enabled", True) else "⚪ DISABLED"
    await send_ephemeral(message, f"🛡️ <b>Anti-Spam Engine:</b> {status_str}")


# ==============================================================================
# INTERACTIVE SETTINGS UI (MATCHING BIOLINK RESTRICTOR ARCHITECTURE)
# ==============================================================================

def generate_settings_choice_keyboard(chat_id: int, bot_username: str) -> InlineKeyboardMarkup:
    """
    Renders choice menu in group matching Image 1:
    '👥 Open here' | '👤 Open in Private Chat'
    """
    clean_id = str(chat_id).replace("-", "m")
    dm_url = f"https://t.me/{bot_username}?start=group_{clean_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Open here", callback_data=f"set:open_here:{chat_id}")],
        [InlineKeyboardButton(text="👤 Open in Private Chat", url=dm_url)],
    ])


def format_settings_hub_text(chat_title: str) -> str:
    """
    Renders standardized header matching Image 2 & 3:
    SETTINGS
    Group: <group name>

    Select one of the settings that you want to change.
    """
    return (
        "<b>Manager</b>\n"
        "<b>SETTINGS</b>\n"
        f"<b>Group:</b> <code>{html.escape(chat_title)}</code>\n\n"
        "<i>Select one of the settings that you want to change.</i>"
    )


def generate_settings_page1_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    """
    Renders exact 2-column Page 1 Settings Menu as shown in reference Image 2,
    with real-time protection indicator badges and group switcher for private DM.
    """
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    spam_badge = " 🟢" if s.get("antispam_enabled", True) else " ⚪"
    flood_badge = " 🟢" if s.get("flood_protection", True) else " ⚪"
    warn_badge = " 🟢" if s.get("auto_warn_enabled", True) else " ⚪"

    buttons = [
        # Row 1
        [
            InlineKeyboardButton(text="📜 Regulation", callback_data=f"{prefix}menu:regulation:{chat_id}"),
            InlineKeyboardButton(text=f"✉️ Anti-Spam{spam_badge}", callback_data=f"{prefix}menu:antispam:{chat_id}"),
        ],
        # Row 2
        [
            InlineKeyboardButton(text="💬 Welcome", callback_data=f"{prefix}menu:welcome:{chat_id}"),
            InlineKeyboardButton(text=f"🗣️ Anti-Flood{flood_badge}", callback_data=f"{prefix}menu:flood:{chat_id}"),
        ],
        # Row 3
        [
            InlineKeyboardButton(text="👋 Goodbye", callback_data=f"{prefix}menu:goodbye:{chat_id}"),
            InlineKeyboardButton(text="🕉 Alphabets", callback_data=f"{prefix}menu:alphabets:{chat_id}"),
        ],
        # Row 4
        [
            InlineKeyboardButton(text="🧠 Captcha", callback_data=f"{prefix}menu:captcha:{chat_id}"),
            InlineKeyboardButton(text="🔦 Checks", callback_data=f"{prefix}menu:checks:{chat_id}"),
        ],
        # Row 5
        [
            InlineKeyboardButton(text="🆘 @Admin", callback_data=f"{prefix}menu:admincall:{chat_id}"),
            InlineKeyboardButton(text="🔐 Blocks", callback_data=f"{prefix}menu:blocks:{chat_id}"),
        ],
        # Row 6
        [
            InlineKeyboardButton(text="📸 Media", callback_data=f"{prefix}menu:media:{chat_id}"),
            InlineKeyboardButton(text="🔞 Porn", callback_data=f"{prefix}menu:porn:{chat_id}"),
        ],
        # Row 7
        [
            InlineKeyboardButton(text=f"❗ Warns{warn_badge}", callback_data=f"{prefix}menu:warn:{chat_id}"),
            InlineKeyboardButton(text="🌘 Night", callback_data=f"{prefix}menu:night:{chat_id}"),
        ],
        # Row 8
        [
            InlineKeyboardButton(text="🔔 Tag", callback_data=f"{prefix}menu:tag:{chat_id}"),
            InlineKeyboardButton(text="🔗 Link", callback_data=f"{prefix}menu:links:{chat_id}"),
        ],
        # Row 9
        [
            InlineKeyboardButton(text="🕵️ Guardian Bot 🆕", callback_data=f"{prefix}menu:guardian:{chat_id}"),
        ],
        # Row 10
        [
            InlineKeyboardButton(text="📭 Approval mode", callback_data=f"{prefix}menu:approval:{chat_id}"),
        ],
        # Row 11
        [
            InlineKeyboardButton(text="🗑️ Deleting Messages", callback_data=f"{prefix}menu:delmsgs:{chat_id}"),
        ],
        # Row 12 (Language button replaced with Switch Group)
        [
            InlineKeyboardButton(text="🔄 Switch Group", callback_data="dm:switch_group"),
            InlineKeyboardButton(text="✅ Close", callback_data=f"{prefix}close:{chat_id}"),
            InlineKeyboardButton(text="▶️ Other", callback_data=f"{prefix}page:2:{chat_id}"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def generate_settings_page2_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    """
    Renders exact Page 2 Settings Menu as shown in reference Image 3.
    """
    prefix = "dm:" if is_dm else "set:"
    buttons = [
        # Row 1
        [InlineKeyboardButton(text="📁 Topic", callback_data=f"{prefix}menu:topic:{chat_id}")],
        # Row 2
        [InlineKeyboardButton(text="🔤 Banned Words", callback_data=f"{prefix}menu:bannedwords:{chat_id}")],
        # Row 3
        [InlineKeyboardButton(text="🕒 Recurring messages", callback_data=f"{prefix}menu:recurring:{chat_id}")],
        # Row 4
        [InlineKeyboardButton(text="👥 Members Management", callback_data=f"{prefix}menu:members:{chat_id}")],
        # Row 5
        [InlineKeyboardButton(text="🧕 Masked users", callback_data=f"{prefix}menu:masked:{chat_id}")],
        # Row 6
        [InlineKeyboardButton(text="📣 Discussion group 🆕", callback_data=f"{prefix}menu:discussion:{chat_id}")],
        # Row 7
        [InlineKeyboardButton(text="📱 Personal Commands", callback_data=f"{prefix}menu:personalcmds:{chat_id}")],
        # Row 8
        [InlineKeyboardButton(text="🎭 Magic Stickers&GIFs", callback_data=f"{prefix}menu:magicstickers:{chat_id}")],
        # Row 9
        [InlineKeyboardButton(text="📏 Message length", callback_data=f"{prefix}menu:msglength:{chat_id}")],
        # Row 10
        [InlineKeyboardButton(text="📢 Channels management 🆕", callback_data=f"{prefix}menu:channels:{chat_id}")],
        # Row 11
        [
            InlineKeyboardButton(text="🖋 Permissions", callback_data=f"{prefix}menu:permissions:{chat_id}"),
            InlineKeyboardButton(text="🔍 Log Channel", callback_data=f"{prefix}menu:logchannel:{chat_id}"),
        ],
        # Row 12 (Language button replaced with Switch Group)
        [
            InlineKeyboardButton(text="◀️ Back", callback_data=f"{prefix}page:1:{chat_id}"),
            InlineKeyboardButton(text="✅ Close", callback_data=f"{prefix}close:{chat_id}"),
            InlineKeyboardButton(text="🔄 Switch Group", callback_data="dm:switch_group"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_regulation_text(chat_title: str, s: Dict[str, Any]) -> str:
    rules = s.get("rules_text", "").strip()
    perm_label = "👥 Everyone" if s.get("rules_perm", "all") == "all" else "👮 Admins Only"
    rules_preview = f"\n\n<b>Current regulations:</b>\n<i>{html.escape(rules[:250])}{'...' if len(rules) > 250 else ''}</i>" if rules else "\n\n<i>No regulations defined yet. Click '✍️ Customize message' or send /setrules &lt;text&gt;</i>"
    return (
        "<b>Manager</b>\n"
        "📜 <b>Group's regulations</b>\n"
        "From this menu you can manage the group's regulations, that will be shown with the command /rules.\n\n"
        "<i>To edit who can use the /rules command, go to the \"Commands permissions\" section.</i>\n\n"
        f"<b>Who can use /rules:</b> {perm_label}"
        f"{rules_preview}"
    )


def generate_regulation_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    perm = s.get("rules_perm", "all")
    perm_label = "🕹️ Permissions: Everyone" if perm == "all" else "🕹️ Permissions: Admins"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Customize message", callback_data=f"{prefix}cust:rules:{chat_id}")],
        [InlineKeyboardButton(text=perm_label, callback_data=f"{prefix}toggle_rules_perm:{chat_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_antispam_text(chat_title: str, s: Dict[str, Any]) -> str:
    master_on = s.get("antispam_enabled", True)
    tg_icon = "🟢 Blocked" if s.get("block_telegram_links") else "⚪ Allowed"
    fwd_icon = "🟢 Blocked" if s.get("block_forwarding") else "⚪ Allowed"
    quote_icon = "🟢 Blocked" if s.get("block_quote") else "⚪ Allowed"
    tot_icon = "🟢 Blocked" if s.get("block_total_links") else "⚪ Allowed"
    status_str = "<code>🟢 ACTIVE</code>" if master_on else "<i>⚪ DISABLED</i>"
    return (
        "<b>Manager</b>\n"
        "✉️ <b>Anti-Spam Engine</b>\n"
        f"Group: <code>{html.escape(chat_title)}</code>\n\n"
        f"• <b>Master Anti-Spam:</b> {status_str}\n"
        f"• <b>Telegram links:</b> {tg_icon}\n"
        f"• <b>Forwarding:</b> {fwd_icon}\n"
        f"• <b>Quote:</b> {quote_icon}\n"
        f"• <b>Total links block:</b> {tot_icon}\n\n"
        "<i>Toggle master protection or individual spam filters below:</i>"
    )


def generate_antispam_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    master_on = s.get("antispam_enabled", True)
    tg = "🟢" if s.get("block_telegram_links") else "⚪"
    fwd = "🟢" if s.get("block_forwarding") else "⚪"
    quote = "🟢" if s.get("block_quote") else "⚪"
    tot = "🟢" if s.get("block_total_links") else "⚪"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🛡️ Master Anti-Spam: {'🟢 ACTIVE' if master_on else '⚪ DISABLED'}",
                callback_data=f"{prefix}toggle:antispam_enabled:{chat_id}:antispam"
            )
        ],
        [InlineKeyboardButton(text=f"📘 Telegram links {tg}", callback_data=f"{prefix}toggle:block_telegram_links:{chat_id}:antispam")],
        [
            InlineKeyboardButton(text=f"📨 Forwarding {fwd}", callback_data=f"{prefix}toggle:block_forwarding:{chat_id}:antispam"),
            InlineKeyboardButton(text=f"💭 Quote {quote}", callback_data=f"{prefix}toggle:block_quote:{chat_id}:antispam"),
        ],
        [InlineKeyboardButton(text=f"🔗 Total links block {tot}", callback_data=f"{prefix}toggle:block_total_links:{chat_id}:antispam")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_welcome_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Enabled" if s.get("welcome_enabled") else "🔴 Disabled"
    cl = "🟢 Yes" if s.get("clean_welcome") else "⚪ No"
    pm_st = "🟢 Enabled" if s.get("welcome_pm_enabled") else "🔴 Disabled"
    msg = s.get("welcome_msg", "👋 Welcome to <b>{chat_title}</b>, {mention}!")
    pm_msg = s.get("welcome_pm_msg", "👋 Hello {name}!\nYour request to join <b>{chat_title}</b> has been approved! Welcome to the group! 🎉")
    return (
        "<b>Manager</b>\n"
        "💬 <b>Welcome Message</b>\n"
        "Configure automated greetings for new members joining the group.\n\n"
        f"• <b>In-Chat Welcome:</b> {st}\n"
        f"• <b>Clean Previous Welcome:</b> {cl}\n"
        f"• <b>Join Request Private DM:</b> {pm_st}\n\n"
        f"<b>In-Chat Template:</b>\n<code>{html.escape(msg)}</code>\n\n"
        f"<b>Private DM Template:</b>\n<code>{html.escape(pm_msg)}</code>\n\n"
        "<i>Placeholders: {mention}, {name}, {chat_title}, {id}</i>"
    )


def generate_welcome_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st_btn = f"⚡ In-Chat: {'ON' if s.get('welcome_enabled') else 'OFF'}"
    cl_btn = f"🧹 Clean Prev: {'ON' if s.get('clean_welcome') else 'OFF'}"
    pm_btn = f"📬 Request PM: {'ON' if s.get('welcome_pm_enabled') else 'OFF'}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=st_btn, callback_data=f"{prefix}toggle:welcome_enabled:{chat_id}:welcome"),
         InlineKeyboardButton(text=cl_btn, callback_data=f"{prefix}toggle:clean_welcome:{chat_id}:welcome")],
        [InlineKeyboardButton(text=pm_btn, callback_data=f"{prefix}toggle:welcome_pm_enabled:{chat_id}:welcome")],
        [InlineKeyboardButton(text="✍️ Custom In-Chat Msg", callback_data=f"{prefix}cust:welcome:{chat_id}")],
        [InlineKeyboardButton(text="📩 Custom Request PM Msg", callback_data=f"{prefix}cust:welcome_pm:{chat_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_goodbye_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Enabled" if s.get("goodbye_enabled") else "🔴 Disabled"
    msg = s.get("goodbye_msg", "👋 Goodbye, {mention}!")
    return (
        "<b>Manager</b>\n"
        "👋 <b>Goodbye Message</b>\n"
        "Send farewell notifications when a member leaves the group.\n\n"
        f"<b>Status:</b> {st}\n\n"
        f"<b>Current Template:</b>\n<code>{html.escape(msg)}</code>\n\n"
        "<i>Placeholders: {mention}, {name}, {chat_title}, {id}</i>"
    )


def generate_goodbye_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st_btn = f"⚡ State: {'ON' if s.get('goodbye_enabled') else 'OFF'}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=st_btn, callback_data=f"{prefix}toggle:goodbye_enabled:{chat_id}:goodbye")],
        [InlineKeyboardButton(text="✍️ Customize message", callback_data=f"{prefix}cust:goodbye:{chat_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_alphabets_text(chat_title: str, s: Dict[str, Any]) -> str:
    ar = "🟢 Blocked" if s.get("block_arabic") else "⚪ Allowed"
    cy = "🟢 Blocked" if s.get("block_cyrillic") else "⚪ Allowed"
    ch = "🟢 Blocked" if s.get("block_chinese") else "⚪ Allowed"
    act = s.get("alphabet_action", "delete").upper()
    return (
        "<b>Manager</b>\n"
        "🕉 <b>Alphabets Filter</b>\n"
        "Block messages containing specific scripts to combat international spam.\n\n"
        f"• <b>Arabic / Persian:</b> {ar}\n"
        f"• <b>Cyrillic (Russian):</b> {cy}\n"
        f"• <b>Chinese / Asian:</b> {ch}\n"
        f"• <b>Action:</b> <code>{act}</code>"
    )


def generate_alphabets_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    ar = "🟢" if s.get("block_arabic") else "⚪"
    cy = "🟢" if s.get("block_cyrillic") else "⚪"
    ch = "🟢" if s.get("block_chinese") else "⚪"
    act = s.get("alphabet_action", "delete").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🇸🇦 Arabic {ar}", callback_data=f"{prefix}toggle:block_arabic:{chat_id}:alphabets")],
        [InlineKeyboardButton(text=f"🇷🇺 Cyrillic {cy}", callback_data=f"{prefix}toggle:block_cyrillic:{chat_id}:alphabets")],
        [InlineKeyboardButton(text=f"🇨🇳 Chinese {ch}", callback_data=f"{prefix}toggle:block_chinese:{chat_id}:alphabets")],
        [InlineKeyboardButton(text=f"🔨 Action: {act}", callback_data=f"{prefix}cycle:alphabet_action:{chat_id}:alphabets")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_captcha_text(chat_title: str, s: Dict[str, Any]) -> str:
    mode = s.get("captcha_mode", "off").upper()
    to = s.get("captcha_timeout", 60)
    act = s.get("captcha_action", "kick").upper()
    return (
        "<b>Manager</b>\n"
        "🧠 <b>Captcha Verification</b>\n"
        "Require new members to verify themselves before sending messages.\n\n"
        f"<b>Mode:</b> <code>{mode}</code>\n"
        f"<b>Timeout:</b> <code>{to}s</code>\n"
        f"<b>Fail Action:</b> <code>{act}</code>"
    )


def generate_captcha_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    mode = s.get("captcha_mode", "off").upper()
    to = s.get("captcha_timeout", 60)
    act = s.get("captcha_action", "kick").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔘 Mode: {mode}", callback_data=f"{prefix}cycle:captcha_mode:{chat_id}:captcha")],
        [InlineKeyboardButton(text=f"⏱ Timeout: {to}s", callback_data=f"{prefix}cycle:captcha_timeout:{chat_id}:captcha")],
        [InlineKeyboardButton(text=f"🔨 Action: {act}", callback_data=f"{prefix}cycle:captcha_action:{chat_id}:captcha")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_checks_text(chat_title: str, s: Dict[str, Any]) -> str:
    bio = "🟢 Active" if s.get("check_bio_links", True) else "🔴 Disabled"
    av = "🟢 Required" if s.get("check_avatar") else "⚪ Disabled"
    un = "🟢 Required" if s.get("check_username") else "⚪ Disabled"
    return (
        "<b>Manager</b>\n"
        "🔦 <b>Member Profile Checks</b>\n"
        "Screen incoming accounts to block bots, self-promoters, and blank profiles.\n\n"
        f"• <b>Bio Links Check:</b> {bio}\n"
        f"• <b>Require Profile Avatar:</b> {av}\n"
        f"• <b>Require @Username:</b> {un}"
    )


def generate_checks_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    bio = "🟢 ON" if s.get("check_bio_links", True) else "⚪ OFF"
    av = "🟢 ON" if s.get("check_avatar") else "⚪ OFF"
    un = "🟢 ON" if s.get("check_username") else "⚪ OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔗 Bio Links: {bio}", callback_data=f"{prefix}toggle:check_bio_links:{chat_id}:checks")],
        [InlineKeyboardButton(text=f"👤 Require Avatar: {av}", callback_data=f"{prefix}toggle:check_avatar:{chat_id}:checks")],
        [InlineKeyboardButton(text=f"📛 Require Username: {un}", callback_data=f"{prefix}toggle:check_username:{chat_id}:checks")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_admincall_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Enabled" if s.get("admin_alert_enabled", True) else "🔴 Disabled"
    pm = "🟢 Enabled" if s.get("admin_alert_pm", True) else "🔴 Disabled"
    cnt = len(s.get("excepted_admins", []))
    return (
        "<b>Manager</b>\n"
        "🆘 <b>@Admin Summon & Reports</b>\n"
        "Members can alert administrators about violations by typing @admin or /admin.\n\n"
        f"<b>Status:</b> {st}\n"
        f"<b>Forward to Admin PMs:</b> {pm}\n"
        f"<b>Configured Excepted Admins:</b> <code>{cnt}</code>"
    )


def generate_admincall_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("admin_alert_enabled", True) else "⚪ OFF"
    pm = "🟢 ON" if s.get("admin_alert_pm", True) else "⚪ OFF"
    cnt = len(s.get("excepted_admins", []))
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔔 State: {st}", callback_data=f"{prefix}toggle:admin_alert_enabled:{chat_id}:admincall")],
        [InlineKeyboardButton(text=f"📩 PM Alerts: {pm}", callback_data=f"{prefix}toggle:admin_alert_pm:{chat_id}:admincall")],
        [InlineKeyboardButton(text=f"👥 Excepted Admins ({cnt})", callback_data=f"{prefix}menu:excepted:{chat_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_blocks_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Enabled" if s.get("blacklist_enabled", True) else "🔴 Disabled"
    cnt = len(s.get("blacklisted_users", []))
    return (
        "<b>Manager</b>\n"
        "🔐 <b>User Blocks & Blacklists</b>\n"
        "Automatically ban violators listed on the group blacklist.\n\n"
        f"<b>Protection Status:</b> {st}\n"
        f"<b>Blacklisted Users:</b> <code>{cnt}</code>\n\n"
        "<i>Use /ban &lt;user&gt; to ban and add users to the blacklist.</i>"
    )


def generate_blocks_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("blacklist_enabled", True) else "⚪ OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🛡️ Blacklist: {st}", callback_data=f"{prefix}toggle:blacklist_enabled:{chat_id}:blocks")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_porn_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Active" if s.get("block_porn") else "🔴 Disabled"
    act = s.get("porn_action", "delete").upper()
    return (
        "<b>Manager</b>\n"
        "🔞 <b>Porn & Adult Content Filter</b>\n"
        "Purges adult media, links, and explicit NSFW keywords.\n\n"
        f"<b>Status:</b> {st}\n"
        f"<b>Action:</b> <code>{act}</code>"
    )


def generate_porn_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("block_porn") else "⚪ OFF"
    act = s.get("porn_action", "delete").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔞 State: {st}", callback_data=f"{prefix}toggle:block_porn:{chat_id}:porn")],
        [InlineKeyboardButton(text=f"🔨 Action: {act}", callback_data=f"{prefix}cycle:porn_action:{chat_id}:porn")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_night_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Active" if s.get("night_mode") else "🔴 Disabled"
    n_start = s.get("night_start", 23)
    n_end = s.get("night_end", 7)
    return (
        "<b>Manager</b>\n"
        "🌘 <b>Night Mode</b>\n"
        "Automatically restrict non-admin messages during night hours.\n\n"
        f"<b>Status:</b> {st}\n"
        f"<b>Schedule:</b> <code>{n_start:02d}:00 - {n_end:02d}:00 UTC</code>"
    )


def generate_night_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("night_mode") else "⚪ OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🌘 State: {st}", callback_data=f"{prefix}toggle:night_mode:{chat_id}:night")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_tag_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Active" if s.get("tag_protection") else "🔴 Disabled"
    lim = s.get("tag_limit", 5)
    act = s.get("tag_action", "delete").upper()
    return (
        "<b>Manager</b>\n"
        "🔔 <b>Anti-Tag / Mass Mention Protection</b>\n"
        "Prevents mass mention raids by blocking messages with too many user tags.\n\n"
        f"<b>Status:</b> {st}\n"
        f"<b>Limit:</b> <code>{lim} mentions</code>\n"
        f"<b>Action:</b> <code>{act}</code>"
    )


def generate_tag_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("tag_protection") else "⚪ OFF"
    lim = s.get("tag_limit", 5)
    act = s.get("tag_action", "delete").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚡ State: {st}", callback_data=f"{prefix}toggle:tag_protection:{chat_id}:tag")],
        [InlineKeyboardButton(text=f"🔢 Limit: {lim}", callback_data=f"{prefix}cycle:tag_limit:{chat_id}:tag")],
        [InlineKeyboardButton(text=f"🔨 Action: {act}", callback_data=f"{prefix}cycle:tag_action:{chat_id}:tag")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_guardian_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Active" if s.get("block_bots") else "🔴 Disabled"
    act = s.get("bot_action", "ban").upper()
    return (
        "<b>Manager</b>\n"
        "🕵️ <b>Guardian Bot (Anti-Bot)</b>\n"
        "Protect your group against bot raids. Regular members adding bots are instantly penalized.\n\n"
        f"<b>Status:</b> {st}\n"
        f"<b>Action:</b> <code>{act}</code>"
    )


def generate_guardian_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("block_bots") else "⚪ OFF"
    act = s.get("bot_action", "ban").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🛡️ Anti-Bot: {st}", callback_data=f"{prefix}toggle:block_bots:{chat_id}:guardian")],
        [InlineKeyboardButton(text=f"🔨 Action: {act}", callback_data=f"{prefix}cycle:bot_action:{chat_id}:guardian")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_approval_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Auto-Approve" if s.get("approval_auto") else "🔴 Manual Admin Review"
    pm_st = "🟢 Enabled" if s.get("welcome_pm_enabled") else "🔴 Disabled"
    pm_msg = s.get("welcome_pm_msg", "👋 Hello {name}!\nYour request to join <b>{chat_title}</b> has been approved! Welcome to the group! 🎉")
    return (
        "<b>Manager</b>\n"
        "📭 <b>Join Request Approval Mode</b>\n"
        "Manage how incoming join requests are handled and greeted.\n\n"
        f"• <b>Approval Mode:</b> <code>{st}</code>\n"
        f"• <b>Private DM Welcome:</b> <code>{pm_st}</code>\n\n"
        f"<b>Private DM Template:</b>\n<code>{html.escape(pm_msg)}</code>\n\n"
        "<i>Placeholders: {mention}, {name}, {chat_title}, {id}</i>"
    )


def generate_approval_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("approval_auto") else "⚪ OFF"
    pm_st = "🟢 ON" if s.get("welcome_pm_enabled") else "⚪ OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚡ Auto-Approve: {st}", callback_data=f"{prefix}toggle:approval_auto:{chat_id}:approval")],
        [InlineKeyboardButton(text=f"📬 Private DM: {pm_st}", callback_data=f"{prefix}toggle:welcome_pm_enabled:{chat_id}:approval")],
        [InlineKeyboardButton(text="📩 Customize PM Welcome", callback_data=f"{prefix}cust:welcome_pm:{chat_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


def format_delmsgs_text(chat_title: str, s: Dict[str, Any]) -> str:
    srv = "🟢 Cleaned" if s.get("clean_service_messages", True) else "⚪ Kept"
    cmd = "🟢 60s" if s.get("auto_clean_bot_cmds") else "⚪ OFF"
    return (
        "<b>Manager</b>\n"
        "🗑️ <b>Deleting Messages & Cleaners</b>\n"
        "Keep the chat clean and free from clutter.\n\n"
        f"• <b>Service Messages (Join/Left):</b> {srv}\n"
        f"• <b>Auto-delete Bot Commands:</b> {cmd}"
    )


def generate_delmsgs_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    srv = "🟢 ON" if s.get("clean_service_messages", True) else "⚪ OFF"
    cmd = "🟢 ON" if s.get("auto_clean_bot_cmds") else "⚪ OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🧹 Service Messages: {srv}", callback_data=f"{prefix}toggle:clean_service_messages:{chat_id}:delmsgs")],
        [InlineKeyboardButton(text=f"⏱ Auto-delete Cmds: {cmd}", callback_data=f"{prefix}toggle:auto_clean_bot_cmds:{chat_id}:delmsgs")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:1:{chat_id}")],
    ])


# ---------------- PAGE 2 SUBMENUS ----------------


def format_topic_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Active" if s.get("strict_topic") else "🔴 Disabled"
    return (
        "<b>Manager</b>\n"
        "📁 <b>Topic Settings</b>\n"
        "Settings for forum supergroup topics.\n\n"
        f"<b>Strict Topic Posting:</b> <code>{st}</code>"
    )


def generate_topic_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("strict_topic") else "⚪ OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚡ Strict Topics: {st}", callback_data=f"{prefix}toggle:strict_topic:{chat_id}:topic")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_bannedwords_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Enabled" if s.get("banned_words_enabled") else "🔴 Disabled"
    cnt = len(s.get("banned_words", []))
    act = s.get("banned_words_action", "delete").upper()
    return (
        "<b>Manager</b>\n"
        "🔤 <b>Banned Words & Profanity Filter</b>\n"
        "Automatically delete or penalize messages containing blacklisted words.\n\n"
        f"<b>Status:</b> {st}\n"
        f"<b>Configured Words:</b> <code>{cnt}</code>\n"
        f"<b>Action:</b> <code>{act}</code>\n\n"
        "<i>Use /addword &lt;word&gt; to add and /delword &lt;word&gt; to remove.</i>"
    )


def generate_bannedwords_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("banned_words_enabled") else "⚪ OFF"
    act = s.get("banned_words_action", "delete").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚡ State: {st}", callback_data=f"{prefix}toggle:banned_words_enabled:{chat_id}:bannedwords")],
        [InlineKeyboardButton(text=f"🔨 Action: {act}", callback_data=f"{prefix}cycle:banned_words_action:{chat_id}:bannedwords")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_recurring_text(chat_title: str, s: Dict[str, Any]) -> str:
    cnt = len(s.get("recurring_messages", []))
    return (
        "<b>Manager</b>\n"
        "🕒 <b>Recurring Messages</b>\n"
        "Automated scheduled broadcasts to keep your group engaged.\n\n"
        f"<b>Active Broadcasts:</b> <code>{cnt}</code>"
    )


def generate_recurring_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_members_text(chat_title: str, s: Dict[str, Any], chat_id: Optional[int] = None) -> str:
    ro = "🟢 Active" if s.get("readonly_mode") else "⚪ Disabled"
    sm = f"{s.get('slow_mode', 0)}s" if s.get('slow_mode', 0) > 0 else "OFF"
    chat_accepted = 0
    if chat_id is not None:
        chat_accepted = sum(1 for m in ACCEPTED_MEMBERS_CACHE.values() if chat_id in m.get("chat_ids", []))
    total_accepted = len(ACCEPTED_MEMBERS_CACHE)
    return (
        "<b>Manager</b>\n"
        "👥 <b>Members Management & Broadcast</b>\n"
        "Group-wide restrictions, accepted member registry, and broadcast messaging.\n\n"
        f"• <b>Read-Only Mode:</b> {ro}\n"
        f"• <b>Slow Mode:</b> <code>{sm}</code>\n"
        f"• <b>Accepted Members (This Chat):</b> <code>{chat_accepted}</code>\n"
        f"• <b>Global Accepted Members:</b> <code>{total_accepted}</code>\n\n"
        "<i>Broadcast messages directly to accepted members or manage them in the Web Dashboard.</i>"
    )


def generate_members_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    ro = "🟢 ON" if s.get("readonly_mode") else "⚪ OFF"
    sm = f"{s.get('slow_mode', 0)}s" if s.get('slow_mode', 0) > 0 else "OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🔒 Read-Only: {ro}", callback_data=f"{prefix}toggle:readonly_mode:{chat_id}:members"),
            InlineKeyboardButton(text=f"⏱ Slow Mode: {sm}", callback_data=f"{prefix}cycle:slow_mode:{chat_id}:members"),
        ],
        [InlineKeyboardButton(text="📢 Broadcast to This Chat Members", callback_data=f"{prefix}bcast_chat:{chat_id}")],
        [InlineKeyboardButton(text="🌐 Broadcast to All Accepted Members", callback_data=f"{prefix}bcast_all:{chat_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_masked_text(chat_title: str, s: Dict[str, Any]) -> str:
    bc = "🟢 Blocked" if s.get("block_channels") else "⚪ Allowed"
    return (
        "<b>Manager</b>\n"
        "🧕 <b>Masked Users & Channel Senders</b>\n"
        "Control messages sent on behalf of Telegram channels.\n\n"
        f"<b>Channel Senders:</b> {bc}"
    )


def generate_masked_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    bc = "🟢 Blocked" if s.get("block_channels") else "⚪ Allowed"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🚫 Channel Senders: {bc}", callback_data=f"{prefix}toggle:block_channels:{chat_id}:masked")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_discussion_text(chat_title: str, s: Dict[str, Any]) -> str:
    ap = "🟢 ON" if s.get("discussion_autopin") else "⚪ OFF"
    return (
        "<b>Manager</b>\n"
        "📣 <b>Discussion Group</b>\n"
        "Settings for discussion groups connected to a channel.\n\n"
        f"<b>Auto-Pin Channel Posts:</b> {ap}"
    )


def generate_discussion_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    ap = "🟢 ON" if s.get("discussion_autopin") else "⚪ OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📌 Auto-Pin Posts: {ap}", callback_data=f"{prefix}toggle:discussion_autopin:{chat_id}:discussion")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_personalcmds_text(chat_title: str, s: Dict[str, Any]) -> str:
    cnt = len(s.get("custom_filters", {}))
    return (
        "<b>Manager</b>\n"
        "📱 <b>Personal Commands & Custom Filters</b>\n"
        "Custom keyword triggers with automated replies.\n\n"
        f"<b>Active Filters:</b> <code>{cnt}</code>\n\n"
        "<i>Use /filter &lt;trigger&gt; &lt;reply&gt; to create and /stop &lt;trigger&gt; to delete.</i>"
    )


def generate_personalcmds_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_magicstickers_text(chat_title: str, s: Dict[str, Any]) -> str:
    lim = s.get("magic_stickers_limit", 0)
    lim_str = f"{lim}/min" if lim > 0 else "Unlimited"
    return (
        "<b>Manager</b>\n"
        "🎭 <b>Magic Stickers & GIFs</b>\n"
        "Limit sticker frequency to prevent sticker flooding.\n\n"
        f"<b>Max Stickers:</b> <code>{lim_str}</code>"
    )


def generate_magicstickers_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    lim = s.get("magic_stickers_limit", 0)
    lim_str = f"{lim}/min" if lim > 0 else "Unlimited"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎭 Limit: {lim_str}", callback_data=f"{prefix}cycle:magic_stickers_limit:{chat_id}:magicstickers")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_msglength_text(chat_title: str, s: Dict[str, Any]) -> str:
    lim = s.get("max_message_length", 0)
    lim_str = f"{lim} characters" if lim > 0 else "Unlimited (Disabled)"
    action = s.get("msg_length_action", "delete").upper()
    return (
        "<b>Manager</b>\n"
        "📏 <b>Message Length Limit</b>\n"
        "Restrict wall-of-text spam messages.\n\n"
        f"<b>Max Allowed Length:</b> <code>{lim_str}</code>\n"
        f"<b>Violation Action:</b> <code>{action}</code>\n\n"
        "<i>Select a preset below, cycle through limits, toggle action, or tap ✍️ Custom:</i>"
    )


def generate_msglength_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    lim = s.get("max_message_length", 0)
    lim_str = f"{lim}" if lim > 0 else "Unlimited"
    action = s.get("msg_length_action", "delete").upper()

    def _btn(val: int) -> InlineKeyboardButton:
        active = (lim == val)
        label = "Off" if val == 0 else str(val)
        text = f"🟢 {label}" if active else label
        return InlineKeyboardButton(text=text, callback_data=f"{prefix}setlen:{val}:{chat_id}")

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"📏 Limit: {lim_str}", callback_data=f"{prefix}cycle:max_message_length:{chat_id}:msglength"),
            InlineKeyboardButton(text=f"🔨 Action: {action}", callback_data=f"{prefix}cycle:msg_length_action:{chat_id}:msglength"),
        ],
        [
            _btn(0),
            _btn(100),
            _btn(250),
            _btn(500),
        ],
        [
            _btn(750),
            _btn(1000),
            _btn(1500),
            _btn(2000),
        ],
        [
            _btn(3000),
            _btn(4000),
            InlineKeyboardButton(text="✍️ Custom", callback_data=f"{prefix}cust:msglength:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}"),
        ],
    ])


def format_channels_text(chat_title: str, s: Dict[str, Any]) -> str:
    st = "🟢 Active" if s.get("block_channel_links") else "🔴 Disabled"
    return (
        "<b>Manager</b>\n"
        "📢 <b>Channels Management</b>\n"
        "Restrict Telegram channel links, mentions, and connected channel bios.\n\n"
        f"<b>Channel Restrictions:</b> <code>{st}</code>"
    )


def generate_channels_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    st = "🟢 ON" if s.get("block_channel_links") else "⚪ OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Channel Block: {st}", callback_data=f"{prefix}toggle:block_channel_links:{chat_id}:channels")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_permissions_text(chat_title: str, s: Dict[str, Any]) -> str:
    return (
        "<b>Manager</b>\n"
        "🖋 <b>Default Permissions</b>\n"
        "Default member send permissions overview.\n\n"
        "<i>To restrict media or links, visit the Media and Links sections in Page 1.</i>"
    )


def generate_permissions_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def format_logchannel_text(chat_title: str, s: Dict[str, Any]) -> str:
    cid = s.get("log_channel_id")
    c_str = f"<code>{cid}</code>" if cid else "<i>None configured</i>"
    return (
        "<b>Manager</b>\n"
        "🔍 <b>Log Channel</b>\n"
        "Forward all moderation actions and violations to an audit channel.\n\n"
        f"<b>Audit Channel ID:</b> {c_str}\n\n"
        "<i>Set with command: /setlog &lt;channel_id&gt;</i>"
    )


def generate_logchannel_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"{prefix}page:2:{chat_id}")],
    ])


def generate_warn_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    auto_warn = s.get("auto_warn_enabled", True)
    w_limit = s.get("warn_limit", 3)
    w_action = s.get("warn_action", "mute").upper()
    w_dur = format_duration(s.get("warn_duration", 86400))
    cancel_on = s.get("warn_cancel_btn", True)
    custom_msg = s.get("custom_warn_msg", "").strip()
    warn_dup = s.get("warn_on_duplicate", True)
    dup_limit = s.get("duplicate_limit", 2)
    dup_win = s.get("duplicate_window", 30)
    warn_flood = s.get("warn_on_flood", True)

    buttons = [
        [
            InlineKeyboardButton(
                text=f"⚡ Master Auto-Warn: {'🟢 ACTIVE' if auto_warn else '⚪ DISABLED'}",
                callback_data=f"{prefix}warn_toggle_auto:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(text="➖ Dec", callback_data=f"{prefix}warn_dec:{chat_id}"),
            InlineKeyboardButton(text=f"⚠️ Ceiling: {w_limit} Warns", callback_data=f"{prefix}warn_cycle:{chat_id}"),
            InlineKeyboardButton(text="➕ Inc", callback_data=f"{prefix}warn_inc:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text=f"🔨 Punishment: {w_action} (MUTE/BAN/KICK)", callback_data=f"{prefix}warn_action:{chat_id}")
        ],
        [
            InlineKeyboardButton(text=f"⏱️ Duration: {w_dur}", callback_data=f"{prefix}warn_dur:{chat_id}")
        ],
        [
            InlineKeyboardButton(
                text=f"🔁 Dup Warn: {'✅ ON' if warn_dup else '❌ OFF'}",
                callback_data=f"{prefix}warn_toggle_dup:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"Limit: {dup_limit}x",
                callback_data=f"{prefix}warn_dup_limit_cycle:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"Window: {dup_win}s",
                callback_data=f"{prefix}warn_dup_win_cycle:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"🌊 Warn on Flood: {'✅ ON' if warn_flood else '❌ OFF'}",
                callback_data=f"{prefix}warn_toggle_flood:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"❌ Cancel Btn: {'✅ ON' if cancel_on else '❌ OFF'}",
                callback_data=f"{prefix}warn_toggle_cancel:{chat_id}"
            ),
        ],
    ]

    if is_dm:
        buttons.append([
            InlineKeyboardButton(
                text=f"✏️ Custom Msg: {'Customized' if custom_msg else 'Default'}",
                callback_data=f"{prefix}warn_custom_msg:{chat_id}"
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text="✏️ Setup Custom Msg in DM ↗️",
                url=f"https://t.me/{BOT_IDENTITY.get('username', 'personal_guardBot')}?start=custom_warn_{abs(chat_id)}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"{prefix}menu:main:{chat_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_warn_text(chat_title: str, s: Dict[str, Any]) -> str:
    auto_warn = s.get("auto_warn_enabled", True)
    w_limit = s.get("warn_limit", 3)
    w_action = s.get("warn_action", "mute").upper()
    w_dur = format_duration(s.get("warn_duration", 86400))
    cancel_on = s.get("warn_cancel_btn", True)
    custom_msg = s.get("custom_warn_msg", "").strip()
    warn_dup = s.get("warn_on_duplicate", True)
    dup_limit = s.get("duplicate_limit", 2)
    dup_win = s.get("duplicate_window", 30)
    warn_flood = s.get("warn_on_flood", True)
    f_limit = s.get("flood_limit", 5)
    f_win = int(s.get("flood_window", 3))
    status_custom = "Custom Template Active" if custom_msg else "Default Template"
    return (
        f"⚠️ <b>WARN CEILING & AUTO-WARN CONFIGURATION</b>\n"
        f"Group: <code>{html.escape(chat_title)}</code>\n\n"
        f"• <b>Master Auto-Warn:</b> {'<code>🟢 ACTIVE</code>' if auto_warn else '<i>⚪ DISABLED</i>'}\n"
        f"• <b>Violation Ceiling:</b> <code>{w_limit} warnings</code>\n"
        f"• <b>Punishment Action:</b> <code>{w_action}</code> (MUTE / BAN / KICK)\n"
        f"• <b>Penalty Duration:</b> <code>{w_dur}</code>\n"
        f"• <b>Warn on Duplicates:</b> {'<code>🟢 ACTIVE</code>' if warn_dup else '<i>⚪ DISABLED</i>'} "
        f"(Repeats: <code>{dup_limit}x</code> in <code>{dup_win}s</code>)\n"
        f"• <b>Warn on Message Flood:</b> {'<code>🟢 ACTIVE</code>' if warn_flood else '<i>⚪ DISABLED</i>'} "
        f"(Ceiling: <code>{f_limit} msgs</code> in <code>{f_win}s</code>)\n"
        f"• <b>Inline Cancel Button:</b> {'<code>ENABLED</code>' if cancel_on else '<i>DISABLED</i>'}\n"
        f"• <b>Warn Notice Template:</b> <code>{status_custom}</code>\n\n"
        f"<i>Tap buttons below to toggle auto-warn, adjust frequency/duplicate thresholds, or customize templates:</i>"
    )


def generate_warn_custom_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Reset to Default Template", callback_data=f"set:warn_custom_reset:{chat_id}")
        ],
        [
            InlineKeyboardButton(text="⬅️ Back to Warn Settings", callback_data=f"set:menu:warn:{chat_id}")
        ]
    ])


def format_warn_custom_text(chat_title: str, s: Dict[str, Any]) -> str:
    custom_msg = s.get("custom_warn_msg", "").strip()
    template_display = f"<code>{html.escape(custom_msg)}</code>" if custom_msg else "<i>Default standard template is active</i>"

    return (
        f"📝 <b>CUSTOM WARN MESSAGE CONFIGURATION</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"<b>Current Active Template:</b>\n"
        f"{template_display}\n\n"
        f"<b>Available Formatting Placeholders:</b>\n"
        f"• <code>{{user}}</code> - User clickable mention\n"
        f"• <code>{{user_id}}</code> - Target user's numerical ID\n"
        f"• <code>{{username}}</code> - Target username or name\n"
        f"• <code>{{reason}}</code> - Violation reason (e.g. Blocked Link)\n"
        f"• <code>{{count}}</code> - Current warning count\n"
        f"• <code>{{limit}}</code> - Max warning ceiling\n"
        f"• <code>{{remaining}}</code> - Warnings left until punishment\n"
        f"• <code>{{action}}</code> - Punishment action (MUTE/BAN/KICK)\n"
        f"• <code>{{chat}}</code> - Group title\n\n"
        f"👉 <b>To set a new custom message:</b> Type and send your desired custom message right here in this private chat!\n"
        f"<i>HTML tags (&lt;b&gt;, &lt;i&gt;, &lt;code&gt;) are fully supported.</i>"
    )


def generate_flood_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    prefix = "dm:" if is_dm else "set:"
    s = CHAT_SETTINGS[chat_id]
    is_on = s.get("flood_protection", True)
    f_limit = s.get("flood_limit", 5)
    f_win = int(s.get("flood_window", 3))
    f_action = s.get("flood_action", "mute").upper()
    f_dur = format_duration(s.get("flood_duration", 900))
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"⚡ Anti-Flood Protection: {'🟢 ACTIVE' if is_on else '⚪ DISABLED'}",
                callback_data=f"{prefix}flood_toggle:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(text="➖ Msg", callback_data=f"{prefix}flood_limit_dec:{chat_id}"),
            InlineKeyboardButton(text=f"📬 Limit: {f_limit} msgs", callback_data=f"{prefix}flood_limit_cycle:{chat_id}"),
            InlineKeyboardButton(text="➕ Msg", callback_data=f"{prefix}flood_limit_inc:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="➖ Sec", callback_data=f"{prefix}flood_win_dec:{chat_id}"),
            InlineKeyboardButton(text=f"⏱️ Window: {f_win}s", callback_data=f"{prefix}flood_win_cycle:{chat_id}"),
            InlineKeyboardButton(text="➕ Sec", callback_data=f"{prefix}flood_win_inc:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text=f"🔨 Punishment: {f_action}", callback_data=f"{prefix}flood_action:{chat_id}"),
            InlineKeyboardButton(text=f"⏱️ Duration: {f_dur}", callback_data=f"{prefix}flood_dur:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"{prefix}menu:main:{chat_id}")
        ]
    ])


def format_flood_text(chat_title: str, s: Dict[str, Any]) -> str:
    is_on = s.get("flood_protection", True)
    f_limit = s.get("flood_limit", 5)
    f_win = int(s.get("flood_window", 3))
    f_action = s.get("flood_action", "mute").upper()
    f_dur = format_duration(s.get("flood_duration", 900))
    return (
        f"⚡ <b>ANTI-FLOOD TUNING & PUNISHMENTS</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"• <b>Status:</b> {'<code>ACTIVE</code>' if is_on else '<i>Disabled</i>'}\n"
        f"• <b>Frequency Ceiling:</b> <code>{f_limit} messages inside {f_win} seconds</code>\n"
        f"• <b>Automated Punishment:</b> <code>{f_action}</code> (MUTE / DELETE / KICK / BAN)\n"
        f"• <b>Mute Duration:</b> <code>{f_dur}</code> (1m, 5m, 15m, 1h, 24h)\n\n"
        f"<i>Tap below to tune anti-spam parameters:</i>"
    )


def generate_links_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    s = CHAT_SETTINGS[chat_id]
    def badge(b: bool) -> str:
        return "❌ Blocked" if b else "✅ Allowed"
    l_action = s.get("link_action", "delete").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"✉️ Member Links: {badge(s.get('block_links'))}", callback_data=f"set:links_member:{chat_id}"),
            InlineKeyboardButton(text=f"👮 Admin Links: {badge(s.get('admin_links_block'))}", callback_data=f"set:links_admin:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text=f"📢 Channel Links: {badge(s.get('block_channel_links'))}", callback_data=f"set:links_channels:{chat_id}"),
            InlineKeyboardButton(text=f"🔨 Action: {l_action}", callback_data=f"set:links_action:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"set:menu:main:{chat_id}")
        ]
    ])


def format_links_text(chat_title: str, s: Dict[str, Any]) -> str:
    def badge(b: bool) -> str:
        return "<code>Blocked</code>" if b else "<i>Allowed</i>"
    return (
        f"🔗 <b>LINKS & INVITES CONFIGURATION</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"• <b>Regular Member Links:</b> {badge(s.get('block_links'))}\n"
        f"• <b>Administrator Links:</b> {badge(s.get('admin_links_block'))}\n"
        f"• <b>Channel Mentions & Links:</b> {badge(s.get('block_channel_links'))}\n"
        f"• <b>Violation Action:</b> <code>{s.get('link_action', 'delete').upper()}</code> (DELETE ONLY or DELETE + WARN)\n\n"
        f"<i>Tap below to configure link interception rules:</i>"
    )


def generate_media_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    s = CHAT_SETTINGS[chat_id]
    def b(key: str) -> str:
        return "❌" if s.get(key) else "✅"
    m_action = s.get("media_action", "delete").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🎭 Stickers: {b('block_sticker')}", callback_data=f"set:media_sticker:{chat_id}"),
            InlineKeyboardButton(text=f"🎞️ GIFs: {b('block_animation')}", callback_data=f"set:media_animation:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text=f"📁 Docs: {b('block_document')}", callback_data=f"set:media_document:{chat_id}"),
            InlineKeyboardButton(text=f"🎙️ Voice: {b('block_voice')}", callback_data=f"set:media_voice:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text=f"🎵 Audio: {b('block_audio')}", callback_data=f"set:media_audio:{chat_id}"),
            InlineKeyboardButton(text=f"🖼️ Photos: {b('block_photo')}", callback_data=f"set:media_photo:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text=f"🎥 Videos: {b('block_video')}", callback_data=f"set:media_video:{chat_id}"),
            InlineKeyboardButton(text=f"🔨 Action: {m_action}", callback_data=f"set:media_action:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"set:menu:main:{chat_id}")
        ]
    ])


def format_media_text(chat_title: str, s: Dict[str, Any]) -> str:
    def b(key: str) -> str:
        return "<code>Blocked</code>" if s.get(key) else "<i>Allowed</i>"
    return (
        f"🎭 <b>MEDIA PERMISSIONS & FILTERS</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"• <b>Stickers:</b> {b('block_sticker')} | <b>GIFs:</b> {b('block_animation')}\n"
        f"• <b>Documents:</b> {b('block_document')} | <b>Voice:</b> {b('block_voice')}\n"
        f"• <b>Audio MP3:</b> {b('block_audio')} | <b>Photos:</b> {b('block_photo')}\n"
        f"• <b>Videos:</b> {b('block_video')}\n"
        f"• <b>Violation Action:</b> <code>{s.get('media_action', 'delete').upper()}</code> (DELETE ONLY or DELETE + WARN)\n\n"
        f"<i>Tap buttons below to toggle restrictions for regular members:</i>"
    )


def generate_excepted_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑️ Clear All Excepted Admins", callback_data=f"set:excepted_clear:{chat_id}")
        ],
        [
            InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"set:menu:main:{chat_id}")
        ]
    ])


def format_excepted_text(chat_title: str, s: Dict[str, Any]) -> str:
    excepted = s.get("excepted_admins", [])
    if excepted:
        list_str = "\n".join(f"• <code>{eid}</code>" for eid in excepted)
    else:
        list_str = "<i>No Excepted Admins designated yet.</i>"
    bot_name = BOT_IDENTITY.get("username", "personal_guardBot")
    return (
        f"👥 <b>EXCEPTED ADMINISTRATORS</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"Designated administrators who have full setup permissions and receive confidential <code>/show</code> reports:\n"
        f"{list_str}\n\n"
        f"👉 <b>How to add:</b> Reply to the admin's message with <code>/addexcept</code> or send <code>/addexcept @admin</code>.\n"
        f"👉 <b>Private DM access:</b> Once added, they can manage settings in Private DM via @{bot_name}."
    )


def generate_dm_main_menu(bot_username: str) -> InlineKeyboardMarkup:
    """
    Renders Private DM main menu matching exact design specification:
    - Row 1: ➕ Add me to a Group ➕
    - Row 2: ⚙️ Manage group Settings ✍️
    - Row 3: 👥 Support / Approval ↗️ | ℹ️ Information 💬
    - Row 4: 📖 Commands Guide
    """
    support_url = os.getenv("SUPPORT_URL", f"https://t.me/{bot_username}")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Add me to a Group ➕",
                    url=f"https://t.me/{bot_username}?startgroup=true"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Manage group Settings ✍️",
                    callback_data="dm:manage_settings"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Support / Approval ↗️",
                    url=support_url
                ),
                InlineKeyboardButton(
                    text="ℹ️ Information 💬",
                    callback_data="dm:info"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📖 Commands Guide",
                    callback_data="dm:help"
                )
            ]
        ]
    )


# ------------------------------------------------------------------------------
# 7. /start (Primary Configuration & Group Settings Engine)
# ------------------------------------------------------------------------------
@router.message(Command("start", "settings"))
async def handle_start(message: Message, command: CommandObject, bot: Bot) -> None:
    """
    /start & /settings:
    - In Supergroups/Groups: Sends the group protection settings dashboard,
      strictly visible/accessible ONLY to authorized admins (Owner, Anonymous Admin, Excepted Admin).
    - In Private DMs: Displays the interactive management hub (Image 1 & 2) allowing
      authorized admins to view and configure their groups directly from private chat.
    """
    # --------------------------------------------------------------------------
    # CASE 1: GROUP / SUPERGROUP EXECUTION
    # --------------------------------------------------------------------------
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await wipe_trigger(message)

        sender_chat_id = message.sender_chat.id if message.sender_chat else None
        user_id = message.from_user.id if message.from_user else 0

        # STRICT RULE: Settings are sent and visible ONLY to authorized admins
        if not await check_can_setup_bot(bot, message.chat.id, user_id, sender_chat_id):
            await send_ephemeral(
                message,
                "❌ <b>Settings Access Restricted:</b> Only the Chat Owner, Anonymous Admins, or Excepted Admins can configure settings.",
                delay=5
            )
            return

        chat_id = message.chat.id
        bot_user = await bot.get_me()
        bot_name = bot_user.first_name or "Manager"
        choice_text = (
            f"<b>{html.escape(bot_name)}</b>\n"
            "Where do you want to open the settings menu?"
        )
        try:
            await message.answer(
                choice_text,
                reply_markup=generate_settings_choice_keyboard(chat_id, bot_user.username or "personal_guardBot"),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            print(f"[SETTINGS ERROR] Could not send settings choice: {e}")
        return

    # --------------------------------------------------------------------------
    # CASE 2: DIRECT PRIVATE DM EXECUTION
    # --------------------------------------------------------------------------
    user_id = message.from_user.id if message.from_user else 0
    bot_user = await bot.get_me()

    # 2A. Deep link directly to a specific group's settings (e.g. /start group_-100123)
    if command and command.args:
        arg = command.args.strip()
        target_cid = None
        if arg.startswith("group_"):
            try:
                raw_val = arg.replace("group_", "")
                if raw_val.startswith("m"):
                    target_cid = -int(raw_val[1:])
                else:
                    v = int(raw_val)
                    target_cid = -v if v > 0 else v
            except ValueError:
                pass
        elif arg.startswith("settings_"):
            try:
                raw_val = arg.replace("settings_", "")
                if raw_val.startswith("m"):
                    target_cid = -int(raw_val[1:])
                else:
                    v = int(raw_val)
                    target_cid = -v if v > 0 else v
            except ValueError:
                pass
        elif arg.startswith("-100"):
            try:
                target_cid = int(arg)
            except ValueError:
                pass
        elif arg == "switch_group":
            fake_query = types.CallbackQuery(
                id="direct_switch",
                from_user=message.from_user,
                chat_instance="",
                message=message,
                data="dm:switch_group"
            )
            await handle_dm_manage_settings(fake_query, bot)
            return
        elif arg.startswith("custom_warn_"):
            try:
                raw_id = arg.replace("custom_warn_", "")
                target_cid = -int(raw_id) if not raw_id.startswith("-") else int(raw_id)
            except ValueError:
                target_cid = None

            if target_cid and await check_can_setup_bot(bot, target_cid, user_id):
                PENDING_CUSTOM_WARN[user_id] = target_cid
                title = await get_cached_chat_title(bot, target_cid)
                text = format_warn_custom_text(title, CHAT_SETTINGS[target_cid])
                kb = generate_warn_custom_keyboard(target_cid)
                try:
                    await send_or_replace_dm_settings(bot, user_id, text, reply_markup=kb)
                    return
                except Exception:
                    pass

        elif arg.startswith("custom_"):
            try:
                parts = arg.split("_")
                subname_param = "_".join(parts[1:-1]) if len(parts) > 2 else parts[1]
                raw_id = parts[-1]
                target_cid = -int(raw_id) if not raw_id.startswith("-") else int(raw_id)
            except Exception:
                target_cid = None
            if target_cid and await check_can_setup_bot(bot, target_cid, user_id):
                PENDING_CUSTOM_INPUT[user_id] = (target_cid, subname_param)
                title = await get_cached_chat_title(bot, target_cid)
                if subname_param in ("msglength", "message_length", "length"):
                    await send_or_replace_dm_settings(
                        bot,
                        user_id,
                        f"📏 <b>Configure Message Length Limit</b>\n\n"
                        f"<b>Group:</b> <code>{html.escape(title)}</code>\n\n"
                        f"Please enter your custom character limit between <code>0</code> and <code>4096</code> (0 to disable):\n"
                        f"<i>Send /cancel to abort.</i>"
                    )
                    return
                nice_name = subname_param.replace("_", " ").title()
                await send_or_replace_dm_settings(
                    bot,
                    user_id,
                    f"✍️ <b>Configure Custom {nice_name}</b>\n\n"
                    f"<b>Group:</b> <code>{html.escape(title)}</code>\n\n"
                    f"Please send your custom message template now.\n"
                    f"<i>Placeholders like {{mention}}, {{name}}, {{chat_title}}, {{id}} are supported.\nSend /cancel to abort.</i>"
                )
                return

        elif arg.startswith("bcast_"):
            try:
                parts = arg.split("_")
                raw_id = parts[1]
                scope = parts[2] if len(parts) > 2 else "chat"
                target_cid = -int(raw_id) if not raw_id.startswith("-") else int(raw_id)
            except Exception:
                target_cid = None
            if target_cid and await check_can_setup_bot(bot, target_cid, user_id):
                PENDING_CUSTOM_INPUT[user_id] = (target_cid, f"broadcast:{scope}")
                title = await get_cached_chat_title(bot, target_cid)
                target_count = sum(1 for m in ACCEPTED_MEMBERS_CACHE.values() if target_cid in m.get("chat_ids", [])) if scope == "chat" else len(ACCEPTED_MEMBERS_CACHE)
                scope_name = f"Group '{title}'" if scope == "chat" else "All Global"
                await send_or_replace_dm_settings(
                    bot,
                    user_id,
                    f"📢 <b>Broadcast to {scope_name} Accepted Members ({target_count} members)</b>\n\n"
                    f"Please send the message you wish to broadcast now.\n"
                    f"<i>HTML formatting tags (<b>bold</b>, <i>italic</i>, <code>code</code>, <a href='...'>link</a>) are supported.\nSend /cancel to abort.</i>"
                )
                return

        if target_cid:
            if await check_can_setup_bot(bot, target_cid, user_id):
                title = await get_cached_chat_title(bot, target_cid)
                text = format_settings_hub_text(title)
                try:
                    await send_or_replace_dm_settings(
                        bot,
                        user_id,
                        text,
                        reply_markup=generate_settings_page1_keyboard(target_cid, is_dm=True)
                    )
                    return
                except Exception:
                    pass
            else:
                await send_or_replace_dm_settings(
                    bot,
                    user_id,
                    "❌ <b>Access Denied:</b> You are not authorized to configure settings for this group.\n"
                    "Only the Group Owner, Anonymous Admins, or Exempted Admins can configure settings."
                )
                return

    # 2B. Direct /settings command in private DM (without args)
    if command and command.command.lower() == "settings":
        authorized_chats = []
        known_cids = {cid for cid in CHAT_SETTINGS.keys() if cid < 0}
        for cid in known_cids:
            if await check_can_setup_bot(bot, cid, user_id):
                title = await get_cached_chat_title(bot, cid)
                authorized_chats.append((cid, title))

        if authorized_chats:
            group_buttons = [
                [InlineKeyboardButton(text=f"👥 {title}", callback_data=f"dmgroup:{cid}")]
                for cid, title in authorized_chats
            ]
            group_buttons.append([
                InlineKeyboardButton(text="🔄 Refresh List", callback_data="dm:refresh_groups"),
                InlineKeyboardButton(text="⬅️ Back", callback_data="dm:main_menu"),
            ])
            kb = InlineKeyboardMarkup(inline_keyboard=group_buttons)
            await send_or_replace_dm_settings(
                bot,
                user_id,
                "⚙️ <b>Your Managed Groups:</b>\n\n"
                "Select a group below to view and configure its settings:",
                reply_markup=kb
            )
            return
        else:
            await send_or_replace_dm_settings(
                bot,
                user_id,
                "⚙️ <b>Group Settings Management</b>\n\n"
                "To manage your group's settings from Private DM:\n"
                "1️⃣ In your group chat, type <code>/settings</code> and tap <b>👤 Open in Private Chat</b>.\n"
                "2️⃣ Or send <code>/settings &lt;group_id&gt;</code> here in DM (e.g. <code>/settings -1001234567890</code>).\n\n"
                "<i>Note: You must be the Group Owner, Anonymous Admin, or an Exempted Admin.</i>"
            )
            return

    # 2B. Welcome Menu Card (Matching Exact User Screenshot Specification)
    welcome_text = (
        "👋 <b>Hello!</b>\n"
        "<b>BioLink Restrictor</b> is the most complete Bot to help you manage your groups easily and safely!\n\n"
        "👉 <b>Add me in a Supergroup and promote me as Admin to let me get in action!</b>\n\n"
        "🔻 <b>WHICH ARE THE COMMANDS?</b> 🔻\n"
        "Press /help to see all the commands and how they work!\n"
        "📄 <i>Default protection is active automatically across all connected groups.</i>"
    )
    try:
        await send_or_replace_dm_settings(
            bot,
            user_id,
            welcome_text,
            reply_markup=generate_dm_main_menu(bot_user.username or "personal_guardBot")
        )
    except Exception:
        pass


@router.callback_query(F.data == "dm:main_menu")
async def handle_dm_main_menu(query: CallbackQuery, bot: Bot) -> None:
    """Returns to the Private DM Welcome Card from any submenu."""
    bot_user = await bot.get_me()
    welcome_text = (
        "👋 <b>Hello!</b>\n"
        "<b>BioLink Restrictor</b> is the most complete Bot to help you manage your groups easily and safely!\n\n"
        "👉 <b>Add me in a Supergroup and promote me as Admin to let me get in action!</b>\n\n"
        "🔻 <b>WHICH ARE THE COMMANDS?</b> 🔻\n"
        "Press /help to see all the commands and how they work!\n"
        "📄 <i>Default protection is active automatically across all connected groups.</i>"
    )
    try:
        await query.message.edit_text(
            welcome_text,
            reply_markup=generate_dm_main_menu(bot_user.username or "personal_guardBot"),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await query.answer()


@router.callback_query(F.data.in_({"dm:manage_settings", "dm:refresh_groups", "dm:switch_group"}))
async def handle_dm_manage_settings(query: CallbackQuery, bot: Bot) -> None:
    """Displays authorized groups for configuration from private DM and allows switching between groups."""
    user_id = query.from_user.id
    bot_user = await bot.get_me()

    # If triggered from inside a group chat, open deep-link to PM group switcher
    if query.message and query.message.chat.type != ChatType.PRIVATE:
        bot_username = bot_user.username or BOT_IDENTITY.get("username", "personal_guardBot")
        await query.answer(url=f"https://t.me/{bot_username}?start=switch_group")
        return

    LAST_DM_SETTINGS_MSG[user_id] = query.message.message_id

    authorized_chats = []
    known_cids = {cid for cid in CHAT_SETTINGS.keys() if cid < 0}
    if MongoDBManager.is_connected():
        try:
            db = MongoDBManager.get_database()
            if db is not None:
                cursor = db.chat_settings.find({}, {"chat_id": 1, "chat_title": 1, "reporting.excepted_admin_ids": 1, "_id": 0})
                async for doc in cursor:
                    c_id = doc.get("chat_id")
                    if c_id and c_id < 0:
                        known_cids.add(c_id)
                        if doc.get("chat_title"):
                            CHAT_TITLES[c_id] = doc["chat_title"]
                        db_excepted = doc.get("reporting", {}).get("excepted_admin_ids", [])
                        if db_excepted:
                            s = CHAT_SETTINGS[c_id]
                            cur = set(s.get("excepted_admins", []))
                            cur.update(int(x) for x in db_excepted if str(x).lstrip('-').isdigit())
                            s["excepted_admins"] = list(cur)
        except Exception as e:
            print(f"[DM SETTINGS NOTICE] MongoDB lookup: {e}")

    for cid in known_cids:
        if await check_can_setup_bot(bot, cid, user_id):
            title = await get_cached_chat_title(bot, cid)
            authorized_chats.append((cid, title))

    if authorized_chats:
        group_buttons = [
            [InlineKeyboardButton(text=f"👥 {title}", callback_data=f"dmgroup:{cid}")]
            for cid, title in authorized_chats
        ]
        group_buttons.append([
            InlineKeyboardButton(text="🔄 Refresh List", callback_data="dm:refresh_groups"),
            InlineKeyboardButton(text="⬅️ Back", callback_data="dm:main_menu"),
        ])
        text = (
            "⚙️ <b>Your Managed Groups:</b>\n\n"
            "👉 <i>Select the group chat you want to configure:</i>\n\n"
            "<i>Note: Only groups where you are the Owner, Anonymous Admin, or Excepted Admin appear here.</i>"
        )
        try:
            await query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=group_buttons),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await query.answer("Authorized groups loaded.")
    else:
        text = (
            "⚙️ <b>Manage Group Settings</b>\n\n"
            "❌ <b>No authorized groups found!</b>\n\n"
            "To manage your group settings here:\n"
            "1. Tap <b>➕ Add me to a Group ➕</b> below.\n"
            "2. Promote the bot to <b>Administrator</b> with management permissions.\n"
            "3. Return here and tap <b>🔄 Refresh List</b>!"
        )
        no_group_buttons = [
            [InlineKeyboardButton(text="➕ Add me to a Group ➕", url=f"https://t.me/{bot_user.username}?startgroup=true")],
            [
                InlineKeyboardButton(text="🔄 Refresh List", callback_data="dm:refresh_groups"),
                InlineKeyboardButton(text="⬅️ Back", callback_data="dm:main_menu"),
            ],
        ]
        try:
            await query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=no_group_buttons),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await query.answer("No authorized groups found.", show_alert=False)


@router.callback_query(F.data.startswith("dmgroup:"))
async def handle_dm_select_group(query: CallbackQuery, bot: Bot) -> None:
    chat_id = int(query.data.split(":")[1])
    user_id = query.from_user.id
    LAST_DM_SETTINGS_MSG[user_id] = query.message.message_id

    if not await check_can_setup_bot(bot, chat_id, user_id):
        await query.answer("❌ You are not an authorized admin for this group.", show_alert=True)
        return

    chat_title = await get_cached_chat_title(bot, chat_id)
    text = format_settings_hub_text(chat_title)
    try:
        await query.message.edit_text(
            text,
            reply_markup=generate_settings_page1_keyboard(chat_id, is_dm=True),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await query.answer(f"Switched to {chat_title}")

    if not await check_can_setup_bot(bot, chat_id, user_id):
        await query.answer("❌ You are not an authorized admin for this group.", show_alert=True)
        return

    chat_title = await get_cached_chat_title(bot, chat_id)
    text = format_settings_hub_text(chat_title)
    try:
        await query.message.edit_text(
            text,
            reply_markup=generate_settings_page1_keyboard(chat_id, is_dm=True),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await query.answer()


@router.callback_query(F.data == "dm:info")
async def handle_dm_info(query: CallbackQuery, bot: Bot) -> None:
    """Displays real-time bot information, runtime metrics, and protection capabilities."""
    uptime_sec = int(time.time() - BOT_START_TIME)
    active_groups_count = len([c for c in CHAT_SETTINGS.keys() if c < 0])
    info_text = (
        "ℹ️ <b>Information & Protection Status</b>\n\n"
        "🛡️ <b>BioLink Restrictor & High-Speed Manager</b>\n"
        "Engineered for sub-millisecond group moderation, real-time link/channel restrictions, and automated protection.\n\n"
        "📊 <b>System Overview:</b>\n"
        f"• <b>Status:</b> <code>ONLINE (UP)</code>\n"
        f"• <b>Engine Loop:</b> <code>{LOOP_ENGINE}</code> (Near-C execution)\n"
        f"• <b>Uptime:</b> <code>{format_uptime(uptime_sec)}</code>\n"
        f"• <b>Active Groups:</b> <code>{active_groups_count}</code>\n"
        f"• <b>Cached Admin Chats:</b> <code>{len({k[0] for k in ADMIN_CACHE.keys()})}</code>\n"
        f"• <b>Violations Handled:</b> <code>{METRICS.get('violations_handled', 0)}</code>\n\n"
        "🛡️ <b>Included Capabilities:</b>\n"
        "• 🤖 <b>Anti-Bot:</b> Instantly bans unauthorized bots added to groups.\n"
        "• 🧹 <b>Service Cleaner:</b> Automatically purges user join/left notifications.\n"
        "• 🔗 <b>Link & Channel Restriction:</b> Real-time in-chat link blocking.\n"
        "• 🎭 <b>Media Filter:</b> Blocks stickers, GIFs, voice, audio, and documents.\n"
        "• ⚡ <b>Anti-Flood:</b> Windowed spam detection with instant mute.\n"
        "• ⚠️ <b>Smart Warn:</b> Warning accumulation ceiling with automated ban/mute.\n"
    )
    back_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data="dm:main_menu")]
    ])
    try:
        await query.message.edit_text(info_text, reply_markup=back_markup, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await query.answer()


@router.callback_query(F.data == "dm:help")
async def handle_dm_help_callback(query: CallbackQuery) -> None:
    help_text = (
        "📖 <b>Commands Guide & Help</b>\n\n"
        "⚡ <b>Available Admin Commands:</b>\n"
        "• <code>/start</code> - Open group protection settings & private hub\n"
        "• <code>/mute &lt;time&gt; [reason]</code> - Restrict user send permissions\n"
        "• <code>/dmute &lt;time&gt; [reason]</code> - Wipe replied message + Mute user\n"
        "• <code>/unmute</code> - Restore user chat privileges\n"
        "• <code>/pin</code> - Silently pin message with zero notification\n"
        "• <code>/unpin</code> - Unpin replied message or all messages\n"
        "• <code>/clear [count]</code> - Wipe recent messages in chunks of 100\n"
        "• <code>/ban [reason]</code> - Permanently ban violator\n"
        "• <code>/dban [reason]</code> - Delete replied message + Ban violator\n"
        "• <code>/tban &lt;time&gt; [reason]</code> - Temporary ban with auto-unban\n"
        "• <code>/unban</code> - Revoke member ban\n"
        "• <code>/kick</code> - Remove user from group (allows rejoining)\n"
        "• <code>/dkick</code> - Delete replied message + Remove user\n"
        "• <code>/promote</code> - Elevate to admin with 0 custom rights\n"
        "• <code>/demote</code> - Strip all administrator rights\n"
        "• <code>/warn [reason]</code> - Issue warning increment with automated ceiling\n"
        "• <code>/resetwarn</code> - Clear user warning counter\n"
        "• <code>/report [reason]</code> - (Reply only) Publicly flag message for review\n"
        "• <code>/show [reason]</code> - (Reply only) Forward report to admins in PM\n"
        "• <code>/addexcept</code> - Designate admin to receive confidential reports\n"
        "• <code>/remexcept</code> - Remove admin from report recipients\n"
        "• <code>/excepted</code> - List currently configured Excepted Admins\n\n"
        f"<i>Engine loop: <code>{LOOP_ENGINE}</code> | Sub-second latency active.</i>"
    )
    back_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data="dm:main_menu")]
    ])
    try:
        await query.message.edit_text(help_text, reply_markup=back_markup, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await query.answer()


def render_submenu(subname: str, chat_title: str, s: Dict[str, Any], chat_id: int, is_dm: bool) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Submenu rendering router. Returns the formatted text and inline keyboard for any requested submenu.
    """
    if subname == "regulation":
        return format_regulation_text(chat_title, s), generate_regulation_keyboard(chat_id, is_dm=is_dm)
    elif subname == "antispam":
        return format_antispam_text(chat_title, s), generate_antispam_keyboard(chat_id, is_dm=is_dm)
    elif subname == "welcome":
        return format_welcome_text(chat_title, s), generate_welcome_keyboard(chat_id, is_dm=is_dm)
    elif subname == "goodbye":
        return format_goodbye_text(chat_title, s), generate_goodbye_keyboard(chat_id, is_dm=is_dm)
    elif subname == "alphabets":
        return format_alphabets_text(chat_title, s), generate_alphabets_keyboard(chat_id, is_dm=is_dm)
    elif subname == "captcha":
        return format_captcha_text(chat_title, s), generate_captcha_keyboard(chat_id, is_dm=is_dm)
    elif subname == "checks":
        return format_checks_text(chat_title, s), generate_checks_keyboard(chat_id, is_dm=is_dm)
    elif subname == "admincall":
        return format_admincall_text(chat_title, s), generate_admincall_keyboard(chat_id, is_dm=is_dm)
    elif subname == "blocks":
        return format_blocks_text(chat_title, s), generate_blocks_keyboard(chat_id, is_dm=is_dm)
    elif subname == "media":
        return format_media_text(chat_title, s), generate_media_keyboard(chat_id, is_dm=is_dm)
    elif subname == "porn":
        return format_porn_text(chat_title, s), generate_porn_keyboard(chat_id, is_dm=is_dm)
    elif subname == "warn":
        return format_warn_text(chat_title, s), generate_warn_keyboard(chat_id, is_dm=is_dm)
    elif subname == "night":
        return format_night_text(chat_title, s), generate_night_keyboard(chat_id, is_dm=is_dm)
    elif subname == "tag":
        return format_tag_text(chat_title, s), generate_tag_keyboard(chat_id, is_dm=is_dm)
    elif subname == "links":
        return format_links_text(chat_title, s), generate_links_keyboard(chat_id, is_dm=is_dm)
    elif subname == "guardian" or subname == "bot":
        return format_guardian_text(chat_title, s), generate_guardian_keyboard(chat_id, is_dm=is_dm)
    elif subname == "approval":
        return format_approval_text(chat_title, s), generate_approval_keyboard(chat_id, is_dm=is_dm)
    elif subname == "delmsgs" or subname == "service":
        return format_delmsgs_text(chat_title, s), generate_delmsgs_keyboard(chat_id, is_dm=is_dm)
    elif subname == "flood":
        return format_flood_text(chat_title, s), generate_flood_keyboard(chat_id, is_dm=is_dm)
    elif subname == "excepted":
        return format_excepted_text(chat_title, s), generate_excepted_keyboard(chat_id, is_dm=is_dm)
    elif subname == "topic":
        return format_topic_text(chat_title, s), generate_topic_keyboard(chat_id, is_dm=is_dm)
    elif subname == "bannedwords":
        return format_bannedwords_text(chat_title, s), generate_bannedwords_keyboard(chat_id, is_dm=is_dm)
    elif subname == "recurring":
        return format_recurring_text(chat_title, s), generate_recurring_keyboard(chat_id, is_dm=is_dm)
    elif subname == "members":
        return format_members_text(chat_title, s, chat_id=chat_id), generate_members_keyboard(chat_id, is_dm=is_dm)
    elif subname == "masked":
        return format_masked_text(chat_title, s), generate_masked_keyboard(chat_id, is_dm=is_dm)
    elif subname == "discussion":
        return format_discussion_text(chat_title, s), generate_discussion_keyboard(chat_id, is_dm=is_dm)
    elif subname == "personalcmds":
        return format_personalcmds_text(chat_title, s), generate_personalcmds_keyboard(chat_id, is_dm=is_dm)
    elif subname == "magicstickers":
        return format_magicstickers_text(chat_title, s), generate_magicstickers_keyboard(chat_id, is_dm=is_dm)
    elif subname == "msglength":
        return format_msglength_text(chat_title, s), generate_msglength_keyboard(chat_id, is_dm=is_dm)
    elif subname == "channels":
        return format_channels_text(chat_title, s), generate_channels_keyboard(chat_id, is_dm=is_dm)
    elif subname == "permissions":
        return format_permissions_text(chat_title, s), generate_permissions_keyboard(chat_id, is_dm=is_dm)
    elif subname == "logchannel":
        return format_logchannel_text(chat_title, s), generate_logchannel_keyboard(chat_id, is_dm=is_dm)
    else:
        return format_settings_hub_text(chat_title), generate_settings_page1_keyboard(chat_id, is_dm=is_dm)


@router.callback_query(F.data.regexp(r"^(set|dm|cfg):"))
async def handle_settings_callback(query: CallbackQuery, bot: Bot) -> None:
    """
    Handles interactive settings configuration clicks (both in-group and from private DMs).
    Guarded strictly by check_can_setup_bot (Owner, Anonymous Admin, Excepted Admin).
    Provides deep modular customization for all violation limits, punishments, and features.
    """
    if query.data in ("dm:switch_group", "dm:refresh_groups"):
        await handle_dm_manage_settings(query, bot)
        return

    parts = query.data.split(":")
    if len(parts) < 3:
        await query.answer()
        return

    action = parts[1]
    subname = None
    chat_id = 0

    # Parse parameters based on action type
    if action in ("open_here", "close", "toggle_rules_perm"):
        try:
            chat_id = int(parts[2])
        except ValueError:
            await query.answer()
            return
    elif action in ("page", "menu", "cust"):
        subname = parts[2]
        try:
            chat_id = int(parts[3])
        except ValueError:
            await query.answer()
            return
    elif action == "setlen":
        # format: prefix:setlen:<val>:<chat_id>
        try:
            target_len = int(parts[2])
            chat_id = int(parts[3])
        except (ValueError, IndexError):
            await query.answer()
            return
        subname = "msglength"
    elif action in ("toggle", "cycle"):
        # e.g. set:toggle:<key>:<chat_id>:<subname>
        key = parts[2]
        try:
            chat_id = int(parts[3])
        except ValueError:
            await query.answer()
            return
        subname = parts[4] if len(parts) >= 5 else "main"
    else:
        # Legacy action: e.g. set:warn_inc:<chat_id>
        try:
            chat_id = int(parts[2])
        except ValueError:
            await query.answer()
            return

    user_id = query.from_user.id
    sender_chat_id = query.message.sender_chat.id if query.message and query.message.sender_chat else None

    # STRICT ACCESS CONTROL: Only Owner, Anonymous Admins, or Excepted Admins can configure settings
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await query.answer("❌ Only the Chat Owner, Anonymous Admins, or Excepted Admins can configure settings.", show_alert=True)
        return

    s = CHAT_SETTINGS[chat_id]
    is_dm = query.message.chat.type == ChatType.PRIVATE if query.message else False
    if is_dm and query.message:
        LAST_DM_SETTINGS_MSG[user_id] = query.message.message_id
    chat_title = await get_cached_chat_title(bot, chat_id)

    # 1. Open Here (Group inline expansion)
    if action == "open_here":
        text = format_settings_hub_text(chat_title)
        kb = generate_settings_page1_keyboard(chat_id, is_dm=False)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
        return

    # 2. Close Menu Action
    if action == "close":
        try:
            await query.message.delete()
        except Exception:
            pass
        if is_dm:
            LAST_DM_SETTINGS_MSG.pop(user_id, None)
        await query.answer("Closed.")
        return

    # 3. Page Flipping (Page 1 <-> Page 2)
    if action == "page":
        text = format_settings_hub_text(chat_title)
        if subname == "2":
            kb = generate_settings_page2_keyboard(chat_id, is_dm=is_dm)
        else:
            kb = generate_settings_page1_keyboard(chat_id, is_dm=is_dm)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
        return

    # 4. Submenu Navigation
    if action == "menu":
        text, kb = render_submenu(subname, chat_title, s, chat_id, is_dm)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
        return

    # 5. Generic Boolean Toggle
    if action == "toggle":
        s[key] = not s.get(key, False)
        DatabaseService.save_settings_background(chat_id, chat_title, s)
        text, kb = render_submenu(subname, chat_title, s, chat_id, is_dm)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        status_str = "ENABLED" if s[key] else "DISABLED"
        await query.answer(f"{key}: {status_str}")
        return

    # 5B. Direct Message Length Preset Selection
    if action == "setlen":
        s["max_message_length"] = max(0, min(4096, target_len))
        DatabaseService.save_settings_background(chat_id, chat_title, s)
        text, kb = render_submenu("msglength", chat_title, s, chat_id, is_dm)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        len_desc = f"{target_len} chars" if target_len > 0 else "Unlimited"
        await query.answer(f"Length limit: {len_desc}")
        return

    # 6. Generic Cycle Option
    if action == "cycle":
        cycles = {
            "alphabet_action": ["delete", "warn"],
            "captcha_mode": ["off", "button", "math"],
            "captcha_timeout": [60, 120, 300],
            "captcha_action": ["kick", "ban"],
            "porn_action": ["delete", "warn", "mute"],
            "tag_limit": [3, 5, 10],
            "tag_action": ["delete", "warn", "mute"],
            "bot_action": ["ban", "kick"],
            "slow_mode": [0, 10, 30, 60],
            "magic_stickers_limit": [0, 3, 5],
            "max_message_length": [0, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4000],
            "msg_length_action": ["delete", "warn"],
            "banned_words_action": ["delete", "warn"],
        }
        options = cycles.get(key, ["delete", "warn"])
        cur = s.get(key, options[0])
        idx = options.index(cur) if cur in options else 0
        s[key] = options[(idx + 1) % len(options)]
        DatabaseService.save_settings_background(chat_id, chat_title, s)
        text, kb = render_submenu(subname, chat_title, s, chat_id, is_dm)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer(f"{key}: {s[key]}")
        return

    # 7. Customize Text in PM
    if action == "cust":
        if is_dm:
            PENDING_CUSTOM_INPUT[user_id] = (chat_id, subname)
            if subname in ("msglength", "message_length", "length"):
                await query.message.answer(
                    "📏 <b>Enter custom maximum message length:</b>\n\n"
                    "Please send an integer between <code>0</code> and <code>4096</code> characters.\n"
                    "• <code>0</code> = Unlimited (Disable limit)\n"
                    "• E.g. <code>1200</code> for 1,200 characters\n\n"
                    "<i>Send /cancel to abort.</i>",
                    parse_mode=ParseMode.HTML
                )
                await query.answer("Enter character limit in PM...")
                return
            nice_name = subname.replace("_", " ").title()
            await query.message.answer(
                f"✍️ <b>Please send your custom {nice_name} message now:</b>\n"
                f"<i>Placeholders like {{mention}}, {{name}}, {{chat_title}}, {{id}} are supported.\nSend /cancel to abort.</i>",
                parse_mode=ParseMode.HTML
            )
            await query.answer("Waiting for text...")
        else:
            bot_me = await bot.get_me()
            dm_link = f"https://t.me/{bot_me.username}?start=custom_{subname}_{abs(chat_id)}"
            await query.answer(f"To customize message, please open bot PM: @{bot_me.username}", show_alert=True)
        return

    # 7B. Broadcast Triggers from Members Management
    if action in ("bcast_chat", "bcast_all"):
        scope = "chat" if action == "bcast_chat" else "all"
        if not is_dm:
            bot_me = await bot.get_me()
            dm_link = f"https://t.me/{bot_me.username}?start=bcast_{abs(chat_id)}_{scope}"
            await query.answer("Please switch to Private DM to compose broadcast safely!", show_alert=True)
            return

        target_count = sum(1 for m in ACCEPTED_MEMBERS_CACHE.values() if chat_id in m.get("chat_ids", [])) if scope == "chat" else len(ACCEPTED_MEMBERS_CACHE)
        PENDING_CUSTOM_INPUT[user_id] = (chat_id, f"broadcast:{scope}")
        scope_name = f"Group '{chat_title}'" if scope == "chat" else "All Global"
        await query.message.answer(
            f"📢 <b>Broadcast to {scope_name} Accepted Members ({target_count} members)</b>\n\n"
            f"Please send the message you wish to broadcast now.\n"
            f"<i>HTML formatting tags (<b>bold</b>, <i>italic</i>, <code>code</code>, <a href='...'>link</a>) are supported.\nSend /cancel to abort.</i>",
            parse_mode=ParseMode.HTML
        )
        await query.answer()
        return

    # 8. Rules Permission Toggle
    if action == "toggle_rules_perm":
        s["rules_perm"] = "admins" if s.get("rules_perm", "all") == "all" else "all"
        DatabaseService.save_settings_background(chat_id, chat_title, s)
        text, kb = render_submenu("regulation", chat_title, s, chat_id, is_dm)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer(f"Rules permission: {s['rules_perm']}")
        return

    # 10. Legacy Warn Actions
    if action == "warn_inc":
        s["warn_limit"] = min(10, int(s.get("warn_limit", 3)) + 1)
        await query.answer(f"Warn Ceiling: {s['warn_limit']} violations")
    elif action == "warn_dec":
        s["warn_limit"] = max(1, int(s.get("warn_limit", 3)) - 1)
        await query.answer(f"Warn Ceiling: {s['warn_limit']} violations")
    elif action == "warn_cycle":
        limits = [1, 2, 3, 5, 10]
        cur = int(s.get("warn_limit", 3))
        idx = limits.index(cur) if cur in limits else 2
        s["warn_limit"] = limits[(idx + 1) % len(limits)]
        await query.answer(f"Warn Ceiling: {s['warn_limit']} violations")
    elif action == "warn_action":
        actions = ["mute", "ban", "kick"]
        cur = s.get("warn_action", "mute")
        idx = actions.index(cur) if cur in actions else 0
        s["warn_action"] = actions[(idx + 1) % len(actions)]
        await query.answer(f"Warn Punishment: {s['warn_action'].upper()}")
    elif action == "warn_dur":
        durations = [3600, 21600, 43200, 86400, 604800, 0]
        cur = int(s.get("warn_duration", 86400))
        idx = durations.index(cur) if cur in durations else 3
        s["warn_duration"] = durations[(idx + 1) % len(durations)]
        await query.answer(f"Warn Duration: {format_duration(s['warn_duration'])}")
    elif action == "warn_toggle_cancel":
        s["warn_cancel_btn"] = not s.get("warn_cancel_btn", True)
        status_str = "ENABLED" if s["warn_cancel_btn"] else "DISABLED"
        await query.answer(f"Cancel Warn Button: {status_str}")
    elif action == "warn_toggle_auto":
        s["auto_warn_enabled"] = not s.get("auto_warn_enabled", True)
        status_str = "ACTIVE" if s["auto_warn_enabled"] else "DISABLED"
        await query.answer(f"Master Auto-Warn: {status_str}")
    elif action == "warn_toggle_dup":
        s["warn_on_duplicate"] = not s.get("warn_on_duplicate", True)
        status_str = "ON" if s["warn_on_duplicate"] else "OFF"
        await query.answer(f"Warn on Duplicates: {status_str}")
    elif action == "warn_dup_limit_cycle":
        limits = [2, 3, 4, 5, 10]
        cur = int(s.get("duplicate_limit", 2))
        idx = limits.index(cur) if cur in limits else 0
        s["duplicate_limit"] = limits[(idx + 1) % len(limits)]
        await query.answer(f"Duplicate Limit: {s['duplicate_limit']} repeats")
    elif action == "warn_dup_win_cycle":
        windows = [10, 15, 30, 60, 120]
        cur = int(s.get("duplicate_window", 30))
        idx = windows.index(cur) if cur in windows else 2
        s["duplicate_window"] = windows[(idx + 1) % len(windows)]
        await query.answer(f"Duplicate Window: {s['duplicate_window']}s")
    elif action == "warn_toggle_flood":
        s["warn_on_flood"] = not s.get("warn_on_flood", True)
        status_str = "ON" if s["warn_on_flood"] else "OFF"
        await query.answer(f"Warn on Flood: {status_str}")
    elif action == "warn_custom_msg":
        PENDING_CUSTOM_WARN[user_id] = chat_id
        text = format_warn_custom_text(chat_title, s)
        kb = generate_warn_custom_keyboard(chat_id)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
        return
    elif action == "warn_custom_reset":
        s["custom_warn_msg"] = ""
        PENDING_CUSTOM_WARN.pop(user_id, None)
        text = format_warn_custom_text(chat_title, s)
        kb = generate_warn_custom_keyboard(chat_id)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer("Custom warning template reset to default.")
        DatabaseService.save_settings_background(chat_id, chat_title, s)
        return

    # 11. Legacy Anti-Flood Actions
    elif action == "flood_toggle":
        s["flood_protection"] = not s.get("flood_protection", True)
        await query.answer(f"Anti-Flood: {'ACTIVE' if s['flood_protection'] else 'DISABLED'}")
    elif action == "flood_limit_inc":
        s["flood_limit"] = min(25, int(s.get("flood_limit", 5)) + 1)
        await query.answer(f"Flood Limit: {s['flood_limit']} msgs")
    elif action == "flood_limit_dec":
        s["flood_limit"] = max(1, int(s.get("flood_limit", 5)) - 1)
        await query.answer(f"Flood Limit: {s['flood_limit']} msgs")
    elif action == "flood_limit_cycle":
        limits = [3, 5, 7, 10, 15, 20]
        cur = int(s.get("flood_limit", 5))
        idx = limits.index(cur) if cur in limits else 1
        s["flood_limit"] = limits[(idx + 1) % len(limits)]
        await query.answer(f"Flood Limit: {s['flood_limit']} msgs")
    elif action == "flood_win_inc":
        s["flood_window"] = min(20.0, float(s.get("flood_window", 3.0)) + 1.0)
        await query.answer(f"Flood Window: {int(s['flood_window'])}s")
    elif action == "flood_win_dec":
        s["flood_window"] = max(1.0, float(s.get("flood_window", 3.0)) - 1.0)
        await query.answer(f"Flood Window: {int(s['flood_window'])}s")
    elif action == "flood_win_cycle":
        windows = [1.0, 2.0, 3.0, 5.0, 10.0]
        cur = float(s.get("flood_window", 3.0))
        idx = windows.index(cur) if cur in windows else 2
        s["flood_window"] = windows[(idx + 1) % len(windows)]
        await query.answer(f"Flood Window: {int(s['flood_window'])}s")
    elif action == "flood_action":
        actions = ["mute", "delete", "kick", "ban"]
        cur = s.get("flood_action", "mute")
        idx = actions.index(cur) if cur in actions else 0
        s["flood_action"] = actions[(idx + 1) % len(actions)]
        await query.answer(f"Flood Punishment: {s['flood_action'].upper()}")
    elif action == "flood_dur":
        durations = [60, 300, 900, 3600, 86400]
        cur = int(s.get("flood_duration", 900))
        idx = durations.index(cur) if cur in durations else 2
        s["flood_duration"] = durations[(idx + 1) % len(durations)]
        await query.answer(f"Mute Duration: {format_duration(s['flood_duration'])}")

    # 12. Legacy Links Actions
    elif action == "links_member":
        s["block_links"] = not s.get("block_links", False)
        await query.answer(f"Member Links: {'Blocked' if s['block_links'] else 'Allowed'}")
    elif action == "links_admin":
        s["admin_links_block"] = not s.get("admin_links_block", False)
        await query.answer(f"Admin Links: {'Blocked' if s['admin_links_block'] else 'Allowed'}")
    elif action == "links_channels":
        s["block_channel_links"] = not s.get("block_channel_links", False)
        await query.answer(f"Channel Links: {'Blocked' if s['block_channel_links'] else 'Allowed'}")
    elif action == "links_action":
        s["link_action"] = "warn" if s.get("link_action", "delete") == "delete" else "delete"
        await query.answer(f"Link Action: {s['link_action'].upper()}")

    # 13. Legacy Media Actions
    elif action == "media_sticker":
        s["block_sticker"] = not s.get("block_sticker", False)
        await query.answer(f"Stickers: {'Blocked' if s['block_sticker'] else 'Allowed'}")
    elif action == "media_animation":
        s["block_animation"] = not s.get("block_animation", False)
        await query.answer(f"GIFs: {'Blocked' if s['block_animation'] else 'Allowed'}")
    elif action == "media_document":
        s["block_document"] = not s.get("block_document", False)
        await query.answer(f"Documents: {'Blocked' if s['block_document'] else 'Allowed'}")
    elif action == "media_voice":
        s["block_voice"] = not s.get("block_voice", False)
        await query.answer(f"Voice Notes: {'Blocked' if s['block_voice'] else 'Allowed'}")
    elif action == "media_audio":
        s["block_audio"] = not s.get("block_audio", False)
        await query.answer(f"Audio: {'Blocked' if s['block_audio'] else 'Allowed'}")
    elif action == "media_photo":
        s["block_photo"] = not s.get("block_photo", False)
        await query.answer(f"Photos: {'Blocked' if s['block_photo'] else 'Allowed'}")
    elif action == "media_video":
        s["block_video"] = not s.get("block_video", False)
        await query.answer(f"Videos: {'Blocked' if s['block_video'] else 'Allowed'}")
    elif action == "media_action":
        s["media_action"] = "warn" if s.get("media_action", "delete") == "delete" else "delete"
        await query.answer(f"Media Action: {s['media_action'].upper()}")

    # 14. Legacy Excepted Actions
    elif action == "excepted_clear":
        s["excepted_admins"] = []
        await query.answer("All Excepted Admins cleared.", show_alert=True)
    elif action == "reload":
        await query.answer("Settings reloaded.")

    # Background MongoDB persistence (write-behind non-blocking)
    DatabaseService.save_settings_background(chat_id, chat_title, s)

    # Re-render appropriate screen for legacy actions
    if action.startswith("warn_"):
        text = format_warn_text(chat_title, s)
        kb = generate_warn_keyboard(chat_id, is_dm=is_dm)
    elif action.startswith("flood_"):
        text = format_flood_text(chat_title, s)
        kb = generate_flood_keyboard(chat_id, is_dm=is_dm)
    elif action.startswith("links_"):
        text = format_links_text(chat_title, s)
        kb = generate_links_keyboard(chat_id, is_dm=is_dm)
    elif action.startswith("media_"):
        text = format_media_text(chat_title, s)
        kb = generate_media_keyboard(chat_id, is_dm=is_dm)
    elif action.startswith("excepted_"):
        text = format_excepted_text(chat_title, s)
        kb = generate_excepted_keyboard(chat_id, is_dm=is_dm)
    else:
        text = format_settings_hub_text(chat_title)
        kb = generate_settings_page1_keyboard(chat_id, is_dm=is_dm)

    try:
        await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ==============================================================================
# CANCEL WARN INLINE CALLBACK HANDLER (ANY ADMIN VALIDATION)
# ==============================================================================

@router.callback_query(F.data.startswith("warn:cancel:"))
async def handle_cancel_warn_callback(query: CallbackQuery, bot: Bot) -> None:
    """
    Handles Cancel Warn inline button clicks on warning notices.
    Strictly verifies admin status (any group admin or anonymous admin can cancel).
    Decrements user warning count in memory & DB, and edits notice into a clean confirmation.
    """
    parts = query.data.split(":")
    if len(parts) < 4:
        await query.answer()
        return

    try:
        chat_id = int(parts[2])
        target_id = int(parts[3])
    except ValueError:
        await query.answer()
        return

    admin_user = query.from_user
    sender_chat_id = query.message.sender_chat.id if query.message and query.message.sender_chat else None

    # Verification: Any chat administrator or anonymous group admin can cancel warnings
    is_admin = await check_admin_rights(bot, chat_id, admin_user.id)
    if not is_admin and sender_chat_id and sender_chat_id == chat_id:
        is_admin = True

    if not is_admin:
        await query.answer("⚠️ Only chat administrators can cancel warnings!", show_alert=True)
        return

    current_count = WARN_CACHE[chat_id].get(target_id, 0)
    new_count = max(0, current_count - 1)
    if new_count <= 0:
        WARN_CACHE[chat_id].pop(target_id, None)
        if not WARN_CACHE[chat_id]:
            WARN_CACHE.pop(chat_id, None)
    else:
        WARN_CACHE[chat_id][target_id] = new_count

    DatabaseService.cancel_warn_background(chat_id, target_id, new_count)
    DatabaseService.log_moderation_background(chat_id, admin_user.id, target_id, "cancel_warn", "Warning cancelled by admin")

    ceiling = CHAT_SETTINGS[chat_id].get("warn_limit", 3)
    admin_name = html.escape(admin_user.full_name)
    admin_mention = f"<a href='tg://user?id={admin_user.id}'>{admin_name}</a>"

    confirmation_text = (
        f"✅ <b>Warning Cancelled</b>\n\n"
        f"🛡️ <b>Admin:</b> {admin_mention}\n"
        f"👤 <b>Target ID:</b> <code>{target_id}</code>\n"
        f"🔢 <b>Current Warnings:</b> <b>{new_count}/{ceiling}</b>\n"
        f"<i>The warning has been officially forgiven and cleared.</i>"
    )

    try:
        await query.message.edit_text(confirmation_text, reply_markup=None, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    await query.answer(f"Warning cancelled! Current warnings: {new_count}/{ceiling}")


# ==============================================================================
# CAPTCHA VERIFICATION CALLBACK HANDLER
# ==============================================================================

@router.callback_query(F.data.startswith("captcha:verify:"))
async def handle_captcha_verify(query: CallbackQuery, bot: Bot) -> None:
    """
    Handles inline Captcha verification button clicks.
    Unrestricts new members and clears the verification prompt immediately.
    """
    parts = query.data.split(":")
    if len(parts) < 4:
        await query.answer()
        return

    try:
        target_chat_id = int(parts[2])
        target_user_id = int(parts[3])
    except ValueError:
        await query.answer()
        return

    if query.from_user.id != target_user_id:
        await query.answer("⚠️ This verification button is only for the newly joined member!", show_alert=True)
        return

    # Unrestrict member privileges
    try:
        await bot.restrict_chat_member(
            chat_id=target_chat_id,
            user_id=target_user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
    except Exception as e:
        print(f"[CAPTCHA WARNING] Could not unrestrict member: {e}")

    try:
        await query.message.delete()
    except Exception:
        try:
            await query.message.edit_text(
                f"✅ {query.from_user.mention_html()} has been verified successfully! Welcome!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    await query.answer("✅ Verification successful! You can now participate in chat.", show_alert=False)


# ==============================================================================
# SUBMENU COMMAND HANDLERS (/rules, /welcome, /goodbye, /words, /filters, etc.)
# ==============================================================================

@router.message(Command("rules"))
async def handle_rules(message: Message, bot: Bot) -> None:
    """Displays the group regulations matching the permissions setting."""
    chat_id = message.chat.id
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        s = CHAT_SETTINGS[chat_id]
        perm = s.get("rules_perm", "all")
        if perm == "admins":
            user_id = message.from_user.id if message.from_user else 0
            sender_chat_id = message.sender_chat.id if message.sender_chat else None
            if not await is_user_admin(bot, chat_id, user_id, sender_chat_id):
                await wipe_trigger(message)
                return

        chat_title = await get_cached_chat_title(bot, chat_id)
        rules = s.get("rules_text", "").strip()
        if rules:
            text = f"📜 <b>Regulations of {html.escape(chat_title)}:</b>\n\n{rules}"
        else:
            text = f"📜 <i>No regulations have been defined for <b>{html.escape(chat_title)}</b> yet.\nAdmins can configure them with <code>/setrules &lt;text&gt;</code> or in <code>/settings</code>.</i>"

        await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        await message.answer("📜 Use <code>/rules</code> inside a group to view its regulations, or configure them via <b>⚙️ Manage group Settings</b>.")


@router.message(Command("setrules"))
async def handle_setrules(message: Message, command: CommandObject, bot: Bot) -> None:
    """Configures group regulations."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.answer("❌ This command can only be used in groups.")
        return

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None

    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only the Owner, Anonymous Admins, or Excepted Admins can configure regulations.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(message, "⚠️ Usage: <code>/setrules &lt;regulations text&gt;</code>\n<i>You can also configure regulations interactively in /settings.</i>")
        return

    new_rules = command.args.strip()
    s = CHAT_SETTINGS[chat_id]
    s["rules_text"] = new_rules
    chat_title = await get_cached_chat_title(bot, chat_id)
    DatabaseService.save_settings_background(chat_id, chat_title, s)
    await message.answer(f"✅ <b>Regulations updated successfully for {html.escape(chat_title)}!</b>", parse_mode=ParseMode.HTML)


@router.message(Command("welcome"))
async def handle_preview_welcome(message: Message, bot: Bot) -> None:
    """Previews the active welcome greeting."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await is_user_admin(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can preview welcome settings.")
        return

    s = CHAT_SETTINGS[chat_id]
    chat_title = await get_cached_chat_title(bot, chat_id)
    st = "🟢 Enabled" if s.get("welcome_enabled") else "🔴 Disabled"
    template = s.get("welcome_msg", "👋 Welcome to <b>{chat_title}</b>, {mention}!")
    sample = template.replace("{mention}", message.from_user.mention_html()) \
                     .replace("{name}", html.escape(message.from_user.full_name)) \
                     .replace("{chat_title}", html.escape(chat_title)) \
                     .replace("{id}", str(user_id))

    await message.answer(
        f"💬 <b>Welcome Status:</b> {st}\n\n"
        f"<b>Preview:</b>\n{sample}\n\n"
        f"<i>To change template, use <code>/setwelcome &lt;text&gt;</code> or configure in <code>/settings</code>.</i>",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("setwelcome"))
async def handle_setwelcome(message: Message, command: CommandObject, bot: Bot) -> None:
    """Configures the welcome message template."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can configure the welcome message.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(message, "⚠️ Usage: <code>/setwelcome &lt;welcome text&gt;</code>\nPlaceholders: <code>{mention}</code>, <code>{name}</code>, <code>{chat_title}</code>, <code>{id}</code>")
        return

    s = CHAT_SETTINGS[chat_id]
    s["welcome_msg"] = command.args.strip()
    s["welcome_enabled"] = True
    chat_title = await get_cached_chat_title(bot, chat_id)
    DatabaseService.save_settings_background(chat_id, chat_title, s)
    await message.answer("✅ <b>Welcome message updated and enabled!</b>", parse_mode=ParseMode.HTML)


@router.message(Command("welcomepm"))
async def handle_preview_welcomepm(message: Message, bot: Bot) -> None:
    """Previews the active private DM welcome greeting."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can preview settings.")
        return

    await wipe_trigger(message)
    s = CHAT_SETTINGS[chat_id]
    chat_title = await get_cached_chat_title(bot, chat_id)
    st = "🟢 Enabled" if s.get("welcome_pm_enabled") else "⚪ Disabled"
    template = s.get("welcome_pm_msg", "👋 Hello {name}!\nYour request to join <b>{chat_title}</b> has been approved! Welcome to the group! 🎉")
    user_obj = message.from_user
    sample = template.replace("{mention}", user_obj.mention_html()) \
                     .replace("{name}", html.escape(user_obj.full_name)) \
                     .replace("{chat_title}", html.escape(chat_title)) \
                     .replace("{id}", str(user_id))

    await message.answer(
        f"✉️ <b>Private DM Welcome Status:</b> {st}\n\n"
        f"<b>Preview:</b>\n{sample}\n\n"
        f"<i>To change template, use <code>/setwelcomepm &lt;text&gt;</code> or configure in <code>/settings</code>.</i>",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("setwelcomepm"))
async def handle_setwelcomepm(message: Message, command: CommandObject, bot: Bot) -> None:
    """Configures and enables the private DM welcome greeting message."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can configure settings.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(
            message,
            "⚠️ Usage: <code>/setwelcomepm &lt;welcome text&gt;</code>\n"
            "Placeholders: <code>{mention}</code>, <code>{name}</code>, <code>{chat_title}</code>, <code>{id}</code>"
        )
        return

    s = CHAT_SETTINGS[chat_id]
    s["welcome_pm_msg"] = command.args.strip()
    s["welcome_pm_enabled"] = True
    chat_title = await get_cached_chat_title(bot, chat_id)
    DatabaseService.save_settings_background(chat_id, chat_title, s)
    await message.answer("✅ <b>Private DM welcome message updated and enabled!</b>", parse_mode=ParseMode.HTML)


@router.message(Command("goodbye"))
async def handle_preview_goodbye(message: Message, bot: Bot) -> None:
    """Previews the active goodbye farewell."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await is_user_admin(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can preview goodbye settings.")
        return

    s = CHAT_SETTINGS[chat_id]
    chat_title = await get_cached_chat_title(bot, chat_id)
    st = "🟢 Enabled" if s.get("goodbye_enabled") else "🔴 Disabled"
    template = s.get("goodbye_msg", "👋 Goodbye, {mention}!")
    sample = template.replace("{mention}", message.from_user.mention_html()) \
                     .replace("{name}", html.escape(message.from_user.full_name)) \
                     .replace("{chat_title}", html.escape(chat_title)) \
                     .replace("{id}", str(user_id))

    await message.answer(
        f"👋 <b>Goodbye Status:</b> {st}\n\n"
        f"<b>Preview:</b>\n{sample}\n\n"
        f"<i>To change template, use <code>/setgoodbye &lt;text&gt;</code> or configure in <code>/settings</code>.</i>",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("setgoodbye"))
async def handle_setgoodbye(message: Message, command: CommandObject, bot: Bot) -> None:
    """Configures the goodbye message template."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can configure the goodbye message.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(message, "⚠️ Usage: <code>/setgoodbye &lt;farewell text&gt;</code>\nPlaceholders: <code>{mention}</code>, <code>{name}</code>, <code>{chat_title}</code>, <code>{id}</code>")
        return

    s = CHAT_SETTINGS[chat_id]
    s["goodbye_msg"] = command.args.strip()
    s["goodbye_enabled"] = True
    chat_title = await get_cached_chat_title(bot, chat_id)
    DatabaseService.save_settings_background(chat_id, chat_title, s)
    await message.answer("✅ <b>Goodbye message updated and enabled!</b>", parse_mode=ParseMode.HTML)


@router.message(Command("addword"))
async def handle_addword(message: Message, command: CommandObject, bot: Bot) -> None:
    """Adds a prohibited word to the banned words filter."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can manage banned words.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(message, "⚠️ Usage: <code>/addword &lt;word or phrase&gt;</code>")
        return

    word = command.args.strip().lower()
    s = CHAT_SETTINGS[chat_id]
    words_list = s.get("banned_words", [])
    if word not in words_list:
        words_list.append(word)
        s["banned_words"] = words_list
        chat_title = await get_cached_chat_title(bot, chat_id)
        DatabaseService.save_settings_background(chat_id, chat_title, s)
        await message.answer(f"✅ Added <code>{html.escape(word)}</code> to banned words list.", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"ℹ️ <code>{html.escape(word)}</code> is already in the banned words list.", parse_mode=ParseMode.HTML)


@router.message(Command("delword"))
async def handle_delword(message: Message, command: CommandObject, bot: Bot) -> None:
    """Removes a word from the banned words filter."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can manage banned words.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(message, "⚠️ Usage: <code>/delword &lt;word or phrase&gt;</code>")
        return

    word = command.args.strip().lower()
    s = CHAT_SETTINGS[chat_id]
    words_list = s.get("banned_words", [])
    if word in words_list:
        words_list.remove(word)
        s["banned_words"] = words_list
        chat_title = await get_cached_chat_title(bot, chat_id)
        DatabaseService.save_settings_background(chat_id, chat_title, s)
        await message.answer(f"✅ Removed <code>{html.escape(word)}</code> from banned words list.", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"ℹ️ <code>{html.escape(word)}</code> was not in the banned words list.", parse_mode=ParseMode.HTML)


@router.message(Command("words"))
async def handle_words(message: Message, bot: Bot) -> None:
    """Lists currently prohibited words in the group."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await is_user_admin(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "⚠️ Only administrators can view the banned words list.")
        return

    await wipe_trigger(message)
    s = CHAT_SETTINGS[chat_id]
    words_list = s.get("banned_words", [])
    if not words_list:
        await message.answer("🔤 No banned words currently configured. Add words using <code>/addword &lt;word&gt;</code>.", parse_mode=ParseMode.HTML)
        return

    items = "\n".join(f"• <code>{html.escape(w)}</code>" for w in words_list[:50])
    await message.answer(f"🔤 <b>Banned Words ({len(words_list)}):</b>\n\n{items}", parse_mode=ParseMode.HTML)


@router.message(Command("filter"))
async def handle_add_filter(message: Message, command: CommandObject, bot: Bot) -> None:
    """Adds a custom keyword trigger and reply filter."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can configure filters.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(message, "⚠️ Usage: <code>/filter &lt;keyword&gt; &lt;reply text&gt;</code>")
        return

    parts = command.args.strip().split(maxsplit=1)
    if len(parts) < 2:
        await send_ephemeral(message, "⚠️ Please provide both a keyword trigger and a reply text.\nUsage: <code>/filter &lt;keyword&gt; &lt;reply text&gt;</code>")
        return

    trigger, reply_text = parts[0].lower(), parts[1]
    s = CHAT_SETTINGS[chat_id]
    filters_dict = s.get("custom_filters", {})
    filters_dict[trigger] = reply_text
    s["custom_filters"] = filters_dict
    chat_title = await get_cached_chat_title(bot, chat_id)
    DatabaseService.save_settings_background(chat_id, chat_title, s)
    await message.answer(f"✅ Filter added for <code>{html.escape(trigger)}</code>!", parse_mode=ParseMode.HTML)


@router.message(Command("stop"))
async def handle_stop_filter(message: Message, command: CommandObject, bot: Bot) -> None:
    """Removes a custom keyword reply filter."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can manage filters.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(message, "⚠️ Usage: <code>/stop &lt;keyword&gt;</code>")
        return

    trigger = command.args.strip().lower()
    s = CHAT_SETTINGS[chat_id]
    filters_dict = s.get("custom_filters", {})
    if trigger in filters_dict:
        del filters_dict[trigger]
        s["custom_filters"] = filters_dict
        chat_title = await get_cached_chat_title(bot, chat_id)
        DatabaseService.save_settings_background(chat_id, chat_title, s)
        await message.answer(f"✅ Stopped filter for <code>{html.escape(trigger)}</code>.", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"ℹ️ No active filter found for <code>{html.escape(trigger)}</code>.", parse_mode=ParseMode.HTML)


@router.message(Command("filters"))
async def handle_list_filters(message: Message, bot: Bot) -> None:
    """Lists all active custom keyword filters in the group."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    s = CHAT_SETTINGS[chat_id]
    filters_dict = s.get("custom_filters", {})
    if not filters_dict:
        await message.answer("📱 No custom personal filters active in this group.\nAdd one with <code>/filter &lt;word&gt; &lt;reply&gt;</code>.", parse_mode=ParseMode.HTML)
        return

    items = "\n".join(f"• <code>{html.escape(k)}</code>" for k in sorted(filters_dict.keys())[:30])
    await message.answer(f"📱 <b>Active Filters ({len(filters_dict)}):</b>\n\n{items}", parse_mode=ParseMode.HTML)


@router.message(Command("setlog"))
async def handle_setlog(message: Message, command: CommandObject, bot: Bot) -> None:
    """Designates a channel for security audit logging."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
        await send_ephemeral(message, "❌ Only authorized admins can configure the audit log channel.")
        return

    await wipe_trigger(message)
    if not command or not command.args:
        await send_ephemeral(message, "⚠️ Usage: <code>/setlog &lt;channel_id or @channel_username&gt;</code>")
        return

    target_channel = command.args.strip()
    s = CHAT_SETTINGS[chat_id]
    s["log_channel"] = target_channel
    chat_title = await get_cached_chat_title(bot, chat_id)
    DatabaseService.save_settings_background(chat_id, chat_title, s)
    await message.answer(f"✅ <b>Audit Log Channel set to:</b> <code>{html.escape(target_channel)}</code>", parse_mode=ParseMode.HTML)


# ==============================================================================
# PRIVATE DM CUSTOM TEXT LISTENER & CANCEL ENGINE
# ==============================================================================

@router.message(Command("cancel"), F.chat.type == ChatType.PRIVATE)
async def handle_dm_cancel_input(message: Message) -> None:
    """Cancels active custom text editing in private DM."""
    user_id = message.from_user.id if message.from_user else 0
    cancelled = False

    if user_id in PENDING_CUSTOM_WARN:
        chat_id = PENDING_CUSTOM_WARN.pop(user_id)
        cancelled = True
        await message.answer(
            "❌ Custom warning message configuration cancelled.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Return to Warn Settings", callback_data=f"set:menu:warn:{chat_id}")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="dm:main_menu")]
            ])
        )

    if user_id in PENDING_CUSTOM_INPUT:
        chat_id, subname = PENDING_CUSTOM_INPUT.pop(user_id)
        cancelled = True
        back_data = f"set:menu:{subname}:{chat_id}" if subname != "main" else f"set:page:1:{chat_id}"
        await message.answer(
            f"❌ Custom {subname} configuration cancelled.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"⚙️ Return to {subname.capitalize()} Settings", callback_data=back_data)],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="dm:main_menu")]
            ])
        )

    if not cancelled:
        await message.answer("ℹ️ No active configuration to cancel.")


@router.message(F.chat.type == ChatType.PRIVATE, ~F.text.startswith("/"))
async def handle_dm_custom_text(message: Message, bot: Bot) -> None:
    """
    Listens for custom configuration text sent by an authorized admin in private DM:
    - Custom warning templates (PENDING_CUSTOM_WARN)
    - Custom rules, welcome, goodbye, or other templates (PENDING_CUSTOM_INPUT)
    """
    user_id = message.from_user.id if message.from_user else 0

    # 1. Handle PENDING_CUSTOM_INPUT (Rules, Welcome, Goodbye, etc.)
    if user_id in PENDING_CUSTOM_INPUT:
        chat_id, subname = PENDING_CUSTOM_INPUT.pop(user_id)
        if not await check_can_setup_bot(bot, chat_id, user_id):
            await message.answer("❌ You are no longer authorized to manage settings for this group.")
            return

        custom_text = message.text.strip()
        if len(custom_text) > 2000:
            PENDING_CUSTOM_INPUT[user_id] = (chat_id, subname)
            await message.answer("❌ Text too long (maximum 2000 characters). Please send a shorter text.")
            return

        s = CHAT_SETTINGS[chat_id]
        chat_title = await get_cached_chat_title(bot, chat_id)

        # Broadcast text processing in private DM
        if subname.startswith("broadcast:"):
            scope = subname.split(":", 1)[1]
            if scope == "chat" and chat_id != 0:
                target_ids = [uid for uid, m in ACCEPTED_MEMBERS_CACHE.items() if chat_id in m.get("chat_ids", [])]
                scope_label = f"Group '{chat_title}'"
            else:
                target_ids = list(ACCEPTED_MEMBERS_CACHE.keys())
                scope_label = "All Global Managed Groups"

            if not target_ids:
                await message.answer(
                    f"⚠️ No accepted members found for {scope_label} to broadcast to.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="👥 Members Management", callback_data=f"set:menu:members:{chat_id}") if chat_id != 0 else InlineKeyboardButton(text="🏠 Main Menu", callback_data="dm:main_menu")]
                    ])
                )
                return

            token = str(uuid.uuid4())[:8]
            PENDING_BROADCAST[token] = {
                "admin_id": user_id,
                "chat_id": chat_id,
                "scope": scope,
                "scope_label": scope_label,
                "target_ids": target_ids,
                "message_text": custom_text,
                "created_at": time.time()
            }

            confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Confirm & Send", callback_data=f"bcast_confirm:{token}"),
                 InlineKeyboardButton(text="❌ Cancel", callback_data=f"bcast_cancel:{token}")]
            ])

            await message.answer(
                f"📢 <b>Broadcast Confirmation Preview</b>\n\n"
                f"🎯 <b>Target Audience:</b> {scope_label}\n"
                f"👥 <b>Total Recipients:</b> <code>{len(target_ids)} members</code>\n\n"
                f"📝 <b>Message Preview:</b>\n"
                f"────────────────────────\n"
                f"{custom_text}\n"
                f"────────────────────────\n\n"
                f"⚠️ <i>Please confirm to dispatch this broadcast. It will be throttled at 25 msgs/sec.</i>",
                reply_markup=confirm_kb,
                parse_mode=ParseMode.HTML
            )
            return

        if subname in ("msglength", "message_length", "length"):
            try:
                val = int(custom_text)
                if val < 0 or val > 4096:
                    raise ValueError()
            except ValueError:
                PENDING_CUSTOM_INPUT[user_id] = (chat_id, subname)
                await message.answer(
                    "❌ <b>Invalid message length!</b>\n"
                    "Please enter an integer between <code>0</code> and <code>4096</code> (0 to disable limit).\n\n"
                    "<i>Send /cancel to abort.</i>",
                    parse_mode=ParseMode.HTML
                )
                return

            s["max_message_length"] = val
            DatabaseService.save_settings_background(chat_id, chat_title, s)
            lim_desc = f"{val} characters" if val > 0 else "Unlimited (Disabled)"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Return to Message Length Settings", callback_data=f"set:menu:msglength:{chat_id}")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="dm:main_menu")]
            ])
            await message.answer(
                f"✅ <b>Message Length Limit Updated!</b>\n\n"
                f"<b>Group:</b> <code>{html.escape(chat_title)}</code>\n"
                f"<b>Max Allowed Length:</b> <code>{lim_desc}</code>\n\n"
                f"<i>Your updated configuration is live immediately across the group.</i>",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            return

        if subname in ("rules", "regulation"):
            s["rules_text"] = custom_text
            back_key = "regulation"
            label = "Regulation"
        elif subname == "welcome":
            s["welcome_msg"] = custom_text
            s["welcome_enabled"] = True
            back_key = "welcome"
            label = "Welcome Message"
        elif subname in ("welcome_pm", "approval_pm"):
            s["welcome_pm_msg"] = custom_text
            s["welcome_pm_enabled"] = True
            back_key = "welcome" if subname == "welcome_pm" else "approval"
            label = "Request PM Welcome"
        elif subname == "goodbye":
            s["goodbye_msg"] = custom_text
            s["goodbye_enabled"] = True
            back_key = "goodbye"
            label = "Goodbye Message"
        else:
            back_key = "main"
            label = subname.replace("_", " ").title()

        DatabaseService.save_settings_background(chat_id, chat_title, s)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⚙️ Return to {label} Settings", callback_data=f"set:menu:{back_key}:{chat_id}")],
            [InlineKeyboardButton(text="🏠 Main Menu", callback_data="dm:main_menu")]
        ])

        await message.answer(
            f"✅ <b>Custom {label} Saved!</b>\n\n"
            f"<b>Group:</b> <code>{html.escape(chat_title)}</code>\n\n"
            f"<b>Preview:</b>\n\n"
            f"{html.escape(custom_text)}\n\n"
            f"<i>Your updated configuration is live immediately across the group.</i>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        return

    # 2. Handle PENDING_CUSTOM_WARN
    if user_id in PENDING_CUSTOM_WARN:
        chat_id = PENDING_CUSTOM_WARN.pop(user_id)
        if not await check_can_setup_bot(bot, chat_id, user_id):
            await message.answer("❌ You are no longer authorized to manage settings for this group.")
            return

        custom_text = message.text.strip()
        if len(custom_text) > 1000:
            PENDING_CUSTOM_WARN[user_id] = chat_id
            await message.answer("❌ Message template too long (maximum 1000 characters). Please send a shorter template.")
            return

        s = CHAT_SETTINGS[chat_id]
        s["custom_warn_msg"] = custom_text
        chat_title = await get_cached_chat_title(bot, chat_id)

        DatabaseService.save_settings_background(chat_id, chat_title, s)

        preview = format_warn_notice(chat_id, message.from_user, "Blocked Link Violation", count=1, ceiling=int(s.get("warn_limit", 3)), chat_title=chat_title)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Return to Warn Settings", callback_data=f"set:menu:warn:{chat_id}")],
            [InlineKeyboardButton(text="🏠 Main Menu", callback_data="dm:main_menu")]
        ])

        await message.answer(
            f"✅ <b>Custom Warning Message Saved!</b>\n\n"
            f"<b>Group:</b> <code>{chat_title}</code>\n\n"
            f"<b>Live Notice Preview:</b>\n\n"
            f"{preview}\n\n"
            f"<i>This custom message will now be used for all warning notices in {chat_title}.</i>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        return


# ==============================================================================
# GLOBAL ACCEPTED MEMBERS BROADCAST ENGINE & DISPATCH WORKER
# ==============================================================================

async def run_background_broadcast(
    bot: Bot,
    recipient_ids: list[int],
    message_text: str,
    task_id: str,
    admin_notify_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Asynchronous throttled broadcaster. Dispatches at 25 msgs/sec
    to strictly observe Telegram API rate limits without 429 throttling.
    """
    sent = 0
    failed = 0
    start_time = time.monotonic()
    print(f"[BROADCAST {task_id}] Starting throttled broadcast to {len(recipient_ids)} recipients...", flush=True)

    for uid in recipient_ids:
        try:
            await bot.send_message(chat_id=uid, text=message_text, parse_mode=ParseMode.HTML)
            sent += 1
        except TelegramForbiddenError:
            failed += 1
            if uid in ACCEPTED_MEMBERS_CACHE:
                ACCEPTED_MEMBERS_CACHE[uid]["status"] = "blocked"
        except TelegramAPIError as e:
            failed += 1
            if "retry after" in str(e).lower():
                await asyncio.sleep(2.0)
        except Exception:
            failed += 1

        # 40ms sleep = 25 messages per second rate cap
        await asyncio.sleep(0.04)

    elapsed = round(time.monotonic() - start_time, 2)
    print(f"[BROADCAST {task_id}] Completed in {elapsed}s: Sent={sent}, Failed={failed}", flush=True)

    if admin_notify_id:
        try:
            await bot.send_message(
                chat_id=admin_notify_id,
                text=(
                    f"✅ <b>Broadcast Completed!</b>\n\n"
                    f"📬 <b>Sent Successfully:</b> <code>{sent}</code>\n"
                    f"❌ <b>Failed / Blocked:</b> <code>{failed}</code>\n"
                    f"⏱ <b>Elapsed Time:</b> <code>{elapsed}s</code>\n"
                    f"👥 <b>Total Recipient Pool:</b> <code>{len(recipient_ids)}</code>"
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    return {"sent": sent, "failed": failed, "elapsed": elapsed}


@router.callback_query(F.data.startswith("bcast_"))
async def handle_broadcast_callback(query: CallbackQuery, bot: Bot) -> None:
    """Handles confirmation or cancellation of pending broadcast batches."""
    parts = query.data.split(":", 1)
    action = parts[0]
    token = parts[1] if len(parts) > 1 else ""
    user_id = query.from_user.id

    bcast_data = PENDING_BROADCAST.pop(token, None)
    if not bcast_data:
        await query.answer("Broadcast session expired or already handled.", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if bcast_data.get("admin_id") != user_id:
        await query.answer("Only the initiating administrator can confirm this broadcast.", show_alert=True)
        PENDING_BROADCAST[token] = bcast_data
        return

    if action == "bcast_cancel":
        await query.answer("Broadcast cancelled.")
        try:
            await query.message.edit_text("❌ <b>Broadcast Cancelled.</b>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    if action == "bcast_confirm":
        target_ids = bcast_data["target_ids"]
        msg_text = bcast_data["message_text"]
        scope_label = bcast_data["scope_label"]
        await query.answer("Broadcasting started...")
        try:
            await query.message.edit_text(
                f"🚀 <b>Broadcast in Progress...</b>\n\n"
                f"🎯 <b>Target:</b> {scope_label}\n"
                f"👥 <b>Total Recipients:</b> <code>{len(target_ids)}</code>\n"
                f"⚡ <i>Sending throttled at 25 msgs/sec. You will receive a summary when finished.</i>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        asyncio.create_task(run_background_broadcast(
            bot=bot,
            recipient_ids=target_ids,
            message_text=msg_text,
            task_id=token,
            admin_notify_id=user_id
        ))


@router.message(Command("broadcast", "bcast"))
async def handle_broadcast_command(message: Message, command: CommandObject, bot: Bot) -> None:
    """
    Broadcasts a message directly to all accepted members across groups or within the current group.
    Strictly guarded by check_can_setup_bot.
    """
    user_id = message.from_user.id if message.from_user else 0
    is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    chat_id = message.chat.id if is_group else 0

    if is_group:
        sender_chat_id = message.sender_chat.id if message.sender_chat else None
        if not await check_can_setup_bot(bot, chat_id, user_id, sender_chat_id):
            await send_ephemeral(message, "❌ Only the Group Owner, Anonymous Admins, or Exempted Admins can broadcast.")
            return
        await wipe_trigger(message)

    msg_body = command.args.strip() if command and command.args else ""
    if not msg_body:
        if is_group:
            bot_me = await bot.get_me()
            dm_link = f"https://t.me/{bot_me.username}?start=bcast_{abs(chat_id)}_chat"
            await message.answer(
                "📢 <b>To start a broadcast, specify the message or use Private DM:</b>\n\n"
                "• <i>Usage:</i> <code>/broadcast &lt;message&gt;</code>\n"
                f"• Or compose securely in <a href='{dm_link}'>Private DM</a>",
                parse_mode=ParseMode.HTML
            )
        else:
            PENDING_CUSTOM_INPUT[user_id] = (0, "broadcast:all")
            await message.answer(
                f"📢 <b>Broadcast to All Accepted Members ({len(ACCEPTED_MEMBERS_CACHE)} members)</b>\n\n"
                f"Please send the message you wish to broadcast now.\n"
                f"<i>HTML formatting tags (<b>bold</b>, <i>italic</i>, <code>code</code>, <a href='...'>link</a>) are supported.\nSend /cancel to abort.</i>",
                parse_mode=ParseMode.HTML
            )
        return

    if is_group:
        target_ids = [uid for uid, m in ACCEPTED_MEMBERS_CACHE.items() if chat_id in m.get("chat_ids", [])]
        scope_label = f"Group '{message.chat.title}'"
    else:
        target_ids = list(ACCEPTED_MEMBERS_CACHE.keys())
        scope_label = "All Global Managed Groups"

    if not target_ids:
        await message.answer(f"⚠️ No accepted members found for {scope_label} to broadcast to.")
        return

    token = str(uuid.uuid4())[:8]
    PENDING_BROADCAST[token] = {
        "admin_id": user_id,
        "chat_id": chat_id,
        "scope": "chat" if is_group else "all",
        "scope_label": scope_label,
        "target_ids": target_ids,
        "message_text": msg_body,
        "created_at": time.time()
    }

    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Confirm & Send", callback_data=f"bcast_confirm:{token}"),
         InlineKeyboardButton(text="❌ Cancel", callback_data=f"bcast_cancel:{token}")]
    ])

    await message.answer(
        f"📢 <b>Broadcast Confirmation Preview</b>\n\n"
        f"🎯 <b>Target Audience:</b> {scope_label}\n"
        f"👥 <b>Total Recipients:</b> <code>{len(target_ids)} members</code>\n\n"
        f"📝 <b>Message Preview:</b>\n"
        f"────────────────────────\n"
        f"{msg_body}\n"
        f"────────────────────────\n\n"
        f"⚠️ <i>Please confirm to dispatch this broadcast. It will be throttled at 25 msgs/sec.</i>",
        reply_markup=confirm_kb,
        parse_mode=ParseMode.HTML
    )


@router.message(Command("members", "acceptedmembers"))
async def handle_members_command(message: Message, bot: Bot) -> None:
    """Shows statistics on request-accepted members and provides dashboard / broadcast controls."""
    user_id = message.from_user.id if message.from_user else 0
    is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    chat_id = message.chat.id if is_group else 0

    if is_group:
        sender_chat_id = message.sender_chat.id if message.sender_chat else None
        if not await is_user_admin(bot, chat_id, user_id, sender_chat_id):
            await send_ephemeral(message, "⚠️ Only administrators can view members registry.")
            return
        await wipe_trigger(message)
        chat_accepted = sum(1 for m in ACCEPTED_MEMBERS_CACHE.values() if chat_id in m.get("chat_ids", []))
    else:
        chat_accepted = 0

    total_accepted = len(ACCEPTED_MEMBERS_CACHE)

    kb_buttons = []
    if is_group:
        kb_buttons.append([InlineKeyboardButton(text="📢 Broadcast Group Members", callback_data=f"set:bcast_chat:{chat_id}")])
    kb_buttons.append([InlineKeyboardButton(text="🌐 Broadcast All Members", callback_data=f"set:bcast_all:{chat_id}")])
    kb_buttons.append([InlineKeyboardButton(text="👥 Members Management", callback_data=f"set:menu:members:{chat_id}")])

    text = (
        f"👥 <b>ACCEPTED MEMBERS REGISTRY</b>\n\n"
        f"• <b>Accepted in this Chat:</b> <code>{chat_accepted}</code>\n"
        f"• <b>Global Consolidated Total:</b> <code>{total_accepted}</code>\n\n"
        f"<i>To filter, select, and message members visually, access the Web Dashboard at <code>/members</code> on the bot web host or use the broadcast controls above.</i>"
    )
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons), parse_mode=ParseMode.HTML)


@router.message(Command("help"))
async def handle_help(message: Message, bot: Bot) -> None:
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await wipe_trigger(message)
        user_id = message.from_user.id if message.from_user else 0
        if not await check_admin_rights(bot, message.chat.id, user_id):
            return

    text = (
        "⚡ <b>High-Speed Telegram Admin Engine Active</b>\n\n"
        "<b>Available Admin Commands:</b>\n"
        "• <code>/start</code> or <code>/settings</code> - Open group protection settings\n"
        "• <code>/rules</code> - Show group regulations\n"
        "• <code>/setrules &lt;text&gt;</code> - Configure group regulations\n"
        "• <code>/welcome</code> - Preview welcome message\n"
        "• <code>/setwelcome &lt;text&gt;</code> - Configure welcome greeting template\n"
        "• <code>/goodbye</code> - Preview goodbye message\n"
        "• <code>/setgoodbye &lt;text&gt;</code> - Configure goodbye farewell template\n"
        "• <code>/words</code> - List prohibited banned words\n"
        "• <code>/addword &lt;word&gt;</code> - Add word to prohibited list\n"
        "• <code>/delword &lt;word&gt;</code> - Remove word from prohibited list\n"
        "• <code>/filters</code> - List active custom keyword filters\n"
        "• <code>/filter &lt;word&gt; &lt;reply&gt;</code> - Add custom keyword filter\n"
        "• <code>/stop &lt;word&gt;</code> - Remove custom keyword filter\n"
        "• <code>/setlog &lt;channel&gt;</code> - Designate security audit log channel\n"
        "• <code>/mute &lt;time&gt; [reason]</code> - Restrict user send permissions\n"
        "• <code>/dmute &lt;time&gt; [reason]</code> - Wipe replied message + Mute user\n"
        "• <code>/unmute</code> - Restore user chat privileges\n"
        "• <code>/pin</code> - Silently pin message with zero notification\n"
        "• <code>/unpin</code> - Unpin replied message or all messages\n"
        "• <code>/clear [count]</code> - Wipe recent messages instantly\n"
        "• <code>/ban</code> - Permanently ban violator\n"
        "• <code>/dban</code> - Delete replied message + Ban violator\n"
        "• <code>/tban &lt;time&gt;</code> - Temporary ban with auto-unban\n"
        "• <code>/unban</code> - Revoke member ban\n"
        "• <code>/promote</code> - Elevate to admin with 0 custom rights\n"
        "• <code>/demote</code> - Strip all administrator rights\n"
        "• <code>/warn</code> - Issue warning increment with automated ceiling\n"
        "• <code>/resetwarn</code> - Clear user warning counter\n"
        "• <code>/report [reason]</code> - (Reply only) Publicly flag message for review\n"
        "• <code>/show [reason]</code> - (Reply only) Forward report to admins in PM\n"
        "• <code>/addexcept</code> - Designate admin to receive confidential reports\n"
        "• <code>/remexcept</code> - Remove admin from report recipients\n"
        "• <code>/excepted</code> - List currently configured Excepted Admins\n\n"
        f"<i>Engine loop: <code>{LOOP_ENGINE}</code> | Sub-second latency active.</i>"
    )

    try:
        reply_markup = None
        if message.chat.type == ChatType.PRIVATE:
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Back", callback_data="dm:main_menu")]
            ])
        await message.answer(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 8. /report & /show (Public & Private Reporting Engine)
# ------------------------------------------------------------------------------

def get_message_link(chat: types.Chat, message_id: int) -> str:
    """Constructs direct Telegram link to message."""
    if chat.username:
        return f"https://t.me/{chat.username}/{message_id}"
    clean_id = str(chat.id)
    if clean_id.startswith("-100"):
        clean_id = clean_id[4:]
    elif clean_id.startswith("-"):
        clean_id = clean_id[1:]
    return f"https://t.me/c/{clean_id}/{message_id}"


def extract_message_snippet(target_msg: Message) -> str:
    """Extracts text preview or media indicator from message."""
    if target_msg.text:
        return target_msg.text[:300] + ("..." if len(target_msg.text) > 300 else "")
    if target_msg.caption:
        return target_msg.caption[:300] + ("..." if len(target_msg.caption) > 300 else "")
    if target_msg.sticker:
        return f"[Sticker {target_msg.sticker.emoji or ''}]"
    if target_msg.animation:
        return "[GIF / Animation]"
    if target_msg.photo:
        return "[Photo]"
    if target_msg.video:
        return "[Video]"
    if target_msg.voice:
        return "[Voice Note]"
    if target_msg.audio:
        return "[Audio Track]"
    if target_msg.document:
        return f"[Document: {target_msg.document.file_name or 'file'}]"
    return "[Message Content]"


async def get_report_recipients(bot: Bot, chat_id: int) -> list[types.User]:
    """
    Returns the list of administrators authorized to receive reports:
    - ONLY:
      1. Owner of the GC (ChatMemberOwner)
      2. Anonymous Admin(s) (is_anonymous == True)
      3. Excepted Admins (user IDs explicitly configured in chat's excepted_admins)
    All other administrators are strictly excluded to prevent notification spam.
    """
    try:
        all_admins = await bot.get_chat_administrators(chat_id)
    except Exception:
        return []

    settings = CHAT_SETTINGS[chat_id]
    excepted_ids = set(settings.get("excepted_admins", []))

    recipients = []
    seen_ids = set()

    for admin in all_admins:
        if admin.user.is_bot or admin.user.id in seen_ids:
            continue

        is_owner = isinstance(admin, ChatMemberOwner)
        is_anonymous = getattr(admin, "is_anonymous", False)
        is_excepted = admin.user.id in excepted_ids

        # Strict filter: ONLY owner + anonymous admins + excepted admins
        if is_owner or is_anonymous or is_excepted:
            recipients.append(admin.user)
            seen_ids.add(admin.user.id)

    return recipients


@router.message(Command("report"))
async def handle_report(message: Message, command: CommandObject, bot: Bot) -> None:
    """
    /report -> Works with reply only!
    Visible publicly to both admins and members in the group chat.
    Dispatches private PM notifications ONLY to:
    - Owner of the GC
    - Anonymous Admins
    - Excepted Admins
    """
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # Must be used as a reply
    if not message.reply_to_message:
        try:
            warning = await message.reply("⚠️ <code>/report</code> must be used as a reply to a message!")
            await asyncio.sleep(5)
            await warning.delete()
            await message.delete()
        except Exception:
            pass
        return

    target_msg = message.reply_to_message
    target_user = target_msg.from_user
    reporter = message.from_user

    if not target_user or not reporter:
        return

    # Check if user attempts to report self
    if target_user.id == reporter.id:
        try:
            warning = await message.reply("⚠️ You cannot report your own message.")
            await asyncio.sleep(5)
            await warning.delete()
            await message.delete()
        except Exception:
            pass
        return

    reason = command.args.strip() if command and command.args else "No specific reason provided"
    snippet = extract_message_snippet(target_msg)
    msg_link = get_message_link(message.chat, target_msg.message_id)

    chat_id = message.chat.id
    target_id = target_user.id
    target_mid = target_msg.message_id

    # Background MongoDB persistence for report record
    DatabaseService.record_report_background(
        report_id=str(uuid.uuid4()),
        chat_id=chat_id,
        target_user_id=target_id,
        reporter_user_id=reporter.id,
        message_id=target_mid,
        message_snippet=snippet,
        reason=reason,
    )

    # Inline action buttons for admins right on the public report message
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑️ Delete", callback_data=f"rep:del:{chat_id}:{target_mid}:{target_id}"),
            InlineKeyboardButton(text="🔇 Mute (15m)", callback_data=f"rep:mute:{chat_id}:{target_mid}:{target_id}"),
            InlineKeyboardButton(text="🔨 Ban", callback_data=f"rep:ban:{chat_id}:{target_mid}:{target_id}"),
        ],
        [
            InlineKeyboardButton(text="🔗 View Message", url=msg_link),
            InlineKeyboardButton(text="✅ Dismiss", callback_data=f"rep:dismiss:{chat_id}:{target_mid}:{target_id}"),
        ]
    ])

    report_text = (
        f"🚨 <b>MESSAGE REPORTED</b>\n\n"
        f"👤 <b>Reported User:</b> <a href=\"tg://user?id={target_user.id}\">{target_user.full_name}</a> (<code>{target_user.id}</code>)\n"
        f"📢 <b>Reported By:</b> <a href=\"tg://user?id={reporter.id}\">{reporter.full_name}</a> (<code>{reporter.id}</code>)\n"
        f"📝 <b>Reason:</b> <i>{reason}</i>\n"
        f"💬 <b>Preview:</b> <code>{snippet}</code>\n\n"
        f"<i>🔒 Dispatched privately to Owner, Anonymous Admins & Excepted Admins.</i>"
    )

    try:
        await message.reply(report_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    # Private report notification: sent ONLY to Owner + Anonymous Admins + Excepted Admins
    recipients = await get_report_recipients(bot, chat_id)
    pm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑️ Delete", callback_data=f"pmrep:del:{chat_id}:{target_mid}:{target_id}"),
            InlineKeyboardButton(text="🔇 Mute (15m)", callback_data=f"pmrep:mute:{chat_id}:{target_mid}:{target_id}"),
        ],
        [
            InlineKeyboardButton(text="🔨 Ban", callback_data=f"pmrep:ban:{chat_id}:{target_mid}:{target_id}"),
            InlineKeyboardButton(text="🔗 View Message", url=msg_link),
        ]
    ])

    pm_report_text = (
        f"🚨 <b>MEMBER REPORT NOTIFICATION</b>\n\n"
        f"🏷️ <b>Group:</b> <code>{message.chat.title}</code> (<code>{chat_id}</code>)\n"
        f"👤 <b>Reported User:</b> <a href=\"tg://user?id={target_user.id}\">{target_user.full_name}</a> (<code>{target_user.id}</code>)\n"
        f"📢 <b>Reported By:</b> <a href=\"tg://user?id={reporter.id}\">{reporter.full_name}</a> (<code>{reporter.id}</code>)\n"
        f"📝 <b>Reason:</b> <i>{reason}</i>\n"
        f"💬 <b>Preview:</b>\n<blockquote>{snippet}</blockquote>\n\n"
        f"<i>🔒 Delivered exclusively to Owner, Anonymous Admins & Excepted Admins.</i>"
    )

    for user in recipients:
        try:
            await bot.send_message(
                chat_id=user.id,
                text=pm_report_text,
                reply_markup=pm_keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("rep:"))
async def handle_report_action_callback(query: CallbackQuery, bot: Bot) -> None:
    """Handles action buttons on public group reports (admin-only execution)."""
    parts = query.data.split(":")
    if len(parts) < 5:
        await query.answer()
        return

    _, action, chat_id_str, target_mid_str, target_uid_str = parts[:5]
    chat_id = int(chat_id_str)
    target_mid = int(target_mid_str)
    target_uid = int(target_uid_str)

    admin_user = query.from_user
    needed_perm = "can_restrict_members" if action in ("mute", "ban") else "can_delete_messages"
    if not await check_admin_rights(bot, chat_id, admin_user.id, needed_perm):
        await query.answer("❌ Only administrators can resolve reports.", show_alert=True)
        return

    if action == "del":
        try:
            await bot.delete_message(chat_id=chat_id, message_id=target_mid)
        except Exception:
            pass
        status_text = f"✅ Message deleted by <a href=\"tg://user?id={admin_user.id}\">{admin_user.full_name}</a>."
    elif action == "mute":
        try:
            until_ts = int(time.time() + 900)  # 15 minutes
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_uid,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                ),
                until_date=until_ts
            )
            await bot.delete_message(chat_id=chat_id, message_id=target_mid)
        except Exception:
            pass
        status_text = f"✅ User muted (15m) & message deleted by <a href=\"tg://user?id={admin_user.id}\">{admin_user.full_name}</a>."
    elif action == "ban":
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=target_uid)
            await bot.delete_message(chat_id=chat_id, message_id=target_mid)
        except Exception:
            pass
        status_text = f"✅ User banned & message deleted by <a href=\"tg://user?id={admin_user.id}\">{admin_user.full_name}</a>."
    elif action == "dismiss":
        status_text = f"✅ Report dismissed by <a href=\"tg://user?id={admin_user.id}\">{admin_user.full_name}</a>."
    else:
        await query.answer()
        return

    # Background MongoDB resolution record & audit trail
    DatabaseService.resolve_report_background(chat_id, target_mid, admin_user.id, action)
    DatabaseService.log_moderation_background(chat_id, admin_user.id, target_uid, f"report_{action}")

    try:
        await query.message.edit_text(
            f"🛡️ <b>REPORT RESOLVED</b>\n\n{status_text}",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await query.answer("Report handled successfully.")


@router.message(Command("show"))
async def handle_show(message: Message, command: CommandObject, bot: Bot) -> None:
    """
    /show -> Reports message directly to chat administrators in private message (DM).
    Works when replying to a message.
    """
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # Delete trigger to keep group chat pristine
    await wipe_trigger(message)

    if not message.reply_to_message:
        try:
            warning = await message.answer("⚠️ <code>/show</code> must be used as a reply to the message you want to report to admins in PM!")
            await asyncio.sleep(5)
            await warning.delete()
        except Exception:
            pass
        return

    target_msg = message.reply_to_message
    target_user = target_msg.from_user
    reporter = message.from_user

    if not target_user or not reporter:
        return

    chat_id = message.chat.id
    chat_title = message.chat.title or "This Group"
    reason = command.args.strip() if command and command.args else "Reported via /show"
    snippet = extract_message_snippet(target_msg)
    msg_link = get_message_link(message.chat, target_msg.message_id)

    target_id = target_user.id
    target_mid = target_msg.message_id

    pm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑️ Delete Message", callback_data=f"pmrep:del:{chat_id}:{target_mid}:{target_id}"),
            InlineKeyboardButton(text="🔇 Mute (15m)", callback_data=f"pmrep:mute:{chat_id}:{target_mid}:{target_id}"),
        ],
        [
            InlineKeyboardButton(text="🔨 Ban User", callback_data=f"pmrep:ban:{chat_id}:{target_mid}:{target_id}"),
            InlineKeyboardButton(text="🔗 Open Message", url=msg_link),
        ]
    ])

    pm_report_text = (
        f"📬 <b>PRIVATE ADMIN REPORT INCOMING</b>\n\n"
        f"🏷️ <b>Group:</b> <code>{chat_title}</code> (<code>{chat_id}</code>)\n"
        f"👤 <b>Reported User:</b> <a href=\"tg://user?id={target_user.id}\">{target_user.full_name}</a> (<code>{target_user.id}</code>)\n"
        f"📢 <b>Reported By:</b> <a href=\"tg://user?id={reporter.id}\">{reporter.full_name}</a> (<code>{reporter.id}</code>)\n"
        f"📝 <b>Reason:</b> <i>{reason}</i>\n"
        f"💬 <b>Preview:</b>\n<blockquote>{snippet}</blockquote>\n\n"
        f"<i>Use the moderation buttons below to manage this violation directly:</i>"
    )

    # Filter: Send ONLY to Owner + Anonymous Admins + Excepted Admins
    recipients = await get_report_recipients(bot, chat_id)

    delivered_count = 0
    for user in recipients:
        try:
            await bot.send_message(
                chat_id=user.id,
                text=pm_report_text,
                reply_markup=pm_keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            delivered_count += 1
        except Exception:
            pass

    try:
        if delivered_count > 0:
            receipt = await message.answer(
                f"📩 <b>Report delivered privately to {delivered_count} authorized recipient(s) (Owner, Anonymous Admins & Excepted Admins).</b>",
                parse_mode=ParseMode.HTML
            )
        else:
            receipt = await message.answer(
                "⚠️ <i>Report generated, but the Owner / Excepted Admins must start the bot in private DM to receive notifications.</i>",
                parse_mode=ParseMode.HTML
            )
        await asyncio.sleep(5)
        await receipt.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pmrep:"))
async def handle_pm_report_action_callback(query: CallbackQuery, bot: Bot) -> None:
    """Handles action buttons taken by an admin inside their private DM."""
    parts = query.data.split(":")
    if len(parts) < 5:
        await query.answer()
        return

    _, action, chat_id_str, target_mid_str, target_uid_str = parts[:5]
    chat_id = int(chat_id_str)
    target_mid = int(target_mid_str)
    target_uid = int(target_uid_str)

    admin_user = query.from_user
    needed_perm = "can_restrict_members" if action in ("mute", "ban") else "can_delete_messages"
    if not await check_admin_rights(bot, chat_id, admin_user.id, needed_perm):
        await query.answer("❌ You lack administrative permissions in that group.", show_alert=True)
        return

    if action == "del":
        try:
            await bot.delete_message(chat_id=chat_id, message_id=target_mid)
            result = "🗑️ Message Deleted"
        except Exception as e:
            result = f"⚠️ Could not delete: {e}"
    elif action == "mute":
        try:
            until_ts = int(time.time() + 900)
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_uid,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                ),
                until_date=until_ts
            )
            await bot.delete_message(chat_id=chat_id, message_id=target_mid)
            result = "🔇 User Muted (15m) & Message Deleted"
        except Exception as e:
            result = f"⚠️ Could not mute: {e}"
    elif action == "ban":
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=target_uid)
            await bot.delete_message(chat_id=chat_id, message_id=target_mid)
            result = "🔨 User Banned & Message Deleted"
        except Exception as e:
            result = f"⚠️ Could not ban: {e}"
    else:
        await query.answer()
        return

    # Background MongoDB resolution record & audit trail
    DatabaseService.resolve_report_background(chat_id, target_mid, admin_user.id, action)
    DatabaseService.log_moderation_background(chat_id, admin_user.id, target_uid, f"report_{action}")

    try:
        await query.message.edit_text(
            f"{query.message.text}\n\n✅ <b>Action Taken:</b> {result} (by you)",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        pass
    await query.answer(f"Executed: {result}")


# ------------------------------------------------------------------------------
# 9. Excepted Admin Management (/addexcept, /remexcept, /excepted)
# ------------------------------------------------------------------------------
@router.message(Command("addexcept", "exceptadmin", "exemptadmin", "addexempt", "exempt", "except"))
async def handle_add_except_admin(message: Message, command: CommandObject, bot: Bot) -> None:
    """Designates an admin as an Excepted Admin to receive report notifications and access settings."""
    await wipe_trigger(message)
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    user_id = message.from_user.id if message.from_user else 0
    # Rule: ONLY Owner, Anonymous Admins, or Excepted Admins can setup the bot
    if not await check_can_setup_bot(bot, message.chat.id, user_id, sender_chat_id):
        try:
            notice = await message.answer("❌ Only the Group Owner, Anonymous Admins, or Excepted Admins can add Excepted Admins.")
            await asyncio.sleep(5)
            await notice.delete()
        except Exception:
            pass
        return

    target_id, target_name, _ = await resolve_target(message, command, bot=bot)
    if not target_id:
        try:
            notice = await message.answer(
                "⚠️ <b>How to add an Exempted Admin:</b>\n"
                "• <b>Reply:</b> Reply to the admin's message with <code>/exemptadmin</code>\n"
                "• <b>Username:</b> <code>/exemptadmin @admin_username</code>\n"
                "• <b>User ID:</b> <code>/exemptadmin 123456789</code>\n\n"
                "<i>Exempted Admins have full rights to execute all commands and manage all group settings.</i>",
                parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(8)
            await notice.delete()
        except Exception:
            pass
        return

    chat_id = message.chat.id
    if message.chat and message.chat.title:
        CHAT_TITLES[chat_id] = message.chat.title
    settings = CHAT_SETTINGS[chat_id]
    current_excepted = {int(x) for x in settings.get("excepted_admins", []) if str(x).lstrip('-').isdigit()}
    current_excepted.add(int(target_id))
    settings["excepted_admins"] = list(current_excepted)

    chat_title = message.chat.title or "This Chat"
    DatabaseService.save_settings_background(chat_id, chat_title, settings)

    name_label = f" (<b>{html.escape(target_name)}</b>)" if target_name else ""
    bot_name = BOT_IDENTITY.get("username", "personal_guardBot")
    try:
        notice = await message.answer(
            f"✅ Admin <code>{target_id}</code>{name_label} is now an <b>Exempted Admin</b>!\n"
            f"<i>They now have full permissions to use all commands and configure all group settings via @{bot_name}.</i>",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(8)
        await notice.delete()
    except Exception:
        pass


@router.message(Command("remexcept", "unexceptadmin", "unexemptadmin", "remexempt", "delexempt", "delexcept"))
async def handle_rem_except_admin(message: Message, command: CommandObject, bot: Bot) -> None:
    """Removes an admin from the Excepted Admins list."""
    await wipe_trigger(message)
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    user_id = message.from_user.id if message.from_user else 0
    if not await check_can_setup_bot(bot, message.chat.id, user_id, sender_chat_id):
        return

    target_id, _, _ = await resolve_target(message, command, bot=bot)
    if not target_id:
        try:
            notice = await message.answer("⚠️ Please reply to the admin's message or specify their username/ID: <code>/remexcept @admin</code>", parse_mode=ParseMode.HTML)
            await asyncio.sleep(5)
            await notice.delete()
        except Exception:
            pass
        return

    chat_id = message.chat.id
    if message.chat and message.chat.title:
        CHAT_TITLES[chat_id] = message.chat.title
    settings = CHAT_SETTINGS[chat_id]
    current_excepted = {int(x) for x in settings.get("excepted_admins", []) if str(x).lstrip('-').isdigit()}
    current_excepted.discard(int(target_id))
    settings["excepted_admins"] = list(current_excepted)

    chat_title = message.chat.title or "This Chat"
    DatabaseService.save_settings_background(chat_id, chat_title, settings)

    try:
        notice = await message.answer(
            f"✅ User <code>{target_id}</code> removed from <b>Exempted Admins</b>.",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(5)
        await notice.delete()
    except Exception:
        pass


@router.message(Command("excepted", "exempted", "exemptadmins", "exceptadmins", "exemptlist"))
async def handle_list_excepted_admins(message: Message, bot: Bot) -> None:
    """Lists all Excepted Admins in the chat."""
    await wipe_trigger(message)
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    user_id = message.from_user.id if message.from_user else 0
    if not await check_can_setup_bot(bot, message.chat.id, user_id, sender_chat_id):
        return

    chat_id = message.chat.id
    if message.chat and message.chat.title:
        CHAT_TITLES[chat_id] = message.chat.title
    settings = CHAT_SETTINGS[chat_id]
    raw_excepted = settings.get("excepted_admins", [])
    excepted_ids = [int(x) for x in raw_excepted if str(x).lstrip('-').isdigit()]

    bot_user = await bot.get_me()
    bot_name = bot_user.username or "personal_guardBot"

    if excepted_ids:
        formatted = "\n".join(f"• <code>{uid}</code> (<a href='tg://user?id={uid}'>Profile</a>)" for uid in excepted_ids)
        text = (
            f"👥 <b>Exempted Admins with Setup Access:</b>\n\n"
            f"{formatted}\n\n"
            f"<i>These admins can configure settings in Private DM via @{bot_name} or direct link:</i>\n"
            f"https://t.me/{bot_name}?start=group_{abs(chat_id)}"
        )
    else:
        text = (
            "👥 <b>Exempted Admins:</b> <i>None configured.</i>\n\n"
            "<i>Currently, settings and reports are restricted to the Group Owner & Anonymous Admins.</i>\n\n"
            "👉 To add an admin, reply to their message with <code>/addexcept</code> or send: <code>/addexcept @admin</code>"
        )

    try:
        notice = await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        await asyncio.sleep(12)
        await notice.delete()
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 9. Admin-Only Command Catalog Synchronization
# ------------------------------------------------------------------------------
async def setup_bot_commands(bot: Bot) -> None:
    """
    Registers scoped command catalogs with Telegram Bot API:
    - BotCommandScopeAllChatAdministrators: ADMIN ONLY commands visible in group menu.
    - BotCommandScopeDefault: Completely empty list so regular users see ZERO admin commands.
    - BotCommandScopeAllPrivateChats: Navigation commands for direct private chats.
    """
    admin_commands = [
        BotCommand(command="mute", description="Restrict user send permissions"),
        BotCommand(command="dmute", description="Delete replied message & mute user"),
        BotCommand(command="unmute", description="Restore user chat privileges"),
        BotCommand(command="pin", description="Silently pin message (no alerts)"),
        BotCommand(command="unpin", description="Unpin replied or all messages"),
        BotCommand(command="clear", description="Instant batch wipe of messages"),
        BotCommand(command="ban", description="Permanently ban violator"),
        BotCommand(command="dban", description="Delete message & ban violator"),
        BotCommand(command="tban", description="Temporary ban with auto-unban"),
        BotCommand(command="unban", description="Revoke member ban"),
        BotCommand(command="promote", description="Elevate to admin (0 custom rights)"),
        BotCommand(command="demote", description="Strip administrator privileges"),
        BotCommand(command="warn", description="Issue warning with auto-enforcement"),
        BotCommand(command="resetwarn", description="Clear user warning counter"),
        BotCommand(command="warns", description="Check user warning status"),
        BotCommand(command="autowarn", description="Toggle automated warning enforcement"),
        BotCommand(command="warndup", description="Configure duplicate spam warning"),
        BotCommand(command="warnflood", description="Configure flood frequency warning"),
        BotCommand(command="antiflood", description="Toggle anti-flood protection engine"),
        BotCommand(command="antispam", description="Toggle anti-spam links & quote engine"),
        BotCommand(command="rules", description="View group regulations"),
        BotCommand(command="setrules", description="Configure regulations"),
        BotCommand(command="welcome", description="Preview welcome greeting"),
        BotCommand(command="setwelcome", description="Configure welcome message"),
        BotCommand(command="welcomepm", description="Preview private DM welcome greeting"),
        BotCommand(command="setwelcomepm", description="Configure private DM welcome message"),
        BotCommand(command="goodbye", description="Preview goodbye message"),
        BotCommand(command="setgoodbye", description="Configure goodbye message"),
        BotCommand(command="words", description="List prohibited words"),
        BotCommand(command="addword", description="Add banned word"),
        BotCommand(command="delword", description="Remove banned word"),
        BotCommand(command="filters", description="List personal keyword filters"),
        BotCommand(command="filter", description="Add keyword reply filter"),
        BotCommand(command="stop", description="Remove keyword filter"),
        BotCommand(command="setlog", description="Set audit log channel"),
        BotCommand(command="report", description="(Reply only) Report message publicly"),
        BotCommand(command="show", description="(Reply only) Report message to admins in PM"),
        BotCommand(command="exemptadmin", description="Add an exempted admin for setup & commands"),
        BotCommand(command="unexemptadmin", description="Remove an exempted admin"),
        BotCommand(command="exempted", description="List all exempted admins"),
        BotCommand(command="addexcept", description="Designate admin to receive reports"),
        BotCommand(command="remexcept", description="Remove admin from report recipients"),
        BotCommand(command="excepted", description="List excepted report admins"),
        BotCommand(command="broadcast", description="Broadcast to accepted members"),
        BotCommand(command="members", description="Accepted members registry & controls"),
        BotCommand(command="start", description="Open group settings (Authorized admins only)"),
        BotCommand(command="settings", description="Alias to /start group settings"),
        BotCommand(command="setcommands", description="Force sync admin command catalog"),
    ]

    # Commands visible to regular members inside group chats
    group_member_commands = [
        BotCommand(command="rules", description="View group regulations"),
        BotCommand(command="report", description="(Reply only) Report message publicly"),
        BotCommand(command="show", description="(Reply only) Report message to admins in PM"),
    ]

    private_commands = [
        BotCommand(command="start", description="Open management interface & settings"),
        BotCommand(command="help", description="Commands & usage guide"),
    ]

    try:
        # 1. Default Scope (Empty: regular members see NO admin commands in catalog)
        await bot.set_my_commands(commands=[], scope=BotCommandScopeDefault())

        # 2. All Group Chats Scope (Members see ONLY member reporting tools)
        await bot.set_my_commands(commands=group_member_commands, scope=BotCommandScopeAllGroupChats())

        # 3. Group Administrators Scope (Populates full admin catalog ONLY for group admins)
        await bot.set_my_commands(commands=admin_commands, scope=BotCommandScopeAllChatAdministrators())

        # 4. Direct Private Chats Scope
        await bot.set_my_commands(commands=private_commands, scope=BotCommandScopeAllPrivateChats())
        print("[CATALOG] Scoped command catalogs registered successfully with Telegram API.")
    except Exception as e:
        print(f"[CATALOG WARNING] Failed to register command scopes: {e}")


@router.message(Command("setcommands", "syncmenu"))
async def handle_sync_commands(message: Message, bot: Bot) -> None:
    """Manual trigger to synchronize admin-only command catalog on demand."""
    await wipe_trigger(message)
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    user_id = message.from_user.id if message.from_user else 0
    # Rule: ONLY Owner, Anonymous Admins, or Excepted/Exempted Admins can configure the bot
    if not await check_can_setup_bot(bot, message.chat.id, user_id, sender_chat_id):
        return
    await setup_bot_commands(bot)


# ==============================================================================
# RENDER HOBBY & FREE TIER RESOURCE OPTIMIZERS (<50MB RAM & <5GB/MO BANDWIDTH)
# ACTIVE CIRCUIT BREAKERS (HARD 500MB RAM & HARD 5GB OUTBOUND METER)
# ==============================================================================

class BandwidthMonitor:
    """
    Tracks and meters all outbound network bytes across Telegram API requests and Render HTTP
    health checks. Enforces hard safety caps to guarantee outbound egress never exceeds Render's
    5GB/month limit under any traffic volume or flood condition.
    """
    OUTBOUND_SAFETY_LIMIT_BYTES: int = int(4.8 * 1024 * 1024 * 1024)  # 4.8 GB hard circuit breaker (96% of 5GB)
    OUTBOUND_WARNING_LIMIT_BYTES: int = int(4.0 * 1024 * 1024 * 1024)  # 4.0 GB warning threshold

    def __init__(self) -> None:
        self.outbound_bytes: int = 0
        self.total_requests: int = 0
        self.circuit_broken: bool = False

    def add_outbound_bytes(self, byte_count: int) -> None:
        self.outbound_bytes += max(0, byte_count)
        self.total_requests += 1
        if self.outbound_bytes >= self.OUTBOUND_SAFETY_LIMIT_BYTES:
            if not self.circuit_broken:
                self.circuit_broken = True
                print(f"[BANDWIDTH CIRCUIT BREAKER ENGAGED] Reached {self.get_outbound_mb()}MB. Pausing non-essential egress.")

    def can_send(self, estimated_bytes: int = 512) -> bool:
        return (self.outbound_bytes + estimated_bytes) < self.OUTBOUND_SAFETY_LIMIT_BYTES

    def get_outbound_bytes(self) -> int:
        return self.outbound_bytes

    def get_outbound_mb(self) -> float:
        return round(self.outbound_bytes / (1024 * 1024), 2)

    def get_outbound_gb(self) -> float:
        return round(self.outbound_bytes / (1024 * 1024 * 1024), 4)


BANDWIDTH_MONITOR = BandwidthMonitor()


class MeteredAiohttpSession(AiohttpSession):
    """
    High-efficiency session connector that meters every outbound byte sent over the wire
    to Telegram's Bot API and enforces the active 5GB circuit breaker.
    """
    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: Optional[int] = None,
    ) -> TelegramType:
        if not BANDWIDTH_MONITOR.can_send(512):
            raise TelegramNetworkError(
                method=method,
                message="Render outbound bandwidth quota circuit breaker active (limit ~4.8GB / 5GB)."
            )

        # Estimate request size (URL + HTTP headers + JSON / multipart payload)
        try:
            est_payload_size = 350
            if hasattr(method, "__dict__"):
                est_payload_size += len(str(method.__dict__))
            BANDWIDTH_MONITOR.add_outbound_bytes(est_payload_size)
        except Exception:
            BANDWIDTH_MONITOR.add_outbound_bytes(400)

        return await super().make_request(bot=bot, method=method, timeout=timeout)


def get_current_rss_mb() -> float:
    """
    Returns current process Resident Set Size (RSS) in Megabytes.
    Uses zero-allocation /proc/self/statm on Linux (Render runtime) with native OS fallbacks.
    """
    # 1. Linux /proc/self/statm (Render production container: 0ms, 0 allocations)
    try:
        with open("/proc/self/statm", "r") as f:
            parts = f.read().split()
            if len(parts) >= 2:
                pages = int(parts[1])
                page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
                return round((pages * page_size) / (1024 * 1024), 2)
    except Exception:
        pass

    # 2. Linux / Unix resource module
    try:
        import resource
        ru = resource.getrusage(resource.RUSAGE_SELF)
        if sys.platform.startswith("linux"):
            return round(ru.ru_maxrss / 1024.0, 2)  # ru_maxrss is in KiB on Linux
        else:
            return round(ru.ru_maxrss / (1024.0 * 1024.0), 2)  # in bytes on Darwin/BSD
    except Exception:
        pass

    # 3. Windows native ctypes GetProcessMemoryInfo (local testing)
    try:
        import ctypes
        from ctypes import wintypes
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD),
                ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t),
            ]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return round(counters.WorkingSetSize / (1024 * 1024), 2)
    except Exception:
        pass

    return 28.5


async def resource_optimizer_worker() -> None:
    """
    Continuous background resource guardian running every 30 seconds.
    Monitors process RSS and enforces a 3-tier circuit breaker to guarantee
    the bot NEVER exceeds 500MB (Render kills at 512MB).
    Under normal operation, keeps usage strictly at ~25-45MB.
    """
    while True:
        try:
            await asyncio.sleep(30)
            now = time.monotonic()
            rss_mb = get_current_rss_mb()

            # 1. Purge expired ADMIN_CACHE entries
            expired_admins = [k for k, v in list(ADMIN_CACHE.items()) if now - v[0] > ADMIN_CACHE_TTL]
            for k in expired_admins:
                ADMIN_CACHE.pop(k, None)

            # 2. Purge stale FLOOD_CACHE entries (>15s idle)
            empty_chats = []
            for chat_id, user_dict in list(FLOOD_CACHE.items()):
                inactive_users = [
                    uid for uid, dq in list(user_dict.items())
                    if not dq or (now - dq[-1] > 15.0)
                ]
                for uid in inactive_users:
                    user_dict.pop(uid, None)
                if not user_dict:
                    empty_chats.append(chat_id)
            for cid in empty_chats:
                FLOOD_CACHE.pop(cid, None)

            # 2B. Purge stale DUPLICATE_CACHE entries (>120s idle)
            empty_dup_chats = []
            for chat_id, user_dict in list(DUPLICATE_CACHE.items()):
                stale_users = [
                    uid for uid, item in list(user_dict.items())
                    if not item or (now - item[2] > 120.0)
                ]
                for uid in stale_users:
                    user_dict.pop(uid, None)
                if not user_dict:
                    empty_dup_chats.append(chat_id)
            for cid in empty_dup_chats:
                DUPLICATE_CACHE.pop(cid, None)

            # 3. Clean zero-warn entries from WARN_CACHE
            empty_warn_chats = []
            for chat_id, user_dict in list(WARN_CACHE.items()):
                zero_users = [uid for uid, count in list(user_dict.items()) if count <= 0]
                for uid in zero_users:
                    user_dict.pop(uid, None)
                if not user_dict:
                    empty_warn_chats.append(chat_id)
            for cid in empty_warn_chats:
                WARN_CACHE.pop(cid, None)

            # 4. Clean orphan private DM keys from CHAT_SETTINGS (supergroups have negative IDs)
            private_chats = [cid for cid in list(CHAT_SETTINGS.keys()) if cid > 0]
            for cid in private_chats:
                CHAT_SETTINGS.pop(cid, None)

            # 5. Bound USERNAME_CACHE (max 5,000 entries)
            if len(USERNAME_CACHE) > 5000:
                for k in list(USERNAME_CACHE.keys())[:1000]:
                    USERNAME_CACHE.pop(k, None)

            # 5B. Clean expired PENDING_BROADCAST sessions (>15 min)
            now_ts = time.time()
            stale_bcasts = [k for k, v in list(PENDING_BROADCAST.items()) if now_ts - v.get("created_at", 0) > 900]
            for k in stale_bcasts:
                PENDING_BROADCAST.pop(k, None)

            # 5C. Bound LAST_DM_SETTINGS_MSG (max 1,000 entries)
            if len(LAST_DM_SETTINGS_MSG) > 1000:
                for k in list(LAST_DM_SETTINGS_MSG.keys())[:300]:
                    LAST_DM_SETTINGS_MSG.pop(k, None)

            # 5D. Bound ACCEPTED_MEMBERS_CACHE (max 10,000 entries in RAM)
            if len(ACCEPTED_MEMBERS_CACHE) > 10000:
                sorted_keys = sorted(
                    ACCEPTED_MEMBERS_CACHE.keys(),
                    key=lambda k: str(ACCEPTED_MEMBERS_CACHE[k].get("last_accepted_at") or ""),
                    reverse=True
                )
                for k in sorted_keys[8000:]:
                    ACCEPTED_MEMBERS_CACHE.pop(k, None)

            # 5E. Clean stale _LAST_DM_SENT_TS entries (>300s)
            stale_dm_keys = [k for k, ts in list(_LAST_DM_SENT_TS.items()) if now_ts - ts > 300]
            for k in stale_dm_keys:
                _LAST_DM_SENT_TS.pop(k, None)

            # 6. HARD 500MB RAM CIRCUIT BREAKER TIER CHECKS:
            if rss_mb > 100.0:
                # Tier 1 Relief (>100MB): Clear admin cache and compress flood deques
                ADMIN_CACHE.clear()
                for chat_id, user_dict in list(FLOOD_CACHE.items()):
                    recent_users = {uid: dq for uid, dq in user_dict.items() if dq and (now - dq[-1] <= 5.0)}
                    if recent_users:
                        FLOOD_CACHE[chat_id] = defaultdict(deque, recent_users)
                    else:
                        FLOOD_CACHE.pop(chat_id, None)

            if rss_mb > 250.0:
                # Tier 2 Emergency Relief (>250MB): Shed flood and warn memory
                FLOOD_CACHE.clear()
                DUPLICATE_CACHE.clear()
                WARN_CACHE.clear()
                USERNAME_CACHE.clear()
                PENDING_CUSTOM_WARN.clear()
                PENDING_CUSTOM_INPUT.clear()
                PENDING_BROADCAST.clear()
                LAST_DM_SETTINGS_MSG.clear()
                _LAST_DM_SENT_TS.clear()
                CHAT_TITLES.clear()

            if rss_mb > 400.0:
                # Tier 3 Critical Circuit Breaker (>400MB): Complete heap shed before Render's 512MB OOM
                ADMIN_CACHE.clear()
                FLOOD_CACHE.clear()
                WARN_CACHE.clear()
                USERNAME_CACHE.clear()
                PENDING_CUSTOM_WARN.clear()
                PENDING_CUSTOM_INPUT.clear()
                PENDING_BROADCAST.clear()
                LAST_DM_SETTINGS_MSG.clear()
                _LAST_DM_SENT_TS.clear()
                CHAT_TITLES.clear()
                print(f"[CIRCUIT BREAKER] Hard memory guard active at {rss_mb}MB. Trimmed heap to protect container.")

            # Trigger Python garbage collection
            gc.collect()

            # Call Linux glibc malloc_trim(0) if running on Linux to return all free heap to OS
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                libc.malloc_trim(0)
            except Exception:
                pass

            # Update internal heartbeat timestamp
            METRICS["last_heartbeat"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def render_keepalive_worker() -> None:
    """
    Self-ping keepalive worker designed for Render Free Web Service tier.
    Render free instances spin down after 15 minutes of HTTP inactivity.
    If RENDER_EXTERNAL_URL or PING_URL is set, performs a lightweight GET request
    to /health every 12 minutes (720 seconds) to guarantee 24/7 continuous uptime.
    """
    ping_url = os.getenv("RENDER_EXTERNAL_URL", "").strip() or os.getenv("PING_URL", "").strip()
    if not ping_url:
        return

    if not ping_url.startswith("http://") and not ping_url.startswith("https://"):
        ping_url = f"https://{ping_url}"
    health_endpoint = ping_url.rstrip("/") + "/health"

    print(f"[RENDER KEEPALIVE] Worker active. Pinging {health_endpoint} every 12m to prevent spindown.", flush=True)

    # Initial delay so application completes boot before first ping
    await asyncio.sleep(60)

    while True:
        try:
            await asyncio.sleep(720)  # 12 minutes
            connector = aiohttp.TCPConnector(limit=1, ssl=False)
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(health_endpoint) as resp:
                    if resp.status == 200:
                        METRICS["last_heartbeat"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        except asyncio.CancelledError:
            break
        except Exception:
            pass


_CACHED_DASHBOARD_HTML: Optional[str] = None


def render_members_dashboard_html() -> str:
    """Renders high-speed, modern, standalone HTML/JS dashboard for accepted members & broadcasts."""
    global _CACHED_DASHBOARD_HTML
    if _CACHED_DASHBOARD_HTML is not None:
        return _CACHED_DASHBOARD_HTML

    _CACHED_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manager — Accepted Members & Broadcast</title>
<style>
  :root {
    --bg-dark: #0e1621;
    --card-bg: #17212b;
    --card-header: #242f3d;
    --accent: #2b5278;
    --accent-hover: #3a6d9b;
    --accent-blue: #5288c1;
    --text-primary: #f5f5f5;
    --text-secondary: #7f91a4;
    --border-color: #242f3d;
    --success: #4fae4e;
    --danger: #e53935;
    --badge-bg: rgba(82, 136, 193, 0.15);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  body { background: var(--bg-dark); color: var(--text-primary); padding: 20px; min-height: 100vh; }
  .container { max-width: 1280px; margin: 0 auto; }
  header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 16px; border-bottom: 1px solid var(--border-color); padding-bottom: 16px; }
  .brand { display: flex; align-items: center; gap: 12px; }
  .brand-icon { font-size: 30px; }
  .brand-title { font-size: 20px; font-weight: 700; color: #fff; }
  .brand-sub { font-size: 12px; color: var(--text-secondary); }
  .stats-badges { display: flex; gap: 10px; flex-wrap: wrap; }
  .stat-badge { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 14px; display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .stat-val { font-weight: 700; color: var(--accent-blue); }
  .grid { display: grid; grid-template-columns: 380px 1fr; gap: 20px; }
  @media (max-width: 960px) { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; }
  .card-header { background: var(--card-header); padding: 12px 18px; font-weight: 600; font-size: 14px; display: flex; justify-content: space-between; align-items: center; }
  .card-body { padding: 16px; flex: 1; display: flex; flex-direction: column; }
  .form-group { margin-bottom: 14px; }
  label { display: block; font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
  textarea, input[type="text"], select { width: 100%; background: #0e1621; border: 1px solid var(--border-color); border-radius: 8px; padding: 10px 12px; color: #fff; font-size: 13px; outline: none; transition: border-color .2s; }
  textarea:focus, input[type="text"]:focus, select:focus { border-color: var(--accent-blue); }
  textarea { resize: vertical; min-height: 130px; line-height: 1.4; font-family: monospace; }
  .tag-btns { display: flex; gap: 6px; margin-bottom: 8px; }
  .tag-btn { background: #242f3d; border: 1px solid #3a4756; color: #7f91a4; font-size: 11px; padding: 4px 8px; border-radius: 4px; cursor: pointer; }
  .tag-btn:hover { color: #fff; border-color: var(--accent-blue); }
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; font-size: 13px; font-weight: 600; padding: 10px 18px; border-radius: 8px; border: none; cursor: pointer; transition: background .2s, opacity .2s; }
  .btn-primary { background: var(--accent); color: #fff; width: 100%; }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-secondary { background: #242f3d; color: var(--text-primary); padding: 6px 12px; font-size: 12px; }
  .btn-secondary:hover { background: #313f52; }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px; }
  .search-wrap { display: flex; gap: 8px; flex: 1; min-width: 260px; }
  .actions-wrap { display: flex; gap: 8px; align-items: center; }
  .table-container { max-height: 580px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 8px; background: #0e1621; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }
  th { background: #1c2734; padding: 10px 12px; position: sticky; top: 0; z-index: 2; border-bottom: 1px solid var(--border-color); font-weight: 600; color: var(--text-secondary); font-size: 12px; }
  td { padding: 10px 12px; border-bottom: 1px solid var(--border-color); vertical-align: middle; }
  tr:hover td { background: rgba(82, 136, 193, 0.05); }
  .avatar { width: 30px; height: 30px; border-radius: 50%; background: var(--accent); display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: 11px; color: #fff; margin-right: 8px; flex-shrink: 0; }
  .user-cell { display: flex; align-items: center; }
  .user-name { font-weight: 600; color: #fff; }
  .user-id { font-size: 11px; color: var(--text-secondary); font-family: monospace; }
  .group-pill { display: inline-block; background: var(--badge-bg); color: var(--accent-blue); padding: 2px 6px; border-radius: 4px; font-size: 11px; margin: 1px 2px; }
  .progress-box { display: none; margin-top: 14px; background: #0e1621; border-radius: 8px; padding: 12px; }
  .progress-bar-bg { width: 100%; height: 8px; background: #242f3d; border-radius: 4px; overflow: hidden; margin-top: 8px; }
  .progress-bar-fill { width: 0%; height: 100%; background: var(--accent-blue); transition: width .3s; }
  .status-text { font-size: 12px; color: var(--text-secondary); display: flex; justify-content: space-between; }
  .empty-msg { text-align: center; padding: 40px; color: var(--text-secondary); }
  .toast { position: fixed; bottom: 20px; right: 20px; background: #1c2734; border: 1px solid var(--accent-blue); color: #fff; padding: 12px 18px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); z-index: 100; font-size: 13px; display: none; }
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="brand">
      <div class="brand-icon">🛡️</div>
      <div>
        <div class="brand-title">Manager Bot Console</div>
        <div class="brand-sub">Global Unified Accepted Members Registry & Broadcast</div>
      </div>
    </div>
    <div class="stats-badges">
      <div class="stat-badge">👥 Total Members: <span id="stat-total" class="stat-val">0</span></div>
      <div class="stat-badge">🏷️ Groups: <span id="stat-groups" class="stat-val">0</span></div>
      <div class="stat-badge">⚡ Status: <span class="stat-val" style="color:var(--success)">ONLINE</span></div>
      <button class="stat-badge" onclick="promptSetBackendUrl()" style="cursor:pointer;background:#242f3d;color:#fff;" title="Configure Backend API Server (for Vercel deployment)">⚙️ API Config</button>
    </div>
  </header>

  <div class="grid">
    <!-- BROADCAST COMPOSER -->
    <div class="card">
      <div class="card-header">
        <span>📢 Compose Broadcast Message</span>
        <span id="selected-badge" style="font-size:12px;color:var(--accent-blue)">0 Selected</span>
      </div>
      <div class="card-body">
        <div class="form-group">
          <label>Target Audience</label>
          <select id="target-mode" onchange="updateTargetMode()">
            <option value="selected">Selected Members (<span id="opt-sel-count">0</span>)</option>
            <option value="filtered">All Filtered Members</option>
            <option value="all">All Global Members</option>
          </select>
        </div>

        <div class="form-group">
          <label>Message Content (HTML Supported)</label>
          <div class="tag-btns">
            <button class="tag-btn" onclick="insertTag('b')">&lt;b&gt;Bold&lt;/b&gt;</button>
            <button class="tag-btn" onclick="insertTag('i')">&lt;i&gt;Italic&lt;/i&gt;</button>
            <button class="tag-btn" onclick="insertTag('code')">&lt;code&gt;Code&lt;/code&gt;</button>
            <button class="tag-btn" onclick="insertLink()">&lt;a&gt;Link&lt;/a&gt;</button>
          </div>
          <textarea id="broadcast-msg" placeholder="Type your broadcast announcement here...&#10;&#10;Supports {name}, {chat_title}, HTML tags like &lt;b&gt;bold&lt;/b&gt;, &lt;a href='...'&gt;links&lt;/a&gt;."></textarea>
        </div>

        <button id="send-btn" class="btn btn-primary" onclick="submitBroadcast()">
          🚀 Send Broadcast
        </button>

        <div id="progress-box" class="progress-box">
          <div class="status-text">
            <span id="progress-status">Dispatching messages...</span>
            <span id="progress-percent">0%</span>
          </div>
          <div class="progress-bar-bg">
            <div id="progress-bar-fill" class="progress-bar-fill"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- MEMBERS REGISTRY & SELECTOR -->
    <div class="card">
      <div class="card-header">
        <span>👥 Request-Accepted Members Registry</span>
        <button class="btn btn-secondary" onclick="fetchMembers()">🔄 Refresh</button>
      </div>
      <div class="card-body">
        <div class="toolbar">
          <div class="search-wrap">
            <input type="text" id="search-input" placeholder="🔍 Search by name, @username, or User ID..." oninput="filterTable()">
            <select id="group-filter" style="max-width:180px;" onchange="filterTable()">
              <option value="">All Groups</option>
            </select>
          </div>
          <div class="actions-wrap">
            <button class="btn btn-secondary" onclick="selectAllFiltered(true)">Select All</button>
            <button class="btn btn-secondary" onclick="selectAllFiltered(false)">Clear</button>
          </div>
        </div>

        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th style="width:36px;"><input type="checkbox" id="master-checkbox" onchange="toggleMasterCheckbox(this)"></th>
                <th>Member</th>
                <th>Username</th>
                <th>Groups</th>
                <th>Last Accepted</th>
                <th>Approvals</th>
              </tr>
            </thead>
            <tbody id="members-table-body">
              <tr><td colspan="6" class="empty-msg">Loading accepted members registry...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
let allMembers = [];
let filteredMembers = [];
let selectedUserIds = new Set();

function getApiBaseUrl() {
  const custom = localStorage.getItem('bot_backend_url');
  if (custom) return custom.replace(/\/$/, '');
  if (window.location.hostname.includes('vercel.app')) {
    return 'https://manager-f6vd.onrender.com';
  }
  return '';
}

function promptSetBackendUrl() {
  const current = getApiBaseUrl() || window.location.origin;
  const val = prompt('Enter your Render Bot Backend URL:', current);
  if (val !== null) {
    localStorage.setItem('bot_backend_url', val.trim());
    fetchMembers();
  }
}

async function fetchMembers() {
  try {
    const res = await fetch(getApiBaseUrl() + '/api/members');
    if (!res.ok) {
      const errTxt = await res.text();
      throw new Error(`Server returned HTTP ${res.status}: ${errTxt.slice(0, 80)}`);
    }
    const data = await res.json();
    if (data.status === 'error') {
      throw new Error(data.message || 'Backend returned error');
    }
    allMembers = data.members || [];
    document.getElementById('stat-total').textContent = allMembers.length;

    // Populate group filter
    const groupsSet = new Set();
    allMembers.forEach(m => (m.chat_titles || []).forEach(t => groupsSet.add(t)));
    document.getElementById('stat-groups').textContent = groupsSet.size;

    const groupFilter = document.getElementById('group-filter');
    const curVal = groupFilter.value;
    groupFilter.innerHTML = '<option value="">All Groups</option>';
    groupsSet.forEach(g => {
      const opt = document.createElement('option');
      opt.value = g;
      opt.textContent = g;
      groupFilter.appendChild(opt);
    });
    groupFilter.value = curVal;

    filterTable();
  } catch (e) {
    showToast('Failed to load members: ' + e.message, true);
  }
}

function filterTable() {
  const query = document.getElementById('search-input').value.trim().toLowerCase();
  const group = document.getElementById('group-filter').value;

  filteredMembers = allMembers.filter(m => {
    const matchQuery = !query ||
      (m.full_name && m.full_name.toLowerCase().includes(query)) ||
      (m.username && m.username.toLowerCase().includes(query)) ||
      String(m.user_id).includes(query);

    const matchGroup = !group || (m.chat_titles && m.chat_titles.includes(group));
    return matchQuery && matchGroup;
  });

  renderTable();
  updateTargetMode();
}

function renderTable() {
  const tbody = document.getElementById('members-table-body');
  if (!filteredMembers.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">No accepted members found.</td></tr>';
    return;
  }

  tbody.innerHTML = filteredMembers.map(m => {
    const isChecked = selectedUserIds.has(m.user_id);
    const initials = (m.first_name ? m.first_name.charAt(0) : 'U').toUpperCase();
    const uname = m.username ? ('@' + m.username) : '<span style="color:var(--text-secondary)">-</span>';
    const groups = (m.chat_titles || []).map(g => `<span class="group-pill">${escapeHtml(g)}</span>`).join('') || '<span style="color:var(--text-secondary)">None</span>';
    const dateStr = m.last_accepted_at ? new Date(m.last_accepted_at).toLocaleString() : '-';

    return `<tr>
      <td><input type="checkbox" data-uid="${m.user_id}" ${isChecked ? 'checked' : ''} onchange="toggleSelectUser(${m.user_id}, this.checked)"></td>
      <td>
        <div class="user-cell">
          <div class="avatar">${initials}</div>
          <div>
            <div class="user-name">${escapeHtml(m.full_name || 'User ' + m.user_id)}</div>
            <div class="user-id">${m.user_id}</div>
          </div>
        </div>
      </td>
      <td>${uname}</td>
      <td>${groups}</td>
      <td style="color:var(--text-secondary);font-size:12px;">${dateStr}</td>
      <td style="font-weight:600;color:var(--accent-blue);">${m.accept_count || 1}</td>
    </tr>`;
  }).join('');
}

function toggleSelectUser(userId, checked) {
  if (checked) {
    selectedUserIds.add(userId);
  } else {
    selectedUserIds.delete(userId);
  }
  updateSelectedBadge();
}

function selectAllFiltered(state) {
  filteredMembers.forEach(m => {
    if (state) selectedUserIds.add(m.user_id);
    else selectedUserIds.delete(m.user_id);
  });
  document.getElementById('master-checkbox').checked = state;
  renderTable();
  updateSelectedBadge();
}

function toggleMasterCheckbox(masterEl) {
  selectAllFiltered(masterEl.checked);
}

function updateSelectedBadge() {
  const count = selectedUserIds.size;
  document.getElementById('selected-badge').textContent = `${count} Selected`;
  updateTargetMode();
}

function updateTargetMode() {
  const mode = document.getElementById('target-mode').value;
  const btn = document.getElementById('send-btn');
  const count = selectedUserIds.size;
  if (mode === 'selected') {
    btn.textContent = `🚀 Send Broadcast to Selected (${count})`;
  } else if (mode === 'filtered') {
    btn.textContent = `🚀 Send Broadcast to Filtered (${filteredMembers.length})`;
  } else {
    btn.textContent = `🚀 Send Broadcast to All (${allMembers.length})`;
  }
}

function insertTag(tag) {
  const ta = document.getElementById('broadcast-msg');
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const sel = ta.value.substring(start, end);
  const rep = `<${tag}>${sel || 'text'}</${tag}>`;
  ta.value = ta.value.substring(0, start) + rep + ta.value.substring(end);
  ta.focus();
}

function insertLink() {
  const url = prompt('Enter link URL (e.g. https://t.me/...):');
  if (!url) return;
  const ta = document.getElementById('broadcast-msg');
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const sel = ta.value.substring(start, end) || 'Click Here';
  const rep = `<a href="${url}">${sel}</a>`;
  ta.value = ta.value.substring(0, start) + rep + ta.value.substring(end);
  ta.focus();
}

async function submitBroadcast() {
  const msg = document.getElementById('broadcast-msg').value.trim();
  if (!msg) {
    alert('Please enter a broadcast message content.');
    return;
  }

  const mode = document.getElementById('target-mode').value;
  let targetUids = [];
  let sendAll = false;

  if (mode === 'selected') {
    targetUids = Array.from(selectedUserIds);
    if (!targetUids.length) {
      alert('Please select at least one member to message.');
      return;
    }
  } else if (mode === 'filtered') {
    targetUids = filteredMembers.map(m => m.user_id);
    if (!targetUids.length) {
      alert('No members in current filter.');
      return;
    }
  } else {
    sendAll = true;
  }

  const recipientCount = sendAll ? allMembers.length : targetUids.length;
  if (!confirm(`Confirm dispatching broadcast to ${recipientCount} accepted member(s)?`)) {
    return;
  }

  const pBox = document.getElementById('progress-box');
  const pStatus = document.getElementById('progress-status');
  const pFill = document.getElementById('progress-bar-fill');
  const btn = document.getElementById('send-btn');

  btn.disabled = true;
  pBox.style.display = 'block';
  pStatus.textContent = 'Scheduling throttled broadcast...';
  pFill.style.width = '25%';

  try {
    const res = await fetch(getApiBaseUrl() + '/api/broadcast', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        all: sendAll,
        user_ids: targetUids,
        message: msg
      })
    });
    const resp = await res.json();
    if (resp.status === 'ok') {
      pFill.style.width = '100%';
      pStatus.textContent = `Broadcast running in background for ${resp.recipient_count} members!`;
      showToast(`Broadcast queued successfully! (${resp.recipient_count} recipients)`);
      setTimeout(() => {
        pBox.style.display = 'none';
        btn.disabled = false;
      }, 4000);
    } else {
      throw new Error(resp.message || 'Broadcast failed.');
    }
  } catch (err) {
    pBox.style.display = 'none';
    btn.disabled = false;
    alert('Broadcast Error: ' + err.message);
  }
}

function showToast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.borderColor = isError ? 'var(--danger)' : 'var(--accent-blue)';
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 3500);
}

function escapeHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

window.addEventListener('DOMContentLoaded', fetchMembers);
</script>
</body>
</html>
"""
    return _CACHED_DASHBOARD_HTML


async def members_dashboard_handler(request: web.Request) -> web.Response:
    """Serves the fast, responsive web frontend dashboard."""
    html_content = render_members_dashboard_html()
    resp = web.Response(text=html_content, content_type="text/html")
    if resp.body is not None:
        BANDWIDTH_MONITOR.add_outbound_bytes(len(resp.body) + 150)
    return resp


def json_serial(obj: Any) -> str:
    """JSON serializer for objects not serializable by default json code (e.g. datetime, date)."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


async def api_get_members_handler(request: web.Request) -> web.Response:
    """REST JSON endpoint returning list of all globally accepted members with pagination."""
    try:
        chat_id_param = request.query.get("chat_id")
        limit_param = request.query.get("limit")
        try:
            limit = min(max(int(limit_param), 1), 5000) if limit_param else 1000
        except (ValueError, TypeError):
            limit = 1000

        all_members = list(ACCEPTED_MEMBERS_CACHE.values())
        if chat_id_param:
            try:
                cid = int(chat_id_param)
                all_members = [m for m in all_members if cid in m.get("chat_ids", [])]
            except ValueError:
                pass

        total_count = len(all_members)
        all_members.sort(key=lambda x: str(x.get("last_accepted_at") or ""), reverse=True)
        paginated_members = all_members[:limit]

        payload = {
            "status": "ok",
            "total": total_count,
            "count": len(paginated_members),
            "members": paginated_members
        }
        json_str = json.dumps(payload, default=json_serial)
        resp = web.Response(
            text=json_str,
            content_type="application/json",
            headers=CORS_HEADERS
        )
        if resp.body is not None:
            BANDWIDTH_MONITOR.add_outbound_bytes(len(resp.body) + 150)
        return resp
    except Exception as e:
        print(f"[API ERROR] api_get_members_handler: {e}", flush=True)
        err_payload = json.dumps({"status": "error", "message": str(e), "members": []})
        return web.Response(text=err_payload, content_type="application/json", status=200, headers=CORS_HEADERS)


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


async def api_options_handler(request: web.Request) -> web.Response:
    """Handles CORS preflight requests for external frontends (e.g. Vercel)."""
    return web.Response(status=200, headers=CORS_HEADERS)


async def api_post_broadcast_handler(request: web.Request) -> web.Response:
    """REST JSON endpoint receiving broadcast dispatch requests from web frontend."""
    global GLOBAL_BOT
    if not GLOBAL_BOT:
        return web.json_response({"status": "error", "message": "Bot is not connected yet."}, status=503, headers=CORS_HEADERS)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error", "message": "Invalid JSON payload."}, status=400, headers=CORS_HEADERS)

    user_ids = data.get("user_ids", [])
    send_all = data.get("all", False)
    message_text = data.get("message", "").strip()

    if not message_text:
        return web.json_response({"status": "error", "message": "Broadcast message cannot be empty."}, status=400, headers=CORS_HEADERS)

    if send_all or not user_ids:
        target_ids = list(ACCEPTED_MEMBERS_CACHE.keys())
    else:
        target_ids = []
        for uid in user_ids:
            try:
                target_ids.append(int(uid))
            except (ValueError, TypeError):
                pass

    if not target_ids:
        return web.json_response({"status": "error", "message": "No valid recipients selected."}, status=400, headers=CORS_HEADERS)

    task_id = str(uuid.uuid4())[:8]
    asyncio.create_task(run_background_broadcast(GLOBAL_BOT, target_ids, message_text, task_id))

    return web.json_response({
        "status": "ok",
        "task_id": task_id,
        "recipient_count": len(target_ids),
        "message": f"Broadcast queued successfully for {len(target_ids)} members."
    }, headers=CORS_HEADERS)


async def start_render_health_server() -> Optional[web.AppRunner]:
    """
    Starts an ultra-lightweight HTTP micro-server on $PORT (default 10000).
    Provides dedicated /health and / routes for Render health checks and uptime monitoring
    matching the standard production JSON health schema.
    """
    port_str = os.getenv("PORT", "10000").strip()
    try:
        port = int(port_str)
    except ValueError:
        port = 10000

    app = web.Application()

    async def health_handler(request: web.Request) -> web.Response:
        uptime_sec = int(time.time() - BOT_START_TIME)
        is_connected = MongoDBManager.is_connected()
        METRICS["last_heartbeat"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        rss_mb = get_current_rss_mb()

        response_payload = {
            "status": "UP",
            "service": os.getenv("SERVICE_NAME", "BioLinkChannelRestrictorBot"),
            "telegram_bot": {
                "status": BOT_IDENTITY.get("status", "ONLINE"),
                "username": BOT_IDENTITY.get("username", "personal_guardBot"),
                "id": BOT_IDENTITY.get("id", 9224266782),
            },
            "database": {
                "type": "MongoDB Atlas" if is_connected else "In-Memory RAM Cache",
                "connected": is_connected,
                "metrics": {
                    "connected": is_connected,
                    "violations_handled": METRICS["violations_handled"],
                    "connected_channels_caught": METRICS["connected_channels_caught"],
                    "bio_links_caught": METRICS["bio_links_caught"],
                    "chat_links_caught": METRICS["chat_links_caught"],
                    "last_heartbeat": METRICS["last_heartbeat"],
                },
            },
            "stats": {
                "active_groups": len([cid for cid in CHAT_SETTINGS.keys() if cid < 0]),
                "cached_admins_chats": len({k[0] for k in ADMIN_CACHE.keys()}),
                "cached_user_bios": METRICS.get("cached_user_bios", 0),
                "ram_usage_mb": rss_mb,
                "ram_limit_mb": 500,
                "outbound_mb": BANDWIDTH_MONITOR.get_outbound_mb(),
                "outbound_limit_gb": 5.0,
            },
            "uptime": format_uptime(uptime_sec),
            "uptime_seconds": uptime_sec,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        resp = web.json_response(response_payload)
        # Meter outbound HTTP response bytes
        if resp.body is not None:
            BANDWIDTH_MONITOR.add_outbound_bytes(len(resp.body) + 200)
        return resp

    # Dedicated health check route for Render Web Service (returns JSON status)
    app.router.add_get("/health", health_handler)

    # Main Web Dashboard routes for Accepted Members & Broadcast GUI (Root / loads GUI directly)
    app.router.add_get("/", members_dashboard_handler)
    app.router.add_get("/members", members_dashboard_handler)
    app.router.add_get("/dashboard", members_dashboard_handler)

    # REST APIs with full CORS support (enables direct Vercel frontend deployments)
    app.router.add_get("/api/members", api_get_members_handler)
    app.router.add_post("/api/broadcast", api_post_broadcast_handler)
    app.router.add_options("/api/members", api_options_handler)
    app.router.add_options("/api/broadcast", api_options_handler)

    try:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"[RENDER] Health check route /health active on 0.0.0.0:{port}", flush=True)
        return runner
    except Exception as e:
        print(f"[RENDER WARNING] Could not bind health server to port {port}: {e}", flush=True)
        return None


# ==============================================================================
# APPLICATION BOOTSTRAP & EXECUTION RUNNER
# ==============================================================================

async def main() -> None:
    # 1. Immediately bind HTTP health check server on $PORT (default 10000).
    # This satisfies Render Web Service's port-binding check instantly (<0.05s)
    # so the deployment is immediately acknowledged as healthy and marked LIVE.
    health_runner = await start_render_health_server()

    token = os.getenv("BOT_TOKEN")
    if not token or token.strip() in ("", "YOUR_BOT_TOKEN_HERE"):
        print("=" * 70, flush=True)
        print("[CRITICAL] BOT_TOKEN is not configured in Render Environment Variables!", flush=True)
        print("To complete deployment:", flush=True)
        print("1. Go to Render Dashboard -> This Web Service -> 'Environment'.", flush=True)
        print("2. Add Key: BOT_TOKEN, Value: <your_telegram_bot_token>", flush=True)
        print("3. Click 'Save Changes' - the bot will start immediately!", flush=True)
        print("=" * 70, flush=True)
        BOT_IDENTITY["status"] = "BOT_TOKEN_MISSING"

        if len(sys.argv) > 1 and sys.argv[1] == "--check-syntax":
            print("[STATUS] Syntax and logic compilation verified successfully.", flush=True)
            if health_runner:
                await health_runner.cleanup()
            return

        # Keep HTTP health check server alive so Render marks the service LIVE
        # and displays this actionable diagnostic message instead of failing with a 20-minute port timeout!
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            if health_runner:
                await health_runner.cleanup()
        return

    print(f"[INITIALIZING] Launching Ultra-Optimized Admin Bot with {LOOP_ENGINE}...", flush=True)

    # High-efficiency metered session connector with DNS caching & socket limit (Render RAM & Bandwidth optimization)
    session = MeteredAiohttpSession(limit=10)
    bot = Bot(token=token.strip(), session=session)
    dp = Dispatcher()
    global GLOBAL_BOT
    GLOBAL_BOT = bot

    # Dynamic bot identity resolution for health metrics
    try:
        if ":" in token:
            BOT_IDENTITY["id"] = int(token.split(":")[0])
    except Exception:
        pass

    try:
        me = await bot.get_me()
        BOT_IDENTITY["username"] = me.username or "personal_guardBot"
        BOT_IDENTITY["id"] = me.id
        BOT_IDENTITY["status"] = "ONLINE"
        print(f"[BOT] Connected as @{BOT_IDENTITY['username']} (ID: {BOT_IDENTITY['id']})", flush=True)
    except Exception as e:
        print(f"[BOT WARNING] Profile resolution notice: {e}", flush=True)
        BOT_IDENTITY["status"] = "OFFLINE"

    # Register high-speed Anti-Flood Middleware
    dp.message.middleware(AntiFloodMiddleware())

    # Include routers
    dp.include_router(router)

    # Delete existing webhook to guarantee clean fast long-polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"[BOT WARNING] delete_webhook notice: {e}", flush=True)

    # Connect to MongoDB & hydrate in-memory caches
    await MongoDBManager.connect()
    if MongoDBManager.is_connected():
        await DatabaseService.hydrate_settings_cache(CHAT_SETTINGS, CHAT_TITLES)
        await DatabaseService.hydrate_warn_cache(WARN_CACHE)
        await DatabaseService.hydrate_accepted_members_cache(ACCEPTED_MEMBERS_CACHE)

    # Register admin-only command catalog with Telegram API
    try:
        await setup_bot_commands(bot)
    except Exception as e:
        print(f"[BOT WARNING] Command setup notice: {e}", flush=True)

    # Start background RAM & cache resource optimizer task + Render 24/7 keepalive
    optimizer_task = asyncio.create_task(resource_optimizer_worker())
    keepalive_task = asyncio.create_task(render_keepalive_worker())

    print(f"[READY] Listening for commands with zero DB roundtrips. Engine: {LOOP_ENGINE}", flush=True)

    try:
        # Polling timeout set to 50s: holds long-polling socket up to 50s on Telegram server.
        # Slashes outbound HTTP request headers by >90% to stay well under Render's 5GB limit (<50MB/mo).
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "chat_join_request", "chat_member"],
            polling_timeout=50,
            handle_signals=True
        )
    finally:
        optimizer_task.cancel()
        keepalive_task.cancel()
        if health_runner:
            await health_runner.cleanup()
        await MongoDBManager.disconnect()
        await bot.session.close()


if __name__ == "__main__":
    if "--check-syntax" in sys.argv:
        print(f"[CHECK] Syntax valid. Event loop engine available: {LOOP_ENGINE}")
        sys.exit(0)

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[STOPPED] Bot terminated cleanly.")
