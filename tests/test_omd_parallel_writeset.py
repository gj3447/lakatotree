"""PROM guard — OMD §D10 write-set 파일시스템 강제 (writeset_fs_soundness).

문헌(고전 결과): glob/패턴 **포함(matching) soundness** — fnmatch 의 `*` 는 경로 구분자 `/`
를 가로지른다(POSIX fnmatch w/o FNM_PATHNAME; Python `fnmatch.fnmatch` 도 동일, `*`→`.*`).
따라서 "구체 경로가 claim 된 glob write-set 에 덮이나"를 **느슨한(loose) 매처**로 판정하면
*거짓-덮임(false-positive)* 이 나고, **궤도 밖(out-of-orbit) 쓰기**가 "덮였다"로 잘못 통과한다.
char-class `[...]` 보수(conservative) 처리도 같은 over-report 를 낸다. 이는 capability-confinement
/ separation-of-write-orbits 의 고전적 안전성 위반(= 권한 누수, "ambient authority" 함정;
Saltzer-Schroeder least-privilege, fail-safe defaults).

OMD 차원: **D10** — write-set FS 강제 (SINGULON 토대 (c) "최대 구멍": 궤도는 advisory 라
`git add -A` 가 worktree 전체를 응결 → 분열). connect Phase-A 감사는 diff 의 모든 경로가
claimed write-set 에 **정확히** 덮이는지 본다. 덮이지 않으면 `writeset_violation`, **미머지**.

코로보레이트 OMD 아티팩트: <WORKSPACE>/PROJECT/PI/omd/omd_server/disjoint.py
  - path_matches_glob(glob, path)  : disjoint.py:114  (정확 세그먼트 매칭, `**`=0+ 세그먼트)
  - path_in_globs(path, globs)     : disjoint.py:135  (감사용 — soundness: 거짓-덮임 금지)
  대비축: globs_overlap (disjoint.py:86) 은 claim 입체검사용이라 char-class 에 **보수적 True**
  (over-report 안전: 병렬도만 손해). 감사는 정반대 — over-report = 궤도밖 쓰기 통과 = 분열.

KG: LakatosTree_OOPTDD_20260616 / node writeset_fs_soundness (D10).

두 가드는 서로 다른 진리원천을 측정한다:
  guard_defect    = self-contained naive(loose) vs fixed(segment-exact) 모델 — revert-proof.
  guard_mechanism = REAL OMD disjoint.py 를 파일경로로 import 해 path_in_globs 의 정확성 검증
                    + 궤도밖 경로에 거짓-덮임 없음(negative control 로 비공허 입증).
"""

from __future__ import annotations

import fnmatch
import importlib.util
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# guard_defect 용 self-contained 모델 (OMD 미참조 — 독립 진리원천)
# ─────────────────────────────────────────────────────────────────────────────


import os as _os
import pytest as _pytest
pytestmark = _pytest.mark.skipif(
    not _os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

def _naive_covered(path: str, globs) -> bool:
    """LOOSE(naive) 포함 판정 — `fnmatch.fnmatch` 직접. `*`/char-class 가 `/` 를 가로지르고
    보수적으로 덮임을 over-report 한다 (= 고전적 false-positive 결함)."""
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _seg_match_exact(pat: str, seg: str) -> bool:
    """단일 세그먼트(슬래시 없음) 정확 매칭. fnmatchcase 는 세그먼트 안에서만 동작."""
    return fnmatch.fnmatchcase(seg, pat)


def _fixed_covered(path: str, globs) -> bool:
    """FIXED(principled) 포함 판정 — 세그먼트 단위 정확 매칭, `**`=0+ 세그먼트.
    disjoint.py 와 *독립* 으로 in-test 재구현(소스 미import). soundness: 거짓-덮임 금지."""

    def matches(glob: str, p: str) -> bool:
        g = glob.strip().lstrip("./")
        if g.endswith("/"):
            g += "**"
        G = tuple(g.split("/"))
        P = tuple(p.strip().lstrip("./").split("/"))
        memo: dict = {}

        def go(i: int, j: int) -> bool:
            if (i, j) in memo:
                return memo[(i, j)]
            if i == len(G):
                r = j == len(P)
            elif G[i] == "**":
                r = go(i + 1, j) or (j < len(P) and go(i, j + 1))
            elif j < len(P) and _seg_match_exact(G[i], P[j]):
                r = go(i + 1, j + 1)
            else:
                r = False
            memo[(i, j)] = r
            return r

        return go(0, 0)

    return any(matches(g, path) for g in globs)


def _audit_admits_orphan(covered_fn, claimed_globs, written_paths) -> bool:
    """connect Phase-A 감사 모델: 쓰여진 경로 중 claimed write-set 에 안 덮인(궤도 밖)이 있으면
    위반→거부. 감사가 위반을 *놓치고* 통과시키면(=orphan 머지) True (분열, §D10)."""
    orphans = [p for p in written_paths if not covered_fn(p, claimed_globs)]
    # 감사가 모든 경로를 '덮였다'고 보면 orphans=[] → 위반 미검출 → merge 허용 → 분열.
    return len(orphans) == 0 and any(
        not _fixed_covered(p, claimed_globs) for p in written_paths
    )


# ─────────────────────────────────────────────────────────────────────────────
# guard_mechanism 용 REAL OMD disjoint.py 로더 (BY FILE PATH — import omd_server 금지)
# ─────────────────────────────────────────────────────────────────────────────

_DISJOINT_PATH = "<WORKSPACE>/PROJECT/PI/omd/omd_server/disjoint.py"


def _load_omd_disjoint():
    """실 OMD disjoint.py 를 파일경로로 로드(stdlib-only, .core/SQLite 미끌림).
    `import omd_server` 는 __init__→.core→SQLite 로 LakatoTree venv 에서 깨지므로 금지."""
    assert Path(_DISJOINT_PATH).is_file(), f"OMD artifact missing: {_DISJOINT_PATH}"
    spec = importlib.util.spec_from_file_location("omd_disjoint", _DISJOINT_PATH)
    assert spec and spec.loader, "spec load failed"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═════════════════════════════════════════════════════════════════════════════
# guard_defect — 음성/개선 오라클 (revert-proof by construction)
# ═════════════════════════════════════════════════════════════════════════════
def test_loose_overlap_admits_orphan_write_exact_path_in_globs_rejects():
    """NAIVE(loose) 감사는 궤도 밖 orphan 쓰기를 '덮였다'로 통과(분열)시키고, FIXED(segment-exact)
    감사는 이를 거부한다. 안전성 property 가 메커니즘(정확 매칭)에 *진짜로* 의존하므로 revert-proof:
    메커니즘을 빼고 naive 로 돌리면 단언이 RED 로 뒤집힌다.

    적대 스케줄: agent 가 write-orbit `a/*` (한 레벨) 만 claim 하고, 궤도 밖 2-레벨
    경로 `a/sub/deep.py`, `a/secret/conf.py` 를 worktree 에 쓴다. 느슨한 fnmatch 는 `*` 가
    `/` 를 가로질러 이 경로들을 '덮였다' 거짓-덮임으로 통과시킨다(FNM_PATHNAME 미적용 결함)."""
    claimed = ["a/*"]                       # 한 세그먼트 한정 write-orbit
    # 적대 입력: claim 에 *실제로는* 안 덮이는 궤도 밖(2-레벨, `/`-가로지르기) 경로.
    orphan_1 = "a/sub/deep.py"              # `a/*` 는 한 세그먼트 — sub/deep 은 궤도 밖
    orphan_2 = "a/secret/conf.py"           # 동
    written = ["a/x.py", orphan_1, orphan_2]  # a/x.py 는 합법(`a/*` 궤도 안)

    # ── (방어적) 적대 경로가 정말 궤도 밖인지 ground-truth 로 확인 ──
    assert _fixed_covered(orphan_1, claimed) is False
    assert _fixed_covered(orphan_2, claimed) is False
    assert _fixed_covered("a/x.py", claimed) is True  # 합법 경로는 덮임

    # ── NAIVE(loose) 모델: orphan 을 덮였다고 over-report → 감사 통과 → 분열 ──
    assert _naive_covered(orphan_1, claimed) is True   # fnmatch `*` 가 `/` 가로지름
    assert _naive_covered(orphan_2, claimed) is True   # 동
    naive_admits = _audit_admits_orphan(_naive_covered, claimed, written)
    assert naive_admits is True, "NAIVE 감사가 궤도밖 쓰기를 막아버림 — 결함 재현 실패"

    # ── FIXED(principled) 모델: orphan 을 안 덮였다고 정확 판정 → 감사 거부 → 불변 ──
    assert _fixed_covered(orphan_1, claimed) is False
    fixed_admits = _audit_admits_orphan(_fixed_covered, claimed, written)
    assert fixed_admits is False, "FIXED 감사가 분열을 통과시킴 — 메커니즘 무효"

    # property 가 메커니즘에 의존: naive≠fixed 여야 revert-proof.
    assert naive_admits != fixed_admits


# ═════════════════════════════════════════════════════════════════════════════
# guard_mechanism — 양성/novel 오라클 (REAL OMD disjoint.py, 독립 진리원천)
# ═════════════════════════════════════════════════════════════════════════════
def test_omd_path_in_globs_is_exact_no_false_positive_on_out_of_orbit():
    """실 OMD substrate 가 정확(soundness) write-set 감사 매처를 *실제로* 구현하는지 코로보레이트.
    in-test 모델을 재사용하지 않고 disjoint.py 를 파일경로로 import 해 path_in_globs/
    path_matches_glob 을 직접 구동한다.

    검증:
      (A) 거짓-덮임 없음: 궤도 밖 경로(`a/sub/deep.py`∉`a/*`, `a/z.py`∉`a/[xy].py`)는 False.
      (B) 거짓-누락 없음: 진짜 덮인 경로(`a/x.py`∈`a/**`, `a/x.py`∈`a/[xy].py`)는 True.
      (negative control) 매처가 공허하지 않음 — 명백히 덮인 경로엔 True, 궤도 밖엔 False 로
          *판별* 한다(둘 다 True/둘 다 False 면 오라클 무의미)."""
    mod = _load_omd_disjoint()
    path_in_globs = mod.path_in_globs
    path_matches_glob = mod.path_matches_glob

    # (A) soundness — 궤도 밖에 거짓-덮임 금지. 이게 naive fnmatch 와 갈리는 지점.
    assert path_in_globs("a/sub/deep.py", ["a/*"]) is False         # `*` 가 `/` 안 가로지름
    assert path_in_globs("a/z.py", ["a/[xy].py"]) is False          # char-class 정확(z 제외)
    assert path_matches_glob("a/[xy].py", "a/z.py") is False
    assert path_matches_glob("a/*", "a/sub/deep.py") is False

    # (B) completeness — 진짜 덮인 경로는 놓치지 않음.
    assert path_in_globs("a/x.py", ["b/**", "a/**"]) is True
    assert path_in_globs("a/x.py", ["a/[xy].py"]) is True
    assert path_matches_glob("a/**", "a/sub/deep.py") is True       # `**`=0+ 세그먼트

    # negative control — 오라클이 판별력 있음(비공허): 같은 매처가 덮임/궤도밖을 *다르게* 답함.
    covered = path_in_globs("a/x.py", ["a/[xy].py"])
    out_of_orbit = path_in_globs("a/z.py", ["a/[xy].py"])
    assert covered is True and out_of_orbit is False
    assert covered != out_of_orbit, "매처가 모든 입력에 같은 답 — 공허(vacuous) 오라클"


# ─────────────────────────────────────────────────────────────────────────────
# 추가 회귀/negative-control (load-bearing 아님)
# ─────────────────────────────────────────────────────────────────────────────
def test_negative_control_real_matcher_rejects_bogus_out_of_orbit_path():
    """실 disjoint.py 매처가 완전히 무관한 경로(`zzz/elsewhere.py`)를 어떤 a-궤도 glob 에도
    덮이지 않는다고 거부 — 오라클이 bogus 입력을 통과시키지 않음을 입증."""
    mod = _load_omd_disjoint()
    assert mod.path_in_globs("zzz/elsewhere.py", ["a/**", "a/*", "a/[xy].py"]) is False
    # 그러나 명백히 덮이는 경로는 통과시킴(완전성) — 항상-False 매처가 아님.
    assert mod.path_in_globs("a/deep/nested/x.py", ["a/**"]) is True


def test_in_test_fixed_model_matches_real_omd_on_audit_cases():
    """독립성 교차검증: in-test FIXED 모델과 실 OMD path_in_globs 가 핵심 감사 케이스에서 *일치*
    (두 오라클이 같은 진리를 서로 다른 코드로 증언). 단, 측정 출처는 분리되어 있다."""
    mod = _load_omd_disjoint()
    cases = [
        ("a/sub/deep.py", ["a/*"]),
        ("a/z.py", ["a/[xy].py"]),
        ("a/x.py", ["a/**"]),
        ("a/x.py", ["a/[xy].py"]),
        ("zzz/x.py", ["a/**"]),
    ]
    for path, globs in cases:
        assert _fixed_covered(path, globs) is mod.path_in_globs(path, globs), (path, globs)
