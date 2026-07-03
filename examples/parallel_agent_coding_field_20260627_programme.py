"""병렬-에이전트 코딩 *분야 자체*를 라카토스 연구프로그램으로 올린 메타-하네스 (2026-06-27).

요청: "병렬 프로그래밍 연구 자체 / 병렬-에이전트 코딩 분야 자체 연구를 라카토트리 위에." 이 하네스는
*병렬-에이전트(LLM 멀티에이전트) 소프트웨어 개발*을, 고전 병렬-프로그래밍 연구프로그램들에서 보호대를
*빌려오는* 하나의 메타 연구프로그램으로 서술한다(7-에이전트 분야조사 + 종합, 문헌 grounded).

  메타 하드코어(field_thesis): 비자명 SW 과제를 write-set 이 *서로소화 가능*하거나 충돌이 *탐지·해소
  가능*한 부분작업 DAG 로 분해할 수 있고, 추가 병렬 인지대역(역할분담·동시탐색) + 조정 substrate 가
  조정·머지 오버헤드를 병렬이득 아래로 누르며 *정확히* 통합되는 코드를 단일 순차 에이전트보다 빠르게
  낸다면, 병렬-에이전트 개발은 일관된 연구프로그램이다. 더 깊은 반증가능 약속: 고전 병렬-프로그래밍
  보장(linearizability·fencing·CALM-단조성·Kahn-결정성·work-depth)이 *비결정적·의미추론* 작업자
  (실패면이 의미적=양립불가 가정)에게로 *전이*된다 — 보호대는 빌려오고, 진짜 새 기여는 *텍스트
  무충돌 ↔ 의미 정확성* 간극을 ground-truth 오라클 없이 닫는 것.

★정직성(no fake green): 고전 7 프로그램은 *문헌 corroborated 역사* → canonical_knowledge(엔진 채점 아님,
  admin). 초점 프로그램(OMD/병렬-에이전트 코딩)은 **provisionally progressive but UNDER-CORROBORATED** —
  설계는 corroborated import 들이나 "선언적 disjointness 가 optimistic-merge 를 *이긴다*"는 use-novel
  사실은 *아직 head-to-head 미측정*. 그래서 초점 노드는 *유일하게 실측 corroborated 된* 협소 주장
  ("서로소 write-set ⇒ 무충돌 머지 by construction" — 본 세션의 실 4-에이전트 git 머지)에만 progressive,
  나머지(우월성·의미정확성)는 정직한 OPEN frontier. verdict 는 judge() 가 그 한 주장에만 부여.

# KG: span_parallel_agent_coding_field_20260627 / LakatosTree_ParallelAgentCodingField_20260627
# 분야조사 워크플로: 8 agent / 191k tok, 7 패러다임 전부 progressive + 종합(field_thesis/frontier/predictions).
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = "<WORKSPACE>/PROJECT/PI/lakatotree"
_RECEIPT_GLOB = "tests/test_pac_field_*.py"
_TREE = "LakatosTree_ParallelAgentCodingField_20260627"


def receipt() -> dict[str, bool]:
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
            res[m.group(1)] = res.get(m.group(1), True) and (m.group(2) == "PASSED")
    return res


# ── 고전 7 도너 연구프로그램 (문헌 corroborated = canonical_knowledge, 엔진 채점 아님) ──
@dataclass(frozen=True)
class DonorProgramme:
    key: str
    name: str
    appraisal: str            # 분야조사 판정 (전부 progressive)
    hard_core: str
    borrows_to_pac: str       # 병렬-에이전트 코딩(PAC)에 빌려주는 것
    lit: str


DONORS: tuple[DonorProgramme, ...] = (
    DonorProgramme("shared_memory", "Shared-memory concurrency", "progressive",
        "공유 가변 주소공간 + 메모리모델로 매개된 동기화; linearizability 정확성, 진행성 위계(blocking/lock-free/wait-free); CAS=Herlihy 보편성.",
        "OCC/CAS read-modify-rebase + STM read/write-set 충돌탐지: 두 diff 는 write-set 서로소면 가환 — 머지-or-retry + 심볼레벨 claim 입도.",
        "Herlihy consensus hierarchy(1991) · Michael-Scott queue(1996) · hazard pointers(2004,→C++26) · x86-TSO(Sewell 2010)"),
    DonorProgramme("message_passing", "Message-passing parallelism", "progressive",
        "공유 가변상태 없음, 통신으로 공유; actor/CSP/MPI. 'communicate-to-share'.",
        "actor let-it-crash + supervision tree(Erlang/OTP)로 실패 sub-agent 재기동; MPI collectives=map-then-reduce 집계; 코드베이스=공유상태엔 순수 메시지패싱 불가(교훈).",
        "Hoare CSP(1978) · Erlang/OTP AXD301 nine-nines · MPI collectives · session types"),
    DonorProgramme("data_parallel", "Data parallelism", "progressive",
        "동일 연산을 데이터 파티션에 동시 적용; SIMD/GPU-SIMT/MapReduce/fork-join; work-depth 비용모델.",
        "Blumofe-Leiserson work-stealing 동적 부하분산(idle agent 가 작업 steal); critical-path(편집 의존사슬) 최소화가 에이전트 수보다 중요; MapReduce speculative re-dispatch.",
        "Blumofe-Leiserson work-stealing(1999) · CUDA SIMT · MapReduce(2004) · Cilk/Rayon"),
    DonorProgramme("async_structured", "Async & structured concurrency", "progressive",
        "협력적 비동기(future/async-await/coroutine) + 구조적 동시성(nursery, 어휘적 수명·취소 전파).",
        "structured concurrency(Trio/TaskGroup/StructuredTaskScope): 어휘적 스코프로 orphan/runaway 에이전트 차단, ExceptionGroup 동시실패 집계, 하향 취소 전파.",
        "Hoare; Trio nurseries(2018) · Java Loom StructuredTaskScope · Kotlin coroutines"),
    DonorProgramme("distributed_coordination", "Distributed coordination & concurrency-control", "progressive",
        "부분동기·실패 하에 합의/lease/fencing/2PC/SSI/CRDT 로 안전·진행 보장; OMD 의 본거지.",
        "Kleppmann 단조 fencing token(lease-only 아님): stalled agent 의 stale 세대토큰은 clobber 못함(GC-pause=LLM stall 의 정석 fix); CALM 무조정 단조성; SSI antidependency=의미충돌 탐지로 승급.",
        "Paxos/Raft · Kleppmann fencing(2016) · CALM(Hellerstein) · SSI(Cahill 2008) · CRDT(Shapiro 2011)"),
    DonorProgramme("dataflow_streaming", "Dataflow & stream parallelism", "progressive",
        "그래프 구조에서 병렬성; dataflow/pipeline/stream, Kahn 결정성, watermark 진행추적.",
        "Chandy-Lamport/Flink 비동기 배리어 스냅샷=스웜 정지 없는 일관 체크포인트(롤백+commit fencing); timely pointstamp/watermark='이 영역 상류 에이전트 전원 완료' 추상.",
        "Kahn(1974) · Chandy-Lamport(1985) · Naiad/timely(2013) · Flink ABS"),
    DonorProgramme("parallel_agent_coding", "Parallel-agent coding (PAC, the field itself)", "progressive",
        "다중 LLM 에이전트가 한 코드베이스를 병렬 개발; write-set/orbit disjointness, 머지조정, task DAG, 코디네이터/MCP substrate.",
        "자기 corroborated 결과: worktree disjoint 격리가 char-레벨 머지충돌 제거 + 독립 부분작업 준선형 가속(worktree CI ~63%↓; CodeCRDT 100% 수렴·0 머지실패·~21%↑).",
        "CodeCRDT · MAST 실패분류(1600 trace) · worktree-parallel-CI · OMD(SINGULON)"),
)


# ── 초점 프로그램: OMD/PAC — provisionally progressive but UNDER-CORROBORATED ──
@dataclass(frozen=True)
class FocalClaim:
    tag: str
    claim: str
    status: str               # corroborated_empirical | OPEN
    evidence: str
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None
    guard: str = ""


FOCAL_CLAIMS: tuple[FocalClaim, ...] = (
    # 유일하게 *실측 corroborated* 된 협소 주장 — 본 세션의 실 4-에이전트 git 머지(CALM 무충돌 by construction).
    FocalClaim(
        tag="singulon_conflict_free_by_construction", status="corroborated_empirical",
        claim="선언적 서로소(입체) write-set ⇒ 무충돌 병렬 머지 by construction(CALM 단조 fragment) — 사후해소 아님.",
        evidence="omd scripts/multiagent_parallel_session.py: 4 물방울 서로소 모듈 실 worktree 개발+동시 connect → 실 git merge 4회·통합 4파일·충돌 0·merge_token max held=1·겹침 직렬화. tests/test_multiagent_session.py 회귀가드. + OOPTDD devloop validate14/14·run4/4.",
        prediction=Prediction(metric_name="singulon_conflict_free_unproven", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실 멀티에이전트 git 세션이 서로소 write-set 에서 머지충돌 0 을 by-construction 으로 보인다",
                              closes_question="q-pac-singulon-conflict-free"),
        novel_target=NovelTarget(metric_name="omd_real_multiagent_merge_zero_conflict", direction="higher", threshold=1.0),
        guard="test_pac_field_singulon_conflict_free_by_construction"),
    # 아래는 전부 정직한 OPEN — 설계는 import corroborated 이나 use-novel 사실 미측정.
    FocalClaim(tag="beats_optimistic_merge", status="OPEN",
        claim="선언적 a-priori disjointness 가 optimistic-merge-and-resolve(CodeCRDT/worktree-then-merge)를 N>=8 에서 충돌율·wall-clock 둘 다 이긴다.",
        evidence="head-to-head 벤치 미실행 — use-novel 사실 미corroborated (degenerating risk: glob 입도 too coarse).",),
    FocalClaim(tag="semantic_correctness", status="OPEN",
        claim="텍스트/CRDT 무충돌이 *의미* 정확성을 보장한다.",
        evidence="반증적: CodeCRDT 의미충돌 5-10% 잔존밴드, critic 에이전트는 producer 맹점 상속(MAST). ground-truth 오라클 부재 = 분야 최대 미해결.",),
)

# ── 프런티어: 반증가능 열린질문 Q1-Q8 (분야조사 종합) ──
FRONTIER_Q: tuple[tuple[str, str, str], ...] = (
    ("q-pac-q1-declarative-beats-optimistic", "OPEN",
     "선언적 glob disjointness(SINGULON)가 N>=8 에서 optimistic-merge 보다 충돌율↓ AND wall-clock↓; 둘 중 하나라도 안 이기거나 >30% 과제가 서로소 분할 불가면 FALSIFIED."),
    ("q-pac-q2-crossover-N", "OPEN",
     "긴밀결합 과제엔 조정+의미조정 비용이 병렬이득을 넘는 crossover N*(<=4)가 존재, 속도곡선 비단조 — N* 는 task DAG 정적 결합도로 사전예측 가능."),
    ("q-pac-q3-fencing-eliminates-stale", "corroborated_partial",
     "단조 fencing token 이 stalled agent 의 stale clobber 를 제거(lease-only 는 허용). OMD fencing TLA(UniqueLiveFence)+가드가 부분 corroborate; agent-stall>TTL 주입 e2e 측정은 OPEN."),
    ("q-pac-q4-textual-not-semantic", "OPEN",
     "텍스트/CRDT 무충돌이 의미정확성 미바운드 — critic 앙상블만으론 의미충돌 <1% 못 만듦(외부 오라클 없이); 만들면 FALSIFIED."),
    ("q-pac-q5-structured-concurrency-reduces-orphans", "OPEN",
     "구조적 동시성(어휘 nursery+하향취소+ExceptionGroup)이 orphan/runaway·연쇄오류(MAST ~37% 조정실패)를 unscoped spawn 대비 감소 — MAST 1600-trace A/B."),
    ("q-pac-q6-CALM-monotonic-lockfree", "OPEN",
     "CALM 정적분류로 단조 부분작업을 무조정 lock-free 실행해도 정확성 회귀 0, 가속 상한=DAG 단조비율(사전예측 천장)."),
    ("q-pac-q7-symbol-granularity", "OPEN",
     "glob/파일 입도는 too coarse(false-sharing 유사) — 심볼/함수 레벨 claim 이 같은 파일 서로소 영역의 spurious 직렬화를 줄여 유효병렬↑."),
    ("q-pac-q8-orbit-escape-enforcement", "OPEN",
     "선언 write-set 예측정확도가 binding constraint — 탐색/리팩터 과제의 orbit-escape >10% 이라 *런타임 강제*(궤도밖 쓰기 거부, OMD §D10) 필요; 미강제로 95%+ 유지되면 FALSIFIED."),
)

# ── use-novelty 베팅 P1-P5 (이 프로그램의 새 예측, 대부분 OPEN) ──
PREDICTIONS_P: tuple[tuple[str, str, str], ...] = (
    ("p1-construction-not-gamble", "OPEN(partly-corroborated)",
     "disjoint 증명-후-dispatch + 잔여만 fencing → N>=8 에서 CodeCRDT 의 -39.4%~+21% 산포를 partitionable 부분의 일관 양(+) 가속으로(머지 by construction). [본 세션이 '무충돌 by construction' 부분만 corroborate]"),
    ("p2-failure-histogram-shifts", "OPEN",
     "조정 substrate 성숙 시 잔여 실패가 조정/텍스트→*의미*(양립불가 인터페이스 가정)로 이동 — MAST 분포가 inter-agent-misalignment→task-verification 으로 shift(반증가능한 histogram 이동 예측)."),
    ("p3-fencing-idempotency-exactly-once", "OPEN(partly-corroborated)",
     "fencing token + idempotency-key dedup → 에이전트 재시도 exactly-once-effective, 중복구현·이중커밋 0(bhgman ingest dedup 거울). [OMD idempotency/fencing 가드가 메커니즘 corroborate]"),
    ("p4-amdahl-boundary-predictable", "OPEN",
     "task DAG critical-path/결합도로 *사전* Amdahl 경계 계산 — 예측이득<조정비면 단일에이전트 라우팅이 always-parallel 을 Pareto 지배('don't build multi-agents'=긴밀결합 특수사례)."),
    ("p5-cross-paradigm-composition", "OPEN",
     "단일 도너 불충분·교차합성 필요충분: {structured-concurrency 수명}+{CALM 분류}+{Kleppmann fencing}+{work-stealing}+{async-barrier 스냅샷}이 임의 단일패러다임 substrate 를 속도∧정확성에서 이긴다 — 단일패러다임이 맞먹으면 FALSIFIED."),
)

BIGGEST_GAP = (
    "의미충돌 *오라클* 간극: 개별적으로 그럴듯하고 텍스트 무충돌·테스트 통과하지만 *양립불가 인터페이스/계약 "
    "가정*에 선 둘+ 패치의 머지는 *틀린데*, 이를 잡을 ground-truth 오라클이 없다(critic=producer 맹점 상속, "
    "CRDT=수렴 보장하나 정확성 아님; CodeCRDT 5-10% 의미충돌 잔존, MAST 사양/검증 ~42%). 모든 고전 도너는 "
    "텍스트/상태 충돌만 푼다 — 가장 근접한 도구는 distributed-coordination SSI 의 'dangerous antidependency'를 "
    "*의미*로 승급(공유 파일 아니라 공유 *계약/인터페이스* write-skew 탐지)이나, 의도의 기계검증 사양(오라클 "
    "역할 타입/계약)이 필요하고 현 시스템엔 없다. ⇒ PAC 는 처리량/조정엔 progressive, 의미정확성엔 정직히 UNRESOLVED."
)


def _score_focal(c: FocalClaim, corroborated: bool) -> dict:
    if c.prediction is None:                         # OPEN 주장 — 채점 안 함
        return dict(tag=c.tag, verdict="OPEN(frontier)", status="OPEN", claim=c.claim, evidence=c.evidence)
    measured = 0.0 if corroborated else c.prediction.baseline_value
    novel_measured = 1.0 if corroborated else 0.0
    v = judge(c.prediction, measured, c.novel_target, novel_measured)
    return dict(tag=c.tag, verdict=v.verdict,
                status="CLOSED" if v.verdict == "progressive" else "OPEN",
                novel=v.novel, improved=v.improved, claim=c.claim, reason=v.reason)


def run(rc: dict[str, bool] | None = None) -> dict:
    rc = receipt() if rc is None else rc
    focal = []
    for c in FOCAL_CLAIMS:
        if c.prediction is None:
            focal.append(_score_focal(c, False))
        elif c.guard not in rc:
            focal.append(dict(tag=c.tag, verdict="pending(no-receipt)", status="OPEN",
                              note=f"guard 미착륙: {c.guard}", claim=c.claim))
        else:
            focal.append(_score_focal(c, rc.get(c.guard, False)))
    return dict(
        donors=[dict(key=d.key, name=d.name, verdict="canonical_knowledge", appraisal=d.appraisal,
                     borrows=d.borrows_to_pac, lit=d.lit) for d in DONORS],
        focal=focal,
        frontier=[dict(name=q, status=s, body=b) for q, s, b in FRONTIER_Q],
        predictions=[dict(name=p, status=s, body=b) for p, s, b in PREDICTIONS_P],
        biggest_gap=BIGGEST_GAP,
    )


# KG 거울용 노드 리스트
NODES = (
    [dict(tag="field_hardcore", verdict="canonical_stage", parent=None,
          comment="메타 하드코어: 병렬-에이전트 개발 = 분해가능 DAG + 빌린 보호대(고전 보장의 비결정작업자 전이) + 텍스트무충돌↔의미정확성 간극 닫기",
          algorithm="conjecture")]
    + [dict(tag=f"donor_{d.key}", verdict="canonical_knowledge", parent="field_hardcore",
            comment=f"[{d.appraisal}] {d.name}: {d.hard_core} [BORROWS] {d.borrows_to_pac} [LIT] {d.lit}",
            algorithm="literature-corroborated") for d in DONORS]
    + [dict(tag=f"focal_{c.tag}",
            verdict=("canonical_stage" if c.status == "corroborated_empirical" else "open_question"),
            parent="donor_parallel_agent_coding",
            comment=f"[{c.status}] {c.claim}  (근거 {c.evidence})",
            algorithm="omd-empirical" if c.prediction else "frontier") for c in FOCAL_CLAIMS]
)

FRONTIER = ([dict(name=q, status=s, body=b) for q, s, b in FRONTIER_Q]
            + [dict(name=p, status="OPEN", body=b) for p, s, b in PREDICTIONS_P])


if __name__ == "__main__":
    rc = receipt()
    r = run(rc)
    print(f"=== 병렬-에이전트 코딩 분야 연구프로그램 (LakatoTree) ===\n")
    print("고전 7 도너 프로그램 (문헌 corroborated = canonical_knowledge):")
    for d in r["donors"]:
        print(f"  [{d['appraisal']:11}] {d['name']}")
    print(f"\n초점 프로그램 OMD/PAC — provisionally progressive, UNDER-CORROBORATED:")
    for c in r["focal"]:
        print(f"  {c['tag']:42} → {c['verdict']}")
    n_open = sum(1 for q in r["frontier"] if q["status"].startswith("OPEN"))
    print(f"\n프런티어 {len(r['frontier'])} 열린질문 ({n_open} OPEN, 1 corroborated_partial) + use-novelty 베팅 {len(r['predictions'])}")
    print(f"\n최대 간극: {r['biggest_gap'][:160]}...")
    print(f"\nKG 거울: {_TREE}")
