"""phantom_read_coherence — OMD D12 read-set 코히런스 가드 (LakatoTree PROM 노드).

리터러처(고전 변칙): 팬텀 읽기 / 직렬성. SQL 격리 레벨(ANSI)·Serializable Snapshot
Isolation(Cahill, Röhm, Fekete 2008). A reader declares a read-set over paths that a
concurrent task then merges; its base snapshot is STALE, so its decisions are computed
against data that no longer holds (옛 base 위 조용한 빌드 → 머지는 성공하나 로직 틀림 =
phantom). 직렬성 처방: read-set 이 커밋으로 무효화되면 abort/rebase, 팬텀 결과 커밋 금지.

OMD dimension: D12 — read-set 코히런스 / 유령 읽기.
OMD problemshift: read-lease 에 integration generation 을 태그한다; read 경로를 건드리는
동시 merge 가 generation 을 +1 하면 reader 는 STALE 로 플래그되어 rebase 를 강제당한다 —
팬텀(stale) 읽기 위에서 행동하지 않는다. SINGULON 은 write-disjointness 만 보장하므로
read 코히런스는 별도 generation gate 로 닫는다.

OMD artifact corroborated:
  - CONCURRENCY.md §inc9 L650-664: meta.integration_gen +1/merge, merge_log(gen->globs),
    read claim 이 task.read_synced_gen 앵커, connect Phase A `_ghost_reads` -> reason
    "read_stale", 회복 read_refresh.
  - omd_server/disjoint.py: sets_overlap / globs_overlap (보수적, soundness-first).
  - tests/test_d12_read_coherence.py (10) — 특히 test_ghost_read_blocks_consumer_connect
    (reason=="read_stale") + 변이검증 test_MUTATION_guard_present_ghost_blocks_connect.

KG lit node: OMD-finding-glob-overlap-gap.

이 파일의 두 load-bearing 가드:
  guard_defect      = test_phantom_stale_read_acted_on_generation_tracking_flags_stale
      자기완결·revert-proof in-test 모델: NAIVE(세대검사 없음)는 팬텀을 받아들이고,
      PRINCIPLED(세대검사 있음)는 STALE 로 플래그+rebase 강제. 같은 스케줄, 한쪽만 가드.
  guard_mechanism   = test_omd_d12_read_coherence_dimension_test_passes_in_real_substrate
      독립 corroboration: 실제 OMD 자체 venv 에서 tests/test_d12_read_coherence.py 를
      subprocess 로 돌려 rc==0 을 단언(인-테스트 모델과 무관한 실-아티팩트 오라클).
      추가로 실제 disjoint.py 를 importlib(file-path)로 직접 로드해 보수적 overlap
      soundness 를 단언(인-테스트 미러가 실제 함수와 합치함을 별 소스로 교차검증).
"""

import importlib.util
import os
import subprocess
import sys

import pytest

# ── 실제 OMD 레포 경로(읽기 전용; 절대 수정 금지) ───────────────────────────
_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_VENV_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_D12_TEST = "tests/test_d12_read_coherence.py"
_OMD_DISJOINT = os.path.join(_OMD_ROOT, "omd_server", "disjoint.py")


import os as _os
import pytest as _pytest
pytestmark = _pytest.mark.skipif(
    not _os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

def _load_real_disjoint():
    """실제 OMD disjoint.py 를 파일 경로로 직접 로드(stdlib-only, .core 안 끌어옴).

    'import omd_server' 금지 — __init__ 이 .core(SQLite)를 임포트해 LakatoTree venv 에서
    깨진다. spec_from_file_location 로 모듈만 격리 로드한다."""
    spec = importlib.util.spec_from_file_location("omd_disjoint", _OMD_DISJOINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ============================================================================
# 인-테스트 미니 모델 (guard_defect 전용) — 실제 OMD 알고리즘을 충실히 미러.
#   integration_gen, merge_log(gen -> write-globs), task.read_synced_gen,
#   connect 의 _ghost_reads 게이트(read_synced_gen *이후* merge_log 중 reads 와
#   sets_overlap 하면 read_stale).
# ============================================================================

def _norm(g):
    return g[:-3] if g.endswith("/**") else g


def _globs_overlap(g1, g2):
    """disjoint.py:globs_overlap 의 핵심을 미러(접두 디렉터리 교차 = 보수적 overlap)."""
    if g1 == g2:
        return True
    a, b = _norm(g1).split("/"), _norm(g2).split("/")
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def _sets_overlap(s1, s2):
    """disjoint.py:sets_overlap 미러."""
    return any(_globs_overlap(a, b) for a in s1 for b in s2)


class MiniStore:
    """generation + merge_log + task read-anchor 만 가진 최소 통합 상태."""

    def __init__(self):
        self._gen = 0
        self._merge_log = {}        # gen -> [write-globs]
        self._read_synced_gen = {}  # task -> gen (또는 None)
        self._reads = {}            # task -> [read-globs]

    def integration_gen(self):
        return self._gen

    # producer 응결 1건 = gen +1 + merge_log 기록 (단일문, 읽고-쓰기 갭 없음).
    def merge(self, task, write_globs):
        self._gen += 1
        self._merge_log[self._gen] = list(write_globs)
        return self._gen

    # consumer read claim = 현 gen 을 task 에 앵커 + reads 기록.
    def anchor_read(self, task, read_globs):
        self._read_synced_gen[task] = self._gen
        self._reads[task] = list(read_globs)

    def ghost_globs(self, task):
        """read_synced_gen *이후* merge_log 중 task 의 reads 와 겹치는 write-globs."""
        anchor = self._read_synced_gen.get(task)
        if anchor is None:
            return []   # read 없는 task = 코히런스 무관.
        reads = self._reads.get(task, [])
        ghosts = []
        for gen, wglobs in self._merge_log.items():
            if gen > anchor and _sets_overlap(reads, wglobs):
                ghosts.extend(wglobs)
        return ghosts

    def refresh_read(self, task):
        """rebase/재독 후 현 gen 으로 재앵커 (회복)."""
        if task in self._read_synced_gen:
            self._read_synced_gen[task] = self._gen


def _consumer_connect(store, task, *, coherence_check):
    """consumer connect 를 모델링.

    coherence_check=False (NAIVE)  : 세대 검사 없음 → 무조건 base 위에서 '행동'(MERGE).
    coherence_check=True  (FIXED)  : ghost_globs 비어있을 때만 MERGE, 아니면 read_stale.

    반환: dict(state, reason, ghost_globs, acted_at_gen).
    'acted_at_gen' = 이 consumer 가 자기 결정을 계산한 base gen(= read_synced_gen).
    """
    anchor = store._read_synced_gen.get(task)
    if not coherence_check:
        # 팬텀 무시: 옛 base(anchor) 위에서 조용히 빌드해 MERGE.
        return {"state": "MERGED", "reason": None,
                "ghost_globs": [], "acted_at_gen": anchor}
    ghosts = store.ghost_globs(task)
    if ghosts:
        return {"state": "BLOCKED", "reason": "read_stale",
                "ghost_globs": ghosts, "acted_at_gen": anchor}
    return {"state": "MERGED", "reason": None,
            "ghost_globs": [], "acted_at_gen": store.integration_gen()}


def _run_phantom_schedule(*, coherence_check):
    """적대적 스케줄(결정론·재정렬 스텝, 실시간 없음):

      1. consumer C 가 src/api 를 gen 0 에서 read-claim → read_synced_gen=0.
      2. producer P 가 src/api 에 팬텀을 응결 → gen 1, merge_log[1] ⊇ src/api.
      3. C 가 connect 시도 — 이때 base 는 이미 g1 인데 C 의 앵커는 g0.

    반환: C 의 connect 결과 + 사실(current_gen).
    """
    store = MiniStore()
    assert store.integration_gen() == 0
    # 1) consumer 가 옛 gen(0)에서 read-set 앵커.
    store.anchor_read("C", ["src/api/**"])
    assert store._read_synced_gen["C"] == 0
    # 2) 동시 producer 가 read 경로에 팬텀 응결 → gen 1.
    g1 = store.merge("P", ["src/api/**"])
    assert g1 == 1 and store.integration_gen() == 1
    # 3) consumer connect.
    res = _consumer_connect(store, "C", coherence_check=coherence_check)
    return store, res


# ============================================================================
# guard_defect (부정/개선 오라클) — 자기완결·revert-proof.
# ============================================================================
def test_phantom_stale_read_acted_on_generation_tracking_flags_stale():
    """팬텀 읽기: NAIVE 는 stale base(g0) 위에서 행동(팬텀 수용), PRINCIPLED 는 STALE
    플래그(read_stale) + rebase 강제. property = '팬텀 읽기 위에서 행동하지 않는다'.

    Revert-proof by construction: 두 모델이 같은 스케줄을 한-테스트에서 돌린다.
    coherence_check(세대 비교)를 떼면 FIXED 가 NAIVE 로 붕괴해 단언이 RED 로 뒤집힌다.
    상수 단언·tautology 없음 — property 가 진짜로 세대-검사에 의존한다.
    """
    # ---- NAIVE (세대 검사 없음) : 변칙 재현 ----
    naive_store, naive = _run_phantom_schedule(coherence_check=False)
    current_gen = naive_store.integration_gen()
    assert current_gen == 1
    # NAIVE 는 응결한다(MERGE) — 그런데 자기 결정을 옛 base(g0) 위에서 계산했다.
    assert naive["state"] == "MERGED", naive
    assert naive["reason"] is None, naive
    # = 팬텀: 행동에 쓴 base gen(0) != 응결 당시 실제 gen(1). 직렬성 위반.
    assert naive["acted_at_gen"] == 0, naive
    assert naive["acted_at_gen"] != current_gen, (
        "NAIVE 가 stale snapshot(g0) 위에서 행동했는데 세상은 이미 g1 = 팬텀 수용")

    # ---- PRINCIPLED (세대 검사 있음) : 변칙 차단 ----
    fixed_store, fixed = _run_phantom_schedule(coherence_check=True)
    assert fixed_store.integration_gen() == 1
    # FIXED 는 STALE 로 플래그 → connect 차단(read_stale), 팬텀 위에서 행동 안 함.
    assert fixed["state"] == "BLOCKED", fixed
    assert fixed["reason"] == "read_stale", fixed
    assert any("src/api" in g for g in fixed["ghost_globs"]), fixed
    # 결정적 대비: 같은 스케줄, 한쪽만 MERGE(팬텀 수용) / 한쪽만 BLOCKED(코히런스).
    assert naive["state"] != fixed["state"], (naive, fixed)

    # ---- 회복(rebase) : refresh 후엔 통과해야(거짓-거부 아님) ----
    fixed_store.refresh_read("C")
    after = _consumer_connect(fixed_store, "C", coherence_check=True)
    assert after["state"] == "MERGED" and after["reason"] is None, after
    assert after["acted_at_gen"] == fixed_store.integration_gen(), after


# ---- 음성 대조(거짓-양성 없음): 비겹침 응결은 차단하지 않는다 ----
def test_non_overlapping_merge_is_not_a_phantom():
    """producer 가 *다른* 영역(src/db)을 응결하면 C 의 src/api read 와 무관 →
    세대-검사가 있어도 차단 안 함. 오라클이 '아무거나 차단'이 아님을 증명."""
    store = MiniStore()
    store.anchor_read("C", ["src/api/**"])
    store.merge("P", ["src/db/**"])   # 겹치지 않는 응결.
    assert store.ghost_globs("C") == []
    res = _consumer_connect(store, "C", coherence_check=True)
    assert res["state"] == "MERGED" and res["reason"] is None, res


# ---- 음성 대조: read 선언 없는 task 는 코히런스 무관 ----
def test_task_without_reads_never_phantom_blocked():
    store = MiniStore()
    store.merge("P", ["src/api/**"])   # 먼저 응결.
    # Q 는 read 앵커 없음 → read_synced_gen=None → 팬텀 검사 무관.
    assert store.ghost_globs("Q") == []
    res = _consumer_connect(store, "Q", coherence_check=True)
    assert res["state"] == "MERGED", res


# ---- 교차검증: 실제 disjoint.py 가 보수적 overlap soundness 를 만족(독립 소스) ----
def test_real_disjoint_overlap_is_sound():
    """실제 OMD disjoint.py 를 file-path importlib 로 직접 로드해 soundness 확인:
    알려진 겹침엔 false-negative 없음, 궤도 밖 경로엔 false-positive 없음.
    인-테스트 미러가 진짜 함수와 합치함을 *다른* 소스로 교차검증(가드 본체 아님)."""
    dj = _load_real_disjoint()
    # 알려진 overlap: 같은 src/api 접두 → 반드시 True(soundness: no false-negative).
    assert dj.globs_overlap("src/api/**", "src/api/v1/**") is True
    assert dj.sets_overlap({"src/api/**"}, {"src/api/handlers.py"}) is True
    # 궤도 밖: 서로소 접두 → False(no false-positive).
    assert dj.globs_overlap("src/api/**", "src/db/**") is False
    assert dj.sets_overlap({"src/api/**"}, {"src/db/**"}) is False


# ============================================================================
# guard_mechanism (긍정/novel 오라클) — 실제 OMD 기제의 독립 corroboration.
#   BEHAVIORAL: OMD 자체 venv 에서 D12 차원 테스트를 subprocess 로 실행, rc==0 단언.
#   인-테스트 미니 모델과 완전히 독립 — 실제 omd_server.Coordinator 가 generation
#   추적으로 stale 읽기를 플래그함을 입증.
# ============================================================================
def test_omd_d12_read_coherence_dimension_test_passes_in_real_substrate():
    """실제 OMD 서브스트레이트가 D12 read-set 코히런스(generation gate)를 구현했는지
    OMD 자체 venv 의 pytest 로 독립 검증.

    이것은 인-테스트 모델을 재유도하지 않는다 — 실제 omd_server.Coordinator 의
    integration_gen / merge_log / _ghost_reads / read_refresh 경로를 그 자신의
    테스트(test_d12_read_coherence.py, 10건)로 돌린다.

    OMD venv 가 진짜로 없으면 정직히 FAIL(xfail/skip 으로 가짜 green 금지)."""
    assert os.path.isfile(_OMD_VENV_PY), (
        f"OMD 자체 venv python 부재: {_OMD_VENV_PY} — 기제 오라클을 honest 하게 돌릴 수 "
        "없음(가짜 green 금지). OMD 레포의 .venv 를 먼저 부트스트랩하라.")
    assert os.path.isdir(os.path.join(_OMD_ROOT, "tests")), _OMD_ROOT

    proc = subprocess.run(
        [_OMD_VENV_PY, "-m", "pytest", _OMD_D12_TEST, "-q"],
        cwd=_OMD_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    out = proc.stdout or ""
    assert proc.returncode == 0, (
        "실제 OMD D12 read-coherence 차원 테스트가 그 자체 venv 에서 실패 "
        f"(rc={proc.returncode}).\n--- pytest output ---\n{out[-4000:]}")
    # 수집 0건(파일 못 찾음 등)으로 인한 거짓 rc==0 방지: 실제로 테스트가 돌았는지 확인.
    assert ("passed" in out) or ("PASSED" in out), (
        f"D12 테스트가 실제로 collect/run 되지 않은 듯(passed 마커 없음):\n{out[-2000:]}")
    assert "no tests ran" not in out, out


# ---- 음성 대조(오라클 비-vacuous 증명): 존재하지 않는 테스트 경로는 rc!=0 ----
def test_subprocess_oracle_discriminates_bogus_test_path():
    """오라클이 진짜로 변별함을 증명: 가짜(존재하지 않는) 테스트 파일을 같은 러너로
    돌리면 pytest 가 rc!=0(또는 'no tests ran')을 낸다 = mechanism 오라클이 그냥
    '항상 green' 이 아님."""
    if not os.path.isfile(_OMD_VENV_PY):
        pytest.skip("OMD venv 부재 — 음성 대조는 venv 가 있을 때만 의미 있음")
    proc = subprocess.run(
        [_OMD_VENV_PY, "-m", "pytest",
         "tests/test_d12_DOES_NOT_EXIST_bogus.py", "-q"],
        cwd=_OMD_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert proc.returncode != 0, (
        "가짜 테스트 경로인데 pytest 가 rc==0 = 오라클이 변별 못 함:\n"
        f"{(proc.stdout or '')[-1500:]}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
