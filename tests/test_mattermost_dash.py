"""mattermost_dash.py 회귀 테스트.

discord_dash.py의 ping_if_worse/upsert_card 설계를 메타모스트로 이식한 것이라
같은 계약(핑 누적 방지, 카드 업서트 폴백, 캐시 우선 데이터소스)을 검증한다.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mattermost_dash as mm


def _payload(claude_level, codex_level):
    return {"providers": {
        "claude": {"ok": True, "level": claude_level, "action": "a"},
        "codex":  {"ok": True, "level": codex_level, "action": "a"},
    }}


# ---------------------------------------------------------------- fetch_payload

def test_fetch_payload_prefers_fresh_cache(monkeypatch, tmp_path):
    cache = tmp_path / "coach-cache.json"
    cache.write_text(json.dumps({"payload": {"marker": "from-cache"}, "ts": time.time()}))
    monkeypatch.setattr(mm, "COACH_CACHE_PATH", str(cache))

    def fail_if_called(extra_args):
        raise AssertionError("캐시가 신선하면 라이브 조회를 하면 안 됨")

    monkeypatch.setattr(mm, "_live_fetch", fail_if_called)

    assert mm.fetch_payload([]) == {"marker": "from-cache"}


def test_fetch_payload_falls_back_when_cache_stale(monkeypatch, tmp_path):
    cache = tmp_path / "coach-cache.json"
    stale_ts = time.time() - (mm.CACHE_STALE_SEC + 60)
    cache.write_text(json.dumps({"payload": {"marker": "from-cache"}, "ts": stale_ts}))
    monkeypatch.setattr(mm, "COACH_CACHE_PATH", str(cache))
    monkeypatch.setattr(mm, "_live_fetch", lambda extra_args: {"marker": "live"})

    assert mm.fetch_payload([]) == {"marker": "live"}


def test_fetch_payload_falls_back_when_cache_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(mm, "COACH_CACHE_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setattr(mm, "_live_fetch", lambda extra_args: {"marker": "live"})

    assert mm.fetch_payload([]) == {"marker": "live"}


def test_fetch_payload_use_cache_false_always_bypasses(monkeypatch, tmp_path):
    cache = tmp_path / "coach-cache.json"
    cache.write_text(json.dumps({"payload": {"marker": "from-cache"}, "ts": time.time()}))
    monkeypatch.setattr(mm, "COACH_CACHE_PATH", str(cache))
    monkeypatch.setattr(mm, "_live_fetch", lambda extra_args: {"marker": "live"})

    # --mock 등 명시적 오버라이드는 신선한 캐시가 있어도 무시해야 함
    assert mm.fetch_payload([], use_cache=False) == {"marker": "live"}


def test_render_card_explains_missing_claude_account_identifier():
    message = mm.render_card({"providers": {
        "claude": {"ok": True, "level": "green", "action": "사용 가능", "windows": {}},
    }})

    assert "Claude" in message
    assert "계정 식별자 미제공" in message


# ---------------------------------------------------------------- upsert_card

def test_upsert_card_edits_existing_post(monkeypatch):
    calls = []

    def fake_request(url, method, body, token):
        calls.append((url, method))
        return {"id": "post-1"}

    monkeypatch.setattr(mm, "_request", fake_request)
    state = {"post_id": "post-1"}

    pid = mm.upsert_card("http://mm.example", "tok", "ch1", "hello", state)

    assert pid == "post-1"
    assert calls == [("http://mm.example/api/v4/posts/post-1", "PUT")]


def test_upsert_card_falls_back_to_new_post_on_404(monkeypatch):
    calls = []

    def fake_request(url, method, body, token):
        calls.append((url, method))
        if method == "PUT":
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "not found", None, None)
        return {"id": "post-2"}

    monkeypatch.setattr(mm, "_request", fake_request)
    state = {"post_id": "stale-post"}

    pid = mm.upsert_card("http://mm.example", "tok", "ch1", "hello", state)

    assert pid == "post-2"
    assert calls[0][1] == "PUT" and calls[1][1] == "POST"


def test_upsert_card_posts_new_when_no_prior_id(monkeypatch):
    def fake_request(url, method, body, token):
        assert method == "POST"
        return {"id": "post-3"}

    monkeypatch.setattr(mm, "_request", fake_request)

    pid = mm.upsert_card("http://mm.example", "tok", "ch1", "hello", {})

    assert pid == "post-3"


# ---------------------------------------------------------------- ping_if_worse

def test_ping_batches_simultaneous_worsening_into_one_message(monkeypatch):
    calls = []

    def fake_request(url, method, body, token):
        calls.append((url, method, body))
        return {"id": "ping-1"}

    monkeypatch.setattr(mm, "_request", fake_request)
    state = {"last_levels": {"claude": "green", "codex": "green"}}
    payload = _payload("yellow", "yellow")

    now = mm.ping_if_worse("http://mm.example", "tok", "ch1", payload, state)

    assert now == {"claude": "yellow", "codex": "yellow"}
    assert len(calls) == 1
    url, method, body = calls[0]
    assert method == "POST" and url == "http://mm.example/api/v4/posts"
    assert "Claude" in body["message"] and "Codex" in body["message"]
    assert state["last_ping_id"] == "ping-1"


def test_ping_deletes_previous_ping_before_posting_new_one(monkeypatch):
    calls = []

    def fake_request(url, method, body, token):
        calls.append((url, method))
        return {} if method == "DELETE" else {"id": "ping-2"}

    monkeypatch.setattr(mm, "_request", fake_request)
    state = {"last_levels": {"claude": "green"}, "last_ping_id": "ping-1"}
    payload = _payload("yellow", "green")

    mm.ping_if_worse("http://mm.example", "tok", "ch1", payload, state)

    assert calls[0] == ("http://mm.example/api/v4/posts/ping-1", "DELETE")
    assert calls[1][1] == "POST"
    assert state["last_ping_id"] == "ping-2"


def test_ping_delete_failure_does_not_block_new_post(monkeypatch):
    def fake_request(url, method, body, token):
        if method == "DELETE":
            raise OSError("already gone")
        return {"id": "ping-new"}

    monkeypatch.setattr(mm, "_request", fake_request)
    state = {"last_levels": {"claude": "green"}, "last_ping_id": "stale"}
    payload = _payload("red", "green")

    now = mm.ping_if_worse("http://mm.example", "tok", "ch1", payload, state)

    assert now["claude"] == "red"
    assert state["last_ping_id"] == "ping-new"


def test_no_worsening_means_no_network_call(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("worsening 없으면 _request가 호출되면 안 됨")

    monkeypatch.setattr(mm, "_request", fail_if_called)
    state = {"last_levels": {"claude": "green", "codex": "green"}, "last_ping_id": "ping-1"}
    payload = _payload("green", "green")

    now = mm.ping_if_worse("http://mm.example", "tok", "ch1", payload, state)

    assert now == {"claude": "green", "codex": "green"}
    assert state["last_ping_id"] == "ping-1"
