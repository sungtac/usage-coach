import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import coach
import telegram_dash


class TelegramDashTests(unittest.TestCase):
    def _claude_config_email(self, contents):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as stream:
            if contents is not None:
                stream.write(contents)
                stream.flush()
            expanduser = lambda path: stream.name if path == "~/.claude.json" else path
            with patch.object(coach.os.path, "expanduser", side_effect=expanduser):
                return coach._claude_cli_account_email()

    def test_claude_cli_account_email_reads_oauth_account(self):
        email = self._claude_config_email(json.dumps({
            "oauthAccount": {"emailAddress": "edgeai3613@gmail.com", "accountUuid": "secret"}
        }))
        self.assertEqual(email, "edgeai3613@gmail.com")

    def test_claude_cli_account_email_returns_none_for_missing_file(self):
        with patch.object(coach.os.path, "expanduser", return_value="/does/not/exist"):
            self.assertIsNone(coach._claude_cli_account_email())

    def test_claude_cli_account_email_returns_none_for_invalid_json(self):
        self.assertIsNone(self._claude_config_email("{"))

    def test_claude_cli_account_email_returns_none_for_missing_keys(self):
        for contents in ({}, {"oauthAccount": {}}, {"oauthAccount": {"emailAddress": ""}}):
            with self.subTest(contents=contents):
                self.assertIsNone(self._claude_config_email(json.dumps(contents)))

    def test_gather_one_prefers_codexbar_account_email(self):
        usage = {"accountEmail": "codexbar@example.com"}
        with patch.object(coach, "load_usage", return_value=usage), \
             patch.object(coach, "classify", return_value=("🟢", "ok", "fine")), \
             patch.object(coach, "windows_summary", return_value=[]), \
             patch.object(coach, "fable_window", return_value=None), \
             patch.object(coach, "_claude_cli_account_email", return_value="cli@example.com"):
            result = coach.gather_one(("claude", "live", "claude"))
        self.assertEqual(result["email"], "codexbar@example.com")

    def test_gather_one_fills_missing_claude_email_from_cli_config(self):
        with patch.object(coach, "load_usage", return_value={}), \
             patch.object(coach, "classify", return_value=("🟢", "ok", "fine")), \
             patch.object(coach, "windows_summary", return_value=[]), \
             patch.object(coach, "fable_window", return_value=None), \
             patch.object(coach, "_claude_cli_account_email", return_value="cli@example.com"):
            result = coach.gather_one(("claude", "live", "claude"))
        self.assertEqual(result["email"], "cli@example.com")

    def test_coach_args_are_built_by_shared_helper(self):
        args = SimpleNamespace(mock=None, file=[], account=[], providers=None)
        extra, multi = telegram_dash.build_coach_extra_args(
            args, {"coach_args": ["--account", "codex:one@example.com"]})
        self.assertEqual(extra, ["--account", "codex:one@example.com",
                                 "--providers", "claude,codex"])
        self.assertEqual(multi, ["antigravity"])

    def test_coach_args_passthrough_and_multi_disabled_for_mock(self):
        args = SimpleNamespace(mock="all", file=["x:claude"], account=["claude:one"],
                               providers="claude,antigravity")
        extra, multi = telegram_dash.build_coach_extra_args(args, {"all_accounts": ["antigravity"]})
        self.assertEqual(extra, ["--mock", "all", "--file", "x:claude",
                                 "--account", "claude:one", "--providers", "claude,antigravity"])
        self.assertEqual(multi, [])

    def payload(self):
        return {"providers": {"claude": {"ok": True, "level": "yellow",
                "action": "작업 <작게> & 안전", "reason": "a < b & c > d",
                "email": "a&b@example.com", "windows": {"5h": {"left_pct": 10, "reset_min": 67}}}}}

    def test_card_escapes_html_and_formats_reset(self):
        card = telegram_dash.build_card(self.payload(), datetime(2026, 1, 2, 3, 4))
        self.assertIn("작업 &lt;작게&gt; &amp; 안전", card)
        self.assertIn("a&amp;b@example.com", card)
        self.assertIn("a &lt; b &amp; c &gt; d", card)
        self.assertIn("리셋 1시간 7분 후", card)
        self.assertIn("갱신 03:04", card)

    def test_card_is_limited_safely(self):
        payload = {"providers": {"claude": {"ok": True, "level": "white", "action": "x" * 100,
                 "reason": "y" * 10000, "windows": {}}}}
        card = telegram_dash.build_card(payload)
        self.assertLessEqual(len(card), 4096)
        self.assertNotIn("<b>", card)

    def test_multi_account_keeps_provider_reason(self):
        payload = {"providers": {"antigravity": {
            "ok": True, "level": "green", "action": "큰 작업 OK",
            "reason": "계정별 여유량을 확인하세요", "multi": [
                {"email": "z@example.com", "windows": {"gemini": {"left_pct": 80}}},
                {"email": "a@example.com", "windows": {"gemini": {"left_pct": 60}}},
            ],
        }}}
        card = telegram_dash.build_card(payload)
        self.assertIn("계정별 여유량을 확인하세요", card)
        self.assertLess(card.index("a"), card.index("z"))

    def test_edit_failure_falls_back_to_send(self):
        with patch.object(telegram_dash, "edit_message", side_effect=telegram_dash.TelegramError("not found", 400)), \
             patch.object(telegram_dash, "send_message", return_value={"message_id": 22}) as send:
            result = telegram_dash.upsert_card("t", "c", "x", {"message_id": 11})
        self.assertEqual(result, 22)
        send.assert_called_once()

    def test_not_modified_is_success(self):
        with patch.object(telegram_dash, "edit_message", side_effect=telegram_dash.TelegramError("Bad Request: message is not modified", 400)), \
             patch.object(telegram_dash, "send_message") as send:
            result = telegram_dash.upsert_card("t", "c", "x", {"message_id": 11})
        self.assertEqual(result, 11)
        send.assert_not_called()

    def test_unrelated_edit_failure_is_not_hidden(self):
        with patch.object(telegram_dash, "edit_message", side_effect=telegram_dash.TelegramError("server error", 500)), \
             patch.object(telegram_dash, "send_message") as send:
            with self.assertRaises(telegram_dash.TelegramError):
                telegram_dash.upsert_card("t", "c", "x", {"message_id": 11})
        send.assert_not_called()

    def test_ping_only_on_worsening_yellow_or_red(self):
        payload = {"providers": {
            "claude": {"ok": True, "level": "yellow", "action": "작은 작업"},
            "codex": {"ok": True, "level": "red", "action": "대기"},
            "antigravity": {"ok": True, "level": "green", "action": "큰 작업 OK"},
        }}
        state = {"last_levels": {"claude": "white", "codex": "red", "antigravity": "yellow"}}
        with patch.object(telegram_dash, "send_message") as send:
            levels = telegram_dash.ping_if_worse("t", "c", payload, state)
        self.assertEqual(levels, {"claude": "yellow", "codex": "red", "antigravity": "green"})
        send.assert_called_once()
        self.assertIn("claude", send.call_args.args[2].lower())

    def test_send_message_uses_html_api_request(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 7}}'

        with patch.object(telegram_dash.urllib.request, "urlopen", return_value=Response()) as urlopen:
            result = telegram_dash.send_message("bot/token", "-100", "<b>x</b>")
        self.assertEqual(result["message_id"], 7)
        request = urlopen.call_args.args[0]
        self.assertIn("/sendMessage", request.full_url)
        self.assertIn("parse_mode=HTML", request.data.decode())

    def test_missing_token_returns_exit_code_2(self):
        with patch.object(sys, "argv", ["telegram_dash.py", "--mock", "all"]), \
             patch.object(telegram_dash, "load_config", return_value={}), \
             patch.object(telegram_dash, "DEFAULT_TOKEN_FILE", "/tmp/usage-coach-token-does-not-exist"), \
             patch.object(telegram_dash, "load_state", return_value={}), \
             patch.object(telegram_dash, "fetch_payload", return_value={"providers": {}}):
            self.assertEqual(telegram_dash.main(), 2)

    def test_mock_out_does_not_need_token_or_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, "argv", ["telegram_dash.py", "--mock", "all", "--out", os.path.join(directory, "x.txt")]), \
             patch.object(telegram_dash.urllib.request, "urlopen", side_effect=AssertionError("network")):
            self.assertEqual(telegram_dash.main(), 0)
            with open(os.path.join(directory, "x.txt"), encoding="utf-8") as stream:
                self.assertIn("<i>갱신", stream.read())

    def test_token_precedence(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env-token"}, clear=False):
            self.assertEqual(telegram_dash._load_token(None, {"bot_token": "config-token"}), "env-token")
        self.assertEqual(telegram_dash._load_token("cli-token", {}), "cli-token")


if __name__ == "__main__":
    unittest.main()
