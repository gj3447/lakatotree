"""Application service for evidence, standing, and claim certification.

# KG: seed-lkt-engine-route-evidence-claim-extract-20260616
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from lakatos.verdict.argue import grounded_extension
from lakatos.verdict.spine import reconcile_standing


def _assemble_af(tag: str, arg_rows: list) -> tuple[set, list]:
    """노드 verdict + 등재된 Argument 들 → Dung AF (arguments, attacks). standing 과 add_critique 공유.
    critique.attacks==tag 이면 verdict 직접 공격, 아니면 다른 argument 공격(verdict 방어)."""
    verdict_arg = f'verdict:{tag}'
    arguments = {verdict_arg}
    attacks: list = []
    for a in arg_rows:
        if not a.get('id'):
            continue
        short = a['id'].split('/')[-1]
        arguments.add(short)
        tgt = verdict_arg if a.get('attacks') == tag else a.get('attacks')
        attacks.append((short, tgt))
    return arguments, attacks
from lakatos.verdict.certify import gate_check, certify_claim, next_actions as cert_next_actions
from lakatos.claim import ClaimStandingPolicy, evaluate_claim_standing
from lakatos.engine import (
    CredibilityTier,
    FoundationMap,
    Possibility,
    Realm,
    ResearchEvent,
    ResearchFrame,
    ResearchProject,
    SourceCredibilityScore,
)
from lakatos.io.replay import LineageReplayGate
from lakatos.io.envfp import environment_fingerprint as default_environment_fingerprint
from lakatos.io.envfp import fingerprint_sha as default_fingerprint_sha
from lakatos.io.lineage import by_output
from lakatos.io.prov import replay_command
from lakatos.world_gates import scan_prompt_injection, web_gate, world_action_gate
from server.contexts.tree.schemas import CritiqueIn, ObservationIn, ResearchEventIn, WorldActionIn
from server.ports import HistoryAppend, KgQuery


FoundationProvider = Callable[[str], FoundationMap | None]
LineageProvider = Callable[[], Iterable[Any]]
EnvironmentProvider = Callable[[], dict]
FingerprintProvider = Callable[[dict], str]
ReproducibleProvider = Callable[[str, str], bool | None]
StandingProvider = Callable[[str, str], dict]
CalibrationProvider = Callable[[str], dict]
StoreResearchEvent = Callable[[str, str, str, str, str, str, Iterable[str] | None, dict], str]


class EvidenceClaimService:
    """Owns evidence ingestion, standing, claim-standing, and certificates."""

    # KG: seed-lkt-engine-route-evidence-claim-extract-20260616

    def __init__(
        self,
        *,
        kg: KgQuery,
        hist: HistoryAppend,
        foundation: FoundationProvider,
        load_lineage: LineageProvider,
        reproducible_for_node: ReproducibleProvider,
        standing: StandingProvider | None = None,
        calibration: CalibrationProvider | None = None,
        store_research_event: StoreResearchEvent | None = None,
        environment_fingerprint: EnvironmentProvider = default_environment_fingerprint,
        fingerprint_sha: FingerprintProvider = default_fingerprint_sha,
    ):
        self.kg = kg
        self.hist = hist
        self.foundation = foundation
        self.load_lineage = load_lineage
        self.reproducible_for_node = reproducible_for_node
        self.standing_provider = standing or self.standing
        self.calibration_provider = calibration or (lambda _name: {"n": 0})
        self.store_research_event_provider = store_research_event or self.store_research_event
        self.environment_fingerprint = environment_fingerprint
        self.fingerprint_sha = fingerprint_sha

    def provenance(self, name: str, tag: str) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_PROV]->(p:ProvNode)
                     RETURN e.judge_script AS script, e.result_path AS rp, e.verdict AS verdict,
                            e.judge_script_sha AS sha, collect({id:p.id,kind:p.kind,type:p.type}) AS prov""",
                       tree=name, tag=tag)
        if not rows or rows[0]['script'] is None:
            raise HTTPException(404, '채점 이력 없음')
        x = rows[0]
        return dict(tag=tag, verdict=x['verdict'], script=x['script'], script_sha=x['sha'],
                    result_path=x['rp'], prov_graph=[p for p in x['prov'] if p['id']],
                    replay=replay_command(x['script'] or '', x['rp'] or ''))

    def add_critique(self, name: str, tag: str, c: CritiqueIn) -> dict:
        self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
              MERGE (a:Argument {id:$tree+'/'+$arg}) SET a.by=$by, a.kind=$kind, a.body=$body,
                    a.attacks=$attacks, a.at=$ts
              MERGE (e)-[:HAS_ARGUMENT]->(a)""",
                tree=name, tag=tag, arg=c.arg_id, by=c.by, kind=c.kind, body=c.body,
                attacks=c.attacks, ts=datetime.now(timezone.utc).isoformat())
        self.hist(name, 'critique', tag, c.model_dump())
        # ★certify.py:13 의 '새 반박이 G3(stands)를 깨면 자동 철회' 이행 — 승격이 stands 를 *요구*한
        # 것의 대칭. 비판 등재 직후 grounded standing 을 재계산하고, CANONICAL 의 standing 이 깨졌으면
        # former_canonical 로 강등(결정론 grounded_extension 사실에만 근거, verdict_source='engine').
        out: dict = {'ok': True, 'note': '비판 등재 — 코드 빌딩은 순수 agent(test_result) 담당'}
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                     RETURN e.verdict AS verdict,
                            coalesce(e.valid_until_rebutted, true) AS vur,
                            collect({id:a.id, attacks:a.attacks}) AS args""",
                       tree=name, tag=tag)
        if rows:
            verdict_arg = f'verdict:{tag}'
            arguments, attacks = _assemble_af(tag, rows[0]['args'])
            stands = verdict_arg in grounded_extension(arguments, attacks)
            decision = reconcile_standing(rows[0]['verdict'], stands=stands,
                                          valid_until_rebutted=bool(rows[0]['vur']))
            out['standing'] = {'stands': stands, **decision}
            if decision['demoted']:
                # 현재최선 철회: CANONICAL→former_canonical. 인간 admin(verdict_source='admin')과 구분.
                self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                      SET e.verdict='former_canonical', e.verdict_source='engine',
                          e.current_best_pointer=false, e.standing_retracted_at=$ts""",
                        tree=name, tag=tag, ts=datetime.now(timezone.utc).isoformat())
                self.hist(name, 'standing_retraction', tag,
                          {'from': 'CANONICAL', 'to': 'former_canonical', 'reason': decision['reason']})
        return out

    def add_research_event(self, name: str, tag: str, ev: ResearchEventIn) -> dict:
        engine_event = ev.to_engine(tag)
        if engine_event.realm in (Realm.INTERNET, Realm.BASH):
            raise HTTPException(422, f'{engine_event.realm.value} 증거는 generic /event 우회 불가 — '
                                     f'POST /observation(G-Web) 또는 /world-action(G-WorldAction) 게이트 경로 사용')
        ts = ev.created_at or datetime.now(timezone.utc).isoformat()
        event_id = f'{name}/{tag}/event/{engine_event.name}'
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     MERGE (ev:ResearchEvent {id:$id})
                     ON CREATE SET ev.name=$event_name, ev.realm=$realm, ev.actor=$actor,
                                   ev.action=$action, ev.target=$tag,
                                   ev.evidence_refs=$evidence_refs, ev.payload=$payload,
                                   ev.created_at=$ts
                     MERGE (e)-[:HAS_RESEARCH_EVENT]->(ev)
                     RETURN ev.id AS id""",
                       tree=name, tag=tag, id=event_id, event_name=engine_event.name,
                       realm=engine_event.realm.value, actor=engine_event.actor,
                       action=engine_event.action, evidence_refs=list(engine_event.evidence_refs),
                       payload=json.dumps(dict(engine_event.payload), ensure_ascii=False), ts=ts)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        self.hist(name, 'research_event', tag, {**engine_event.db_record(), 'id': event_id})
        return {'ok': True, 'id': event_id, 'event': engine_event.name}

    def store_research_event(
        self,
        name: str,
        tag: str,
        event_id: str,
        realm: str,
        action: str,
        actor: str,
        evidence_refs: Iterable[str] | None,
        payload: dict,
    ) -> str:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     MERGE (ev:ResearchEvent {id:$id})
                     ON CREATE SET ev.name=$id, ev.realm=$realm, ev.actor=$actor,
                                   ev.action=$action, ev.target=$tag,
                                   ev.evidence_refs=$evidence_refs, ev.payload=$payload,
                                   ev.created_at=$ts
                     MERGE (e)-[:HAS_RESEARCH_EVENT]->(ev)
                     RETURN ev.id AS id""",
                       tree=name, tag=tag, id=event_id, realm=realm, actor=actor, action=action,
                       evidence_refs=list(evidence_refs or []),
                       payload=json.dumps(payload, ensure_ascii=False),
                       ts=datetime.now(timezone.utc).isoformat())
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        return event_id

    def add_observation(self, name: str, tag: str, o: ObservationIn) -> dict:
        from lakatos.grounding import GROUNDED

        injection = scan_prompt_injection(o.content)
        comps = dict(source_class_weight=o.source_class_weight, link_authority=o.link_authority,
                     primary_source_bonus=o.primary_source_bonus, provenance_score=o.provenance_score,
                     corroboration_score=o.corroboration_score, recency_score=o.recency_score,
                     supply_chain_score=o.supply_chain_score)
        obs = dict(url=o.url, retrieved_at=o.retrieved_at, content_hash=o.content_hash,
                   raw_snapshot_path=o.raw_snapshot_path, source_type=o.source_type,
                   lakatos_location=o.lakatos_location, **comps)
        gate = web_gate(obs, injection=injection)
        if not gate.passed:
            detail = list(gate.reasons)
            if 'trust_components' in detail:
                detail.append('G-Trust: 분해 신뢰 성분 1+ 양수 필요 (bare trust 미지원)')
            raise HTTPException(422, f'G-Web 미통과 — 누락/위반: {detail}')
        payload = {k: str(v) for k, v in obs.items() if v not in (None, '')}
        payload['injection_risk'] = str(injection['risk'])
        payload['injection_signals'] = ','.join(injection['signals'])
        score = SourceCredibilityScore(injection_penalty=injection['risk'],
                                       **{k: (v or 0.0) for k, v in comps.items()})
        payload.update({k: str(round(v, 4)) for k, v in score.as_components().items()})
        tier = score.tier
        if injection['risk'] >= GROUNDED['injection_high_risk_floor']['value'] and tier.value == 'EXTRACTED':
            tier = CredibilityTier.AMBIGUOUS
            payload['injection_tier_capped'] = 'true'
        payload['tier'] = tier.value
        payload['credibility_decomposed'] = 'true'
        payload['confidence'] = str(round(score.trust, 4))
        eid = f'{name}/{tag}/obs/{o.event_id}'
        self.store_research_event_provider(name, tag, eid, 'internet', 'fetch', o.actor, o.evidence_refs, payload)
        self.hist(name, 'observation', tag, {'id': eid, 'url': o.url, 'injection_risk': injection['risk']})
        cred = {'decomposed': payload.get('credibility_decomposed') == 'true',
                'confidence': float(payload['confidence']), 'tier': payload.get('tier'),
                'components': {k: float(payload[k]) for k in SourceCredibilityScore().as_components()
                               if k in payload}}
        return {'ok': True, 'id': eid, 'gate': 'G-Web', 'injection': injection, 'credibility': cred}

    def add_world_action(self, name: str, tag: str, a: WorldActionIn) -> dict:
        act = dict(command=a.command, cwd=a.cwd, exit_code=a.exit_code,
                   stdout_summary=a.stdout_summary, stderr_summary=a.stderr_summary,
                   touched_files=a.touched_files, git_diff_hash=a.git_diff_hash)
        gate = world_action_gate(act, require_git_diff=a.require_git_diff)
        if not gate.passed:
            raise HTTPException(422, f'G-WorldAction 미통과 — 누락: {list(gate.reasons)}')
        payload = {'command': a.command, 'cwd': a.cwd, 'exit_code': str(a.exit_code),
                   'stdout_summary': a.stdout_summary[:500], 'stderr_summary': a.stderr_summary[:500],
                   'touched_files': ','.join(a.touched_files)}
        if a.git_diff_hash:
            payload['git_diff_hash'] = a.git_diff_hash
        payload['confidence'] = '0.8' if a.exit_code == 0 else '0.2'
        eid = f'{name}/{tag}/act/{a.event_id}'
        self.store_research_event_provider(name, tag, eid, 'bash', a.command[:60] or 'bash_run',
                                           a.actor, a.evidence_refs, payload)
        self.hist(name, 'world_action', tag, {'id': eid, 'exit_code': a.exit_code})
        return {'ok': True, 'id': eid, 'gate': 'G-WorldAction'}

    def standing(self, name: str, tag: str) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                     RETURN e.verdict AS verdict, collect({id:a.id, attacks:a.attacks, kind:a.kind, by:a.by}) AS args""",
                       tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        verdict_arg = f'verdict:{tag}'
        arguments, attacks = _assemble_af(tag, rows[0]['args'])
        ext = grounded_extension(arguments, attacks)
        stands = verdict_arg in ext
        return dict(tag=tag, verdict=rows[0]['verdict'], stands=stands,
                    grounded_extension=sorted(ext),
                    note='stands=False → 막지 못한 의문 존재, 판결 재검토 필요 (코드빌딩=순수agent)')

    def research_events(self, name: str, tag: str) -> dict:
        rows = self.research_event_rows(name, tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        events = [event for row in rows if (event := self.event_row_dict(tag, row)) is not None]
        return {"tag": tag, "count": len(events), "events": events}

    def claim_standing(self, name: str, tag: str, require_replay: bool = True) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                     RETURN e.tag AS tag, e.verdict AS verdict, e.source_trust AS source_trust,
                            e.verdict_source AS verdict_source, e.judge_script AS judge_script,
                            e.judge_script_sha AS judge_script_sha, e.result_path AS result_path,
                            collect({id:a.id, attacks:a.attacks, kind:a.kind, by:a.by}) AS args""",
                       tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        x = rows[0]
        result_path = x.get('result_path') or ''
        frame = ResearchFrame(ResearchProject(name=name, goal='claim standing'))
        frame.open_possibility(Possibility(tag, f'claim standing for {name}/{tag}',
                                           evidence_refs=((result_path,) if result_path else ())))
        if x.get('source_trust') is not None:
            frame.record_event(ResearchEvent(
                name=f'{tag}:source-trust',
                realm=Realm.INTERNET,
                actor='server:node',
                action='source_trust',
                target=tag,
                evidence_refs=((result_path,) if result_path else ()),
                payload=(('trust', str(x['source_trust'])),),
            ))
        if x.get('verdict_source') == 'scripted' or x.get('judge_script') or result_path:
            action = 'test_failed' if x.get('verdict') == 'rejected' else 'test_passed'
            refs = tuple(v for v in (result_path, x.get('judge_script_sha') or '') if v)
            frame.record_event(ResearchEvent(
                name=f'{tag}:scripted-result',
                realm=Realm.BASH,
                actor=x.get('judge_script') or 'server:judge',
                action=action,
                target=tag,
                evidence_refs=refs,
                payload=(('exit_code', '0'),) if action == 'test_passed' else (('exit_code', '1'),),
            ))
        for arg in x.get('args') or []:
            event = self.event_from_argument(tag, arg)
            if event is not None:
                frame.record_event(event)
        for row in self.research_event_rows(name, tag):
            event = self.event_from_row(tag, row)
            if event is not None:
                frame.record_event(event)

        lineage = None
        if result_path:
            ds = list(self.load_lineage())
            if result_path in by_output(ds):
                cur_env = self.fingerprint_sha(self.environment_fingerprint())
                lineage = LineageReplayGate.evaluate(
                    result_path,
                    ds,
                    sources={d.output for d in ds if d.kind == 'source'},
                    current_env=cur_env,
                )

        standing_result = evaluate_claim_standing(
            tag,
            frame=frame,
            foundation=self.foundation(name),
            lineage=lineage,
            policy=ClaimStandingPolicy(require_replay=require_replay),
        )
        return standing_result.to_dict()

    def node_certificate(self, name: str, tag: str) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     RETURN e.verdict AS verdict, e.verdict_source AS vsrc,
                            e.pred_metric AS pm, e.judge_script AS script,
                            e.judge_script_sha AS sha, e.result_path AS rp""", tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        x = rows[0]
        checks = []
        prereg = x['vsrc'] == 'scripted' and x['pm'] is not None and bool(x['script'])
        checks.append(gate_check('preregistered', prereg,
                                 f"{x['script']}:{(x['sha'] or '')[:12]}" if prereg else '',
                                 '' if prereg else '사전등록+스크립트 채점 이력 없음(또는 script 미기록)'))
        rep = self.reproducible_for_node(name, tag)
        checks.append(gate_check('reproducible', rep is True,
                                 x['rp'] or '' if rep is True else '',
                                 '' if rep is True else
                                 ('계보 미기록 — 인증은 기록을 요구' if rep is None else 'raw root 재생성 불가')))
        st = self.standing_provider(name, tag)
        checks.append(gate_check('stands', bool(st['stands']),
                                 ','.join(st['grounded_extension']) if st['stands'] else '',
                                 '' if st['stands'] else '미해소 의문 존재'))
        cal = self.calibration_provider(name)
        checks.append(gate_check('calibrated', cal['n'] >= 1,
                                 f"/api/tree/{name}/calibration n={cal['n']} (tree-level)" if cal['n'] >= 1 else '',
                                 '' if cal['n'] >= 1 else 'novel 등록 예측의 보정 기록 0건(트리 수준)'))
        from lakatos.grounding import GROUNDED

        valid_tiers = {'literature', 'policy_in_scale', 'policy'}
        grounded_ok = bool(GROUNDED) and all(g.get('tier') in valid_tiers for g in GROUNDED.values())
        checks.append(gate_check('grounded', grounded_ok,
                                 'lakatos/grounding.py GROUNDED tier registry' if grounded_ok else '',
                                 '시스템 수준 불변식 — 채점 상수 전부 tier 공개(노드별 아님)'
                                 if grounded_ok else 'GROUNDED 레지스트리에 tier 미표기 상수 존재'))
        cert = certify_claim(f'{name}/{tag}', checks, dict(
            as_of=datetime.now(timezone.utc).isoformat(),
            shas={k: v for k, v in {(x['script'] or ''): (x['sha'] or '')}.items() if k and v}))
        return dict(claim_id=cert.claim_id, certified=cert.certified, missing=list(cert.missing),
                    checks=[dict(gate=c.gate, passed=c.passed, evidence_ref=c.evidence_ref,
                                 note=c.note) for c in cert.checks],
                    evidence_window=cert.evidence_window, limits=cert.limits,
                    next_actions=cert_next_actions(cert))

    def research_event_rows(self, name: str, tag: str) -> list[dict]:
        return self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_RESEARCH_EVENT]->(ev:ResearchEvent)
                     RETURN ev.id AS id, ev.name AS name, ev.realm AS realm, ev.actor AS actor,
                            ev.action AS action, ev.evidence_refs AS evidence_refs,
                            ev.payload AS payload, ev.created_at AS created_at
                     ORDER BY ev.created_at, ev.name""", tree=name, tag=tag)

    @staticmethod
    def event_from_argument(tag: str, arg: dict) -> ResearchEvent | None:
        if not arg.get('id'):
            return None
        short = arg['id'].split('/')[-1]
        kind = (arg.get('kind') or 'comment').lower()
        action = 'doubt' if kind == 'doubt' else ('human_verdict' if kind in {'evaluation', 'verdict'} else kind)
        payload = (('confidence', '0.75'),) if action == 'human_verdict' else ()
        return ResearchEvent(
            name=short,
            realm=Realm.HUMAN,
            actor=arg.get('by') or 'human',
            action=action,
            target=tag,
            evidence_refs=(arg['id'],),
            payload=payload,
        )

    @staticmethod
    def event_from_row(tag: str, row: dict) -> ResearchEvent | None:
        if not row.get('name') or not row.get('realm'):
            return None
        try:
            realm = Realm(row['realm'])
        except ValueError:
            return None
        payload_raw = row.get('payload') or '{}'
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:
                payload = {}
        else:
            payload = payload_raw
        return ResearchEvent(
            name=row['name'],
            realm=realm,
            actor=row.get('actor') or '',
            action=row.get('action') or '',
            target=tag,
            evidence_refs=tuple(row.get('evidence_refs') or []),
            payload=tuple((str(k), str(v)) for k, v in payload.items()),
        )

    @classmethod
    def event_row_dict(cls, tag: str, row: dict) -> dict | None:
        event = cls.event_from_row(tag, row)
        if event is None:
            return None
        return {
            "id": row.get("id") or "",
            "name": event.name,
            "realm": event.realm.value,
            "actor": event.actor,
            "action": event.action,
            "target": event.target,
            "evidence_refs": list(event.evidence_refs),
            "payload": dict(event.payload),
            "created_at": row.get("created_at"),
        }
