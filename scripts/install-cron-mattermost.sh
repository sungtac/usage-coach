#!/usr/bin/env bash
# usage-coach 메타모스트 대시보드 cron 설치 — mattermost_dash.py 5분 간격 실행 (Linux/WSL2용)
# install-cron.sh(디스코드)와 동일 계약이되, 별도 MARKER를 써서 같은 crontab에 공존한다.
# 테스트 훅: CRONTAB_FILE (install-cron.sh와 동일 계약)
set -euo pipefail
MARKER="# usage-coach-dashboard-mattermost"   # _cron_common.sh source 전에 정해야 기본값을 안 씀
source "$(cd "$(dirname "$0")" && pwd)/_cron_common.sh"   # fail/get_current_crontab/write_crontab/acquire_cron_lock

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
[[ -n "$PYTHON_BIN" ]] || fail "python3 를 찾을 수 없음"
[[ -f "$HOME/.config/usage-coach/mattermost.json" ]] \
  || fail "메타모스트 연결정보 미설정 — ~/.config/usage-coach/mattermost.json 에 {\"url\": \"...\", \"token\": \"...\", \"channel_id\": \"...\"} 를 먼저 만드세요"

shq() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

acquire_cron_lock
get_current_crontab

# install-cron.sh와 동일한 WSL2 PATH 트림(998자 명령 길이 한도 회피, 2026-08-04 실측 버그 대응).
trimmed_path() {
  printf '%s' "$1" | tr ':' '\n' | grep -vE '^/mnt/[A-Za-z](/|$)' | awk '!seen[$0]++' | paste -sd: -
}
INSTALL_PATH="$(trimmed_path "$PATH")"
LINE="*/5 * * * * PATH=$(shq "$INSTALL_PATH") $(shq "$PYTHON_BIN") $(shq "$DIR/mattermost_dash.py") >> \"\$HOME/.config/usage-coach/cron.log\" 2>&1 $MARKER"

KEPT_LINES=""
[[ -n "$CURRENT_CRONTAB" ]] && KEPT_LINES="$(printf '%s\n' "$CURRENT_CRONTAB" | grep -vE -- "${MARKER}\$" || true)"
if [[ -n "$KEPT_LINES" ]]; then
  NEW_CRONTAB="$(printf '%s\n%s\n' "$KEPT_LINES" "$LINE")"
else
  NEW_CRONTAB="$(printf '%s\n' "$LINE")"
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "[DRY_RUN] 설치될 crontab (마커: $MARKER):"
  echo "$NEW_CRONTAB"
else
  printf '%s\n' "$NEW_CRONTAB" | write_crontab
  "$PYTHON_BIN" "$DIR/mattermost_dash.py" || echo "경고: 최초 실행 실패(설정 확인 필요) — cron은 정상 등록됨" >&2
fi
echo "설치됨: crontab 마커 '$MARKER' (5분 간격, Linux/WSL2 cron)"
