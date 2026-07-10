"""RED-first 이중가드 — certified-foundation 게이트 (첫 적대적 인증서 *소비자*).

deep-think 2026-07-08 GO게이트: 어떤 결정도 certified 를 읽지 않는다(prophylactic). 이 게이트가 그 빈
소비자 슬롯을 채운다 — foundation admission 을 fail-closed 로: client 가 주장한 status='satisfied' +
자유문자열 evidence_refs 를 불신하고, 각 근거가 *실제 certified 노드*로 해소될 때만 satisfied 유지.
아니면 needed 강등 → FoundationGate gap → synthesize_promotion → CANONICAL 승격 차단.

★단방향 안전: satisfied→gap 만, 절대 gap→satisfied 아님(최악=과보수, fail-open 아님).
이중가드(측정주권 규약 동형):
  guard_defect(음성)   : uncertified/absent/tampered 근거 → 강등(satisfied False, gap). 미구현 시 RED.
  guard_mechanism(양성): certified 근거 → satisfied 유지 + optional/waived 불변 → over-broad reject 방지.
  회귀(비파괴)          : evidence_ok 전부 True(플래그-off 등가) → 기존 satisfied 보존.
"""
from lakatos.engine import FoundationGate, FoundationMap, FoundationRequirement, KnowledgeKind
from lakatos.verdict.cert_gate import certified_foundation


def _fmap(*reqs: FoundationRequirement) -> FoundationMap:
    m = FoundationMap()
    for r in reqs:
        m.add(r)
    return m


def _req(name: str, *, status: str = "satisfied", refs: tuple = ("Tree/n1",),
         optional: bool = False) -> FoundationRequirement:
    return FoundationRequirement(name=name, kind=KnowledgeKind.DATA, question="q", why_needed="w",
                                 evidence_refs=refs, status=status, optional=optional)


def test_guard_defect_uncertified_evidence_downgrades_to_gap() -> None:
    """음성 오라클 — 근거가 certified 아니면 satisfied→needed 강등 → FoundationGate 실패(승격 차단)."""
    fm = _fmap(_req("root-data-contract", refs=("Tree/n_bogus",)))
    out = certified_foundation(fm, evidence_ok=lambda ref: False)
    (req,) = out.requirements()
    assert req.status == "needed", req
    assert req.satisfied is False
    assert FoundationGate.evaluate(out).passed is False


def test_guard_mechanism_certified_evidence_stays_satisfied() -> None:
    """양성 오라클 — certified 근거는 satisfied 유지 → over-broad reject-everything 방지."""
    fm = _fmap(_req("root-data-contract", refs=("Tree/n_good",)))
    out = certified_foundation(fm, evidence_ok=lambda ref: True)
    (req,) = out.requirements()
    assert req.status == "satisfied"
    assert req.satisfied is True
    assert FoundationGate.evaluate(out).passed is True


def test_optional_waived_untouched() -> None:
    """비파괴 — optional/waived(인간 면제) 경로는 인증서와 무관하게 satisfied 유지(강등 안 됨)."""
    fm = _fmap(_req("opt", status="waived", refs=(), optional=True))
    out = certified_foundation(fm, evidence_ok=lambda ref: False)
    (req,) = out.requirements()
    assert req.satisfied is True


def test_partial_certification_downgrades_if_any_ref_uncertified() -> None:
    """근거 하나라도 uncertified 면 강등(AND 의미) — certified·bogus 섞기로 통과 못 산다."""
    fm = _fmap(_req("multi", refs=("Tree/n_ok", "Tree/n_bad")))
    out = certified_foundation(fm, evidence_ok=lambda ref: ref.endswith("n_ok"))
    (req,) = out.requirements()
    assert req.status == "needed"


def test_flag_off_equivalent_preserves_existing_satisfied() -> None:
    """회귀(비파괴) — evidence_ok 전부 True(플래그-off 등가)면 기존 satisfied 전부 보존."""
    fm = _fmap(_req("a", refs=("Tree/x",)), _req("b", refs=("Tree/y",)))
    out = certified_foundation(fm, evidence_ok=lambda ref: True)
    assert FoundationGate.evaluate(out).passed is True


def test_non_evidence_needed_req_untouched() -> None:
    """근거-기반 satisfied 가 아닌 requirement(status=needed)는 필터 무관(그대로 gap)."""
    fm = _fmap(_req("pending", status="needed", refs=()))
    out = certified_foundation(fm, evidence_ok=lambda ref: True)
    (req,) = out.requirements()
    assert req.status == "needed"


# ── 통합 가드: 서버 provider 배선(app._certified_foundation_provider)이 실제로 강등/passthrough 하는가 ──

def _rows() -> list:
    return [{"name": "root-data-contract", "kind": "data", "evidence_refs": ["T/n_bogus"],
             "status": "satisfied", "satisfied": True}]


def test_provider_flag_on_downgrades_uncertified(monkeypatch) -> None:
    """통합 음성 — flag-on 트리에서 provider 가 미인증 근거 requirement 를 강등(CANONICAL 승격 게이트 실패)."""
    import server.app as A
    monkeypatch.setattr(A, "_foundation_rows", lambda name: _rows())
    monkeypatch.setattr(A, "_tree_requires_cert", lambda name: True)
    monkeypatch.setattr(A, "_evidence_ok", lambda tree, ref: False)
    (req,) = A._certified_foundation_provider("T").requirements()
    assert req.satisfied is False


def test_provider_flag_off_is_byte_identical(monkeypatch) -> None:
    """통합 회귀 — flag-off(기본) 트리는 base 그대로. _evidence_ok 는 호출조차 되면 안 됨(비파괴·성능)."""
    import server.app as A

    def _must_not_call(*a, **k):
        raise AssertionError("flag off 인데 _evidence_ok 호출됨")

    monkeypatch.setattr(A, "_foundation_rows", lambda name: _rows())
    monkeypatch.setattr(A, "_tree_requires_cert", lambda name: False)
    monkeypatch.setattr(A, "_evidence_ok", _must_not_call)
    (req,) = A._certified_foundation_provider("T").requirements()
    assert req.satisfied is True


def test_evidence_ok_failsafe_on_lookup_error(monkeypatch) -> None:
    """통합 fail-safe — 인증서 조회가 터지면 _evidence_ok 는 False(=fail-closed), 절대 silent pass 아님."""
    import server.app as A

    def _boom(*a, **k):
        raise RuntimeError("kg down")

    monkeypatch.setattr(A, "_evidence_claim_service", _boom)
    assert A._evidence_ok("T", "T/n") is False
