#!/bin/bash
# antigravity(agy) "language server" 상시 기동 — codexbar가 antigravity 사용량을
# 조회하려면 실제 TTY를 가진 agy 대화형 세션이 살아있어야 한다(2026-08-12 실측:
# agy 원샷 호출/TTY 없는 백그라운드 실행은 감지 안 됨, tmux pty로 띄운 `agy -i`
# 세션이 떠있는 동안에는 codexbar usage --provider antigravity가 정상 응답함).
# 이 세션은 응답을 요구하지 않는 대기 프롬프트만 넣고 그대로 유지한다.
#
# 이미 세션이 있으면 그대로 두고(안전하게 재실행 가능), 없으면 재시도 루프로 새로 띄운다.
set -uo pipefail

SESSION="agy-keepalive"
LOG="$HOME/.claude/logs/agy-keepalive.log"
mkdir -p "$(dirname "$LOG")"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "[$(date '+%F %T')] $SESSION: 이미 실행 중 — 건너뜀" >> "$LOG"
  exit 0
fi

tmux new-session -d -s "$SESSION" -x 200 -y 50 \
  "export PATH=\"$HOME/.local/bin:\$PATH\"; while true; do echo \"[\$(date '+%F %T')] agy -i 기동\" >> '$LOG'; agy -i '대기 세션 — 응답하지 말고 세션만 유지'; echo \"[\$(date '+%F %T')] agy 종료 — 5초 뒤 재시작\" >> '$LOG'; sleep 5; done"

echo "[$(date '+%F %T')] $SESSION: 새로 기동함" >> "$LOG"
