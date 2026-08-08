"""JSON 출력은 reset 시각이 없는 완전 소진/사용 가능 창도 보존해야 한다."""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import coach


def main():
    usage = {
        "primary": {"windowMinutes": 300, "usedPercent": 0, "resetsAt": None},
        "secondary": None,
        "tertiary": None,
    }
    emoji, action, detail = coach.classify("claude", usage)
    results = [{
        "label": "claude",
        "ok": True,
        "plan": None,
        "windows": coach.windows_summary(usage),
        "emoji": emoji,
        "action": action,
        "detail": detail,
    }]
    payload = coach.to_payload(results)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert payload["providers"]["claude"]["windows"]["5h"]["reset_min"] is None
    assert "reset_min" in encoded
    print("PASS: null reset window serializes without crashing")


if __name__ == "__main__":
    main()
