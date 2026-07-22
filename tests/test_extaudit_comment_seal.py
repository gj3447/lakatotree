"""EXTAUDIT S4 — 해석 층 봉인: 판정 시점 comment 를 영수증 v3 에 봉인 + 사후 드리프트 검출.

적대감사 2026-07-22 급소 #6: 판정은 암호학적으로 봉인되지만 해석(comment)은 자유텍스트였다 —
실증: TripleSubstrate c6 에서 엔진이 degenerating 을 때렸는데 같은 노드 comment 에 ~1,500자
사후 승리 에세이가 실렸다. comment 는 RECEIPT_FIELDS 봉인 밖이라 드리프트 검출이 성립할 여지
자체가 없었다(하네스 진단: Constrain 부재 → Correct 개입지점 없음의 연쇄).

봉합(v3, jp1 presence-dispatch 전례): comment_sha(판정 시점 comment 의 sha256)를 봉인 필드셋에
추가. comment_sha non-null → v3 헤더, engine_rule_sha non-null → v2, 아니면 v1 — 기존 코퍼스
재유도 바이트동일(carve-out by construction). 노드 미러 comment_sha_at_verdict 로 fsck 가
사후 개서를 검출(COMMENT_DRIFT_AFTER_VERDICT, WARN — 삭제·차단 아님: Eilu va-Eilu, 서사는
자유이되 *판정 이후 바뀌었다는 사실*이 침묵할 수 없게).
# KG: q-extaudit-narrative-escape-20260722 / crit-extaudit-20260722-receipt-seals-claims-not-experiments
"""
import hashlib

from lakatos.verdicts import (RECEIPT_FIELDS, canonical_receipt_blob, comment_drift,
                              comment_seal_sha, match_receipt_encoding, receipt_content_sha)


def _fields(**kw):
    base = dict(tree='t', tag='n', target_id=None, verdict='progressive', verdict_source='scripted',
                metric_name='m', metric_value=0.5, novel_confirmed=True, lakatos_status='progressive',
                judged_at='2026-07-23T00:00:00+00:00', judge_script_sha='j1', prev_receipt_sha=None,
                measurement_grade='server_regenerated', engine_rule_sha='e1')
    base.update(kw)
    return base


# ── 봉인: v3 인코딩 + carve-out ─────────────────────────────────────────────────────────
def test_receipt_fields_include_comment_sha():
    assert 'comment_sha' in RECEIPT_FIELDS


def test_v3_header_when_comment_sha_present():
    blob = canonical_receipt_blob(_fields(comment_sha=comment_seal_sha('원본 코멘트')))
    assert blob.startswith(b'verdict-receipt\x00v3\n'), blob[:30]


def test_v2_carveout_byte_identical_without_comment_sha():
    # comment_sha 부재(기존 코퍼스) → v2 경로 바이트동일 — 기존 재유도·골든 전부 무변경.
    f = _fields()
    blob = canonical_receipt_blob(f)
    assert blob.startswith(b'verdict-receipt\x00v2\n')
    assert b'comment_sha' not in blob


def test_comment_seal_changes_sha_and_forgery_detected_both_ways():
    sealed = _fields(comment_sha=comment_seal_sha('판정 시점 코멘트'))
    sha3 = receipt_content_sha(sealed)
    assert sha3 != receipt_content_sha(_fields())              # v3 ≠ v2 (도메인 분리)
    assert match_receipt_encoding(dict(sealed), sha3) == 'current'
    stripped = dict(sealed); stripped['comment_sha'] = None    # v3 에서 필드 떼기 → 위조 검출
    assert match_receipt_encoding(stripped, sha3) is None


# ── 봉인 해시: 결정론 + 빈 코멘트 정규화 ──────────────────────────────────────────────────
def test_comment_seal_sha_deterministic_and_empty():
    assert comment_seal_sha('에세이') == comment_seal_sha('에세이')
    assert comment_seal_sha(None) == comment_seal_sha('') == hashlib.sha256(b'').hexdigest()


# ── 드리프트 검출 (순수 술어) ─────────────────────────────────────────────────────────────
def test_comment_drift_detects_post_verdict_rewrite():
    seal = comment_seal_sha('판정 시점의 겸손한 코멘트')
    same = {'comment': '판정 시점의 겸손한 코멘트', 'comment_sha_at_verdict': seal}
    rewritten = {'comment': '판정 시점의 겸손한 코멘트\n\n[추가] 사실상 승리다: ...1500자 에세이...',
                 'comment_sha_at_verdict': seal}
    legacy = {'comment': '아무 코멘트'}                          # 봉인 이전 노드 — 판단 보류
    assert comment_drift(same) is False
    assert comment_drift(rewritten) is True
    assert comment_drift(legacy) is None                        # 부재≠반증 (dead-σ)


# ── fsck 배선: 드리프트가 감사 표면에 뜬다 (WARN, 비차단) ─────────────────────────────────
def test_fsck_flags_comment_drift_after_verdict():
    from server.contexts.audit.fsck import fsck_node
    seal = comment_seal_sha('원본')
    rec = {'tag': 'n1', 'verdict': 'degenerating', 'verdict_source': 'scripted',
           'pred_registered_at': 'x', 'source_trust': 1.0, 'assurance_tier_resolved': 'anchored',
           'current_receipt_sha': 'r1',
           'comment': '원본 + 사후 승리 서사', 'comment_sha_at_verdict': seal}
    ids = [f.check_id for f in fsck_node(rec)]
    assert 'COMMENT_DRIFT_AFTER_VERDICT' in ids, ids
    rec_ok = dict(rec, comment='원본')
    assert 'COMMENT_DRIFT_AFTER_VERDICT' not in [f.check_id for f in fsck_node(rec_ok)]


# ── submit 배선 앵커 (ag1 장르): 봉인·미러가 프로덕션 경로에 실제로 실린다 ────────────────────
def test_submit_wires_comment_seal():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    svc = (root / 'server' / 'contexts' / 'tree' / 'judgement_service.py').read_text(encoding='utf-8')
    assert 'comment_sha=' in svc and 'comment_sha_at_verdict' in svc, \
        'submit 경로에 comment 봉인/미러 미배선(S4 붕괴)'
    policy = (root / 'server' / 'contexts' / 'tree' / 'judgement_policy.py').read_text(encoding='utf-8')
    assert 'comment_sha' in policy, 'build_receipt_fields 에 comment_sha 미포함'
