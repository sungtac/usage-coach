"""ping_if_worse() 회귀 테스트: 네트워크 실패 격리 + 핑 메시지 누적 방지.

배경 1(2026-08-13): provider별 루프 안의 _request() POST가 try/except 없이 불렸다.
실패(예: DNS 오류)가 나면 함수 전체가 예외를 던지며 죽어 main()이 last_levels를
저장하지 못했고, 다음 크론 주기에 같은 악화 전이를 또 감지해 디스코드에 중복
알림을 보냈다. 이제 POST 실패는 격리되어 now가 항상 반환돼야 한다.

배경 2(2026-08-21): 카드(upsert_card)는 편집이라 안 쌓이지만, 핑은 악화될 때마다
새 메시지를 POST만 해서 채널에 계속 쌓였다(사용자 지적). 이제 여러 provider가
동시에 악화되면 한 메시지로 묶어 보내고, 다음 악화 시엔 이전 핑을 지우고 새로
게시해 항상 최신 경고 하나만 남는다.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import discord_dash


def _payload(claude_level, codex_level):
    return {"providers": {
        "claude": {"ok": True, "level": claude_level, "action": "a"},
        "codex":  {"ok": True, "level": codex_level, "action": "a"},
    }}


def test_ping_batches_simultaneous_worsening_into_one_message(monkeypatch):
    calls = []

    def fake_request(url, method, body):
        calls.append((url, method, body))
        return {"id": "new-ping-1"}

    monkeypatch.setattr(discord_dash, "_request", fake_request)

    state = {"last_levels": {"claude": "green", "codex": "green"}}
    payload = _payload("yellow", "yellow")

    now = discord_dash.ping_if_worse("http://example.invalid/webhook", payload, state)

    assert now == {"claude": "yellow", "codex": "yellow"}
    assert len(calls) == 1
    _url, method, body = calls[0]
    assert method == "POST"
    assert "Claude" in body["content"] and "Codex" in body["content"]
    assert state["last_ping_id"] == "new-ping-1"


def test_ping_deletes_previous_ping_before_posting_new_one(monkeypatch):
    calls = []

    def fake_request(url, method, body):
        calls.append((url, method))
        if method == "POST":
            return {"id": "ping-2"}
        return {}

    monkeypatch.setattr(discord_dash, "_request", fake_request)

    state = {"last_levels": {"claude": "green"}, "last_ping_id": "ping-1"}
    payload = _payload("yellow", "green")

    discord_dash.ping_if_worse("http://example.invalid/webhook", payload, state)

    assert calls[0] == ("http://example.invalid/webhook/messages/ping-1", "DELETE")
    assert calls[1][1] == "POST"
    assert state["last_ping_id"] == "ping-2"


def test_ping_delete_failure_does_not_block_new_post(monkeypatch):
    def fake_request(url, method, body=None):
        if method == "DELETE":
            raise OSError("message already gone")
        return {"id": "ping-new"}

    monkeypatch.setattr(discord_dash, "_request", fake_request)

    state = {"last_levels": {"claude": "green"}, "last_ping_id": "stale-id"}
    payload = _payload("red", "green")

    now = discord_dash.ping_if_worse("http://example.invalid/webhook", payload, state)

    assert now["claude"] == "red"
    assert state["last_ping_id"] == "ping-new"


def test_no_worsening_means_no_network_call(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("worsening 없으면 _request가 호출되면 안 됨")

    monkeypatch.setattr(discord_dash, "_request", fail_if_called)

    state = {"last_levels": {"claude": "green", "codex": "green"}, "last_ping_id": "ping-1"}
    payload = _payload("green", "green")

    now = discord_dash.ping_if_worse("http://example.invalid/webhook", payload, state)

    assert now == {"claude": "green", "codex": "green"}
    assert state["last_ping_id"] == "ping-1"   # 안 건드림


def test_ping_failure_does_not_raise(monkeypatch):
    def always_fail(url, method, body=None):
        raise OSError("boom")

    monkeypatch.setattr(discord_dash, "_request", always_fail)

    state = {"last_levels": {"claude": "green"}}
    payload = _payload("red", "green")

    now = discord_dash.ping_if_worse("http://example.invalid/webhook", payload, state)

    assert now["claude"] == "red"
