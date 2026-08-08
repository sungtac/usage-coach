"""라이브 사용량 조회가 계정 전환 뒤에도 stale web 캐시를 쓰지 않는지 검증."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import coach


def main():
    claude = coach.LIVE_CMDS["claude"]
    assert "--source" in claude
    assert claude[claude.index("--source") + 1] == "oauth"
    fallback = coach.LIVE_FALLBACK_CMDS["claude"]
    assert len(fallback) == 1
    assert fallback[0][fallback[0].index("--source") + 1] == "cli"
    print("PASS: Claude usage source is explicit OAuth")
    print("PASS: Claude usage has non-web CLI fallback")


if __name__ == "__main__":
    main()
