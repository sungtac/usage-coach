#!/usr/bin/env python3
"""usage-coach 텔레그램 대시보드.

discord_dash의 coach 조회·병합·게이지 로직을 재사용해 HTML 텍스트 한 개를
주기적으로 편집하고, level이 악화될 때만 별도 알림을 보낸다.
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from discord_dash import (
    BAR_W, LEVELS, PROV_EMOJI, PROV_HEX, SEVERITY, WIN_CODE, _bar,
    _primary_window, _win_emoji, build_coach_extra_args, fetch_all_accounts,
    fetch_payload, merge_all_accounts, provider_order,
)

CONFIG_PATH = os.path.expanduser("~/.config/usage-coach/telegram.json")
STATE_PATH = os.path.expanduser("~/.config/usage-coach/telegram-state.json")
DEFAULT_TOKEN_FILE = os.path.expanduser("~/.edge-agent/secrets/telegram/claude.token")
MAX_TEXT = 4096
API_ROOT = "https://api.telegram.org/bot"


class TelegramError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _esc(value):
    return html.escape(str(value), quote=False)


def _duration(minutes):
    minutes = round(minutes)
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days}일 {hours}시간" if hours else f"{days}일"
    if hours:
        return f"{hours}시간 {mins}분" if mins else f"{hours}시간"
    return f"{mins}분"


def _reset_text(minutes):
    if minutes is None:
        return None
    return "곧 초기화" if round(minutes) < 1 else f"{_duration(minutes)} 후"


def _plain_truncate(text):
    """길이 초과 시 태그를 제거한 안전한 HTML 텍스트로 줄인다."""
    if len(text) <= MAX_TEXT:
        return text
    plain = re.sub(r"<[^>]*>", "", text)
    plain = html.escape(html.unescape(plain), quote=False)
    return plain[:MAX_TEXT - 3] + "..."


def _window_line(code, info, width=None):
    info = info or {}
    pct = info.get("left_pct")
    shown = "—" if pct is None else str(pct)
    label = str(code)
    width = width or len(label)
    reset = _reset_text(info.get("reset_min"))
    return (f"{_win_emoji(pct)} <code>{_esc(label.ljust(width))}  "
            f"{_bar(pct)}</code> <b>{_esc(shown)}%</b>" +
            (f" · 리셋 {_esc(reset)}" if reset else ""))


def _provider_block(key, provider):
    title = _esc(key.title())
    if not provider.get("ok"):
        error = _esc(str(provider.get("error", ""))[:120])
        return f"⚠️ <b>{title}</b> — 조회 실패 — {error}"

    level = provider.get("level")
    default_emoji = LEVELS.get(level, ("#9AA4B2", "⚪", ""))[1]
    emoji = default_emoji if level not in ("green", "white") else PROV_EMOJI.get(key, default_emoji)
    lines = [f"{emoji} <b>{title}</b> — {_esc(provider.get('action', ''))}"]
    if provider.get("email"):
        lines.append(f"<i>{_esc(provider['email'])}</i>")

    accounts = provider.get("multi")
    if accounts:
        accounts = sorted(accounts, key=lambda a: (a.get("email") or "?").split("@", 1)[0].lower())
        width = max((len((a.get("email") or "?").split("@", 1)[0]) for a in accounts), default=1)
        for account in accounts:
            local = (account.get("email") or "?").split("@", 1)[0]
            pk = _primary_window(account.get("windows", {}))
            info = account.get("windows", {}).get(pk, {}) if pk else {}
            code = WIN_CODE.get(pk, pk or "")
            lines.append(f"<i>{_esc(local.ljust(width))}</i>\n" +
                         _window_line(code, info, len(code)))
    else:
        windows = provider.get("windows", {})
        win_width = max((len(WIN_CODE.get(wk, wk)) for wk in windows), default=1)
        for wk, info in windows.items():
            lines.append(_window_line(WIN_CODE.get(wk, wk), info, win_width))
    if provider.get("reason"):
        lines.append(f"<b>{_esc(provider['reason'])}</b>")
    return "\n".join(lines)


def build_card(payload, now=None):
    blocks = [_provider_block(key, payload["providers"][key])
              for key in provider_order(payload.get("providers", {}))]
    current = now or datetime.now()
    blocks.append(f"<i>갱신 {current:%H:%M}</i>")
    return _plain_truncate("\n\n".join(blocks))


def _api_request(token, method, params):
    url = f"{API_ROOT}{urllib.parse.quote(token, safe='')}/{method}"
    data = urllib.parse.urlencode(params).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    try:
        result = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        result = {}
    if not result.get("ok"):
        raise TelegramError(result.get("description", f"Telegram API 오류 ({status})"), status)
    return result.get("result", {})


def send_message(token, chat_id, text):
    return _api_request(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def edit_message(token, chat_id, message_id, text):
    return _api_request(token, "editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                                     "text": text, "parse_mode": "HTML"})


def upsert_card(token, chat_id, text, state, force_new=False):
    message_id = state.get("message_id")
    if message_id and not force_new:
        try:
            edit_message(token, chat_id, message_id, text)
            return message_id
        except TelegramError as exc:
            if "message is not modified" in str(exc).lower():
                return message_id
            if exc.status not in (None, 400, 404):
                raise
    result = send_message(token, chat_id, text)
    return result.get("message_id")


def ping_if_worse(token, chat_id, payload, state):
    last = state.get("last_levels", {})
    current = {}
    for key, provider in payload.get("providers", {}).items():
        level = provider.get("level") if provider.get("ok") else None
        current[key] = level
        if level not in ("yellow", "red"):
            continue
        previous = last.get(key)
        if previous is not None and SEVERITY.get(level, 9) < SEVERITY.get(previous, 9):
            emoji, verdict = LEVELS[level][1], LEVELS[level][2]
            who = key.title()
            if provider.get("email"):
                who += f"({provider['email'].split('@', 1)[0]})"
            send_message(token, chat_id,
                         f"{emoji} <b>{_esc(who)}</b> {_esc(verdict)} — {_esc(provider.get('action', ''))}")
    return current


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {}


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"   # 같은 디렉토리 임시파일 + os.replace 로 원자적 교체(부분쓰기 방지)
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def _load_token(cli_value, config):
    if cli_value:
        return cli_value
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return os.environ["TELEGRAM_BOT_TOKEN"]
    if config.get("bot_token"):
        return config["bot_token"]
    token_file = config.get("bot_token_file", DEFAULT_TOKEN_FILE)
    try:
        token = Path(os.path.expanduser(token_file)).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"텔레그램 토큰 파일을 읽을 수 없어요: {token_file} ({exc})") from exc
    if not token:
        raise ValueError(f"텔레그램 토큰 파일이 비어 있어요: {token_file}")
    return token


def main():
    ap = argparse.ArgumentParser(description="usage-coach 텔레그램 대시보드")
    ap.add_argument("--out", metavar="PATH", help="HTML 텍스트만 저장(Bot API 미사용)")
    ap.add_argument("--token", help="Bot API 토큰")
    ap.add_argument("--chat-id", help="채팅 ID")
    ap.add_argument("--force-new", action="store_true")
    ap.add_argument("--mock", metavar="N")
    ap.add_argument("--file", action="append", default=[], metavar="PATH:PROVIDER")
    ap.add_argument("--providers")
    ap.add_argument("--account", action="append", default=[], metavar="PROVIDER:LABEL")
    args = ap.parse_args()
    config = load_config()
    extra, multi = build_coach_extra_args(args, config)
    payload = fetch_payload(extra)
    if multi:
        merge_all_accounts(payload, multi, config)
    card = build_card(payload)
    if args.out:
        Path(args.out).write_text(card, encoding="utf-8")
        print(f"텔레그램 카드 저장: {args.out}")
        return 0
    try:
        token = _load_token(args.token, config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    chat_id = args.chat_id or os.environ.get("TELEGRAM_CHAT_ID") or config.get("chat_id")
    if not chat_id:
        print("채팅 ID가 없어요. --chat-id / TELEGRAM_CHAT_ID / telegram.json 의 chat_id 중 "
              "하나로 지정하세요.", file=sys.stderr)
        return 2
    state = load_state()
    state["last_levels"] = ping_if_worse(token, chat_id, payload, state)
    save_state(state)   # 핑 상태를 먼저 영속화 — 카드 편집이 실패해도 같은 전이가 재핑되지 않도록
    state["message_id"] = upsert_card(token, chat_id, card, state, args.force_new)
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
