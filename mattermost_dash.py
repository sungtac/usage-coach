#!/usr/bin/env python3
"""usage-coach 메타모스트 대시보드 — discord_dash.py의 카드(업서트)+핑 설계를
그대로 메타모스트에 이식한다. Components V2 같은 리치 UI가 없어 마크다운 텍스트로
렌더링한다는 점만 다르다.

데이터 소스는 라이브 재조회가 아니라 discord_dash.py가 5분 크론마다 갱신해두는
~/.config/usage-coach/coach-cache.json을 읽는다 — 메타모스트까지 독립적으로
`coach --json --once`를 매 5분 부르면 codexbar 락 경합이 늘어난다(2026-08-21
statusline 지연 버그의 원인과 동일 클래스). 캐시가 없거나 너무 오래됐을 때만
직접 조회로 폴백한다.

실행: LaunchAgent/cron이 주기 실행(기본 5분, discord_dash.py 크론 직후 권장).
설정: ~/.config/usage-coach/mattermost.json {"url", "token", "channel_id"}
상태: ~/.config/usage-coach/mattermost-state.json {"post_id", "last_levels", "last_ping_id"}
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from discord_dash import LEVELS, SEVERITY, PROV_EMOJI, WIN_CODE, COACH  # 판정 정책·상수 재사용

CONFIG_PATH = os.path.expanduser("~/.config/usage-coach/mattermost.json")
STATE_PATH = os.path.expanduser("~/.config/usage-coach/mattermost-state.json")
COACH_CACHE_PATH = os.path.expanduser("~/.config/usage-coach/coach-cache.json")
CACHE_STALE_SEC = 20 * 60   # 5분 크론 기준 4주기 — 이보다 오래되면 캐시를 못 믿고 직접 조회
USERNAME = "usage-coach"

BAR_W = 14


# ---------------------------------------------------------------- 데이터 소스

def _live_fetch(extra_args):
    cmd = [sys.executable, str(COACH), "--json", "--once"] + extra_args
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"coach --json 실패 (exit {out.returncode}): {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def fetch_payload(extra_args, use_cache=True):
    """coach-cache.json(디스코드 크론이 채움)을 우선 사용, 없거나 오래됐으면 직접 조회.
    use_cache=False(--mock/--file 등 명시적 오버라이드)면 캐시를 건너뛰고 항상 직접 조회."""
    if use_cache:
        try:
            with open(COACH_CACHE_PATH, encoding="utf-8") as f:
                cached = json.load(f)
            age = time.time() - cached.get("ts", 0)
            if age <= CACHE_STALE_SEC:
                return cached["payload"]
            print(f"coach-cache.json이 {int(age)}초 전 데이터라 오래됨 — 직접 조회로 폴백", file=sys.stderr)
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    return _live_fetch(extra_args)


# ---------------------------------------------------------------- 마크다운 렌더링

def _bar(pct):
    if pct is None:
        return "░" * BAR_W
    filled = max(0, min(BAR_W, round(pct / 100 * BAR_W)))
    return "█" * filled + "░" * (BAR_W - filled)


def _win_emoji(pct):
    if pct is None:
        return "⚪"
    if pct < 25:
        return "🔴"
    if pct < 50:
        return "🟡"
    return "🟢"


def _dur_min(mins):
    mins = round(mins)
    d, rem = divmod(mins, 1440)
    h, m = divmod(rem, 60)
    if d:
        return f"{d}일 {h}시간" if h else f"{d}일"
    if h:
        return f"{h}시간 {m}분" if m else f"{h}시간"
    return f"{m}분"


def _provider_section(key, p):
    if not p.get("ok"):
        unconfigured = p.get("configured") is False
        icon = "⚪" if unconfigured else "⚠️"
        prefix = "" if unconfigured else "조회 실패 — "
        return f"**{icon} {key.title()}**\n{prefix}{str(p.get('error', ''))[:120]}"

    level = p.get("level")
    emoji = LEVELS.get(level, ("#9AA4B2", "⚪", ""))[1]
    if level in ("green", "white"):
        emoji = PROV_EMOJI.get(key, emoji)
    head = f"**{emoji} {key.title()}**"
    if p.get("email"):
        head += f" · {p['email']}"
    elif key == "claude":
        # Claude 조회는 성공해도 codexbar가 계정 식별자를 반환하지 않을 수 있다.
        # 빈 헤더로 숨기지 않고 현재 조회 한계를 명시한다.
        head += " · 계정 식별자 미제공"
    if p.get("action"):
        head += f" — {p['action']}"

    lines = []
    windows = p.get("windows", {})
    lw = max((len(WIN_CODE.get(wk, wk)) for wk in windows), default=0)
    for wk, info in windows.items():
        pct = info.get("left_pct")
        line = (f"{_win_emoji(pct)} `{WIN_CODE.get(wk, wk).ljust(lw)}  {_bar(pct)}` "
                f"**{'—' if pct is None else pct}%**")
        reset_min = info.get("reset_min")
        if reset_min is not None:
            line += f" · {_dur_min(reset_min)} 남음" if round(reset_min) >= 1 else " · 곧 초기화"
        lines.append(line)

    parts = [head]
    if lines:
        parts.append("\n".join(lines))
    if p.get("reason"):
        parts.append(f"_{p['reason']}_")
    return "\n".join(parts)


def provider_order(provs):
    order = ["claude", "codex", "antigravity"]
    return [k for k in order if k in provs] + [k for k in provs if k not in order]


def render_card(payload):
    provs = payload.get("providers", {})
    sections = [_provider_section(key, provs[key]) for key in provider_order(provs)]
    body = "\n\n---\n\n".join(sections)
    ts = time.strftime("%H:%M", time.localtime())
    return f"#### 📊 사용량 코치 — {ts} 업데이트\n\n{body}"


# ---------------------------------------------------------------- 메타모스트 API

def _request(url, method, payload_json, token, _retries=3):
    data = None if payload_json is None else json.dumps(payload_json,
                                                        ensure_ascii=False).encode()
    headers = {"User-Agent": "usage-coach-dash", "Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    for attempt in range(_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            return json.loads(raw) if raw else {}
        except urllib.error.URLError as e:
            if isinstance(e.reason, OSError) and attempt < _retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def upsert_card(base_url, token, channel_id, message, state, force_new=False):
    pid = state.get("post_id")
    if pid and not force_new:
        try:
            _request(f"{base_url}/api/v4/posts/{pid}", "PUT",
                     {"id": pid, "message": message}, token)
            return pid
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    res = _request(f"{base_url}/api/v4/posts", "POST",
                   {"channel_id": channel_id, "message": message}, token)
    return res.get("id")


def ping_if_worse(base_url, token, channel_id, payload, state):
    """provider level이 yellow/red로 악화된 순간에만 새 메시지(푸시).
    이전 핑 메시지(state["last_ping_id"])가 있으면 지우고 새로 게시 — discord_dash.py
    ping_if_worse와 동일 설계(안 지우면 채널에 핑이 계속 쌓임)."""
    last = state.get("last_levels", {})
    now = {}
    lines = []
    for key, p in payload.get("providers", {}).items():
        lv = p.get("level") if p.get("ok") else None
        now[key] = lv
        if lv not in ("yellow", "red"):
            continue
        prev = last.get(key)
        if prev is not None and SEVERITY.get(lv, 9) < SEVERITY.get(prev, 9):
            _color, emoji, verdict = LEVELS[lv]
            who = key.title()
            if p.get("email"):
                who += f"({p['email'].split('@', 1)[0]})"
            lines.append(f"{emoji} **{who}** {verdict} — {p.get('action', '')}")

    if lines:
        old_id = state.get("last_ping_id")
        if old_id:
            try:
                _request(f"{base_url}/api/v4/posts/{old_id}", "DELETE", None, token)
            except Exception as e:
                print(f"이전 핑 삭제 실패: {e}", file=sys.stderr)
        try:
            res = _request(f"{base_url}/api/v4/posts", "POST",
                           {"channel_id": channel_id, "message": "\n".join(lines)}, token)
            state["last_ping_id"] = res.get("id")
        except Exception as e:
            print(f"핑 전송 실패: {e}", file=sys.stderr)
    return now


# ---------------------------------------------------------------- 설정·상태

def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="usage-coach 메타모스트 대시보드")
    ap.add_argument("--out", metavar="PATH", help="메시지 텍스트만 저장(API 미사용)")
    ap.add_argument("--force-new", action="store_true", help="편집 대신 새 메시지 게시")
    ap.add_argument("--mock", metavar="N", help="coach --mock 전달(1~5|all, 캐시 폴백시에만 유효)")
    ap.add_argument("--providers", help="coach --providers 전달(캐시 폴백시에만 유효)")
    args = ap.parse_args()

    config = load_config()
    extra = []
    override = bool(args.mock)
    if args.mock:
        extra += ["--mock", args.mock]
    if args.providers:
        extra += ["--providers", args.providers]
    else:
        extra += ["--providers", "claude,codex,antigravity"]

    payload = fetch_payload(extra, use_cache=not override)
    message = render_card(payload)

    if args.out:
        Path(args.out).write_text(message, encoding="utf-8")
        print(f"메시지 저장: {args.out}")
        return 0

    base_url = config.get("url")
    token = config.get("token")
    channel_id = config.get("channel_id")
    if not (base_url and token and channel_id):
        print("메타모스트 연결정보가 없어요. ~/.config/usage-coach/mattermost.json 에 "
              '{"url": "...", "token": "...", "channel_id": "..."} 를 넣어주세요.',
              file=sys.stderr)
        return 2
    base_url = base_url.rstrip("/")

    state = load_state()
    state["last_levels"] = ping_if_worse(base_url, token, channel_id, payload, state)
    try:
        state["post_id"] = upsert_card(base_url, token, channel_id, message, state, args.force_new)
    except Exception as e:
        save_state(state)
        print(f"카드 갱신 실패: {e}", file=sys.stderr)
        return 1
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
