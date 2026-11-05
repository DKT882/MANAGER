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


if __name__ == "__main__":
    unittest.main()
