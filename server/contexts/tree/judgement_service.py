"""Application service for node judgement and scripted verdicts.

# KG: seed-lkt-engine-route-judgement-extract-20260616
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import HTTPException

from lakatos.argue import grounded_extension
from lakatos.engine import FoundationMap, LakatosEvidence, LakatosGate
from lakatos.judge import NovelTarget, Prediction, PredictionMissing, judge
from lakatos.pnr import CounterexampleType, ProofGeneratedConcept, Response, appraise_response
from lakatos.prov import prov_triples, replay_command
from lakatos.spine import credibility_from_trust, dialectical_verdict, synthesize_promotion
from lakatos.verdicts import ADMIN_VERDICTS, is_admin_verdict
from server.contexts.tree.schemas import PredictionIn, TestResultIn, VerdictIn
from server.ports import HistoryAppend, KgQuery, KgTx


FoundationProvider = Callable[[str], FoundationMap | None]
ReproducibleProvider = Callable[[str, str], bool | None]


class JudgementService:
    """Owns node verdict, prediction, and scripted test-result mutations."""

    # KG: seed-lkt-engine-route-judgement-extract-20260616

    def __init__(
        self,
        *,
        kg: KgQuery,
        kg_tx: KgTx,
        hist: HistoryAppend,
        foundation: FoundationProvider,
        reproducible_for_node: ReproducibleProvider,
    ):
        self.kg = kg
        self.kg_tx = kg_tx
        self.hist = hist
        self.foundation = foundation
        self.reproducible_for_node = reproducible_for_node

    def set_verdict(self, name: str, tag: str, v: VerdictIn) -> dict:
        if not is_admin_verdict(v.verdict):
            raise HTTPException(403, f'판결 어휘({v.verdict})는 test_result 스크립트 전용 — 수동 지정 금지. '
                                     f'행정 상태만: {sorted(ADMIN_VERDICTS)}')
        if v.verdict == 'CANONICAL':
            pre = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
                        OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]->(a:Argument)
                        RETURN cur.verdict AS verdict,
                               cur.source_trust AS source_trust,
                               cur.novel_confirmed AS novel_confirmed,
                               collect({id:a.id, attacks:a.attacks}) AS args''', tree=name, tag=tag)
            if not pre:
                raise HTTPException(404, f'노드 없음: {tag}')
            cand = pre[0]
            varg = f'verdict:{tag}'
            arguments = {varg}
            attacks = []
            for a in (cand.get('args') or []):
                if not a.get('id'):
                    continue
                short = a['id'].split('/')[-1]
                arguments.add(short)
                attacks.append((short, varg if a.get('attacks') == tag else a.get('attacks')))
            stands = varg in grounded_extension(arguments, attacks)
            st = cand.get('source_trust')
            credibility = credibility_from_trust(
                float(st) if st is not None else 1.0,
                novel_confirmed=bool(cand.get('novel_confirmed')),
                has_human_verdict=bool(v.human_verdict),
            )
            decision = synthesize_promotion(
                scripted_verdict=cand.get('verdict') or 'proof',
                stands=stands,
                foundation=self.foundation(name),
                credibility=credibility,
                reproducible=self.reproducible_for_node(name, tag),
            )
            if not decision['ok']:
                raise HTTPException(409, f"CANONICAL 승격 차단(합성 엔진 게이트): {list(decision['reasons'])}. "
                                         f"게이트별: {decision['gates']}")
            self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
                  WITH t, cur
                  OPTIONAL MATCH (t)-[:HAS_NODE]->(old {verdict:'CANONICAL'})
                  WHERE old.tag <> $tag
                  SET old.verdict='former_canonical', old.current_best_pointer=false
                  SET cur.verdict='CANONICAL', cur.verdict_source='admin',
                      cur.current_best_pointer=true,
                      cur.canonical_scope=$scope,
                      cur.canonical_assumptions=$assumptions,
                      cur.canonical_evidence_window=$evidence_window,
                      cur.valid_until_rebutted=$valid_until_rebutted ''',
                    tree=name, tag=tag, scope=v.scope, assumptions=v.assumptions,
                    evidence_window=v.evidence_window, valid_until_rebutted=v.valid_until_rebutted)
            rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag}) RETURN e.tag AS tag''',
                           tree=name, tag=tag)
        else:
            rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                      SET e.verdict=$verdict, e.verdict_source='admin' RETURN e.tag AS tag''',
                           tree=name, tag=tag, verdict=v.verdict)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        self.hist(name, 'verdict', tag, v.model_dump())
        return {'ok': True}

    def register_prediction(self, name: str, tag: str, p: PredictionIn) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  WHERE e.verdict_source IS NULL OR e.verdict_source <> 'scripted'
                  SET e.pred_metric=$metric_name, e.pred_direction=$direction,
                      e.pred_baseline=$baseline_value, e.pred_noise_band=$noise_band,
                      e.pred_novel=$novel_prediction, e.pred_closes=$closes_question,
                      e.pred_novel_metric=$novel_metric, e.pred_novel_direction=$novel_direction,
                      e.pred_novel_threshold=$novel_threshold, e.pred_script_sha=$judge_script_sha,
                      e.pred_credence=$credence,
                      e.novel_registered = ($novel_metric IS NOT NULL),
                      e.pred_registered_at=$ts
                  RETURN e.tag AS tag""",
                       tree=name, tag=tag, ts=datetime.now(timezone.utc).isoformat(), **p.model_dump())
        if not rows:
            raise HTTPException(409, '노드 없음 또는 이미 채점됨 — 사후 예측등록 금지')
        if p.closes_question:
            self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q {name:$cq})
                  SET q.n_visits=coalesce(q.n_visits, 0) + 1''', tree=name, cq=p.closes_question)
        self.hist(name, 'prediction_register', tag, p.model_dump())
        return {'ok': True, 'note': '예측 사전등록 완료 — 이제 실험을 실행하고 test_result 를 스크립트로 제출'}

    def submit_test_result(self, name: str, tag: str, r: TestResultIn) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     RETURN e.pred_metric AS m, e.pred_direction AS d, e.pred_baseline AS b,
                            e.pred_noise_band AS nb, e.pred_novel AS novel, e.verdict_source AS vsrc,
                            e.pred_novel_metric AS nmet, e.pred_novel_direction AS ndir,
                            e.pred_novel_threshold AS nthr, e.pred_script_sha AS psha""", tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        pr = rows[0]
        if pr['vsrc'] == 'scripted':
            raise HTTPException(409, '이미 스크립트로 채점된 노드 — 재채점 금지 (re-roll 조작 차단). 새 노드로 분기할 것')
        if pr['psha'] and r.script_sha and pr['psha'] != r.script_sha:
            raise HTTPException(409, f"채점 스크립트 sha256 불일치 — 사전등록 {pr['psha'][:12]} ≠ 제출 {r.script_sha[:12]}")
        nt = None
        if pr['nmet'] and pr['ndir'] and pr['nthr'] is not None:
            nt = NovelTarget(metric_name=pr['nmet'], direction=pr['ndir'], threshold=pr['nthr'])
        try:
            v = judge(None if pr['m'] is None else Prediction(
                metric_name=pr['m'], direction=pr['d'], baseline_value=pr['b'],
                noise_band=pr['nb'] or 0.0, novel_prediction=pr['novel'] or ''),
                r.metric_value, novel_target=nt, novel_measured=r.novel_measured)
        except PredictionMissing as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        lak_result = None
        have_qual = None not in (r.lakatos_anomaly, r.lakatos_consequence, r.lakatos_excess, r.lakatos_hardcore)
        if have_qual or r.human_verdict_required:
            lak_result = LakatosGate.evaluate(LakatosEvidence(
                theory_laden_anomaly=bool(r.lakatos_anomaly),
                independent_testable_consequence=bool(r.lakatos_consequence),
                excess_empirical_content=bool(r.lakatos_excess),
                hard_core_preserved=bool(r.lakatos_hardcore),
                implementation_complete=r.implementation_complete,
                data_branch=r.data_branch,
                data_replay_passed=r.data_replay_passed,
                human_verdict_required=r.human_verdict_required))
        pnr_appraisal = None
        if r.counterexample_response:
            try:
                resp = Response(r.counterexample_response)
            except ValueError:
                raise HTTPException(422, f'알 수 없는 반례 대응: {r.counterexample_response} — '
                                         f'{[e.value for e in Response]} 중 하나')
            ce_type = None
            if r.counterexample_type:
                try:
                    ce_type = CounterexampleType(r.counterexample_type)
                except ValueError:
                    raise HTTPException(422, f'알 수 없는 반례유형: {r.counterexample_type} — '
                                             f'{[e.value for e in CounterexampleType]} 중 하나')
            pgc = None
            if r.ce_proof_concept_name:
                pgc = ProofGeneratedConcept(
                    name=r.ce_proof_concept_name,
                    born_from_counterexample=r.ce_proof_born_from or '',
                    incorporated_lemma=r.ce_proof_incorporated_lemma or '')
            pnr_appraisal = appraise_response(
                resp, excess_content=r.ce_excess_content, novel_corroborated=r.ce_novel_corroborated,
                in_heuristic_spirit=r.ce_in_heuristic_spirit,
                hard_core_preserved=(r.lakatos_hardcore if r.lakatos_hardcore is not None else True),
                counterexample_type=ce_type, proof_generated_concept=pgc)
        decided = dialectical_verdict(v.verdict, pnr_appraisal=pnr_appraisal, lakatos_result=lak_result)
        verdict = decided['verdict']
        lakatos_status = decided['lakatos']
        ts = datetime.now(timezone.utc).isoformat()
        ops = [("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                   SET e.metric_name=$mn, e.metric_value=$mv, e.verdict=$v,
                       e.verdict_source='scripted', e.judge_script=$script, e.judge_script_sha=$sha,
                       e.result_path=coalesce(nullif($rp,''), e.result_path), e.judged_at=$ts,
                       e.novel_confirmed=$novel, e.source_trust=$st, e.lakatos_status=$lstat""",
                dict(tree=name, tag=tag, mn=pr['m'], mv=r.metric_value, v=verdict,
                     script=r.script, sha=r.script_sha, rp=r.result_path, ts=ts, novel=v.novel,
                     st=r.source_trust, lstat=lakatos_status))]
        for tr in prov_triples(name, tag, r.script, r.result_path, verdict, r.script_sha or '', ts):
            if tr.get('kind'):
                ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                      MERGE (p:ProvNode {id:$id}) SET p.kind=$kind, p.type=$type, p.sha256=$sha
                      MERGE (e)-[:HAS_PROV]->(p)""",
                            dict(tree=name, tag=tag, id=tr['id'], kind=tr['kind'],
                                 type=tr.get('type'), sha=tr.get('sha256'))))
            else:
                ops.append(("""MERGE (a:ProvNode {id:$f}) MERGE (b:ProvNode {id:$to})
                      MERGE (a)-[rel:PROV_REL {kind:$rk}]->(b)""",
                            dict(f=tr['from'], to=tr['to'], rk=tr['rel'])))
        self.kg_tx(ops)
        self.hist(name, 'test_result', tag, dict(value=r.metric_value, baseline=pr['b'],
                                                 delta=round(v.delta, 4), verdict=verdict, script=r.script,
                                                 novel=v.novel, script_sha=r.script_sha))
        return {'ok': True, 'verdict': verdict, 'delta': round(v.delta, 4), 'novel': v.novel,
                'lakatos': lakatos_status, 'metric_verdict': v.verdict,
                'requires_human': bool(decided.get('requires_human')),
                'rule': v.reason, 'replay': replay_command(r.script, r.result_path)}
