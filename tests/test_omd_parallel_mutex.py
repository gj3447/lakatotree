"""OMD D-SINGULON / mutex_disjoint_orbits — glob write-set 상호배제 guard.

literature : Dijkstra/Lamport mutual exclusion (단일 임계영역·단일 락);
             Courtois readers-writers. 시판 락은 glob-overlap leasing 부재
             (etcd Txn=per-key, Spanner serializable, Consul/Redis TTL).
anomaly    : 병렬-dev의 임계영역 = "glob write-set". 소박한 prefix 탐지기는
             src/** 와 src/a.py 를 서로소로 오판 → 둘 다 HELD → 공유경로
             동시쓰기 → 머지충돌(SINGULON 분열).
problemshift: 세그먼트-단위 패턴교집합(soundness: false-negative 0)으로
             overlap⇒serialize, 입체(disjoint)일 때만 병렬.
OMD dim    : SINGULON (disjoint write-sets ⇒ merge-conflict-free).
OMD artifact corroborated:
    omd_server/disjoint.py  globs_overlap / sets_overlap
        (docstring: "절대 false-negative를 내지 않는다")
    TLA spec/omd_lease.tla  NoOverlappingHeld
        (INVARIANTS 등재: spec/omd_lease.cfg)
KG node    : OMD-finding-glob-overlap-gap

judge() 계약:
    guard_defect  = test_naive_prefix_conflict_check_misses_true_overlap_real_one_catches
        in-test로 NAIVE(=첫 와일드카드 앞 prefix 동일성) vs PRINCIPLED(=세그먼트
        패턴교집합) 두 lease-manager 를 만들어 적대 스케줄을 돌린다. NAIVE 는
        NoOverlappingHeld 안전성을 위반(겹치는 둘 다 HELD)하고 PRINCIPLED 는 유지.
        둘 다 in-test → mechanism 지우면 RED 로 뒤집힘(revert-proof by construction).
    guard_mechanism = test_omd_sets_overlap_is_sound_and_tla_checks_no_overlapping_held
        실제 omd_server/disjoint.py 를 파일경로로 로드해 soundness(겹침 배터리에
        false-negative 0)를 검증 + TLA NoOverlappingHeld 가 .tla 에 선언되고
        .cfg INVARIANTS 에 실제 체크됨을 파싱(+ bogus 이름 음성대조).
"""

from __future__ import annotations

import importlib.util
import os
import re

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# 경로 상수 (read-only; OMD 레포는 절대 수정 금지)
# ─────────────────────────────────────────────────────────────────────────────
OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
DISJOINT_PY = os.path.join(OMD_ROOT, "omd_server", "disjoint.py")
LEASE_TLA = os.path.join(OMD_ROOT, "spec", "omd_lease.tla")
LEASE_CFG = os.path.join(OMD_ROOT, "spec", "omd_lease.cfg")


# ═════════════════════════════════════════════════════════════════════════════
# guard_defect 용 in-test 최소 모델 (self-contained, revert-proof)
# ═════════════════════════════════════════════════════════════════════════════
_WILD = re.compile(r"[*?\[]")


import os as _os
import pytest as _pytest
_OMD_ROOT = _os.environ.get("OMD_ROOT", "<WORKSPACE>/PROJECT/PI/omd")
_OMD_ABSENT = not _os.path.isdir(_OMD_ROOT)
# audit un-gate: 자기완결 defect 오라클(naive-vs-fixed in-test 모델, OMD 불요)은 게이트 없이 CI 서 실행.
# OMD-의존 mechanism 오라클(disjoint import / TLA 파싱 / OMD venv subprocess)만 부재 시 skip(아래 @_skip_omd).
_skip_omd = _pytest.mark.skipif(
    _OMD_ABSENT, reason="OMD 자매 repo 미체크아웃/OMD_ROOT 미설정 — 크로스레포 mechanism 오라클(로컬/CI-checkout 시만)")

def _naive_prefix(g: str) -> str:
    """소박한 탐지기: 첫 와일드카드 *앞* 디렉토리 prefix 만 본다.
    와일드카드가 없으면 경로 전체를 prefix 로 본다(→ src/a.py 는 'src/a.py')."""
    g = g.strip().lstrip("./").rstrip("/")
    m = _WILD.search(g)
    if not m:
        return g
    head = g[: m.start()]
    return head.rsplit("/", 1)[0].rstrip("/") if "/" in head else ""


def naive_overlap(g1: str, g2: str) -> bool:
    """NAIVE 충돌판정: prefix 문자열 동일성. src/** 와 src/a.py 를 서로소로 오판."""
    return _naive_prefix(g1) == _naive_prefix(g2)


# --- PRINCIPLED 탐지기: 실제 OMD 알고리즘의 독립 in-test 재구현 ---
#     (mechanism 오라클은 실제 모듈을 임포트; 여기는 self-contained 모델이라 별도 구현)
def _seg_intersect(a: str, b: str) -> bool:
    """단일 세그먼트 두 패턴(*,?,literal)이 공통 문자열을 갖는가."""
    memo: dict = {}

    def go(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(a) and j == len(b):
            r = True
        elif i < len(a) and a[i] == "*":
            r = go(i + 1, j) or (j < len(b) and go(i, j + 1))
        elif j < len(b) and b[j] == "*":
            r = go(i, j + 1) or (i < len(a) and go(i + 1, j))
        elif i < len(a) and j < len(b):
            r = (a[i] == "?" or b[j] == "?" or a[i] == b[j]) and go(i + 1, j + 1)
        else:
            r = False
        memo[key] = r
        return r

    return go(0, 0)


def _path_intersect(A: tuple, B: tuple) -> bool:
    """세그먼트 시퀀스 두 glob 이 공통 경로를 갖는가 (** = 0+ 세그먼트)."""
    memo: dict = {}

    def go(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(A) and j == len(B):
            r = True
        elif i < len(A) and A[i] == "**":
            r = go(i + 1, j) or (j < len(B) and go(i, j + 1))
        elif j < len(B) and B[j] == "**":
            r = go(i, j + 1) or (i < len(A) and go(i + 1, j))
        elif i < len(A) and j < len(B):
            r = _seg_intersect(A[i], B[j]) and go(i + 1, j + 1)
        else:
            r = False
        memo[key] = r
        return r

    return go(0, 0)


def _norm(g: str) -> str:
    g = g.strip().lstrip("./")
    if g.endswith("/"):
        g += "**"
    return g


def principled_overlap(g1: str, g2: str) -> bool:
    """PRINCIPLED 충돌판정: 세그먼트-단위 패턴교집합(soundness)."""
    if g1 == g2:
        return True
    return _path_intersect(tuple(_norm(g1).split("/")), tuple(_norm(g2).split("/")))


class LeaseManager:
    """최소 OMD lease 코어. overlap_fn 으로 충돌판정을 주입한다.

    grant(): 현재 HELD 중 write-set 이 겹치는 게 있으면 PENDING(serialize),
             없으면 HELD. NoOverlappingHeld(겹치는 둘 다 HELD 금지)를 강제하려
             *시도*한다 — overlap_fn 이 false-negative 면 이 강제가 새어나간다."""

    def __init__(self, overlap_fn):
        self._overlap = overlap_fn
        self.held: list[tuple[str, str]] = []  # (orbit_id, write_glob)

    def _conflict(self, glob: str) -> bool:
        return any(self._overlap(g, glob) for _, g in self.held)

    def grant(self, orbit_id: str, glob: str) -> str:
        if self._conflict(glob):
            return "PENDING"
        self.held.append((orbit_id, glob))
        return "HELD"


def held_pairs_overlap(mgr: LeaseManager, truth_overlap) -> bool:
    """현재 HELD 들 사이에 *실제로* 겹치는 쌍이 있는가 (truth = 정확한 판정).
    NoOverlappingHeld 위반 = True."""
    h = mgr.held
    for i in range(len(h)):
        for j in range(i + 1, len(h)):
            if truth_overlap(h[i][1], h[j][1]):
                return True
    return False


# ═════════════════════════════════════════════════════════════════════════════
# guard_mechanism 용 실제 OMD 모듈 로더 (by FILE PATH — import omd_server 금지)
# ═════════════════════════════════════════════════════════════════════════════
def _load_real_disjoint():
    spec = importlib.util.spec_from_file_location("omd_disjoint", DISJOINT_PY)
    assert spec is not None and spec.loader is not None, f"cannot spec {DISJOINT_PY}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # stdlib-only; .core/SQLite 안 건드림
    return mod


def _invariant_declared(tla_text: str, name: str) -> bool:
    """'<Name> ==' 가 .tla 에 정의되어 있는가."""
    return re.search(rf"(?m)^\s*{re.escape(name)}\s*==", tla_text) is not None


def _invariant_checked(cfg_text: str, name: str) -> bool:
    """name 이 .cfg 의 INVARIANTS 섹션 아래에 *토큰으로* 등재되어 있는가."""
    m = re.search(r"(?ms)^\s*INVARIANTS?\s*\n(.*?)(?:\n\s*[A-Z_]+\s*\n|\Z)", cfg_text)
    if not m:
        return False
    body = m.group(1)
    return re.search(rf"(?m)^\s*{re.escape(name)}\s*$", body) is not None


# 알려진 겹침 배터리 — soundness: 실제 탐지기는 전부 True 여야(false-negative 0).
KNOWN_OVERLAPS = [
    ("src/**", "src/a.py"),
    ("a/*/c", "a/b/c"),
    ("x/**", "x/y/z"),
    ("src/", "src/deep/nested/f.py"),   # 디렉토리 선언 = 서브트리
    ("a/b/c", "a/b/c"),                 # 동일
    ("pkg/**/*.py", "pkg/mod/sub/z.py"),
]

# 알려진 서로소(입체) — false-positive 아닌지 sanity (병렬 허용).
KNOWN_DISJOINT = [
    ("src/a.py", "src/b.py"),
    ("a/**", "b/**"),
    ("x/y/z", "x/y/w"),
]


# ═════════════════════════════════════════════════════════════════════════════
# GUARD 1 (defect / negative oracle) — self-contained, revert-proof
# ═════════════════════════════════════════════════════════════════════════════
def test_naive_prefix_conflict_check_misses_true_overlap_real_one_catches():
    """NAIVE prefix 동일성 탐지기는 겹치는 write-set 을 서로소로 오판해 둘 다
    HELD → NoOverlappingHeld 위반(SINGULON 분열). PRINCIPLED 세그먼트교집합은
    overlap 을 잡아 serialize → 안전성 유지.

    revert-proof: 두 모델 모두 in-test. principled_overlap 을 naive 로 바꾸면
    아래 'fixed holds' 단언이 즉시 RED 가 된다(mechanism 의존성 진짜)."""
    # 적대 스케줄: 같은 경로 src/a.py 를 건드리는 두 task.
    #   orbit-A: 광역 write-set  "src/**"
    #   orbit-B: 구체 write-set  "src/a.py"   (genuinely overlaps A)
    schedule = [("A", "src/**"), ("B", "src/a.py")]

    # 정확(ground-truth) 판정으로 위반 여부를 측정한다.
    truth = principled_overlap
    # 이 두 glob 이 진짜 겹친다는 전제부터 못 박는다(테스트가 무의미해지지 않게).
    assert truth("src/**", "src/a.py") is True, "battery precondition: must overlap"

    # ── BROKEN(naive) ───────────────────────────────────────────────
    naive_mgr = LeaseManager(naive_overlap)
    naive_states = [naive_mgr.grant(oid, g) for oid, g in schedule]
    # naive 는 prefix('src') vs prefix('src/a.py') 가 달라 충돌을 못 봄 → 둘 다 HELD
    assert naive_states == ["HELD", "HELD"], naive_states
    naive_violates = held_pairs_overlap(naive_mgr, truth)
    assert naive_violates is True, (
        "NAIVE 가 NoOverlappingHeld 를 위반해야 한다(겹치는 둘 다 HELD = 동시쓰기)"
    )

    # ── FIXED(principled) ───────────────────────────────────────────
    fixed_mgr = LeaseManager(principled_overlap)
    fixed_states = [fixed_mgr.grant(oid, g) for oid, g in schedule]
    # principled 는 overlap 을 잡아 두 번째를 직렬화(PENDING)
    assert fixed_states == ["HELD", "PENDING"], fixed_states
    fixed_violates = held_pairs_overlap(fixed_mgr, truth)
    assert fixed_violates is False, (
        "PRINCIPLED 는 NoOverlappingHeld 를 유지해야 한다(겹치면 serialize)"
    )

    # 핵심 대비: 같은 스케줄에서 naive=위반, fixed=안전.
    assert naive_violates and not fixed_violates


# ═════════════════════════════════════════════════════════════════════════════
# GUARD 2 (mechanism / positive novel oracle) — REAL OMD artifact, independent
# ═════════════════════════════════════════════════════════════════════════════
@_skip_omd
def test_omd_sets_overlap_is_sound_and_tla_checks_no_overlapping_held():
    """실제 omd_server/disjoint.py 를 파일경로로 로드해 SOUNDNESS 를 검증:
    겹침 배터리 전부에서 globs_overlap/sets_overlap == True (false-negative 0).
    + TLA NoOverlappingHeld 가 .tla 선언 ∧ .cfg INVARIANTS 체크됨(+bogus 음성대조).

    defect 오라클과 *독립* 진리원: 거긴 in-test 모델, 여긴 실제 OMD 산출물."""
    mod = _load_real_disjoint()
    assert hasattr(mod, "globs_overlap") and hasattr(mod, "sets_overlap")

    # (1) SOUNDNESS: 알려진 겹침에 false-negative 0 -----------------------------
    missed = [(a, b) for a, b in KNOWN_OVERLAPS if not mod.globs_overlap(a, b)]
    assert missed == [], f"real globs_overlap false-negatives (unsound!): {missed}"

    # sets_overlap 도 write-set 단위로 동일하게 sound
    assert mod.sets_overlap(["src/**"], ["src/a.py"]) is True
    assert mod.sets_overlap(["docs/**", "a/*/c"], ["a/b/c"]) is True

    # (1b) 실제 탐지기가 naive 보다 *엄격히* 낫다는 증명:
    #      naive prefix 동일성은 적어도 한 쌍을 놓치고, 실제는 안 놓친다.
    naive_missed = [
        (a, b) for a, b in KNOWN_OVERLAPS if not naive_overlap(a, b)
    ]
    assert naive_missed, "naive 가 아무것도 안 놓치면 대비가 무의미 — 배터리 점검"
    for a, b in naive_missed:
        assert mod.globs_overlap(a, b) is True, (
            f"real must catch what naive misses: {a} vs {b}"
        )

    # (2) sanity: 알려진 입체(서로소)에 false-positive 아님 (병렬 허용) ----------
    for a, b in KNOWN_DISJOINT:
        assert mod.globs_overlap(a, b) is False, f"false-positive on disjoint {a} {b}"

    # (3) TLA NoOverlappingHeld: 선언 ∧ INVARIANTS 체크 -------------------------
    with open(LEASE_TLA, encoding="utf-8") as fh:
        tla = fh.read()
    with open(LEASE_CFG, encoding="utf-8") as fh:
        cfg = fh.read()

    assert _invariant_declared(tla, "NoOverlappingHeld"), "NoOverlappingHeld 미선언(.tla)"
    assert _invariant_checked(cfg, "NoOverlappingHeld"), "NoOverlappingHeld 미체크(.cfg)"

    # 음성대조: bogus 이름은 같은 파서가 거부해야(오라클 비공허성) -----------------
    bogus = "NoOverlappingHeld_BOGUS_XYZ"
    assert not _invariant_declared(tla, bogus), "parser 가 bogus 를 선언으로 오인"
    assert not _invariant_checked(cfg, bogus), "parser 가 bogus 를 체크로 오인"


# ═════════════════════════════════════════════════════════════════════════════
# 보조 회귀/음성대조 (load-bearing 아님)
# ═════════════════════════════════════════════════════════════════════════════
def test_naive_overlap_is_genuinely_blind_regression():
    """NAIVE 가 적대쌍을 못 본다는 사실을 따로 못박는다(in-test 모델 sanity)."""
    assert naive_overlap("src/**", "src/a.py") is False
    assert principled_overlap("src/**", "src/a.py") is True


@_skip_omd
def test_real_disjoint_loads_by_path_not_via_package():
    """omd_server 패키지 임포트(.core/SQLite)를 피해 파일경로 로드가 되는지."""
    mod = _load_real_disjoint()
    assert callable(mod.globs_overlap)
    # disjoint.py 는 stdlib-only — 패키지 __init__ 를 안 끌어온다
    assert mod.__name__ == "omd_disjoint"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
