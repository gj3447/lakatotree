"""Application service for node judgement and scripted verdicts.

# KG: seed-lkt-engine-route-judgement-extract-20260616
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from lakatos import assurance, longinus
from lakatos.engine_identity import ENGINE_RULE_SHA, effective_floor
from lakatos.node_state import NodeState, assert_transition_allowed, derive_node_state
from lakatos.verdict.argue import assemble_af, grounded_extension
from lakatos.eureka import classify as eureka_classify
from lakatos.engine import FoundationMap, LakatosEvidence, LakatosGate
from lakatos.ontology import DomainOntology
from lakatos.verdict.judge import NovelTarget, Prediction, PredictionMissing, judge
from lakatos.verdict.pnr import CounterexampleType, ProofGeneratedConcept, Response, appraise_response
from lakatos.io.prov import prov_triples, replay_command
from lakatos.verdict.spine import credibility_from_trust, dialectical_verdict, synthesize_promotion
from lakatos.verdicts import (ADMIN_VERDICTS, fold_receipt_chain, is_admin_verdict,
                              prediction_content_sha, receipt_content_sha)
from lakatos.write_cert import CertError, CertSignerNotAllowed, verify_write_cert
from server.contexts.audit import fsck as audit_fsck
from server.contexts.tree.judgement_policy import (apply_verdict_demotes, build_receipt_fields,
                                                   engine_freshness_fires, qualitative_flags,
                                                   resolve_measurement)
from server.engine_freshness import freshness_provider_from_env
from server.contexts.tree.schemas import PredictionIn, TestResultIn, VerdictIn
from server.file_hashing import file_sha
from server.ports import HistoryAppend, KgQuery, KgTx


FoundationProvider = Callable[[str], FoundationMap | None]
ReproducibleProvider = Callable[[str, str], bool | None]


# FF4 (보안, deep-dive 2026-06-26): judge-script sha 재유도가 *임의* 절대파일을 읽지 않도록 허용 루트 안으로
#   containment(relative traversal 거부와 대칭). 허용 = repo ROOT + OS temp(테스트/런타임 작업영역) + 선택 env.
def _allowed_script_roots() -> list[Path]:
    roots = [Path(longinus.ROOT).resolve(), Path(tempfile.gettempdir()).resolve()]
    for part in os.environ.get('LAKATOS_SCRIPT_ROOTS', '').split(os.pathsep):
        part = part.strip()
        if part:
            try:
                roots.append(Path(part).resolve())
            except OSError:
                pass
    return roots


# FF4 판정의 단일 출처 — sha 재유도(JudgementService._isolate_script_file)와 AG2 replay 실행(app._replay_run)이
#   *같은* 격리를 공유한다(보안 로직 이중화 = drift 위험). 통과=(resolved, {}) / 거부=(None, {'reason': ...}).
SCRIPT_MAX_BYTES = 8 << 20   # FF4: 무제한 read/exec RAM-DoS 차단 (judge 스크립트는 작다)


def isolate_script_file(file_str: str, max_bytes: int = SCRIPT_MAX_BYTES) -> tuple[Path | None, dict]:
    """허용 루트(repo ROOT + OS temp + env) 안, size-cap 이하, 존재하는 정규파일로 격리.
    상대경로는 ROOT 기준 join 후 traversal 거부, 절대경로는 _allowed_script_roots() 안일 때만 허용."""
    root = Path(longinus.ROOT).resolve()
    p = Path(file_str)
    if p.is_absolute():
        try:
            resolved = p.resolve()
        except OSError:
            return None, {'reason': 'unresolvable', 'script': file_str}
        # 절대경로도 허용 루트 안에 있어야 — 임의 파일 sha 오라클 + 무인증 RAM-DoS 차단.
        if not any(r == resolved or r in resolved.parents for r in _allowed_script_roots()):
            return None, {'reason': 'out_of_root', 'script': file_str}
    else:
        resolved = (root / p).resolve()
        if root not in resolved.parents and resolved != root:   # ../ 탈출 = traversal 거부
            return None, {'reason': 'path_traversal', 'script': file_str}
    if not resolved.is_file():   # 미존재/비정규 = 재계산 불가
        return None, {'reason': 'not_a_file', 'script': file_str}
    try:   # unbounded read 차단 — size cap (대용량 파일 RAM-exhaustion 방지)
        if resolved.stat().st_size > max_bytes:
            return None, {'reason': 'too_large', 'script': file_str, 'size': resolved.stat().st_size}
    except OSError:
        return None, {'reason': 'read_error', 'script': file_str}
    return resolved, {}

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


def _require_state_transition(before, after: NodeState) -> None:
    try:
        assert_transition_allowed(before, after)
    except ValueError as e:
        raise HTTPException(409, str(e))


class JudgementService:
    """Owns node verdict, prediction, and scripted test-result mutations."""

    # KG: seed-lkt-engine-route-judgement-extract-20260616

    _SCRIPT_MAX_BYTES = SCRIPT_MAX_BYTES   # FF4 size cap — 모듈 정본(isolate_script_file 과 공유)

    def __init__(
        self,
        *,
        kg: KgQuery,
        kg_tx: KgTx,
        hist: HistoryAppend,
        foundation: FoundationProvider,
        reproducible_for_node: ReproducibleProvider,
        producer_replay_for_node: ReproducibleProvider | None = None,
        producer_replay_submit=None,
        engine_freshness=None,
    ):
        self.kg = kg
        self.kg_tx = kg_tx
        self.hist = hist
        self.foundation = foundation
        self.reproducible_for_node = reproducible_for_node
        # 나생문 #1 근본 봉합(live): 채점 스크립트 재실행으로 측정 외부검증(미주입=None 반환 no-op = 거동 불변).
        self.producer_replay_for_node = producer_replay_for_node or (lambda _n, _t: None)
        # AG3/R-SOV V1 (측정주권 2026-07-03): submit 시 *들어온* 값을 서버가 재유도 → 전체 ProducerReplayVerdict
        #   (regenerated 포함). 값소유 치환의 원천. 미주입=None 반환 no-op(거동 불변: client 값 그대로 봉인).
        self.producer_replay_submit = producer_replay_submit or (lambda *_a, **_k: None)
        # jp4: 판관 자기신원/능력 provider — 미주입=env opt-in 기본(미설정=None=게이트 완전 사체,
        #   비파괴; 테스트는 명시 주입으로만 무장). app.py 무편집 라이브 배선 = 이 env-default.
        self.engine_freshness = (engine_freshness if engine_freshness is not None
                                 else freshness_provider_from_env())

    def _node_eigentrust(self, name: str, tag: str) -> tuple[str | None, float | None, bool]:
        """노드의 인터넷 관측 그래프 eigentrust → (src, eigen, backed). src=None: internal 노드
        (인터넷 주장 없음 / 식별 source 없음). seed 자격은 *서버검증 URL 도메인*(#1 R3 forge 봉쇄) —
        client 의 source_type 라벨이 아니다. credibility 게이트(#1)와 eureka source_trust(#4)가
        *동일* 산출을 공유한다(no whack-a-mole). (repository.internet_observations 와 동형 — D9 백로그:
        단일 헬퍼로 통합 후보.)"""
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

    def _isolate_script_file(self, file_str: str) -> tuple[Path | None, dict]:
        """FF4 경로격리(모듈 정본 isolate_script_file 로 위임) — 평이경로/`file::symbol` 양 분기 *공용*
        (나생문 #12: 분기 비대칭 봉합). sha 재유도와 AG2 replay 실행이 같은 격리를 쓴다."""
        return isolate_script_file(file_str, self._SCRIPT_MAX_BYTES)

    def _recompute_script_sha(self, script: str) -> tuple[str | None, dict]:
        """#H3 (prom-honesty/receipt-integrity): judge_script_sha 를 *서버가 파일 내용에서 재유도*.

        '어느 스크립트가 채점했나' 영수증은 client 문자열 신뢰면 동어반복(client psha vs client script_sha).
        r.script 가 읽을 수 있는 소스면 서버가 그 본문으로 sha256 을 재계산해 영수증을 현실에 묶는다.
          - 'file::symbol' 형태 → longinus.symbol_body_sha (CPG 본문해시; 부재/모호=None).
          - 평이한 경로 → 파일 내용 hashlib.sha256.
        두 분기 모두 _isolate_script_file 로 FF4 격리(허용 루트·size-cap)를 *동일하게* 거친다.
        재계산 불가(inline/미존재/traversal/심볼 모호/루트 밖)면 (None, …) 반환 → 호출부가 정직 fallback
        (client 값 유지 + server_verified=False).
        """
        s = (script or '').strip()
        if not s:
            return None, {'reason': 'empty_script'}
        if '::' in s:   # file::symbol — Longinus CPG 본문해시(심볼 실존검증)
            file_part, _, symbol = s.partition('::')
            resolved, info = self._isolate_script_file(file_part)   # FF4 격리: 평이경로 분기와 대칭
            if resolved is None:
                return None, info
            try:
                sha, sinfo = longinus.symbol_body_sha(str(resolved), symbol)
            except OSError:
                return None, {'reason': 'symbol_io_error', 'script': s}
            if sha is None:
                return None, {'reason': 'symbol_unresolved', **sinfo}
            return sha, {'reason': 'symbol_body_sha', **sinfo}
        resolved, info = self._isolate_script_file(s)
        if resolved is None:
            return None, info
        try:
            sha = file_sha(str(resolved))
        except OSError:
            return None, {'reason': 'read_error', 'script': s}
        return sha, {'reason': 'file_content_sha', 'path': str(resolved)}

    def set_verdict(self, name: str, tag: str, v: VerdictIn) -> dict:
        # prom-honesty/3 (적대감사 2026-06-20): 결합 불변식의 핵심 게이트 — scripted 판결 수동 지정 시 403.
        #   회귀가드: tests/test_prom_honesty_node_gating.py::test_set_verdict_403_on_scripted_verdict.
        #   (노드-쓰기 우회는 prom-honesty/1 에서 validator 422 + writer by-construction 으로 차단.)
        if not is_admin_verdict(v.verdict):
            raise HTTPException(403, f'판결 어휘({v.verdict})는 test_result 스크립트 전용 — 수동 지정 금지. '
                                     f'행정 상태만: {sorted(ADMIN_VERDICTS)}')
        if v.verdict == 'CANONICAL':
            # R4(후속 PROM): 승격도 원장에 산다 — 포인터/직전-canonical 스냅샷을 pre 에서 읽어 receipt 를
            #   Python 에서 내용주소로 선계산(prev 체인), write CAS 가 두 스냅샷을 재검증한다.
            pre = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
                        OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]->(a:Argument)
                        WITH t, cur, collect({id:a.id, attacks:a.attacks, by:a.by, kind:a.kind}) AS args
                        OPTIONAL MATCH (t)-[:HAS_NODE]->(old {verdict:'CANONICAL'})
                        WHERE old.tag <> $tag
                        WITH t, cur, args,
                             head(collect({tag: old.tag, prev: old.current_receipt_sha})) AS oldrec
                        RETURN cur.verdict AS verdict,
                               cur.verdict_source AS verdict_source,
                               cur.node_state AS node_state,
                               cur.source_trust AS source_trust,
                               cur.novel_confirmed AS novel_confirmed,
                               cur.qualitative_self_report AS qualitative_self_report,
                               cur.author AS author,
                               t.assurance_tier AS assurance_tier,
                               t.attestor_dids AS attestor_dids,
                               cur.current_receipt_sha AS prev_receipt_sha,
                               oldrec.tag AS old_tag, oldrec.prev AS old_prev,
                               args AS args''',
                          tree=name, tag=tag)
            if not pre:
                raise HTTPException(404, f'노드 없음: {tag}')
            cand = pre[0]
            # AG5-IDENT (측정주권 2026-07-03): 비가역 verb(CANONICAL 승격) 서명강제 + verb-바인딩 cert.
            #   dead-σ(FE5 open-but-observable): cert 강제는 트리가 attestor 를 선언(attestor_dids)했을 때만 —
            #   무-attestor 트리는 무인증 CANONICAL 유지(키 없는 배포 안 잠금). cert 명령이 verb 를 실어
            #   submit 용 cert 를 canonical 승격에 재생(sign-X-execute-Y)하지 못하게 봉인한다.
            tier = assurance.resolve_tier(cand.get('assurance_tier'))
            attestors = [str(d).strip() for d in (cand.get('attestor_dids') or []) if d and str(d).strip()]
            canonical_cert_required = (assurance.GATE_WRITE_CERT
                                       in assurance.gates_for('set_verdict_canonical', tier) and bool(attestors))
            if canonical_cert_required or v.write_cert is not None:
                if v.write_cert is None:
                    raise HTTPException(403, f'write-cert 필수 — attestor 선언 {tier} 트리의 CANONICAL 승격은 '
                                             f'서명 명령만 인정(allow-list {len(attestors)}명). 비가역 verb '
                                             f'서명강제(AG5-IDENT).')
                expected_command = dict(tree=name, tag=tag, prev_receipt_sha=cand.get('prev_receipt_sha'),
                                        metric_value=None, script_sha=None, verb='set_verdict_canonical')
                try:
                    verify_write_cert(v.write_cert.model_dump(), expected_command=expected_command,
                                      allowlist=attestors if attestors else [v.write_cert.signer_did])
                except CertError as _ce:
                    raise HTTPException(403, f'write-cert 검증 실패(CANONICAL 승격, sign-X-execute-Y 봉인): '
                                             f'{type(_ce).__name__} — {_ce}')
            _require_state_transition(derive_node_state(cand), NodeState.CANONICAL)
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
            # FF3 (설계감사 2026-06-26): human attestation 의 actor(by)가 *노드 작성자(author)와 다를 때만* 인정 —
            #   작성자가 자기 노드에 자기 인장을 찍어 floor 를 여는 self-vouch 봉쇄(H2 의 'Sybil 한계: author 미식별'
            #   후속). author 미설정(legacy/익명)이면 by≠'' 로 기존 동작 보존(비파괴); 설정 시에만 by≠author 강제.
            #   ★Sybil 천장: author/by 둘 다 client 선언 — 한 actor 가 두 정체성을 쓰면 우회 가능(실 auth 전 한계).
            _author = (cand.get('author') or '').strip()
            has_human = bool(v.human_verdict) and any(
                _is_human_attestation_arg(a) and (a.get('by') or '').strip() != _author
                for a in (cand.get('args') or []))
            credibility = self._eigentrust_credibility(
                name, tag, novel_confirmed=bool(cand.get('novel_confirmed')),
                has_human_verdict=has_human)
            # G6 S4 (git-흡수): anchored tier 의 replay 승격 FLOOR — producer replay 가 *실행되어 실패*
            #   (False)했으면 CANONICAL 승격 차단. 재실행이 측정을 반증한 노드를 최강 주장으로 못 올린다.
            #   dead-σ 교정(관통위험 ④): LAKATOS_REPLAY_EXEC off 면 replay=None(검증 불가)로 *비차단* —
            #   floor 를 exec-트리거로 오설정하면 exec-OFF 배포가 anchored 승격 전부 409 lock 이 된다.
            #   (tier 는 위 AG5-IDENT cert 게이트에서 이미 resolve 됨 — 재계산 안 함.)
            replay_v = self.producer_replay_for_node(name, tag)
            if (assurance.GATE_REPLAY_FLOOR in assurance.gates_for('set_verdict_canonical', tier)
                    and replay_v is False):
                raise HTTPException(409, "CANONICAL 승격 차단(G6 anchored replay floor): producer replay "
                                         "가 실행되어 측정 재검증에 *실패*했다 — 재측정과 모순되는 노드는 "
                                         "최강 주장이 될 수 없다(재실험 또는 새 노드로 분기).")
            decision = synthesize_promotion(
                scripted_verdict=cand.get('verdict') or 'proof',
                verdict_source=cand.get('verdict_source'),   # SSOT floor: 레거시 NULL-source 는 영수증 아님
                stands=stands,
                foundation=self.foundation(name),
                credibility=credibility,
                reproducible=self.reproducible_for_node(name, tag),
                qualitative_self_report=bool(cand.get('qualitative_self_report')),   # #H1: 질적 self-report 표식 → 메트릭 단독 floor 차단
                producer_replay_verified=replay_v,   # 나생문 #1 live: 재실행 검증 → 세 번째 외부앵커(G6 floor 와 동일 관측 1회)
            )
            if not decision['ok']:
                raise HTTPException(409, f"CANONICAL 승격 차단(합성 엔진 게이트): {list(decision['reasons'])}. "
                                         f"게이트별: {decision['gates']}")
            # jp4 CA fail-closed: stale/무능력 판관은 CANONICAL 을 못 연다 — 하드 409. provisional
            #   CANONICAL 은 형용모순(최강 주장 + 임시 태그)이고 승격은 저빈도 운영 verb 라 루프 안 막음.
            _fresh = self.engine_freshness() if self.engine_freshness else None
            if engine_freshness_fires(_fresh):
                raise HTTPException(409, f"CANONICAL 승격 차단(jp4 CA fail-closed): 서빙 판관이 stale/무능력 — "
                                         f"boot_git_sha={(_fresh or {}).get('boot_git_sha')} "
                                         f"disk_head_sha={(_fresh or {}).get('disk_head_sha')} "
                                         f"missing={(_fresh or {}).get('missing')}. "
                                         f"scripts/dev_server_restart.sh 재기동 후 재시도.")
            # 나생문 #1: 측정 외부성(reproducible|human|producer-replay 검증)을 노드에 *persist* — floor 의
            #   honest-exposure 를 실제 관측가능하게(judge_receipt 단독 CANONICAL 은 anchored=False 로 보인다).
            floor_anchored = bool(decision['gates'].get('floor', {}).get('measurement_externally_anchored'))
            # #H5 원자 CAS: 스냅샷(verdict/source/qsr + 논증집합 지문)이 write 시점에도 동일할 때만 승격.
            #   동시 재채점(source 변경)·반박 critique(논증집합 변경)가 끼면 0행 → 409. (M5 의 submit 원자가드를
            #   verdict-승격 경로로 미러. 단 credibility/foundation/reproducible 등 광역 신뢰그래프 race 는
            #   지문 밖 — 노드 자체 verdict/source/qsr/논증까지만 낙관적 락; 광역은 후속.)
            # #M12: 직전 canonical 강등을 verdict_source='engine' 으로 귀속(다른 강등경로와 정합).
            # R4(후속 PROM): 승격·강등 모두 *같은 statement* 에서 v1 null-스펙 :VerdictReceipt 를 민팅하고
            #   포인터를 전진시킨다 — 측정 필드는 전부 null(측정영수증 위장 금지, null 이 정직), prev 링크가
            #   reflog 동형 복구영수증('(was <tag>)' = prev 한 칸 걷기). 포인터/old 스냅샷도 CAS 에 편입:
            #   pre-read 와 write 사이에 head 전진·canonical 교체가 끼면 0행 → 409(어차피 floor 재평가 대상).
            ts = datetime.now(timezone.utc).isoformat()
            prev_rsha = cand.get('prev_receipt_sha')
            # jp1: 승격/강등도 판관 행위 — engine_rule_sha 봉인(v2 mint). null-스펙의 측정필드는 여전히 null.
            _null_spec = dict(tree=name, target_id=None, metric_name=None, metric_value=None,
                              novel_confirmed=None, lakatos_status=None, judged_at=ts,
                              judge_script_sha=None, engine_rule_sha=ENGINE_RULE_SHA)
            rsha = receipt_content_sha(dict(_null_spec, tag=tag, verdict='CANONICAL',
                                            verdict_source='admin', prev_receipt_sha=prev_rsha))
            old_tag, old_prev = cand.get('old_tag'), cand.get('old_prev')
            old_rsha = receipt_content_sha(dict(_null_spec, tag=old_tag, verdict='former_canonical',
                                                verdict_source='engine', prev_receipt_sha=old_prev)) \
                if old_tag else None
            rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
                  SET cur._cas = coalesce(cur._cas,0) + 0
                  WITH t, cur
                  WHERE coalesce(cur.verdict,'') = coalesce($exp_verdict,'')
                    AND coalesce(cur.verdict_source,'') = coalesce($exp_source,'')
                    AND coalesce(cur.qualitative_self_report,false) = $exp_qsr
                    AND coalesce(cur.current_receipt_sha,'') = coalesce($prev_rsha,'')
                  WITH t, cur
                  OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]->(a:Argument)
                  WITH t, cur, [x IN collect(a.id + '|' + coalesce(a.attacks,'')) WHERE x IS NOT NULL | x] AS arg_fp
                  WHERE size(arg_fp) = $exp_argn AND all(x IN arg_fp WHERE x IN $exp_arg_fp)
                  WITH t, cur
                  OPTIONAL MATCH (t)-[:HAS_NODE]->(old {verdict:'CANONICAL'})
                  WHERE old.tag <> $tag
                  WITH t, cur, old
                  WHERE (old IS NULL AND $old_tag IS NULL)
                     OR (old.tag = $old_tag AND coalesce(old.current_receipt_sha,'') = coalesce($old_prev,''))
                  FOREACH (_ IN CASE WHEN old IS NOT NULL THEN [1] ELSE [] END |
                      SET old.verdict='former_canonical', old.verdict_source='engine',
                          old.current_best_pointer=false, old.node_state=$former_state,
                          old.demoted_at=$ts, old.current_receipt_sha=$old_rsha
                      MERGE (orec:VerdictReceipt {receipt_sha:$old_rsha})
                        ON CREATE SET orec.tree=$tree, orec.tag=$old_tag,
                          orec.verdict='former_canonical', orec.verdict_source='engine',
                          orec.judged_at=$ts, orec.prev_receipt_sha=$old_prev,
                          orec.engine_rule_sha=$engine_rule_sha
                      MERGE (old)-[:HAS_RECEIPT]->(orec)
                  )
                  SET cur.verdict='CANONICAL', cur.verdict_source='admin',
                      cur.node_state=$canonical_state,
                      cur.current_best_pointer=true,
                      cur.canonical_scope=$scope,
                      cur.canonical_assumptions=$assumptions,
                      cur.canonical_evidence_window=$evidence_window,
                      cur.valid_until_rebutted=$valid_until_rebutted,
                      cur.measurement_externally_anchored=$mea
                  MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                    ON CREATE SET rec.tree=$tree, rec.tag=$tag, rec.verdict='CANONICAL',
                      rec.verdict_source='admin', rec.judged_at=$ts, rec.prev_receipt_sha=$prev_rsha,
                      rec.engine_rule_sha=$engine_rule_sha
                  MERGE (cur)-[:HAS_RECEIPT]->(rec)
                  SET cur.current_receipt_sha=$rsha
                  RETURN cur.tag AS tag''',
                    tree=name, tag=tag,
                    exp_verdict=cand.get('verdict'), exp_source=cand.get('verdict_source'),
                    exp_qsr=bool(cand.get('qualitative_self_report')),
                    exp_argn=len(snap_arg_fp), exp_arg_fp=snap_arg_fp,
                    former_state=NodeState.FORMER_CANONICAL.value,
                    canonical_state=NodeState.CANONICAL.value,
                    scope=v.scope, assumptions=v.assumptions,
                    evidence_window=v.evidence_window, valid_until_rebutted=v.valid_until_rebutted,
                    mea=floor_anchored,
                    ts=ts, prev_rsha=prev_rsha, rsha=rsha,
                    old_tag=old_tag, old_prev=old_prev, old_rsha=old_rsha,
                    engine_rule_sha=ENGINE_RULE_SHA)
            if not rows:   # 원자 CAS 0행 = read→write 사이 스냅샷 변경(동시 승격/재채점/반박/head 전진) → 차단
                raise HTTPException(409, '동시변경 감지(CANONICAL 원자 CAS 0행) — floor 판정 스냅샷'
                                         '(verdict/source/qsr/논증집합/영수증 포인터/직전 canonical)이 승격 직전 '
                                         '변해 무효. 최신상태 재평가 필요.')
        else:
            state_rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                       RETURN e.verdict AS verdict, e.verdict_source AS verdict_source,
                              e.node_state AS node_state, e.pred_registered_at AS pred_registered_at,
                              e.judged_at AS judged_at, e.metric_value AS metric_value,
                              e.current_receipt_sha AS prev_receipt_sha''',
                                 tree=name, tag=tag)
            if not state_rows:
                raise HTTPException(404, f'노드 없음: {tag}')
            next_state = derive_node_state({'verdict': v.verdict, 'verdict_source': 'admin'})
            _require_state_transition(derive_node_state(state_rows[0]), next_state)
            # R4(후속 PROM): 행정 verdict 이동도 원장에 산다 — v1 null-스펙 receipt + 포인터 전진,
            #   mini-CAS(verdict/포인터 스냅샷)로 read→write race 는 0행 → 409.
            ts = datetime.now(timezone.utc).isoformat()
            prev_rsha = state_rows[0].get('prev_receipt_sha')
            rsha = receipt_content_sha(dict(
                tree=name, tag=tag, target_id=None, verdict=v.verdict, verdict_source='admin',
                metric_name=None, metric_value=None, novel_confirmed=None, lakatos_status=None,
                judged_at=ts, judge_script_sha=None, prev_receipt_sha=prev_rsha,
                engine_rule_sha=ENGINE_RULE_SHA))
            rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                      WHERE coalesce(e.verdict,'') = coalesce($exp_verdict,'')
                        AND coalesce(e.current_receipt_sha,'') = coalesce($prev_rsha,'')
                      SET e.verdict=$verdict, e.verdict_source='admin', e.node_state=$node_state
                      MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                        ON CREATE SET rec.tree=$tree, rec.tag=$tag, rec.verdict=$verdict,
                          rec.verdict_source='admin', rec.judged_at=$ts, rec.prev_receipt_sha=$prev_rsha,
                          rec.engine_rule_sha=$engine_rule_sha
                      MERGE (e)-[:HAS_RECEIPT]->(rec)
                      SET e.current_receipt_sha=$rsha
                      RETURN e.tag AS tag''',
                           tree=name, tag=tag, verdict=v.verdict,
                           node_state=next_state.value,
                           exp_verdict=state_rows[0].get('verdict'),
                           prev_rsha=prev_rsha, rsha=rsha, ts=ts,
                           engine_rule_sha=ENGINE_RULE_SHA)
            if not rows:   # mini-CAS 0행 = read→write 사이 동시변경(재채점/head 전진) → stale 이동 차단
                raise HTTPException(409, '동시변경 감지(행정 verdict mini-CAS 0행) — 최신상태 재평가 필요.')
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

    def _baseline_lineage(self, name: str, tag: str, p: PredictionIn) -> str:
        """R12(ManifestoGap S1): 예측 baseline 을 부모의 서버-persist measured 에 앵커.
        anchored=부모 measured 와 |Δ|≤noise_band · unanchored=벗어남(전략적 부풀림 노출) ·
        no_prior=부모 measured 없음(콜드스타트 명시). 비파괴 마크(강제 아님) + fail-safe(조회 실패=no_prior)."""
        try:
            rows = self.kg(
                "MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})-[:BRANCHED_FROM]->(par) "
                "WHERE par.metric_value IS NOT NULL "
                "RETURN par.metric_value AS parent_measured ORDER BY par.judged_at DESC LIMIT 1",
                tree=name, tag=tag)
        except Exception:
            return "no_prior"
        if not rows or rows[0].get("parent_measured") is None:
            return "no_prior"
        pm = float(rows[0]["parent_measured"])
        return "anchored" if abs(float(p.baseline_value) - pm) <= float(p.noise_band or 0.0) else "unanchored"

    def register_prediction(self, name: str, tag: str, p: PredictionIn) -> dict:
        meta = self.kg("MATCH (t:LakatosTree {name:$n}) RETURN t.ontology AS ontology", n=name)
        onto = DomainOntology.from_json(meta[0].get("ontology")) if meta else None
        baseline_lineage = self._baseline_lineage(name, tag, p)   # R12: 등록 전 계보 앵커 판정
        if onto is not None:   # 선언된 metric 어휘 강제(opt-in) — 개선 metric + novel metric 둘 다
            viols = (onto.metric_violations(p.metric_name, p.direction)
                     + onto.metric_violations(p.novel_metric, p.novel_direction))
            if viols:
                raise HTTPException(422, f"metric 온톨로지 위반: {viols}")
        # C1 S3-engine: 등록-시점 spec 봉인 — 예측 spec *전체*를 내용주소 PredictionReceipt 로 mint.
        #   prev 는 노드의 현 체인 head(보통 None=genesis). rsha 를 Python 에서 선계산해야 하므로 head 를
        #   먼저 읽고, 아래 guarded SET 의 WHERE 에 CAS(coalesce(current)=coalesce($prev_rsha))를 더해
        #   read-write 사이 경합을 원자적으로 봉쇄(#M5/강등 receipt 의 CAS 패턴 답습 — 불일치=0행=409,
        #   오염된 mint 없음). submit 은 이미 e.current_receipt_sha 를 prev 로 봉인하므로 verdict receipt 가
        #   이 prediction sha 를 내용으로 커밋 → spec back-fit 은 체인이 표현 못 한다(ReceiptChainBroken).
        head_rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  RETURN e.current_receipt_sha AS prev_rsha""", tree=name, tag=tag)
        prev_rsha = head_rows[0].get('prev_rsha') if head_rows else None
        ts = datetime.now(timezone.utc).isoformat()
        spec = p.model_dump()
        pred_receipt_fields = dict(
            receipt_kind='prediction', tree=name, tag=tag,
            baseline_lineage=baseline_lineage, registered_at=ts, prev_receipt_sha=prev_rsha,
            **spec)
        rsha = prediction_content_sha(pred_receipt_fields)
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  WHERE (e.verdict_source IS NULL OR e.verdict_source <> 'scripted')
                        AND e.pred_registered_at IS NULL
                        AND coalesce(e.node_state, 'DRAFT') IN $allowed_from
                        AND coalesce(e.current_receipt_sha,'') = coalesce($prev_rsha,'')
                  SET e.pred_metric=$metric_name, e.pred_direction=$direction,
                      e.pred_baseline=$baseline_value, e.pred_noise_band=$noise_band,
                      e.pred_scale_type=$scale_type,
                      e.pred_novel=$novel_prediction, e.pred_closes=$closes_question,
                      e.pred_novel_metric=$novel_metric, e.pred_novel_direction=$novel_direction,
                      e.pred_novel_threshold=$novel_threshold, e.pred_script_sha=$judge_script_sha,
                      e.pred_credence=$credence,
                      e.novel_registered = ($novel_metric IS NOT NULL),
                      e.pred_registered_at=$ts,
                      e.node_state=$node_state,
                      e.baseline_lineage=$baseline_lineage
                  WITH e
                  MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                    ON CREATE SET rec.receipt_kind='prediction', rec.tree=$tree, rec.tag=$tag,
                      rec.metric_name=$metric_name, rec.direction=$direction,
                      rec.baseline_value=$baseline_value, rec.noise_band=$noise_band,
                      rec.scale_type=$scale_type, rec.novel_prediction=$novel_prediction,
                      rec.novel_metric=$novel_metric, rec.novel_direction=$novel_direction,
                      rec.novel_threshold=$novel_threshold, rec.judge_script_sha=$judge_script_sha,
                      rec.closes_question=$closes_question, rec.credence=$credence,
                      rec.baseline_lineage=$baseline_lineage, rec.registered_at=$ts,
                      rec.prev_receipt_sha=$prev_rsha
                  MERGE (e)-[:HAS_RECEIPT]->(rec)
                  SET e.current_receipt_sha=$rsha, e.pred_receipt_sha=$rsha
                  RETURN e.tag AS tag""",
                       tree=name, tag=tag, ts=ts,
                       node_state=NodeState.PREDICTED.value,
                       baseline_lineage=baseline_lineage,   # R12: 계보 앵커 마크(비파괴)
                       allowed_from=[NodeState.DRAFT.value, NodeState.ADMINISTRATIVE.value],
                       rsha=rsha, prev_rsha=prev_rsha,
                       **spec)
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
                            e.pred_registered_at AS pred_registered_at,
                            e.node_state AS node_state, e.judged_at AS judged_at,
                            e.metric_value AS existing_metric_value,
                            e.verdict AS existing_verdict, e.lakatos_status AS existing_lstat,
                            e.current_receipt_sha AS prev_receipt_sha,
                            e.pred_closes AS closes,
                            size([(e)-[:RAISES_QUESTION]->(q) | q.name]) AS n_opened,
                            t.hard_core AS hard_core,
                            t.require_novel_anchor AS require_novel_anchor,
                            t.assurance_tier AS assurance_tier,
                            t.attestor_dids AS attestor_dids""", tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        pr = rows[0]
        # G6(git-흡수): tier 정책은 assurance 디스패치 테이블(SSOT)이 결정 — 핸들러가 하드코딩하지 않는다.
        #   receipted/anchored tier 는 novel-anchor 게이트를 무장(신규 트리 기본=anchored, git default-OFF 반전);
        #   legacy(무tier)/notebook 은 트리의 opt-in 플래그(FF1)로만 발동(거동 불변, 소급 강등 없음).
        tier = assurance.resolve_tier(pr.get('assurance_tier'))
        require_novel_anchor = (
            assurance.GATE_NOVEL_ANCHOR in assurance.gates_for('submit_test_result', tier)
            or bool(pr.get('require_novel_anchor')))   # FF1 phase2: opt-in tree policy 는 그대로 존중
        # jp4 판관 자기고유수용감각 — stale(코드경로 한정)/무능력 판정. 3중 fail-open: 미주입(None)=
        #   'unchecked' 무강등 / 판정불가(stale_code None)='indeterminate' 무발화(부재≠반증) / 발화는
        #   engine_freshness_fires 가 is True·is False 만 문다. 발화해도 거부가 아니라 ④ provisional
        #   강등(채점 흐름은 계속 — 정직 라벨) — 재기동 후 동일값 재제출 freshen 으로 승급.
        fresh = self.engine_freshness() if self.engine_freshness else None
        fresh_fire = engine_freshness_fires(fresh)
        efresh = ('unchecked' if fresh is None else
                  'incapable' if fresh.get('capable') is False else
                  'stale_code' if fresh.get('stale_code') is True else
                  'indeterminate' if fresh.get('stale_code') is None else 'fresh')
        # novel-anchor freshen (2026-07-03): 앵커-데모트 partial 은 *동일 metric_value* 의 서버앵커
        #   재제출로만 승급 가능(G1 "바이트동일 재제출=freshen" 정합). 값이 다르면 re-roll → 409 유지.
        #   앵커 성립 여부는 아래 sha 재유도 후 재검(freshen_anchor 인데 미앵커면 409) — client 문자열
        #   재제출로는 이 통로를 못 연다(FF1 봉합 유지).
        # jp4 확장: provisional_stale_engine partial 도 같은 좁은통로(동일값 재제출)로 — 단 판관이
        #   *여전히* stale/무능력이면 409(재기동 먼저).
        freshen_anchor = False
        freshen_reason = None
        if pr['vsrc'] == 'scripted':
            can_freshen = (pr.get('existing_verdict') == 'partial'
                           and pr.get('existing_lstat') in ('novel_not_server_anchored',
                                                            'provisional_stale_engine')
                           and r.metric_value == pr.get('existing_metric_value'))
            if not can_freshen:
                raise HTTPException(409, '이미 스크립트로 채점된 노드 — 재채점 금지 (re-roll 조작 차단). '
                                         '새 노드로 분기할 것 (예외: novel_not_server_anchored/'
                                         'provisional_stale_engine partial 은 동일 metric_value 재제출로 '
                                         'freshen 가능 — 전자는 서버앵커, 후자는 비-stale 판관 요구)')
            freshen_anchor = True
            freshen_reason = pr.get('existing_lstat')
            if freshen_reason == 'provisional_stale_engine' and fresh_fire:
                raise HTTPException(409, f"freshen 거부 — 판관이 여전히 stale/무능력: "
                                         f"boot_git_sha={(fresh or {}).get('boot_git_sha')} vs "
                                         f"disk_head_sha={(fresh or {}).get('disk_head_sha')}, "
                                         f"missing={(fresh or {}).get('missing')}. "
                                         f"scripts/dev_server_restart.sh 재기동 후 동일값 재제출.")
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
        # G10(git-흡수): attestor 선언 트리의 판결 쓰기는 *서명 cert 가 유일한 명령원*(push-cert 이식,
        #   receive-pack.c:2179-2199 — cert 와 다른 명령의 동시 제출=프로토콜 에러). 발동 = tier 게이트
        #   무장(assurance.GATE_WRITE_CERT) ∧ attestor allow-list(키 실물) 선언 — on/off 플래그가 아니라
        #   키 선언이 스위치(advisory GIT_PUSH_CERT_STATUS 는 정확히 P1 실패라 반전). allow-list 없는
        #   트리는 서명자 자체가 없어 잠글 수 없다(dead-σ: 키 없는 배포를 409 로 잠그지 않는다).
        #   명령 바인딩 = {tree, tag, prev_receipt_sha(G1 체인 포인터 CAS), metric_value, script_sha}
        #   → sign-X-execute-Y 불가 + replay 는 옛 포인터 서명이 되어 구조적으로 죽는다.
        #   author 는 client 문자열이 아니라 서명(signer_did)에서 유도되어 스탬프된다(Sybil 갭 봉합).
        attestors = [str(d).strip() for d in (pr.get('attestor_dids') or []) if d and str(d).strip()]
        cert_required = (assurance.GATE_WRITE_CERT in assurance.gates_for('submit_test_result', tier)
                         and bool(attestors))
        attested_by_did = None
        if cert_required or r.write_cert is not None:
            if r.write_cert is None:
                raise HTTPException(403, f'write-cert 필수 — attestor 선언 {tier} 트리의 판결 쓰기는 서명 '
                                         f'명령만 인정(allow-list {len(attestors)}명). client author 문자열은 '
                                         f'authorship 이 아니다(G10 Sybil 봉합)')
            expected_command = dict(tree=name, tag=tag, prev_receipt_sha=pr.get('prev_receipt_sha'),
                                    metric_value=r.metric_value, script_sha=stored_sha,
                                    verb='submit_test_result')   # AG5-IDENT: cert 를 이 verb 에 바인딩
            try:
                attestation = verify_write_cert(
                    r.write_cert.model_dump(),
                    expected_command=expected_command,
                    # 자발적 cert(비강제 트리): allow-list 없으면 자기서명 검증만 — authorship 증명이지
                    # 권위 주장이 아니다(권위 필터는 allow-list 가 정본).
                    allowlist=attestors if attestors else [r.write_cert.signer_did])
            except CertSignerNotAllowed as e:
                raise HTTPException(403, str(e))
            except CertError as e:
                raise HTTPException(422, str(e))
            attested_by_did = attestation['signer_did']
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
        # freshen 자격 재검: 이번 재제출이 *양측 서버앵커* 를 실제로 성립시켜야만 좁은 통로가 열린다.
        #   (jp4: 이 요구는 novel-anchor 사유 전용 — provisional_stale_engine 은 novel_script 가 애초에
        #   없던 단순 metric 노드도 있어 비-stale 판관 재검(위)만 요구한다.)
        if (freshen_anchor and freshen_reason == 'novel_not_server_anchored'
                and not (sha_verified and novel_server_sha is not None)):
            raise HTTPException(409, 'freshen 거부 — 재제출의 script 와 novel_script 가 둘 다 서버가 '
                                     '읽을 수 있는 파일 경로여야 한다 (client 문자열로는 승급 불가)')
        both_anchored = sha_verified and novel_server_sha is not None
        novel_server_anchored = novel_server_sha is not None              # FF1: novel 측정이 서버 재유도됨
        cross_metric_novel = pr['nmet'] is not None and pr['nmet'] != pr['m']
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
        # AG4/R-SOV V2 재현성 천장(측정주권 2026-07-03): tier 게이트(assurance SSOT)가 무장하고 노드
        #   재현성이 *구조적으로 반증*(reproducible is False: lineage dangling/비-source root)이면
        #   apply_verdict_demotes 가 progressive→partial 천장. ★불가 None(result_path 없음/미검증)은
        #   천장 안 함(부재≠반증, dead-σ) — 라이브 노드(result_path='')는 None → 무회귀.
        _repro = self.reproducible_for_node(name, tag)
        _repro_ceiling = assurance.GATE_REPRODUCIBILITY_CEILING in assurance.gates_for('submit_test_result', tier)
        # DE1: 구조적 강등 체인(#H1-hardcore + AG4 재현성천장 + FF1 novel-anchor)을 순수 정책으로 추출.
        _dec = apply_verdict_demotes(
            decided['verdict'], decided['lakatos'], hc_derived=hc_derived,
            require_novel_anchor=require_novel_anchor, novel=bool(v.novel),
            cross_metric_novel=cross_metric_novel, novel_server_anchored=novel_server_anchored,
            reproducible=_repro, reproducibility_ceiling=_repro_ceiling,
            engine_fresh_fire=fresh_fire)   # jp4 ④: stale/무능력 판관 → provisional 강등(마지막)
        verdict, lakatos_status, novel_independent = _dec.verdict, _dec.lakatos_status, _dec.novel_independent
        # #H1/#H10 질적 backing(서버앵커 독립 novel + ce_novel_corroborated) — DE1 순수 추출.
        qual_backed, qual_self_report = qualitative_flags(
            have_qual=have_qual, verdict=verdict, novel_server_anchored=novel_server_anchored,
            ce_novel_corroborated=bool(r.ce_novel_corroborated))
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
            'novel_registered': bool(pr['nmet']), 'novel_confirmed': novel_independent, 'verdict': verdict,
            'delta': v.delta, 'noise_band': pr['nb'] or 0.0, 'source_trust': est,
            'closed': 1 if pr.get('closes') else 0, 'opened': int(pr.get('n_opened') or 0),
        }, require_promotion=False)
        ts = datetime.now(timezone.utc).isoformat()
        # AG3/R-SOV V1 값소유(측정주권 2026-07-03): submit 시 *들어온* 값을 서버가 재유도 → 전체 verdict.
        #   persisted 노드가 아니라 incoming(r.script/result_path/metric_value)을 replay 하므로 신규노드도
        #   seal 전에 소유(AG6/V4 ordering 역전 교정 — 기존 producer_replay_for_node 는 아직 persist 안 된
        #   e.metric_value=None 을 읽어 submit 시 항상 not_attempted 로 죽어 있었다). resolve_measurement 이
        #   verified∧regenerated 부분집합에서만 regenerated 를 SSOT 로 치환(SCOPED — 외부/반증값 파괴 금지).
        #   여기서 계산해 next_state·receipt·SET·hist 가 *같은* effective_metric/measurement_grade 를 봉인.
        _vo = self.producer_replay_submit(r.script, r.result_path, r.metric_value)
        # AG5/R-SOV V3 + jp5: 권위(attested)는 *트리가 선언한* non-empty allow-list 대비 서명만 —
        #   empty-attestor fallback 자기서명은 authorship('authored', OWNED_GRADES 밖 → G6 fail-closed)
        #   이지 attestation 이 아니다(버리는 키페어로 G6 를 사는 인센티브 역전 봉합). :654 의 fallback
        #   검증 자체는 유지(서명 유효성+verb 바인딩 = sign-X-execute-Y 봉쇄는 self-sign 에도 가치).
        attested_by_allowlist = attested_by_did is not None and bool(attestors)
        authored_self_signed = attested_by_did is not None and not attestors
        effective_metric, measurement_grade, replay_status = resolve_measurement(
            _vo, r.metric_value, attested=attested_by_allowlist, authored=authored_self_signed)
        next_state = derive_node_state({
            'verdict': verdict,
            'verdict_source': 'scripted',
            'novel_confirmed': novel_independent,
            'metric_value': effective_metric,
            'judged_at': ts,
        })
        _require_state_transition(
            derive_node_state({
                'node_state': pr.get('node_state'),
                'verdict_source': pr.get('vsrc'),
                'pred_registered_at': pr.get('pred_registered_at'),
                'pred_metric': pr.get('m'),
                'metric_value': pr.get('existing_metric_value'),
                'judged_at': pr.get('judged_at'),
            }),
            next_state,
        )
        # #M5 (atomic-rescore): 판결 SET 의 *첫 절* 을 원자 CAS claim 으로 — register_prediction 의 원자
        #   write-WHERE 패턴 답습. WHERE (vsrc IS NULL OR vsrc<>'scripted') 가드로 단일 managed-write tx
        #   안에서 동시 submit 중 한쪽만 SET 매칭 → 이중채점(TOCTOU) 봉쇄. judge() 검증을 다 통과한 *뒤*
        #   이 SET 이 실행되므로 거부 시 노드가 빈 scripted 로 잠기지 않는다. RETURN e.tag(claimed)=0행이면
        #   이미 scripted → 아래에서 409. (상단 238행 read-check 는 빠른 거절, 이 가드가 원자 권위.)
        # G1(git-흡수): 이 scripted 판결을 *불변 내용주소 :VerdictReceipt* 로 발행한다. receipt_sha =
        #   sha256(canonical payload) 를 Python 에서 미리 계산(prev=노드의 현 포인터로 체인). 아래 #M5 CAS
        #   *같은 statement* 안에서 SET 직후 MERGE(rec {receipt_sha}) ON CREATE SET + 포인터 전진 →
        #   CAS 가드가 0행이면 receipt 도 안 생김(원자성 보존, 신규 race 창 0). e.verdict 는 체인 head 의 파생 캐시.
        # P0a (ManifestoGap R8): producer replay 상태를 판결에 persist — 채점 스크립트 재실행 검증이
        #   시도됐나/일치했나를 label 로 공시(TOUCH_THE_SKY '영수증은 현실이 끊어 준다'의 관측가능화).
        #   not_attempted = LAKATOS_REPLAY_EXEC off(dead-σ 교정: 검증 불가는 부재지 반증 아님) 또는 미주입;
        #   verified = 재실행 측정이 제출값과 일치; mismatch = 불일치(승격 floor 가 이걸로 차단);
        #   not_replayable = 재실행 시도했으나 실행 불가(CLI 계약 비호환 등 — 2026-07-13, mismatch 오분류 교정).
        #   (replay_status·effective_metric·measurement_grade 는 위 값소유 seam 에서 이미 계산됨.)
        prev_rsha = pr.get('prev_receipt_sha')
        target_id = pr.get('closes')   # q_target_identity_scheme: 선언 의미키(pred_closes)
        # DE1: G1 receipt 봉인필드 조립을 순수 정책으로 추출 — AG3 measurement_grade 봉인(server_regenerated/
        #   client_asserted). metric_value 도 값소유 결과(effective_metric)를 봉인한다.
        receipt_fields = build_receipt_fields(
            tree=name, tag=tag, target_id=target_id, verdict=verdict, metric_name=pr['m'],
            metric_value=effective_metric, novel_confirmed=novel_independent, lakatos_status=lakatos_status,
            judged_at=ts, judge_script_sha=stored_sha, prev_receipt_sha=prev_rsha,
            measurement_grade=measurement_grade,
            engine_rule_sha=ENGINE_RULE_SHA)   # jp1: 판관 정체성 봉인(v2) — 명시 전달(가드가 핀)
        rsha = receipt_content_sha(receipt_fields)
        ops = [("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                   SET e._cas = coalesce(e._cas,0) + 0
                   WITH e
                   WHERE e.verdict_source IS NULL OR e.verdict_source <> 'scripted'
                      OR ($freshen AND e.verdict = 'partial'
                          AND e.lakatos_status IN ['novel_not_server_anchored', 'provisional_stale_engine']
                          AND e.metric_value = $mv)
                   SET e.metric_name=$mn, e.metric_value=$mv, e.verdict=$v,
                       e.verdict_source='scripted', e.node_state=$node_state,
                       e.judge_script=$script, e.judge_script_sha=$sha,
                       e.result_path=coalesce(nullif($rp,''), e.result_path), e.judged_at=$ts,
                       e.novel_confirmed=$novel, e.source_trust=$st, e.lakatos_status=$lstat,
                       e.eureka_felt=$eu_felt, e.eureka_true=$eu_true,
                       e.eureka_hallucinated=$eu_hall, e.eureka_reasons=$eu_reasons,
                       e.eureka_bf=$eu_bf, e.qualitative_self_report=$qsr,
                       e.novel_server_anchored=$nsa, e.assurance_tier_resolved=$atier,
                       e.attested_by_did=$attested_by_did, e.replay_status=$replay_status,
                       e.measurement_grade=$mg,
                       e.engine_freshness=$efresh, e.judged_by_boot_git_sha=$boot_sha
                   WITH e
                   MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                     ON CREATE SET rec.tree=$tree, rec.tag=$tag, rec.target_id=$target_id,
                       rec.verdict=$v, rec.verdict_source='scripted', rec.metric_name=$mn,
                       rec.metric_value=$mv, rec.novel_confirmed=$novel, rec.lakatos_status=$lstat,
                       rec.judged_at=$ts, rec.judge_script_sha=$sha, rec.prev_receipt_sha=$prev_rsha,
                       rec.measurement_grade=$mg, rec.engine_rule_sha=$engine_rule_sha
                   MERGE (e)-[:HAS_RECEIPT]->(rec)
                   SET e.current_receipt_sha=$rsha
                   RETURN e.tag AS claimed""",
                dict(tree=name, tag=tag, mn=pr['m'], mv=effective_metric, v=verdict,
                     mg=measurement_grade,   # AG3: 측정 출처등급(server_regenerated/client_asserted) 봉인
                     freshen=freshen_anchor,   # novel-anchor freshen: CAS 탈출은 앵커-데모트 partial 동일값 재제출만
                     script=r.script, sha=stored_sha, rp=r.result_path, ts=ts, novel=novel_independent,
                     node_state=next_state.value,
                     st=est, lstat=lakatos_status, qsr=qual_self_report,
                     nsa=(novel_server_sha is not None),   # FF1 phase1: cross-metric novel 서버앵커 여부(가시성, 점수 불변)
                     atier=tier,   # G6 S5: 이 판결이 어느 tier 로 resolve 됐는지 스탬프(fsck tier-resolve 흔적)
                     attested_by_did=attested_by_did,   # G10: author=서명 유도(client 문자열 아님), 무cert=null
                     replay_status=replay_status,   # P0a: producer replay 상태(not_attempted/verified/mismatch/not_replayable)
                     rsha=rsha, target_id=target_id, prev_rsha=prev_rsha,   # G1: 내용주소 receipt + 체인 포인터
                     engine_rule_sha=ENGINE_RULE_SHA,   # jp1: 판관 정체성(v2 봉인 필드) persist — 누락=위양성 mismatch
                     efresh=efresh,                     # jp4: 판관 자기진단 관측화(unchecked/fresh/stale_code/incapable/indeterminate)
                     boot_sha=(fresh or {}).get('boot_git_sha'),   # jp4: 노드-레벨 판관 신원 provenance(영수증 봉인은 jp1 engine_rule_sha 가 정본)
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
        # R6(후속 PROM): pre-commit fsck 시트 — 이제 쓸 record 를 *쓰기 전에* 같은 체커(boundary_fsck ==
        #   fsck_node == 감사)로 검사. 정상 경로는 by-construction 통과(prereg 필수·tier/receipt 스탬프
        #   동봉)라 이 시트의 가치는 활성 필터가 아니라 **드리프트 보험**: 미래의 어떤 write 경로 변경이
        #   스탬프를 빠뜨리면 라이브에서 즉시 422(원자성 무훼손 — kg_tx 이전 거부, 잠긴 노드 없음).
        #   prereg 다리: judge() 가 이미 PredictionMissing 으로 구조 강제하므로(여기 도달 = pred_metric
        #   실재), 시트에는 실측 timestamp 또는 metric-등록 증거를 싣는다 — 시트의 실이빨은 tier/원장
        #   스탬프 드리프트(레거시 read-double 이 timestamp 필드를 안 실어도 prereg 로 오발화하지 않음).
        _prospective = dict(verdict=verdict, verdict_source='scripted',
                            pred_registered_at=(pr.get('pred_registered_at')
                                                or ('(pred-metric-registered)' if pr.get('m') else None)),
                            judged_at=ts,
                            source_trust=est, assurance_tier_resolved=tier,
                            current_receipt_sha=rsha, qualitative_self_report=qual_self_report)
        _seat = audit_fsck.boundary_fsck(_prospective)
        if _seat:
            raise HTTPException(422, f'pre-commit fsck 거부(쓰기 전 — 원장/스탬프 드리프트): '
                                     f'{[(f.check_id, f.severity) for f in _seat]}')
        tx_result = self.kg_tx(ops)
        # #M5: 원자 CAS claim 결과 판정 — 첫 op(가드된 판결 SET)이 0행이면 동시 submit 이 이미 점유 → 409.
        #   per-op 결과 shape(len==ops, 각 op 의 .data() 리스트)일 때만 검사(실제 KG 트랜잭션). 그 외(미모델
        #   테스트 더블/None)는 상단 read-check 가 권위 — 하위호환 보존(좁은 검사로 거짓 409 회피).
        if (isinstance(tx_result, list) and len(tx_result) == len(ops)
                and isinstance(tx_result[0], list) and not tx_result[0]):
            raise HTTPException(409, '동시/재채점 차단 — 이미 scripted (원자 CAS claim 0행; 새 노드로 분기할 것)')
        self.hist(name, 'test_result', tag, dict(value=effective_metric, baseline=pr['b'],
                                                 delta=round(v.delta, 4), verdict=verdict, script=r.script,
                                                 novel=v.novel, script_sha=stored_sha,
                                                 freshen=freshen_anchor))
        return {'ok': True, 'freshen': freshen_anchor,
                'verdict': verdict, 'delta': round(v.delta, 4), 'novel': v.novel,
                'lakatos': lakatos_status, 'metric_verdict': v.verdict,
                'requires_human': bool(decided.get('requires_human')),
                # #H3: sha 영수증이 서버 파일재계산으로 검증됐는지(False=inline/미존재 → 정직 fallback, client 값).
                'script_sha_server_verified': sha_verified, 'judge_script_sha': stored_sha,
                # G10: authorship 은 서명에서 유도(무cert=None) — client 문자열이 아니다.
                'attested_by': attested_by_did,
                'eureka': {'felt': eu.felt, 'true': eu.true, 'hallucinated': eu.hallucinated,
                           'reasons': list(eu.reasons), 'bf': round(eu.bf, 3)},
                'rule': v.reason, 'replay': replay_command(r.script, r.result_path)}

    def load_receipt_chain(self, name: str, tag: str) -> dict:
        """노드의 :VerdictReceipt 체인 + 현 포인터 로드(G1). fold/verify 의 read 경로."""
        head_rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     RETURN e.current_receipt_sha AS head, e.verdict AS cache_verdict,
                            e.verdict_source AS cache_source""", tree=name, tag=tag)
        if not head_rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        h = head_rows[0]
        # C1 S3-engine: receipt_kind + prediction 봉인필드도 노출 — 외부검증자(c1verify)가 read 표면
        #   바이트만으로 prediction blob 을 재유도(sha 재계산)할 수 있어야 한다(포인터 신뢰 금지).
        # jp1: verdict 봉인필드(tree/tag/target_id/metric_value/novel_confirmed/lakatos_status/
        #   measurement_grade/engine_rule_sha)도 전량 노출 — v1/v2 verdict blob 재유도가 같은 표면에서
        #   성립(jp3 recompute·외부검증자 소비). judged_at 는 기존 노출분 재사용 불가라 명시 추가.
        recs = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})-[:HAS_RECEIPT]->(r:VerdictReceipt)
                     RETURN r.receipt_sha AS receipt_sha, r.prev_receipt_sha AS prev_receipt_sha,
                            r.verdict AS verdict, r.verdict_source AS verdict_source,
                            r.receipt_kind AS receipt_kind, r.metric_name AS metric_name,
                            r.direction AS direction, r.baseline_value AS baseline_value,
                            r.noise_band AS noise_band, r.scale_type AS scale_type,
                            r.novel_prediction AS novel_prediction, r.novel_metric AS novel_metric,
                            r.novel_direction AS novel_direction, r.novel_threshold AS novel_threshold,
                            r.judge_script_sha AS judge_script_sha, r.closes_question AS closes_question,
                            r.credence AS credence, r.baseline_lineage AS baseline_lineage,
                            r.registered_at AS registered_at,
                            r.tree AS tree, r.tag AS tag, r.target_id AS target_id,
                            r.metric_value AS metric_value, r.novel_confirmed AS novel_confirmed,
                            r.lakatos_status AS lakatos_status, r.judged_at AS judged_at,
                            r.measurement_grade AS measurement_grade,
                            r.engine_rule_sha AS engine_rule_sha""", tree=name, tag=tag)
        return {'head': h.get('head'), 'cache_verdict': h.get('cache_verdict'),
                'cache_source': h.get('cache_source'), 'receipts': list(recs or [])}

    def verify_verdict_chain(self, name: str, tag: str) -> dict:
        """G1 rebuild_verify(verdict 판): 체인 fold 로 현재 verdict 를 *재유도*해 e.verdict 캐시와 대조.

        캐시를 손상시키면(또는 포인터 dangling) 불일치/ReceiptChainBroken 으로 검출 — '캐시 신뢰 금지, 재유도가 판관'.
        """
        chain = self.load_receipt_chain(name, tag)
        folded = fold_receipt_chain(chain['receipts'], chain['head'],
                                    cache_verdict=chain['cache_verdict'], cache_source=chain['cache_source'])
        ok = folded['verdict'] == chain['cache_verdict']
        return {'ok': ok, 'rederived': folded['verdict'], 'cache': chain['cache_verdict'],
                'from_receipt': folded['from_receipt']}

    def demote_stale_canonical(self, name: str, *, dry_run: bool = True) -> dict:
        """jp1 stale-CANONICAL 재심 스윕(opt-in ops verb) — '오늘 판관이면 이걸 여전히 CANONICAL 이라
        부를까?'를 원장 수준에서 집행. head receipt 의 sealed engine_rule_sha 가 유효 floor
        (docs/engine_rule_floor.json 선언분 ∪ 현 ENGINE_RULE_SHA) 밖이면 — v1 legacy 의 필드 부재
        (익명 판관) 포함 — 재심 전까지 former_canonical 강등 + v2 engine receipt mint(원장 append,
        app.py AGM per-tag CAS 패턴 계승). dry_run 기본 true = 후보 열거만(비파괴 기본off).
        인간 잠금(valid_until_rebutted=false)은 강등하지 않고 skipped_locked 로 보고만.
        demoted 카운트가 novel 오라클(stale_canonical_auto_demoted)의 실측값."""
        floor = effective_floor()
        rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {verdict:'CANONICAL'})
                  OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(r:VerdictReceipt {receipt_sha:e.current_receipt_sha})
                  RETURN e.tag AS tag, e.current_receipt_sha AS prev_rsha,
                         r.engine_rule_sha AS ers,
                         coalesce(e.valid_until_rebutted, true) AS vur''', tree=name)
        stale = [x for x in (rows or []) if x.get('ers') not in floor]
        locked = [x['tag'] for x in stale if x.get('vur') is False]
        candidates = [x for x in stale if x.get('vur') is not False]
        out = {'tree': name, 'dry_run': dry_run, 'floor_size': len(floor),
               'canonical_total': len(rows or []),
               'candidates': [{'tag': x['tag'], 'sealed_engine_rule_sha': x.get('ers')}
                              for x in candidates],
               'skipped_locked': locked, 'demoted': []}
        if dry_run:
            return out
        ts = datetime.now(timezone.utc).isoformat()
        for x in candidates:
            prev = x.get('prev_rsha')
            rsha = receipt_content_sha(dict(
                tree=name, tag=x['tag'], target_id=None, verdict='former_canonical',
                verdict_source='engine', metric_name=None, metric_value=None,
                novel_confirmed=None, lakatos_status=None, judged_at=ts,
                judge_script_sha=None, prev_receipt_sha=prev, engine_rule_sha=ENGINE_RULE_SHA))
            done = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                      WHERE e.verdict='CANONICAL'
                        AND coalesce(e.current_receipt_sha,'') = coalesce($prev,'')
                      SET e.verdict='former_canonical', e.verdict_source='engine',
                          e.current_best_pointer=false, e.node_state=$former_state,
                          e.demoted_at=$ts, e.stale_engine_rule_demoted_at=$ts
                      MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                        ON CREATE SET rec.tree=$tree, rec.tag=$tag, rec.verdict='former_canonical',
                          rec.verdict_source='engine', rec.judged_at=$ts, rec.prev_receipt_sha=$prev,
                          rec.engine_rule_sha=$engine_rule_sha
                      MERGE (e)-[:HAS_RECEIPT]->(rec)
                      SET e.current_receipt_sha=$rsha
                      RETURN e.tag AS tag''',
                           tree=name, tag=x['tag'], prev=prev, rsha=rsha, ts=ts,
                           former_state=NodeState.FORMER_CANONICAL.value,
                           engine_rule_sha=ENGINE_RULE_SHA)
            if done:
                out['demoted'].append(x['tag'])
                self.hist(name, 'stale_engine_demotion', x['tag'],
                          {'sealed': x.get('ers'), 'floor_size': len(floor), 'receipt_sha': rsha})
        return out
