r"""single_leader_epoch — D14 단일-리더 HA 입장 / TLA omd_leader.

문헌(literature):
  Leader election with epochs/terms (Raft term §5.4 "term" monotonicity; ZAB epoch)
  + STONITH/fencing tokens. 두 코디네이터가 동시에 자기를 리더로 믿으면(split-brain)
  서로 충돌하는 쓰기를 발행 → store corruption. 처방 = monotone epoch: takeover 가
  epoch 을 +1 하고, 낡은 epoch 을 실은 stale 리더의 쓰기는 fence-out(거부). 결과:
  epoch-current writer 는 최대 1명.

OMD dimension: D14 single-leader HA admission.
KG lit node:   OMD-finding-fencing-required.

corroborated OMD artifact (mechanism oracle, STRUCTURAL TLA):
  <WORKSPACE>/PROJECT/PI/omd/spec/omd_leader.tla
    SingleLeader                  (omd_leader.tla:102)
    NoEnabledStaleMutate          (omd_leader.tla:105)  \* stale c는 Mutate ENABLED 불가
    StaleCoordinatorCannotBeLeader(omd_leader.tla:112)  \* leader ⇒ localEpoch=epoch
  <WORKSPACE>/PROJECT/PI/omd/spec/omd_leader.cfg
    INVARIANTS 절에 위 셋 모두 등재 → 실제 model-checked.
  behavioral 근거: tests/test_d14_ha_admission.py (takeover epoch+1, 좀비 변이 차단).

oracle_kind: tla (structural — TLC/java 미가용, 선언+체크 등재만 정적 검증).

판정 계약: guard_defect(개선 오라클, in-test naive vs fenced) +
           guard_mechanism(실아티팩트 TLA 구조 오라클, 독립 출처) = progressive.
"""

import os
import re

SPEC_DIR = "<WORKSPACE>/PROJECT/PI/omd/spec"
TLA_PATH = os.path.join(SPEC_DIR, "omd_leader.tla")
CFG_PATH = os.path.join(SPEC_DIR, "omd_leader.cfg")

# .cfg 의 섹션 키워드(이 줄을 만나면 INVARIANTS 목록이 끝난다).
_CFG_SECTIONS = {
    "CONSTANT", "CONSTANTS", "SPECIFICATION", "INIT", "NEXT",
    "INVARIANT", "INVARIANTS", "PROPERTY", "PROPERTIES",
    "CONSTRAINT", "CONSTRAINTS", "ACTION_CONSTRAINT", "SYMMETRY",
    "VIEW", "CHECK_DEADLOCK", "ALIAS", "POSTCONDITION",
}


# --------------------------------------------------------------------------
# 실아티팩트 파서 (mechanism oracle 보조) — 두 출처를 독립적으로 읽는다.
# --------------------------------------------------------------------------
import os as _os
import pytest as _pytest
_OMD_ROOT = _os.environ.get("OMD_ROOT", "<WORKSPACE>/PROJECT/PI/omd")
_OMD_ABSENT = not _os.path.isdir(_OMD_ROOT)
# audit un-gate: 자기완결 defect 오라클(naive-vs-fixed in-test 모델, OMD 불요)은 게이트 없이 CI 서 실행.
# OMD-의존 mechanism 오라클(disjoint import / TLA 파싱 / OMD venv subprocess)만 부재 시 skip(아래 @_skip_omd).
_skip_omd = _pytest.mark.skipif(
    _OMD_ABSENT, reason="OMD 자매 repo 미체크아웃/OMD_ROOT 미설정 — 크로스레포 mechanism 오라클(로컬/CI-checkout 시만)")

def _tla_declared_operators(tla_text):
    """`<Name> ==` 형태로 *선언된* 연산자 이름 집합."""
    names = set()
    for line in tla_text.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*==", line)
        if m:
            names.add(m.group(1))
    return names


def _cfg_checked_invariants(cfg_text):
    """.cfg 의 INVARIANT(S) 절 아래 *실제 체크되는* 불변식 이름 집합."""
    names = set()
    collecting = False
    for raw in cfg_text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("\\*"):
            continue
        first = stripped.split()[0]
        if first in ("INVARIANT", "INVARIANTS"):
            collecting = True
            # 같은 줄에 이름이 붙어있을 수도 있음: "INVARIANTS Foo Bar"
            for tok in stripped.split()[1:]:
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", tok):
                    names.add(tok)
            continue
        if first in _CFG_SECTIONS:
            collecting = False
            continue
        if collecting:
            for tok in stripped.split():
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", tok):
                    names.add(tok)
    return names


# ==========================================================================
# guard_defect — 개선 오라클 (self-contained, revert-proof)
#   naive(no epoch) split-brain double-write  vs  fenced(monotone epoch)
# ==========================================================================
class _Store:
    """공유 자원. epoch_fencing=False 면 naive(모든 쓰기 수락)."""

    def __init__(self, epoch_fencing):
        self.epoch_fencing = epoch_fencing
        self.current_epoch = 0          # store 가 본 가장 높은 leader epoch
        self.accepted = []              # 수락된 (writer, epoch) 쓰기 로그

    def write(self, writer, write_epoch):
        if self.epoch_fencing:
            # STONITH/fencing token: epoch < current → stale, 거부.
            if write_epoch < self.current_epoch:
                return False            # fenced out
            self.current_epoch = write_epoch
        self.accepted.append((writer, write_epoch))
        return True


class _Coordinator:
    def __init__(self, cid, epoch):
        self.cid = cid
        self.epoch = epoch              # 이 코디네이터가 믿는 자신의 leader epoch

    def mutate(self, store):
        return store.write(self.cid, self.epoch)


def _run_split_brain_schedule(epoch_fencing):
    """적대적 결정론 스케줄(시간이 아니라 reorder 로 GC/partition 모델링).

      t0: C1 이 리더로 기동 (epoch=1).
      t1: 네트워크 분할 — C2 도 자신을 리더로 믿고 takeover.
            * fencing 켜짐 → epoch 을 2 로 bump (monotone).
            * fencing 꺼짐 → epoch 개념 없음(둘 다 1로 둠 = naive).
      t2: 분할 치유 후 stale C1 이 깨어나 옛 epoch 으로 변이.
      t3: 현 리더 C2 가 변이.
    반환: store (수락 로그 검사용).
    """
    store = _Store(epoch_fencing=epoch_fencing)
    c1 = _Coordinator("c1", epoch=1)
    if epoch_fencing:
        c2 = _Coordinator("c2", epoch=2)   # takeover bump
    else:
        c2 = _Coordinator("c2", epoch=1)   # naive: takeover 도 같은(무의미) epoch

    # C1 이 리더로서 먼저 한 번 쓴다 (store.current_epoch=1 로 끌어올림).
    assert c1.mutate(store) is True
    # 분할 동안 C2 takeover → 현 리더로서 쓴다.
    assert c2.mutate(store) is True
    # 치유 후 stale C1 이 옛 토큰으로 변이 시도(좀비 쓰기).
    c1.mutate(store)
    # 현 리더 C2 가 한 번 더 변이.
    c2.mutate(store)
    return store


def test_split_brain_double_write_epoch_fencing_admits_one_writer():
    """NAIVE 는 split-brain double-write 를 허용(부패), FENCED 는 단일 writer 강제.

    revert-proof: _Store.write 의 epoch-fence 분기를 지우면(=epoch_fencing 무시),
    fenced 케이스도 naive 처럼 두 writer 가 land → 아래 단언이 RED 로 뒤집힌다.
    """
    # ---- NAIVE: epoch 없음 → split-brain. 두 리더의 쓰기가 모두 land.
    naive = _run_split_brain_schedule(epoch_fencing=False)
    naive_writers = {w for (w, _e) in naive.accepted}
    # 안전성(single-writer) 위반: 서로 다른 두 코디네이터가 모두 store 에 썼다.
    assert naive_writers == {"c1", "c2"}, (
        "naive 모델이 split-brain double-write 를 보여야 한다(두 writer)"
    )
    # stale C1 의 좀비 쓰기가 takeover 이후에도 남아 부패를 일으킴.
    assert ("c1", 1) in naive.accepted
    assert sum(1 for (w, _e) in naive.accepted if w == "c1") == 2

    # ---- FENCED: monotone epoch → stale C1 은 fence-out. 단 한 writer 만 land.
    fenced = _run_split_brain_schedule(epoch_fencing=True)
    # takeover 이후 store.current_epoch=2. C1(epoch=1) 의 좀비 쓰기는 거부.
    fenced_post_takeover = [(w, e) for (w, e) in fenced.accepted if e >= 2]
    fenced_writers_post = {w for (w, _e) in fenced_post_takeover}
    assert fenced_writers_post == {"c2"}, (
        "fencing 이 켜지면 takeover 후엔 현-epoch writer(c2) 만 land 해야 한다"
    )
    # stale C1 의 좀비 변이(epoch=1)는 takeover(epoch=2) 이후 단 한 번도 수락되지 않음.
    c1_after_bump = [
        i for i, (w, e) in enumerate(fenced.accepted)
        if w == "c1" and i > 0  # i==0 은 takeover 전 정당한 첫 쓰기
    ]
    assert c1_after_bump == [], "stale c1 의 좀비 쓰기는 fence-out 되어야 한다"

    # ---- 핵심 대비: 같은 적대 스케줄에서 naive 는 위반, fenced 는 성립.
    assert naive_writers != fenced_writers_post


# ==========================================================================
# guard_mechanism — 실 OMD substrate 독립 corroboration (STRUCTURAL TLA)
# ==========================================================================
@_skip_omd
def test_omd_tla_checks_single_leader_and_stale_cannot_lead():
    """omd_leader.tla 가 fencing 불변식 셋을 *선언* AND .cfg 가 *체크* 등재.

    in-test 모델과 완전히 독립(실 spec 파일을 읽어 정적 검증). 음성 통제로
    bogus 이름이 둘 중 어디에도 없음을 단언 → 오라클 비공허성 보장.
    """
    with open(TLA_PATH, encoding="utf-8") as f:
        tla_text = f.read()
    with open(CFG_PATH, encoding="utf-8") as f:
        cfg_text = f.read()

    declared = _tla_declared_operators(tla_text)
    checked = _cfg_checked_invariants(cfg_text)

    required = {
        "SingleLeader",
        "NoEnabledStaleMutate",
        "StaleCoordinatorCannotBeLeader",
    }

    # (a) 세 불변식 모두 .tla 에 `<Name> ==` 로 선언되어 있어야.
    missing_decl = required - declared
    assert not missing_decl, f"omd_leader.tla 미선언 불변식: {sorted(missing_decl)}"

    # (b) 세 불변식 모두 .cfg INVARIANTS 절에 등재(=실제 model-checked)되어야.
    missing_chk = required - checked
    assert not missing_chk, f"omd_leader.cfg 미체크 불변식: {sorted(missing_chk)}"

    # (c) 음성 통제: 존재하지 않는 이름은 선언/체크 어디에도 없어야(파서 비공허).
    bogus = "NoSplitBrainEverProvenByMagic_XYZ"
    assert bogus not in declared, "파서가 bogus 이름을 선언으로 오인하면 안 됨"
    assert bogus not in checked, "파서가 bogus 이름을 체크로 오인하면 안 됨"

    # (d) 음성 통제 강화: 파서가 정말 .cfg 를 읽었는지 — 실재 등재 항목으로 확인.
    assert "TypeOK" in checked, "파서가 .cfg INVARIANTS 절을 실제로 수집해야 함"


# ==========================================================================
# 회귀/음성 통제 (보조) — 파서 판별력 + cfg 절 경계.
# ==========================================================================
@_skip_omd
def test_cfg_parser_discriminates_and_respects_section_boundaries():
    """.cfg 파서가 INVARIANTS 절만 수집하고 CONSTANTS/SPEC 토큰은 안 줍는지."""
    sample = (
        "CONSTANTS\n"
        "  Coordinators = {c1, c2}\n"
        "  MaxEpoch = 3\n"
        "SPECIFICATION Spec\n"
        "CHECK_DEADLOCK FALSE\n"
        "INVARIANTS\n"
        "  TypeOK\n"
        "  SingleLeader\n"
        "  NoEnabledStaleMutate\n"
        "  StaleCoordinatorCannotBeLeader\n"
    )
    got = _cfg_checked_invariants(sample)
    assert "SingleLeader" in got
    assert "StaleCoordinatorCannotBeLeader" in got
    # CONSTANTS/SPECIFICATION 영역의 토큰은 불변식으로 새지 않아야.
    assert "Coordinators" not in got
    assert "Spec" not in got
    assert "MaxEpoch" not in got
    # 실 cfg 도 동일 결론.
    with open(CFG_PATH, encoding="utf-8") as f:
        real = _cfg_checked_invariants(f.read())
    assert {"SingleLeader", "NoEnabledStaleMutate",
            "StaleCoordinatorCannotBeLeader"} <= real


def test_defect_oracle_is_revert_proof_under_flag_toggle():
    """메커니즘(epoch fence)을 끄면(naive) 안전성 위반, 켜면 성립 — 토글 민감성.

    이 회귀는 guard_defect 의 revert-proof 성을 명시적으로 못박는다: 동일
    스케줄에서 fencing 플래그만 뒤집어 결과가 달라짐을 보인다(상수/항진 아님)."""
    naive = _run_split_brain_schedule(epoch_fencing=False)
    fenced = _run_split_brain_schedule(epoch_fencing=True)

    # naive: stale c1 좀비 쓰기가 land (위반).
    assert sum(1 for (w, _e) in naive.accepted if w == "c1") == 2
    # fenced: stale c1 좀비 쓰기가 fence-out (성립).
    assert sum(1 for (w, _e) in fenced.accepted if w == "c1") == 1
    # 두 모델의 수락 로그가 실제로 다름 → 메커니즘에 결과가 의존.
    assert naive.accepted != fenced.accepted
