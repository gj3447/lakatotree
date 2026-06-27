"""PROM guard — fencing_token_vs_ttl  (D6 fencing / TLA UniqueLiveFence + NoEnabledStaleMutate).

문헌 anomaly (lit):
  Kleppmann, "How to do distributed locking" (2016). 순수 TTL lease 는 안전하지 않다:
  lease 가 만료된(그러나 GC pause/네트워크 지연으로 멈춰 있던) 프로세스가 깨어나 write 하면
  이미 다른 소유자가 잡은 상태를 덮어쓴다(lost update). HBase 가 정확히 이 버그를 겪었고,
  Redlock 은 fencing 이 없어 같은 결함을 가진다. 처방 = lease 와 함께 발급되는 monotone
  FENCING TOKEN; 자원은 지금까지 본 최고 token 보다 낮은 token 의 write 를 거부한다.

OMD problemshift (story):
  OMD 의 모든 lease(orbit)는 monotone fence(acquire revision)를 들고 다닌다. merge/CONNECT
  게이트가 fencing 강제 지점이다 — lease 가 만료·회수된 멈춘 droplet 은, 자신이 캡처한 fence 가
  현재 소유자 대비 stale 이므로 merge 할 수 없다. 즉 OMD 는 TTL 단독이 아니라 fence-on-lease 로
  Kleppmann anomaly 를 닫는 progressive 한 problemshift 를 한다.

OMD dimension: D6 fencing.
OMD artifact corroborated (real, model-checked):
  - spec/omd_lease.tla   UniqueLiveFence ==   (live lease 들은 서로 다른 monotone fence)
        → spec/omd_lease.cfg INVARIANTS 에 UniqueLiveFence 등재(model-checked).
  - spec/omd_leader.tla  NoEnabledStaleMutate == (stale-epoch coordinator 는 Mutate 불가)
        → spec/omd_leader.cfg INVARIANTS 에 NoEnabledStaleMutate 등재(model-checked).
  실 알고리즘: omd_lease.tla 의 orbitFence / nextFence (acquire 마다 nextFence 증가, EXCEPT 로
  orbit 에 부여) — in-test 모델은 이 monotone 발급을 충실히 미러한다.

KG lit node: OMD-finding-fencing-required.

oracle_kind: tla (구조적 — TLC/java 없음, .tla 선언 + .cfg INVARIANTS 등재 + bogus 음성통제).
"""

from __future__ import annotations

import os
import re

# ── 실 OMD spec 경로 (read-only) ────────────────────────────────────────────
OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
SPEC_DIR = os.path.join(OMD_ROOT, "spec")
LEASE_TLA = os.path.join(SPEC_DIR, "omd_lease.tla")
LEASE_CFG = os.path.join(SPEC_DIR, "omd_lease.cfg")
LEADER_TLA = os.path.join(SPEC_DIR, "omd_leader.tla")
LEADER_CFG = os.path.join(SPEC_DIR, "omd_leader.cfg")

# TLC .cfg 의 섹션 키워드 (INVARIANTS 블록의 끝을 잡기 위함)
_CFG_SECTIONS = {
    "CONSTANTS", "CONSTANT", "SPECIFICATION", "SPECIFICATIONS",
    "INVARIANT", "INVARIANTS", "PROPERTY", "PROPERTIES",
    "CONSTRAINT", "CONSTRAINTS", "ACTION_CONSTRAINT", "ACTION_CONSTRAINTS",
    "INIT", "NEXT", "SYMMETRY", "VIEW", "CHECK_DEADLOCK", "ALIAS",
    "POSTCONDITION",
}


# ════════════════════════════════════════════════════════════════════════════
#  DEFECT 모델 (self-contained, revert-proof) — 순수 TTL vs fencing token
# ════════════════════════════════════════════════════════════════════════════
class Resource:
    """공유 자원: 마지막 write 한 값과 (fencing 시) 지금까지 본 최고 token 을 보관."""

    def __init__(self) -> None:
        self.value = None          # 마지막으로 커밋된 write
        self.highest_token = 0     # fencing 강제용 — 본 적 있는 최고 token

    def write(self, value, token, *, enforce_fence: bool) -> bool:
        """write 시도. enforce_fence=True 면 stale(낮은) token 을 거부.

        반환: True=커밋됨, False=거부됨.
        enforce_fence=False 가 정확히 'token 검사를 떼낸' naive 동작(revert-proof toggle).
        """
        if enforce_fence and token < self.highest_token:
            return False  # stale fence — Kleppmann 의 fencing 거부
        if token > self.highest_token:
            self.highest_token = token
        self.value = value
        return True


import os as _os
import pytest as _pytest
pytestmark = _pytest.mark.skipif(
    not _os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

def _run_gc_pause_schedule(*, enforce_fence: bool):
    """Kleppmann GC-pause 스케줄을 결정론적 step 재배열로 구동.

    fence 발급은 omd_lease.tla 의 nextFence(monotone++) 를 미러한다:
      A 가 acquire → fence 1,  B 가 (만료 후) acquire → fence 2.
    'GC pause'/'crash'/'delay' 는 실시간이 아니라 명시적 step 순서로 모델링.
    반환: 최종 자원 값.
    """
    res = Resource()
    next_fence = 1  # monotone fence 발급기 (omd_lease.tla nextFence)

    # step 1: client A 가 lease 획득 → fence 1 캡처
    fence_A = next_fence
    next_fence += 1

    # step 2: A 가 'GC pause' (held-but-stale). 아직 아무 write 안 함.
    #   (실시간 sleep 아님 — 단지 write step 을 뒤로 재배열한 것)

    # step 3: A 의 lease 가 만료, client B 가 새로 acquire → fence 2 캡처
    fence_B = next_fence
    next_fence += 1

    # step 4: B 가 정당하게 write (B 가 현재 소유자)
    res.write("B", fence_B, enforce_fence=enforce_fence)

    # step 5: A 가 pause 에서 깨어나 stale lease 로 write 시도 (fence 1)
    res.write("A", fence_A, enforce_fence=enforce_fence)

    return res.value


# ════════════════════════════════════════════════════════════════════════════
#  TLA 구조 oracle 헬퍼 — 선언 + cfg INVARIANTS 등재 파서
# ════════════════════════════════════════════════════════════════════════════
def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def declared_in_tla(tla_text: str, name: str) -> bool:
    """`<Name> ==` 가 .tla 에 정의되어 있는가 (줄 시작, 연산자 정의)."""
    pat = re.compile(r"^\s*" + re.escape(name) + r"\s*==", re.MULTILINE)
    return pat.search(tla_text) is not None


def invariant_checked_in_cfg(cfg_text: str, name: str) -> bool:
    """INVARIANTS 섹션 아래에 `name` 이 실제로 등재되어 model-check 되는가."""
    lines = cfg_text.splitlines()
    in_block = False
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        # 주석 줄(\* …)은 무시
        if stripped.startswith("\\*"):
            continue
        first_tok = stripped.split()[0]
        if not in_block:
            if first_tok in ("INVARIANT", "INVARIANTS"):
                in_block = True
                # 같은 줄에 인라인으로 이름이 올 수도 있음: "INVARIANTS Foo Bar"
                rest = stripped.split()[1:]
                if name in rest:
                    return True
            continue
        # 블록 안: 새 섹션 키워드를 만나면 종료
        if first_tok in _CFG_SECTIONS:
            break
        # 이 줄들의 토큰이 곧 invariant 이름
        if name in stripped.split():
            return True
    return False


# ════════════════════════════════════════════════════════════════════════════
#  guard_defect — 음성/개선 oracle (revert-proof in-test 데모)
# ════════════════════════════════════════════════════════════════════════════
def test_pure_ttl_lease_admits_stale_write_fencing_token_rejects_it():
    """순수 TTL lease 는 stale write 를 허용(clobber), fencing token 은 거부.

    안전 property: GC-pause 스케줄이 끝나면 자원의 값은 *현재 합법 소유자* B 의 것이어야 한다.
    A 는 lease 가 만료·회수된 뒤 깨어난 stale writer 이므로 그의 write 가 살아남으면 안 된다.
    """
    # naive 순수 TTL (token 검사 없음): A 가 B 를 덮어씀 → lost update (안전성 위반)
    naive_final = _run_gc_pause_schedule(enforce_fence=False)
    assert naive_final == "A", (
        "순수 TTL 모델이 Kleppmann anomaly 를 재현해야 한다: stale A 가 B 를 clobber"
    )

    # fenced (monotone token 검사): A 의 fence(1) < highest(2) → 거부, B 가 살아남음
    fenced_final = _run_gc_pause_schedule(enforce_fence=True)
    assert fenced_final == "B", (
        "fencing token 모델은 stale A 를 거부하고 합법 소유자 B 의 write 를 보존해야 한다"
    )

    # revert-proof: 두 결과가 *반드시* 갈라져야 한다. fence 검사를 떼면(enforce_fence=False)
    # fenced 모델도 'A' 로 corrupt → 이 assert 가 RED 로 뒤집힌다. 토톨로지/상수 아님.
    assert naive_final != fenced_final, (
        "property 가 fencing 메커니즘에 진짜로 의존해야 한다 (검사 제거 시 동일 corrupt)"
    )


# ════════════════════════════════════════════════════════════════════════════
#  guard_mechanism — 양성/novel oracle (실 OMD spec 구조 corroboration)
# ════════════════════════════════════════════════════════════════════════════
def test_omd_tla_checks_unique_live_fence_and_no_stale_mutate():
    """실 OMD TLA spec 이 fencing 불변식을 *정의 + model-check* 함을 독립 확증.

    DEFECT oracle 의 in-test 모델과 무관한 별개의 진실원천(실 .tla/.cfg 파일)에서 측정.
    """
    lease_tla = _read(LEASE_TLA)
    lease_cfg = _read(LEASE_CFG)
    leader_tla = _read(LEADER_TLA)
    leader_cfg = _read(LEADER_CFG)

    # UniqueLiveFence: omd_lease.tla 선언 + omd_lease.cfg INVARIANTS 등재
    assert declared_in_tla(lease_tla, "UniqueLiveFence"), (
        "UniqueLiveFence 가 omd_lease.tla 에 `==` 로 정의돼야 한다"
    )
    assert invariant_checked_in_cfg(lease_cfg, "UniqueLiveFence"), (
        "UniqueLiveFence 가 omd_lease.cfg INVARIANTS 에 등재(model-checked)돼야 한다"
    )

    # NoEnabledStaleMutate: omd_leader.tla 선언 + omd_leader.cfg INVARIANTS 등재
    assert declared_in_tla(leader_tla, "NoEnabledStaleMutate"), (
        "NoEnabledStaleMutate 가 omd_leader.tla 에 `==` 로 정의돼야 한다"
    )
    assert invariant_checked_in_cfg(leader_cfg, "NoEnabledStaleMutate"), (
        "NoEnabledStaleMutate 가 omd_leader.cfg INVARIANTS 에 등재돼야 한다"
    )

    # 음성통제(vacuity 방지): 존재하지 않는 불변식은 어느 oracle 도 찾으면 안 된다.
    bogus = "NoSuchFenceInvariant"
    assert not declared_in_tla(lease_tla, bogus)
    assert not declared_in_tla(leader_tla, bogus)
    assert not invariant_checked_in_cfg(lease_cfg, bogus)
    assert not invariant_checked_in_cfg(leader_cfg, bogus), (
        "oracle 가 진짜로 식별력이 있어야 한다 (bogus 이름은 거부)"
    )


# ── 추가 음성통제: cfg 파서가 INVARIANTS 밖 토큰을 오인하지 않는지 ─────────────
def test_cfg_parser_does_not_match_non_invariant_section_tokens():
    """파서가 다른 섹션의 토큰(예: CONSTANTS 의 'MaxFence')을 invariant 로 오인하면 안 된다."""
    lease_cfg = _read(LEASE_CFG)
    # MaxFence 는 CONSTANTS 에만 있고 INVARIANTS 에는 없다.
    assert "MaxFence" in lease_cfg  # sanity: 파일에 분명히 존재
    assert not invariant_checked_in_cfg(lease_cfg, "MaxFence"), (
        "CONSTANTS 의 토큰이 INVARIANTS 등재로 잘못 잡히면 oracle 이 vacuous 해진다"
    )
