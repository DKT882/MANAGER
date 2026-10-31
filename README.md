# High-Speed Telegram Admin Engine

An ultra-optimized Telegram moderation bot built in Python 3.11+ using `aiogram` (v3.x) with near-C event loop speed and zero-database in-memory caching.

## Features & Speed Architecture

1. **Sub-Millisecond Loop Acceleration**
   - Integrates `uvloop` on Linux / macOS and `winloop` on Windows for ultra-fast C-level I/O loop performance.
   - Fully local in-memory caching system (`CHAT_SETTINGS`, `WARN_CACHE`, `FLOOD_CACHE`, and `ADMIN_CACHE` with 60s TTL) eliminating all database latency.

2. **Instant Message Wipe Trigger Engine**
   - Every incoming admin command immediately issues an asynchronous `message.delete()` BEFORE any database/cache checks or permissions parsing.

3. **Strict Parallel Telegram Native Admin Rights Validation**
   - Enforces granular custom permissions against Telegram's native rights:
     - `can_restrict_members` (`/mute`, `/dmute`, `/ban`, `/dban`, `/tban`, `/warn`, `/resetwarn`)
     - `can_delete_messages` (`/clear`)
     - `can_pin_messages` (`/pin`, `/unpin`)
     - `can_promote_members` (`/promote`, `/demote`)
     - `can_change_info` (`/settings`)
   - Suppresses execution quietly if rights are missing.

4. **Mandatory Command Matrix**
   - `/mute <time> [reason]` & `/dmute <time> [reason]`: Wipe trigger/target + restrict send privileges.
   - `/unmute`: Restore user permissions.
   - `/pin`: Pin targets silently with notification suppression (`disable_notification=True`).
   - `/unpin`: Unpin replied or all messages.
   - `/clear [count]`: Instant batch wipe of recent messages.
   - `/ban`, `/dban`, & `/tban <time>`: Permanent, message-wiping, or temporary bans.
   - `/unban`: Revoke member ban.
   - `/promote`: Instantly lift target to admin with 0 custom permissions.
   - `/demote`: Instantly strip all administrator privileges.
   - `/warn`, `/resetwarn`, & `/warns`: Local warning counter mapping to automated enforcement ceilings.
   - `/report [reason]`: (Reply only) Publicly flag a message with one-click admin action buttons (`Delete`, `Mute`, `Ban`, `Dismiss`).
   - `/show [reason]`: (Reply only) Forward a violator report directly to administrators' private DMs with moderation buttons.
   - `/settings`: Interactive inline control panel matching the BioLink Restrictor architecture.

5. **Spam & Media Interceptors**
   - **Anti-Flood Middleware**: Sliding window frequency scanner (`flood_window: 3s`, `flood_limit: 5`) with automated restriction.
   - **Media Scanner**: Instant suppression for `sticker`, `gif` (animation), `document`, `audio`, and `voice`.
   - **Link Interceptor**: Real-time URL and invite link blocker with optional strict admin link deletion.

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Bot Token
Set the `BOT_TOKEN` environment variable:
- **Windows PowerShell:**
  ```powershell
  $env:BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
  ```
- **Linux/macOS:**
  ```bash
  export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
  ```

### 3. Launch the Bot
```bash
python bot.py
```
