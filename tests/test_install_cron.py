"""install-cron.sh / uninstall-cron.sh — Linux/WSL2용 install.sh 대응 스크립트 검증.

CRONTAB_FILE 환경변수로 진짜 사용자 crontab을 건드리지 않고 가짜 파일로 격리한다
(install.sh의 macOS 전용 가드 때문에 이 환경에서 검증 못 하던 것의 WSL2 대응 — 감사
리포트 D단계). test_install_scripts.py와 같은 패턴(webhook 설정·DRY_RUN 계약)을 따른다.
"""
import json, os, subprocess
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"


def run(script, home, cron_file, dry_run="1", extra_env=None):
    env = dict(os.environ, HOME=str(home), DRY_RUN=dry_run, CRONTAB_FILE=str(cron_file))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["bash", str(SCRIPTS / script)], capture_output=True, text=True, env=env)


def _prep(home):
    cfg = home / ".config/usage-coach"
    cfg.mkdir(parents=True)
    (cfg / "discord.json").write_text(json.dumps({"webhook_url": "https://example.invalid/hook"}))


def test_install_cron_fails_without_webhook_config(tmp_path):
    cron_file = tmp_path / "crontab.txt"
    r = run("install-cron.sh", tmp_path, cron_file)
    assert r.returncode == 1
    assert "webhook" in r.stderr.lower()
    assert not cron_file.exists()


def test_install_cron_dry_run_does_not_touch_file(tmp_path):
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    r = run("install-cron.sh", tmp_path, cron_file, dry_run="1")
    assert r.returncode == 0, r.stderr
    assert "usage-coach-dashboard" in r.stdout
    assert not cron_file.exists()          # DRY_RUN은 파일을 실제로 안 씀


def test_install_cron_writes_marker_line(tmp_path):
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    r = run("install-cron.sh", tmp_path, cron_file, dry_run="0")
    assert r.returncode == 0, r.stderr
    content = cron_file.read_text()
    assert "*/5 * * * *" in content
    assert "discord_dash.py" in content
    assert "# usage-coach-dashboard" in content


def test_install_cron_preserves_existing_unrelated_lines(tmp_path):
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    cron_file.write_text("0 4 * * * /some/other/job.sh\n")
    run("install-cron.sh", tmp_path, cron_file, dry_run="0")
    content = cron_file.read_text()
    assert "/some/other/job.sh" in content          # 기존 무관 줄 보존
    assert "usage-coach-dashboard" in content


def test_install_cron_is_idempotent(tmp_path):
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    run("install-cron.sh", tmp_path, cron_file, dry_run="0")
    run("install-cron.sh", tmp_path, cron_file, dry_run="0")   # 재설치
    lines = [l for l in cron_file.read_text().splitlines() if "usage-coach-dashboard" in l]
    assert len(lines) == 1                          # 중복 등록 안 됨


def test_uninstall_cron_removes_only_marker_line(tmp_path):
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    cron_file.write_text("0 4 * * * /some/other/job.sh\n")
    run("install-cron.sh", tmp_path, cron_file, dry_run="0")
    r = run("uninstall-cron.sh", tmp_path, cron_file, dry_run="0")
    assert r.returncode == 0, r.stderr
    content = cron_file.read_text()
    assert "usage-coach-dashboard" not in content
    assert "/some/other/job.sh" in content           # 무관 줄은 여전히 보존


def test_marker_substring_in_unrelated_line_is_not_removed(tmp_path):
    """마커 문자열이 줄 끝이 아니라 다른 줄 중간(주석 등)에 우연히 있으면 지우면 안 된다."""
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    decoy = "0 9 * * * /bin/true # note: usage-coach-dashboard is unrelated here\n"
    cron_file.write_text(decoy)
    run("install-cron.sh", tmp_path, cron_file, dry_run="0")
    r = run("uninstall-cron.sh", tmp_path, cron_file, dry_run="0")
    assert r.returncode == 0, r.stderr
    content = cron_file.read_text()
    assert decoy.strip() in content                  # 오탐으로 지워지면 안 됨
    # 그래도 install-cron.sh가 새로 심은 정식 마커 줄은 제거돼야 함
    assert not any(l.rstrip().endswith("# usage-coach-dashboard") for l in content.splitlines())


def test_path_round_trips_through_cron_line(tmp_path):
    """PATH에 홑따옴표·쌍따옴표·달러·백틱이 섞여도 (1) 설치 직후 동기실행 (2) crontab에 심긴
    줄을 cron처럼 최소환경에서 독립 재실행 둘 다에서 원본 PATH 값이 한 글자도 안 틀리고 나오는지
    (문법만 보는 sh -n이 아니라 실제 실행값 비교 — codex-critic 1차 지적 반영)."""
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    fakebin = tmp_path / "fakebin"; fakebin.mkdir()
    capture = tmp_path / "captured_path.txt"
    fake_python = fakebin / "python3"
    fake_python.write_text(f"#!/bin/sh\nprintf '%s' \"$PATH\" > '{capture}'\n")
    fake_python.chmod(0o755)
    evil_path = "/usr/bin:/tmp/'sing'quote/\"dq\"/$HOME/`bt`:/bin"

    env = dict(os.environ, HOME=str(tmp_path), DRY_RUN="0", CRONTAB_FILE=str(cron_file),
               PATH=evil_path, PYTHON_BIN=str(fake_python))
    r = subprocess.run(["bash", str(SCRIPTS / "install-cron.sh")], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr

    # (1) RunAtLoad 대응 동기 1회 실행에서 캡처된 PATH가 원본과 완전히 동일한지
    assert capture.exists(), "설치 직후 동기 실행이 안 됨"
    assert capture.read_text() == evil_path
    capture.unlink()

    # (2) crontab에 심긴 줄 자체를, cron이 실제로 넘기는 것처럼 "다른(최소) 환경"에서
    # 독립 재실행해도 줄에 박힌 PATH= 프리픽스만으로 원본이 그대로 재현되는지
    line = next(l for l in cron_file.read_text().splitlines() if "usage-coach-dashboard" in l)
    command_part = line.split(None, 5)[5]
    clean_env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    subprocess.run(["sh", "-c", command_part], env=clean_env, capture_output=True, text=True)
    assert capture.exists(), "crontab 줄 독립 재실행이 실패함(구문 깨짐 가능성)"
    assert capture.read_text() == evil_path


def test_crontab_l_unexplained_failure_aborts_without_writing(tmp_path):
    """crontab -l이 원인불명으로 실패하면(권한오류 등) 빈 crontab으로 오인해 덮어쓰지 말고 중단
    해야 한다 — stderr 메시지뿐 아니라 '쓰기용 crontab 재호출이 실제로 없었는지'까지 확인
    (codex-critic 1차 지적: 간접 확인만으론 부족)."""
    _prep(tmp_path)
    fakebin = tmp_path / "fakebin"; fakebin.mkdir()
    call_log = tmp_path / "crontab_calls.log"
    (fakebin / "crontab").write_text(
        f"#!/bin/sh\necho \"$@\" >> '{call_log}'\n"
        "if [ \"$1\" = \"-l\" ]; then echo 'permission denied' >&2; exit 1; fi\n"
        "cat > /dev/null\n"   # 혹시 write 모드로도 불리면 입력만 삼키는 안전망(실제로는 안 불려야 함)
    )
    (fakebin / "crontab").chmod(0o755)
    env = dict(os.environ, HOME=str(tmp_path), DRY_RUN="0",
               PATH=f"{fakebin}:{os.environ['PATH']}")
    env.pop("CRONTAB_FILE", None)   # 진짜 crontab 코드경로를 타게 하되 PATH로 가짜 crontab을 앞세움
    r = subprocess.run(["bash", str(SCRIPTS / "install-cron.sh")], capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert "crontab -l 실패" in r.stderr or "원인불명" in r.stderr
    calls = call_log.read_text().splitlines() if call_log.exists() else []
    assert calls == ["-l"], f"write 모드 재호출이 있으면 안 됨(덮어쓰기 발생 가능): {calls}"
