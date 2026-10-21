"""2026-10-22 전수 리뷰에서 고친 결함들의 회귀 테스트."""
import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import coach
import discord_dash
import telegram_dash


def _iso(minutes, tz=True):
    t = coach.now_utc() + dt.timedelta(minutes=minutes)
    return t.isoformat().replace("+00:00", "Z") if tz else t.replace(tzinfo=None).isoformat()


class WinParsingTests(unittest.TestCase):
    def test_naive_resets_at_is_treated_as_utc(self):
        r = coach.win({"usedPercent": 10, "windowMinutes": 300, "resetsAt": _iso(120, tz=False)})
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r["mins"], 120, delta=1)

    def test_malformed_windows_are_skipped_not_crashing(self):
        for w in (["x"], "x", {"usedPercent": "10", "windowMinutes": 300, "resetsAt": _iso(5)},
                  {"usedPercent": 10, "windowMinutes": "300", "resetsAt": _iso(5)},
                  {"usedPercent": True, "windowMinutes": 300, "resetsAt": _iso(5)},
                  {"usedPercent": 10, "windowMinutes": -300, "resetsAt": _iso(5)}):
            with self.subTest(w=w):
                self.assertIsNone(coach.win(w))
        usage = {"primary": ["bad"], "secondary": {"usedPercent": 10, "windowMinutes": 10080,
                                                    "resetsAt": _iso(5040, tz=False)}}
        emoji, _action, _detail = coach.classify("codex", usage)
        self.assertEqual(emoji, "🟢")


class ProviderListTests(unittest.TestCase):
    def test_coach_providers_tolerate_spaces(self):
        args = SimpleNamespace(mock=None, file=[], providers="claude, codex , antigravity")
        sources = coach.build_sources(args, argparse.ArgumentParser())
        self.assertEqual([s[0] for s in sources], ["claude", "codex", "antigravity"])
        self.assertEqual(sources[2][1], "live-all")

    def test_dashboard_providers_tolerate_spaces(self):
        args = SimpleNamespace(mock=None, file=[], account=[], providers="claude, codex, antigravity")
        extra, multi = discord_dash.build_coach_extra_args(args, {})
        self.assertEqual(extra, ["--providers", "claude,codex"])
        self.assertEqual(multi, ["antigravity"])


class TelegramTruncateTests(unittest.TestCase):
    def test_truncation_never_leaves_a_broken_entity(self):
        for n in range(6):
            payload = {"providers": {"claude": {"ok": True, "level": "white", "action": "x",
                                                "reason": "a" * n + "&" * 5000, "windows": {}}}}
            card = telegram_dash.build_card(payload)
            # 모든 & 는 완결된 엔티티의 시작이어야 한다
            self.assertIsNone(re.search(r"&(?!amp;|lt;|gt;)", card), n)
            self.assertLessEqual(len(html.unescape(card)), telegram_dash.MAX_TEXT)


class InstallEnvOnlyTests(unittest.TestCase):
    def test_env_only_config_does_not_install_broken_agent(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / "Library/LaunchAgents").mkdir(parents=True)
            env = dict(os.environ, HOME=home, DRY_RUN="1",
                       DISCORD_WEBHOOK_URL="https://example.invalid/hook",
                       TELEGRAM_BOT_TOKEN="t")
            r = subprocess.run(["bash", str(ROOT / "scripts/install.sh")],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertEqual(list((Path(home) / "Library/LaunchAgents").iterdir()), [])
            self.assertNotIn("example.invalid", r.stdout + r.stderr)   # 비밀값 미노출


class StatuslineTests(unittest.TestCase):
    def _run(self, home, payload):
        return subprocess.run(["bash", str(ROOT / "scripts/statusline-command.sh")],
                              input=json.dumps(payload), capture_output=True, text=True,
                              env=dict(os.environ, HOME=home))

    def test_non_object_nested_fields_exit_zero(self):
        with tempfile.TemporaryDirectory() as home:
            for payload in ({"workspace": "x"}, {"model": "opus"}, {"cwd": 5},
                            {"context_window": {"used_percentage": "12"}},
                            {"context_window": []}):
                with self.subTest(payload=payload):
                    r = self._run(home, payload)
                    self.assertEqual(r.returncode, 0, r.stderr)

    def test_session_id_cannot_escape_sessions_dir(self):
        with tempfile.TemporaryDirectory() as home:
            for sid in ("../../evil", "..", "a/b", ""):
                self.assertEqual(self._run(home, {"session_id": sid, "cwd": "/x"}).returncode, 0)
            written = [str(p.relative_to(home)) for p in Path(home).rglob("*.json")]
            self.assertEqual(written, [])
            self._run(home, {"session_id": "3f2a-uuid_1.x", "cwd": "/x"})
            self.assertTrue((Path(home) / ".config/usage-coach/sessions/3f2a-uuid_1.x.json").exists())


if __name__ == "__main__":
    unittest.main()
