# usage-coach

[codexbar](https://github.com/steipete/CodexBar)의 사용량 데이터를 읽어 **"지금 어떤 크기의 작업을 돌리면 되는지 + 왜 + (필요시) 언제"**를 알려주는 터미널 도구. 단순 정보 표시가 아니라 **행동 권고**가 출력이다.

Claude · Codex · Antigravity의 5시간·7일 한도를 교차 분석해 5가지 상황으로 코칭하고, 에이전트 루프용 **요금 가드**(`--hook` / `--guard-check`)를 함께 제공한다.

## 핵심 개념

- **5시간 한도** = 안 쓰면 reset으로 사라짐 → 남으면 아낌없이 소진(use-it-or-lose-it).
- **7일 한도** = 페이스 관리.
- **Fable 5 주간 한도**(Claude Max 구독) = 표시 전용 `Fable` 라인. 코칭·요금가드 판정에는 미반영이며, 기본 구독처럼 데이터가 없으면 라인 자체를 생략한다. `--json`에는 `fable_7d` 키로 나온다.
- 코어 비교 = `left`(잔량 비율) vs `timeLeft`(reset까지 시간 비율). 둘 중 빡빡한 쪽이 작업 크기 상한.

## 출력 5종

| | 상황 | 권고 |
|--|--|--|
| 🔴 | 7일 한도가 빠듯 | 큰 작업은 미루기 |
| 🟢 | 5시간 넉넉 + 7일 여유 | 지금 큰 작업 |
| ⏳ | 5시간 부족 + 초기화 임박 | 곧 reset, 잠깐 대기 |
| 🟡 | 5시간 부족 + 페이스 뒤처짐 | 작은 작업만 |
| ⚪ | 평소 | 평소대로 |

## 요구사항

- Python 3 (표준 라이브러리만 — 의존성 없음)
- [codexbar](https://github.com/steipete/CodexBar) — 사용량 데이터 소스(`codexbar` CLI)

## 설치

```bash
git clone https://github.com/sungtac/usage-coach.git
cd usage-coach
# 전역 명령으로 쓰려면 심링크(선택)
ln -s "$PWD/coach.py" /usr/local/bin/coach
```

## 사용법

```bash
coach                                    # 전체 provider 라이브 조회 + watch
coach --providers claude,codex           # 특정 provider만
coach --once                             # 한 번만 찍고 종료
coach --mock all                         # 출력 5종 데모(모킹)
coach --file samples/claude.json:claude  # JSON 파일에서 읽기
coach --account antigravity:foo@gmail.com  # 계정 지정(codexbar --account 패스스루, 반복 가능)
coach --json                             # 머신 출력(JSON 1줄) — 에이전트 루프용
```

codexbar 제약: `--provider all`은 hang하므로 provider별로 따로 조회한다(coach가 자동 처리). codex는 `--source auto`(app-server가 ephemeral 모드인 환경에서 `cli` RPC가 타임아웃나는 문제 때문 — oauth 경로로 폴백). codexbar는 동시 실행 시에도 잠금/행이 걸리므로 coach.py 프로세스 간에는 파일 락(`~/.config/usage-coach/codexbar.lock`)으로 직렬화하고, 일시 실패·타임아웃은 1회 재시도한다(락 대기 최대 60초, 실행당 타임아웃은 단일 계정 조회 45초·전 계정 조회 90초 — 그래도 안 잡히면 fail-open으로 건너뛴다).

계정 미등록(해당 호스트에 그 provider 앱·계정이 아예 없는 영구 상태, 예: antigravity 미설치)은 재시도로 안 풀리는 별도 상태라 일시 실패(⚠️)와 구분해 ⚪로 표시한다(JSON은 `configured: false`).

## 테스트

전체 스위트는 pytest로 돌린다(일부 테스트 파일은 pytest 함수형이라 직접 실행하면 아무것도 검사하지 않는다).

```bash
python3 -m pytest -q
```

## 요금 가드 (에이전트 루프)

긴 자율 루프가 사용량을 보고 **위험하면 스스로 멈추게** 한다.

- `coach --hook` — Claude Code Stop 훅용. 7일 가드. 정지 시 `{"continue":false,"stopReason":...}` 출력(exit 0), 통과 시 무출력. 훅 입력의 `stop_hook_active`가 참일 때(루프 2턴째부터)만 판정한다.
- `coach --guard-check` — provider 중립 체크(Codex `/goal` 워처용). 정지 시 exit 10 + 사유 1줄(stdout), 통과 시 exit 0 무출력.
- `coach guard on|off|status` — 런타임 스위치(기본 off → 항상 통과).

판정 = 하이브리드 OR: `left < timeLeft − m`(페이스) **또는** `left < floor`(절대). 설정 = `~/.config/usage-coach/guard.json` (provider별 `m`/`floor`/`pace`, 기본 0.10/0.10/true).

coach/codexbar 조회 오류나 유효한 7일 window 부재(판정 불가)는 기본 **fail-open** — 그 provider는 건너뛰고(경고는 stderr) 작업을 막지 않는다. 판정 불가도 정지시키려면 guard.json 최상위에 `"strict": true`를 넣는다(opt-in fail-closed).

## 디스코드 대시보드 (`discord_dash.py`)

coach 출력을 **Components V2** 메시지(provider별 컨테이너 + 유니코드 게이지 바)로 조립해 디스코드 웹훅 메시지 하나를 **계속 편집**하는 라이브 대시보드. 채널을 열면 항상 최신 상태가 보인다. 전부 네이티브 텍스트라 데스크톱·모바일 어느 폭에서도 선명하다(구버전 PNG 카드는 세로가 길수록 통째로 축소되는 문제가 있어 교체).

- 구성 = provider별 컨테이너(accent 색 = level) 안에 윈도우별 게이지 바 + **코칭 문구(action·reason 전문)** + 리셋 시각(`<t:..:R>` — 보는 사람 로컬 기준 "3시간 후"처럼 자동 표시).
- (봇 세션 섹션은 제거됐다. `scripts/statusline-command.sh`는 여전히 `~/.config/usage-coach/sessions/<session_id>.json` 스냅샷을 남기지만 현재 대시보드는 이를 표시하지 않는다.)
- level이 🟡/🔴로 **나빠지는 순간에만** 새 메시지를 게시해 푸시 알림을 울린다(평소 편집은 무알림).
- 의존성 없음(coach 본체와 동일 — 표준 라이브러리만).
- 함정: 웹훅으로 components를 보낼 때 URL에 `?with_components=true`가 없으면 필드가 통째로 무시된다(`Cannot send an empty message`, 50006). POST·PATCH(편집) 모두 해당.

```bash
python3 discord_dash.py --out c.json        # 컴포넌트 JSON만 저장(웹훅 미사용, 검증용)
python3 discord_dash.py --mock all --out c.json
python3 discord_dash.py                     # 조회→조립→웹훅 업서트(+악화 핑)
```

설정: `~/.config/usage-coach/discord.json`에 `{"webhook_url": "..."}` (또는 env `DISCORD_WEBHOOK_URL`). 같은 파일의 `"coach_args": ["--account", "antigravity:foo@gmail.com"]`로 대시보드가 추적할 계정을 고정할 수 있다(카드에 계정 이메일 표시됨). 여러 계정을 오가는 provider는 `"all_accounts"`(기본 `["antigravity"]`)에 넣으면 codexbar `--all-accounts`로 **등록된 전 계정을 계정별 바로 표시**하고, 코칭·본문·핑은 가장 여유 있는 계정 기준으로 잡는다(끄려면 `"all_accounts": []`). 상태(메시지 ID·직전 level)는 `discord-state.json`에 저장. 주기 실행은 LaunchAgent 등으로 5분 간격 권장(웹훅만 쓰므로 봇 토큰·gateway 불필요).

## 텔레그램 대시보드 (`telegram_dash.py`)

Discord 대시보드와 같은 coach 사용량·코칭 정보를 Telegram HTML 텍스트 카드 하나로 표시하고, 기존 메시지를 계속 편집한다. level이 🟡/🔴로 나빠질 때만 별도 푸시를 보낸다.

- 설정 = `~/.config/usage-coach/telegram.json`, 상태 = `~/.config/usage-coach/telegram-state.json`. 봇 토큰은 `--token` / `TELEGRAM_BOT_TOKEN` / 설정의 `bot_token` / `bot_token_file`(기본 `~/.edge-agent/secrets/telegram/claude.token`) 순서로 찾는다. 채팅 ID는 `--chat-id` / `TELEGRAM_CHAT_ID` / 설정의 `chat_id` 중 하나로 **반드시 지정**해야 하며(하드코딩 기본값 없음), 없으면 발송하지 않고 명확히 실패한다.
- `--out`은 Bot API를 호출하지 않고 카드 텍스트만 저장한다.

```bash
python3 telegram_dash.py --mock all --out t.txt  # API 없이 검증
python3 telegram_dash.py                       # 조회→Telegram 업서트(+악화 핑)
```

주기 실행은 `scripts/install.sh`가 설치 시점의 PATH를 포함한 두 LaunchAgent를 생성한다(대시보드별로 `discord.json`/`telegram.json` 설정 파일이 있을 때만 — 환경변수는 launchd 잡에 전달되지 않으므로 설정은 파일에 둘 것). 실행 전 `DRY_RUN=1 scripts/install.sh`로 생성 내용을 검토할 수 있다.

## 라이선스

[MIT](./LICENSE)
