"""R4-LEDGER — verdict 원장 완결 가드 (후속 PROM 2026-07-03, 원장의 마지막 창 봉합).

  guard_defect(음성)     : test_canonical_cache_tamper_is_detected_not_endorsed
        — CANONICAL 승격이 무영수증이면 verify 오라클이 *역방향* 판정한다: 정직 승격=변조(ok=False),
          캐시를 progressive 로 되돌리는 변조=정상(ok=True). 승격이 receipt 를 민팅하면 정방향 복원:
          정직 승격 ok=True, 캐시 되돌림(승격 말소 공격) ok=False.
  guard_mechanism(양성)  : test_promotion_and_demotion_mint_v1_receipts
        — 승격 receipt = v1 null-스펙({verdict:CANONICAL, verdict_source:'admin', 측정필드 전부 null —
          측정영수증 위장 금지, null 이 정직}, prev=현 head, 인코딩 bump 없음: receipt_content_sha 재유도
          일치) + 직전 canonical 강등 receipt(verdict_source:'engine', prev=old 의 이전 head — prev 체인
          한 칸 걷기가 '(was <tag>)' 복구영수증의 reflog 동형) + else-분기 행정 verdict 도 동형 발행.

fake 는 dispatch+파라미터 적용형(_StatefulKg/_BeliefKg 장르): 구현이 MERGE(rec) 를 안 실으면(revert)
fake 도 receipt 를 안 민팅 → defect 가드 RED. floor 는 monkeypatch 로 고정(H5 선례 — 시험 대상은 원장).

# KG: LakatosTree_GitAbsorption_20260702 / followup-R4-verdict-ledger
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import server.contexts.tree.judgement_service as js_mod
from lakatos.verdicts import receipt_content_sha
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import VerdictIn


class _LedgerKg:
    """승격/강등/행정 경로의 원장 시맨틱을 충실 적용하는 상태형 KG.

    노드 store: tag → props. receipts: [{receipt_sha, prev_receipt_sha, verdict, verdict_source}].
    구현 쿼리에 'MERGE (rec:VerdictReceipt' 가 *있을 때만* receipt 민팅(revert-민감)."""

    def __init__(self, nodes: dict[str, dict]):
        self.nodes = {k: dict(v) for k, v in nodes.items()}
        self.receipts: list[dict] = []
        self.last_promo_ts: str | None = None   # 구현이 넘긴 judged_at 캡처(v1 재유도 대조용)

    def _mint(self, node: dict, rsha, prev, verdict, source):
        self.receipts.append({'receipt_sha': rsha, 'prev_receipt_sha': prev,
                              'verdict': verdict, 'verdict_source': source})
        node['current_receipt_sha'] = rsha

    def __call__(self, query, **p):
        tag = p.get('tag')
        # ── set_verdict CANONICAL: pre 스냅샷 read ──
        if 'HAS_ARGUMENT' in query and 'RETURN cur.verdict AS verdict' in query:
            n = self.nodes.get(tag)
            if not n:
                return []
            row = {k: n.get(k) for k in ('verdict', 'verdict_source', 'node_state', 'source_trust',
                                         'novel_confirmed', 'qualitative_self_report', 'author')}
            row['args'] = []
            row['assurance_tier'] = None
            if 'AS prev_receipt_sha' in query:            # R4: 포인터 스냅샷
                row['prev_receipt_sha'] = n.get('current_receipt_sha')
            if 'AS old_tag' in query:                     # R4: 직전 canonical 스냅샷
                old = next(((t, o) for t, o in self.nodes.items()
                            if o.get('verdict') == 'CANONICAL' and t != tag), None)
                row['old_tag'] = old[0] if old else None
                row['old_prev'] = old[1].get('current_receipt_sha') if old else None
            return [row]
        # ── set_verdict CANONICAL: 원자 CAS write ──
        if "SET cur.verdict='CANONICAL'" in query:
            cur = self.nodes[tag]
            self.last_promo_ts = p.get('ts')
            if (p.get('exp_verdict') or '') != (cur.get('verdict') or ''):
                return []
            if '$prev_rsha' in query and \
                    (p.get('prev_rsha') or '') != (cur.get('current_receipt_sha') or ''):
                return []                                  # 포인터 CAS 불일치
            old = next(((t, o) for t, o in self.nodes.items()
                        if o.get('verdict') == 'CANONICAL' and t != tag), None)
            if '$old_tag' in query:                        # old 스냅샷 CAS
                if (old[0] if old else None) != p.get('old_tag'):
                    return []
            if old is not None:
                old[1].update(verdict='former_canonical', verdict_source='engine',
                              current_best_pointer=False)
                if 'MERGE (orec:VerdictReceipt' in query:
                    self._mint(old[1], p['old_rsha'], p.get('old_prev'),
                               'former_canonical', 'engine')
            cur.update(verdict='CANONICAL', verdict_source='admin',
                       current_best_pointer=True)
            if 'MERGE (rec:VerdictReceipt' in query:
                self._mint(cur, p['rsha'], p.get('prev_rsha'), 'CANONICAL', 'admin')
            return [{'tag': tag}]
        # ── else-분기(행정 verdict): 상태 read / mini-CAS write ──
        if 'RETURN e.verdict AS verdict' in query and 'pred_registered_at' in query:
            n = self.nodes.get(tag)
            if not n:
                return []
            row = {k: n.get(k) for k in ('verdict', 'verdict_source', 'node_state',
                                         'pred_registered_at', 'judged_at', 'metric_value')}
            if 'AS prev_receipt_sha' in query:
                row['prev_receipt_sha'] = n.get('current_receipt_sha')
            return [row]
        if "e.verdict_source='admin'" in query and 'SET e.verdict=$verdict' in query:
            n = self.nodes[tag]
            if '$prev_rsha' in query and \
                    (p.get('prev_rsha') or '') != (n.get('current_receipt_sha') or ''):
                return []
            n.update(verdict=p['verdict'], verdict_source='admin', node_state=p['node_state'])
            if 'MERGE (rec:VerdictReceipt' in query:
                self._mint(n, p['rsha'], p.get('prev_rsha'), p['verdict'], 'admin')
            return [{'tag': tag}]
        # ── receipt 체인 read (load_receipt_chain / verify) ──
        if 'current_receipt_sha AS head' in query:
            n = self.nodes.get(tag)
            return [{'head': n.get('current_receipt_sha'), 'cache_verdict': n.get('verdict'),
                     'cache_source': n.get('verdict_source')}] if n else []
        if 'HAS_RECEIPT' in query and 'receipt_sha AS receipt_sha' in query:
            return [dict(r) for r in self.receipts]
        return [{'tag': tag}]


def _svc(kg) -> JudgementService:
    svc = JudgementService(kg=kg, kg_tx=lambda ops: [[{'ok': 1}] for _ in ops],
                           hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None)
    svc._eigentrust_credibility = lambda *a, **k: {}
    return svc


def _floor_pass(monkeypatch):
    monkeypatch.setattr(js_mod, 'synthesize_promotion',
                        lambda **k: {'ok': True, 'reasons': [], 'gates': {}})


def _scored_node(rsha='r1' * 32):
    """submit 완료 상태의 노드(영수증 1개 보유) — 승격의 정직한 출발점."""
    return {'verdict': 'progressive', 'verdict_source': 'scripted',
            'node_state': 'CANONICAL_CANDIDATE', 'novel_confirmed': True,
            'qualitative_self_report': False, 'current_receipt_sha': rsha}


def _seed_receipt(kg: _LedgerKg, tag: str):
    rsha = kg.nodes[tag]['current_receipt_sha']
    kg.receipts.append({'receipt_sha': rsha, 'prev_receipt_sha': None,
                        'verdict': 'progressive', 'verdict_source': 'scripted'})


# ── guard_defect (음성): verify 역방향 판정의 죽음 ─────────────────────────────────────────
def test_canonical_cache_tamper_is_detected_not_endorsed(monkeypatch):
    _floor_pass(monkeypatch)
    kg = _LedgerKg({'n': _scored_node()})
    _seed_receipt(kg, 'n')
    svc = _svc(kg)
    assert svc.set_verdict('T', 'n', VerdictIn(verdict='CANONICAL'))['ok'] is True
    # (1) 정직한 승격이 체인으로 재유도된다 — 무영수증이면 fold=progressive≠캐시 CANONICAL → ok=False(현행 RED).
    v = svc.verify_verdict_chain('T', 'n')
    assert v['ok'] is True and v['rederived'] == 'CANONICAL', \
        f'정직 승격을 변조로 판정(역방향 오라클): {v}'
    # (2) 캐시 되돌림 변조(승격 말소 공격): 무영수증이면 ok=True(변조 승인 — 현행 RED), 원장 완결 후 ok=False.
    kg.nodes['n']['verdict'] = 'progressive'
    v2 = svc.verify_verdict_chain('T', 'n')
    assert v2['ok'] is False and v2['rederived'] == 'CANONICAL', \
        f'승격 말소 변조를 정상으로 승인: {v2}'


def test_admin_verdict_mints_receipt_and_tamper_detected(monkeypatch):
    """else-분기(행정 verdict, 예: superseded)도 동형 — 무영수증 이동은 이제 없다."""
    _floor_pass(monkeypatch)
    kg = _LedgerKg({'n': _scored_node()})
    _seed_receipt(kg, 'n')
    svc = _svc(kg)
    assert svc.set_verdict('T', 'n', VerdictIn(verdict='superseded'))['ok'] is True
    assert len(kg.receipts) == 2, '행정 verdict 이동이 무영수증(원장 구멍)'
    v = svc.verify_verdict_chain('T', 'n')
    assert v['ok'] is True and v['rederived'] == 'superseded'
    kg.nodes['n']['verdict'] = 'progressive'   # 행정 이동 말소 시도
    assert svc.verify_verdict_chain('T', 'n')['ok'] is False


# ── guard_mechanism (양성): v1 null-스펙 receipt + 강등 동반 + 복구 오라클 ──────────────────
def test_promotion_and_demotion_mint_v1_receipts(monkeypatch):
    _floor_pass(monkeypatch)
    old_head = 'o1' * 32
    kg = _LedgerKg({'n': _scored_node(), 'oldc': {'verdict': 'CANONICAL', 'verdict_source': 'admin',
                                                  'node_state': 'CANONICAL',
                                                  'current_receipt_sha': old_head}})
    _seed_receipt(kg, 'n')
    kg.receipts.append({'receipt_sha': old_head, 'prev_receipt_sha': None,
                        'verdict': 'CANONICAL', 'verdict_source': 'admin'})
    svc = _svc(kg)
    svc.set_verdict('T', 'n', VerdictIn(verdict='CANONICAL'))
    # (1) 승격 receipt: v1 null-스펙 — 측정필드 전부 null(측정영수증 위장 금지), prev=승격 전 head.
    promo = next(r for r in kg.receipts if r['verdict'] == 'CANONICAL' and r['verdict_source'] == 'admin'
                 and r['prev_receipt_sha'] == 'r1' * 32)
    assert kg.nodes['n']['current_receipt_sha'] == promo['receipt_sha']
    # (2) 직전 canonical 강등 receipt: engine 귀속, prev=old 의 이전 head — prev 한 칸 걷기 = '(was oldc)'.
    demo = next(r for r in kg.receipts if r['verdict'] == 'former_canonical')
    assert demo['verdict_source'] == 'engine' and demo['prev_receipt_sha'] == old_head
    assert kg.nodes['oldc']['verdict'] == 'former_canonical'
    assert kg.nodes['oldc']['current_receipt_sha'] == demo['receipt_sha']
    was = next(r for r in kg.receipts if r['receipt_sha'] == demo['prev_receipt_sha'])
    assert was['verdict'] == 'CANONICAL', 'prev 체인 한 칸 걷기가 강등 전 상태를 복구하지 못함'
    # (3) 인코딩 v1 결정론: 서비스가 판 receipt_sha 가 null-스펙 필드의 content-sha 재유도와 일치(bump 없음).
    ts = kg.last_promo_ts   # 구현이 파라미터로 넘긴 judged_at (fake 가 캡처)
    refields = dict(tree='T', tag='n', target_id=None, verdict='CANONICAL', verdict_source='admin',
                    metric_name=None, metric_value=None, novel_confirmed=None, lakatos_status=None,
                    judged_at=ts, judge_script_sha=None, prev_receipt_sha='r1' * 32)
    assert receipt_content_sha(refields) == promo['receipt_sha'], \
        'v1 인코딩 재유도 불일치 — 필드셋/정규화가 스펙 밖(인코딩 bump 위험)'
    # (4) 두 노드 verify 모두 정방향.
    assert svc.verify_verdict_chain('T', 'n')['ok'] is True
    assert svc.verify_verdict_chain('T', 'oldc')['ok'] is True


def test_promotion_pointer_cas_blocks_stale_write(monkeypatch):
    """포인터 스냅샷 CAS: pre-read 와 write 사이 동시 재채점(head 전진)이 끼면 0행 → 409."""
    _floor_pass(monkeypatch)
    kg = _LedgerKg({'n': _scored_node()})
    _seed_receipt(kg, 'n')
    svc = _svc(kg)
    pre = kg.__call__   # read 후 write 전에 head 를 몰래 전진시키는 래퍼
    def race(query, **p):
        rows = pre(query, **p)
        if 'HAS_ARGUMENT' in query and 'AS prev_receipt_sha' in query:
            kg.nodes['n']['current_receipt_sha'] = 'x9' * 32   # 동시 전진
        return rows
    svc.kg = race
    with pytest.raises(HTTPException) as e:
        svc.set_verdict('T', 'n', VerdictIn(verdict='CANONICAL'))
    assert e.value.status_code == 409
