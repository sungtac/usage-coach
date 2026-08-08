"""요금가드가 활성화됐을 때 데이터 부재를 통과로 오판하지 않는지 검증."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import coach


class GuardSafetyTests(unittest.TestCase):
    def test_usage_failure_is_a_stop_reason(self):
        with patch.object(coach, "load_usage", side_effect=RuntimeError("missing codexbar")):
            reason = coach.guard_check(
                [("codex", "command", ["codexbar"])],
                coach.load_guard_config(path="/does/not/exist"),
            )
        self.assertIn("판정 불가", reason)
        self.assertIn("codex", reason)

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
