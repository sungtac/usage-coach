"""install-cron-mattermost.sh / uninstall-cron-mattermost.sh — test_install_cron.py(디스코드)와
동일 패턴. 핵심 차이점만 검증: 별도 설정파일(mattermost.json)·별도 마커·디스코드 크론과의 공존.
"""
import json, os, subprocess
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
MARKER = "# usage-coach-dashboard-mattermost"


def run(script, home, cron_file, dry_run="1", extra_env=None):
    env = dict(os.environ, HOME=str(home), DRY_RUN=dry_run, CRONTAB_FILE=str(cron_file))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["bash", str(SCRIPTS / script)], capture_output=True, text=True, env=env)


def _prep(home):
    cfg = home / ".config/usage-coach"
    cfg.mkdir(parents=True)
    (cfg / "mattermost.json").write_text(json.dumps(
        {"url": "https://mm.example.invalid", "token": "tok", "channel_id": "ch1"}))


def test_install_cron_fails_without_mattermost_config(tmp_path):
    cron_file = tmp_path / "crontab.txt"
    r = run("install-cron-mattermost.sh", tmp_path, cron_file)
    assert r.returncode == 1
    assert "메타모스트" in r.stderr
    assert not cron_file.exists()


def test_install_cron_writes_marker_line(tmp_path):
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    r = run("install-cron-mattermost.sh", tmp_path, cron_file, dry_run="0")
    assert r.returncode == 0, r.stderr
    content = cron_file.read_text()
    assert "*/5 * * * *" in content
    assert "mattermost_dash.py" in content
    assert MARKER in content


def test_install_cron_is_idempotent(tmp_path):
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    run("install-cron-mattermost.sh", tmp_path, cron_file, dry_run="0")
    run("install-cron-mattermost.sh", tmp_path, cron_file, dry_run="0")
    lines = [l for l in cron_file.read_text().splitlines() if MARKER in l]
    assert len(lines) == 1


def test_uninstall_cron_removes_only_marker_line(tmp_path):
    _prep(tmp_path)
    cron_file = tmp_path / "crontab.txt"
    cron_file.write_text("0 4 * * * /some/other/job.sh\n")
    run("install-cron-mattermost.sh", tmp_path, cron_file, dry_run="0")
    r = run("uninstall-cron-mattermost.sh", tmp_path, cron_file, dry_run="0")
    assert r.returncode == 0, r.stderr
    content = cron_file.read_text()
    assert MARKER not in content
    assert "/some/other/job.sh" in content


def test_discord_and_mattermost_crons_coexist(tmp_path):
    """두 대시보드를 같은 crontab에 설치해도 서로의 마커 줄을 건드리지 않아야 한다."""
    home = tmp_path
    cfg = home / ".config/usage-coach"
    cfg.mkdir(parents=True)
    (cfg / "discord.json").write_text(json.dumps({"webhook_url": "https://example.invalid/hook"}))
    (cfg / "mattermost.json").write_text(json.dumps(
        {"url": "https://mm.example.invalid", "token": "tok", "channel_id": "ch1"}))
    cron_file = home / "crontab.txt"

    r1 = run("install-cron.sh", home, cron_file, dry_run="0")
    assert r1.returncode == 0, r1.stderr
    r2 = run("install-cron-mattermost.sh", home, cron_file, dry_run="0")
    assert r2.returncode == 0, r2.stderr

    content = cron_file.read_text()
    assert "discord_dash.py" in content
    assert "mattermost_dash.py" in content
    assert content.count("# usage-coach-dashboard\n") == 1 or \
        any(l.rstrip().endswith("# usage-coach-dashboard") for l in content.splitlines())
    assert any(l.rstrip().endswith(MARKER) for l in content.splitlines())

    # 메타모스트만 제거해도 디스코드 줄은 남아야 함
    r3 = run("uninstall-cron-mattermost.sh", home, cron_file, dry_run="0")
    assert r3.returncode == 0, r3.stderr
    content = cron_file.read_text()
    assert "discord_dash.py" in content
    assert "mattermost_dash.py" not in content
