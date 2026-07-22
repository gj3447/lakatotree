"""EXTAUDIT S3 — VAL(Verdict Assurance Level) L0-L3: 판정 표면에 보증 등급 강제 동봉 (SLSA 흡수).

적대감사 2026-07-22 급소 #5: armed 게이트에서 딴 progressive 와 전부 꺼진 배포에서 딴 progressive 가
소비자에게 바이트 동일하게 보였다 — 구분은 저salience 메타필드뿐. SLSA 원칙 전사:
  · 레벨은 산출물에 *저장*되는 라벨이 아니라 검증(읽기) 시점에 도출되는 판정 (저장=자기신고)
  · 생산자 자기신고는 레벨을 올리지 못한다 — 입력은 서버가 봉인·기록한 필드만
  · L0 basis 는 '부재'(no_receipt)와 '양성 반증'(replay_refuted)을 구분한다

사다리: L0 client_asserted < L1 receipted < L2 replay_verified < L3 attested_witnessed.
L3 은 temporal witness(S7) 전까지 도달 불가 — 그게 정직한 상태다.
표면 계약: 채점/진보 어휘(is_self_report_blocked_verdict)는 bare 방출 금지, 'progressive@L2(...)' 형식.
admin 어휘(proof 등)는 원문 유지(등급 무의미).
# KG: q-extaudit-verdict-context-parity-20260722 / crit-extaudit-20260722-default-disarmed-gates
"""
from lakatos.verdicts import VAL_LEVELS, format_verdict_with_val, verdict_assurance


def _row(**kw):
    base = dict(verdict='progressive', verdict_source='scripted', current_receipt_sha='r1')
    base.update(kw)
    return base


# ── T1 사다리 특성화 ──────────────────────────────────────────────────────────────────
def test_ladder_l0_to_l3():
    assert verdict_assurance({'verdict': 'progressive'})['val'] == 0            # 레거시(키 부재... 아래 참조)
    a1 = verdict_assurance(_row())
    assert a1['val'] == 1                                                        # 영수증 O, 검증 無
    a2 = verdict_assurance(_row(measurement_grade='server_regenerated', replay_status='verified'))
    assert a2['val'] == 2                                                        # 서버 재유도
    a3 = verdict_assurance(
        _row(measurement_grade='server_regenerated', replay_status='verified',
             assurance_tier_resolved='anchored', attested_by_did='did:key:zA',
             engine_rule_sha='e1'),
        tree_attestors=['did:key:zA'], engine_rule_floor=frozenset({'e1'}),
        temporal_witness=True)
    assert a3['val'] == 3                                                        # 전 조건 AND
    assert VAL_LEVELS == ('client_asserted', 'receipted', 'replay_verified', 'attested_witnessed')


def test_l0_basis_distinguishes_absence_kinds():
    # 키 부재(레거시) vs client_asserted 무검증 vs 영수증 미도래 — basis 로 구분(전부 L0 이지만 다른 사연).
    legacy = verdict_assurance({'verdict': 'progressive'})                       # verdict_source 키 자체 부재
    asserted = verdict_assurance(_row(measurement_grade='client_asserted', replay_status='not_attempted'))
    noreceipt = verdict_assurance({'verdict': 'progressive', 'verdict_source': 'scripted',
                                   'current_receipt_sha': None})
    assert legacy['basis'] == ('legacy_no_receipt',)
    assert asserted['basis'] == ('client_asserted_unverified',)
    assert noreceipt['basis'] == ('no_receipt',)


# ── T2 급소 오라클 (parity gap): armed vs disarmed progressive 가 표면에서 달라야 한다 ────
def test_parity_gap_closed_on_surface():
    armed = format_verdict_with_val('progressive', verdict_assurance(
        _row(measurement_grade='server_regenerated', replay_status='verified')))
    disarmed = format_verdict_with_val('progressive', verdict_assurance(
        _row(measurement_grade='client_asserted', replay_status='not_attempted')))
    assert armed != disarmed, "armed/disarmed progressive 가 여전히 동일 표면(급소 #5 잔존)"
    assert '@L2(replay_verified' in armed and '@L0(client_asserted' in disarmed
    assert '@L' in armed and '@L' in disarmed


# ── T3 음성 오라클 (결함 주입): 라벨만 보고 등급 주면 죽는다 ─────────────────────────────
def test_forged_grade_with_refuting_replay_is_l0():
    # grade 라벨은 server_regenerated 인데 replay 가 반증(mismatch) — 라벨 신뢰면 L2 로 새는 위조 row.
    forged = verdict_assurance(_row(measurement_grade='server_regenerated', replay_status='mismatch'))
    assert forged['val'] == 0 and forged['basis'] == ('replay_refuted',)


def test_broken_chain_caps_at_l0():
    ok2 = _row(measurement_grade='server_regenerated', replay_status='verified')
    assert verdict_assurance(ok2, chain_ok=False)['val'] == 0
    assert verdict_assurance(ok2, chain_ok=False)['basis'] == ('receipt_chain_broken',)


# ── T4 dead-σ 무회귀: 검증 불가(None/미주입)는 강등 사유가 아니다 (승급만 없음) ─────────────
def test_unknowns_do_not_demote():
    ok2 = _row(measurement_grade='server_regenerated', replay_status='verified')
    assert verdict_assurance(ok2, chain_ok=None)['val'] == 2          # 체인 미대조 = L2 유지
    assert verdict_assurance(ok2)['val'] == 2                          # floor/attestor 미주입 = L3 불가일 뿐
    nr = verdict_assurance(_row(replay_status='not_replayable'))
    assert nr['val'] == 1                                              # 재실행 불가 = L1 유지(반증 아님)


# ── T5 표면 배선: standing() 이 bare verdict 를 방출하지 않는다 / admin 어휘는 원문 유지 ────
def test_standing_embeds_val_and_keeps_admin_bare():
    from server.contexts.tree.evidence_claim_service import EvidenceClaimService
    svc = object.__new__(EvidenceClaimService)

    def _kg_scored(q, **p):
        return [{'verdict': 'progressive', 'verdict_source': 'scripted', 'current_receipt_sha': 'r1',
                 'measurement_grade': 'client_asserted', 'replay_status': 'not_attempted', 'args': []}]

    svc.kg = _kg_scored
    out = svc.standing('t', 'n')
    assert out['verdict'] == 'progressive@L0(client_asserted,client_asserted_unverified)', out['verdict']
    assert out['assurance']['val'] == 0

    def _kg_admin(q, **p):
        return [{'verdict': 'proof', 'verdict_source': None, 'current_receipt_sha': None,
                 'measurement_grade': None, 'replay_status': None, 'args': []}]

    svc.kg = _kg_admin
    out2 = svc.standing('t', 'n')
    assert out2['verdict'] == 'proof', out2['verdict']   # admin 어휘 원문 — 과잉 포맷 금지
