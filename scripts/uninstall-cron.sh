#!/usr/bin/env bash
# usage-coach 대시보드 cron 제거 — install-cron.sh의 대응 제거 경로 (Linux/WSL2용)
# 테스트 훅: CRONTAB_FILE (install-cron.sh와 동일 계약)
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_cron_common.sh"   # fail/MARKER/get_current_crontab/write_crontab/acquire_cron_lock

acquire_cron_lock

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
