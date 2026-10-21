"""classify가 win()의 timeLeft를 1.0으로 클램프해, 손상된 먼 미래 resetsAt가
거짓 🔴('큰 작업 미루세요')를 내지 않는지 검증한다.

timeLeft = mins/wm 이므로 resetsAt가 멀수록(그러나 year ≥ 2000이라 win() epoch
가드는 통과) timeLeft가 1을 넘어 부풀고, 쿼터가 넉넉해도 left < timeLeft - M 이
참이 되어 red가 잘못 발동했다. win()에서 timeLeft를 min(1.0, ...)으로 막는다.
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import coach


def _iso(mins):
    return (coach.now_utc() + dt.timedelta(minutes=mins)).isoformat().replace("+00:00", "Z")


CORRUPT_FUTURE = "9999-01-01T00:00:00Z"   # year ≥ 2000 → epoch 가드는 통과, timeLeft만 폭증


class ClassifyClampTests(unittest.TestCase):
    def test_win_clamps_timeleft_to_one(self):
        r = coach.win({"windowMinutes": 10080, "usedPercent": 5, "resetsAt": CORRUPT_FUTURE})
        self.assertLessEqual(r["timeLeft"], 1.0)

    def test_no_false_red_with_corrupt_future_reset_and_plenty_quota(self):
        # 5h 넉넉 + 7d 95% 남음인데 7d resetsAt만 손상 → red가 아니라 green 이어야
        usage = {
            "primary":   {"windowMinutes": 300,   "usedPercent": 30, "resetsAt": _iso(120)},
            "secondary": {"windowMinutes": 10080, "usedPercent": 5,  "resetsAt": CORRUPT_FUTURE},
            "tertiary":  None,
        }
        emoji, _, _ = coach.classify("claude", usage)
        self.assertNotEqual(emoji, "🔴")
        self.assertEqual(emoji, "🟢")

    def test_no_false_red_on_pace_only_provider(self):
        # 소진형 없이 7d만 있는 provider(Antigravity류) — 손상 resetsAt로 거짓 red 금지
        usage = {
            "primary":   {"windowMinutes": 10080, "usedPercent": 5, "resetsAt": CORRUPT_FUTURE},
            "secondary": None, "tertiary": None,
        }
        emoji, _, _ = coach.classify("antigravity", usage)
        self.assertNotEqual(emoji, "🔴")

    def test_genuine_pace_overrun_still_red(self):
        # 정상 resetsAt + 실제로 빠듯한 7d(10% 남음, 리셋 멀음) → red는 그대로 발동
        usage = {
            "primary":   {"windowMinutes": 300,   "usedPercent": 40, "resetsAt": _iso(120)},
            "secondary": {"windowMinutes": 10080, "usedPercent": 90, "resetsAt": _iso(9000)},
            "tertiary":  None,
        }
        emoji, _, _ = coach.classify("claude", usage)
        self.assertEqual(emoji, "🔴")


if __name__ == "__main__":
    unittest.main()
