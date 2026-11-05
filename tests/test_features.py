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


if __name__ == "__main__":
    unittest.main()
