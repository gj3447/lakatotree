"""engine_judge_audit — 3D 나무 전 노드의 손-verdict 를 **엔진 judge() 판결과 대조**한다.

배경: bpc_icp/sx3i_icp/lx3_icp/datum dogfood 프로그램은 노드 verdict 를 `_n(verdict=...)` 로
*손-설정*한다(metric_value `m` + pred_baseline `base` 는 인라인으로 들고 있으나 judge() 로 굴리진
않았다). 이 모듈은 측정-backed 노드(m,base 존재) 전부를 엔진 판결커널 `judge()` 에 굴려 **엔진이
생성한 verdict** 와 손-설정을 대조한다 — 손-verdict 가 엔진과 갈리는 지점(과장/저평가)을 노출.

판결 범위(Stevens/Lakatos): judge() 는 {progressive, partial, equivalent, rejected} 만 생성한다.
  - progressive = improved(noise 밖) ∧ novel(독립 초과경험)
  - partial     = improved ∧ novel 미공급/미확정
  - equivalent  = |measured−baseline| ≤ noise_band (유의차 없음)
  - rejected    = 개선 아님 ∧ noise 밖
CANONICAL/degenerating/canonical_stage 는 *가지상태*(Laudan)이지 per-node judge 결과가 아님 → N/A.
novel_target 은 구조적으로 공급돼야 progressive 가 나옴(F-CON-3) — 부울 flag(nr/nc)만으론 partial.
∴ 손-progressive 가 engine-partial 로 떨어지는 건 '과장'이 아니라 'novel 미배선'의 정직한 노출.

실행: python -m examples.engine_judge_audit
"""
from __future__ import annotations

from lakatos.verdict.judge import Prediction, judge, NovelTarget

REGISTRY = [   # (module, node-list attr)
    ('examples.bpc_icp_programme', 'NODES'),
    ('examples.sx3i_icp_programme', 'BLOOM_NODES'),
    ('examples.lx3_icp_programme', 'BLOOM_NODES'),
    ('examples.datum_programme', 'BLOOM_NODES'),
]
BRANCH_STATE = {'CANONICAL', 'canonical_stage', 'degenerating'}   # judge 범위 밖

# ── novel 구조 배선 (progressive 의 마지막 조각: 부울 flag 아닌 *독립 측정* 요구) ──
# tag → dict(metric, direction, threshold, novel_measured, novel_sha, measured_sha).
# ★정직성: 비어있다 = 어느 3D 노드도 아직 *독립 novel 측정*을 judge() 에 구조 공급하지 않았다.
#   → progressive 손-설정 노드는 엔진에서 partial 상한(novel 미배선). 가짜 novel 날조 금지(타세션 노드).
#   owner 가 distinct-sha 독립 측정을 여기 등록해야 엔진이 progressive 를 *생성*한다.
NOVEL_SPECS: dict = {}


def judge_node(node: dict) -> dict:
    """노드 1개 → 엔진 verdict (m/base 없으면 ABSTAIN). 손-설정과 분류 대조."""
    m, b = node.get('metric_value'), node.get('pred_baseline')
    tag, hand = node['tag'], node['verdict']
    if m is None or b is None:
        cls = 'N/A(가지상태)' if hand in BRANCH_STATE else 'ABSTAIN(m/base 부재)'
        return dict(tag=tag, hand=hand, engine=None, delta=None, cls=cls)
    pred = Prediction(metric_name=tag, direction=node.get('pred_direction', 'lower'),
                      baseline_value=float(b), noise_band=float(node.get('pred_noise_band') or 0.0))
    ns = NOVEL_SPECS.get(tag)
    if ns:   # 구조 공급된 독립 novel → judge() 가 progressive 도달 가능(독립성 게이트 통과시)
        nt = NovelTarget(metric_name=ns['metric'], direction=ns['direction'], threshold=float(ns['threshold']))
        v = judge(pred, float(m), novel_target=nt, novel_measured=float(ns['novel_measured']),
                  measured_sha=ns.get('measured_sha', ''), novel_sha=ns.get('novel_sha', ''))
    else:    # novel 미배선 → progressive 도달 불가(partial 상한, 정직)
        v = judge(pred, float(m))
    eng = v.verdict
    if hand in BRANCH_STATE:
        cls = f'N/A(가지상태, engine={eng})'
    elif hand == eng:
        cls = 'AGREE'
    elif hand == 'progressive' and eng == 'partial':
        cls = 'PARTIAL(novel 미배선→progressive 미확정)'
    else:
        cls = 'MISMATCH'
    return dict(tag=tag, hand=hand, engine=eng, delta=round(v.delta, 4),
                improved=v.improved, cls=cls, reason=v.reason)


def audit(registry=REGISTRY) -> dict:
    rows, mism = [], []
    for mod, attr in registry:
        nodes = getattr(__import__(mod, fromlist=[attr]), attr)
        for n in nodes:
            r = judge_node(n); r['programme'] = mod.split('.')[-1]
            if r['engine'] is None and 'ABSTAIN' in r['cls']:
                continue                  # 구조 노드(문제/판결불가) — 표에서 생략
            rows.append(r)
            if r['cls'] == 'MISMATCH':
                mism.append(r)
    summary = {}
    for r in rows:
        key = r['cls'].split('(')[0]
        summary[key] = summary.get(key, 0) + 1
    return dict(rows=rows, mismatches=mism, summary=summary, n=len(rows))


def novel_mechanism_selftest() -> dict:
    """progressive 의 novel 게이트가 *구조적으로* 작동함을 증명 (가짜 novel 차단).
    A 다른-metric novel→progressive · B 같은-metric distinct-sha→progressive ·
    C 같은-metric same-sha→demote(partial) · D novel 없음→partial."""
    P = Prediction(metric_name='X', direction='lower', baseline_value=10.0, noise_band=0.5)
    a = judge(P, 8.0, novel_target=NovelTarget('Y', 'higher', 5.0), novel_measured=6.0,
              measured_sha='a', novel_sha='b')                      # 다른 metric = 독립
    b = judge(P, 8.0, novel_target=NovelTarget('X', 'lower', 9.0), novel_measured=8.5,
              measured_sha='a', novel_sha='b')                      # 같은 metric, distinct sha = 독립
    c = judge(P, 8.0, novel_target=NovelTarget('X', 'lower', 9.0), novel_measured=8.5,
              measured_sha='a', novel_sha='a')                      # 같은 metric, same sha = 비독립
    d = judge(P, 8.0)                                               # novel 없음
    checks = {
        'A_diff_metric_novel→progressive': a.verdict == 'progressive',
        'B_same_metric_distinct_sha→progressive': b.verdict == 'progressive',
        'C_same_metric_same_sha→demote_partial': c.verdict == 'partial' and not c.novel,
        'D_no_novel→partial': d.verdict == 'partial',
    }
    return dict(passed=all(checks.values()), checks=checks)


def main():
    st = novel_mechanism_selftest()
    a = audit()
    print('═' * 92)
    print('  engine_judge_audit — 3D 나무 손-verdict vs 엔진 judge() 판결 (손-설정 검증)')
    print('═' * 92)
    prog = None
    for r in a['rows']:
        if r['programme'] != prog:
            prog = r['programme']; print(f'\n### {prog}')
        eng = r['engine'] or '—'
        mark = '🔴' if r['cls'] == 'MISMATCH' else ('  ' if 'AGREE' in r['cls'] or 'N/A' in r['cls'] else '· ')
        print(f'  {mark}{r["tag"]:30} hand={r["hand"]:13} engine={eng:11} Δ={str(r.get("delta")):>9}  {r["cls"]}')
    print('\n' + '─' * 92)
    print(f'  요약: {a["summary"]}   (총 {a["n"]} 측정-backed 노드)')
    if a['mismatches']:
        print(f'  🔴 MISMATCH {len(a["mismatches"])} — 손-verdict 가 엔진과 갈림(검토 대상):')
        for r in a['mismatches']:
            print(f'     · {r["programme"]}/{r["tag"]}: hand={r["hand"]} → engine={r["engine"]} (Δ={r["delta"]})')
    print('─' * 92)
    print(f'  novel 게이트 self-test(progressive 의 마지막 조각): passed={st["passed"]}')
    for k, ok in st['checks'].items():
        print(f'     {"✅" if ok else "❌"} {k}')
    n_prog_hand = sum(1 for r in a['rows'] if r['hand'] == 'progressive')
    n_prog_eng = sum(1 for r in a['rows'] if r['engine'] == 'progressive')
    print(f'  → novel 구조배선 등록(NOVEL_SPECS): {len(NOVEL_SPECS)}개. 엔진 progressive {n_prog_eng}/{n_prog_hand}(손).')
    print(f'    ∴ 손-progressive {n_prog_hand}건은 *독립 novel 미배선*(부울 flag만)→엔진 partial 상한. '
          f'owner 가 distinct-sha 독립측정 등록해야 엔진이 progressive 생성(가짜 novel 차단).')
    print('═' * 92)
    return dict(audit=a, novel_selftest=st)


if __name__ == '__main__':
    main()
