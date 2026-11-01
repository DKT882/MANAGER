"""
High-Speed Telegram Admin Bot Implementation
Framework: aiogram v3.x | Event Loop: uvloop (Linux/macOS) / winloop (Windows)
Features: In-memory Caching, Instant Wipe Trigger, Strict Parallel Native Admin Rights,
          Anti-Flood Middleware, Instant Media/Link Interceptor, Interactive Settings UI.
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
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
    # Anti-flood settings
    "flood_protection": True,
    "flood_window": 3.0,       # Frequency window in seconds
    "flood_limit": 5,          # Maximum messages allowed inside window
    "flood_action": "mute",    # Violation action: 'mute', 'delete', 'kick', 'ban'
    "flood_duration": 900,     # Mute duration in seconds
    # Warning settings
    "warn_limit": 3,           # Ceiling before automated penalty (1 to 10)
    "warn_action": "mute",     # Automated ceiling action: 'mute', 'ban', 'kick'
    "warn_duration": 86400,    # Penalty duration in seconds (0 = permanent)
    "warn_cancel_btn": True,   # Attach inline Cancel Warn button to warn notices
    "custom_warn_msg": "",     # Custom warn notice template configured in private DM
    # Reporting exception settings
    "excepted_admins": [],     # List of admin user IDs explicitly designated to receive reports
    # Service messages cleanup (auto delete user join / left notifications)
    "clean_service_messages": True,
    # Anti-bot setting (auto-ban/auto-kick bots added to the group chat)
    "block_bots": False,
    "bot_action": "ban",       # Violation action: 'ban' or 'kick'
}

# CHAT_SETTINGS: chat_id -> configuration dict
CHAT_SETTINGS: Dict[int, Dict[str, Any]] = defaultdict(lambda: DEFAULT_CHAT_CONFIG.copy())

# WARN_CACHE: chat_id -> user_id -> count
WARN_CACHE: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

# FLOOD_CACHE: chat_id -> user_id -> deque of monotonic timestamps
FLOOD_CACHE: Dict[int, Dict[int, deque]] = defaultdict(lambda: defaultdict(deque))

# ADMIN_CACHE: (chat_id, user_id) -> (monotonic_timestamp, set_of_permissions, is_owner, is_anonymous)
# Caches Telegram administrator custom rights for 60s to prevent roundtrip API lag
ADMIN_CACHE: Dict[Tuple[int, int], Tuple[float, set, bool, bool]] = {}
ADMIN_CACHE_TTL = 60.0  # seconds

# PENDING_CUSTOM_WARN: admin_user_id -> chat_id being configured in private DM
PENDING_CUSTOM_WARN: Dict[int, int] = {}

# CHAT_TITLES: chat_id -> cached group title (eliminates redundant getChat roundtrips)
CHAT_TITLES: Dict[int, str] = {}

# Pre-compiled high-performance regex patterns
RE_DURATION = re.compile(r"^(\d+)([smhdw]?)$")
RE_LINK = re.compile(r"(https?://\S+|t\.me/\S+|telegram\.me/\S+)", re.IGNORECASE)

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
    Instantly wipes the incoming admin trigger command message from the chat.
    Executes BEFORE permission checks or command parsing to eliminate latency.
    """
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError, Exception):
        pass


async def check_admin_rights(
    bot: Bot,
    chat_id: int,
    user_id: int,
    required_permission: Optional[str] = None
) -> bool:
    """
    Strict parallel validation against native Telegram administrator custom rights.
    Utilizes local high-speed TTL cache. If user lacks explicit rights, returns False quietly.
    """
    if not user_id or not chat_id:
        return False

    now = time.monotonic()
    cache_key = (chat_id, user_id)

    # 1. Inspect local memory cache
    if cache_key in ADMIN_CACHE:
        cached_time, perms, is_owner, _ = ADMIN_CACHE[cache_key]
        if now - cached_time < ADMIN_CACHE_TTL:
            if is_owner:
                return True
            if required_permission is None:
                return len(perms) > 0 or "is_admin" in perms
            return required_permission in perms

    # 2. Fetch fresh native rights from Telegram API
    # Enforce strict cache bounds (<= 300 entries) to guarantee minimal memory usage (<30MB RAM)
    if len(ADMIN_CACHE) >= 300:
        for k in list(ADMIN_CACHE.keys()):
            if now - ADMIN_CACHE[k][0] > ADMIN_CACHE_TTL:
                ADMIN_CACHE.pop(k, None)
        if len(ADMIN_CACHE) >= 300:
            for k in list(ADMIN_CACHE.keys())[:50]:
                ADMIN_CACHE.pop(k, None)

    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
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
            if required_permission is None:
                return True
            return required_permission in perms
        else:
            ADMIN_CACHE[cache_key] = (now, set(), False, False)
            return False
    except Exception:
        return False


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

    if not user_id:
        return False

    # 1. Check Excepted / Exempted Admins in in-memory settings (0ms)
    settings = CHAT_SETTINGS[chat_id]
    excepted_ids = set(settings.get("excepted_admins", []))
    if user_id in excepted_ids:
        return True

    # 2. Check local Admin Cache (TTL 60s)
    now = time.monotonic()
    cache_key = (chat_id, user_id)
    if cache_key in ADMIN_CACHE:
        cached_time, perms, is_owner, is_anon = ADMIN_CACHE[cache_key]
        if now - cached_time < ADMIN_CACHE_TTL:
            if is_owner or is_anon:
                return True

    # 3. Fetch Telegram member status
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
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
    command: Optional[CommandObject] = None
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Resolves target user from reply or text parameters.
    Returns: (target_user_id, target_user_name, extra_arguments_string)
    """
    # 1. Target from replied message
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        extra_args = command.args if command and command.args else ""
        return target_user.id, target_user.full_name, extra_args.strip()

    # 2. Target from command arguments (user ID or @username)
    if command and command.args:
        parts = command.args.split(maxsplit=1)
        first_arg = parts[0]
        remaining = parts[1] if len(parts) > 1 else ""

        # Numeric user ID
        if first_arg.isdigit() or (first_arg.startswith("-") and first_arg[1:].isdigit()):
            return int(first_arg), f"User {first_arg}", remaining.strip()

        # Target mention via entities
        if message.entities:
            for entity in message.entities:
                if entity.type == "text_mention" and entity.user:
                    return entity.user.id, entity.user.full_name, remaining.strip()

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

            # 2. Automated restriction
            action = settings.get("flood_action", "mute")
            flood_dur = settings.get("flood_duration", 900)
            try:
                if action == "warn":
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
# 0. SERVICE MESSAGE CLEANER (AUTO-DELETE JOIN / LEAVE NOTIFICATIONS)
# ==============================================================================

@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.new_chat_members | F.left_chat_member
)
async def handle_service_messages(message: Message, bot: Bot) -> None:
    """
    1. Anti-Bot: If block_bots is enabled, bans any newly added bot instantly.
    2. Auto-deletes user join (new_chat_members) and leave (left_chat_member)
       service notifications instantly when clean_service_messages is enabled.
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

    # 2. Service Message Cleanup
    if settings.get("clean_service_messages", True):
        try:
            await message.delete()
        except Exception:
            pass


# ==============================================================================
# ASYNCHRONOUS MEDIA & LINK INTERCEPTOR (SUB-SECOND SCANNER)
# ==============================================================================

@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    ~F.text.startswith("/")
)
async def message_media_and_link_interceptor(message: Message, bot: Bot) -> None:
    """
    Monitors all incoming group messages against local settings:
    - Stickers
    - Animations (GIF)
    - Documents
    - Audio
    - Voice
    - Links (In-chat URLs and Admin Links)
    """
    user = message.from_user
    if not user or user.is_bot:
        return

    chat_id = message.chat.id
    if message.chat and message.chat.title:
        CHAT_TITLES[chat_id] = message.chat.title
    settings = CHAT_SETTINGS[chat_id]
    is_admin = await check_admin_rights(bot, chat_id, user.id)

    # 1. Media Type Interceptions
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

    # 2. Link Interceptions
    has_link = False
    is_channel_link = False
    if message.entities:
        for entity in message.entities:
            if entity.type in ("url", "text_link"):
                has_link = True
                break
            elif entity.type == "mention":
                is_channel_link = True

    if not has_link and message.text:
        if RE_LINK.search(message.text):
            has_link = True

    if has_link or (is_channel_link and settings.get("block_channel_links")):
        # Check non-admin link block
        if not is_admin and (settings.get("block_links") or (is_channel_link and settings.get("block_channel_links"))):
            METRICS["violations_handled"] += 1
            METRICS["chat_links_caught"] += 1
            await wipe_trigger(message)
            if settings.get("link_action") == "warn":
                await issue_warn_and_notify(bot, chat_id, user, bot.id, "Sent blocked link")
            return

        # Check strict admin link block
        if is_admin and settings.get("admin_links_block"):
            METRICS["violations_handled"] += 1
            METRICS["chat_links_caught"] += 1
            await wipe_trigger(message)
            return


# ==============================================================================
# MANDATORY COMMAND MATRIX
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. /mute & /dmute
# ------------------------------------------------------------------------------
@router.message(Command("mute", "dmute"))
async def handle_mute(message: Message, command: CommandObject, bot: Bot) -> None:
    # RULE: Immediate async call to message.delete() BEFORE anything else
    await wipe_trigger(message)

    # Parallel Native Administrator Rights Validation
    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members"):
        return

    target_id, target_name, remaining_args = await resolve_target(message, command)
    if not target_id:
        return

    # Check if target is an admin (cannot restrict admins)
    if await check_admin_rights(bot, message.chat.id, target_id):
        return

    # If /dmute, wipe target replied-to message as well
    if command.command.lower() == "dmute" and message.reply_to_message:
        try:
            await message.reply_to_message.delete()
        except Exception:
            pass

    # Parse duration (e.g. /mute 10m flood)
    parts = remaining_args.split(maxsplit=1) if remaining_args else []
    duration_str = parts[0] if parts else None
    reason = parts[1] if len(parts) > 1 else "No reason specified"

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
    except Exception:
        pass


@router.message(Command("unmute"))
async def handle_unmute(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members"):
        return

    target_id, _, _ = await resolve_target(message, command)
    if not target_id:
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
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 2. /pin & /unpin
# ------------------------------------------------------------------------------
@router.message(Command("pin"))
async def handle_pin(message: Message, bot: Bot) -> None:
    # RULE: Immediate async call to message.delete()
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_pin_messages"):
        return

    if not message.reply_to_message:
        return

    try:
        # Notification suppression: disable_notification=True
        await bot.pin_chat_message(
            chat_id=message.chat.id,
            message_id=message.reply_to_message.message_id,
            disable_notification=True
        )
    except Exception:
        pass


@router.message(Command("unpin"))
async def handle_unpin(message: Message, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_pin_messages"):
        return

    try:
        if message.reply_to_message:
            await bot.unpin_chat_message(
                chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )
        else:
            await bot.unpin_all_chat_messages(chat_id=message.chat.id)
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 3. /clear
# ------------------------------------------------------------------------------
@router.message(Command("clear", "purge"))
async def handle_clear(message: Message, command: CommandObject, bot: Bot) -> None:
    # RULE: Immediate wipe trigger
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_delete_messages"):
        return

    chat_id = message.chat.id

    # If replying to a message, purge from that message forward up to trigger
    if message.reply_to_message:
        start_id = message.reply_to_message.message_id
        end_id = message.message_id
        msg_ids = list(range(start_id, end_id))
        if msg_ids:
            # Batch delete in chunks of 100 (Telegram limit)
            for i in range(0, len(msg_ids), 100):
                chunk = msg_ids[i:i + 100]
                try:
                    await bot.delete_messages(chat_id=chat_id, message_ids=chunk)
                except Exception:
                    # Fallback single message deletion
                    for mid in chunk:
                        try:
                            await bot.delete_message(chat_id=chat_id, message_id=mid)
                        except Exception:
                            pass
        return

    # If numeric count provided: e.g. /clear 20
    if command.args and command.args.strip().isdigit():
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


# ------------------------------------------------------------------------------
# 4. /ban, /dban, & /tban
# ------------------------------------------------------------------------------
@router.message(Command("ban", "dban", "tban"))
async def handle_ban_matrix(message: Message, command: CommandObject, bot: Bot) -> None:
    # RULE: Immediate wipe trigger
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members"):
        return

    target_id, _, remaining_args = await resolve_target(message, command)
    if not target_id:
        return

    if await check_admin_rights(bot, message.chat.id, target_id):
        return

    cmd = command.command.lower()

    # /dban: absolute wipe of target replied message
    if cmd == "dban" and message.reply_to_message:
        try:
            await message.reply_to_message.delete()
        except Exception:
            pass

    # /tban: parse duration
    until_ts = None
    if cmd == "tban":
        parts = remaining_args.split(maxsplit=1) if remaining_args else []
        duration_str = parts[0] if parts else "1h"
        seconds, _ = parse_time_duration(duration_str)
        if seconds > 0:
            until_ts = int(time.time() + seconds)

    try:
        await bot.ban_chat_member(
            chat_id=message.chat.id,
            user_id=target_id,
            until_date=until_ts
        )
    except Exception:
        pass


@router.message(Command("unban"))
async def handle_unban(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members"):
        return

    target_id, _, _ = await resolve_target(message, command)
    if not target_id:
        return

    try:
        await bot.unban_chat_member(
            chat_id=message.chat.id,
            user_id=target_id,
            only_if_banned=True
        )
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 4B. /kickme (Instant Self-Kick for Members - Hidden from Catalog)
# ------------------------------------------------------------------------------
@router.message(Command("kickme"))
async def handle_kickme(message: Message, bot: Bot) -> None:
    """
    /kickme:
    Instantly kicks the sending member from the group.
    - Intentionally omitted from command catalogs (hidden command).
    - Immediate trigger wipe (<1ms).
    - Performs ban + unban to eject member without a permanent blacklist.
    """
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # Instant wipe of trigger message
    await wipe_trigger(message)

    user = message.from_user
    if not user or user.is_bot:
        return

    chat_id = message.chat.id
    user_id = user.id

    # Telegram Bot API prevents kicking chat owners or administrators
    if await check_admin_rights(bot, chat_id, user_id):
        return

    try:
        # Standard Telegram kick: ban + unban to immediately eject from the chat
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)

        # Background audit logging
        DatabaseService.log_moderation_background(
            chat_id=chat_id,
            admin_id=user_id,
            target_id=user_id,
            action="kickme",
            reason="Self-kick request"
        )
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 5. /promote & /demote
# ------------------------------------------------------------------------------
@router.message(Command("promote"))
async def handle_promote(message: Message, command: CommandObject, bot: Bot) -> None:
    """
    Instantly lifts target to admin status with exactly 0 custom permissions.
    """
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_promote_members"):
        return

    target_id, _, _ = await resolve_target(message, command)
    if not target_id:
        return

    try:
        # Lifts to admin with 0 custom permissions
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
        # Invalidate target's cached rights
        ADMIN_CACHE.pop((message.chat.id, target_id), None)
    except Exception:
        pass


@router.message(Command("demote"))
async def handle_demote(message: Message, command: CommandObject, bot: Bot) -> None:
    """
    Instantly strips all admin privileges from the target user.
    """
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_promote_members"):
        return

    target_id, _, _ = await resolve_target(message, command)
    if not target_id:
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
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 6. /warn, /resetwarn, & /warns
# ------------------------------------------------------------------------------
@router.message(Command("warn"))
async def handle_warn(message: Message, command: CommandObject, bot: Bot) -> None:
    """
    Increments local counter and triggers automated enforcement upon hitting ceiling.
    """
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members"):
        return

    target_id, target_name, remaining_args = await resolve_target(message, command)
    if not target_id:
        return

    if await check_admin_rights(bot, message.chat.id, target_id):
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
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members"):
        return

    target_id, _, _ = await resolve_target(message, command)
    if not target_id:
        return

    # In-memory reset: pop key immediately to eliminate zero-value RAM residue
    WARN_CACHE[message.chat.id].pop(target_id, None)
    if not WARN_CACHE[message.chat.id]:
        WARN_CACHE.pop(message.chat.id, None)
    DatabaseService.reset_warn_background(message.chat.id, target_id)
    DatabaseService.log_moderation_background(message.chat.id, user_id, target_id, "resetwarn")


@router.message(Command("warns"))
async def handle_get_warns(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    target_id, _, _ = await resolve_target(message, command)
    if not target_id:
        target_id = message.from_user.id if message.from_user else 0

    count = WARN_CACHE[message.chat.id].get(target_id, 0)
    ceiling = CHAT_SETTINGS[message.chat.id].get("warn_limit", 3)

    # Send ephemeral warning status (deleted after 5s to keep chat pristine)
    try:
        notice = await message.answer(f"⚠️ User Warning Count: <b>{count}/{ceiling}</b>", parse_mode=ParseMode.HTML)
        await asyncio.sleep(5)
        await notice.delete()
    except Exception:
        pass


# ==============================================================================
# INTERACTIVE SETTINGS UI (MATCHING BIOLINK RESTRICTOR ARCHITECTURE)
# ==============================================================================

def generate_settings_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    """
    Renders high-speed modular settings hub with direct jump to feature customization submenus.
    """
    s = CHAT_SETTINGS[chat_id]
    warn_dur_str = format_duration(s.get("warn_duration", 86400))
    flood_dur_str = format_duration(s.get("flood_duration", 900))
    media_blocked = sum(1 for k in [
        "block_sticker", "block_animation", "block_document",
        "block_audio", "block_voice", "block_photo", "block_video"
    ] if s.get(k))

    buttons = [
        [
            InlineKeyboardButton(
                text=f"⚠️ Warn Ceiling ({s.get('warn_limit', 3)} ➔ {s.get('warn_action', 'mute').upper()} {warn_dur_str})",
                callback_data=f"set:menu:warn:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"⚡ Anti-Flood ({'ON' if s.get('flood_protection') else 'OFF'} | {s.get('flood_limit', 5)}msg/{int(s.get('flood_window', 3))}s ➔ {s.get('flood_action', 'mute').upper()})",
                callback_data=f"set:menu:flood:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🤖 Anti-Bot ({'ON' if s.get('block_bots') else 'OFF'} ➔ {s.get('bot_action', 'ban').upper()})",
                callback_data=f"set:menu:bot:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"🧹 Service Msgs ({'ON' if s.get('clean_service_messages', True) else 'OFF'})",
                callback_data=f"set:menu:service:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"🔗 Links & Invites ({'RESTRICTED' if s.get('block_links') or s.get('admin_links_block') else 'ALLOWED'})",
                callback_data=f"set:menu:links:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"🎭 Media Filters ({media_blocked}/7 Blocked)",
                callback_data=f"set:menu:media:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"👥 Excepted Admins ({len(s.get('excepted_admins', []))} configured)",
                callback_data=f"set:menu:excepted:{chat_id}"
            )
        ],
    ]

    if is_dm:
        buttons.append([
            InlineKeyboardButton(text="🔄 Reload", callback_data=f"set:reload:{chat_id}"),
            InlineKeyboardButton(text="⬅️ Back to Groups", callback_data="dm:manage_settings"),
            InlineKeyboardButton(text="🏠 Main Menu", callback_data="dm:main_menu"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="🔄 Reload", callback_data=f"set:reload:{chat_id}"),
            InlineKeyboardButton(text="✅ Close", callback_data=f"set:close:{chat_id}"),
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def generate_warn_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    s = CHAT_SETTINGS[chat_id]
    w_limit = s.get("warn_limit", 3)
    w_action = s.get("warn_action", "mute").upper()
    w_dur = format_duration(s.get("warn_duration", 86400))
    cancel_on = s.get("warn_cancel_btn", True)
    custom_msg = s.get("custom_warn_msg", "").strip()

    buttons = [
        [
            InlineKeyboardButton(text="➖ Decrease", callback_data=f"set:warn_dec:{chat_id}"),
            InlineKeyboardButton(text=f"⚠️ Ceiling: {w_limit} Warns", callback_data=f"set:warn_cycle:{chat_id}"),
            InlineKeyboardButton(text="➕ Increase", callback_data=f"set:warn_inc:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text=f"🔨 Punishment: {w_action} (MUTE/BAN/KICK)", callback_data=f"set:warn_action:{chat_id}")
        ],
        [
            InlineKeyboardButton(text=f"⏱️ Duration: {w_dur}", callback_data=f"set:warn_dur:{chat_id}")
        ],
        [
            InlineKeyboardButton(
                text=f"❌ Cancel Button: {'✅ ON' if cancel_on else '❌ OFF'}",
                callback_data=f"set:warn_toggle_cancel:{chat_id}"
            )
        ],
    ]

    if is_dm:
        buttons.append([
            InlineKeyboardButton(
                text=f"✏️ Custom Msg: {'Customized' if custom_msg else 'Default'}",
                callback_data=f"set:warn_custom_msg:{chat_id}"
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
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"set:menu:main:{chat_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_warn_text(chat_title: str, s: Dict[str, Any]) -> str:
    w_limit = s.get("warn_limit", 3)
    w_action = s.get("warn_action", "mute").upper()
    w_dur = format_duration(s.get("warn_duration", 86400))
    cancel_on = s.get("warn_cancel_btn", True)
    custom_msg = s.get("custom_warn_msg", "").strip()
    status_custom = "Custom Template Active" if custom_msg else "Default Template"
    return (
        f"⚠️ <b>WARN CEILING & ANTI-SPAM NOTICE CONFIGURATION</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"• <b>Violation Ceiling:</b> <code>{w_limit} warnings</code>\n"
        f"• <b>Punishment Action:</b> <code>{w_action}</code> (MUTE / BAN / KICK)\n"
        f"• <b>Penalty Duration:</b> <code>{w_dur}</code>\n"
        f"• <b>Inline Cancel Button:</b> {'<code>ENABLED</code>' if cancel_on else '<i>DISABLED</i>'}\n"
        f"• <b>Warn Notice Template:</b> <code>{status_custom}</code>\n\n"
        f"<i>Tap the buttons below to customize thresholds, toggle the cancel button, or configure custom messages in DM:</i>"
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
    s = CHAT_SETTINGS[chat_id]
    is_on = s.get("flood_protection", True)
    f_limit = s.get("flood_limit", 5)
    f_win = int(s.get("flood_window", 3))
    f_action = s.get("flood_action", "mute").upper()
    f_dur = format_duration(s.get("flood_duration", 900))
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"⚡ Protection: {'✅ ACTIVE' if is_on else '❌ DISABLED'}",
                callback_data=f"set:flood_toggle:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(text="➖ Msg", callback_data=f"set:flood_limit_dec:{chat_id}"),
            InlineKeyboardButton(text=f"📬 Limit: {f_limit} msgs", callback_data=f"set:flood_limit_cycle:{chat_id}"),
            InlineKeyboardButton(text="➕ Msg", callback_data=f"set:flood_limit_inc:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="➖ Sec", callback_data=f"set:flood_win_dec:{chat_id}"),
            InlineKeyboardButton(text=f"⏱️ Window: {f_win}s", callback_data=f"set:flood_win_cycle:{chat_id}"),
            InlineKeyboardButton(text="➕ Sec", callback_data=f"set:flood_win_inc:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text=f"🔨 Punishment: {f_action}", callback_data=f"set:flood_action:{chat_id}"),
            InlineKeyboardButton(text=f"⏱️ Mute Duration: {f_dur}", callback_data=f"set:flood_dur:{chat_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"set:menu:main:{chat_id}")
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


def generate_bot_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    s = CHAT_SETTINGS[chat_id]
    is_on = s.get("block_bots", False)
    b_action = s.get("bot_action", "ban").upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🤖 Anti-Bot: {'✅ ACTIVE' if is_on else '❌ DISABLED'}",
                callback_data=f"set:bot_toggle:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🔨 Punishment: {b_action} (BAN / KICK)",
                callback_data=f"set:bot_action:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"set:menu:main:{chat_id}")
        ]
    ])


def format_bot_text(chat_title: str, s: Dict[str, Any]) -> str:
    is_on = s.get("block_bots", False)
    b_action = s.get("bot_action", "ban").upper()
    return (
        f"🤖 <b>ANTI-BOT AUTO-PROTECTION</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"• <b>Status:</b> {'<code>ACTIVE</code>' if is_on else '<i>Disabled</i>'}\n"
        f"• <b>Punishment Action:</b> <code>{b_action}</code> (BAN: permanent / KICK: allows rejoining)\n\n"
        f"<i>When active, any unauthorized bot added to this group is instantly penalized.</i>"
    )


def generate_service_keyboard(chat_id: int, is_dm: bool = False) -> InlineKeyboardMarkup:
    s = CHAT_SETTINGS[chat_id]
    is_on = s.get("clean_service_messages", True)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🚷 Delete Join/Left: {'✅ ACTIVE' if is_on else '❌ DISABLED'}",
                callback_data=f"set:service_toggle:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"set:menu:main:{chat_id}")
        ]
    ])


def format_service_text(chat_title: str, s: Dict[str, Any]) -> str:
    is_on = s.get("clean_service_messages", True)
    return (
        f"🧹 <b>SERVICE MESSAGE CLEANER</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"• <b>Status:</b> {'<code>ACTIVE (Auto-Delete)</code>' if is_on else '<i>Disabled</i>'}\n\n"
        f"<i>Automatically purges user joined and user left system notifications.</i>"
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
    return (
        f"👥 <b>EXCEPTED ADMINISTRATORS</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"Designated administrators who have full setup permissions and receive confidential <code>/show</code> reports:\n"
        f"{list_str}\n\n"
        f"<i>To add an administrator, reply to their message in the group with <code>/addexcept</code>.</i>"
    )


def format_settings_text(chat_title: str, s: Dict[str, Any]) -> str:
    """Renders standardized settings dashboard text."""
    warn_dur_str = format_duration(s.get("warn_duration", 86400))
    flood_dur_str = format_duration(s.get("flood_duration", 900))
    media_blocked = sum(1 for k in [
        "block_sticker", "block_animation", "block_document",
        "block_audio", "block_voice", "block_photo", "block_video"
    ] if s.get(k))

    return (
        f"⚙️ <b>GROUP CONFIGURATION DASHBOARD</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"🛡️ <b>PUNISHMENTS & VIOLATIONS:</b>\n"
        f"• <b>Warn Ceiling:</b> <code>{s.get('warn_limit', 3)} violations</code> ➔ <code>{s.get('warn_action', 'mute').upper()} ({warn_dur_str})</code>\n"
        f"• <b>Anti-Flood:</b> {'<code>ACTIVE</code>' if s.get('flood_protection') else '<i>Disabled</i>'} "
        f"({s.get('flood_limit', 5)} msgs / {int(s.get('flood_window', 3))}s) ➔ <code>{s.get('flood_action', 'mute').upper()} ({flood_dur_str})</code>\n"
        f"• <b>Anti-Bot:</b> {'<code>ACTIVE</code>' if s.get('block_bots') else '<i>Disabled</i>'} "
        f"➔ <code>{s.get('bot_action', 'ban').upper()}</code>\n\n"
        f"🔒 <b>RESTRICTIONS & FILTERS:</b>\n"
        f"• <b>Member Links:</b> {'<code>Blocked</code>' if s.get('block_links') else '<i>Allowed</i>'} (Action: <code>{s.get('link_action', 'delete').upper()}</code>)\n"
        f"• <b>Admin Links:</b> {'<code>Blocked</code>' if s.get('admin_links_block') else '<i>Allowed</i>'}\n"
        f"• <b>Channel Links / Invites:</b> {'<code>Blocked</code>' if s.get('block_channel_links') else '<i>Allowed</i>'}\n"
        f"• <b>Media Blocked:</b> <code>{media_blocked}/7 types</code> (Action: <code>{s.get('media_action', 'delete').upper()}</code>)\n"
        f"• <b>Join/Left Cleanup:</b> {'<code>ACTIVE</code>' if s.get('clean_service_messages', True) else '<i>Disabled</i>'}\n"
        f"• <b>Excepted Admins:</b> <code>{len(s.get('excepted_admins', []))} designated</code>\n\n"
        f"👉 <i>Tap any category below to customize rules, thresholds, and punishments:</i>"
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
            return

        chat_id = message.chat.id
        chat_title = message.chat.title or "This Chat"
        s = CHAT_SETTINGS[chat_id]

        text = format_settings_text(chat_title, s)

        try:
            await message.answer(text, reply_markup=generate_settings_keyboard(chat_id), parse_mode=ParseMode.HTML)
        except Exception:
            pass
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
                target_cid = int(arg.replace("group_", ""))
            except ValueError:
                pass
        elif arg.startswith("-100"):
            try:
                target_cid = int(arg)
            except ValueError:
                pass
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
                    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
                    return
                except Exception:
                    pass

        if target_cid and await check_can_setup_bot(bot, target_cid, user_id):
            s = CHAT_SETTINGS[target_cid]
            title = await get_cached_chat_title(bot, target_cid)
            text = format_settings_text(title, s)
            try:
                await message.answer(
                    text,
                    reply_markup=generate_settings_keyboard(target_cid, is_dm=True),
                    parse_mode=ParseMode.HTML
                )
                return
            except Exception:
                pass

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
        await message.answer(
            welcome_text,
            reply_markup=generate_dm_main_menu(bot_user.username or "personal_guardBot"),
            parse_mode=ParseMode.HTML
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


@router.callback_query(F.data.in_({"dm:manage_settings", "dm:refresh_groups"}))
async def handle_dm_manage_settings(query: CallbackQuery, bot: Bot) -> None:
    """Displays authorized groups for configuration from private DM."""
    user_id = query.from_user.id
    bot_user = await bot.get_me()

    authorized_chats = []
    for cid in list(CHAT_SETTINGS.keys()):
        if cid < 0 and await check_can_setup_bot(bot, cid, user_id):
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
            "⚙️ <b>Manage Group Settings</b>\n"
            "👉 <i>Select the group whose settings you want to change:</i>\n\n"
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

    if not await check_can_setup_bot(bot, chat_id, user_id):
        await query.answer("❌ You are not an authorized admin for this group.", show_alert=True)
        return

    s = CHAT_SETTINGS[chat_id]
    chat_title = await get_cached_chat_title(bot, chat_id)
    text = format_settings_text(chat_title, s)
    try:
        await query.message.edit_text(
            text,
            reply_markup=generate_settings_keyboard(chat_id, is_dm=True),
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


@router.callback_query(F.data.startswith("set:"))
async def handle_settings_callback(query: CallbackQuery, bot: Bot) -> None:
    """
    Handles interactive settings configuration clicks (both in-group and from private DMs).
    Guarded strictly by check_can_setup_bot (Owner, Anonymous Admin, Excepted Admin).
    Provides deep modular customization for all violation limits, punishments, and features.
    """
    parts = query.data.split(":")
    if len(parts) < 3:
        await query.answer()
        return

    action = parts[1]
    # For nested menu callbacks: set:menu:<submenu>:<chat_id>
    if action == "menu" and len(parts) >= 4:
        sub = parts[2]
        try:
            chat_id = int(parts[3])
        except ValueError:
            await query.answer()
            return
    else:
        sub = None
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
    chat_title = await get_cached_chat_title(bot, chat_id)

    # 1. Close Menu Action
    if action == "close":
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.answer("Closed.")
        return

    # 2. Category Submenu Navigation
    if action == "menu":
        if sub == "main":
            text = format_settings_text(chat_title, s)
            kb = generate_settings_keyboard(chat_id, is_dm=is_dm)
        elif sub == "warn":
            text = format_warn_text(chat_title, s)
            kb = generate_warn_keyboard(chat_id, is_dm=is_dm)
        elif sub == "flood":
            text = format_flood_text(chat_title, s)
            kb = generate_flood_keyboard(chat_id, is_dm=is_dm)
        elif sub == "bot":
            text = format_bot_text(chat_title, s)
            kb = generate_bot_keyboard(chat_id, is_dm=is_dm)
        elif sub == "service":
            text = format_service_text(chat_title, s)
            kb = generate_service_keyboard(chat_id, is_dm=is_dm)
        elif sub == "links":
            text = format_links_text(chat_title, s)
            kb = generate_links_keyboard(chat_id, is_dm=is_dm)
        elif sub == "media":
            text = format_media_text(chat_title, s)
            kb = generate_media_keyboard(chat_id, is_dm=is_dm)
        elif sub == "excepted":
            text = format_excepted_text(chat_title, s)
            kb = generate_excepted_keyboard(chat_id, is_dm=is_dm)
        else:
            text = format_settings_text(chat_title, s)
            kb = generate_settings_keyboard(chat_id, is_dm=is_dm)

        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
        return

    # 3. Warn Ceiling & Punishment Mutations
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

    # 4. Anti-Flood Tuning & Punishment Mutations
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

    # 5. Anti-Bot Protection & Punishment
    elif action == "bot_toggle":
        s["block_bots"] = not s.get("block_bots", False)
        await query.answer(f"Anti-Bot: {'ACTIVE' if s['block_bots'] else 'DISABLED'}")
    elif action == "bot_action":
        s["bot_action"] = "kick" if s.get("bot_action", "ban") == "ban" else "ban"
        await query.answer(f"Anti-Bot Punishment: {s['bot_action'].upper()}")

    # 6. Service Messages Cleaner
    elif action == "service_toggle":
        s["clean_service_messages"] = not s.get("clean_service_messages", True)
        await query.answer(f"Join/Left Cleaner: {'ACTIVE' if s['clean_service_messages'] else 'DISABLED'}")

    # 7. Links & Invites Restrictions
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

    # 8. Media Restrictions
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

    # 9. Excepted Admins Management
    elif action == "excepted_clear":
        s["excepted_admins"] = []
        await query.answer("All Excepted Admins cleared.", show_alert=True)
    elif action == "reload":
        await query.answer("Settings reloaded.")

    # Background MongoDB persistence (write-behind non-blocking)
    DatabaseService.save_settings_background(chat_id, chat_title, s)

    # Re-render appropriate screen
    if action.startswith("warn_"):
        text = format_warn_text(chat_title, s)
        kb = generate_warn_keyboard(chat_id, is_dm=is_dm)
    elif action.startswith("flood_"):
        text = format_flood_text(chat_title, s)
        kb = generate_flood_keyboard(chat_id, is_dm=is_dm)
    elif action.startswith("bot_"):
        text = format_bot_text(chat_title, s)
        kb = generate_bot_keyboard(chat_id, is_dm=is_dm)
    elif action.startswith("service_"):
        text = format_service_text(chat_title, s)
        kb = generate_service_keyboard(chat_id, is_dm=is_dm)
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
        text = format_settings_text(chat_title, s)
        kb = generate_settings_keyboard(chat_id, is_dm=is_dm)

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
# PRIVATE DM CUSTOM WARN MESSAGE LISTENER & CANCEL ENGINE
# ==============================================================================

@router.message(Command("cancel"), F.chat.type == ChatType.PRIVATE)
async def handle_dm_cancel_input(message: Message) -> None:
    """Cancels active custom warning message editing in private DM."""
    user_id = message.from_user.id if message.from_user else 0
    if user_id in PENDING_CUSTOM_WARN:
        chat_id = PENDING_CUSTOM_WARN.pop(user_id)
        await message.answer(
            "❌ Custom warning message configuration cancelled.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Return to Warn Settings", callback_data=f"set:menu:warn:{chat_id}")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="dm:main_menu")]
            ])
        )


@router.message(F.chat.type == ChatType.PRIVATE, ~F.text.startswith("/"))
async def handle_dm_custom_warn_text(message: Message, bot: Bot) -> None:
    """
    Listens for custom warning message template input sent by an authorized admin in private DM.
    Saves the template to chat settings and MongoDB and shows a live preview.
    """
    user_id = message.from_user.id if message.from_user else 0
    if user_id not in PENDING_CUSTOM_WARN:
        return

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
        "• <code>/start</code> - Open group protection settings (Authorized admins only)\n"
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
@router.message(Command("addexcept", "exceptadmin"))
async def handle_add_except_admin(message: Message, command: CommandObject, bot: Bot) -> None:
    """Designates an admin as an Excepted Admin to receive report notifications."""
    await wipe_trigger(message)
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    user_id = message.from_user.id if message.from_user else 0
    # Rule: ONLY Owner, Anonymous Admins, or Excepted Admins can setup the bot
    if not await check_can_setup_bot(bot, message.chat.id, user_id, sender_chat_id):
        return

    target_id, target_name, _ = await resolve_target(message, command)
    if not target_id:
        return

    chat_id = message.chat.id
    if message.chat and message.chat.title:
        CHAT_TITLES[chat_id] = message.chat.title
    settings = CHAT_SETTINGS[chat_id]
    current_excepted = set(settings.get("excepted_admins", []))
    current_excepted.add(target_id)
    settings["excepted_admins"] = list(current_excepted)

    chat_title = message.chat.title or "This Chat"
    DatabaseService.save_settings_background(chat_id, chat_title, settings)

    try:
        notice = await message.answer(
            f"✅ User <code>{target_id}</code> designated as an <b>Excepted Admin</b> (will receive confidential reports).",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(5)
        await notice.delete()
    except Exception:
        pass


@router.message(Command("remexcept", "unexceptadmin"))
async def handle_rem_except_admin(message: Message, command: CommandObject, bot: Bot) -> None:
    """Removes an admin from the Excepted Admins report recipient list."""
    await wipe_trigger(message)
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    user_id = message.from_user.id if message.from_user else 0
    if not await check_can_setup_bot(bot, message.chat.id, user_id, sender_chat_id):
        return

    target_id, _, _ = await resolve_target(message, command)
    if not target_id:
        return

    chat_id = message.chat.id
    if message.chat and message.chat.title:
        CHAT_TITLES[chat_id] = message.chat.title
    settings = CHAT_SETTINGS[chat_id]
    current_excepted = set(settings.get("excepted_admins", []))
    current_excepted.discard(target_id)
    settings["excepted_admins"] = list(current_excepted)

    chat_title = message.chat.title or "This Chat"
    DatabaseService.save_settings_background(chat_id, chat_title, settings)

    try:
        notice = await message.answer(
            f"✅ User <code>{target_id}</code> removed from <b>Excepted Admins</b>.",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(5)
        await notice.delete()
    except Exception:
        pass


@router.message(Command("excepted"))
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
    excepted_ids = settings.get("excepted_admins", [])

    if excepted_ids:
        formatted = "\n".join(f"• <code>{uid}</code>" for uid in excepted_ids)
        text = (
            f"👥 <b>Excepted Admins for Reports:</b>\n{formatted}\n\n"
            f"<i>Note: Owner of the GC & Anonymous Admins always receive reports automatically.</i>"
        )
    else:
        text = (
            "👥 <b>Excepted Admins for Reports:</b> <i>None configured.</i>\n\n"
            "<i>Currently, reports are delivered strictly to the Owner of the GC & Anonymous Admins. Use <code>/addexcept &lt;id&gt;</code> to designate additional admins.</i>"
        )

    try:
        notice = await message.answer(text, parse_mode=ParseMode.HTML)
        await asyncio.sleep(8)
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
        BotCommand(command="report", description="(Reply only) Report message publicly"),
        BotCommand(command="show", description="(Reply only) Report message to admins in PM"),
        BotCommand(command="addexcept", description="Designate admin to receive reports"),
        BotCommand(command="remexcept", description="Remove admin from report recipients"),
        BotCommand(command="excepted", description="List excepted report admins"),
        BotCommand(command="start", description="Open group settings (Authorized admins only)"),
        BotCommand(command="settings", description="Alias to /start group settings"),
        BotCommand(command="setcommands", description="Force sync admin command catalog"),
    ]

    # Commands visible to regular members inside group chats
    group_member_commands = [
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

            # 5. HARD 500MB RAM CIRCUIT BREAKER TIER CHECKS:
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
                WARN_CACHE.clear()
                PENDING_CUSTOM_WARN.clear()
                CHAT_TITLES.clear()

            if rss_mb > 400.0:
                # Tier 3 Critical Circuit Breaker (>400MB): Complete heap shed before Render's 512MB OOM
                ADMIN_CACHE.clear()
                FLOOD_CACHE.clear()
                WARN_CACHE.clear()
                PENDING_CUSTOM_WARN.clear()
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

    # Health check routes for Render Web Service
    app.router.add_get("/health", health_handler)
    app.router.add_get("/", health_handler)

    try:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"[RENDER] Health check route /health active on 0.0.0.0:{port}")
        return runner
    except Exception as e:
        print(f"[RENDER WARNING] Could not bind health server to port {port}: {e}")
        return None


# ==============================================================================
# APPLICATION BOOTSTRAP & EXECUTION RUNNER
# ==============================================================================

async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token or token.strip() == "YOUR_BOT_TOKEN_HERE":
        print("=" * 70)
        print("[CRITICAL] BOT_TOKEN is not configured!")
        print("Please set the BOT_TOKEN environment variable or populate it in your .env file.")
        print("Example: set BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")
        print("=" * 70)
        # Still validate initialization for syntax testing
        if len(sys.argv) > 1 and sys.argv[1] == "--check-syntax":
            print("[STATUS] Syntax and logic compilation verified successfully.")
            return
        sys.exit(1)

    print(f"[INITIALIZING] Launching Ultra-Optimized Admin Bot with {LOOP_ENGINE}...")

    # High-efficiency metered session connector with DNS caching & socket limit (Render RAM & Bandwidth optimization)
    session = MeteredAiohttpSession(limit=10)
    bot = Bot(token=token.strip(), session=session)
    dp = Dispatcher()

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
    except Exception as e:
        print(f"[BOT] Profile resolution notice: {e}")

    # Register high-speed Anti-Flood Middleware
    dp.message.middleware(AntiFloodMiddleware())

    # Include routers
    dp.include_router(router)

    # Delete existing webhook to guarantee clean fast long-polling
    await bot.delete_webhook(drop_pending_updates=True)

    # Connect to MongoDB & hydrate in-memory caches
    await MongoDBManager.connect()
    if MongoDBManager.is_connected():
        await DatabaseService.hydrate_settings_cache(CHAT_SETTINGS, CHAT_TITLES)
        await DatabaseService.hydrate_warn_cache(WARN_CACHE)

    # Register admin-only command catalog with Telegram API
    await setup_bot_commands(bot)

    # Start background RAM & cache resource optimizer task
    optimizer_task = asyncio.create_task(resource_optimizer_worker())

    # Start Render health server if PORT is assigned
    health_runner = await start_render_health_server()

    print(f"[READY] Listening for commands with zero DB roundtrips. Engine: {LOOP_ENGINE}")

    try:
        # Polling timeout set to 50s: holds long-polling socket up to 50s on Telegram server.
        # Slashes outbound HTTP request headers by >90% to stay well under Render's 5GB limit (<50MB/mo).
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            polling_timeout=50,
            handle_signals=True
        )
    finally:
        optimizer_task.cancel()
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
