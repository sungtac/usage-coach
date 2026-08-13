# install-cron.sh / uninstall-cron.sh 공용 — crontab 안전 read/write + 락.
# source해서 쓴다(직접 실행 대상 아님). 코드리뷰 지적: 이 로직이 두 스크립트에 거의
# 그대로 복붙돼 있어 한쪽만 고치면 다른 쪽이 뒤처질 위험이 있었다.
fail() { echo "오류: $*" >&2; exit 1; }
MARKER="# usage-coach-dashboard"

# 테스트 훅: CRONTAB_FILE 이 설정되면 실제 `crontab` 명령 대신 그 파일을 읽고 쓴다
# (진짜 사용자 crontab을 실수로 건드리지 않고 검증하기 위함). 미설정 시 실제 crontab 사용.
#
# crontab -l 실패를 "빈 crontab"으로 오인하면 기존 작업(daily_review.sh 등)을 통째로
# 덮어써 지울 수 있다 — "no crontab for <user>"만 진짜 빈 상태이고, 그 외 원인불명
# 실패(권한 오류 등)는 반드시 여기서 중단한다.
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

# read-modify-write 사이 경쟁을 install-cron.sh/uninstall-cron.sh끼리는 flock으로 막는다.
# (다른 프로세스가 그 순간 별도로 `crontab -e`를 돌리는 경우까지는 못 막는다 — crontab
# 명령 자체가 원자적 교체를 지원하지 않아서다. 그 잔여 위험은 감수한다.)
acquire_cron_lock() {
  mkdir -p "$HOME/.config/usage-coach"
  local lock_file="$HOME/.config/usage-coach/install-cron.lock"
  exec 200>"$lock_file"
  flock -w 10 200 || fail "다른 install/uninstall-cron.sh 실행 중(10초 대기 후 포기) — 잠시 후 재시도"
}
