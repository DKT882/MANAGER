import unittest

from database.models import ChatSettingsModel, AcceptedMemberModel
import bot


class TestAcceptedMembersAndPMWelcome(unittest.TestCase):
    def test_chat_settings_model_pm_welcome(self):
        settings = ChatSettingsModel(
            chat_id=-100123456789,
            welcome_pm_enabled=True,
            welcome_pm_msg="Custom PM: Hello {name} for {chat_title}"
        )
        self.assertTrue(settings.welcome_pm_enabled)
        self.assertIn("Custom PM", settings.welcome_pm_msg)

        in_mem = settings.to_in_memory_dict()
        self.assertTrue(in_mem["welcome_pm_enabled"])
        self.assertEqual(in_mem["welcome_pm_msg"], "Custom PM: Hello {name} for {chat_title}")

        restored = ChatSettingsModel.from_in_memory_dict(-100123456789, "Test Group", in_mem)
        self.assertTrue(restored.welcome_pm_enabled)
        self.assertEqual(restored.welcome_pm_msg, in_mem["welcome_pm_msg"])

    def test_accepted_member_model(self):
        member = AcceptedMemberModel(
            user_id=12345678,
            first_name="Alice",
            username="alice_tg",
            full_name="Alice Wonder",
            chat_ids=[-100111, -100222],
            chat_titles=["Alpha Group", "Beta Group"],
            accept_count=2,
        )
        self.assertEqual(member.user_id, 12345678)
        self.assertEqual(len(member.chat_ids), 2)
        self.assertEqual(member.status, "active")

    def test_default_chat_config(self):
        self.assertIn("welcome_pm_enabled", bot.DEFAULT_CHAT_CONFIG)
        self.assertFalse(bot.DEFAULT_CHAT_CONFIG["welcome_pm_enabled"])
        self.assertIn("welcome_pm_msg", bot.DEFAULT_CHAT_CONFIG)

    def test_welcome_menu_formatting(self):
        s = bot.DEFAULT_CHAT_CONFIG.copy()
        s["welcome_pm_enabled"] = True
        s["welcome_pm_msg"] = "Welcome PM Test {name}"
        text = bot.format_welcome_text("My Group", s)
        self.assertIn("Join Request Private DM", text)
        self.assertIn("Welcome PM Test", text)

        kb = bot.generate_welcome_keyboard(-100123456, is_dm=True)
        btn_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertTrue(any("toggle:welcome_pm_enabled" in d for d in btn_data))
        self.assertTrue(any("cust:welcome_pm" in d for d in btn_data))

    def test_approval_menu_formatting(self):
        s = bot.DEFAULT_CHAT_CONFIG.copy()
        text = bot.format_approval_text("My Group", s)
        self.assertIn("Join Request Approval Mode", text)
        self.assertIn("Private DM Welcome", text)

        kb = bot.generate_approval_keyboard(-100123456, is_dm=False)
        btn_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertTrue(any("toggle:approval_auto" in d for d in btn_data))
        self.assertTrue(any("toggle:welcome_pm_enabled" in d for d in btn_data))
        self.assertTrue(any("cust:welcome_pm" in d for d in btn_data))

    def test_members_menu_formatting(self):
        bot.ACCEPTED_MEMBERS_CACHE.clear()
        bot.ACCEPTED_MEMBERS_CACHE[999001] = {
            "user_id": 999001,
            "full_name": "Test User",
            "chat_ids": [-100555],
            "chat_titles": ["Test Chat"],
        }
        s = bot.DEFAULT_CHAT_CONFIG.copy()
        text = bot.format_members_text("Test Chat", s, chat_id=-100555)
        self.assertIn("Accepted Members (This Chat)", text)
        self.assertIn("1", text)

        kb = bot.generate_members_keyboard(-100555, is_dm=True)
        btn_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertTrue(any("bcast_chat" in d for d in btn_data))
        self.assertTrue(any("bcast_all" in d for d in btn_data))

    def test_render_dashboard_html(self):
        html = bot.render_members_dashboard_html()
        self.assertIn("Manager Bot Console", html)
        self.assertIn("Global Unified Accepted Members Registry", html)
        self.assertIn("/api/members", html)
        self.assertIn("/api/broadcast", html)
        self.assertIn("Send Broadcast", html)

    def test_cors_headers_defined(self):
        self.assertIn("Access-Control-Allow-Origin", bot.CORS_HEADERS)
        self.assertEqual(bot.CORS_HEADERS["Access-Control-Allow-Origin"], "*")

    def test_warn_and_duplicate_settings_model(self):
        settings = ChatSettingsModel(
            chat_id=-100999888,
            warnings={
                "auto_warn_enabled": False,
                "warn_on_duplicate": True,
                "duplicate_limit": 4,
                "duplicate_window": 45,
                "warn_on_flood": True,
                "warn_limit": 5,
            }
        )
        self.assertFalse(settings.warnings.auto_warn_enabled)
        self.assertTrue(settings.warnings.warn_on_duplicate)
        self.assertEqual(settings.warnings.duplicate_limit, 4)
        self.assertEqual(settings.warnings.duplicate_window, 45)
        self.assertTrue(settings.warnings.warn_on_flood)

        in_mem = settings.to_in_memory_dict()
        self.assertFalse(in_mem["auto_warn_enabled"])
        self.assertTrue(in_mem["warn_on_duplicate"])
        self.assertEqual(in_mem["duplicate_limit"], 4)
        self.assertEqual(in_mem["duplicate_window"], 45)
        self.assertTrue(in_mem["warn_on_flood"])

        restored = ChatSettingsModel.from_in_memory_dict(-100999888, "Warn Test Group", in_mem)
        self.assertFalse(restored.warnings.auto_warn_enabled)
        self.assertTrue(restored.warnings.warn_on_duplicate)
        self.assertEqual(restored.warnings.duplicate_limit, 4)
        self.assertEqual(restored.warnings.duplicate_window, 45)
        self.assertTrue(restored.warnings.warn_on_flood)

    def test_warn_menu_formatting_and_keyboard(self):
        s = bot.DEFAULT_CHAT_CONFIG.copy()
        s["auto_warn_enabled"] = True
        s["warn_on_duplicate"] = True
        s["duplicate_limit"] = 3
        s["duplicate_window"] = 30
        s["warn_on_flood"] = True

        text = bot.format_warn_text("Test Warn Chat", s)
        self.assertIn("Master Auto-Warn", text)
        self.assertIn("Warn on Duplicates", text)
        self.assertIn("<code>3x</code> in <code>30s</code>", text)
        self.assertIn("Warn on Message Flood", text)

        kb = bot.generate_warn_keyboard(-100999888, is_dm=False)
        btn_data = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        self.assertTrue(any("warn_toggle_auto" in d for d in btn_data))
        self.assertTrue(any("warn_toggle_dup" in d for d in btn_data))
        self.assertTrue(any("warn_dup_limit_cycle" in d for d in btn_data))
        self.assertTrue(any("warn_dup_win_cycle" in d for d in btn_data))
        self.assertTrue(any("warn_toggle_flood" in d for d in btn_data))

    def test_duplicate_cache_and_config(self):
        self.assertIn("auto_warn_enabled", bot.DEFAULT_CHAT_CONFIG)
        self.assertTrue(bot.DEFAULT_CHAT_CONFIG["auto_warn_enabled"])
        self.assertIn("warn_on_duplicate", bot.DEFAULT_CHAT_CONFIG)
        self.assertTrue(bot.DEFAULT_CHAT_CONFIG["warn_on_duplicate"])
        self.assertIn("duplicate_limit", bot.DEFAULT_CHAT_CONFIG)
        self.assertIn("duplicate_window", bot.DEFAULT_CHAT_CONFIG)
        self.assertIn("warn_on_flood", bot.DEFAULT_CHAT_CONFIG)
        self.assertIsInstance(bot.DUPLICATE_CACHE, dict)

    def test_antispam_toggle_and_model(self):
        self.assertIn("antispam_enabled", bot.DEFAULT_CHAT_CONFIG)
        self.assertTrue(bot.DEFAULT_CHAT_CONFIG["antispam_enabled"])

        settings = ChatSettingsModel(
            chat_id=-100777666,
            antispam_enabled=False
        )
        self.assertFalse(settings.antispam_enabled)
        in_mem = settings.to_in_memory_dict()
        self.assertFalse(in_mem["antispam_enabled"])
        restored = ChatSettingsModel.from_in_memory_dict(-100777666, "Antispam Test", in_mem)
        self.assertFalse(restored.antispam_enabled)

        s = bot.DEFAULT_CHAT_CONFIG.copy()
        s["antispam_enabled"] = False
        text = bot.format_antispam_text("Test Chat", s)
        self.assertIn("DISABLED", text)

        kb = bot.generate_antispam_keyboard(-100777666, is_dm=False)
        btn_data = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        self.assertTrue(any("toggle:antispam_enabled" in d for d in btn_data))

    def test_dm_group_switcher_button_replaces_language(self):
        self.assertIsInstance(bot.LAST_DM_SETTINGS_MSG, dict)
        self.assertNotIn("lang", bot.DEFAULT_CHAT_CONFIG)

        # Page 1 checks
        kb_page1_dm = bot.generate_settings_page1_keyboard(-100777, is_dm=True)
        btn_data_p1 = [btn.callback_data for row in kb_page1_dm.inline_keyboard for btn in row if btn.callback_data]
        self.assertIn("dm:switch_group", btn_data_p1)
        self.assertFalse(any("lang" in d for d in btn_data_p1))

        # Page 2 checks
        kb_page2_dm = bot.generate_settings_page2_keyboard(-100777, is_dm=True)
        btn_data_p2 = [btn.callback_data for row in kb_page2_dm.inline_keyboard for btn in row if btn.callback_data]
        self.assertIn("dm:switch_group", btn_data_p2)
        self.assertFalse(any("lang" in d for d in btn_data_p2))

        # In group chat, switch_group is also in the exact language position
        kb_page1_gc = bot.generate_settings_page1_keyboard(-100777, is_dm=False)
        btn_data_gc = [btn.callback_data for row in kb_page1_gc.inline_keyboard for btn in row if btn.callback_data]
        self.assertIn("dm:switch_group", btn_data_gc)
        self.assertFalse(any("lang" in d for d in btn_data_gc))

    def test_dispatch_private_welcome_dm(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()

        mock_user = MagicMock()
        mock_user.id = 5018082627
        mock_user.full_name = "DKT Secondary"
        mock_user.first_name = "DKT"
        mock_user.username = "dkt_test"
        mock_user.mention_html.return_value = "<a href='tg://user?id=5018082627'>DKT</a>"

        settings = {
            "welcome_pm_enabled": True,
            "welcome_pm_msg": "Hello {name}, welcome to {chat_title}!"
        }

        # Test successful delivery
        res = asyncio.run(bot.dispatch_private_welcome_dm(
            mock_bot, -100999, mock_user, "VIP Group", settings
        ))
        self.assertTrue(res)
        mock_bot.send_message.assert_called_once()
        self.assertEqual(mock_bot.send_message.call_args[1]["chat_id"], 5018082627)
        self.assertIn("Hello DKT Secondary", mock_bot.send_message.call_args[1]["text"])

        # Test disabled
        settings["welcome_pm_enabled"] = False
        res2 = asyncio.run(bot.dispatch_private_welcome_dm(
            mock_bot, -100999, mock_user, "VIP Group", settings
        ))
        self.assertFalse(res2)

    def test_json_serial_and_members_api(self):
        import json
        from datetime import datetime, timezone, date

        now_dt = datetime.now(timezone.utc)
        today_d = date.today()
        payload = {
            "status": "ok",
            "dt": now_dt,
            "d": today_d
        }
        # Should not raise TypeError: Object of type datetime is not JSON serializable
        json_output = json.dumps(payload, default=bot.json_serial)
        self.assertIn(now_dt.isoformat()[:10], json_output)
        self.assertIn(today_d.isoformat(), json_output)

    def test_html_caching_and_keepalive(self):
        import asyncio
        h1 = bot.render_members_dashboard_html()
        h2 = bot.render_members_dashboard_html()
        self.assertIs(h1, h2)
        self.assertTrue(asyncio.iscoroutinefunction(bot.render_keepalive_worker))

    def test_wipe_trigger_preserves_dm_commands(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from aiogram.enums import ChatType

        # Mock private chat message
        dm_msg = MagicMock()
        dm_msg.chat.type = ChatType.PRIVATE
        dm_msg.delete = AsyncMock()

        asyncio.run(bot.wipe_trigger(dm_msg))
        # delete() MUST NOT be called in private chat
        dm_msg.delete.assert_not_called()

        # Mock group chat message
        group_msg = MagicMock()
        group_msg.chat.type = ChatType.SUPERGROUP
        group_msg.delete = AsyncMock()

        asyncio.run(bot.wipe_trigger(group_msg))
        # delete() MUST be called in group chat
        group_msg.delete.assert_called_once()

    def test_chat_join_request_sends_dm_before_approving(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        mock_bot = MagicMock()
        call_order = []

        async def fake_send_message(*args, **kwargs):
            call_order.append("send_message")
            return MagicMock()

        async def fake_approve(*args, **kwargs):
            call_order.append("approve_chat_join_request")
            return True

        mock_bot.send_message = AsyncMock(side_effect=fake_send_message)
        mock_bot.approve_chat_join_request = AsyncMock(side_effect=fake_approve)

        # Configure chat settings
        chat_id = -100555666
        bot.CHAT_SETTINGS[chat_id] = {
            "approval_auto": True,
            "welcome_pm_enabled": True,
            "welcome_pm_msg": "Welcome {name}!"
        }
        bot._LAST_DM_SENT_TS.clear()

        # Build join request
        mock_user = MagicMock()
        mock_user.id = 8881234
        mock_user.full_name = "New Applicant"
        mock_user.first_name = "New"
        mock_user.username = "new_applicant"
        mock_user.mention_html.return_value = "New"

        req = MagicMock()
        req.chat.id = chat_id
        req.chat.title = "Test Approvals"
        req.from_user = mock_user

        asyncio.run(bot.handle_chat_join_request(req, mock_bot))

        # Critical verification: send_message must be called BEFORE approve_chat_join_request!
        self.assertIn("send_message", call_order)
        self.assertIn("approve_chat_join_request", call_order)
        dm_idx = call_order.index("send_message")
        approve_idx = call_order.index("approve_chat_join_request")
        self.assertLess(dm_idx, approve_idx, "Private DM MUST be dispatched BEFORE approving join request!")

    def test_msglength_model_and_defaults(self):
        self.assertIn("max_message_length", bot.DEFAULT_CHAT_CONFIG)
        self.assertIn("msg_length_action", bot.DEFAULT_CHAT_CONFIG)
        self.assertEqual(bot.DEFAULT_CHAT_CONFIG["msg_length_action"], "delete")

        model = ChatSettingsModel(
            chat_id=-100999,
            max_message_length=1500,
            msg_length_action="warn"
        )
        self.assertEqual(model.max_message_length, 1500)
        self.assertEqual(model.msg_length_action, "warn")

        d = model.to_in_memory_dict()
        self.assertEqual(d["max_message_length"], 1500)
        self.assertEqual(d["msg_length_action"], "warn")

        restored = ChatSettingsModel.from_in_memory_dict(-100999, "Test Chat", d)
        self.assertEqual(restored.max_message_length, 1500)
        self.assertEqual(restored.msg_length_action, "warn")

    def test_msglength_menu_formatting_and_keyboard(self):
        chat_id = -100444555
        bot.CHAT_SETTINGS[chat_id] = {
            "max_message_length": 1000,
            "msg_length_action": "warn"
        }
        text = bot.format_msglength_text("My Test Group", bot.CHAT_SETTINGS[chat_id])
        self.assertIn("Message Length Limit", text)
        self.assertIn("1000 characters", text)
        self.assertIn("WARN", text)

        kb = bot.generate_msglength_keyboard(chat_id, is_dm=True)
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callback_datas = [btn.callback_data for btn in all_buttons]
        button_texts = [btn.text for btn in all_buttons]

        # Preset checking
        self.assertTrue(any("dm:setlen:100:" in d for d in callback_datas))
        self.assertTrue(any("dm:setlen:500:" in d for d in callback_datas))
        self.assertTrue(any("dm:setlen:1000:" in d for d in callback_datas))
        self.assertTrue(any("dm:setlen:4000:" in d for d in callback_datas))
        self.assertTrue(any("🟢 1000" in t for t in button_texts))

        # Action toggle and custom buttons
        self.assertTrue(any("dm:cycle:msg_length_action:" in d for d in callback_datas))
        self.assertTrue(any("dm:cust:msglength:" in d for d in callback_datas))
        self.assertTrue(any("dm:page:2:" in d for d in callback_datas))

    def test_duration_formatting_and_parsing(self):
        self.assertEqual(bot.format_duration(0), "Permanent")
        self.assertEqual(bot.format_duration(0, zero_label="Never"), "Never")
        self.assertEqual(bot.format_duration(900), "15m")
        self.assertEqual(bot.format_duration(86400), "1d")
        self.assertEqual(bot.format_duration(604800), "1w")
        self.assertEqual(bot.format_duration(5184000), "2mo")
        self.assertEqual(bot.format_duration_long(5184000), "2 months")

        self.assertEqual(bot.parse_custom_duration_input("1d"), 86400)
        self.assertEqual(bot.parse_custom_duration_input("1w"), 604800)
        self.assertEqual(bot.parse_custom_duration_input("2mo"), 5184000)
        self.assertEqual(bot.parse_custom_duration_input("2M"), 5184000)
        self.assertEqual(bot.parse_custom_duration_input("15m"), 900)
        self.assertEqual(bot.parse_custom_duration_input("0"), 0)
        self.assertEqual(bot.parse_custom_duration_input("never"), 0)
        self.assertIsNone(bot.parse_custom_duration_input("invalid_dur"))

    def test_warndur_and_expiry_menus_and_model(self):
        # Permanent duration (0) must validate cleanly without Pydantic ge=60 error
        model = ChatSettingsModel.from_in_memory_dict(
            -100777888,
            "Duration Test Group",
            {"warn_duration": 0, "warn_expiry": 604800}
        )
        self.assertEqual(model.warnings.warn_duration, 0)
        self.assertEqual(model.warnings.warn_expiry, 604800)
        mem = model.to_in_memory_dict()
        self.assertEqual(mem["warn_duration"], 0)
        self.assertEqual(mem["warn_expiry"], 604800)

        chat_id = -100777888
        bot.CHAT_SETTINGS[chat_id]["warn_duration"] = 5184000  # 2mo
        bot.CHAT_SETTINGS[chat_id]["warn_expiry"] = 604800    # 1w

        dur_text, dur_kb = bot.render_submenu("warndur", "Duration Test", bot.CHAT_SETTINGS[chat_id], chat_id, is_dm=True)
        self.assertIn("2 months", dur_text)
        dur_cb = [btn.callback_data for row in dur_kb.inline_keyboard for btn in row if btn.callback_data]
        dur_labels = [btn.text for row in dur_kb.inline_keyboard for btn in row]
        self.assertTrue(any("dm:setwarndur:86400:" in d for d in dur_cb))
        self.assertTrue(any("dm:setwarndur:604800:" in d for d in dur_cb))
        self.assertTrue(any("dm:setwarndur:5184000:" in d for d in dur_cb))
        self.assertTrue(any("🟢 2mo" in t for t in dur_labels))
        self.assertTrue(any("dm:cust:warndur:" in d for d in dur_cb))

        exp_text, exp_kb = bot.render_submenu("warnexpiry", "Duration Test", bot.CHAT_SETTINGS[chat_id], chat_id, is_dm=True)
        self.assertIn("1 week", exp_text)
        exp_cb = [btn.callback_data for row in exp_kb.inline_keyboard for btn in row if btn.callback_data]
        exp_labels = [btn.text for row in exp_kb.inline_keyboard for btn in row]
        self.assertTrue(any("dm:setwarnexp:604800:" in d for d in exp_cb))
        self.assertTrue(any("🟢 1w" in t for t in exp_labels))
        self.assertTrue(any("dm:cust:warnexpiry:" in d for d in exp_cb))

    def test_warn_counter_increments_and_db_fallback(self):
        import asyncio
        import time
        from unittest.mock import AsyncMock, MagicMock, patch

        chat_id = -100666777
        user_id = 555444333
        bot.WARN_CACHE.clear()
        bot.WARN_TIMESTAMPS.clear()
        bot.CHAT_SETTINGS[chat_id] = {
            **bot.DEFAULT_CHAT_CONFIG,
            "warn_limit": 3,
            "warn_action": "mute",
            "warn_duration": 86400,
            "warn_expiry": 0,
            "auto_warn_enabled": True,
        }
        bot.CHAT_TITLES[chat_id] = "Warn Sequence Group"

        sent_texts = []
        recorded_counts = []

        mock_bot = MagicMock()
        mock_bot.id = 999000

        async def fake_send_message(chat_id, text, **kwargs):
            sent_texts.append(text)
            return MagicMock()

        mock_bot.send_message = AsyncMock(side_effect=fake_send_message)
        mock_bot.restrict_chat_member = AsyncMock(return_value=True)

        target_user = MagicMock()
        target_user.id = user_id
        target_user.full_name = "Test Member"
        target_user.username = "test_member"

        def fake_record_warn(cid, uid, admin_id, reason, current_count):
            recorded_counts.append(current_count)

        with patch.object(bot.DatabaseService, "get_user_warn_state", new=AsyncMock(return_value=(0, None))), \
             patch.object(bot.DatabaseService, "record_warn_background", side_effect=fake_record_warn), \
             patch.object(bot.DatabaseService, "log_moderation_background"):

            async def run_seq():
                # 1st warn -> 1/3
                await bot.issue_warn_and_notify(mock_bot, chat_id, target_user, 111, "Violation 1")
                # 2nd warn -> 2/3
                await bot.issue_warn_and_notify(mock_bot, chat_id, target_user, 111, "Violation 2")
                # 3rd warn -> ceiling reached (punish & reset)
                await bot.issue_warn_and_notify(mock_bot, chat_id, target_user, 111, "Violation 3")

            asyncio.run(run_seq())

        self.assertEqual(recorded_counts, [1, 2, 0])
        self.assertIn("1/3", sent_texts[0])
        self.assertIn("2/3", sent_texts[1])
        self.assertIn("WARNING CEILING REACHED", sent_texts[2])
        self.assertEqual(bot.WARN_CACHE[chat_id].get(user_id, 0), 0)
        mock_bot.restrict_chat_member.assert_awaited_once()

        # Verify cache-miss restores persisted DB count instead of restarting at 1/3
        bot.WARN_CACHE.clear()
        bot.WARN_TIMESTAMPS.clear()
        sent_texts.clear()
        with patch.object(bot.DatabaseService, "get_user_warn_state", new=AsyncMock(return_value=(1, time.time()))), \
             patch.object(bot.DatabaseService, "record_warn_background", side_effect=fake_record_warn), \
             patch.object(bot.DatabaseService, "log_moderation_background"):
            asyncio.run(bot.issue_warn_and_notify(mock_bot, chat_id, target_user, 111, "After Cache Miss"))

        self.assertIn("2/3", sent_texts[0])
        self.assertEqual(bot.WARN_CACHE[chat_id][user_id], 2)


if __name__ == "__main__":
    unittest.main()
