"""Application service for programme-level tree operations.

# KG: seed-lkt-engine-route-programme-extract-20260616
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timezone
from functools import wraps
from typing import Any

import psycopg2.extras
from fastapi import HTTPException

from lakatos.quant.calibrate import brier_score, calibration_error, log_score
from lakatos.io.reconcile import (
    HistoryPayloadError,
    canonical_history_payload,
    validate_history_record,
)
from lakatos.verdict.judge import NovelTarget, Prediction, judge
from lakatos.programme.explore import rank_questions as default_rank_questions
from lakatos.programme.heuristic import (appraise_and_plan, branch_pressure as _branch_pressure_pct,
                               expected_progress_gain, realized_reward)
from lakatos.programme.lifecycle import lifecycle_state
from lakatos.quant.metrics import branch_inputs
from lakatos.verdicts import (ENGINE_VERDICTS, FORCEFUL_SOURCES,
                              FRONTIER_PROGRESS_VERDICTS,
                              SCORED_PROGRESS_VERDICTS, SCRIPTED_VERDICTS,
                              TESTED_CORE_VERDICTS, receipt_content_sha)
from lakatos.programme.series import series_from_path
from lakatos.programme.kuhn import incumbent_degenerating
from lakatos.programme.stack import evaluate_stack
from lakatos.programme.tradition import (ResearchTradition, TraditionCommitment, TraditionRevision,
                                         appraise_tradition_revision)
from lakatos import assurance
from server.contexts.tree.advice import advice_for, with_advice
from server.contexts.tree.cycle_budget import budget_state, remaining_budget
from server.contexts.tree.diagnostics import diagnose_required_constraints
from server.contexts.tree.schemas import (
    ArtifactIn,
    CritiqueIn,
    CycleIn,
    ElementIn,
    ElementUseIn,
    FoundationRequirementIn,
    NodeIn,
    PredictionIn,
    TestResultIn,
    TraditionAppraiseIn,
    TraditionIn,
)
from server.contexts.tree.verdict_intents import (
    VerdictIntentError,
    validate_verdict_intent_group,
)
from server.ports import HistoryAppend, KgQuery, PgFactory


TreeDataProvider = Callable[[str], dict]
MetricsProvider = Callable[[dict], dict]
NodeAdder = Callable[[str, NodeIn, str], dict]
PredictionRegistrar = Callable[[str, str, PredictionIn], dict]
TestResultSubmitter = Callable[[str, str, TestResultIn], dict]
CycleCompensator = Callable[[str, str, str], str]
CycleClaimReleaser = Callable[[str, str, str], None]
CritiqueAdder = Callable[[str, str, CritiqueIn], dict]
StandingProvider = Callable[[str, str], dict]
ArtifactInserter = Callable[[dict], Any]
QuestionRanker = Callable[[list[dict], int], list[dict]]


def _serialized_ledger_command(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        scope = getattr(self, 'ledger_scope', None) or (lambda: nullcontext())
        with scope():
            return method(self, *args, **kwargs)

    return wrapped


_CYCLE_RESULT_VERDICTS = SCRIPTED_VERDICTS | ENGINE_VERDICTS
recoverable_cycle_lakatos_values = frozenset({
    "n/a",
    "unverified",
    "progressive",
    "progressive_conditional",
    "degenerating",
    "different_programme",
    "ambiguous",
    "hard_core_violated_structural",
    "reproducibility_refuted",
    "novel_not_server_anchored",
    "provisional_stale_engine",
})


def issuer_calibration_annotation(cal: dict, min_n: int) -> dict:
    """표시-only 투명성 (credence-loop 연구 CONDITIONAL_CLOSE, 2026-07-21): 랭킹 credence 를 *발급한*
    판관의 측정 보정품질(ECE, n)을 랭킹 값 *옆에* 노출한다. ★융합 아님 — 이 값은 dominates()/
    branch_credence/CRITERIA 에 절대 들어가지 않는다(realized ECE→랭킹 credence 융합은 범주오류[pred_credence
    예보과신 ≠ verdict-라벨발 branch_credence] + tiny-n[n=0~10] + confirm_monotone 정리 RED 로 held-out
    falsifier 뒤로 defer). n<min_n(=ece_gate_min_n) 은 고정-bin ECE 소표본 고분산 → abstain(날조 0 금지).
    독자가 "이 랭킹 credence 는 ECE=X(n=Y) 판관이 발급"임을 *보게* 할 뿐, 보정됨을 주장하지 않는다.
    """
    if cal['n'] < min_n:
        return dict(ece=None, n=cal['n'], status='abstain_small_n',
                    note=f'보정표본 n={cal["n"]}<{min_n} — ECE noise(고정-bin 소표본 고분산), 인증 보류')
    return dict(ece=cal.get('calibration_error'), n=cal['n'], status='surfaced',
                note='이 랭킹 credence 를 발급한 판관의 측정 ECE(표시-only, 랭킹 값 미변경). '
                     'ECE 높음=발급자 과신 — 보정됨 주장 아님.')


class ProgrammeService:
    """Owns programme calibration, direction, cycle, foundation, and history operations."""

    # KG: seed-lkt-engine-route-programme-extract-20260616

    def __init__(
        self,
        *,
        kg: KgQuery,
        hist: HistoryAppend,
        pg: PgFactory,
        tree_data: TreeDataProvider,
        compute_metrics: MetricsProvider,
        add_node: NodeAdder,
        compensate_cycle_node: CycleCompensator,
        release_cycle_claim: CycleClaimReleaser,
        register_prediction: PredictionRegistrar,
        submit_test_result: TestResultSubmitter,
        add_critique: CritiqueAdder,
        standing: StandingProvider,
        insert_artifact: ArtifactInserter,
        rank_questions: QuestionRanker = default_rank_questions,
        ledger_ready: Callable[[], None] | None = None,
        ledger_scope=None,
    ):
        self.kg = kg
        self.hist = hist
        self.pg = pg
        self.tree_data = tree_data
        self.compute_metrics = compute_metrics
        self.add_node = add_node
        self.compensate_cycle_node = compensate_cycle_node
        self.release_cycle_claim = release_cycle_claim
        self.register_prediction = register_prediction
        self.submit_test_result = submit_test_result
        self.add_critique = add_critique
        self.standing = standing
        self.insert_artifact = insert_artifact
        self.rank_questions = rank_questions
        self.ledger_ready = ledger_ready or (lambda: None)
        self.ledger_scope = ledger_scope or (lambda: nullcontext())

    def calibration(self, name: str) -> dict:
        # ADR D2(2026-07-28): receipt-gate 비대칭 수리 — raw novel_confirmed 는 무영수증
        # self-report 를 포함해 판관 보정 측정을 오염시켰다(tree_metrics 의 neutralize 게이트와
        # 의미론 정렬). FORCEFUL(scripted/engine) 판정만 + 결정론 정렬(순차 소비 전제).
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e)
                     WHERE e.pred_credence IS NOT NULL AND e.novel_confirmed IS NOT NULL
                           AND e.novel_registered = true
                           AND e.verdict_source IN $forceful
                     RETURN e.pred_credence AS p, e.novel_confirmed AS o
                     ORDER BY e.judged_at, e.tag""", tree=name,
                       forceful=sorted(FORCEFUL_SOURCES))
        fc = [(r['p'], 1 if r['o'] else 0) for r in rows]
        return dict(n=len(fc), brier=round(brier_score(fc), 4), log_score=round(log_score(fc), 4),
                    calibration_error=round(calibration_error(fc), 4),
                    scope='tree_level',
                    note='Brier 0=완벽, log=overconfidence 강벌, ECE=보정오차. novel 등록 예측만, '
                         '트리(발급자) 수준. FORCEFUL(영수증) 판정 결과만 계상 — 무영수증 '
                         'self-report 는 보정 측정에서 제외(ADR D2), judged_at 결정론 정렬')

    def directions(self, name: str) -> dict:
        td = self.tree_data(name)
        can = next((r for r in td['nodes'] if r['verdict'] == 'CANONICAL'), None)
        metrics = self.compute_metrics(td)
        cred = (metrics.get('bayes') or {}).get('canonical_credence') or 0.5
        # crisis→explore(#9): 퇴행깊이(가지 연속 비진보 최대) ≥ k = Kuhn 위기(가설공간 확장 신호) → 탐색 폭 확대.
        #   정본 leaf 는 진보판결이라 그 경로 consec 은 무용 → 트리 전역 max_degeneration_depth 를 쓴다.
        crisis = incumbent_degenerating([], int(metrics.get('max_degeneration_depth', 0)))
        opens = [q for q in td['frontier'] if q['status'] == 'OPEN']

        def _num(q, k, d):
            value = q.get(k)
            return d if value is None else value

        # positive heuristic 신호 — 질문→연 노드 역매핑. 정본/진보 노드가 연 질문 = 살아있는 전선.
        progressive = FRONTIER_PROGRESS_VERDICTS   # verdicts.py SSOT (engine-unify 2026-07-23)
        front_qnames = {qn for r in td['nodes'] if r.get('verdict') in progressive
                        for qn in (r.get('questions') or [])}
        novel_qnames = {qn for r in td['nodes'] if r.get('novel_registered')
                        for qn in (r.get('questions') or [])}
        # 가지 미해결-문제압 + 실현 reward(bandit 학습). 실패해도 directions 는 살린다.
        pressure, reward = 0.0, None
        try:
            bi = branch_inputs(td['nodes'], td['frontier'])
            pressure = _branch_pressure_pct(bi)
            reward = realized_reward(int(bi.get('prediction_hits', 0)), int(bi.get('nodes_spent', 0)))
        except (KeyError, HTTPException):
            pass

        qmeta = []
        for q in opens:
            # ★ VoI 분자: q 에 명시 expected_gain 있으면 존중, 없으면 tree 구조+학습 reward 로 실계산
            #   (전엔 0.1 하드코딩 = 가짜 분자, positive heuristic 미배선).
            eg = q.get('expected_gain')
            if eg is None:
                eg = expected_progress_gain(
                    canonical_credence=cred, problem_pressure=pressure, learned_reward=reward,
                    on_canonical_frontier=q['name'] in front_qnames,
                    has_novel_target=q['name'] in novel_qnames)
            # finding D2: None은 비용 미측정 상태로 보존한다. ranker가 가짜 단위비용을 만들지 않는다.
            qmeta.append(dict(name=q['name'], body=(q['body'] or '')[:160],
                              expected_gain=eg, cost=q.get('cost'),
                              credence=cred, n_visits=_num(q, 'n_visits', 1),
                              on_canonical_frontier=q['name'] in front_qnames,
                              gain_source='explicit' if q.get('expected_gain') is not None else 'derived'))
        total_visits = max(sum(q['n_visits'] for q in qmeta), len(qmeta), 1)
        ranked = self.rank_questions(qmeta, total_visits=total_visits, crisis=crisis)
        for q in ranked:
            q['branch_from'] = (can or {}).get('tag')
            q['suggested_tag'] = q['name'].replace('q-', 'exp-') + '-try1'
        from lakatos.grounding import GROUNDED
        # 투명성 표시-only: 이 랭킹 credence 를 발급한 판관의 측정 ECE 를 값 *옆에* 노출(융합 아님 —
        #   dominates/branch_credence 미변경, credence-loop CONDITIONAL_CLOSE 2026-07-21). ★display-only
        #   fail-safe: 보정 조회 실패는 directions core 응답을 절대 깨지 않는다(pressure/reward 와 동일 규율).
        try:
            _issuer_cal = issuer_calibration_annotation(
                self.calibration(name), GROUNDED['ece_gate_min_n']['value'])
        except Exception:   # noqa: BLE001 — display-only: 보정 조회(KG/auth 등) 실패가 directions core 를 절대 못 깬다
            _issuer_cal = dict(ece=None, n=0, status='unavailable',
                               note='보정 조회 실패 — 표시 생략(display-only fail-safe)')
        return dict(canonical=(can or {}).get('tag'), canonical_credence=cred,
                    issuer_calibration=_issuer_cal,
                    branch_pressure=round(pressure, 4), crisis_exploration=crisis,
                    ranked_directions=ranked,
                    protocol=['① prediction 사전등록(구조적 novel_metric/threshold + script_sha 권장)',
                              '② 변경 하나 실행', '③ test_result 스크립트 채점', '④ 자동 판결+질문 close'])

    def trust_view(self, name: str) -> dict:
        """P6 배선 — 트리의 실 인터넷 관측 그래프에 eigentrust 돌려 글로벌 출처신뢰 산출(queryable).
        coverage.mode 가 graph_propagated/seed_dominated/uniform_unlearned 로 정직하게 현 데이터 두께 표기."""
        import json as _json
        from lakatos.trust import global_source_trust
        rows = self.kg(
            "MATCH (t:LakatosTree {name:$n})-[:HAS_NODE]->(e)-[:HAS_RESEARCH_EVENT]->"
            "(ev:ResearchEvent {realm:'internet'}) RETURN e.tag AS node, ev.payload AS payload",
            n=name)
        observations = []
        for r in rows or []:
            try:
                p = _json.loads(r.get('payload') or '{}')
            except (ValueError, TypeError):
                p = {}
            observations.append(dict(
                source=(p.get('url') or p.get('source_type') or '').strip(),
                source_type=p.get('source_type') or '', node=r.get('node') or '',
                corroboration_score=float(p.get('corroboration_score') or 0.0)))
        result = global_source_trust(observations)
        result['n_observations'] = len(observations)
        return result

    def heuristic_view(self, name: str, leaf: str | None = None) -> dict:
        """MSRP 연구정책 — negative(hard core 보호) + positive(생성된 다음 수). directions 의 상위층:
        directions=VoI 우선순위, heuristic=무슨 종류의 수를(ABANDON/PUSH/PROBE/PRIORITIZE) 왜."""
        td, bi, _ = self.branch_stack(name, leaf)
        metrics = self.compute_metrics(td)
        bi = dict(bi)
        bi['canonical_credence'] = (metrics.get('bayes') or {}).get('canonical_credence') or 0.5
        # 나생문 #5: free-text hard_core 를 가정별로 토큰화(judgement_service 와 동형) — 단일 blob 으로 넘기면
        #   _probe_moves 의 'already-probed' 제외가 dead-wired(metric_name 네임스페이스와 교차 불가)되고 PROBE 가
        #   hard-core 전체를 단일 stale 타깃으로만 낸다. 가정별로 쪼개 per-assumption probe + 억제가 살아나게.
        raw_hc = td.get('hard_core')
        if isinstance(raw_hc, (list, tuple)):
            hard_core = tuple(str(c).strip() for c in raw_hc if str(c).strip())
        elif raw_hc:
            hard_core = tuple(t.strip() for t in str(raw_hc).replace(';', ',').replace('\n', ',').split(',') if t.strip())
        else:
            hard_core = ()
        tested = tuple(r.get('metric_name') for r in td['nodes']
                       if r.get('verdict') in TESTED_CORE_VERDICTS and r.get('metric_name'))
        return appraise_and_plan(nodes=td['nodes'], frontier=td['frontier'], branch=bi,
                                 hard_core=hard_core, tested_core=tested)

    def stack_view(self, name: str, leaf: str | None = None) -> dict:
        _, bi, sv = self.branch_stack(name, leaf)
        return dict(leaf=bi['leaf'], inputs={k: bi[k] for k in
                    ('consecutive_nonprogressive', 'nodes_spent', 'prediction_hits',
                     'problem_balance_windowed')}, **self.stack_dict(sv))

    def lifecycle_view(self, name: str, leaf: str | None = None) -> dict:
        _, bi, sv = self.branch_stack(name, leaf)
        ls = lifecycle_state(bi['verdicts'], sv, bi['novel_registered_recent'],
                             bi['problem_balance_windowed'], bi['canonical_improved_recent'])
        return dict(leaf=bi['leaf'], state=ls.state, reason=ls.reason, regret=ls.regret,
                    window=ls.window, stack=self.stack_dict(sv))

    def series_view(self, name: str, leaf: str | None = None) -> dict:
        """프로그램-시계열 진단(#5) — 정본경로 verdict 시퀀스를 series_from_path 로 평가.
        authority=diagnostic_only(promotion_authority=False) — verdict 권위 절대 부여 안 함.
        개념(internal/external)·비교 anomaly(rival) 입력은 아직 KG 미배선이라 coverage 로 *명시*한다
        (overclaim 금지). bridge 가 laudan.conceptual_problem_score 를 노드마다 실호출(현재 0 입력)하므로
        고아였던 laudan 진단 함수가 런타임 caller 를 얻는다. 풍부한 입력 배선은 후속 prom."""
        _, bi, _ = self.branch_stack(name, leaf)
        ap = series_from_path(bi['path'])
        # #① step 5 bridge: 기록된 전통 수정(appraise_tradition)의 개념압력 합을 diagnostic 으로 surface.
        #   tradition authoring+appraise 가 있어야 비-0 → 고아였던 tradition→series 경로가 살아난다(diagnostic_only).
        tcp = self._tradition_conceptual_pressure(name)
        return dict(
            leaf=bi['leaf'], trend=ap.trend, authority=ap.authority,
            promotion_authority=ap.promotion_authority, steps=ap.steps,
            progressive_count=ap.progressive_count, nonprogressive_count=ap.nonprogressive_count,
            off_axis_count=ap.off_axis_count, problem_balance_total=ap.problem_balance_total,
            rival_anomaly_count=ap.rival_anomaly_count,
            conceptual_problem_score=ap.conceptual_problem_score, reasons=list(ap.reasons),
            problem_balance_windowed=bi['problem_balance_windowed'],
            tradition_conceptual_pressure=round(tcp, 4),   # #① Laudan 연구전통 개념압력(diagnostic_only)
            coverage={
                'verdict_sequence': 'wired',
                'conceptual_problem': ('tradition_wired' if tcp > 0 else 'not_projected_from_kg'),
                'rival_anomaly': 'not_projected_from_kg',        # RivalProblemRecord 미수집(후속)
                'note': 'diagnostic_only — series=정본경로 verdict + tradition 개념압력(있으면). verdict 권위 없음.',
            },
        )

    # ── #① Laudan 연구전통 authoring + series bridge (diagnostic-only) ──────────────────────
    def _tradition_conceptual_pressure(self, name: str) -> float:
        """기록된 전통 수정의 개념압력 합(series bridge 입력). 전통/수정 없으면 0.0.
        best-effort — 진단 add-on 이라 kg 실패가 series 를 죽이지 않는다(directions 패턴 일관)."""
        try:
            rows = self.kg(
                "MATCH (t:LakatosTree {name:$tree})-[:HAS_TRADITION]->(:ResearchTradition)"
                "-[:HAS_TRADITION_REVISION]->(rv:TraditionRevision) "
                "RETURN coalesce(sum(rv.conceptual_pressure), 0.0) AS cp", tree=name)
            return float(rows[0]['cp']) if rows and rows[0].get('cp') is not None else 0.0
        except Exception:   # noqa: BLE001 — 진단 add-on; kg 미가용 시 0.0(중립)
            return 0.0

    def set_tradition(self, name: str, t: TraditionIn) -> dict:
        """연구전통 + commitments 영속(KG). tradition.py 도메인 불변식으로 검증(enum 위반 422)."""
        import json
        try:
            ResearchTradition(tradition_id=t.tradition_id, name=t.name)
            for c in t.commitments:
                TraditionCommitment(commitment_id=c.commitment_id, kind=c.kind, statement=c.statement,
                                    revisability=c.revisability, source_refs=tuple(c.source_refs))
        except ValueError as e:
            raise HTTPException(422, str(e))
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})
                  SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                  WITH t
                  MERGE (rt:ResearchTradition {tradition_id:$tid})
                  SET rt.name=$tname, rt.commitments=$commitments,
                      rt.ontology_commitments=$onto, rt.methodology_rules=$meth, rt.exemplars=$exemplars,
                      rt.accepted_problem_types=$probs, rt.background_theories=$bg,
                      rt.revision_policy=$rpol, rt.compatibility_notes=$cnotes, rt.updated_at=$ts
                  MERGE (t)-[:HAS_TRADITION]->(rt)
                  RETURN rt.tradition_id AS id""",
                       tree=name, tid=t.tradition_id, tname=t.name,
                       commitments=json.dumps([c.model_dump() for c in t.commitments], ensure_ascii=False),
                       onto=list(t.ontology_commitments), meth=list(t.methodology_rules),
                       exemplars=list(t.exemplars), probs=list(t.accepted_problem_types),
                       bg=list(t.background_theories), rpol=t.revision_policy, cnotes=t.compatibility_notes,
                       ts=datetime.now(timezone.utc).isoformat())
        if not rows:
            raise HTTPException(404, f'트리 없음: {name}')
        self.hist(name, 'tradition_set', t.tradition_id, {'commitments': len(t.commitments)})
        return {'ok': True, 'tradition_id': t.tradition_id, 'commitments': len(t.commitments),
                'authority': 'diagnostic_only'}

    def get_tradition(self, name: str) -> dict:
        import json
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_TRADITION]->(rt:ResearchTradition)
                  RETURN rt.tradition_id AS tid, rt.name AS tname, rt.commitments AS commitments,
                         rt.ontology_commitments AS onto, rt.methodology_rules AS meth,
                         rt.exemplars AS exemplars, rt.accepted_problem_types AS probs,
                         rt.background_theories AS bg, rt.revision_policy AS rpol,
                         rt.compatibility_notes AS cnotes""", tree=name)
        if not rows:
            raise HTTPException(404, f'전통 없음: {name}')
        r = rows[0]
        return dict(tradition_id=r['tid'], name=r['tname'],
                    commitments=json.loads(r['commitments'] or '[]'),
                    ontology_commitments=r['onto'] or [], methodology_rules=r['meth'] or [],
                    exemplars=r['exemplars'] or [], accepted_problem_types=r['probs'] or [],
                    background_theories=r['bg'] or [], revision_policy=r['rpol'] or '',
                    compatibility_notes=r['cnotes'] or '', authority='diagnostic_only')

    def appraise_tradition(self, name: str, a: TraditionAppraiseIn) -> dict:
        """전통 commitment 수정 진단(append-only 기록 → series bridge 누적). authority=diagnostic_only."""
        import json
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_TRADITION]->(rt:ResearchTradition)
                  RETURN rt.commitments AS commitments""", tree=name)
        if not rows:
            raise HTTPException(404, f'전통 없음: {name}')
        by_id = {c['commitment_id']: c for c in json.loads(rows[0]['commitments'] or '[]')}
        cdata = by_id.get(a.commitment_id)
        if not cdata:
            raise HTTPException(404, f'commitment 없음: {a.commitment_id}')
        try:
            commitment = TraditionCommitment(
                commitment_id=cdata['commitment_id'], kind=cdata['kind'],
                statement=cdata.get('statement', ''), revisability=cdata.get('revisability', 'routine'),
                source_refs=tuple(cdata.get('source_refs') or ()))
            ap = appraise_tradition_revision(commitment, TraditionRevision(
                target_commitment_id=a.commitment_id, operation=a.operation, reason=a.reason,
                receipt_refs=tuple(a.receipt_refs), compatibility_claim=a.compatibility_claim))
        except ValueError as e:
            raise HTTPException(422, str(e))
        self.kg("""MATCH (t:LakatosTree {name:$tree})
              SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
              WITH t
              MATCH (t)-[:HAS_TRADITION]->(rt:ResearchTradition)
              CREATE (rt)-[:HAS_TRADITION_REVISION]->(:TraditionRevision {
                  target:$target, operation:$op, outcome:$outcome, conceptual_pressure:$cp,
                  methodology_pressure:$mp, ontology_pressure:$onp, created_at:$ts})""",
                tree=name, target=a.commitment_id, op=a.operation, outcome=ap.outcome,
                cp=ap.conceptual_pressure, mp=ap.methodology_pressure, onp=ap.ontology_pressure,
                ts=datetime.now(timezone.utc).isoformat())
        self.hist(name, 'tradition_appraise', a.commitment_id, {'outcome': ap.outcome})
        return dict(outcome=ap.outcome, conceptual_pressure=ap.conceptual_pressure,
                    methodology_pressure=ap.methodology_pressure, ontology_pressure=ap.ontology_pressure,
                    reasons=list(ap.reasons), authority=ap.authority)

    # ── G3(git-흡수): 봉인 1-verb 정직 사이클 보조 — incore trial + 보상 롤백 ──────────────
    def _cycle_trial(self, c: CycleIn) -> dict:
        """incore trial(merge-ort.h:86 이식) — judge 순수함수로 *쓰기 0* 사전 판정.

        첫 write 전에 4xx 대부분(무측정 novel·척도 위반 등)을 격추한다 = git 의 '빈 커밋 거부'.
        반환은 미리보기이지 영수증이 아니다(사전등록 없는 판정은 rung 이 될 수 없음)."""
        nt = None
        if c.novel_metric and c.novel_direction and c.novel_threshold is not None:
            nt = NovelTarget(metric_name=c.novel_metric, direction=c.novel_direction,
                             threshold=c.novel_threshold)
        try:
            pred = Prediction(metric_name=c.metric_name, direction=c.direction,
                              baseline_value=c.baseline, noise_band=c.noise_band,
                              novel_prediction='(incore cycle trial)')
            v = judge(pred, c.measured, novel_target=nt, novel_measured=c.novel_measured)
        except ValueError as e:
            raise with_advice(HTTPException(422, str(e)))
        return {'verdict_preview': v.verdict, 'delta_preview': round(v.delta, 4),
                'novel_preview': v.novel}

    # ── PROM16 S1/S5: 루프-경계 사이클 예산 (내구 파생, 인메모리 카운터 아님) ────────────────
    def _cycle_budget_state(self, name: str) -> tuple[int | None, int]:
        """(cycle_budget, scored_nodes) — 정본은 cycle_budget 모듈(SSOT). 여기선 위임만 한다.

        예산을 여기서 재유도하면 run_cycle 이 보는 술어와 judgement_service 초크포인트가 보는 술어가
        갈라진다(그게 첫 구현이 무너진 자리다) — 세는 곳과 막는 곳은 같은 정의를 봐야 한다.
        술어·fail-safe·잔여 비대칭의 정직한 서술 전부: server/contexts/tree/cycle_budget.py 참조.
        """
        return budget_state(self.kg, name)

    @staticmethod
    def _cycle_claim(
        name: str,
        c: CycleIn,
        document: list | None = None,
    ) -> str:
        document = [name, c.model_dump()] if document is None else document
        return "cycle-" + hashlib.sha256(
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def _recover_cycle_result(
        self,
        name: str,
        tag: str,
        claim: str,
    ) -> tuple[dict, dict, str, list[tuple[str, dict, str]]] | None:
        """Read an exact verdict-transaction intent for whole-command retry."""

        event_id = f"ob-cycle-result-{claim.removeprefix('cycle-')}"
        try:
            rows = self.kg(
                """MATCH (o:OutboxEntry {id:$event_id})
                   MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                   OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(rec:VerdictReceipt {
                     receipt_sha:e.current_receipt_sha})
                   OPTIONAL MATCH (t)-[:HAS_FRONTIER]->(q:OpenQuestion {
                     name:rec.target_id})
                   OPTIONAL MATCH (q)-[:HAS_CLOSURE]->(closure:QuestionClosure {
                     id:e.current_receipt_sha})
                   CALL {
                     WITH e
                     OPTIONAL MATCH (group_o:OutboxEntry {
                       causal_group:e.current_receipt_sha})
                     WITH [entry IN collect(group_o {
                       .id, .tree, .op, .node_tag, .payload, .status,
                       .created_at, .reason, .applied_at, .receipt_sha,
                       .causal_group, .causal_index, .request_sha256
                     }) WHERE entry.id IS NOT NULL] AS group_outboxes
                     RETURN group_outboxes
                   }
                   RETURN o.id AS id, o.tree AS tree, o.op AS op,
                          o.node_tag AS node_tag, o.payload AS payload,
                          o.status AS status, o.created_at AS created_at,
                          o.reason AS reason, o.applied_at AS applied_at,
                          o.receipt_sha AS outbox_receipt_sha,
                          o.causal_group AS cycle_causal_group,
                          o.causal_index AS cycle_causal_index,
                          e.current_receipt_sha AS current_receipt_sha,
                          e.verdict AS current_verdict,
                          e.verdict_source AS current_verdict_source,
                          e.lakatos_status AS current_lakatos_status,
                          e.metric_value AS current_metric_value,
                          rec.receipt_sha AS bound_receipt_sha,
                          rec.tree AS receipt_tree, rec.tag AS receipt_tag,
                          rec.target_id AS receipt_target_id,
                          rec.verdict AS receipt_verdict,
                          rec.verdict_source AS receipt_verdict_source,
                          rec.metric_name AS receipt_metric_name,
                          rec.metric_value AS receipt_metric_value,
                          rec.novel_confirmed AS receipt_novel_confirmed,
                          rec.lakatos_status AS receipt_lakatos_status,
                          rec.judged_at AS receipt_judged_at,
                          rec.judge_script_sha AS receipt_judge_script_sha,
                          rec.prev_receipt_sha AS receipt_prev_receipt_sha,
                          rec.measurement_grade AS receipt_measurement_grade,
                          rec.engine_rule_sha AS receipt_engine_rule_sha,
                          rec.comment_sha AS receipt_comment_sha,
                          rec.replay_status AS receipt_replay_status,
                          rec.replay_reason AS receipt_replay_reason,
                          rec.regenerated_metric AS receipt_regenerated_metric,
                          rec.judge_script_path AS receipt_judge_script_path,
                          rec.result_path AS receipt_result_path,
                          rec.result_sha256 AS receipt_result_sha256,
                          rec.measurement_lock_sha AS receipt_measurement_lock_sha,
                          rec.source_script_path AS receipt_source_script_path,
                          rec.source_result_path AS receipt_source_result_path,
                          rec.history_payload_sha256 AS receipt_history_payload_sha256,
                          rec.prediction_temporal_commitment_sha256 AS
                            receipt_prediction_temporal_commitment_sha256,
                          q.status AS question_state,
                          q.closed_by AS question_closed_by,
                          q.closed_events AS question_closed_events,
                          closure.id AS closure_id,
                          closure.closed_by AS closure_closed_by,
                          closure.at AS closure_at,
                          closure.tree AS closure_tree,
                          closure.question AS closure_question,
                          closure.trigger AS closure_trigger,
                          closure.verdict AS closure_verdict,
                          closure.receipt_sha AS closure_receipt_sha,
                          COUNT { MATCH (q)-[:HAS_CLOSURE]->
                            (:QuestionClosure {id:e.current_receipt_sha})-
                            [:CAUSED_BY]->(rec) } AS closure_bound_count,
                          COUNT { MATCH (:QuestionClosure {
                            id:e.current_receipt_sha}) } AS closure_global_count,
                          COUNT { MATCH (e)-[:CLOSES_QUESTION]->(q) }
                            AS closes_rel_count,
                          head([(e)-[rel:CLOSES_QUESTION]->(q) |
                            rel.receipt_sha]) AS closes_rel_receipt_sha,
                          head([(e)-[rel:CLOSES_QUESTION]->(q) |
                            rel.verdict]) AS closes_rel_verdict,
                          head([(e)-[rel:CLOSES_QUESTION]->(q) |
                            rel.at]) AS closes_rel_at,
                          group_outboxes
                   """,
                event_id=event_id,
                tree=name,
                tag=tag,
            )
        except Exception:  # noqa: BLE001 - compatibility seam; real writes still fail closed later
            return None
        if not rows:
            return None
        if len(rows) != 1:
            raise HTTPException(500, "cycle result intent cardinality conflict")
        row = rows[0]
        if (
            row.get("id") != event_id
            or row.get("tree") != name
            or row.get("op") != "cycle_result"
            or row.get("node_tag") != tag
            or row.get("reason") != "cycle_result_commit_intent"
            or not (
                (row.get("status") == "pending" and row.get("applied_at") is None)
                or (row.get("status") == "applied" and row.get("applied_at") is not None)
            )
        ):
            raise HTTPException(500, "cycle result intent immutable binding conflict")
        try:
            if not isinstance(row.get("created_at"), str):
                raise ValueError("created_at must be ISO text")
            parsed_created_at = datetime.fromisoformat(row["created_at"])
            if parsed_created_at.utcoffset() is None:
                raise ValueError("created_at must include a timezone")
        except (TypeError, ValueError) as exc:
            raise HTTPException(500, "cycle result intent timestamp corrupt") from exc

        def unique_object(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError(f"duplicate key: {key}")
                out[key] = value
            return out

        try:
            raw_payload = row.get("payload")
            payload = json.loads(raw_payload, object_pairs_hook=unique_object)
            if canonical_history_payload(payload) != raw_payload:
                raise ValueError("cycle result payload is not canonical")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(500, "cycle result intent payload corrupt") from exc
        result = payload.get("result") if isinstance(payload, dict) else None
        dependent_ids = (
            payload.get("dependent_history_event_ids")
            if isinstance(payload, dict)
            else None
        )
        if (
            not isinstance(payload, dict)
            or set(payload) != {
                "cycle_claim", "cycle_request", "dependent_history_event_ids",
                "result", "verdict_receipt_sha",
            }
            or payload.get("cycle_claim") != claim
            or not isinstance(payload.get("cycle_request"), list)
            or len(payload["cycle_request"]) != 2
            or payload["cycle_request"][0] != name
            or not isinstance(payload["cycle_request"][1], dict)
            or hashlib.sha256(json.dumps(
                payload["cycle_request"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")).hexdigest() != claim.removeprefix("cycle-")
            or not isinstance(result, dict)
            or set(result) != {
                "delta",
                "lakatos",
                "novel",
                "novel_server_anchored",
                "verdict",
            }
            or not isinstance(payload.get("verdict_receipt_sha"), str)
            or len(payload["verdict_receipt_sha"]) != 64
            or row.get("outbox_receipt_sha") != payload["verdict_receipt_sha"]
            or row.get("current_receipt_sha") != payload["verdict_receipt_sha"]
            or row.get("bound_receipt_sha") != payload["verdict_receipt_sha"]
            or row.get("receipt_tree") != name
            or row.get("receipt_tag") != tag
            or row.get("cycle_causal_group") != payload["verdict_receipt_sha"]
            or row.get("cycle_causal_index") != 2
            or row.get("current_verdict_source") != "scripted"
            or row.get("current_verdict") != result.get("verdict")
            or row.get("current_lakatos_status") != result.get("lakatos")
            or row.get("receipt_verdict_source") != "scripted"
            or row.get("receipt_verdict") != result.get("verdict")
            or row.get("receipt_lakatos_status") != result.get("lakatos")
            or not isinstance(dependent_ids, list)
            or not dependent_ids
            or any(
                not isinstance(item, str) or not item.startswith("ob-")
                for item in dependent_ids
            )
            or len(set(dependent_ids)) != len(dependent_ids)
            or not isinstance(result.get("verdict"), str)
            or result.get("verdict") not in _CYCLE_RESULT_VERDICTS
            or not isinstance(result.get("lakatos"), str)
            or result.get("lakatos") not in recoverable_cycle_lakatos_values
            or type(result.get("delta")) not in (int, float)
            or not math.isfinite(float(result["delta"]))
            or result.get("novel") is not None
               and type(result.get("novel")) is not bool
            or type(result.get("novel_server_anchored")) is not bool
        ):
            raise HTTPException(500, "cycle result intent payload shape conflict")
        receipt_fields = {
            "tree": row.get("receipt_tree"),
            "tag": row.get("receipt_tag"),
            "target_id": row.get("receipt_target_id"),
            "verdict": row.get("receipt_verdict"),
            "verdict_source": row.get("receipt_verdict_source"),
            "metric_name": row.get("receipt_metric_name"),
            "metric_value": row.get("receipt_metric_value"),
            "novel_confirmed": row.get("receipt_novel_confirmed"),
            "lakatos_status": row.get("receipt_lakatos_status"),
            "judged_at": row.get("receipt_judged_at"),
            "judge_script_sha": row.get("receipt_judge_script_sha"),
            "prev_receipt_sha": row.get("receipt_prev_receipt_sha"),
            "measurement_grade": row.get("receipt_measurement_grade"),
            "engine_rule_sha": row.get("receipt_engine_rule_sha"),
            "comment_sha": row.get("receipt_comment_sha"),
            "replay_status": row.get("receipt_replay_status"),
            "replay_reason": row.get("receipt_replay_reason"),
            "regenerated_metric": row.get("receipt_regenerated_metric"),
            "judge_script_path": row.get("receipt_judge_script_path"),
            "result_path": row.get("receipt_result_path"),
            "result_sha256": row.get("receipt_result_sha256"),
            "measurement_lock_sha": row.get("receipt_measurement_lock_sha"),
            "source_script_path": row.get("receipt_source_script_path"),
            "source_result_path": row.get("receipt_source_result_path"),
            "history_payload_sha256": row.get(
                "receipt_history_payload_sha256"
            ),
            "prediction_temporal_commitment_sha256": row.get(
                "receipt_prediction_temporal_commitment_sha256"
            ),
        }
        if receipt_content_sha(receipt_fields) != payload["verdict_receipt_sha"]:
            raise HTTPException(500, "cycle verdict receipt content hash mismatch")
        if dependent_ids[0] != f"ob-test-result-{payload['verdict_receipt_sha']}":
            raise HTTPException(500, "cycle dependency order conflict")
        if len(dependent_ids) > 2 or (
            len(dependent_ids) == 2
            and dependent_ids[1]
                != f"ob-question-close-{payload['verdict_receipt_sha']}"
        ):
            raise HTTPException(500, "cycle dependency manifest conflict")
        dependent_rows = row.get("group_outboxes")
        if not isinstance(dependent_rows, list):
            raise HTTPException(500, "cycle causal group snapshot missing")
        by_id = {dep.get("id"): dep for dep in (dependent_rows or [])}
        if (
            len(by_id) != len(dependent_rows or [])
            or len(by_id) != len(dependent_ids) + 1
            or event_id not in by_id
        ):
            raise HTTPException(500, "cycle dependency manifest is incomplete")

        current_snapshot = {
            "current_receipt_sha": row.get("current_receipt_sha"),
            "verdict": row.get("current_verdict"),
            "verdict_source": row.get("current_verdict_source"),
            "lakatos_status": row.get("current_lakatos_status"),
            "metric_value": row.get("current_metric_value"),
        }
        receipt_snapshot = dict(receipt_fields)
        receipt_snapshot["receipt_sha"] = row.get("bound_receipt_sha")
        closure_snapshot = {
            "question_state": row.get("question_state"),
            "question_closed_by": row.get("question_closed_by"),
            "question_closed_events": row.get("question_closed_events"),
            "closure_id": row.get("closure_id"),
            "closure_closed_by": row.get("closure_closed_by"),
            "closure_at": row.get("closure_at"),
            "closure_tree": row.get("closure_tree"),
            "closure_question": row.get("closure_question"),
            "closure_trigger": row.get("closure_trigger"),
            "closure_verdict": row.get("closure_verdict"),
            "closure_receipt_sha": row.get("closure_receipt_sha"),
            "closure_bound": row.get("closure_bound_count") == 1,
            "closure_global_count": row.get("closure_global_count"),
            "closes_rel_count": row.get("closes_rel_count"),
            "closes_rel_receipt_sha": row.get("closes_rel_receipt_sha"),
            "closes_rel_verdict": row.get("closes_rel_verdict"),
            "closes_rel_at": row.get("closes_rel_at"),
        }
        try:
            validated_group = validate_verdict_intent_group(
                tree=name,
                tag=tag,
                receipt_sha=payload["verdict_receipt_sha"],
                receipt=receipt_snapshot,
                current=current_snapshot,
                outboxes=list(dependent_rows or []),
                closure=closure_snapshot,
                require_cycle=True,
            )
        except VerdictIntentError as exc:
            raise HTTPException(
                500, f"cycle verdict intent group corrupt: {exc}"
            ) from exc
        if validated_group.cycle_payload != payload:
            raise HTTPException(500, "cycle result intent changed during recovery")
        dependent_history: list[tuple[str, dict, str]] = []
        for index, dependent_id in enumerate(dependent_ids):
            dep = by_id.get(dependent_id) or {}
            expected_op = "test_result" if index == 0 else "question_close"
            expected_reason = f"{expected_op}_commit_intent"
            try:
                if not isinstance(dep.get("created_at"), str):
                    raise ValueError("created_at must be ISO text")
                dependent_created_at = datetime.fromisoformat(dep["created_at"])
                if dependent_created_at.utcoffset() is None:
                    raise ValueError("created_at must include a timezone")
                dependent_payload = json.loads(
                    dep.get("payload"), object_pairs_hook=unique_object
                )
                if canonical_history_payload(dependent_payload) != dep.get("payload"):
                    raise ValueError("dependent payload is not canonical")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise HTTPException(500, "cycle dependency payload corrupt") from exc
            if not (
                dep.get("tree") == name
                and dep.get("op") == expected_op
                and dep.get("node_tag") == tag
                and dep.get("reason") == expected_reason
                and dep.get("receipt_sha") == payload["verdict_receipt_sha"]
                and dep.get("causal_group") == payload["verdict_receipt_sha"]
                and dep.get("causal_index") == index
                and (
                    (dep.get("status") == "pending" and dep.get("applied_at") is None)
                    or (dep.get("status") == "applied"
                        and dep.get("applied_at") is not None)
                )
            ):
                raise HTTPException(500, "cycle dependency immutable binding conflict")
            if index == 0 and not (
                dependent_payload.get("receipt_sha")
                    == payload["verdict_receipt_sha"]
                and dependent_payload.get("verdict") == result.get("verdict")
                and dependent_payload.get("lakatos") == result.get("lakatos")
                and dependent_payload.get("delta") == result.get("delta")
                and dependent_payload.get("novel") == result.get("novel")
                and dependent_payload.get("novel_server_anchored")
                    == result.get("novel_server_anchored")
                and dependent_payload.get("cycle_claim") == claim
                and dependent_payload.get("cycle_request_sha256")
                    == claim.removeprefix("cycle-")
            ):
                raise HTTPException(500, "cycle test-result dependency semantic mismatch")
            if index == 1 and not (
                dependent_payload.get("receipt_sha")
                    == payload["verdict_receipt_sha"]
                and dependent_payload.get("verdict") == result.get("verdict")
                and dependent_payload.get("trigger") == "ADJUDICATED"
                and dependent_payload.get("question")
                    == row.get("receipt_target_id")
            ):
                raise HTTPException(500, "cycle question-close dependency semantic mismatch")
            dependent_history.append((expected_op, dependent_payload, dependent_id))
        return dict(result), payload, event_id, dependent_history

    @staticmethod
    def _cycle_multi_run_summary(c: CycleIn) -> dict | None:
        """Derive the deterministic multi-run view bound by the cycle claim."""

        if not c.multi_run:
            return None
        from lakatos.programme.multi_run import multi_run_collect

        vals = list(c.multi_run_values or [])
        if len(vals) < 2:
            raise HTTPException(
                422,
                detail={
                    'error': 422,
                    'reason': 'multi_run_requires_n_ge_2',
                    'note': (
                        'multi_run=True 이면 multi_run_values 길이 ≥2 필요'
                        '(default OFF 유지)'
                    ),
                },
            )
        summary = multi_run_collect(
            lambda i: float(vals[i]), multi_run=True, n=len(vals)
        )
        if abs(float(summary['mean']) - float(c.measured)) > 1e-6:
            raise HTTPException(
                422,
                detail={
                    'error': 422,
                    'reason': 'multi_run_mean_mismatch',
                    'mean': summary['mean'],
                    'measured': c.measured,
                    'note': 'measured 는 multi_run_values 평균과 일치해야 함',
                },
            )
        return summary

    def _complete_recovered_cycle(
        self,
        name: str,
        c: CycleIn,
        recovered: tuple[dict, dict, str, list[tuple[str, dict, str]]],
    ) -> dict:
        """Finish projections/critique after an exact committed cycle replay."""

        res, cycle_payload, cycle_event_id, dependent_history = recovered
        for op, payload, event_id in dependent_history:
            projected = self.hist(
                name,
                op,
                c.tag,
                payload,
                event_id=event_id,
            )
            if projected is False:
                raise HTTPException(
                    503, f"{op} history pending; causal successors deferred"
                )
        cycle_projected = self.hist(
            name,
            "cycle_result",
            c.tag,
            cycle_payload,
            event_id=cycle_event_id,
        )
        if cycle_projected is False:
            raise HTTPException(503, "cycle history projection remains pending")
        for critique in c.critiques:
            self.add_critique(name, c.tag, critique)
        budget, used = self._cycle_budget_state(name)
        remaining = remaining_budget(budget, used)
        out = dict(
            tree=name,
            tag=c.tag,
            verdict=res.get("verdict"),
            novel=res.get("novel"),
            lakatos=res.get("lakatos"),
            delta=res.get("delta"),
            critiques=len(c.critiques),
            standing=self.standing(name, c.tag),
            idempotent=True,
            note="durable cycle_result exact replay — committed verdict reused",
        )
        if remaining is not None:
            out["remaining_budget"] = remaining
        multi_run_summary = self._cycle_multi_run_summary(c)
        if multi_run_summary is not None:
            out["multi_run"] = multi_run_summary
        out["novel_server_anchored"] = res["novel_server_anchored"]
        if res.get("lakatos") in (
            "novel_not_server_anchored",
            "provisional_stale_engine",
        ):
            tip = advice_for(res["lakatos"])
            if tip:
                out["advice"], out["advice_mode"] = tip, "suggest-only"
        return out

    @_serialized_ledger_command
    def run_cycle(self, name: str, c: CycleIn) -> dict:
        """봉인 1-verb 정직 사이클(git-흡수 G3, P3 porcelain 경제학 역전) — 사전등록→채점→제출→영수증을
        client 호출 *한 번*에. note 경로(2-verb)보다 정직경로가 구조적으로 싸다.

        ① incore trial(쓰기 0)이 먼저 4xx 격추 · dry_run=True 면 여기서 미리보기 반환(영수증 아님).
        ② prediction 영수증 전 실패는 exact creation-marker 소유분만 보상 삭제한다.
        ③ prediction 영수증이 첫 내구점: submit/critique 실패는 노드+receipt를 보존한다.
        4xx 엔 advice 레지스트리가 다음 명령을 제안(suggest-only, 게이트 우회 off-switch 없음).
        ⓪ 루프-경계 예산(PROM16 S1/S5, opt-in): 트리가 cycle_budget 을 선언했고 소진됐으면 *실행
           대신* 타입 거부(status='budget_exhausted') — 첫 write 전. 미선언=무제한(응답 shape 불변)."""
        # Preflight the *entire* command before recovery reads, node ownership,
        # prediction receipts, or any other mutation. Neo4j accepts text that
        # PostgreSQL JSONB cannot represent; discovering it after the prediction
        # receipt would strand an irreversible partial cycle.
        cycle_request = [name, c.model_dump()]
        try:
            validate_history_record(
                name,
                "cycle_result",
                c.tag,
                {"cycle_request": cycle_request},
                "ob-cycle-result-preflight",
            )
        except HistoryPayloadError as exc:
            raise HTTPException(
                422,
                "cycle request contains text PostgreSQL JSONB cannot represent",
            ) from exc
        claim = self._cycle_claim(name, c, cycle_request)
        if not c.dry_run:
            # Recovery projection and every durable cycle mutation share the
            # same audited writer authority as direct ledger verbs.  This is
            # deliberately before the first recovery read/add-node step.
            self.ledger_ready()
            recovered = self._recover_cycle_result(name, c.tag, claim)
            if recovered is not None:
                return self._complete_recovered_cycle(name, c, recovered)

        # ⓪ 예산 게이트 — trial(판정) 보다도 먼저. 못 도는 사이클은 미리보기조차 오도이고, 루프
        #    드라이버는 이유코드로 즉시 멈춰야 한다.
        #    범위(과대주장 금지): 이 게이트는 run_cycle 표면의 *조기* 거부일 뿐이고, 강제 자체는
        #    judgement_service 초크포인트(submit_test_result/set_verdict)의 같은 게이트가 한다 —
        #    그래서 3-verb 경로로 갈아타도 채점은 안 된다(verb-교체 우회 없음). 이 선조회는 빠른 UX와
        #    dry-run 표시용이고, 실제 권위는 submit_test_result/set_verdict 의 첫 mutation statement가
        #    트리 락 아래 다시 세는 LOCKED_BUDGET_GUARD다. KG 장애·동시 writer 에서 mutation은 fail-closed.
        #    상향에는 명시 확인(및 attestor 트리 write-cert)이 필요하지만 운영자 authn 구분은 아직 없다.
        #    add_node/register_prediction 은 예산 밖이라 소진 트리도 구조 write 는 계속 된다.
        budget, used = self._cycle_budget_state(name)
        remaining = remaining_budget(budget, used)   # 미선언=None(무제한) · 레거시 초과분은 0 clamp
        if remaining == 0:
            return {'tree': name, 'tag': c.tag, 'status': 'budget_exhausted',
                    # 'scored_nodes' — 세는 대상의 정직한 이름. 이건 *판결받은 노드 수*이지 호출횟수가
                    #   아니다(cycles_used 는 미채점 노드까지 세던 구 술어 시절의 거짓 이름이었다).
                    'remaining_budget': 0, 'cycle_budget': budget, 'scored_nodes': used,
                    'note': f'트리 채점 예산 {budget} 소진(채점노드 {used}) — 실행 안 함(쓰기 0). '
                            f'submit_result/set_verdict 도 같은 예산으로 429 거부된다. '
                            f'예산을 올리거나(create_tree cycle_budget) 새 트리로 분기할 것'}
        # multi_run opt-in (default OFF): validate N≥2 values ↔ measured=mean; never flips default.
        multi_run_summary = self._cycle_multi_run_summary(c)
        trial = self._cycle_trial(c)
        if c.dry_run:
            out = dict(tree=name, tag=c.tag, dry_run=True, **trial,
                       note='incore trial — 영수증 아님·아무것도 쓰지 않음. 제출은 dry_run=false 로')
            if remaining is not None:
                out['remaining_budget'] = remaining   # 미리보기는 쓰기 0 = 소모 0(차감 없음)
            # R2-NOVEL(s3): FF1 강등 사전 예고 — 트리 정책 1-read 를 *fail-safe* 로 결합. 조회 실패
            #   (KG-less fake/운영 단절)=힌트 생략: 불확실한 정책으로 예고를 지어내지 않는다.
            #   ※ 이 read 는 dry_run 분기 전용. (2026-07-15 정정: "비-dry 경로엔 새 kg 쿼리 0" 이라던
            #     종전 주석은 더 이상 참이 아니다 — PROM16 예산 게이트가 _cycle_budget_state 1-read 를
            #     양 경로 공통으로 추가했다. 조회 실패 시 dry-run 힌트는 생략하며, live write 권위는
            #     judgement_service 의 lock-held mutation guard다.)
            try:
                rows = self.kg('MATCH (t:LakatosTree {name:$tree}) '
                               'RETURN t.require_novel_anchor AS require_novel_anchor, '
                               't.assurance_tier AS assurance_tier', tree=name)
            except Exception:   # noqa: BLE001 — 진단 힌트 전용: 실패=생략(dry_run 은 반드시 산다)
                rows = None
            if rows:
                pol = rows[0]
                # judgement_service.submit_test_result 의 무장 규칙 미러(SSOT=assurance 디스패치):
                #   tier 게이트(receipted/anchored) ∨ 트리 opt-in 플래그(FF1 phase2).
                armed = (assurance.GATE_NOVEL_ANCHOR in assurance.gates_for(
                             'submit_test_result', assurance.resolve_tier(pol.get('assurance_tier')))
                         or bool(pol.get('require_novel_anchor')))
                cross_metric_novel = c.novel_metric is not None and c.novel_metric != c.metric_name
                out['would_demote_to_partial'] = bool(
                    armed and cross_metric_novel and trial.get('novel_preview')
                    and not c.novel_script
                    and trial.get('verdict_preview') in SCORED_PROGRESS_VERDICTS)
            return out
        # A process crash must not strand an unrecoverable deterministic
        # ownership token; a different payload derives a different claim.
        prediction_durable = False
        try:
            self.add_node(
                name,
                NodeIn(tag=c.tag, parent=(c.parent or None),
                       algorithm=c.algorithm, comment=c.comment),
                claim,
            )
            self.register_prediction(name, c.tag, PredictionIn(
                metric_name=c.metric_name, direction=c.direction, baseline_value=c.baseline,
                noise_band=c.noise_band, novel_metric=c.novel_metric, novel_direction=c.novel_direction,
                novel_threshold=c.novel_threshold, judge_script_sha=c.script_sha,
                closes_question=c.closes_question, credence=c.credence))
            # register_prediction atomically mints the immutable prediction
            # receipt/current head. From here the node is durable and rollback
            # would erase evidence. Releasing a marker can only reduce delete
            # authority, so a concurrent clear is harmless.
            prediction_durable = True
            try:
                self.release_cycle_claim(name, c.tag, claim)
            except Exception:
                pass  # receipt guards compensation even if marker cleanup is delayed
            result_input = TestResultIn(
                metric_value=c.measured, script=c.script, script_sha=c.script_sha,
                novel_measured=c.novel_measured,
                novel_script=c.novel_script,   # R2-NOVEL(s1): 서버앵커 소스 관통 — 없으면 FF1 partial
                source_trust=c.source_trust,
                counterexample_response=c.counterexample_response, counterexample_type=c.counterexample_type,
                ce_excess_content=c.ce_excess_content, ce_novel_corroborated=c.ce_novel_corroborated,
                ce_in_heuristic_spirit=c.ce_in_heuristic_spirit,
                lakatos_anomaly=c.lakatos_anomaly, lakatos_consequence=c.lakatos_consequence,
                lakatos_excess=c.lakatos_excess, lakatos_hardcore=c.lakatos_hardcore)
            submit_parameters = inspect.signature(self.submit_test_result).parameters.values()
            parameter_names = {parameter.name for parameter in submit_parameters}
            accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in submit_parameters
            )
            durable_submit = (
                "cycle_claim" in parameter_names or accepts_kwargs
            )
            durable_cycle_request = (
                "cycle_request" in parameter_names or accepts_kwargs
            )
            if durable_submit and durable_cycle_request:
                res = self.submit_test_result(
                    name, c.tag, result_input,
                    cycle_claim=claim,
                    cycle_request=cycle_request,
                )
            elif durable_submit:
                # Compatibility for old injected test doubles only.  The live
                # app exposes both bindings and always takes the branch above.
                res = self.submit_test_result(
                    name, c.tag, result_input, cycle_claim=claim
                )
            else:
                # Narrow compatibility path for legacy in-memory test doubles.
                res = self.submit_test_result(name, c.tag, result_input)
        except HTTPException as e:
            # A concurrent identical cycle may have committed after our initial
            # recovery read but before this invocation reached prediction or
            # verdict CAS.  Re-read the immutable cycle receipt before exposing
            # a false conflict; exact payload binding prevents cross-request
            # result reuse.
            recovered = self._recover_cycle_result(name, c.tag, claim)
            if recovered is not None:
                return self._complete_recovered_cycle(name, c, recovered)
            if not prediction_durable:
                try:
                    self.compensate_cycle_node(name, c.tag, claim)
                except Exception:
                    pass  # never mask the original cycle verdict/error
            raise with_advice(e)
        except Exception:
            if not prediction_durable:
                try:
                    self.compensate_cycle_node(name, c.tag, claim)
                except Exception:
                    pass  # exact token makes fail-safe preservation preferable
            raise
        cycle_event_id = res.get("_cycle_event_id")
        cycle_payload = res.get("_cycle_payload")
        if durable_submit and (
            cycle_event_id is None or not isinstance(cycle_payload, dict)
        ):
            raise HTTPException(500, "cycle verdict lacks durable cycle_result intent")
        if cycle_event_id is not None and isinstance(cycle_payload, dict):
            cycle_projected = self.hist(
                name,
                "cycle_result",
                c.tag,
                cycle_payload,
                event_id=cycle_event_id,
            )
            if cycle_projected is False:
                raise HTTPException(503, "cycle history projection remains pending")
        # ── 영수증 착륙(내구점) 이후 — critique 실패는 4xx+advice 로 전파하되 롤백하지 않는다.
        try:
            for critique in c.critiques:
                self.add_critique(name, c.tag, critique)
        except HTTPException as e:
            raise with_advice(e)
        out = dict(tree=name, tag=c.tag, verdict=res.get('verdict'), novel=res.get('novel'),
                   lakatos=res.get('lakatos'),   # R2-NOVEL(s2): FF1 강등사유를 삼키지 않는다
                   delta=res.get('delta'), critiques=len(c.critiques),
                   standing=self.standing(name, c.tag),
                   note='in-process 오케스트레이션 — bash(build/judge)는 client/CLI 책임(서버 no-RCE)')
        if multi_run_summary is not None:
            out['multi_run'] = multi_run_summary
        if remaining is not None:
            # 이 사이클이 영수증 1 을 착륙시켰으므로 정확히 1 소모(재채점은 409 로 막혀 있어 성공경로
            #   = 새로 채점된 노드 1). 단 *강제*는 언제나 저장소 재파생이지 이 숫자가 아니다(보고용).
            out['remaining_budget'] = remaining - 1
        if 'novel_server_anchored' in res:   # 있으면 노출(가시성) — 없는 키를 지어내지 않는다
            out['novel_server_anchored'] = res['novel_server_anchored']
        if res.get('lakatos') in ('novel_not_server_anchored', 'provisional_stale_engine'):
            # suggest-only advice(H9 SSOT=advice.py 레지스트리) — 상태코드/verdict 불변, 우회 수단 아님.
            tip = advice_for(res['lakatos'])
            if tip:
                out['advice'], out['advice_mode'] = tip, 'suggest-only'
        return out

    def add_artifact(self, name: str, a: ArtifactIn) -> dict:
        self.insert_artifact(dict(tree=name, node_tag=a.node_tag, kind=a.kind,
                                  data=a.data, ts=datetime.now(timezone.utc)))
        self.hist(name, 'artifact', a.node_tag, {'kind': a.kind})
        return {'ok': True}

    def add_element(self, name: str, el: ElementIn) -> dict:
        self.kg("""MATCH (t:LakatosTree {name:$tree})
              SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
              WITH t
              MERGE (el:LakatosElement {name:$elname})
              SET el.definition=$definition, el.implication=$implication,
                  el.lifecycle=$lifecycle, el.scope=$scope, el.updated_at=$ts
              MERGE (t)-[:HAS_ELEMENT]->(el)
              RETURN el.name AS name""",
                tree=name, elname=el.name, definition=el.definition, implication=el.implication,
                lifecycle=el.lifecycle, scope=el.scope, ts=datetime.now(timezone.utc).isoformat())
        self.hist(name, 'element_upsert', el.name, el.model_dump())
        return {'ok': True, 'name': el.name}

    def attach_element(self, name: str, tag: str, element_name: str, use: ElementUseIn) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})
                  SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                  WITH t
                  MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                  MATCH (t)-[:HAS_ELEMENT]->(el:LakatosElement {name:$elname})
                  MERGE (e)-[u:USES_ELEMENT]->(el)
                  SET u.note=$note, u.evidence_ref=$evidence_ref, u.at=$ts
                  RETURN e.tag AS tag, el.name AS element""",
                       tree=name, tag=tag, elname=element_name, note=use.note,
                       evidence_ref=use.evidence_ref, ts=datetime.now(timezone.utc).isoformat())
        if not rows:
            raise HTTPException(404, f'노드 또는 엘리멘트 없음: {tag}, {element_name}')
        self.hist(name, 'element_use', tag, {'element': element_name, **use.model_dump()})
        return {'ok': True, 'tag': tag, 'element': element_name}

    def add_foundation_requirement(self, name: str, req: FoundationRequirementIn) -> dict:
        engine_req = req.to_engine()
        self.kg("""MATCH (t:LakatosTree {name:$tree})
              SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
              WITH t
              MERGE (fr:FoundationRequirement {name:$tree+'/'+$name})
              SET fr.short_name=$name, fr.kind=$kind, fr.question=$question,
                  fr.why_needed=$why_needed, fr.acceptance_criteria=$acceptance_criteria,
                  fr.evidence_refs=$evidence_refs, fr.status=$status, fr.optional=$optional,
                  fr.owner=$owner, fr.risk_if_missing=$risk_if_missing,
                  fr.satisfied=$satisfied, fr.updated_at=$ts
              MERGE (t)-[:HAS_FOUNDATION]->(fr)
              RETURN fr.name AS name""",
                tree=name, ts=datetime.now(timezone.utc).isoformat(), **engine_req.db_record())
        self.hist(name, 'foundation_upsert', req.name, engine_req.db_record())
        return {'ok': True, 'name': req.name, 'satisfied': engine_req.satisfied}

    def get_foundation_requirements(self, name: str) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_FOUNDATION]->(fr:FoundationRequirement)
                     RETURN fr.short_name AS name, fr.kind AS kind, fr.question AS question,
                            fr.why_needed AS why_needed, fr.acceptance_criteria AS acceptance_criteria,
                            fr.evidence_refs AS evidence_refs, fr.status AS status,
                            fr.optional AS optional, fr.owner AS owner,
                            fr.risk_if_missing AS risk_if_missing, fr.satisfied AS satisfied
                     ORDER BY fr.kind, fr.short_name""", tree=name)
        gaps = [r['name'] for r in rows if not r.get('satisfied')]
        return {'requirements': rows, 'summary': {'required': len(rows),
                'satisfied': len(rows) - len(gaps), 'gaps': gaps}}

    def history(self, name: str, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self.pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT ts, op, node_tag, payload FROM public.history WHERE tree=%s '
                        'ORDER BY id DESC LIMIT %s', (name, limit))
            return [dict(row, ts=row['ts'].isoformat()) for row in cur.fetchall()]

    def neo4j_constraint_diagnostics(self) -> dict:
        return diagnose_required_constraints(self.kg("SHOW CONSTRAINTS"))

    def branch_stack(self, name: str, leaf: str | None):
        td = self.tree_data(name)
        try:
            bi = branch_inputs(td['nodes'], td['frontier'], leaf=leaf)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        sv = evaluate_stack(bi['verdicts'], bi['consecutive_nonprogressive'], bi['nodes_spent'],
                            bi['prediction_hits'], bi['problem_balance_windowed'])
        return td, bi, sv

    @staticmethod
    def stack_dict(sv) -> dict:
        return dict(decision=sv.decision, conflict=sv.conflict, quorum=sv.quorum, reason=sv.reason,
                    votes=[dict(layer=v.layer, vote=v.vote, reason=v.reason, detail=v.detail)
                           for v in sv.votes])
