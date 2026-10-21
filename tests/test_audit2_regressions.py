"""2차 감사(2026-10-22) 회귀 테스트 — 각 테스트는 수정 전 코드에서 실패한다."""

import contextlib
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import coach  # noqa: E402
import discord_dash  # noqa: E402
import telegram_dash  # noqa: E402

TIGHT = {"secondary": {"usedPercent": 99, "windowMinutes": 10080,
                       "resetsAt": "2999-01-01T00:00:00Z"}}


def _clean_env(home, extra_path=None):
    path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                           if ".local/bin" not in p)
    if extra_path:
        path = f"{extra_path}{os.pathsep}{path}"
    return dict(os.environ, HOME=str(home), PATH=path)


# ── watch: EOF stdin이 interval을 무시한 무한 재조회가 되지 않는다 ─────────
def test_watch_with_eof_stdin_respects_interval(tmp_path):
    with open(os.devnull) as devnull:
        proc = subprocess.Popen([sys.executable, str(ROOT / "coach.py"), "--mock", "2",
                                 "--watch", "30"], stdin=devnull, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=_clean_env(tmp_path))
        time.sleep(1.5)
        proc.kill()
        out, _ = proc.communicate()
    frames = out.decode("utf-8", "replace").count("사용량 코치")
    assert frames <= 2, f"{frames} frames in 1.5s with a 30s interval"


# ── 공백뿐인 stderr도 실패 사유가 IndexError 메시지로 둔갑하지 않는다 ─────
def test_whitespace_only_stderr_reports_clear_failure(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    fake = fakebin / "codexbar"
    fake.write_text("#!/bin/sh\necho ' ' >&2\nexit 1\n")
    fake.chmod(0o755)
    for prov in ("claude", "codex", "antigravity"):
        r = subprocess.run([sys.executable, str(ROOT / "coach.py"), "--providers", prov,
                            "--json"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env=_clean_env(tmp_path, str(fakebin)), timeout=60)
        entry = json.loads(r.stdout)["providers"][prov]
        assert entry["ok"] is False
        assert "list index" not in entry["error"], (prov, entry["error"])
        assert "조회 실패" in entry["error"]


# ── strict: 판정 불가가 다른 provider의 실제 정지 사유를 가리지 않는다 ─────
def test_strict_unavailable_keeps_real_triggers():
    for failing, tight in (("claude", "codex"), ("codex", "claude")):
        def fake(kind, arg, failing=failing):
            if arg == failing:
                raise RuntimeError("down")
            return TIGHT
        with patch.object(coach, "load_usage", side_effect=fake):
            reason = coach.guard_check([(failing, "live", failing), (tight, "live", tight)],
                                       coach.load_guard_config(path="/x"), strict=True)
        assert "판정 불가" in reason and failing in reason
        assert f"{tight} 주간" in reason, reason


# ── guard status 미리보기 = 훅/워처 실제 판정(strict 내부 오류 포함) ──────
def test_guard_status_matches_strict_hook_on_internal_error():
    with patch.object(coach, "guard_enabled", return_value=True), \
            patch.object(coach, "load_guard_strict", return_value=True), \
            patch.object(coach, "guard_check", side_effect=KeyError("k")):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            coach.run_guard_cmd("status", [])
        assert "지금이면 정지" in out.getvalue()
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2):
            assert coach.run_guard_check([]) == 10


def test_guard_cli_end_to_end_contract(tmp_path):
    """실제 CLI: fail-open 기본 / strict 정지 — Claude 훅·Codex 워처 출력 계약."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    fake = fakebin / "codexbar"
    fake.write_text("#!/bin/sh\necho 'boom' >&2\nexit 1\n")
    fake.chmod(0o755)
    env = _clean_env(tmp_path, str(fakebin))
    cfg = tmp_path / ".config/usage-coach"

    def run(*args, stdin=""):
        return subprocess.run([sys.executable, str(ROOT / "coach.py"), *args,
                               "--providers", "claude,codex"],
                              input=stdin, capture_output=True, text=True, env=env, timeout=60)

    assert run("guard", "on").returncode == 0
    event = '{"stop_hook_active": true}'
    hook, chk = run("--hook", stdin=event), run("--guard-check")
    assert (hook.returncode, hook.stdout, chk.returncode, chk.stdout) == (0, "", 0, "")
    assert "claude" in chk.stderr and "codex" in chk.stderr
    (cfg / "guard.json").write_text('{"strict": true}')
    hook, chk = run("--hook", stdin=event), run("--guard-check")
    payload = json.loads(hook.stdout)
    assert hook.returncode == 0 and payload["continue"] is False
    assert "claude" in payload["stopReason"] and "codex" in payload["stopReason"]
    assert chk.returncode == 10 and "claude" in chk.stdout and "codex" in chk.stdout
    assert "지금이면 정지" in run("guard", "status").stdout
    assert run("guard", "off").returncode == 0
    assert (cfg / "guard.json").exists()            # off는 strict 설정을 건드리지 않는다
    assert run("--guard-check").returncode == 0


# ── 대시보드: 일시적 조회 실패 뒤의 악화는 여전히 핑한다 ───────────────────
def test_discord_pings_red_after_transient_failure():
    for prov in ("claude", "codex"):
        sent = []
        with patch.object(discord_dash, "_request", lambda *a, **k: sent.append(a)):
            st = {"last_levels": {prov: "white"}}
            st["last_levels"] = discord_dash.ping_if_worse(
                "w", {"providers": {prov: {"ok": False, "error": "x"}}}, st)
            st["last_levels"] = discord_dash.ping_if_worse(
                "w", {"providers": {prov: {"ok": True, "level": "red"}}}, st)
        assert len(sent) == 1, prov


def test_telegram_pings_red_after_transient_failure():
    for prov in ("claude", "codex"):
        sent = []
        with patch.object(telegram_dash, "send_message", lambda *a, **k: sent.append(a)):
            st = {"last_levels": {prov: "white"}}
            st["last_levels"] = telegram_dash.ping_if_worse(
                "t", "c", {"providers": {prov: {"ok": False, "error": "x"}}}, st)
            st["last_levels"] = telegram_dash.ping_if_worse(
                "t", "c", {"providers": {prov: {"ok": True, "level": "red"}}}, st)
        assert len(sent) == 1, prov


# ── Telegram 길이 한도는 UTF-16 단위 ───────────────────────────────────────
def test_telegram_truncation_counts_utf16_units():
    text = "<b>x</b>" + ("🔴 a&b\n" * 1200)
    out = telegram_dash._plain_truncate(text)
    import html
    assert len(html.unescape(out).encode("utf-16-le")) // 2 <= telegram_dash.MAX_TEXT
    assert out.endswith("...")


# ── install.sh: 저장소 경로의 XML 메타문자도 이스케이프 ─────────────────────
def test_install_escapes_repo_dir_in_plist(tmp_path):
    repo = tmp_path / "R&D <x>"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/install.sh", repo / "scripts/install.sh")
    home = tmp_path / "home"
    (home / ".config/usage-coach").mkdir(parents=True)
    (home / ".config/usage-coach/discord.json").write_text("{}")
    r = subprocess.run(["bash", str(repo / "scripts/install.sh")], capture_output=True,
                       text=True, env=dict(os.environ, HOME=str(home), DRY_RUN="1"))
    assert r.returncode == 0, r.stderr
    plist = home / "Library/LaunchAgents/com.usage-coach.dashboard.plist"
    data = plistlib.loads(plist.read_bytes())
    assert data["ProgramArguments"][1] == f"{repo.resolve()}/discord_dash.py"


# ── statusline: 홈 접두어는 경로 경계에서만 ~ 로 줄인다 ──────────────────
def test_statusline_home_prefix_respects_path_boundary(tmp_path):
    home = tmp_path / "u"
    home.mkdir()
    env = dict(os.environ, HOME=str(home))
    for cwd, want in ((f"{home}ac/proj", f"{home}ac/proj"), (f"{home}/proj", "~/proj"),
                      (str(home), "~")):
        r = subprocess.run(["bash", str(ROOT / "scripts/statusline-command.sh")],
                           input=json.dumps({"cwd": cwd}), capture_output=True, text=True,
                           env=env)
        assert r.stdout == want, (cwd, r.stdout)
