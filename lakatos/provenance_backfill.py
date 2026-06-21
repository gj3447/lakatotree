"""Occam step 5 (정본 prom 2026-06-21): 영수증 체제(prom-honesty) *이전* 승격된 NULL-source 진보/CANONICAL
노드를 *명시적 무영수증*(verdict_source='pre_receipt')으로 backfill — verdict_source 를 total 로 만들되
provenance 를 *날조하지 않는다*.

정직(하드코어: 영수증 없는 green 은 거짓말):
  - pre_receipt 는 영수증의 *부재*를 단언할 뿐이다(참 — 이 노드들엔 baseline/measured/guard/research 가 없다).
    force_of('pre_receipt')==INCONCLUSIVE 이므로 metrics 는 backfill 전에도(NULL) 후에도(마커) 이들을 진보집계에서
    제외한다 — 바뀌는 건 NULL(미기록인지 withhold 인지 모호)이 *명시*로 바뀌는 것뿐. verdict 자체는 불변(non-destructive).
  - receipt *필드가 있는* NULL-source 노드는 pre_receipt 로 찍지 않는다 → needs_reverify(replay/judge 재실행으로
    실 source 를 받아야 함). silent 처리 금지: 분류해 노출한다.
  - 이미 실 source(scripted/engine/reproducible/human)면 손대지 않는다(idempotent).
# KG: span_lakatotree_verdict_registry
"""
from lakatos.verdicts import PROGRESS_VERDICTS, force_of_row

# 영수증 존재의 흔적이 될 수 있는 노드 필드 — 하나라도 있으면 backfill 대상 아님(re-verify 로 실 source 부여)
RECEIPT_FIELDS = ('baseline', 'measured', 'guard_test', 'pred_baseline', 'content_hash', 'novel_target')

PRE_RECEIPT = 'pre_receipt'


def classify_unreceipted(rows: list) -> dict:
    """진보/CANONICAL 노드 행 리스트 → 3버킷.

    각 row 기대 키: 'tag', 'verdict', (선택) 'verdict_source', 'n_research'(연구이벤트 수), + 선택 receipt 필드.
    반환: {'pre_receipt': [tag], 'needs_reverify': [tag], 'already_sourced': [tag]}.
      - already_sourced : 이미 실 영수증 source(force_of==COUNTS) 또는 이미 pre_receipt 마커 → 건드리지 않음
      - needs_reverify  : NULL-source 인데 receipt 필드/연구이벤트 보유 → replay/judge 재실행 필요(자동 backfill 불가)
      - pre_receipt     : NULL-source + 무영수증 → 명시적 pre_receipt 로 backfill 가능
    """
    out = {'pre_receipt': [], 'needs_reverify': [], 'already_sourced': []}
    for r in rows:
        if r.get('verdict') not in PROGRESS_VERDICTS:
            continue
        force = force_of_row(r)
        # 이미 실 영수증(COUNTS) 또는 이미 명시 마커(verdict_source 가 set 됨) → 손대지 않음(idempotent)
        if force == 'COUNTS' or r.get('verdict_source'):
            out['already_sourced'].append(r.get('tag'))
            continue
        has_receipt = (any(r.get(k) is not None for k in RECEIPT_FIELDS)
                       or (r.get('n_research') or 0) > 0)
        (out['needs_reverify'] if has_receipt else out['pre_receipt']).append(r.get('tag'))
    return out
