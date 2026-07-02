"""OMD 엔진 실효성(production-effectiveness) 라카토스 연구프로그램 (2026-07-02).

선행: omd_parallel_20260627_programme(고전 동시성 13원리 — 전부 progressive)이 P0
(서버권위 disjoint-lease 수학)의 건전성을 닫았다. 그런데 2026-06-30 실사고(consumer_b 가 OMD 를
우회해 공유브랜치 직접커밋 → +17 divergence)와 28-에이전트 audit 이 낸 피드백
(omd/docs/FEEDBACK_problems_20260630.md)은 *다른 층*의 반례를 냈다:

    "P0 가 아무리 정교해도 (P1) 아무도 안 쓰고 (P2) 공유파일에 약하고
     (P4) 안전기능 다수가 design-only 면 전부 무의미하다."

이 프로그램은 그 문제상황을 라카토스 problemshift 로 재서술한다:

  하드코어(hard core, 채점 안 함):
    "OMD 의 실가치 = P0 수학 × 채택. 보장은 opt-in 선의 위에서는 성립하지 않는다 —
     우회는 fail-loud 게이트로 감지되고, happy-path 는 원샷 동사로 접히고,
     design-only 갭은 실행가능한 oracle 로 기계화되어야 보장이 실재한다."

  보호대(protective belt) = FEEDBACK P1~P5 각각에 대한 OMD 의 응답 5건
    (bypass fail-loud 감사 · hot 공유파일 진단 · idem-GC · complete_task 원샷 ·
     strict-writeset commit 게이트) — 커밋 e29d7f2/40ab3f3/44b6187 로 착륙.

  정직 OPEN frontier = 아직 design-only 로 남은 것들: P2 3-way shared 레인 부재,
    P3 충돌=경보 의미론, §3.D 배리어-bound 재기동 단위복구, P6 SPOF/멀티프로세스 HA,
    그리고 P1 의 궁극 심판인 *현장 adoption_ratio 실측*.

★규율(omd_parallel/design_audit/frontier_fix 와 동일): 노드는 verdict 를 손입력하지
  않는다. 사전등록 Prediction + 독립 NovelTarget + 명명된 이중 가드만 들고 OPEN 으로
  앉는다. guard 미착륙 = 정직한 pending(가짜 green 0). verdict 는 전부 judge() 생성.

★★ 이중 가드(발견당 독립 두 오라클):
    guard_defect    → 개선축(measured)      : NAIVE(기제 제거/무감사) 모델이 그 실패를
                                              허용하고 원리 기제가 닫음을 revert-proof 로
                                              in-test 증명 (음성 오라클).
    guard_mechanism → novel축(novel_measured): 그 기제가 *실제 OMD substrate* 에 있음을
                                              독립 조달 — 실 OMD venv subprocess 로
                                              P-차원 테스트 rc==0 (양성 오라클).

  defect닫힘 ∧ mechanism존재 → progressive / defect닫힘 ∧ mechanism없음 → partial
  defect열림 ∧ mechanism존재 → equivalent  / 둘 다 미착륙 → pending(no-receipt)

# KG 거울: LakatosTree_OmdEngine_20260702
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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# OMD-engine guard 들이 착륙할 전용 파일 패턴(비면 전부 pending). P-문제당 1파일 × 2가드.
_RECEIPT_GLOB = "tests/test_omd_engine_*.py"
_TREE = "LakatosTree_OmdEngine_20260702"


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo .venv pytest 로 OMD-engine guard 테스트를 돌려
    {test_func: passed} 수집(self-report 아님). guard 파일 0개면 빈 dict → 전부 정직 pending."""
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
class EngineNode:
    tag: str
    dimension: str                # FEEDBACK P# / OMD 커밋 표지
    parent: str | None
    evidence: str                 # 실제 OMD file / test / 커밋 sha
    story: str                    # 실사고·설계부채 anomaly → OMD problemshift
    prom: str                     # 실 기제가 OMD 어디에 사는가
    prediction: Prediction | None = None      # 개선축(defect-closed)
    novel_target: NovelTarget | None = None   # novel축(real-substrate mechanism)
    guard_defect: str = ""        # 개선축 음성 오라클(revert-proof in-test 모델)
    guard_mechanism: str = ""     # novel축 양성 오라클(실 OMD venv subprocess)


NODES_DEF: tuple[EngineNode, ...] = (
    EngineNode(
        tag="adoption_hardcore", dimension="하드코어 / FEEDBACK 한줄결론", parent=None,
        evidence="omd/docs/FEEDBACK_problems_20260630.md §결론 — 'P0 가 아무리 정교해도 P1 이 안 풀리면 전부 무의미'",
        story="하드코어 추측: OMD 실가치 = P0 수학 × 채택. 보장은 opt-in 선의 위에서 성립하지 않는다 — "
              "우회 fail-loud·happy-path 원샷·design-only 갭의 oracle 기계화가 채택의 기계적 조건이다. "
              "보호대 5노드가 이 핵을 P1~P5 anomaly 로부터 지킨다. (루트 — 채점 안 함)",
        prom="omd_server/{bypass_audit,hot_files,harness}.py · core.complete_task/strict_writeset/idem_ttl · Makefile verify · CI",
    ),
    EngineNode(
        tag="p1_bypass_failloud", dimension="P1 우회 fail-loud 감사", parent="adoption_hardcore",
        evidence="omd_server/bypass_audit.py classify/gate/adoption_ratio · omd_server/harness.py · tests/test_p1_bypass.py · 커밋 e29d7f2/44b6187",
        story="실사고(2026-06-30): 에이전트들이 OMD 를 우회해 공유 통합브랜치 직접커밋 → +17 divergence. "
              "advisory 보장 + 우회감지 0 = '코드는 옳은데 아무도 안 쓴다'. problemshift: 보호 브랜치 "
              "first-parent 히스토리를 (머지×trailer×작성자)로 분류해 우회 4종(직접커밋/수동머지/위조 "
              "trailer/위조머지)을 fail-loud NO_GO + adoption_ratio 노출. CI/Makefile/warn-only hook 배선.",
        prom="omd_server/bypass_audit.py + harness.py(CI 진입점) + Makefile verify + .github CI 게이트",
        prediction=Prediction(metric_name="p1_bypass_commit_admitted_silently", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 우회감사가 분류 5종·위조 2종·adoption 임계 게이트를 실 git 위에서 통과(P1 차원테스트 green)",
                              closes_question="q-omd-p1-bypass"),
        novel_target=NovelTarget(metric_name="omd_p1_bypass_dimension_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_trailer_blind_audit_admits_bypass_classify_fails_loud",
        guard_mechanism="test_omd_p1_bypass_dimension_test_passes_in_real_substrate",
    ),
    EngineNode(
        tag="p2_hotfile_diagnosis", dimension="P2 hot 공유파일 경합 진단", parent="adoption_hardcore",
        evidence="omd_server/hot_files.py hot_file_audit/recommend_shared_globs/gate · tests/test_p2_p4_harness.py · 커밋 e29d7f2",
        story="disjoint-only 세계관은 env.py/modbus.py 같은 중앙파일의 직렬화·거부 마찰을 진단조차 못 한다"
              "(실사고 충돌 파일이 정확히 그 둘). problemshift: 히스토리 touch-빈도(커밋수·저자수)로 hot "
              "파일을 식별하고 shared glob 등급 후보를 fail-loud 권고 — disjoint 불변식은 유지한 채 최약 "
              "케이스를 가시화. (3-way merge 1급 레인 자체는 아직 OPEN — q-omd-p2-threeway-lane.)",
        prom="omd_server/hot_files.py (진단 게이트, max_hot NO_GO)",
        prediction=Prediction(metric_name="p2_hot_contention_undiagnosed", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD hot-file 감사가 실 git repo 에서 검출·정렬·임계 NO_GO 를 통과(P2 하네스 차원테스트 green)",
                              closes_question="q-omd-p2-hotfile"),
        novel_target=NovelTarget(metric_name="omd_p2_hotfile_dimension_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_disjoint_only_worldview_silent_on_hot_contention_audit_diagnoses",
        guard_mechanism="test_omd_p2_hotfile_dimension_test_passes_in_real_substrate",
    ),
    EngineNode(
        tag="p2_shared_lane_3way", dimension="P2 shared 레인 3-way 응결", parent="p2_hotfile_diagnosis",
        evidence="omd_server/core.py WRITE_MODES/_conflicts(shared 공존)/declare(shared)/shared_conflict · store.py tasks.shared · tests/test_p2_shared_lane.py · 커밋 c41356d(증분10) · 현장실측 field-hotfiles-jgbpc-20260702(hot 30파일)",
        story="진단(hot_files)만으론 hot 파일이 여전히 직렬화/거부(실행 레인 부재 — q-omd-p2-threeway-lane). "
              "problemshift: declare(shared=[...])+claim(mode='shared') 로 shared↔shared 동시 HELD 공존, "
              "응결은 git 3-way 자동병합, 같은 hunk 진짜 충돌은 shared_conflict(정상사건·retryable·rebase "
              "힌트, P3 부분 해소). 배타(write/read) 궤도의 '구조적 불가=경보' 의미론은 불변 — disjoint 는 "
              "여전히 1급시민, hot 파일만 별도 레인.",
        prom="core.WRITE_MODES + _conflicts shared 공존 + next_task shared-aware 게이트 + Phase C shared_conflict + MCP declare(shared=)",
        prediction=Prediction(metric_name="p2_hot_file_forced_serialization", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 가 공존/배타보존/3-way automerge/shared_conflict/경보 음성컨트롤 5종을 실 git 위에서 통과(증분10 차원테스트 green)",
                              closes_question="q-omd-p2-threeway-lane"),
        novel_target=NovelTarget(metric_name="omd_p2_shared_lane_dimension_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_disjoint_only_serializes_hot_file_shared_lane_parallelizes",
        guard_mechanism="test_omd_p2_shared_lane_dimension_test_passes_in_real_substrate",
    ),
    EngineNode(
        tag="p4_idem_gc", dimension="P4 idempotency 테이블 GC", parent="adoption_hardcore",
        evidence="omd_server/core.py _sweep_inline(idem_ttl 지난 DONE 정리) · tests/test_p4_idem_gc.py · 커밋 e29d7f2",
        story="CONCURRENCY §D9 자백 부채: 'request_id 행 무한 누적'. exactly-once 테이블이 GC 없이는 "
              "장수 코디네이터에서 무한성장(침묵 자원고갈). problemshift: 변환-불변식 3종을 지키는 TTL "
              "GC — 만료 DONE 삭제(누적 차단) · INFLIGHT 나이 무관 절대 보존 · ttl 이내 DONE replay "
              "캐시적중 유지(exactly-once 의미 보존).",
        prom="core._sweep_inline + Coordinator(idem_ttl=…) (기존 sweep 경로에 합류 — 별도 데몬 아님)",
        prediction=Prediction(metric_name="p4_idem_table_unbounded_growth", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD 가 만료삭제·INFLIGHT 보존·replay 유지·ttl=None GC-off 를 SQLite store 에서 통과(P4 차원테스트 green)",
                              closes_question="q-omd-p4-idemgc"),
        novel_target=NovelTarget(metric_name="omd_p4_idem_gc_dimension_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_gcless_idem_table_grows_unbounded_ttl_gc_bounds_it",
        guard_mechanism="test_omd_p4_idem_gc_dimension_test_passes_in_real_substrate",
    ),
    EngineNode(
        tag="p5_complete_task_oneshot", dimension="P5 complete_task 원샷 wrapper", parent="adoption_hardcore",
        evidence="omd_server/core.py complete_task(finish+connect 합성, MCP 노출) · tests/test_p5_complete_task.py · 커밋 40ab3f3/44b6187",
        story="7~8 verb happy-path 는 망각-스트랜드를 구조적으로 만든다: finish 망각 → 영구 IN_ORBIT·궤도 "
              "미해제·대기자 기아; connect 망각 → 영영 미통합. 채택(P1)을 갉는 마찰. problemshift: "
              "complete_task()=finish+connect(+push) 원샷, INV ok:True ⟺ MERGED, 단계 거부는 stage "
              "이름으로 fail-loud 전파(반쪽성공 위장 금지).",
        prom="core.complete_task + server.py MCP verb + connect auto-push(3cb47a7)",
        prediction=Prediction(metric_name="p5_forgotten_verb_strands_task", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD complete_task 가 실 git 원샷 머지·빈커밋·단계거부 stage 전파를 통과(P5 차원테스트 green)",
                              closes_question="q-omd-p5-oneshot"),
        novel_target=NovelTarget(metric_name="omd_p5_complete_task_dimension_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_forgotten_finish_strands_task_oneshot_merges_and_frees_orbit",
        guard_mechanism="test_omd_p5_complete_task_dimension_test_passes_in_real_substrate",
    ),
    EngineNode(
        tag="p5_strict_writeset_gate", dimension="P5 strict-writeset commit 게이트", parent="adoption_hardcore",
        evidence="omd_server/core.py commit(strict_writeset: 궤도-밖 자동 제외) · tests/test_p5_strict_writeset.py · 커밋 40ab3f3",
        story="write-set 위반이 commit 땐 경고만(advisory)·connect 에서야 거부 = 일 다 한 뒤 늦은 실패. "
              "problemshift: strict_writeset 이 commit-time 에 궤도-밖 경로를 자동 제외(히스토리 진입 "
              "차단·working tree 보존) — 위반이 커밋 경계에서 조기에 드러나고 connect 는 깨끗한 커밋만 "
              "받는다(late failure 0).",
        prom="core.commit(strict_writeset) + excluded_out_of_orbit 명시 회신",
        prediction=Prediction(metric_name="p5_writeset_violation_fails_late", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 OMD strict commit 이 실 git worktree 에서 궤도-밖 제외+working tree 보존을 통과(P5 strict 차원테스트 green)",
                              closes_question="q-omd-p5-strict"),
        novel_target=NovelTarget(metric_name="omd_p5_strict_writeset_dimension_test_passes", direction="higher", threshold=1.0),
        guard_defect="test_advisory_commit_fails_late_at_connect_strict_fails_early",
        guard_mechanism="test_omd_p5_strict_writeset_dimension_test_passes_in_real_substrate",
    ),
)


def _score(n: EngineNode, defect_closed: bool, mech_present: bool) -> dict:
    """독립 두 축을 judge() 에 먹인다 — improved(개선축)과 novel(novel축)이 다른 측정에서 온다."""
    measured = 0.0 if defect_closed else n.prediction.baseline_value
    novel_measured = 1.0 if mech_present else 0.0
    v = judge(n.prediction, measured, n.novel_target, novel_measured)
    return dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                verdict=v.verdict,
                status="CLOSED" if v.verdict == "progressive" else "OPEN",
                novel=v.novel, improved=v.improved, reason=v.reason)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 생성(손입력 0). 가드 미착륙 = 정직 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES_DEF:
        if n.prediction is None:
            out.append(dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                            verdict="canonical_stage", status="ROOT"))
            continue
        have = (n.guard_defect in rc) or (n.guard_mechanism in rc)
        if not have:
            out.append(dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                            verdict="pending(no-receipt)", status="OPEN",
                            note=f"guard 미착륙: defect={n.guard_defect} mechanism={n.guard_mechanism}"))
            continue
        out.append(_score(n, rc.get(n.guard_defect, False), rc.get(n.guard_mechanism, False)))
    return out


def _discrimination_demo() -> list[tuple[str, bool, bool, str]]:
    """judge() 가 4-칸을 판별함을 합성 receipt 로 증명(채점력 0 의 도그푸드 연극 아님)."""
    probe = NODES_DEF[1]   # p1_bypass_failloud (대표 노드)
    cases = [(True, True), (True, False), (False, True), (False, False)]
    return [(f"defect={dc}, mech={mp}", dc, mp, _score(probe, dc, mp)["verdict"]) for dc, mp in cases]


# ── KG 거울용 — verdict 는 stage 라벨만, 진보성은 run() judge() 권위 ──
def _kg_node(n: EngineNode) -> dict:
    pred = n.prediction
    return dict(
        tag=n.tag,
        verdict="canonical_stage",
        parent=n.parent,
        comment=f"[{n.dimension}] {n.story}  (근거 {n.evidence})"
                + (f"  [PROM] {n.prom}" if n.prom else ""),
        limitation=(f"novel≠개선 (독립 이중가드): improve={pred.metric_name} / novel={n.novel_target.metric_name}"
                    if pred else "하드코어 추측: 실가치 = P0 수학 × 채택"),
        algorithm="omd-engine-problemshift" if pred else "hardcore-conjecture",
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

# 정직 OPEN — 이번 회차가 닫지 *못한* 것들(FEEDBACK P2 잔여·P3·P4 잔여·P6 + 현장 심판).
OPEN_QUESTIONS = [
    dict(name="q-omd-p1-field-adoption",
         body="[P1 궁극심판] 실 현장 repo(예: consumer_b)의 통합브랜치에서 adoption_ratio 를 주기 실측해 "
              "임계(예: ≥0.9) 위에 서는가 — 감사 도구가 아니라 *현장 데이터*가 닫는 질문."),
    # q-omd-p2-threeway-lane: 증분10(p2_shared_lane_3way, 커밋 c41356d)이 닫음 — OPEN 목록에서 제거.
    dict(name="q-omd-p3-conflict-recovery",
         body="[P3] SERVER_SPEC §충돌='구조적 불가·경보' 의미론 vs 실코드베이스의 충돌=정상사건 — "
              "rollback+alarm 이 아니라 graceful 복구(재시도·rebase 안내) 경로가 필요한가."),
    dict(name="q-omd-p4-barrier-restart",
         body="[P4 잔여] CONCURRENCY §3.D 배리어-bound CONNECTING 재기동 단위복구 미구현 + "
              "TRIPPED→CONSUMED 수거 동사 미구현 — 크래시 시 배리어 부분 트립이 남는다."),
    dict(name="q-omd-p6-spof",
         body="[P6] 단일 coordinator+leader·SQLite store·repo-wide merge_token = SPOF. D14 는 "
              "단일프로세스 테스트만 — 멀티프로세스/파티션 integration 실측 부재. transitions 라이브러리 "
              "유지 공백 리스크 포함."),
]


if __name__ == "__main__":
    rc = receipt()
    landed = sum(1 for ok in rc.values() if ok)
    print(f"OMD-engine guard receipt: {landed}/{len(rc) or 0} green ({_RECEIPT_GLOB})\n")
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
        print(f"  [{r['dimension']:34}] {r['tag']:26} → {r['verdict']:20} {tail}")
    n_findings = sum(1 for n in NODES_DEF if n.prediction is not None)
    print(f"\n총 {n_findings} problemshift: OPEN(pending) {n_open} · CLOSED(progressive) {n_closed}. "
          f"verdict 전부 judge() 생성(손입력 0).")
    print(f"정직 OPEN frontier {len(OPEN_QUESTIONS)}건: "
          + ", ".join(q["name"] for q in OPEN_QUESTIONS))
    print("\n판별력 증명 (_discrimination_demo):")
    for label, _dc, _mp, verdict in _discrimination_demo():
        print(f"  {label:28} → {verdict}")
    print(f"\nKG 거울: {_TREE}")
