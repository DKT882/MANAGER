# MANAGER: Ultra-Optimized Telegram Moderation Engine

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-aiogram%20v3.x-informational.svg)](https://docs.aiogram.dev/)
[![Event Loop](https://img.shields.io/badge/loop-uvloop%20%2F%20winloop-success.svg)](https://github.com/MagicStack/uvloop)
[![Database](https://img.shields.io/badge/database-MongoDB%20%7C%20Motor-green.svg)](https://motor.readthedocs.io/)
[![License](https://img.shields.io/badge/license-MIT-purple.svg)](#)

An enterprise-grade, ultra-optimized Telegram group moderation bot engineered in Python using `aiogram` (v3.x). Designed for **sub-second, eye-blink command execution** (60–180ms), instant message cleanup, scoped administrative command catalogs, and durable MongoDB persistence.

---

## ⚡ Speed & Latency Architecture

### Sub-Second "Blink of an Eye" Execution
A human eye blink takes between **100 and 300 milliseconds**. `MANAGER` achieves end-to-end execution within **60 to 180 milliseconds**:

```
+-----------------------------------------------------------------------------------------+
| TOTAL END-TO-END TIMELINE: ~70ms - 180ms (Within the 100ms - 300ms Eye-Blink Window)   |
+-----------------------------------------------------------------------------------------+
  User Sends Command            Bot In-Memory Engine            Telegram Deletes / Restricts
 [Telegram Ingress: 20-60ms] -> [Local Compute: 0.5 - 2ms]   -> [Telegram Egress: 20-60ms]
                                          │
                              • Zero DB roundtrips on reads
                              • Instant delete trigger
                              • In-memory cache hit (<0.01ms)
                              • uvloop / winloop C core
```

1. **High-Performance C Event Loop:** Integrates `uvloop` (Linux/macOS) and `winloop` (Windows) for near-C loop execution.
2. **Instant Message Wipe Trigger Engine:** Every incoming admin command immediately executes `message.delete()` **before** running any permission parsing or cache checks.
3. **Strict Parallel Telegram Native Admin Rights Validation:** Granular permission verification (`can_restrict_members`, `can_delete_messages`, `can_pin_messages`, `can_promote_members`, `can_change_info`) backed by a 60-second in-memory TTL cache to eliminate remote API lag.
4. **Hybrid In-Memory Write-Behind MongoDB Architecture:** Reads run exclusively in RAM (`0ms`). Updates persist to MongoDB asynchronously in the background.

---

## 🛡️ Moderation & Command Matrix

### 1. Scoped Command Catalogs
Command autocomplete and menus in Telegram are strictly scoped:
- **Group Administrators (`BotCommandScopeAllChatAdministrators`):** Full moderation command catalog visible.
- **Regular Members (`BotCommandScopeAllGroupChats`):** Administrative commands are completely hidden. Regular members only see `/report` and `/show`.
- **Private Chats (`BotCommandScopeAllPrivateChats`):** Direct navigation commands (`/start`, `/help`, `/settings`).

### 2. Mandatory Command Matrix

| Command | Usage | Scope / Permissions | Description |
| :--- | :--- | :--- | :--- |
| `/mute` | `/mute <time> [reason]` | `can_restrict_members` | Wipes trigger; revokes member sending and media permissions. |
| `/dmute` | `/dmute <time> [reason]` | `can_restrict_members` | Wipes trigger + target replied message + mutes user. |
| `/unmute` | `/unmute [target]` | `can_restrict_members` | Restores default chat privileges. |
| `/pin` | (Reply to target) | `can_pin_messages` | Silently pins message (`disable_notification=True`). |
| `/unpin` | (Reply or all) | `can_pin_messages` | Unpins specific target or clears pinned messages. |
| `/clear` | `/clear [count]` or (Reply) | `can_delete_messages` | Batch-deletes messages backwards using native API chunking. |
| `/ban` | `/ban [target]` | `can_restrict_members` | Permanently kicks and bans member. |
| `/dban` | (Reply to target) | `can_restrict_members` | Deletes replied message + immediately bans violator. |
| `/tban` | `/tban <time> [target]` | `can_restrict_members` | Temporary ban (e.g. `1h`, `1d`, `7d`) with auto-unban timestamp. |
| `/unban` | `/unban [target]` | `can_restrict_members` | Revokes ban status. |
| `/promote` | `/promote [target]` | `can_promote_members` | Lifts target to admin with **0 custom permissions**. |
| `/demote` | `/demote [target]` | `can_promote_members` | Strips all administrator privileges. |
| `/warn` | `/warn [target]` | `can_restrict_members` | Increments warning count; triggers penalty at ceiling. |
| `/resetwarn`| `/resetwarn [target]` | `can_restrict_members` | Resets target's warning counter to zero. |
| `/warns` | `/warns [target]` | All Members (Ephemeral) | Returns user warning count (auto-deleted after 5 seconds). |
| `/kickme` | `/kickme` | All Members (Hidden) | Instantly kicks the calling member from the group without a permanent ban (allows rejoining). Omitted from command catalogs. |
| `/report` | `/report [reason]` (Reply only) | All Members & Admins | Publicly flags message in group with action buttons; sends private PMs **strictly** to Owner, Anonymous Admins & Excepted Admins. |
| `/show` | `/show [reason]` (Reply only) | All Members | Forwards violator report directly to the Owner, Anonymous Admins & Excepted Admins' private DMs. |
| `/addexcept`| `/addexcept [target]` | Owner / Anon / Excepted | Designates an admin as an Excepted Admin to receive report alerts. |
| `/remexcept`| `/remexcept [target]` | Owner / Anon / Excepted | Removes an admin from the Excepted Admin report notification list. |
| `/excepted` | `/excepted` | Owner / Anon / Excepted | Displays all currently configured Excepted Admins in the chat. |
| `/start` | `/start` | Owner / Anon / Excepted | Launches the bot and immediately displays group settings (strictly visible to authorized admins only). In DM: opens multi-group management hub. |
| `/settings` | `/settings` | Owner / Anon / Excepted | Alias to `/start` group settings dashboard. |
| `/setcommands`| `/setcommands` | Owner / Anon / Excepted | Forces synchronization of scoped command menus with Telegram. |

---

## ⚡ Asynchronous Spam, Service & Media Interceptors

- **Auto-Delete Join & Group Left Notifications:** Automatically wipes annoying member join (`new_chat_members`) and leave (`left_chat_member`) notification service messages immediately upon arrival. Fully configurable via interactive settings (`🚷 Delete Join/Left: ON/OFF`) directly inside groups or remotely from the bot's private DM hub. Strictly restricted so only the **Chat Owner**, **Anonymous Admins**, or **Excepted Admins** can toggle or configure it.
- **Sliding-Window Anti-Flood Middleware:** High-speed router middleware tracking frequencies (`flood_window: 3s`, `flood_limit: 5`). Violators are automatically muted and spam messages are purged instantly.
- **Media Type Filtering:** Instant suppression of `sticker`, `gif` (animation), `document`, `audio`, `voice`, `photo`, and `video`.
- **Link Interceptor:** Real-time URL and invite link blocker with optional strict admin link deletion.

---

## 🗄️ Enterprise MongoDB Architecture

The database layer is engineered for durability, zero latency, and seamless future feature expansion:

```
+------------------------------------------------------------------------------------------+
|                 HYBRID IN-MEMORY CACHE & MONGODB ARCHITECTURE                             |
+------------------------------------------------------------------------------------------+

      TELEGRAM EVENT (Mute / Warn / Settings Toggle)
                           │
                           ▼
          [ 1. In-Memory Engine (RAM) ] ──────────► Sub-millisecond Execution (<1ms)
                           │
       (Asynchronous Non-Blocking Write-Behind)
                           │
                           ▼
               [ 2. MongoDB Service ] ────────────► Persistent ReplicaSet Storage
                           ▲
                           │ (On Bot Startup Hydration)
               [ 3. Initial Cache Load ]
```

### Future-Proofing & Extensibility Features
1. **Document Versioning Pattern (`schema_version: int`):** Enables non-blocking, automated on-the-fly schema migrations as new features are added in future releases.
2. **Feature Flags Bag (`feature_flags: Dict[str, bool]`):** Add progressive rollouts and new feature toggles without schema migrations.
3. **Custom Attributes Bag (`custom_attributes: Dict[str, Any]`):** Schema-less metadata bag pattern for storing arbitrary third-party plugin configurations or webhooks.
4. **Pydantic v2 `extra="allow"` with Default Factories:** Gracefully handles missing fields on deserialization when older database documents are loaded.

### Collections & Indexes

| Collection | Purpose | Key Indexes |
| :--- | :--- | :--- |
| `chat_settings` | Group configuration toggles & limits | `chat_id` (Unique, Ascending) |
| `user_warnings` | Warning counts & historical violation logs | `(chat_id, user_id)` (Compound Unique) |
| `moderation_audit_logs` | Immutable security audit trail | `(chat_id, timestamp DESC)` |
| `reports` | Community report incidents & status | `(chat_id, status)`, `report_id` (Unique) |

---

## 📁 Project Structure

```text
MANAGER/
├── database/
│   ├── __init__.py        # Exported models, connection manager, and service layer
│   ├── connection.py      # Async connection pooling & automatic index creation
│   ├── models.py          # Pydantic v2 schemas with migration engine
│   └── service.py         # Asynchronous Data Access Layer (DAO) / Write-Behind service
├── bot.py                 # Core high-speed bot engine & handlers
├── DOCUMENTATION.md       # Comprehensive architectural & operational manual
├── README.md              # Project documentation
├── requirements.txt       # Environment dependencies
├── .env.example           # Environment template
└── .gitignore             # Git ignore rules
```

---

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/DKT882/MANAGER.git
cd MANAGER
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
Create a `.env` file or export environment variables:
```bash
# Telegram Bot Token from @BotFather
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ

# MongoDB Connection (Optional - falls back to local in-memory if empty)
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=telegram_admin_bot
```

- **Windows PowerShell:**
  ```powershell
  $env:BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
  $env:MONGO_URI="mongodb://localhost:27017"
  ```
- **Linux / macOS:**
  ```bash
  export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
  export MONGO_URI="mongodb://localhost:27017"
  ```

### 4. Verify Syntax & Loop Engine
```bash
python bot.py --check-syntax
# Output: [CHECK] Syntax valid. Event loop engine available: winloop (or uvloop)
```

### 5. Launch the Bot
```bash
python bot.py
```
