"""P7-A: grounding/이론 위생 — single-source 상수 원칙 강제 (TDD RED→GREEN).

THEORY P0 'grounding single-source 상수' 가 직접 위반된 3건:
  GROUND-1     agm.demote_canonical 의 magic 0.1
  GROUND-2/LKT-T3-1  claim._event_confidence 의 realm/action 하드코딩 confidence
  LKT-T3-2/3   explore.voi 의 존재않는 SKILL.md 참조 + Howard1966 SOURCES 미등록
"""
import re

import pytest

import lakatos.grounding as G
from lakatos.engine import Realm, ResearchEvent
import lakatos.agm as agm
import lakatos.claim as claim
import lakatos.explore as explore


# ── GROUND-1: agm demote penalty grounded + 실소비 ──────────────────────────
def test_demote_canonical_penalty_grounded():
    assert 'demote_canonical_penalty' in G.GROUNDED
    g = G.GROUNDED['demote_canonical_penalty']
    assert g['value'] == 0.1
    assert g['tier'] == 'policy'           # AGM 방법은 문헌, 0.1 여유폭은 정책
    assert g['source'] in G.SOURCES


def test_agm_demote_consumes_grounded_penalty():
    pen = G.GROUNDED['demote_canonical_penalty']['value']
    old = agm.Belief(belief_id='old', statement='옛 정본', kind='protective_belt', credence=0.9)
    new = agm.Belief(belief_id='new', statement='새 정본', kind='protective_belt', credence=0.6)
    r = agm.demote_canonical([old], 'old', new)
    demoted = next(b for b in r.base if b.belief_id == 'old')
    assert demoted.credence == pytest.approx(min(0.9, max(0.6 - pen, 0.0)))   # 0.5


def test_agm_source_has_no_bare_penalty_literal():
    # demote_canonical 본문에 0.1 리터럴이 직접 박혀있지 않다 (grounding 경유).
    src = (agm.__file__,)
    text = open(src[0], encoding='utf-8').read()
    body = text.split('def demote_canonical', 1)[1]
    assert 'new_canonical.credence - 0.1' not in body, 'demote 가 여전히 0.1 하드코딩'


# ── GROUND-2 / LKT-T3-1: claim 증거 confidence grounded ─────────────────────
def test_evidence_realm_confidence_grounded():
    assert 'evidence_realm_confidence' in G.GROUNDED
    vals = G.GROUNDED['evidence_realm_confidence']['value']
    for r in Realm:
        assert r.name in vals, f'{r.name} realm confidence 누락'
    assert G.GROUNDED['evidence_realm_confidence']['tier'] == 'policy'


def test_evidence_action_confidence_grounded():
    assert 'evidence_action_confidence' in G.GROUNDED
    vals = G.GROUNDED['evidence_action_confidence']['value']
    assert {'pass', 'fail', 'verdict', 'doubt'} <= set(vals)
    assert G.GROUNDED['evidence_action_confidence']['tier'] == 'policy'


def test_claim_event_confidence_consumes_grounded_realm():
    realm_vals = G.GROUNDED['evidence_realm_confidence']['value']
    ev = ResearchEvent(name='e', realm=Realm.BASH, actor='a', action='observe', target='t')
    assert claim._event_confidence(ev) == pytest.approx(realm_vals['BASH'])


def test_claim_event_confidence_consumes_grounded_action():
    act_vals = G.GROUNDED['evidence_action_confidence']['value']
    ev = ResearchEvent(name='e', realm=Realm.AGENT, actor='a', action='build_success', target='t')
    assert claim._event_confidence(ev) == pytest.approx(act_vals['pass'])


def test_claim_source_has_no_inline_realm_confidence_dict():
    text = open(claim.__file__, encoding='utf-8').read()
    # 옛 하드코딩 패턴(Realm.INTERNET: 0.35 …)이 모듈에서 사라졌다.
    assert not re.search(r'Realm\.\w+:\s*0\.\d+', text), 'claim 에 inline realm confidence dict 잔존'


# ── LKT-T3-2 / LKT-T3-3: explore voi 문서 + Howard1966 SOURCES ───────────────
def test_howard1966_in_sources():
    assert 'howard1966' in G.SOURCES
    assert 'Howard' in G.SOURCES['howard1966']


def test_explore_voi_doc_no_skillmd_cites_howard():
    doc = explore.voi.__doc__ or ''
    assert 'SKILL.md' not in doc, 'voi docstring 이 존재않는 SKILL.md 참조'
    assert 'Howard' in doc, 'voi docstring 이 Howard 출처를 인용해야'
