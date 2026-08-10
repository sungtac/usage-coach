#!/usr/bin/env bash
# usage-coach 대시보드 cron 제거 — install-cron.sh의 대응 제거 경로 (Linux/WSL2용)
# 테스트 훅: CRONTAB_FILE (install-cron.sh와 동일 계약)
set -euo pipefail
fail() { echo "오류: $*" >&2; exit 1; }
MARKER="# usage-coach-dashboard"

# install-cron.sh와 동일한 안전장치: crontab -l 실패를 "빈 crontab"으로 오인하면
# 제거 스크립트가 사용자의 기존 crontab을 통째로 지워버릴 수 있다 — 원인불명 실패는 중단.
get_current_crontab() {
  if [[ -n "${CRONTAB_FILE:-}" ]]; then
    if [[ -f "$CRONTAB_FILE" ]]; then CURRENT_CRONTAB="$(cat "$CRONTAB_FILE")"; else CURRENT_CRONTAB=""; fi
    return
  fi
  local out rc=0
  out="$(crontab -l 2>&1)" || rc=$?
  if [[ $rc -ne 0 ]]; then
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

# install-cron.sh와 같은 lock 파일 — 두 스크립트가 동시에 crontab을 건드리지 않게 직렬화한다.
mkdir -p "$HOME/.config/usage-coach"
LOCK_FILE="$HOME/.config/usage-coach/install-cron.lock"
exec 200>"$LOCK_FILE"
flock -w 10 200 || fail "다른 install/uninstall-cron.sh 실행 중(10초 대기 후 포기) — 잠시 후 재시도"

get_current_crontab

KEPT_LINES=""
[[ -n "$CURRENT_CRONTAB" ]] && KEPT_LINES="$(printf '%s\n' "$CURRENT_CRONTAB" | grep -vE -- "${MARKER}\$" || true)"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "[DRY_RUN] 제거 후 crontab:"
  printf '%s\n' "$KEPT_LINES"
else
  printf '%s\n' "$KEPT_LINES" | write_crontab
fi
echo "제거됨: crontab 마커 '$MARKER' (설정 ~/.config/usage-coach/ 은 보존)"
