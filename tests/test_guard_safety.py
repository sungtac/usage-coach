"""요금가드가 활성화됐을 때 데이터 부재를 통과로 오판하지 않는지 검증."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import coach


class GuardSafetyTests(unittest.TestCase):
    def test_usage_failure_is_a_stop_reason_in_strict_mode(self):
        with patch.object(coach, "load_usage", side_effect=RuntimeError("missing codexbar")):
            reason = coach.guard_check(
                [("codex", "command", ["codexbar"])],
                coach.load_guard_config(path="/does/not/exist"),
                strict=True,
            )
        self.assertIn("판정 불가", reason)
        self.assertIn("codex", reason)

    def test_usage_failure_fails_open_by_default(self):
        # 소비자 계약(Claude Stop 훅 / Codex goal 워처): 조회 실패 = 정지 안 함
        for label in ("claude", "codex"):
            with self.subTest(label=label), \
                    patch.object(coach, "load_usage", side_effect=RuntimeError("missing codexbar")), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                reason = coach.guard_check([(label, "live", label)],
                                           coach.load_guard_config(path="/does/not/exist"))
            self.assertIsNone(reason)
            self.assertIn(label, err.getvalue())

    def test_missing_weekly_window_fails_open_by_default(self):
        usage = {"primary": {"usedPercent": 10, "windowMinutes": 300,
                             "resetsAt": "2999-01-01T00:00:00Z"}}
        with patch.object(coach, "load_usage", return_value=usage), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(coach.guard_check([("codex", "live", "codex")],
                                                coach.load_guard_config(path="/x")))
            self.assertIn("판정 불가", coach.guard_check([("codex", "live", "codex")],
                                                       coach.load_guard_config(path="/x"),
                                                       strict=True))

    def test_failed_provider_does_not_hide_real_trigger(self):
        tight = {"secondary": {"usedPercent": 99, "windowMinutes": 10080,
                               "resetsAt": "2999-01-01T00:00:00Z"}}

        def fake(kind, arg):
            if arg == "antigravity":
                raise RuntimeError("down")
            return tight
        with patch.object(coach, "load_usage", side_effect=fake), \
                contextlib.redirect_stderr(io.StringIO()):
            reason = coach.guard_check([("antigravity", "live", "antigravity"),
                                        ("codex", "live", "codex")],
                                       coach.load_guard_config(path="/x"))
        self.assertIn("codex", reason)
        self.assertNotIn("판정 불가", reason)

    def test_load_guard_strict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "guard.json")
            for raw, want in (('{"strict": true}', True), ('{"strict": "yes"}', False),
                              ('{}', False), ('[]', False), ('{', False)):
                with open(path, "w") as f:
                    f.write(raw)
                self.assertIs(coach.load_guard_strict(path), want, raw)
        self.assertFalse(coach.load_guard_strict("/does/not/exist"))
        # 최상위 strict 키가 provider 설정 로딩을 깨지 않는다
        self.assertEqual(set(coach.load_guard_config(path="/x")), set(coach.GUARD_TARGETS))

    def test_guard_check_cli_unexpected_error_fails_open(self):
        with patch.object(coach, "guard_enabled", return_value=True), \
                patch.object(coach, "load_guard_strict", return_value=False), \
                patch.object(coach, "guard_check", side_effect=KeyError("boom")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = coach.run_guard_check([])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "")

    def test_hook_tolerates_non_object_event(self):
        for raw in ("[]", '"x"', "5", "null"):
            with self.subTest(raw=raw), \
                    patch.object(coach, "guard_enabled", return_value=True), \
                    patch.object(coach.sys, "stdin", io.StringIO(raw)), \
                    patch.object(coach, "guard_check", side_effect=AssertionError("must not run")):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    coach.run_hook([])
                self.assertEqual(out.getvalue(), "")

    def test_hook_stops_with_continue_false_on_trigger(self):
        with patch.object(coach, "guard_enabled", return_value=True), \
                patch.object(coach.sys, "stdin", io.StringIO('{"stop_hook_active": true}')), \
                patch.object(coach, "load_guard_strict", return_value=False), \
                patch.object(coach, "guard_check", return_value="요금가드: x"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                coach.run_hook([])
        self.assertEqual(json.loads(out.getvalue()), {"continue": False, "stopReason": "요금가드: x"})

    def test_guard_check_returns_nonzero_for_stop_reason(self):
        with patch.object(coach, "guard_enabled", return_value=True), \
                patch.object(coach, "guard_check", return_value="요금가드 판정 불가"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = coach.run_guard_check([])
        self.assertNotEqual(code, 0)
        self.assertIn("요금가드 판정 불가", output.getvalue())


if __name__ == "__main__":
    unittest.main()
