#!/usr/bin/env bash
# usage-coach 대시보드 LaunchAgent 설치 — discord_dash.py 5분 간격 실행
# DRY_RUN=1 이면 launchctl 을 건너뛰고 plist 파일만 만든다(테스트 계약).
set -euo pipefail
fail() { echo "오류: $*" >&2; exit 1; }

DIR="$(cd "$(dirname "$0")/.." && pwd)"
# DRY_RUN 은 launchctl 없이 plist 만 만들므로 플랫폼 무관(테스트·검토용)
[[ "${DRY_RUN:-0}" == "1" || "$(uname)" == "Darwin" ]] || fail "macOS 전용입니다 (launchd 사용)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
[[ -n "$PYTHON_BIN" ]] || fail "python3 를 찾을 수 없음"
# 대시보드별로 그 대시보드의 설정 파일이 있을 때만 LaunchAgent 를 설치한다
# (Discord 전용·Telegram 전용 사용자가 자기 것만 깨끗이 설치되도록). 둘 다 없으면 실패.
# 환경변수(DISCORD_WEBHOOK_URL·TELEGRAM_*)는 launchd 잡에 전달되지 않으므로(plist엔 PATH만,
# 비밀값은 굽지 않음) 설치 판정에 쓰지 않는다 — env만 있으면 5분마다 실패하는 잡이 생긴다.
DISCORD_CFG=0
[[ -f "$HOME/.config/usage-coach/discord.json" ]] && DISCORD_CFG=1
TELEGRAM_CFG=0
[[ -f "$HOME/.config/usage-coach/telegram.json" ]] && TELEGRAM_CFG=1
[[ "$DISCORD_CFG" == 1 || "$TELEGRAM_CFG" == 1 ]] \
  || fail "Discord/Telegram 설정 파일이 없어요 — ~/.config/usage-coach/discord.json 에 {\"webhook_url\": \"...\"} 또는 telegram.json 중 하나는 먼저 만드세요 (환경변수는 launchd 잡에 전달되지 않음)"

mkdir -p "$HOME/Library/LaunchAgents"
# 설치 시점의 완전한 PATH를 굽는다 — launchd 기본 PATH에는 /usr/local/bin 등이 없어
# coach.py의 codexbar 호출이 Errno 2로 죽는다 (2026-08-04 E2E 실측)
# plist는 XML이므로 & 뿐 아니라 < > " 까지 모두 이스케이프한다(& 먼저).
# PATH뿐 아니라 저장소 경로($DIR, 예: ~/R&D/usage-coach)·PYTHON_BIN 도 plist에 들어가므로 같이 이스케이프.
# 치환문의 & 는 \& 로 이스케이프해야 한다 — bash 5.2+ 에서 ${v//p/s} 의 s 안에 있는 & 는
# "매칭된 문자열"로 확장되므로, &lt; 라고 쓰면 & 가 매칭(<)으로 치환돼 <lt; 가 된다.
# (&amp; 만은 매칭이 & 라서 우연히 결과가 같아 이 버그가 오래 가려져 있었다.)
xml_esc() {
  local v="$1"
  v="${v//&/\&amp;}"
  v="${v//</\&lt;}"
  v="${v//>/\&gt;}"
  v="${v//\"/\&quot;}"
  printf '%s' "$v"
}
PATH_ESC="$(xml_esc "$PATH")"
DIR_ESC="$(xml_esc "$DIR")"
PYTHON_ESC="$(xml_esc "$PYTHON_BIN")"

LABEL="com.usage-coach.dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TELEGRAM_LABEL="com.usage-coach.telegram-dashboard"
TELEGRAM_PLIST="$HOME/Library/LaunchAgents/$TELEGRAM_LABEL.plist"

# $1=label $2=plist경로 $3=스크립트파일 — 표준 plist 한 개를 쓴다
write_plist() {
  cat > "$2" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array>
    <string>$PYTHON_ESC</string>
    <string>$DIR_ESC/$3</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$PATH_ESC</string></dict>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
}

installed=()
[[ "$DISCORD_CFG" == 1 ]]  && { write_plist "$LABEL" "$PLIST" "discord_dash.py"; installed+=("$PLIST"); }
[[ "$TELEGRAM_CFG" == 1 ]] && { write_plist "$TELEGRAM_LABEL" "$TELEGRAM_PLIST" "telegram_dash.py"; installed+=("$TELEGRAM_PLIST"); }

if [[ "${DRY_RUN:-0}" != "1" ]]; then
  UID_N=$(id -u)
  if [[ "$DISCORD_CFG" == 1 ]]; then
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_N" "$PLIST"
  fi
  if [[ "$TELEGRAM_CFG" == 1 ]]; then
    launchctl bootout "gui/$UID_N/$TELEGRAM_LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_N" "$TELEGRAM_PLIST"
  fi
fi
echo "설치됨: ${installed[*]} (5분 간격)"
