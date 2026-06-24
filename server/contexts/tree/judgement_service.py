"""Application service for node judgement and scripted verdicts.

# KG: seed-lkt-engine-route-judgement-extract-20260616
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import HTTPException

from lakatos.verdict.argue import grounded_extension
from lakatos.eureka import classify as eureka_classify
from lakatos.engine import FoundationMap, LakatosEvidence, LakatosGate
from lakatos.verdict.judge import NovelTarget, Prediction, PredictionMissing, judge
from lakatos.verdict.pnr import CounterexampleType, ProofGeneratedConcept, Response, appraise_response
from lakatos.io.prov import prov_triples, replay_command
from lakatos.verdict.spine import credibility_from_trust, dialectical_verdict, synthesize_promotion
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

    def _node_eigentrust(self, name: str, tag: str) -> tuple[str | None, float | None, bool]:
        """노드의 인터넷 관측 그래프 eigentrust → (src, eigen, backed). src=None: internal 노드
        (인터넷 주장 없음 / 식별 source 없음). seed 자격은 *서버검증 URL 도메인*(#1 R3 forge 봉쇄) —
        client 의 source_type 라벨이 아니다. credibility 게이트(#1)와 eureka source_trust(#4)가
        *동일* 산출을 공유한다(no whack-a-mole). (read_models._internet_observations 와 동형.)"""
        import json
        rows = self.kg(
            "MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})-[:HAS_RESEARCH_EVENT]->"
            "(ev:ResearchEvent {realm:'internet'}) RETURN ev.payload AS payload ORDER BY ev.created_at",
            tree=name, tag=tag)
        if not rows:
            return None, None, False
        observations, src = [], None
        for r in rows:
            try:
                p = json.loads(r.get('payload') or '{}')
            except (ValueError, TypeError):
                p = {}
            s = (p.get('url') or p.get('source_type') or '').strip()
            if not s:
                continue
            if src is None:
                src = s
            observations.append(dict(source=s, url=p.get('url') or '',   # seed 는 서버검증 URL 도메인으로
                                     source_type=p.get('source_type') or '', node=tag,
                                     corroboration_score=float(p.get('corroboration_score') or 0.0)))
        if src is None:
            return None, None, False
        from lakatos.trust import global_source_trust
        gst = global_source_trust(observations)
        eigen = gst['trust'].get(src)
        backed = eigen is not None and gst['coverage']['mode'] != 'uniform_unlearned'
        return src, eigen, backed

    def _eigentrust_credibility(self, name: str, tag: str, *, novel_confirmed: bool,
                                has_human_verdict: bool) -> dict | None:
        """prom-honesty/credibility (정본 prom 2026-06-21): CANONICAL 승격의 credibility 게이트 입력을
        client-self-reported source_trust 대신 *노드의 인터넷 관측 그래프 eigentrust* 로 산출한다.
          - 인터넷 관측이 없으면 internal 노드 → None(credibility 게이트 생략; constitution+reproducible 가 영수증).
            단 human 이 vouch 하면 그 영수증을 보존한다(credibility=None 이면 floor 가 human 신호 유실, D2↔floor).
          - 있으면 그 source 의 eigentrust(네트워크 신뢰, sybil 저항)로 backed 판정 — self-report 1.0 으론 통과 못 함."""
        src, eigen, backed = self._node_eigentrust(name, tag)
        if src is None:
            return (credibility_from_trust(0.0, trust_backed=False, novel_confirmed=novel_confirmed,
                                           has_human_verdict=True) if has_human_verdict else None)
        return credibility_from_trust(
            float(eigen) if backed else 0.0, trust_backed=backed,
            novel_confirmed=novel_confirmed, has_human_verdict=has_human_verdict)

    def _eigentrust_source_trust(self, name: str, tag: str) -> float:
        """#4 (prom-honesty/provenance_reality_derived): eureka BF 의 source_trust 를 client-self-reported
        r.source_trust 가 아니라 *노드 인터넷 관측 eigentrust* 로 재유도 — forged source_trust 로 BF 를
        부풀려 true-eureka 를 살 수 없다(credibility 게이트와 동일 원천). internal 노드(인터넷 주장 없음)
        =1.0(스크립트 측정 영수증, credibility 주장 아님). 인터넷 노드: backed=그 source eigentrust,
        미뒷받침(forged source_type/junk URL → #1 URL-도메인 seed gating)=0.0(BF 중립). receipt:
        tests/test_eureka_source_trust_eigentrust.py."""
        src, eigen, backed = self._node_eigentrust(name, tag)
        if src is None:
            return 1.0
        return float(eigen) if backed else 0.0

    def set_verdict(self, name: str, tag: str, v: VerdictIn) -> dict:
        # prom-honesty/3 (적대감사 2026-06-20): 결합 불변식의 핵심 게이트 — scripted 판결 수동 지정 시 403.
        #   회귀가드: tests/test_prom_honesty_node_gating.py::test_set_verdict_403_on_scripted_verdict.
        #   (노드-쓰기 우회는 prom-honesty/1 에서 validator 422 + writer by-construction 으로 차단.)
        if not is_admin_verdict(v.verdict):
            raise HTTPException(403, f'판결 어휘({v.verdict})는 test_result 스크립트 전용 — 수동 지정 금지. '
                                     f'행정 상태만: {sorted(ADMIN_VERDICTS)}')
        if v.verdict == 'CANONICAL':
            pre = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
                        OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]->(a:Argument)
                        RETURN cur.verdict AS verdict,
                               cur.verdict_source AS verdict_source,
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
            credibility = self._eigentrust_credibility(
                name, tag, novel_confirmed=bool(cand.get('novel_confirmed')),
                has_human_verdict=bool(v.human_verdict))
            decision = synthesize_promotion(
                scripted_verdict=cand.get('verdict') or 'proof',
                verdict_source=cand.get('verdict_source'),   # SSOT floor: 레거시 NULL-source 는 영수증 아님
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

    def node_eureka(self, name: str, tag: str) -> dict:
        """A1: 노드별 measurement-grade eureka 읽기 — 판결 seam(submit_test_result)이 같은 kg_tx 로
        영속한 felt/true/hallucinated/reasons/bf. standing(promotion)은 별도 상위 층이라 제외
        (seam 이 require_promotion=False 로 산출). 미채점 노드는 judged=False."""
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     RETURN e.tag AS tag, e.verdict AS verdict, e.eureka_felt AS felt,
                            e.eureka_true AS true, e.eureka_hallucinated AS hallucinated,
                            e.eureka_reasons AS reasons, e.eureka_bf AS bf""", tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        x = rows[0]
        if x.get('felt') is None:
            return dict(tag=tag, judged=False, felt=False, true=False, hallucinated=False,
                        reasons=[], note='스크립트 채점 전 — eureka 는 test_result 판결 seam 에서 산출됨')
        return dict(tag=tag, judged=True, verdict=x.get('verdict'), felt=bool(x['felt']),
                    true=bool(x['true']), hallucinated=bool(x['hallucinated']), bf=x.get('bf'),
                    reasons=list(x.get('reasons') or []),
                    note='measurement-grade: felt=novel 등록, true=확증+substantial BF+순문제폐쇄. standing 은 별도 층')

    def register_prediction(self, name: str, tag: str, p: PredictionIn) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  WHERE e.verdict_source IS NULL OR e.verdict_source <> 'scripted'
                  SET e.pred_metric=$metric_name, e.pred_direction=$direction,
                      e.pred_baseline=$baseline_value, e.pred_noise_band=$noise_band,
                      e.pred_scale_type=$scale_type,
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
                            e.pred_noise_band AS nb, e.pred_scale_type AS scale,
                            e.pred_novel AS novel, e.verdict_source AS vsrc,
                            e.pred_novel_metric AS nmet, e.pred_novel_direction AS ndir,
                            e.pred_novel_threshold AS nthr, e.pred_script_sha AS psha,
                            e.pred_closes AS closes,
                            size([(e)-[:RAISES_QUESTION]->(q) | q.name]) AS n_opened""", tree=name, tag=tag)
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
                noise_band=pr['nb'] or 0.0, novel_prediction=pr['novel'] or '',
                scale_type=pr.get('scale') or 'ratio'),   # Stevens 가드 reachable (옛 노드 null→ratio)
                r.metric_value, novel_target=nt, novel_measured=r.novel_measured,
                # prom-honesty/sha: 예측 측정 출처 = 채점 스크립트 sha, novel 측정 출처 = r.novel_sha.
                #   둘 다 있고 다르면 같은 metric 이어도 독립(epsilon 우회 봉쇄); 같으면 비독립 → demote.
                measured_sha=r.script_sha or '', novel_sha=r.novel_sha or '')
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
        # A1: measurement-grade eureka at the judgement seam — felt(novel registered) vs
        # true(confirmed + substantial BF + net problem closure). Built from the just-scored fields
        # (require_promotion=False: standing lives in the standing layer, not on a node) and persisted
        # in the SAME kg_tx op-list below — atomic with the verdict, no second non-atomic write (B1).
        # opened = questions this node raises (n_opened); closed = 1 if it closes a frontier question.
        # #4 (provenance_reality_derived): eureka BF 의 source_trust 는 client r.source_trust 가 아니라
        # 노드 인터넷 관측 eigentrust 로 재유도 — forged source_trust 로 true-eureka 를 못 산다(credibility 와
        # 동일 원천). internal 노드=1.0. 영속(e.source_trust)도 이 값으로 → tree-level eureka_over_tree 도 정직.
        est = self._eigentrust_source_trust(name, tag)
        eu = eureka_classify({
            'novel_registered': bool(pr['nmet']), 'novel_confirmed': v.novel, 'verdict': verdict,
            'delta': v.delta, 'noise_band': pr['nb'] or 0.0, 'source_trust': est,
            'closed': 1 if pr.get('closes') else 0, 'opened': int(pr.get('n_opened') or 0),
        }, require_promotion=False)
        ts = datetime.now(timezone.utc).isoformat()
        ops = [("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                   SET e.metric_name=$mn, e.metric_value=$mv, e.verdict=$v,
                       e.verdict_source='scripted', e.judge_script=$script, e.judge_script_sha=$sha,
                       e.result_path=coalesce(nullif($rp,''), e.result_path), e.judged_at=$ts,
                       e.novel_confirmed=$novel, e.source_trust=$st, e.lakatos_status=$lstat,
                       e.eureka_felt=$eu_felt, e.eureka_true=$eu_true,
                       e.eureka_hallucinated=$eu_hall, e.eureka_reasons=$eu_reasons,
                       e.eureka_bf=$eu_bf""",
                dict(tree=name, tag=tag, mn=pr['m'], mv=r.metric_value, v=verdict,
                     script=r.script, sha=r.script_sha, rp=r.result_path, ts=ts, novel=v.novel,
                     st=est, lstat=lakatos_status,
                     eu_felt=eu.felt, eu_true=eu.true, eu_hall=eu.hallucinated,
                     eu_reasons=list(eu.reasons), eu_bf=round(eu.bf, 6)))]
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
                'eureka': {'felt': eu.felt, 'true': eu.true, 'hallucinated': eu.hallucinated,
                           'reasons': list(eu.reasons), 'bf': round(eu.bf, 3)},
                'rule': v.reason, 'replay': replay_command(r.script, r.result_path)}
