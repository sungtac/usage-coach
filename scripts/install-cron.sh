#!/usr/bin/env bash
# usage-coach 대시보드 cron 설치 — discord_dash.py 5분 간격 실행 (Linux/WSL2용, install.sh의 비-macOS 대응)
# install.sh와 동일 계약: webhook_url 확인, python3 확인, DRY_RUN=1이면 실제 crontab을 안 건드리고
# "설치될 내용"만 출력한다.
#
# 테스트 훅: CRONTAB_FILE 이 설정되면 실제 `crontab` 명령 대신 그 파일을 읽고 쓴다
# (진짜 사용자 crontab을 실수로 건드리지 않고 검증하기 위함). 미설정 시 실제 crontab 사용.
set -euo pipefail
fail() { echo "오류: $*" >&2; exit 1; }

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
[[ -n "$PYTHON_BIN" ]] || fail "python3 를 찾을 수 없음"
[[ -f "$HOME/.config/usage-coach/discord.json" || -n "${DISCORD_WEBHOOK_URL:-}" ]] \
  || fail "webhook_url 미설정 — ~/.config/usage-coach/discord.json 에 {\"webhook_url\": \"...\"} 를 먼저 만드세요"

MARKER="# usage-coach-dashboard"

# 값 하나를 injection-safe 한 작은따옴표 문자열로 감싼다(내용에 $, `, ", \ 무엇이 와도 안전).
shq() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

# 현재 crontab을 전역변수 CURRENT_CRONTAB 에 담는다. $(...) 서브셸 안에서 fail()을 부르면
# exit이 서브셸만 끝내고 본 스크립트는 안 멈추는 함정이 있어, 최상위에서 직접 호출한다.
get_current_crontab() {
  if [[ -n "${CRONTAB_FILE:-}" ]]; then
    if [[ -f "$CRONTAB_FILE" ]]; then CURRENT_CRONTAB="$(cat "$CRONTAB_FILE")"; else CURRENT_CRONTAB=""; fi
    return
  fi
  local out rc=0
  out="$(crontab -l 2>&1)" || rc=$?
  if [[ $rc -ne 0 ]]; then
    # "no crontab for <user>"만 진짜 빈 상태다. 그 외 실패(권한 오류 등)를 빈 crontab으로
    # 오인하면 기존 작업(이 repo의 daily_review.sh 포함)을 통째로 덮어써 지울 수 있다 —
    # 그래서 원인불명 실패는 반드시 여기서 중단한다.
    if [[ "$out" == *"no crontab for"* ]]; then CURRENT_CRONTAB=""
    else fail "crontab -l 실패(원인불명) — 기존 crontab 보존을 위해 여기서 멈춤: $out"
    fi
  else
    CURRENT_CRONTAB="$out"
  fi
}

write_crontab() {
  if [[ -n "${CRONTAB_FILE:-}" ]]; then cat > "$CRONTAB_FILE"
  else crontab -
  fi
}

# read-modify-write 사이 경쟁을 이 스크립트/uninstall-cron.sh끼리는 flock으로 막는다.
# (다른 프로세스가 그 순간 별도로 `crontab -e`를 돌리는 경우까지는 못 막는다 — crontab
# 명령 자체가 원자적 교체를 지원하지 않아서다. 그 잔여 위험은 감수한다.)
mkdir -p "$HOME/.config/usage-coach"
LOCK_FILE="$HOME/.config/usage-coach/install-cron.lock"
exec 200>"$LOCK_FILE"
flock -w 10 200 || fail "다른 install/uninstall-cron.sh 실행 중(10초 대기 후 포기) — 잠시 후 재시도"

get_current_crontab

# 설치 시점의 완전한 PATH를 굽는다(install.sh의 launchd PATH 주입과 동일 이유, 2026-08-04 실측).
# 값 전체를 shq로 감싸 PATH에 특수문자가 있어도 cron이 잘못 해석하지 않게 한다.
LINE="*/5 * * * * PATH=$(shq "$PATH") $(shq "$PYTHON_BIN") $(shq "$DIR/discord_dash.py") >> \"\$HOME/.config/usage-coach/cron.log\" 2>&1 $MARKER"

# 마커가 "줄 끝"에 오는 경우만 골라 제거한다 — grep -F로 아무 위치나 매칭하면 다른 작업의
# 인자·주석·로그경로에 우연히 같은 문자열이 있을 때 무관한 줄까지 지울 수 있다.
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
  # RunAtLoad 대응 — launchd는 등록 즉시 1회 실행하지만 cron은 다음 5분 경계까지 대기하므로
  # 여기서 한 번 동기 실행해 "설치하면 바로 반영"을 맞춘다.
  "$PYTHON_BIN" "$DIR/discord_dash.py" || echo "경고: 최초 실행 실패(설정 확인 필요) — cron은 정상 등록됨" >&2
fi
echo "설치됨: crontab 마커 '$MARKER' (5분 간격, Linux/WSL2 cron)"
