"""서빙 프로세스의 코드 신원(git-흡수 G2, S5 봉합).

deep-dive 2026-07-02(비평가 실측): 라이브 :55170 프로세스가 6커밋 stale 코드를 서빙 중인데 *감지할 방법이 없었다* —
/version 엔드포인트가 없어 프로세스가 어느 커밋에서 부팅했는지 알 수 없었다. git 은 산출물이 자기 생산자 신원을
지닌다(commit-graph trailer-checksum, commit-graph.c:2220-2221). 이식: 부팅 *시점*의 git sha 를 한 번 스냅샷해
캐시하고, 디스크 HEAD 와 비교해 stale 을 *자기보고*한다.

핵심 불변식: boot_git_sha 는 import 시점(=프로세스 기동)에 한 번 잡고 다시 유도하지 않는다 — 그래야 "이 프로세스가
어느 코드로 돌고 있나"의 참값이 된다. disk_head_sha() 는 매 호출 재유도(현 디스크). 둘이 다르면 stale.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from functools import lru_cache

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git_head_sha(root: str) -> str:
    """root 저장소의 HEAD 커밋 sha(짧은형). subprocess 우선, 실패 시 .git/HEAD 수동 파싱, 최후 'unknown'."""
    try:
        out = subprocess.run(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    # 배포 tarball 등 git 부재 대비: .git/HEAD → ref 파일 수동 해석.
    try:
        head = os.path.join(root, ".git", "HEAD")
        with open(head) as f:
            ref = f.read().strip()
        if ref.startswith("ref:"):
            refpath = os.path.join(root, ".git", ref.split(" ", 1)[1].strip())
            with open(refpath) as f:
                return f.read().strip()[:7]
        return ref[:7]   # detached HEAD = 직접 sha
    except OSError:
        return "unknown"


# ── 부팅 스냅샷(모듈 import 시점 = 프로세스 기동) — 재유도 금지 ──────────────────────────────
BOOT_GIT_SHA: str = _git_head_sha(_ROOT)
BOOT_TIME: str = datetime.now(timezone.utc).isoformat()


@lru_cache(maxsize=1)
def _cached_root() -> str:
    return _ROOT


def disk_head_sha() -> str:
    """현 디스크의 HEAD sha(매 호출 재유도) — 부팅 스냅샷과 비교해 프로세스 stale 판정용."""
    return _git_head_sha(_cached_root())


def served_version() -> dict:
    """서빙 코드 신원 + stale 자기보고. /version 엔드포인트와 배포 프로브가 소비.

    stale=True ⟺ 프로세스가 부팅한 커밋(boot_git_sha)이 현 디스크 HEAD(disk_head_sha)와 다름
    = 코드가 갱신됐으나 프로세스 미재기동(S5 결함의 관측가능화).
    """
    disk = disk_head_sha()
    return {
        "boot_git_sha": BOOT_GIT_SHA,
        "boot_time": BOOT_TIME,
        "disk_head_sha": disk,
        "stale": BOOT_GIT_SHA != disk and BOOT_GIT_SHA != "unknown" and disk != "unknown",
    }
