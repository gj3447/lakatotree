"""EXTAUDIT S1 — force_of 는 *라벨*도 *영수증 포인터*도 아니라 *측정 등급*을 봐야 한다 (DVC lock 흡수).

적대감사 2026-07-22 급소 #3: client_asserted float 가 verdict_source='scripted' 라벨로 COUNTS 를 샀다.
'scripted' 의 실의미는 "서버가 실행했다"가 아니라 "submit endpoint 를 통과했다"(judgement_policy.py:102)이고,
재실행된 유일 표본 67건 중 51건(76%)이 불일치였다. DVC 에는 클라이언트가 outs 해시를 주장하는 경로
자체가 없다(dvc/stage/serialize.py — outs 는 실행 후 관측으로만 기록) — 그 원칙의 최소 이식:

  measurement_grade == 'client_asserted' ∧ replay_status != 'verified'  →  INCONCLUSIVE
  (진보 credit 제외. "replay 안 켜면 공짜 COUNTS" 인센티브를 "안 켜면 credit 없음"으로 역전.)

키 *부재*(레거시/픽스처)는 신뢰 유지 — 2026-07-21 receipt-gate 와 동일한 _SOURCE_ABSENT 철학.
attested(서명)는 저자성·비부인이 실재하므로 이 슬라이스에선 강등하지 않는다(OWNED_GRADES 정렬은 후속).
# KG: q-extaudit-replay-default-on-20260722 (b)안 / crit-extaudit-20260722-replay-76pct-mismatch
"""
from lakatos.verdicts import force_of_row
from lakatos.quant.metrics import tree_metrics


def _node(tag, **kw):
    base = dict(tag=tag, parent=None, verdict='progressive', verdict_source='scripted',
                novel_registered=True, novel_confirmed=True,
                metric_name='m', metric_value=1.0, metric_scope='s',
                current_receipt_sha='r-' + tag)
    base.update(kw)
    return base


# ── guard_defect (음성 오라클): client_asserted 무검증 값은 힘이 없다 ───────────────────
def test_client_asserted_unreplayed_is_inconclusive():
    assert force_of_row({'verdict': 'progressive', 'verdict_source': 'scripted',
                         'current_receipt_sha': 'r1',
                         'measurement_grade': 'client_asserted',
                         'replay_status': 'not_attempted'}) == 'INCONCLUSIVE'


def test_client_asserted_no_replay_key_is_inconclusive():
    # grade 만 실리고 replay_status 키가 없어도 '검증됨' 아님 → 강등 (fail-closed 방향).
    assert force_of_row({'verdict': 'progressive', 'verdict_source': 'scripted',
                         'current_receipt_sha': 'r1',
                         'measurement_grade': 'client_asserted'}) == 'INCONCLUSIVE'


# ── guard_mechanism (양성 오라클): 검증된/서명된/레거시 값은 힘을 잃지 않는다 ─────────────
def test_server_regenerated_still_counts():
    assert force_of_row({'verdict': 'progressive', 'verdict_source': 'scripted',
                         'current_receipt_sha': 'r1',
                         'measurement_grade': 'server_regenerated',
                         'replay_status': 'verified'}) == 'COUNTS'


def test_attested_grade_still_counts():
    # 서명 경로 무회귀 — 저자성/비부인은 실재(값 검증은 아님 — VAL 사다리에서 L1 로 구분, S3).
    assert force_of_row({'verdict': 'progressive', 'verdict_source': 'scripted',
                         'current_receipt_sha': 'r1',
                         'measurement_grade': 'attested',
                         'replay_status': 'not_attempted'}) == 'COUNTS'


def test_grade_key_absent_legacy_still_counts():
    # 키 부재 = 레거시/픽스처 신뢰 (_SOURCE_ABSENT 철학, 기존 golden 전체 비파괴).
    assert force_of_row({'verdict': 'progressive', 'verdict_source': 'scripted',
                         'current_receipt_sha': 'r1'}) == 'COUNTS'


# ── 파급 (SSOT 술어 하나로 집계 전체 차등): fertility 가 client_asserted 를 안 센다 ───────
def test_tree_metrics_excludes_client_asserted_unreplayed_from_fertility():
    nodes = [
        _node('clean', measurement_grade='server_regenerated', replay_status='verified'),
        _node('asserted1', measurement_grade='client_asserted', replay_status='not_attempted'),
        _node('asserted2', measurement_grade='client_asserted', replay_status='not_attempted'),
    ]
    m = tree_metrics(nodes, [], None)
    assert m['fertility']['confirmed'] == 1, m['fertility']


def test_tree_metrics_client_asserted_replay_verified_keeps_credit():
    # 이중가드: replay 가 실제 verified 면 client 제출값이어도 검증 완료 → credit 유지.
    nodes = [_node('verified', measurement_grade='client_asserted', replay_status='verified')]
    m = tree_metrics(nodes, [], None)
    assert m['fertility']['confirmed'] == 1, m['fertility']
