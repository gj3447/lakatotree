"""OMD 병렬-프로그래밍 지식을 라카토스 연구프로그램(PROM)으로 도그푸드한 하네스 (2026-06-27).

OMD(입체운행물방울) = 멀티에이전트 *병렬* 소프트웨어 개발 코디네이터. 이 하네스는 OMD 가 구현/검증한
병렬·분산 프로그래밍 지식 전체를 하나의 라카토스 *연구프로그램*으로 재서술한다:

  하드코어(hard core, 채점 안 함) = SINGULON:
    "서로소(입체) write-set ⇒ 무충돌 응결(merge) ⇒ 분열(악)=0"  +  통일테제:
    "소유·수명한정·fence 가 박힌 단일 LEASE 하나 → 4 투영(orbit/flag/semaphore/barrier)".
    이건 반증 대상이 아니라 보호대가 지키는 핵. (prediction=None)

  보호대(protective belt) = 고전 병렬/분산 문헌의 *anomaly* 에 대한 OMD 의 problemshift 13건.
    각 노드는 그 원리(상호배제·fencing·lease 회수·교착자유·기아자유·crash-safe barrier/semaphore·
    exactly-once·split-phase 2PC·phantom-read·write-set 건전성·단일리더 epoch)를 인코딩한다.

★규율(design_audit_20260625 / frontier_fix_20260626 와 동일): 노드는 verdict 를 손입력하지 않는다.
  각 노드는 사전등록 Prediction + 독립 NovelTarget + *명명된 이중 가드* 만 들고 OPEN 으로 앉는다.
  guard 미착륙 = 정직한 pending(가짜 green 0). verdict 는 전부 judge() 가 생성한다.

★★ 이중 가드(frontier_fix FG-2 교정 계승): 발견(원리)당 *독립* 두 오라클 —

    guard_defect    → 개선축(measured)     : NAIVE 베이스라인이 그 고전적 실패를 *허용*하고 원리적
                                              메커니즘이 닫음을, 테스트 안에서 깨진모델 vs 고친모델을
                                              둘 다 돌려 revert-proof 로 증명 (음성 오라클).
    guard_mechanism → novel축(novel_measured): 그 메커니즘이 *실제 OMD substrate* 에 있음을 독립
                                              조달 — disjoint.py 실모듈 import / 모델체크된 TLA+
                                              불변식 / 차원별 OMD 테스트 subprocess (양성 오라클).

  두 축이 서로 다른 출처라서 judge() 가 진짜로 판별한다:

    defect닫힘 ∧ mechanism존재 → progressive  (문헌 anomaly 를 OMD 가 실제로 해소 — 진보적 problemshift)
    defect닫힘 ∧ mechanism없음 → partial      (원리는 알지만 OMD substrate 미확증 = ad-hoc)
    defect열림 ∧ mechanism존재 → equivalent   (substrate 는 있으나 원리 모델 미완)
    둘 다 미착륙              → pending(no-receipt)

  _discrimination_demo() 가 이 4-칸을 합성 receipt 로 증명한다(채점력 0 의 도그푸드 연극 아님).

문헌 grounding 은 공유 KG 의 OMD 선행연구(OMD-finding-fencing-required: Kleppmann/HBase fencing;
OMD-finding-glob-overlap-gap: PG-SSI predicate locking)와 고전결과(Dijkstra/Lamport/Gray&Cheriton/
Coffman/Gray-2PC/Raft-ZAB epoch)에 묶인다.
# KG: span_omd_parallel_20260627 / LakatosTree_OmdParallel_20260627
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = "<WORKSPACE>/PROJECT/PI/lakatotree"
# OMD-parallel guard 들이 착륙할 전용 파일 패턴(비면 전부 pending). 원리당 1파일 × 2가드.
_RECEIPT_GLOB = "tests/test_omd_parallel_*.py"
_TREE = "LakatosTree_OmdParallel_20260627"


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo .venv pytest 로 OMD-parallel guard 테스트를 돌려 {test_func: passed} 수집(self-report 아님).

    guard 파일이 아직 0개면 빈 dict → run() 이 전부 정직한 pending 을 낸다.
    """
    matches = glob.glob(os.path.join(_ROOT, _RECEIPT_GLOB))
    if not matches:
        return {}
    cmd = (f"cd {_ROOT} && . .venv/bin/activate 2>/dev/null; "
           f"python -m pytest {_RECEIPT_GLOB} -v --no-header -p no:cacheprovider 2>&1")
    out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        m = re.search(r"\b(test_\w+)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR)\b", line)
        if m:
            name, ok = m.group(1), m.group(2) == "PASSED"
            res[name] = res.get(name, True) and ok
    return res


@dataclass(frozen=True)
class ParallelNode:
    tag: str
    dimension: str                # OMD 차원(D#) / TLA 불변식 표지
    parent: str | None
    evidence: str                 # 실제 OMD file:line 또는 TLA 불변식 + cfg
    story: str                    # 문헌 anomaly → OMD problemshift
    lit: str                      # 인용한 고전 결과
    prom: str                     # 실 메커니즘이 OMD 어디에 사는가
    prediction: Prediction | None = None      # 개선축(defect-closed)
    novel_target: NovelTarget | None = None   # novel축(real-substrate mechanism) — *독립* metric
    guard_defect: str = ""        # 개선축 음성 오라클(green = naive 실패 & fixed 통과, revert-proof)
    guard_mechanism: str = ""     # novel축 양성 오라클(green = 실 OMD substrate 에 메커니즘 존재)


# 하드코어 루트(채점 안 함) + 13 OPEN 보호대 노드.
NODES_DEF: tuple[ParallelNode, ...] = (
    ParallelNode(
        tag="singulon_hardcore", dimension="SINGULON / 통일테제", parent=None,
        evidence="omd/CONCEPT.md §SINGULON · omd_server/__init__.py(서로소 write-set ⇒ 분열=0) · CONCURRENCY.md §0.2(1 lease → 4 투영)",
        story="하드코어 추측: (1) 서로소(입체) write-set ⇒ 무충돌 응결 ⇒ 분열=0; (2) 소유·수명한정·fence 박힌 "
              "단일 LEASE 하나가 orbit/flag/semaphore/barrier·merge_token 으로 투영된다. 보호대 13노드가 이 핵을 "
              "고전 anomaly 로부터 지킨다. (루트 — 채점 안 함)",
        lit="Lakatos(1970) 연구프로그램: 하드코어 + 보호대 + 양/음성 휴리스틱.",
        prom="omd_server/disjoint.py · core.py(_cs/reclaim_agent/_connect_phase_*) · spec/*.tla",
    ),

    # ───────── 상호배제 계열 ─────────
    ParallelNode(
        tag="mutex_disjoint_orbits", dimension="SINGULON / TLA NoOverlappingHeld", parent="singulon_hardcore",
        evidence="omd_server/disjoint.py sets_overlap/globs_overlap(순수·import 가능) · spec/omd_lease.tla:136 NoOverlappingHeld(omd_lease.cfg INVARIANTS 등재)",
        story="Dijkstra/Lamport 상호배제: 임계영역 동시진입 금지. OMD 는 이를 *구조적*으로 — 두 작업은 write-set "
              "glob 이 서로소일 때만 병렬, 겹치면 직렬화(=SINGULON). NAIVE prefix/exact 충돌검사는 진짜 겹침을 "
              "놓쳐(false-negative) 둘 다 HELD → 공유경로 동시쓰기 → 머지충돌. 실 disjoint 는 세그먼트 패턴교집합으로 "
              "false-negative 0(건전).",
        lit="Dijkstra/Lamport 상호배제; OMD glob-overlap leasing(시판 락 부재의 핵심 IP, KG OMD-finding-glob-overlap-gap).",
        prom="omd_server/disjoint.py:93 sets_overlap / :86 globs_overlap; TLA NoOverlappingHeld",
        prediction=Prediction(metric_name="mutex_naive_conflict_check_false_negative", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD disjoint 는 알려진 겹침 배터리에서 false-negative 0(건전) — naive prefix 검사는 놓친다",
                              closes_question="q-omd-mutex-disjoint"),
        novel_target=NovelTarget(metric_name="omd_disjoint_overlap_sound_no_false_negative", direction="higher", threshold=1.0),
        guard_defect="test_naive_prefix_conflict_check_misses_true_overlap_real_one_catches",
        guard_mechanism="test_omd_sets_overlap_is_sound_and_tla_checks_no_overlapping_held",
    ),
    ParallelNode(
        tag="writeset_fs_soundness", dimension="D10 / P0-11 write-set FS 감사", parent="mutex_disjoint_orbits",
        evidence="omd_server/disjoint.py:114 path_matches_glob / :135 path_in_globs(정확매칭, false-positive 0) — :86 globs_overlap(over-report)과 의도적 분리",
        story="선언적 write-set 은 FS 에서 *집행*돼야 의미가 있다(capability/least-privilege): git diff ⊆ 선언 globs "
              "아니면 git add -A 로 궤도 밖 경로를 커밋해 SINGULON 분열을 침묵으로 깬다. 충돌검사용 globs_overlap 은 "
              "char-class 를 보수적 over-report(claim 시 안전: 병렬도만 손해) 하지만 *감사*엔 unsound(덮인다 오판=궤도밖 "
              "쓰기 통과). 그래서 감사는 정확 path_in_globs(false-positive 0)를 쓴다.",
        lit="Capability/least-privilege; predicate-lock soundness(PG-SSI, KG OMD-finding-glob-overlap-gap).",
        prom="omd_server/disjoint.py path_in_globs/path_matches_glob (감사) vs globs_overlap (claim)",
        prediction=Prediction(metric_name="loose_matcher_admits_out_of_orbit_write", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 path_in_globs 는 궤도 밖 구체경로에 false-positive 0 — over-report 매처는 통과시킨다",
                              closes_question="q-omd-writeset"),
        novel_target=NovelTarget(metric_name="omd_path_in_globs_exact_no_false_positive", direction="higher", threshold=1.0),
        guard_defect="test_loose_overlap_admits_orphan_write_exact_path_in_globs_rejects",
        guard_mechanism="test_omd_path_in_globs_is_exact_no_false_positive_on_out_of_orbit",
    ),
    ParallelNode(
        tag="two_phase_commit_split", dimension="D8 split-phase merge / TLA omd_connect", parent="mutex_disjoint_orbits",
        evidence="spec/omd_connect.tla AtMostOneMergeToken(:111)+TokenImpliesConnecting(:114)+MergedHasMergeSha(:117) (omd_connect.cfg INVARIANTS)",
        story="긴 부작용(git merge)은 코디네이터 락을 쥔 채 하면 안 되나 원자·복구가능해야 한다(Gray 2PC + WAL 복구). "
              "OMD split-phase: A) 락 안에서 fence 재검증 + repo-wide merge_token 획득, B) 락 밖 git merge, C) orbit "
              "해제 *전* merge_sha 기록 + 재시작이 trailer 로 복구. NAIVE 단상은 merge 성공과 MERGED 표기 사이 crash 시 "
              "CONNECTING 영구좌초 또는 재머지(이중효과). split-phase 는 정확히-한번 복구.",
        lit="Gray two-phase commit + write-ahead/crash recovery.",
        prom="core._connect_phase_a/b/c; merge_token(capacity 1); TLA omd_connect 불변식 4종",
        prediction=Prediction(metric_name="single_phase_merge_crash_strands_or_double_applies", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="merge_sha-before-release + token 배타 불변식이 omd_connect.tla 선언+INVARIANTS 등재(본 가드=정적검증; TLC 는 OMD CI tla.yml 이 실행)",
                              closes_question="q-omd-2pc"),
        novel_target=NovelTarget(metric_name="omd_connect_2pc_invariants_declared_registered", direction="higher", threshold=1.0),
        guard_defect="test_single_phase_merge_crash_strands_split_phase_recovers_exactly_once",
        guard_mechanism="test_omd_tla_checks_merge_sha_and_at_most_one_merge_token",
    ),
    ParallelNode(
        tag="phantom_read_coherence", dimension="D12 read-set 일관성", parent="mutex_disjoint_orbits",
        evidence="omd/CONCURRENCY.md §D12 integration-generation 추적 + read-lease stale-flag · tests/test_d12_read_coherence.py",
        story="Phantom read/serializability(SQL isolation, SSI): read-set 을 선언한 reader 가, 그 경로를 다른 작업이 "
              "merge 하면 stale base 위에서 판단한다(더 이상 참 아닌 데이터). OMD 는 read-lease 에 integration "
              "generation 을 박고, 읽은 경로가 declare 후 바뀌면 reader 를 STALE 로 표식해 rebase 강제 — phantom 위 "
              "행동 금지. NAIVE 는 generation 검사 없이 g0 스냅샷으로 행동.",
        lit="Phantom reads / serializability (SQL isolation; Serializable Snapshot Isolation).",
        prom="core read-lease generation 추적; CONCURRENCY.md §D12",
        prediction=Prediction(metric_name="phantom_stale_read_acted_on_unflagged", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 가 generation 으로 stale read 를 flag 한다(차원테스트 green)",
                              closes_question="q-omd-phantom"),
        novel_target=NovelTarget(metric_name="omd_d12_read_coherence_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_phantom_stale_read_acted_on_generation_tracking_flags_stale",
        guard_mechanism="test_omd_d12_read_coherence_dimension_test_passes_in_real_substrate",
    ),

    # ───────── fencing/lease 계열 ─────────
    ParallelNode(
        tag="fencing_token_vs_ttl", dimension="D6 fencing / TLA UniqueLiveFence + NoEnabledStaleMutate", parent="singulon_hardcore",
        evidence="spec/omd_lease.tla:143 UniqueLiveFence(omd_lease.cfg) · spec/omd_leader.tla:105 NoEnabledStaleMutate(omd_leader.cfg)",
        story="Kleppmann '분산 락': 순수 TTL lease 는 GC pause/네트워크 지연에 불안전 — lease 만료 후 깨어난 프로세스가 "
              "쓰면 상태가 깨진다(HBase 실버그; Redlock 은 fencing 없음). 해법=단조 fencing token 을 lease 와 함께 발급, "
              "자원이 더 낮은 token 의 쓰기를 거부. OMD 는 orbit 마다 fence(획득 revision), merge/CONNECT 가 집행지점.",
        lit="Kleppmann 'How to do distributed locking'; HBase fencing 버그; Redlock 무fencing (KG OMD-finding-fencing-required).",
        prom="core orbit fence(획득 revision) · CONNECT 게이트 fence 재검증; TLA UniqueLiveFence/NoEnabledStaleMutate",
        prediction=Prediction(metric_name="pure_ttl_lease_admits_stale_writer", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="fence 단조성/무stale-mutate 불변식이 omd_lease/omd_leader.tla 선언+INVARIANTS 등재(본 가드=정적검증; TLC 는 OMD CI tla.yml 이 실행)",
                              closes_question="q-omd-fencing"),
        novel_target=NovelTarget(metric_name="omd_fencing_invariants_declared_registered", direction="higher", threshold=1.0),
        guard_defect="test_pure_ttl_lease_admits_stale_write_fencing_token_rejects_it",
        guard_mechanism="test_omd_tla_checks_unique_live_fence_and_no_stale_mutate",
    ),
    ParallelNode(
        tag="lease_reclamation_liveness", dimension="D2 통합 회수", parent="fencing_token_vs_ttl",
        evidence="omd/CONCURRENCY.md §D2 core.reclaim_agent() 단일 회수 루틴 · tests/test_d2_reclaim.py(bail+zombie 둘 다 requeue)",
        story="Gray&Cheriton(1989) lease: 시간한정 락이라 죽은/단절된 holder 가 시스템을 영구 블록 못 한다. Liveness: "
              "모든 lease 는 유한시간 내 회수. OMD 는 자발 bail 과 비자발 zombie-timeout 을 *하나의* reclaim_agent() "
              "루틴으로 통합(두 갈래 코드의 발산 방지). NAIVE(TTL/회수 없음)는 holder crash 시 대기자 영구 정지.",
        lit="Gray & Cheriton (1989) leases — fault-tolerant 분산 파일 캐시 일관성.",
        prom="core.reclaim_agent() 통합 회수; heartbeat_ttl 기본 ON",
        prediction=Prediction(metric_name="orphan_lease_blocks_waiter_forever", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 가 자발+zombie lease 를 단일 경로로 회수해 대기자를 promote(차원테스트 green)",
                              closes_question="q-omd-reclaim"),
        novel_target=NovelTarget(metric_name="omd_unified_reclaim_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_unreclaimed_orphan_lease_blocks_waiter_finite_ttl_reclaim_frees_it",
        guard_mechanism="test_omd_d2_reclaim_dimension_test_passes_in_real_substrate",
    ),
    ParallelNode(
        tag="single_leader_epoch", dimension="D14 단일리더 HA / TLA omd_leader", parent="fencing_token_vs_ttl",
        evidence="spec/omd_leader.tla:102 SingleLeader + :105 NoEnabledStaleMutate + :112 StaleCoordinatorCannotBeLeader(omd_leader.cfg)",
        story="Epoch/term 리더선출(Raft term, ZAB epoch) + STONITH/fencing: 둘 다 리더라 믿는 코디네이터(split-brain)는 "
              "충돌 쓰기로 손상. 해법=단조 epoch — takeover 가 epoch 증가, stale 리더의 (옛 epoch) 쓰기는 fence-out. "
              "epoch-현재 writer 는 최대 1. NAIVE(epoch 없음)는 파티션 시 두 리더 동시 쓰기.",
        lit="Raft term / ZAB epoch 리더선출; STONITH fencing.",
        prom="core leader-lease epoch; D14 admission; TLA SingleLeader/StaleCoordinatorCannotBeLeader",
        prediction=Prediction(metric_name="dual_coordinator_split_brain_double_write", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="단일리더/무stale-mutate/stale-못됨-리더 불변식이 omd_leader.tla 선언+INVARIANTS 등재(본 가드=정적검증; TLC 는 OMD CI tla.yml 이 실행)",
                              closes_question="q-omd-leader"),
        novel_target=NovelTarget(metric_name="omd_leader_tla_invariants_declared_registered", direction="higher", threshold=1.0),
        guard_defect="test_split_brain_double_write_epoch_fencing_admits_one_writer",
        guard_mechanism="test_omd_tla_checks_single_leader_and_stale_cannot_lead",
    ),

    # ───────── 교착/기아(liveness) 계열 ─────────
    ParallelNode(
        tag="deadlock_freedom_dag", dimension="D7 / P0-10 의존 DAG 비순환", parent="singulon_hardcore",
        evidence="omd core depend/declare 사이클 게이트(_find_cycle DFS, P0-10) · tests/test_d7_dep_cycle.py(back-edge/self-dep 거부, 그래프 불변)",
        story="Coffman 조건(1971): 교착엔 순환대기가 필요. 비순환 자원/의존 순서(Havender)로 깬다. OMD 는 declare()/"
              "depend() 가 사이클을 만들 엣지를 거부({ok:false,reason:dep_cycle}) + claim 에서 wait-for 사이클 탐지 — "
              "그래프 불변 유지. NAIVE(게이트 없음)는 A→B→C→A 순환대기로 0 진척.",
        lit="Coffman 조건(순환대기); Havender 자원순서.",
        prom="core depend/declare _find_cycle DFS 게이트(P0-10)",
        prediction=Prediction(metric_name="cyclic_dependency_causes_deadlock", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 가 dep-cycle/self-dep 를 거부하고 그래프를 불변 유지(차원테스트 green)",
                              closes_question="q-omd-deadlock"),
        novel_target=NovelTarget(metric_name="omd_dag_acyclicity_gate_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_cyclic_dep_deadlocks_acyclicity_gate_rejects_back_edge_and_unblocks",
        guard_mechanism="test_omd_d7_dep_cycle_dimension_test_passes_in_real_substrate",
    ),
    ParallelNode(
        tag="starvation_freedom_fifo", dimension="D7 no-overtaking phase-fair FIFO", parent="deadlock_freedom_dag",
        evidence="omd/CONCURRENCY.md §D7 no-overtaking 규칙 + _has_earlier_waiter + next_seq() 단조 FIFO; reader↔writer phase-fair",
        story="Lamport bakery(1974) bounded-waiting; Courtois readers-writers 공정성. 교착자유 너머 liveness 는 *기아자유* "
              "필요 — 대기자는 유한 스텝 내 서빙. greedy/LIFO 또는 무한 reader-선호는 writer 영구기아. 해법=no-overtaking "
              "(FIFO) phase-fair 큐: 신규 도착이 이미 대기중 요청을 추월 못 한다. NAIVE greedy 는 호환 후발을 계속 grant 해 "
              "이른 대기자 W 를 영구기아.",
        lit="Lamport bakery bounded-waiting; Courtois-Heymans-Parnas readers-writers 공정성.",
        prom="core no-overtaking(_has_earlier_waiter) + next_seq() 단조 FIFO; CONCURRENCY.md §D7",
        prediction=Prediction(metric_name="greedy_grant_starves_early_waiter", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="OMD 설계가 no-overtaking/phase-fair FIFO 를 명시 약속한다(실 doc 확증)",
                              closes_question="q-omd-starvation"),
        novel_target=NovelTarget(metric_name="omd_no_overtaking_fifo_documented", direction="higher", threshold=1.0),
        guard_defect="test_greedy_grant_starves_waiter_no_overtaking_fifo_bounds_wait",
        guard_mechanism="test_omd_concurrency_doc_commits_to_no_overtaking_phase_fair_fifo",
    ),

    # ───────── crash-safe 동기화 프리미티브 계열 ─────────
    ParallelNode(
        tag="barrier_crash_safe", dimension="D5 crash-safe 응결 배리어", parent="singulon_hardcore",
        evidence="omd/CONCURRENCY.md §D5 generation-stamped rendezvous + BROKEN terminal · tests/test_d5_barrier.py",
        story="배리어 동기화(cyclic/sense-reversing): N 참가자 랑데부 후 함께 진행. NAIVE 배리어는 참가자가 도착 전 죽으면 "
              "영구 HANG. crash-safe 해법=generation-stamp + BROKEN terminal: 참가자 사망/타임아웃 시 배리어가 깨지고 "
              "전원 기상(CyclicBarrier.reset/BrokenBarrierException). OMD 응결 배리어는 멤버십=task 집합, generation 박힘, "
              "사망 시 BROKEN.",
        lit="Barrier synchronization (cyclic barrier / sense-reversing barrier).",
        prom="core _barrier_eval BROKEN terminal; policy break/shrink; CONCURRENCY.md §D5",
        prediction=Prediction(metric_name="naive_barrier_hangs_on_member_death", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 배리어가 참가자 사망 시 BROKEN 으로 전원 기상(차원테스트 green)",
                              closes_question="q-omd-barrier"),
        novel_target=NovelTarget(metric_name="omd_d5_barrier_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_naive_barrier_hangs_on_death_generation_broken_terminal_wakes_all",
        guard_mechanism="test_omd_d5_barrier_dimension_test_passes_in_real_substrate",
    ),
    ParallelNode(
        tag="semaphore_crash_safe", dimension="D4 crash-safe 카운팅 세마포어", parent="singulon_hardcore",
        evidence="omd/CONCURRENCY.md §D4 permit=lease, avail = max − count(ACTIVE) · tests/test_d4_semaphore.py",
        story="Dijkstra 카운팅 세마포어(P/V): 최대 K holder. NAIVE(획득 시 감소·해제 시 증가 정수)는 holder 가 해제 없이 "
              "crash 하면 permit 을 누수 — 가용량이 단조로 0 까지 침식(영구 용량손실). crash-safe 해법=permit-as-lease: "
              "avail 을 max − count(ACTIVE lease)로 *유도*해 죽은 holder permit 이 만료 시 구조적 회복. ",
        lit="Dijkstra 카운팅 세마포어 (P/V).",
        prom="core permit=lease, avail = max − count(ACTIVE); CONCURRENCY.md §D4",
        prediction=Prediction(metric_name="naive_semaphore_leaks_permit_on_crash", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 가 permit 을 lease 로 만들어 crash 누수를 구조적 회복(차원테스트 green)",
                              closes_question="q-omd-semaphore"),
        novel_target=NovelTarget(metric_name="omd_d4_semaphore_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_naive_semaphore_leaks_permit_lease_derived_avail_recovers",
        guard_mechanism="test_omd_d4_semaphore_dimension_test_passes_in_real_substrate",
    ),
    ParallelNode(
        tag="flag_crash_safe", dimension="D3 EPHEMERAL(=lease) vs LATCH(durable)", parent="singulon_hardcore",
        evidence="omd/CONCURRENCY.md §D3 플래그 두 종류 분리(EPHEMERAL=lease / LATCH 단조 done<merged) · tests/test_d3_flags.py",
        story="producer-소유 신호 하나에 두 상충 요구가 산다: 내구 사실(done/merged)은 producer 사망 후에도 "
              "*살아남아야*, 소유 신호(build_running)는 사망 시 *사라져야*(죽은 producer 소유 오신뢰·영구 hang 방지). "
              "단일-종류 플래그는 둘 중 하나를 반드시 어긴다(auto-clear=내구 분실, persist=소유 누수). OMD D3 = 두 종류 "
              "분리: LATCH(영속·단조·downgrade 거부·회수X) + EPHEMERAL(owned+TTL lease·사망 시 BROKEN/PRODUCER_DEAD 기상). "
              "lease 4투영 중 4번째(orbit/flag/semaphore/barrier).",
        lit="producer-owned ephemeral state(ZooKeeper ephemeral znode=세션 죽으면 소멸) vs durable latch",
        prom="core flag_set EPHEMERAL=flag_ephemeral lease(PRODUCER_DEAD 기상) / LATCH 단조 done<merged; §D3",
        prediction=Prediction(metric_name="single_kind_flag_cannot_serve_both_durable_and_ownership", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 가 EPHEMERAL(lease·PRODUCER_DEAD)+LATCH(단조·생존) 두 종류로 둘 다 충족(차원테스트 green)",
                              closes_question="q-omd-flag"),
        novel_target=NovelTarget(metric_name="omd_d3_flags_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_single_kind_flag_cannot_serve_both_durable_and_ownership_split_does",
        guard_mechanism="test_omd_d3_flags_dimension_test_passes_in_real_substrate",
    ),
    ParallelNode(
        tag="exactly_once_idempotency", dimension="D9 idempotency / exactly-once", parent="singulon_hardcore",
        evidence="omd/CONCURRENCY.md §D9 idempotency 테이블 + 의미 dedup(intent_key) · tests/test_d9_idempotency.py",
        story="RPC/MCP 의 현실 보장은 at-least-once(타임아웃 재시도). exactly-once *효과*는 수신측 idempotency key + dedup "
              "테이블로 회복(idempotent receiver, EIP). 없으면 재시도된 변이 op(merge)가 두 번 적용 → 이중효과/손상. OMD 는 "
              "각 변이 요청에 idempotency key, 재시도는 캐시 히트로 재적용 대신 캐시결과 반환.",
        lit="At-least-once delivery → exactly-once effect (idempotent receiver, Enterprise Integration Patterns).",
        prom="core idempotency 테이블 + intent_key 의미 dedup; CONCURRENCY.md §D9",
        prediction=Prediction(metric_name="at_least_once_retry_double_applies_effect", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 가 request_id/intent_key 로 재시도를 dedup 해 정확히-한번(차원테스트 green)",
                              closes_question="q-omd-idempotency"),
        novel_target=NovelTarget(metric_name="omd_d9_idempotency_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_retry_double_applies_merge_idempotency_key_makes_it_exactly_once",
        guard_mechanism="test_omd_d9_idempotency_dimension_test_passes_in_real_substrate",
    ),
)


def _score(n: ParallelNode, defect_closed: bool, mech_present: bool) -> dict:
    """독립 두 축을 judge() 에 먹인다 — improved(개선축)과 novel(novel축)이 *다른* 측정에서 온다."""
    measured = 0.0 if defect_closed else n.prediction.baseline_value   # 개선축: naive 실패 닫힘=baseline 아래
    novel_measured = 1.0 if mech_present else 0.0                      # novel축: 실 substrate 메커니즘=threshold 적중
    v = judge(n.prediction, measured, n.novel_target, novel_measured)
    return dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                verdict=v.verdict,
                status="CLOSED" if v.verdict == "progressive" else "OPEN",
                novel=v.novel, improved=v.improved, reason=v.reason)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 가 생성(손입력 0). 두 가드 미착륙 = 정직한 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES_DEF:
        if n.prediction is None:                                       # 하드코어 루트
            out.append(dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                            verdict="canonical_stage", status="ROOT"))
            continue
        have = (n.guard_defect in rc) or (n.guard_mechanism in rc)
        if not have:                                                   # receipt 미도래 = 정직한 pending
            out.append(dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                            verdict="pending(no-receipt)", status="OPEN",
                            note=f"guard 미착륙: defect={n.guard_defect} mechanism={n.guard_mechanism}"))
            continue
        out.append(_score(n, rc.get(n.guard_defect, False), rc.get(n.guard_mechanism, False)))
    return out


def _discrimination_demo() -> list[tuple[str, bool, bool, str]]:
    """judge() 가 4-칸을 *판별*함을 합성 receipt 로 증명(채점력 0 의 도그푸드 연극 아님).

      (defect닫힘, mech있음) → progressive | (defect닫힘, mech없음) → partial
      (defect열림, mech있음) → equivalent  | (defect열림, mech없음) → equivalent
    """
    probe = NODES_DEF[1]   # mutex_disjoint_orbits (대표 노드)
    cases = [(True, True), (True, False), (False, True), (False, False)]
    return [(f"defect={dc}, mech={mp}", dc, mp, _score(probe, dc, mp)["verdict"]) for dc, mp in cases]


# ── KG 거울용 — verdict 는 stage 라벨만, 진보성은 run() judge() 권위 ──
def _kg_node(n: ParallelNode) -> dict:
    pred = n.prediction
    return dict(
        tag=n.tag,
        verdict="canonical_stage",
        parent=n.parent,
        comment=f"[{n.dimension}] {n.story}  (근거 {n.evidence})  [LIT] {n.lit}"
                + (f"  [PROM] {n.prom}" if n.prom else ""),
        limitation=(f"novel≠개선 (독립 이중가드): improve={pred.metric_name} / novel={n.novel_target.metric_name}"
                    if pred else "하드코어 추측: SINGULON + 1-lease-4-투영 통일테제"),
        algorithm="omd-parallel-problemshift" if pred else "hardcore-conjecture",
        metric_value=None,
        questions=[pred.closes_question] if pred else [],
    )


NODES = [_kg_node(n) for n in NODES_DEF]

FRONTIER = [
    dict(name=n.prediction.closes_question, status="OPEN", closed_by=None,
         body=f"[{n.dimension}] {n.tag}: {n.prediction.novel_prediction} "
              f"(guards: defect={n.guard_defect} / mechanism={n.guard_mechanism}; 근거 {n.evidence})")
    for n in NODES_DEF if n.prediction is not None
]


if __name__ == "__main__":
    rc = receipt()
    landed = sum(1 for ok in rc.values() if ok)
    print(f"OMD-parallel guard receipt: {landed}/{len(rc) or 0} green ({_RECEIPT_GLOB})\n")
    rows = run(rc)
    n_open = sum(1 for r in rows if r["status"] == "OPEN")
    n_closed = sum(1 for r in rows if r["status"] == "CLOSED")
    for r in rows:
        if r["status"] == "ROOT":
            tail = "(하드코어 추측·루트)"
        elif r["verdict"].startswith("pending"):
            tail = r.get("note", "")
        else:
            tail = f"novel={r.get('novel')} improved={r.get('improved')} — {r.get('reason')}"
        print(f"  [{r['dimension']:42}] {r['tag']:28} → {r['verdict']:20} {tail}")
    n_findings = sum(1 for n in NODES_DEF if n.prediction is not None)
    print(f"\n총 {n_findings} 원리: OPEN(pending) {n_open} · CLOSED(progressive) {n_closed}. "
          f"verdict 전부 judge() 생성(손입력 0). naive 깨고 실 OMD 메커니즘 확증하면 자동 progressive.")
    print("\n판별력 증명 (_discrimination_demo) — 단일비트 하네스는 progressive/pending 만:")
    for label, _dc, _mp, verdict in _discrimination_demo():
        print(f"  {label:28} → {verdict}")
    print(f"\nKG 거울: {_TREE}")
