"""Application service for node judgement and scripted verdicts.

# KG: seed-lkt-engine-route-judgement-extract-20260616
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from lakatos import longinus
from lakatos.verdict.argue import assemble_af, grounded_extension
from lakatos.eureka import classify as eureka_classify
from lakatos.engine import FoundationMap, LakatosEvidence, LakatosGate
from lakatos.ontology import DomainOntology
from lakatos.verdict.judge import NovelTarget, Prediction, PredictionMissing, judge
from lakatos.verdict.pnr import CounterexampleType, ProofGeneratedConcept, Response, appraise_response
from lakatos.io.prov import prov_triples, replay_command
from lakatos.verdict.spine import credibility_from_trust, dialectical_verdict, synthesize_promotion
from lakatos.verdicts import ADMIN_VERDICTS, is_admin_verdict
from server.contexts.tree.schemas import PredictionIn, TestResultIn, VerdictIn
from server.ports import HistoryAppend, KgQuery, KgTx


FoundationProvider = Callable[[str], FoundationMap | None]
ReproducibleProvider = Callable[[str, str], bool | None]

# #H2 (human-attestation): floor 의 human 영수증으로 인정하는 KG Argument 의 kind 토큰.
#   evidence_claim_service.event_from_argument 와 *동일* 집합(kind∈{evaluation,verdict}→human_verdict action) —
#   인간 attestation 의 단일 어휘 정본. doubt/comment/rebuttal 등은 human 평가가 아니라 제외.
_HUMAN_ATTESTATION_KINDS = frozenset({'evaluation', 'verdict'})


def _is_human_attestation_arg(arg: dict) -> bool:
    """KG Argument 가 *실제 human attestation* 인가 — kind∈human 집합 AND by(사람 actor) 존재.
    client 의 1비트가 아니라 *영속된* Argument 존재로 판정(H2 우회 봉쇄). by 가 비면(익명) human 으로 안 침."""
    if not arg or not arg.get('id'):
        return False
    if (arg.get('kind') or '').strip().lower() not in _HUMAN_ATTESTATION_KINDS:
        return False
    return bool((arg.get('by') or '').strip())


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

    def _recompute_script_sha(self, script: str) -> tuple[str | None, dict]:
        """#H3 (prom-honesty/receipt-integrity): judge_script_sha 를 *서버가 파일 내용에서 재유도*.

        '어느 스크립트가 채점했나' 영수증은 client 문자열 신뢰면 동어반복(client psha vs client script_sha).
        r.script 가 읽을 수 있는 소스면 서버가 그 본문으로 sha256 을 재계산해 영수증을 현실에 묶는다.
          - 'file::symbol' 형태 → longinus.symbol_body_sha (CPG 본문해시; 부재/모호=None).
          - 평이한 경로 → 파일 내용 hashlib.sha256.
        안전 경로: 상대경로는 프로젝트 루트(longinus.ROOT) 기준 join 하되 루트를 벗어나면(traversal) 거부.
        절대경로는 *존재하는 정규파일* 일 때만 직접 읽음. 재계산 불가(inline/미존재/traversal/심볼 모호)면
        (None, …) 반환 → 호출부가 정직 fallback(client 값 유지 + server_verified=False).
        """
        s = (script or '').strip()
        if not s:
            return None, {'reason': 'empty_script'}
        if '::' in s:   # file::symbol — Longinus CPG 본문해시(심볼 실존검증)
            file_part, _, symbol = s.partition('::')
            try:
                sha, info = longinus.symbol_body_sha(file_part, symbol)
            except OSError:
                return None, {'reason': 'symbol_io_error', 'script': s}
            if sha is None:
                return None, {'reason': 'symbol_unresolved', **info}
            return sha, {'reason': 'symbol_body_sha', **info}
        root = Path(longinus.ROOT).resolve()
        p = Path(s)
        if p.is_absolute():
            try:
                resolved = p.resolve()
            except OSError:
                return None, {'reason': 'unresolvable', 'script': s}
            if not (resolved.is_file()):   # 미존재/비정규 = 재계산 불가
                return None, {'reason': 'not_a_file', 'script': s}
        else:
            resolved = (root / p).resolve()
            if root not in resolved.parents and resolved != root:   # ../ 탈출 = traversal 거부
                return None, {'reason': 'path_traversal', 'script': s}
            if not resolved.is_file():
                return None, {'reason': 'not_a_file', 'script': s}
        try:
            content = resolved.read_bytes()
        except OSError:
            return None, {'reason': 'read_error', 'script': s}
        return hashlib.sha256(content).hexdigest(), {'reason': 'file_content_sha', 'path': str(resolved)}

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
                               cur.qualitative_self_report AS qualitative_self_report,
                               collect({id:a.id, attacks:a.attacks, by:a.by, kind:a.kind}) AS args''',
                          tree=name, tag=tag)
            if not pre:
                raise HTTPException(404, f'노드 없음: {tag}')
            cand = pre[0]
            # #H5 (설계감사 2026-06-26): floor 판정의 스냅샷 지문 — verdict/source/qsr + 논증집합.
            #   write 가 이 지문을 원자 CAS 로 재검증해, read→write 사이 동시변경 시 0행 → 409(stale 승격 차단).
            snap_arg_fp = sorted(f"{a['id']}|{a.get('attacks') or ''}"
                                 for a in (cand.get('args') or []) if a.get('id'))
            # #H8 (설계감사 2026-06-26): floor 의 stands 도 actor-aware assemble_af 정본으로 — 인라인 AF
            #   조립(by 무시) 폐기. cand.args 가 이미 by 를 싣고 있어, 작성자가 자기 doubt 를 자기 rebuttal 로
            #   막아 CANONICAL floor 를 통과하던 self-vouch 가 여기서도 봉쇄된다(add_critique/standing 과 통일).
            arguments, attacks = assemble_af(tag, cand.get('args') or [])
            stands = f'verdict:{tag}' in grounded_extension(arguments, attacks)
            # #H2 (human-attestation): floor 의 has_human 은 client 1비트(v.human_verdict)가 *단독* 으로 못 연다.
            #   v.human_verdict 는 'KG 에서 그 human Argument 를 찾아라'는 *요청* 으로만 쓰고, 실제 영수증은
            #   *영속된* human attestation Argument 존재(kind∈{evaluation,verdict} AND by 사람 actor)로 판정.
            #   영수증 0 인 노드에 client True 만으론 CANONICAL floor 가 안 열린다(no_receipt_for_canonical).
            #   (Sybil 한계: by 가 노드 작성자와 다른지는 노드 author 가 KG 에 미식별이라 미강제 — 후속.)
            has_human = bool(v.human_verdict) and any(
                _is_human_attestation_arg(a) for a in (cand.get('args') or []))
            credibility = self._eigentrust_credibility(
                name, tag, novel_confirmed=bool(cand.get('novel_confirmed')),
                has_human_verdict=has_human)
            decision = synthesize_promotion(
                scripted_verdict=cand.get('verdict') or 'proof',
                verdict_source=cand.get('verdict_source'),   # SSOT floor: 레거시 NULL-source 는 영수증 아님
                stands=stands,
                foundation=self.foundation(name),
                credibility=credibility,
                reproducible=self.reproducible_for_node(name, tag),
                qualitative_self_report=bool(cand.get('qualitative_self_report')),   # #H1: 질적 self-report 표식 → 메트릭 단독 floor 차단
            )
            if not decision['ok']:
                raise HTTPException(409, f"CANONICAL 승격 차단(합성 엔진 게이트): {list(decision['reasons'])}. "
                                         f"게이트별: {decision['gates']}")
            # #H5 원자 CAS: 스냅샷(verdict/source/qsr + 논증집합 지문)이 write 시점에도 동일할 때만 승격.
            #   동시 재채점(source 변경)·반박 critique(논증집합 변경)가 끼면 0행 → 409. (M5 의 submit 원자가드를
            #   verdict-승격 경로로 미러. 단 credibility/foundation/reproducible 등 광역 신뢰그래프 race 는
            #   지문 밖 — 노드 자체 verdict/source/qsr/논증까지만 낙관적 락; 광역은 후속.)
            # #M12: 직전 canonical 강등을 verdict_source='engine' 으로 귀속(다른 강등경로와 정합).
            rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
                  WHERE coalesce(cur.verdict,'') = coalesce($exp_verdict,'')
                    AND coalesce(cur.verdict_source,'') = coalesce($exp_source,'')
                    AND coalesce(cur.qualitative_self_report,false) = $exp_qsr
                  WITH t, cur
                  OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]->(a:Argument)
                  WITH t, cur, [x IN collect(a.id + '|' + coalesce(a.attacks,'')) WHERE x IS NOT NULL | x] AS arg_fp
                  WHERE size(arg_fp) = $exp_argn AND all(x IN arg_fp WHERE x IN $exp_arg_fp)
                  WITH t, cur
                  OPTIONAL MATCH (t)-[:HAS_NODE]->(old {verdict:'CANONICAL'})
                  WHERE old.tag <> $tag
                  SET old.verdict='former_canonical', old.verdict_source='engine',
                      old.current_best_pointer=false
                  SET cur.verdict='CANONICAL', cur.verdict_source='admin',
                      cur.current_best_pointer=true,
                      cur.canonical_scope=$scope,
                      cur.canonical_assumptions=$assumptions,
                      cur.canonical_evidence_window=$evidence_window,
                      cur.valid_until_rebutted=$valid_until_rebutted
                  RETURN cur.tag AS tag''',
                    tree=name, tag=tag,
                    exp_verdict=cand.get('verdict'), exp_source=cand.get('verdict_source'),
                    exp_qsr=bool(cand.get('qualitative_self_report')),
                    exp_argn=len(snap_arg_fp), exp_arg_fp=snap_arg_fp,
                    scope=v.scope, assumptions=v.assumptions,
                    evidence_window=v.evidence_window, valid_until_rebutted=v.valid_until_rebutted)
            if not rows:   # 원자 CAS 0행 = read→write 사이 스냅샷 변경(동시 승격/재채점/반박) → stale 승격 차단
                raise HTTPException(409, '동시변경 감지(CANONICAL 원자 CAS 0행) — floor 판정 스냅샷'
                                         '(verdict/source/qsr/논증집합)이 승격 직전 변해 무효. 최신상태 재평가 필요.')
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
        meta = self.kg("MATCH (t:LakatosTree {name:$n}) RETURN t.ontology AS ontology", n=name)
        onto = DomainOntology.from_json(meta[0].get("ontology")) if meta else None
        if onto is not None:   # 선언된 metric 어휘 강제(opt-in) — 개선 metric + novel metric 둘 다
            viols = (onto.metric_violations(p.metric_name, p.direction)
                     + onto.metric_violations(p.novel_metric, p.novel_direction))
            if viols:
                raise HTTPException(422, f"metric 온톨로지 위반: {viols}")
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  WHERE (e.verdict_source IS NULL OR e.verdict_source <> 'scripted')
                        AND e.pred_registered_at IS NULL
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
                            size([(e)-[:RAISES_QUESTION]->(q) | q.name]) AS n_opened,
                            t.hard_core AS hard_core""", tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        pr = rows[0]
        if pr['vsrc'] == 'scripted':
            raise HTTPException(409, '이미 스크립트로 채점된 노드 — 재채점 금지 (re-roll 조작 차단). 새 노드로 분기할 것')
        # #H3 (receipt-integrity): server_sha 를 r.script 파일 *내용*에서 재유도해 영수증을 현실에 묶는다.
        #   불일치 비교 대상을 client-vs-client(psha vs script_sha, 동어반복) → server-vs-client/registered 로 교체.
        server_sha, sha_info = self._recompute_script_sha(r.script)
        sha_verified = server_sha is not None
        if sha_verified:
            if r.script_sha and server_sha != r.script_sha:   # 제출 sha 가 파일 내용과 불일치 → 날조 봉쇄
                raise HTTPException(422, f"judge_script_sha 서버재계산 불일치 — 파일 {server_sha[:12]} ≠ 제출 "
                                         f"{(r.script_sha or '')[:12]} ({sha_info.get('reason')})")
            if pr['psha'] and server_sha != pr['psha']:   # 사전등록 psha 가 채점 스크립트 내용과 불일치
                raise HTTPException(409, f"채점 스크립트 sha256 불일치 — 사전등록 {pr['psha'][:12]} ≠ 서버재계산 "
                                         f"{server_sha[:12]} (서버가 r.script 내용에서 재유도)")
        else:
            # 재계산 불가(inline/미존재 파일/심볼 모호) — 정직 fallback: 레거시 client-vs-client 비교 유지.
            #   sha 영수증은 server-미검증이므로 응답에 script_sha_server_verified=False 로 노출(동어반복 위험 숨김 금지).
            if pr['psha'] and r.script_sha and pr['psha'] != r.script_sha:
                raise HTTPException(409, f"채점 스크립트 sha256 불일치 — 사전등록 {pr['psha'][:12]} ≠ 제출 {r.script_sha[:12]}")
        # 저장·prov 는 server_sha(파일 재유도) 우선; 재계산 불가면 client 값 보존(server-미검증 플래그와 함께).
        stored_sha = server_sha if sha_verified else (r.script_sha or '')
        nt = None
        if pr['nmet'] and pr['ndir'] and pr['nthr'] is not None:
            nt = NovelTarget(metric_name=pr['nmet'], direction=pr['ndir'], threshold=pr['nthr'])
        # #H6 (설계감사 2026-06-26): novel 독립성(measured_sha≠novel_sha)을 client 문자열이 아니라 *양측
        #   서버재계산* 에 묶는다. 예측측=H3 stored_sha(sha_verified 일 때 파일 재유도값), novel측=r.novel_script
        #   본문 재유도(novel_server_sha). 둘 다 서버앵커일 때만 독립 후보 — 어느 한쪽이라도 client-only
        #   (novel_script 미제공/재계산불가, 또는 예측 script inline=sha 미검증)이면 ''로 넘겨 같은-metric novel
        #   을 비독립 demote. 독립은 *두 개의 서로 다른 실재 산출물* 로 증명(client novel_sha 한 줄로 못 산다).
        #   다른 metric novel 은 그 자체로 독립 사실이라 judge 의 same-metric 게이트 밖(영향 없음).
        novel_server_sha, _ = (self._recompute_script_sha(r.novel_script)
                               if r.novel_script else (None, {'reason': 'no_novel_script'}))
        both_anchored = sha_verified and novel_server_sha is not None
        judge_measured_sha = stored_sha if both_anchored else ''
        judge_novel_sha = novel_server_sha if both_anchored else ''
        try:
            v = judge(None if pr['m'] is None else Prediction(
                metric_name=pr['m'], direction=pr['d'], baseline_value=pr['b'],
                noise_band=pr['nb'] or 0.0, novel_prediction=pr['novel'] or '',
                scale_type=pr.get('scale') or 'ratio'),   # Stevens 가드 reachable (옛 노드 null→ratio)
                r.metric_value, novel_target=nt, novel_measured=r.novel_measured,
                measured_sha=judge_measured_sha, novel_sha=judge_novel_sha)
        except PredictionMissing as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        # #H1-hardcore (설계감사 frontier 닫기): hard_core 보존을 client self-report bool 이 아니라
        #   negative_heuristic(touched_assumptions ∩ tree.hard_core)로 *구조적으로 파생*. 제출이 touched
        #   가정을 선언하고 그게 tree 의 hard core 를 건드리면(protected≠∅) 아래에서 different_programme 로
        #   강등 — self-report bool(lakatos_hardcore=True)로 위반을 못 숨긴다. touched 미제공 시 레거시 폴백.
        #   잔여 frontier: touched-set 은 아직 제출자 선언 — git-diff ∩ Longinus 로 파생은 후속.
        _raw_core = (pr.get('hard_core') or '').replace(';', ',').replace('\n', ',')
        _core_tokens = {tok.strip().lower() for tok in _raw_core.split(',') if tok.strip()}
        _touched = [tok.strip().lower() for tok in (r.touched_assumptions or []) if tok and tok.strip()]
        hc_derived = None
        if _touched and _core_tokens:
            from lakatos.programme.heuristic import negative_heuristic
            hc_derived = not negative_heuristic(hard_core=_core_tokens,
                                                refuted_assumptions=_touched)['protected']
        lak_result = None
        have_qual = None not in (r.lakatos_anomaly, r.lakatos_consequence, r.lakatos_excess, r.lakatos_hardcore)
        if have_qual or r.human_verdict_required:
            lak_result = LakatosGate.evaluate(LakatosEvidence(
                theory_laden_anomaly=bool(r.lakatos_anomaly),
                independent_testable_consequence=bool(r.lakatos_consequence),
                excess_empirical_content=bool(r.lakatos_excess),
                hard_core_preserved=(hc_derived if hc_derived is not None else bool(r.lakatos_hardcore)),
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
                hard_core_preserved=(hc_derived if hc_derived is not None
                                     else (r.lakatos_hardcore if r.lakatos_hardcore is not None else True)),
                counterexample_type=ce_type, proof_generated_concept=pgc)
        decided = dialectical_verdict(v.verdict, pnr_appraisal=pnr_appraisal, lakatos_result=lak_result)
        verdict = decided['verdict']
        lakatos_status = decided['lakatos']
        # #H1-hardcore: 구조적 hard_core 위반(touched ∩ core ≠ ∅)이면 메트릭/질적 주장과 무관하게
        #   different_programme 로 강등 — '음의 휴리스틱을 떠남 = 다른 프로그램'(AXIS-CORR). bool 로 못 숨김.
        if hc_derived is False and verdict in ('progressive', 'progressive_conditional'):
            verdict, lakatos_status = 'different_programme', 'hard_core_violated_structural'
        # #H1 (설계감사): 질적 verdict 가 영수증 없는 self-report bool 로 progressive 를 떠받쳤는가.
        #   메트릭 개선은 실 영수증이나 '하드코어 보존·초과경험내용'(lakatos_*/ce_*)은 자기보고다. 독립
        #   영수증(독립 novel 측정 sha + ce_novel_corroborated) 없이 질적 bool 이 progressive(_conditional)를
        #   유지하면 표식 → CANONICAL floor 가 메트릭 단독으론 안 연다(set_verdict 가 이 표식을 floor 에 넘김).
        qual_backed = bool(r.novel_sha and r.ce_novel_corroborated)   # 독립 novel 측정 영수증
        qual_self_report = bool(have_qual and verdict in ('progressive', 'progressive_conditional')
                                and not qual_backed)
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
        # #M5 (atomic-rescore): 판결 SET 의 *첫 절* 을 원자 CAS claim 으로 — register_prediction 의 원자
        #   write-WHERE 패턴 답습. WHERE (vsrc IS NULL OR vsrc<>'scripted') 가드로 단일 managed-write tx
        #   안에서 동시 submit 중 한쪽만 SET 매칭 → 이중채점(TOCTOU) 봉쇄. judge() 검증을 다 통과한 *뒤*
        #   이 SET 이 실행되므로 거부 시 노드가 빈 scripted 로 잠기지 않는다. RETURN e.tag(claimed)=0행이면
        #   이미 scripted → 아래에서 409. (상단 238행 read-check 는 빠른 거절, 이 가드가 원자 권위.)
        ops = [("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                   WHERE e.verdict_source IS NULL OR e.verdict_source <> 'scripted'
                   SET e.metric_name=$mn, e.metric_value=$mv, e.verdict=$v,
                       e.verdict_source='scripted', e.judge_script=$script, e.judge_script_sha=$sha,
                       e.result_path=coalesce(nullif($rp,''), e.result_path), e.judged_at=$ts,
                       e.novel_confirmed=$novel, e.source_trust=$st, e.lakatos_status=$lstat,
                       e.eureka_felt=$eu_felt, e.eureka_true=$eu_true,
                       e.eureka_hallucinated=$eu_hall, e.eureka_reasons=$eu_reasons,
                       e.eureka_bf=$eu_bf, e.qualitative_self_report=$qsr
                   RETURN e.tag AS claimed""",
                dict(tree=name, tag=tag, mn=pr['m'], mv=r.metric_value, v=verdict,
                     script=r.script, sha=stored_sha, rp=r.result_path, ts=ts, novel=v.novel,
                     st=est, lstat=lakatos_status, qsr=qual_self_report,
                     eu_felt=eu.felt, eu_true=eu.true, eu_hall=eu.hallucinated,
                     eu_reasons=list(eu.reasons), eu_bf=round(eu.bf, 6)))]
        for tr in prov_triples(name, tag, r.script, r.result_path, verdict, stored_sha, ts):
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
        tx_result = self.kg_tx(ops)
        # #M5: 원자 CAS claim 결과 판정 — 첫 op(가드된 판결 SET)이 0행이면 동시 submit 이 이미 점유 → 409.
        #   per-op 결과 shape(len==ops, 각 op 의 .data() 리스트)일 때만 검사(실제 KG 트랜잭션). 그 외(미모델
        #   테스트 더블/None)는 상단 read-check 가 권위 — 하위호환 보존(좁은 검사로 거짓 409 회피).
        if (isinstance(tx_result, list) and len(tx_result) == len(ops)
                and isinstance(tx_result[0], list) and not tx_result[0]):
            raise HTTPException(409, '동시/재채점 차단 — 이미 scripted (원자 CAS claim 0행; 새 노드로 분기할 것)')
        self.hist(name, 'test_result', tag, dict(value=r.metric_value, baseline=pr['b'],
                                                 delta=round(v.delta, 4), verdict=verdict, script=r.script,
                                                 novel=v.novel, script_sha=stored_sha))
        return {'ok': True, 'verdict': verdict, 'delta': round(v.delta, 4), 'novel': v.novel,
                'lakatos': lakatos_status, 'metric_verdict': v.verdict,
                'requires_human': bool(decided.get('requires_human')),
                # #H3: sha 영수증이 서버 파일재계산으로 검증됐는지(False=inline/미존재 → 정직 fallback, client 값).
                'script_sha_server_verified': sha_verified, 'judge_script_sha': stored_sha,
                'eureka': {'felt': eu.felt, 'true': eu.true, 'hallucinated': eu.hallucinated,
                           'reasons': list(eu.reasons), 'bf': round(eu.bf, 3)},
                'rule': v.reason, 'replay': replay_command(r.script, r.result_path)}
