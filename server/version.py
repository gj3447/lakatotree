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


def _manual_git_head_sha(root: str) -> str:
    """git 실행파일 부재 시 *root 자신의* .git/HEAD만 읽는 제한적 fallback."""
    git_dir = os.path.join(root, ".git")
    try:
        # linked worktree의 .git은 실제 git-dir를 가리키는 text file이다.
        if os.path.isfile(git_dir):
            with open(git_dir, encoding="utf-8") as f:
                pointer = f.read().strip()
            if not pointer.startswith("gitdir:"):
                return "unknown"
            git_dir = pointer.split(":", 1)[1].strip()
            if not os.path.isabs(git_dir):
                git_dir = os.path.join(root, git_dir)
            git_dir = os.path.realpath(git_dir)

        head = os.path.join(git_dir, "HEAD")
        with open(head, encoding="utf-8") as f:
            ref = f.read().strip()
        if ref.startswith("ref:"):
            refpath = os.path.join(git_dir, ref.split(" ", 1)[1].strip())
            with open(refpath, encoding="utf-8") as f:
                return f.read().strip()[:7]
        return ref[:7]   # detached HEAD = 직접 sha
    except OSError:
        return "unknown"


def _exact_lakatotree_git_root(root: str) -> bool | None:
    """own .git + project markers + exact top-level이면 True, git 부재면 None."""
    own_git = os.path.join(root, ".git")
    has_project_markers = (
        os.path.isfile(os.path.join(root, "pyproject.toml"))
        and os.path.isdir(os.path.join(root, "lakatos"))
    )
    if not os.path.lexists(own_git) or not has_project_markers:
        return False
    try:
        top = subprocess.run(
            ["git", "-C", root, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
    except OSError:
        return None
    except subprocess.SubprocessError:
        return False
    top_level = top.stdout.strip()
    return bool(top_level) and top.returncode == 0 and os.path.realpath(top_level) == root


def _git_head_sha(root: str) -> str:
    """검증된 LakatoTree *정확한 repo root*의 HEAD sha. 그 외에는 ``unknown``.

    ``git -C``는 대상에 ``.git``이 없어도 부모 저장소까지 올라간다. 배포 snapshot이
    SYMPOSIUM 부모 SHA를 자기 신원으로 도용하면 boot/disk가 같은 거짓 ``stale=false``가
    만들어진다. 따라서 own .git + project markers + show-toplevel exact-match를 모두
    통과한 뒤에만 HEAD를 신뢰한다.
    """
    exact_root = os.path.realpath(os.fspath(root))
    exact = _exact_lakatotree_git_root(exact_root)
    if exact is False:
        return "unknown"
    if exact is None:
        return _manual_git_head_sha(exact_root)

    try:
        out = subprocess.run(
            ["git", "-C", exact_root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
        return "unknown"
    except OSError:
        # git binary 자체가 없을 때만 own .git fallback. top-level mismatch/명령 실패는
        # fallback으로 우회시키지 않는다 — 검증 실패는 신원 부재다.
        return _manual_git_head_sha(exact_root)
    except subprocess.SubprocessError:
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
    = 코드가 갱신됐으나 프로세스 미재기동(S5 결함의 관측가능화). 신원을 검증할 수 없으면
    stale=None — 부재는 fresh(False)의 증거가 아니다.
    """
    disk = disk_head_sha()
    identity_verified = BOOT_GIT_SHA != "unknown" and disk != "unknown"
    return {
        "boot_git_sha": BOOT_GIT_SHA,
        "boot_time": BOOT_TIME,
        "disk_head_sha": disk,
        "identity_verified": identity_verified,
        "stale": (BOOT_GIT_SHA != disk) if identity_verified else None,
    }


# ── jp4 (JP 캠페인 2026-07-10): 코드경로-한정 staleness — 판관 관련 코드가 실제로 바뀌었나 ──────
#   전체 stale(boot≠disk)은 결과-아티팩트/docs 커밋에도 발화해 채점 루프를 자기차단한다. 판관
#   게이트는 lakatos/·server/ 경로의 실변경만 물어야 한다(git diff pathspec).
JUDGE_CODE_PATHS = ("lakatos", "server")
_code_paths_cache: dict = {}


def code_paths_changed(base: str, head: str, paths: tuple = JUDGE_CODE_PATHS,
                       root: str | None = None) -> bool | None:
    """base..head 사이에 판관-관련 코드경로가 바뀌었는가. True/False/None(판정불가).

    'unknown'(git 부재/tarball) 검사가 base==head 보다 *먼저* — 양쪽 다 unknown 인 동일성이
    '신선'으로 위장하지 못하게(관측 채널의 정직). 판정불가는 None(부재≠반증 — 발화는 호출측
    engine_freshness_fires 가 is True 만 문다). root seam 은 테스트(tmp git repo) 주입용."""
    if "unknown" in (base, head):
        return None
    if base == head:
        return False
    r = root or _cached_root()
    key = (r, base, head, paths)
    if key in _code_paths_cache:
        return _code_paths_cache[key]
    try:
        out = subprocess.run(
            ["git", "-C", r, "diff", "--name-only", f"{base}..{head}", "--", *paths],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None                     # base sha 미해석(rebase-drop/shallow 등) = 판정불가
    result = bool(out.stdout.strip())
    _code_paths_cache[key] = result     # (root,base,head) 불변 쌍만 캐시 — 실패(None)는 캐시 안 함
    return result
