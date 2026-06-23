"""Application service for programme-level tree operations.

# KG: seed-lkt-engine-route-programme-extract-20260616
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras
from fastapi import HTTPException

from lakatos.quant.calibrate import brier_score, calibration_error, log_score
from lakatos.programme.explore import rank_questions as default_rank_questions
from lakatos.programme.heuristic import (appraise_and_plan, branch_pressure as _branch_pressure_pct,
                               expected_progress_gain, realized_reward)
from lakatos.programme.lifecycle import lifecycle_state
from lakatos.quant.metrics import branch_inputs
from lakatos.programme.series import series_from_path
from lakatos.programme.stack import evaluate_stack
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
)
from server.ports import HistoryAppend, KgQuery, PgFactory


TreeDataProvider = Callable[[str], dict]
MetricsProvider = Callable[[dict], dict]
NodeAdder = Callable[[str, NodeIn], dict]
PredictionRegistrar = Callable[[str, str, PredictionIn], dict]
TestResultSubmitter = Callable[[str, str, TestResultIn], dict]
CritiqueAdder = Callable[[str, str, CritiqueIn], dict]
StandingProvider = Callable[[str, str], dict]
ArtifactInserter = Callable[[dict], Any]
QuestionRanker = Callable[[list[dict], int], list[dict]]


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
        register_prediction: PredictionRegistrar,
        submit_test_result: TestResultSubmitter,
        add_critique: CritiqueAdder,
        standing: StandingProvider,
        insert_artifact: ArtifactInserter,
        rank_questions: QuestionRanker = default_rank_questions,
    ):
        self.kg = kg
        self.hist = hist
        self.pg = pg
        self.tree_data = tree_data
        self.compute_metrics = compute_metrics
        self.add_node = add_node
        self.register_prediction = register_prediction
        self.submit_test_result = submit_test_result
        self.add_critique = add_critique
        self.standing = standing
        self.insert_artifact = insert_artifact
        self.rank_questions = rank_questions

    def calibration(self, name: str) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e)
                     WHERE e.pred_credence IS NOT NULL AND e.novel_confirmed IS NOT NULL
                           AND e.novel_registered = true
                     RETURN e.pred_credence AS p, e.novel_confirmed AS o""", tree=name)
        fc = [(r['p'], 1 if r['o'] else 0) for r in rows]
        return dict(n=len(fc), brier=round(brier_score(fc), 4), log_score=round(log_score(fc), 4),
                    calibration_error=round(calibration_error(fc), 4),
                    scope='tree_level',
                    note='Brier 0=완벽, log=overconfidence 강벌, ECE=보정오차. novel 등록 예측만, 트리(발급자) 수준')

    def directions(self, name: str) -> dict:
        td = self.tree_data(name)
        can = next((r for r in td['nodes'] if r['verdict'] == 'CANONICAL'), None)
        metrics = self.compute_metrics(td)
        cred = (metrics.get('bayes') or {}).get('canonical_credence') or 0.5
        opens = [q for q in td['frontier'] if q['status'] == 'OPEN']

        def _num(q, k, d):
            value = q.get(k)
            return d if value is None else value

        # positive heuristic 신호 — 질문→연 노드 역매핑. 정본/진보 노드가 연 질문 = 살아있는 전선.
        progressive = {'CANONICAL', 'progressive', 'progressive_conditional'}
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
            qmeta.append(dict(name=q['name'], body=(q['body'] or '')[:160],
                              expected_gain=eg, cost=_num(q, 'cost', 1.0),
                              credence=cred, n_visits=_num(q, 'n_visits', 1),
                              on_canonical_frontier=q['name'] in front_qnames,
                              gain_source='explicit' if q.get('expected_gain') is not None else 'derived'))
        total_visits = max(sum(q['n_visits'] for q in qmeta), len(qmeta), 1)
        ranked = self.rank_questions(qmeta, total_visits=total_visits)
        for q in ranked:
            q['branch_from'] = (can or {}).get('tag')
            q['suggested_tag'] = q['name'].replace('q-', 'exp-') + '-try1'
        return dict(canonical=(can or {}).get('tag'), canonical_credence=cred,
                    branch_pressure=round(pressure, 4), ranked_directions=ranked,
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
        hard_core = tuple((td.get('hard_core') or ()) if isinstance(td.get('hard_core'), (list, tuple))
                          else ([td['hard_core']] if td.get('hard_core') else ()))
        tested = tuple(r.get('metric_name') for r in td['nodes']
                       if r.get('verdict') in ('CANONICAL', 'progressive') and r.get('metric_name'))
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
        return dict(
            leaf=bi['leaf'], trend=ap.trend, authority=ap.authority,
            promotion_authority=ap.promotion_authority, steps=ap.steps,
            progressive_count=ap.progressive_count, nonprogressive_count=ap.nonprogressive_count,
            off_axis_count=ap.off_axis_count, problem_balance_total=ap.problem_balance_total,
            rival_anomaly_count=ap.rival_anomaly_count,
            conceptual_problem_score=ap.conceptual_problem_score, reasons=list(ap.reasons),
            problem_balance_windowed=bi['problem_balance_windowed'],
            coverage={
                'verdict_sequence': 'wired',
                'conceptual_problem': 'not_projected_from_kg',   # internal/external 미수집
                'rival_anomaly': 'not_projected_from_kg',        # RivalProblemRecord 미수집
                'note': 'diagnostic_only — series 는 정본경로 verdict 시퀀스 기반. 개념/비교 입력 미배선(후속). verdict 권위 없음.',
            },
        )

    def run_cycle(self, name: str, c: CycleIn) -> dict:
        self.add_node(name, NodeIn(tag=c.tag, parent=(c.parent or None),
                                   algorithm=c.algorithm, comment=c.comment))
        self.register_prediction(name, c.tag, PredictionIn(
            metric_name=c.metric_name, direction=c.direction, baseline_value=c.baseline,
            noise_band=c.noise_band, novel_metric=c.novel_metric, novel_direction=c.novel_direction,
            novel_threshold=c.novel_threshold, judge_script_sha=c.script_sha,
            closes_question=c.closes_question, credence=c.credence))
        res = self.submit_test_result(name, c.tag, TestResultIn(
            metric_value=c.measured, script=c.script, script_sha=c.script_sha,
            novel_measured=c.novel_measured, source_trust=c.source_trust,
            counterexample_response=c.counterexample_response, counterexample_type=c.counterexample_type,
            ce_excess_content=c.ce_excess_content, ce_novel_corroborated=c.ce_novel_corroborated,
            ce_in_heuristic_spirit=c.ce_in_heuristic_spirit,
            lakatos_anomaly=c.lakatos_anomaly, lakatos_consequence=c.lakatos_consequence,
            lakatos_excess=c.lakatos_excess, lakatos_hardcore=c.lakatos_hardcore))
        for critique in c.critiques:
            self.add_critique(name, c.tag, critique)
        return dict(tree=name, tag=c.tag, verdict=res.get('verdict'), novel=res.get('novel'),
                    delta=res.get('delta'), critiques=len(c.critiques),
                    standing=self.standing(name, c.tag),
                    note='in-process 오케스트레이션 — bash(build/judge)는 client/CLI 책임(서버 no-RCE)')

    def add_artifact(self, name: str, a: ArtifactIn) -> dict:
        self.insert_artifact(dict(tree=name, node_tag=a.node_tag, kind=a.kind,
                                  data=a.data, ts=datetime.now(timezone.utc)))
        self.hist(name, 'artifact', a.node_tag, {'kind': a.kind})
        return {'ok': True}

    def add_element(self, name: str, el: ElementIn) -> dict:
        self.kg("""MATCH (t:LakatosTree {name:$tree})
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
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
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
            cur.execute('SELECT ts, op, node_tag, payload FROM history WHERE tree=%s '
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
