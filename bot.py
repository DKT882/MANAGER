"""
High-Speed Telegram Admin Bot Implementation
Framework: aiogram v3.x | Event Loop: uvloop (Linux/macOS) / winloop (Windows)
Features: In-memory Caching, Instant Wipe Trigger, Strict Parallel Native Admin Rights,
          Anti-Flood Middleware, Instant Media/Link Interceptor, Interactive Settings UI.
"""

from __future__ import annotations

import asyncio
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

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router, types
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
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
    # Link filters
    "block_links": False,
    "admin_links_block": False,
    # Anti-flood settings
    "flood_protection": True,
    "flood_window": 3.0,       # Frequency window in seconds
    "flood_limit": 5,          # Maximum messages allowed inside window
    "flood_action": "mute",    # Violation action: 'mute' or 'delete'
    # Warning settings
    "warn_limit": 3,           # Ceiling before automated penalty
    "warn_action": "mute",     # Automated ceiling action: 'mute' or 'ban'
    "warn_duration": 86400,    # 24 hours penalty duration in seconds
}

# CHAT_SETTINGS: chat_id -> configuration dict
CHAT_SETTINGS: Dict[int, Dict[str, Any]] = defaultdict(lambda: DEFAULT_CHAT_CONFIG.copy())

# WARN_CACHE: chat_id -> user_id -> count
WARN_CACHE: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

# FLOOD_CACHE: chat_id -> user_id -> deque of monotonic timestamps
FLOOD_CACHE: Dict[int, Dict[int, deque]] = defaultdict(lambda: defaultdict(deque))

# ADMIN_CACHE: (chat_id, user_id) -> (monotonic_timestamp, set_of_permissions, is_owner)
# Caches Telegram administrator custom rights for 60s to prevent roundtrip API lag
ADMIN_CACHE: Dict[Tuple[int, int], Tuple[float, set, bool]] = {}
ADMIN_CACHE_TTL = 60.0  # seconds

# ==============================================================================
# INSTANT WIPE & PARALLEL NATIVE ADMIN RIGHTS ENGINE
# ==============================================================================

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
        cached_time, perms, is_owner = ADMIN_CACHE[cache_key]
        if now - cached_time < ADMIN_CACHE_TTL:
            if is_owner:
                return True
            if required_permission is None:
                return len(perms) > 0 or "is_admin" in perms
            return required_permission in perms

    # 2. Fetch fresh native rights from Telegram API
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        if isinstance(member, ChatMemberOwner):
            ADMIN_CACHE[cache_key] = (now, set(), True)
            return True
        elif isinstance(member, ChatMemberAdministrator):
            perms = {"is_admin"}
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

            ADMIN_CACHE[cache_key] = (now, perms, False)
            if required_permission is None:
                return True
            return required_permission in perms
        else:
            ADMIN_CACHE[cache_key] = (now, set(), False)
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

    match = re.match(r"^(\d+)([smhdw]?)$", duration_str.strip().lower())
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

            # 1. Instant wipe of violating flood message
            try:
                await event.delete()
            except Exception:
                pass

            # 2. Automated restriction
            action = settings.get("flood_action", "mute")
            try:
                if action == "mute":
                    until_ts = int(time.time() + 900)  # 15 minutes penalty
                    await bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        permissions=ChatPermissions(
                            can_send_messages=False,
                            can_send_media_messages=False,
                            can_send_other_messages=False,
                            can_add_web_page_previews=False,
                        ),
                        until_date=until_ts
                    )
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
# ASYNCHRONOUS MEDIA & LINK INTERCEPTOR (SUB-SECOND SCANNER)
# ==============================================================================

@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
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
    settings = CHAT_SETTINGS[chat_id]
    is_admin = await check_admin_rights(bot, chat_id, user.id)

    # 1. Media Type Interceptions
    if not is_admin:
        if settings.get("block_sticker") and message.sticker:
            await wipe_trigger(message)
            return

        if settings.get("block_animation") and message.animation:
            await wipe_trigger(message)
            return

        if settings.get("block_document") and message.document:
            await wipe_trigger(message)
            return

        if settings.get("block_audio") and message.audio:
            await wipe_trigger(message)
            return

        if settings.get("block_voice") and message.voice:
            await wipe_trigger(message)
            return

    # 2. Link Interceptions
    has_link = False
    if message.entities:
        for entity in message.entities:
            if entity.type in ("url", "text_link"):
                has_link = True
                break

    if not has_link and message.text:
        if re.search(r"(https?://\S+|t\.me/\S+|telegram\.me/\S+)", message.text, re.IGNORECASE):
            has_link = True

    if has_link:
        # Check non-admin link block
        if not is_admin and settings.get("block_links"):
            await wipe_trigger(message)
            return

        # Check strict admin link block
        if is_admin and settings.get("admin_links_block"):
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

    chat_id = message.chat.id
    settings = CHAT_SETTINGS[chat_id]
    ceiling = settings.get("warn_limit", 3)

    # Fast in-memory counter increment
    WARN_CACHE[chat_id][target_id] += 1
    current_warns = WARN_CACHE[chat_id][target_id]

    if current_warns >= ceiling:
        # Automated enforcement threshold reached
        WARN_CACHE[chat_id][target_id] = 0  # Reset counter
        action = settings.get("warn_action", "mute")
        duration = settings.get("warn_duration", 86400)
        until_ts = int(time.time() + duration)

        try:
            if action == "mute":
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=target_id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                    ),
                    until_date=until_ts
                )
            elif action == "ban":
                await bot.ban_chat_member(chat_id=chat_id, user_id=target_id, until_date=until_ts)
        except Exception:
            pass


@router.message(Command("resetwarn"))
async def handle_resetwarn(message: Message, command: CommandObject, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_restrict_members"):
        return

    target_id, _, _ = await resolve_target(message, command)
    if not target_id:
        return

    # In-memory reset
    WARN_CACHE[message.chat.id][target_id] = 0


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

def generate_settings_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Renders high-speed inline keyboard representing current in-memory settings.
    """
    s = CHAT_SETTINGS[chat_id]

    def state_badge(is_active: bool) -> str:
        return "✅ ON" if is_active else "❌ OFF"

    def block_badge(is_blocked: bool) -> str:
        return "❌ Blocked" if is_blocked else "✅ Allowed"

    buttons = [
        [
            InlineKeyboardButton(
                text=f"✉️ In-Chat Links: {state_badge(s['block_links'])}",
                callback_data=f"set:block_links:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"👮 Admin Links: {block_badge(s['admin_links_block'])}",
                callback_data=f"set:admin_links_block:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"🎭 Stickers: {block_badge(s['block_sticker'])}",
                callback_data=f"set:block_sticker:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"🎞️ GIFs: {block_badge(s['block_animation'])}",
                callback_data=f"set:block_animation:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"📁 Documents: {block_badge(s['block_document'])}",
                callback_data=f"set:block_document:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"🎙️ Audio/Voice: {block_badge(s['block_voice'])}",
                callback_data=f"set:block_voice:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"⚡ Anti-Flood: {state_badge(s['flood_protection'])} ({s['flood_limit']}msg/{int(s['flood_window'])}s)",
                callback_data=f"set:flood_protection:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"⚠️ Warn Limit: {s['warn_limit']} | Action: {s['warn_action'].upper()}",
                callback_data=f"set:warn_toggle:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(text="🔄 Reload", callback_data=f"set:reload:{chat_id}"),
            InlineKeyboardButton(text="✅ Close", callback_data=f"set:close:{chat_id}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("settings"))
async def handle_settings(message: Message, bot: Bot) -> None:
    await wipe_trigger(message)

    user_id = message.from_user.id if message.from_user else 0
    if not await check_admin_rights(bot, message.chat.id, user_id, "can_change_info"):
        return

    chat_id = message.chat.id
    chat_title = message.chat.title or "This Chat"
    s = CHAT_SETTINGS[chat_id]

    text = (
        f"⚙️ <b>SETTINGS MANAGEMENT</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"• <b>In-Chat Links:</b> {'Blocked' if s['block_links'] else 'Allowed'}\n"
        f"• <b>Admin Links:</b> {'DELETED' if s['admin_links_block'] else 'Allowed'}\n"
        f"• <b>Anti-Flood:</b> {'ACTIVE' if s['flood_protection'] else 'Disabled'} ({s['flood_limit']} in {int(s['flood_window'])}s)\n"
        f"• <b>Warn Ceiling:</b> {s['warn_limit']} violations ➔ {s['warn_action'].upper()}\n\n"
        f"<i>Select an option below to toggle local cache settings instantly:</i>"
    )

    try:
        await message.answer(text, reply_markup=generate_settings_keyboard(chat_id), parse_mode=ParseMode.HTML)
    except Exception:
        pass


@router.callback_query(F.data.startswith("set:"))
async def handle_settings_callback(query: CallbackQuery, bot: Bot) -> None:
    parts = query.data.split(":")
    if len(parts) < 3:
        await query.answer()
        return

    _, action, chat_id_str = parts[:3]
    chat_id = int(chat_id_str)

    user_id = query.from_user.id
    if not await check_admin_rights(bot, chat_id, user_id, "can_change_info"):
        await query.answer("❌ You lack administrative permissions to alter settings.", show_alert=True)
        return

    s = CHAT_SETTINGS[chat_id]

    if action == "close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if action == "reload":
        await query.answer("Refreshed in-memory settings.")
    elif action in ("block_links", "admin_links_block", "block_sticker", "block_animation", "block_document", "flood_protection"):
        s[action] = not s[action]
        await query.answer(f"Toggled {action}: {'ON' if s[action] else 'OFF'}")
    elif action == "block_voice":
        new_val = not s["block_voice"]
        s["block_voice"] = new_val
        s["block_audio"] = new_val
        await query.answer(f"Voice & Audio: {'Blocked' if new_val else 'Allowed'}")
    elif action == "warn_toggle":
        # Cycle through warn ceilings: 3 -> 5 -> 10 -> 3
        ceilings = [3, 5, 10]
        curr_idx = ceilings.index(s["warn_limit"]) if s["warn_limit"] in ceilings else 0
        s["warn_limit"] = ceilings[(curr_idx + 1) % len(ceilings)]
        await query.answer(f"Warn limit set to {s['warn_limit']}")

    # Fast in-memory UI re-render
    chat_title = query.message.chat.title or "This Chat"
    text = (
        f"⚙️ <b>SETTINGS MANAGEMENT</b>\n"
        f"Group: <code>{chat_title}</code>\n\n"
        f"• <b>In-Chat Links:</b> {'Blocked' if s['block_links'] else 'Allowed'}\n"
        f"• <b>Admin Links:</b> {'DELETED' if s['admin_links_block'] else 'Allowed'}\n"
        f"• <b>Anti-Flood:</b> {'ACTIVE' if s['flood_protection'] else 'Disabled'} ({s['flood_limit']} in {int(s['flood_window'])}s)\n"
        f"• <b>Warn Ceiling:</b> {s['warn_limit']} violations ➔ {s['warn_action'].upper()}\n\n"
        f"<i>Select an option below to toggle local cache settings instantly:</i>"
    )

    try:
        await query.message.edit_text(
            text=text,
            reply_markup=generate_settings_keyboard(chat_id),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ------------------------------------------------------------------------------
# 7. /start & /help
# ------------------------------------------------------------------------------
@router.message(Command("start", "help"))
async def handle_start_help(message: Message) -> None:
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await wipe_trigger(message)

    text = (
        "⚡ <b>High-Speed Telegram Admin Engine Active</b>\n\n"
        "<b>Available Admin Commands:</b>\n"
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
        "• <code>/settings</code> - Real-time in-memory group protection panel\n\n"
        f"<i>Engine loop: <code>{LOOP_ENGINE}</code> | Sub-second latency active.</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Open Group Settings", callback_data=f"set:reload:{message.chat.id}")],
    ])

    try:
        await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        pass


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
    bot = Bot(token=token.strip())
    dp = Dispatcher()

    # Register high-speed Anti-Flood Middleware
    dp.message.middleware(AntiFloodMiddleware())

    # Include routers
    dp.include_router(router)

    # Delete existing webhook to guarantee clean fast long-polling
    await bot.delete_webhook(drop_pending_updates=True)
    print(f"[READY] Listening for commands with zero DB roundtrips. Engine: {LOOP_ENGINE}")

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()


if __name__ == "__main__":
    if "--check-syntax" in sys.argv:
        print(f"[CHECK] Syntax valid. Event loop engine available: {LOOP_ENGINE}")
        sys.exit(0)

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[STOPPED] Bot terminated cleanly.")
