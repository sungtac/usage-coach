#!/bin/bash
# Claude Code statusLine — 세션 스냅샷 기록자(대시보드 '봇 세션' 클로드 카드의 데이터원).
#
# 프로덕션 로컬 스크립트의 스냅샷 계약(~/.config/usage-coach/sessions/<sid>.json:
# cwd·project_dir·model·used·ts)을 정본화한 것 (2026-08-05 E2E 3차 게이트 —
# 정본화 전엔 저자 로컬 사설 스크립트라 신규 계정에서 클로드 카드가 영구 공백).
# 의존성: python3 만 사용 (jq 불요 — 신규 계정 전제도구 최소화).
# 어떤 입력에도 0으로 종료한다 — statusline 실패가 세션을 방해하면 안 된다.
input=$(cat)
STATUSLINE_INPUT="$input" exec python3 - <<'PY'
import json, os, re, sys, time

try:
    d = json.loads(os.environ.get("STATUSLINE_INPUT", ""))
except ValueError:
    sys.exit(0)
if not isinstance(d, dict):   # 유효 JSON이어도 객체가 아니면(null/숫자/배열/문자열) 데이터 없음 처리
    sys.exit(0)

def obj(v):   # 중첩 필드가 객체가 아니면(문자열 등) 빈 객체로 — .get() 크래시 방지
    return v if isinstance(v, dict) else {}


def text(v):
    return v if isinstance(v, str) else ""


ws = obj(d.get("workspace"))
cwd = text(ws.get("current_dir")) or text(d.get("cwd"))
model = text(obj(d.get("model")).get("display_name"))
used = obj(d.get("context_window")).get("used_percentage")
if isinstance(used, bool) or not isinstance(used, (int, float)):
    used = None

home = os.path.expanduser("~")
# 경로 경계까지 비교 — /home/sungt 가 /home/sungtac/... 를 "~ac/..." 로 줄이지 않게
short = "~" + cwd[len(home):] if cwd == home or cwd.startswith(home.rstrip("/") + "/") else cwd
line = short + (f" [{model}]" if model else "")
if used is not None:
    line += f" · ctx {round(used)}%"
print(line, end="")

sid = d.get("session_id")
# session_id는 파일명으로 쓰이므로 안전 문자만 허용 — "../x" 같은 값이 sessions/ 밖에 쓰지 못하게
if isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9._-]+", sid) and sid not in (".", ".."):
    snap_dir = os.path.join(home, ".config/usage-coach/sessions")
    try:
        os.makedirs(snap_dir, exist_ok=True)
        with open(os.path.join(snap_dir, f"{sid}.json"), "w") as f:
            # bot_name: 런처가 심어주는 봇 식별자 — 같은 작업폴더를 쓰는 여러 봇을
            # 대시보드가 구분해 표시하는 데 쓴다(tasks/bot-session-identity, discord-multiagent repo).
            json.dump({"cwd": cwd,
                       "project_dir": text(ws.get("project_dir")) or cwd,
                       "model": model, "used": used,
                       "ts": int(time.time()),
                       "bot_name": os.environ.get("CLAUDE_BOT_NAME") or ""}, f)
    except OSError:
        pass
PY
