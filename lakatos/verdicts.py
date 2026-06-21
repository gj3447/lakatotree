"""라카토트리 verdict registry.

판결 어휘는 서버, 메트릭, 문서가 같은 집합을 바라봐야 한다. 새 어휘는
이 파일과 테스트를 바꾸는 규약 개정 사건으로만 들어온다.
# KG: span_lakatotree_verdict_registry
"""

SCRIPTED_VERDICTS = frozenset({
    "progressive",
    "partial",
    "equivalent",
    "rejected",
})

ADMIN_VERDICTS = frozenset({
    "CANONICAL",
    "canonical_stage",
    "former_canonical",
    "proof",
    "superseded",
    "CANONICAL_KNOWLEDGE",
    "repurposed_measurement",
})

KNOWLEDGE_VERDICTS = frozenset({
    "CANONICAL_KNOWLEDGE",
})

# 나생문 F-ARCH-2: 엔진 게이트 판결(engine.LakatosVerdict) + 재빌드 판결을 단일 레지스트리에 통합
ENGINE_VERDICTS = frozenset({
    "progressive",            # judge 와 공유
    "progressive_conditional",
    "degenerating",
    "withdrawn",              # ENG-CORR-2: pnr surrender → spine.dialectical_verdict 가 emit (등록 누락이었음)
    "different_programme",    # AXIS-CORR (audit qual-fidelity 2026-06-18): hard_core 위반 = 음의 휴리스틱을
                              # 떠난 것 = *다른 프로그램*(정체성 축). 진보 축의 degenerating(belt 내용-비진보)과 구분.
    "ambiguous",
})

REBUILD_VERDICTS = frozenset({
    "rebuildable",
    "progressive_conditional",
    "metric_mismatch",
    "env_drift",
    "step_failed",
})

VERDICT_REGISTRY = SCRIPTED_VERDICTS | ADMIN_VERDICTS | ENGINE_VERDICTS | REBUILD_VERDICTS

# 의미 분류(진보/비진보) — source-based 그룹(SCRIPTED/ADMIN/…)을 가로지르는 직교 축.
# metrics 가 자체 튜플로 하드코딩하던 것을 단일 정본으로 흡수(SSOT). 새 어휘는 여기서만.
# THR-1: dialectical 판결(degenerating/withdrawn)도 비진보로 셈 — 전엔 비진보 밖이라
# consec/stall 카운터를 리셋(진보로 오인)했다. progressive_conditional 은 (조건부)진보 측.
PROGRESS_VERDICTS = frozenset({
    "progressive",
    "progressive_conditional",
    "CANONICAL",
    "former_canonical",
})

NONPROGRESSIVE_VERDICTS = frozenset({
    "rejected",
    "partial",
    "equivalent",
    "degenerating",
    "withdrawn",
    "different_programme",   # 현 프로그램의 진보 아님(다른 프로그램으로 분기) — withdrawn 과 동류(off-axis)
})


def is_progress_verdict(verdict: str) -> bool:
    return verdict in PROGRESS_VERDICTS


def is_nonprogressive_verdict(verdict: str) -> bool:
    return verdict in NONPROGRESSIVE_VERDICTS


def is_admin_verdict(verdict: str) -> bool:
    return verdict in ADMIN_VERDICTS or verdict.startswith("repurposed_")


def is_scripted_verdict(verdict: str) -> bool:
    return verdict in SCRIPTED_VERDICTS


def is_engine_verdict(verdict: str) -> bool:
    return verdict in ENGINE_VERDICTS or verdict in REBUILD_VERDICTS


# ── 정본 prom (Occam 통합 2026-06-21): "영수증 vs 자기보고"의 *단일 3치 술어* ──────────────────
#   6라운드 동안 metrics·CANONICAL floor·credibility 가 이 술어를 각자 재유도하다 drift 했다(버그의 근원).
#   레지스트리가 어휘를 소유하듯 이 술어도 한 곳에서 소유한다. verdict_source 가 *현실이 다시 끊을 수 있는
#   영수증*({scripted,engine,reproducible,human})이면 COUNTS; 진보어휘인데 영수증 미도래(키 있고 빈 source)면
#   INCONCLUSIVE; 그 외(admin/구조 또는 비진보)는 SELF_REPORT. 키 *부재*(레거시/테스트 픽스처)는 신뢰(집계 보존).
#   ★verdict_source 는 server-set-only — client 입력으로 받으면 모든 구멍이 동시에 재개방된다(스키마 가드).
FORCEFUL_SOURCES = frozenset({'scripted', 'engine', 'reproducible', 'human'})
# 명시적 *무영수증* 마커(Occam step 5): 레거시 노드가 영수증 체제(prom-honesty) *이전*에 승격됐고
#   검증 가능한 영수증이 없음을 *명시*한다 — NULL(미기록인지 의도적 withhold 인지 모호)보다 정직하다.
#   force 가 아니므로 COUNTS 되지 않고, 진보집계에서 빠지도록 INCONCLUSIVE 로 매핑(NULL 진보어휘와 동일 취급).
#   ★fabrication 아님: 영수증의 *부재*를 단언할 뿐(참), 영수증을 날조하지 않는다.
INCONCLUSIVE_SOURCES = frozenset({'pre_receipt', 'prehistory'})
_SOURCE_ABSENT = object()   # verdict_source 키 자체가 없음(레거시/픽스처) — None(영수증 미도래)과 구분


def force_of(verdict: str, verdict_source=_SOURCE_ABSENT) -> str:
    """단일 영수증 술어 → 'COUNTS' | 'INCONCLUSIVE' | 'SELF_REPORT'. verdict_source 생략 = 키 부재(신뢰)."""
    if verdict_source in FORCEFUL_SOURCES:
        return 'COUNTS'
    if verdict_source in INCONCLUSIVE_SOURCES:
        return 'INCONCLUSIVE'   # 명시적 무영수증 마커(legacy/prehistory) — NULL 진보어휘와 동일 취급
    if verdict_source is _SOURCE_ABSENT:
        return 'SELF_REPORT'   # 키 부재 = 레거시/픽스처(force 없으나 inconclusive 도 아님 → 기존 집계 보존)
    if not verdict_source and verdict in PROGRESS_VERDICTS:
        return 'INCONCLUSIVE'   # 키 있고 빈 source + 진보어휘 = 영수증 미도래
    return 'SELF_REPORT'


def force_of_row(row: dict) -> str:
    """노드 dict → force_of. verdict_source 키 부재(레거시)와 None(영수증 미도래)을 구분해 넘긴다."""
    return force_of(row.get('verdict'),
                    row['verdict_source'] if 'verdict_source' in row else _SOURCE_ABSENT)


def is_self_report_blocked_verdict(verdict: str) -> bool:
    """노드 수동 작성으로 self-report 금지 어휘 — 채점(scripted/engine) ∪ 진보집계(PROGRESS_VERDICTS,
    CANONICAL/former_canonical 포함). 적대 재검증(2026-06-21): scripted/engine 만 막으면 정본급 진보어휘
    (CANONICAL·former_canonical)가 노드 경로로 새서 metrics 진보를 부풀렸다(set_verdict 의 promotion gate
    — eigentrust+논증+재현 — 와 engine 강등을 우회). 이 어휘는 judge/engine 채점 또는 set_verdict 만 부여한다.
    구조/행정 어휘(proof·canonical_stage·superseded·CANONICAL_KNOWLEDGE·repurposed_*)는 노드 작성 허용."""
    return (is_scripted_verdict(verdict) or is_engine_verdict(verdict)
            or verdict in PROGRESS_VERDICTS)


def is_registered_verdict(verdict: str) -> bool:
    # 나생문 F-ARCH-2: 엔진/재빌드 판결도 등록 어휘 (분기 차단)
    return verdict in VERDICT_REGISTRY
