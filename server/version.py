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


def _canonical_git_sha(value: str) -> str | None:
    candidate = value.strip()
    if (
        len(candidate) == 40
        and all(char in "0123456789abcdef" for char in candidate)
    ):
        return candidate
    return None


def _manual_git_head_sha(root: str) -> str:
    """Resolve the exact full SHA from this repository without invoking Git."""
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
            ref_name = ref.split(":", 1)[1].strip()
            if (
                not ref_name.startswith("refs/")
                or os.path.isabs(ref_name)
                or ".." in ref_name.split("/")
            ):
                return "unknown"
            common_dir = git_dir
            common_dir_file = os.path.join(git_dir, "commondir")
            if os.path.isfile(common_dir_file):
                with open(common_dir_file, encoding="utf-8") as f:
                    common_pointer = f.read().strip()
                common_dir = os.path.realpath(
                    common_pointer
                    if os.path.isabs(common_pointer)
                    else os.path.join(git_dir, common_pointer)
                )
            for ref_root in dict.fromkeys((git_dir, common_dir)):
                refpath = os.path.join(ref_root, *ref_name.split("/"))
                try:
                    with open(refpath, encoding="utf-8") as f:
                        resolved = _canonical_git_sha(f.read())
                except OSError:
                    resolved = None
                if resolved is not None:
                    return resolved
            for ref_root in dict.fromkeys((git_dir, common_dir)):
                packed_refs = os.path.join(ref_root, "packed-refs")
                try:
                    with open(packed_refs, encoding="utf-8") as f:
                        for line in f:
                            if line.startswith(("#", "^")):
                                continue
                            fields = line.rstrip("\n").split(" ", 1)
                            if len(fields) != 2 or fields[1] != ref_name:
                                continue
                            resolved = _canonical_git_sha(fields[0])
                            return resolved or "unknown"
                except OSError:
                    continue
            return "unknown"
        return _canonical_git_sha(ref) or "unknown"
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
            ["git", "-C", exact_root, "rev-parse", "--verify", "HEAD^{commit}"],
            capture_output=True, text=True, timeout=5,
        )
        resolved = _canonical_git_sha(out.stdout)
        if out.returncode == 0 and resolved is not None:
            return resolved
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
        # stale 의 referent 는 자기 박스 1-hop(프로세스 vs 자기 디스크)뿐 — canon(origin) 대비는
        # 이 프로세스가 측정하지 않는다(네트워크 없는 읽기 표면). 07-28 실측: scope 무명시 stale:false
        # 가 'canon 대비 신선'으로 오독돼 remediation 6커밋 뒤 서빙이 초록으로 위장했다. overclaim 제거:
        "stale_scope": "process_vs_disk",
        "canon_lag": "unknown",   # 대조는 외부 watchdog(P2)의 몫 — 감지 없이 신선 주장 금지
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
