from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import coach  # noqa: E402


def _write_usage(path: Path, used_percent: int) -> None:
    resets = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z")
    usage = {"primary": {"windowMinutes": 10080, "usedPercent": used_percent, "resetsAt": resets}}
    path.write_text(json.dumps([{"usage": usage}]), encoding="utf-8")


class GuardStrictTests(unittest.TestCase):
    def test_query_failure_is_fail_open_by_default(self) -> None:
        sources = [("claude", "file", "/no/such/usage.json")]
        self.assertIsNone(coach.guard_check(sources, coach.load_guard_config(), strict=False))

    def test_query_failure_stops_in_strict_mode(self) -> None:
        sources = [("claude", "file", "/no/such/usage.json")]
        reason = coach.guard_check(sources, coach.load_guard_config(), strict=True)
        self.assertIsNotNone(reason)
        self.assertIn("claude", reason)
        self.assertIn("조회 실패", reason)

    def test_strict_does_not_stop_when_usage_is_under_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            usage_file = Path(temporary_directory) / "usage.json"
            _write_usage(usage_file, used_percent=10)  # plenty of weekly quota left
            sources = [("claude", "file", str(usage_file))]
            self.assertIsNone(coach.guard_check(sources, coach.load_guard_config(), strict=True))

    def test_guard_strict_reads_environment_flag(self) -> None:
        saved = os.environ.get("COACH_GUARD_STRICT")
        saved_path = coach.GUARD_STRICT_PATH
        # Isolate from any real flag file so only the env var decides here.
        coach.GUARD_STRICT_PATH = os.path.join(tempfile.gettempdir(), "usage-coach-no-such-strict-flag")
        try:
            for value, expected in (("1", True), ("true", True), ("on", True), ("0", False), ("", False)):
                if value == "":
                    os.environ.pop("COACH_GUARD_STRICT", None)
                else:
                    os.environ["COACH_GUARD_STRICT"] = value
                self.assertEqual(expected, coach.guard_strict())
        finally:
            coach.GUARD_STRICT_PATH = saved_path
            if saved is None:
                os.environ.pop("COACH_GUARD_STRICT", None)
            else:
                os.environ["COACH_GUARD_STRICT"] = saved


if __name__ == "__main__":
    unittest.main()
