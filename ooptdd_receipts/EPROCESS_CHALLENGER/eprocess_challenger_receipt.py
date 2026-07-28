"""e-process challenger 영수증 — S9 흡수층의 발화·유효성·병행성을 실코드로 증언.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 quant/{eprocess,metrics,
multiplicity}.py 불변). 재구현 금지 — tests/test_eprocess.py 의 픽스처/호출을 그대로 차용한다.

음성 오라클(no-fake-green): ① 건강 스트림(전부 적중)에서 abandon 이 발화하면 assert 가 죽는다 —
과잉 경보로 K=3 을 밀어내는 challenger 는 무효. ② E[e|H0]<=1 이 p0 경계 그리드에서 하나라도
깨지면 죽는다 — 구 고정-BF 누적층이 위반하던 바로 그 부등식(finding_b2a8aa7064fc11aa)이라,
새 층이 같은 결함을 재발시키면 이 영수증이 틀린다.
# KG: plan-lktadv-p4-eprocess-s9-20260728 / seed-lktadv-eprocess-absorption-s9-20260728
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.grounding import GROUNDED  # noqa: E402
from lakatos.quant import eprocess as ep  # noqa: E402
from lakatos.quant.metrics import tree_metrics  # noqa: E402
from lakatos.quant.multiplicity import false_progressive_screen  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.quant.eprocess_challenger", "event": name, **attrs}


def _nodes(n, confirmed):
    return [dict(tag=f'm{i:02d}', verdict='partial', verdict_source='scripted',
                 current_receipt_sha='r' * 64, novel_registered=True,
                 novel_confirmed=confirmed, judged_at=f'2026-07-{i + 1:02d}')
            for i in range(n)]


def verify(backend, cid):
    """miss 스트림 발화 + 구조강등 제외 + 건강 침묵 + 유효성 그리드 + e-BH 병행."""
    # (1) 지속 miss 스트림 → 실경로(tree_metrics) 발화 + alert 병행.
    bad = _nodes(14, confirmed=False)
    m = tree_metrics(bad, [])
    ep_out = m['eprocess']
    assert ep_out['abandon'] is True and ep_out['fired_at'] is not None, \
        f"miss 14 스트림 무발화(배선 죽음): {ep_out}"
    assert any('e-process' in a for a in m['alerts']), m['alerts']
    backend.ship([_ev(cid, "eprocess_abandon_fires_on_miss_stream",
                      e_max=ep_out['e_max'], threshold=ep_out['threshold'],
                      fired_at=ep_out['fired_at'], stream_n=ep_out['stream_n'])])

    # (2) 구조적 강등은 반증 스트림에서 제외 + 공시 (운영 강등 != 과학적 반증).
    mixed = bad + [dict(tag='s1', verdict='partial', verdict_source='scripted',
                        current_receipt_sha='r' * 64, novel_registered=True,
                        novel_confirmed=False, lakatos_status='reproducibility_refuted',
                        judged_at='2026-07-20')]
    m2 = tree_metrics(mixed, [])
    assert m2['eprocess']['excluded_structural'] == ['s1'], m2['eprocess']
    assert m2['eprocess']['stream_n'] == 14, "제외분이 스트림에 새면 오독"
    backend.ship([_ev(cid, "structural_demote_excluded_from_stream",
                      excluded=m2['eprocess']['excluded_structural'])])

    # (3) 이중가드: 건강 스트림 침묵 + E[e|H0]<=1 전 그리드 (유효성의 심장).
    good = tree_metrics(_nodes(14, confirmed=True), [])
    assert good['eprocess']['abandon'] is False, f"건강 스트림 오발화: {good['eprocess']}"
    assert not any('e-process' in a for a in good['alerts'])
    p0g = GROUNDED['eprocess_p0']['value']
    for p0 in (0.2, p0g, 0.5, 0.7):
        lam = ep.default_lambda(p0)
        for pct in range(int(p0 * 100), 101):
            ph = pct / 100
            exp_e = ph * (1 + lam * (p0 - 1)) + (1 - ph) * (1 + lam * p0)
            assert exp_e <= 1.0 + 1e-12, f"유효성 위반 E[e]={exp_e} (p0={p0}, p_hit={ph})"
    backend.ship([_ev(cid, "healthy_stream_silent_and_validity_holds",
                      healthy_e_max=good['eprocess']['e_max'], validity_grid="E[e|H0]<=1 PASS")])

    # (4) e-BH 병행 출력 — 임의 의존 하 FDR, 임계 규칙 준수.
    rep = false_progressive_screen(
        [dict(tag='strong', delta=-9.0, noise_band=1.0, direction='lower'),
         dict(tag='weak', delta=-1.0, noise_band=1.0, direction='lower')])
    assert 'strong' in rep.survivors_ebh and 'weak' not in rep.survivors_ebh, rep
    assert set(rep.survivors_ebh) <= set(rep.survivors_bh), "e-BH 가 BH 초과 reject(규칙 위반)"
    backend.ship([_ev(cid, "ebh_survivors_emitted",
                      survivors_ebh=list(rep.survivors_ebh), survivors_bh=list(rep.survivors_bh))])
