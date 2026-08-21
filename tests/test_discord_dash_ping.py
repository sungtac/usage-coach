"""ping_if_worse() 네트워크 실패 격리 회귀 테스트.

이전엔 provider별 루프 안의 _request() POST가 try/except 없이 불렸다. 실패(예:
DNS 오류)가 나면 함수 전체가 예외를 던지며 죽어 main()이 last_levels를 저장하지
못했고, 다음 크론 주기에 같은 악화 전이를 또 감지해 디스코드에 중복 알림을
보냈다(2026-08-21). 이제 개별 POST 실패는 격리되어 now가 항상 반환돼야 한다.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import discord_dash


def _payload(claude_level, codex_level):
    return {"providers": {
        "claude": {"ok": True, "level": claude_level, "action": "a"},
        "codex":  {"ok": True, "level": codex_level, "action": "a"},
    }}


def test_ping_failure_on_one_provider_does_not_lose_the_other(monkeypatch):
    calls = []

    def fake_request(webhook, method, body):
        calls.append(body["content"])
        if "Claude" in body["content"]:
            raise OSError("Temporary failure in name resolution")

    monkeypatch.setattr(discord_dash, "_request", fake_request)

    state = {"last_levels": {"claude": "green", "codex": "green"}}
    payload = _payload("yellow", "yellow")

    now = discord_dash.ping_if_worse("http://example.invalid/webhook", payload, state)

    assert now == {"claude": "yellow", "codex": "yellow"}
    assert len(calls) == 2


def test_ping_failure_does_not_raise(monkeypatch):
    def always_fail(webhook, method, body):
        raise OSError("boom")

    monkeypatch.setattr(discord_dash, "_request", always_fail)

    state = {"last_levels": {"claude": "green"}}
    payload = _payload("red", "green")

    now = discord_dash.ping_if_worse("http://example.invalid/webhook", payload, state)

    assert now["claude"] == "red"
