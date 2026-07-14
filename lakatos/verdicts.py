"""라카토트리 verdict registry — *어휘*(verdict)와 *영수증 술어*(force_of)의 단일 정본(SSOT).

판결 어휘는 서버, 메트릭, 문서가 같은 집합을 바라봐야 한다. 새 어휘는
이 파일과 테스트를 바꾸는 규약 개정 사건으로만 들어온다.

★force_of (정본 prom Occam 통합 2026-06-21): "영수증인가 자기보고인가"의 *단일 3치 술어*. metrics·CANONICAL
floor·credibility 가 각자 이 술어를 재유도하다 6라운드 drift 했다(버그의 근원) → 한 곳에서 소유한다.
verdict_source(현실이 끊어 준 영수증의 출처)를 normalize_source 로 정본화한 뒤 force(COUNTS)·무영수증
(INCONCLUSIVE)·자기보고/구조(SELF_REPORT)로 가른다. *미래의 모든 게이트는 이 술어를 import 한다 — 재유도 금지*
(spine.synthesize_promotion floor / quant.metrics inconclusive / judgement_service credibility 가 그 예).
★verdict_source 는 server-set-only 다 — client 입력으로 받는 순간 모든 구멍이 동시에 재개방된다. 이 불변식은
*두 겹*으로 강제된다: (1) write-facing 스키마(NodeIn/VerdictIn/PredictionIn/TestResultIn)에 verdict_source
필드가 없고 model_config=extra='forbid' 라 client 가 보내면 422; (2) 모든 write 는 Cypher 리터럴('scripted'/
'engine'/'admin'/'pre_receipt')로만 SET 한다(by-construction). docstring 이 아니라 코드가 막는다.
# KG: span_lakatotree_verdict_registry
"""

import hashlib
import json
import math

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
    "progressive_unverified",  # metric-progressive지만 Lakatos/PnR 질적 검증은 없는 중립 판결.
                               # SCRIPTED/PROGRESS/NONPROGRESSIVE/CONFIRMED_NOVEL_PROGRESS에는 넣지 않는다.
    "degenerating",
    "withdrawn",              # ENG-CORR-2: pnr surrender → spine.dialectical_verdict 가 emit (등록 누락이었음)
    "different_programme",    # AXIS-CORR (audit qual-fidelity 2026-06-18): hard_core 위반 = 음의 휴리스틱을
                              # 떠난 것 = *다른 프로그램*(정체성 축). 진보 축의 degenerating(belt 내용-비진보)과 구분.
    "ambiguous",
})

REBUILD_VERDICTS = frozenset({
    "rebuildable",          # executor 재실행 영수증(rebuild.py) — 실제 bash 재실행 + metric 일치
    "rebuildable_static",   # #7: 정적 /rebuild-verify DAG 체크(재실행 아님) — 영수증급 'rebuildable' 과 구분
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

# 설계감사 M3: *예측 적중(prediction_hit)* 으로 셀 수 있는 *확증된* novel 진보만.
# PROGRESS_VERDICTS 는 consec/stall 카운터(비진보 리셋)·노드-쓰기 게이트용 *넓은* 진보축이라
# 미확증 progressive_conditional(engine.py:676-685 구현미완/replay미증명)·former_canonical(강등)까지
# 포함한다. 그러나 라우든 폐기규칙②(예산 소진 ∧ 적중 0)와 bandit realized_reward 는 *적중*을
# 묻는다 — 미확증을 적중으로 세면 degenerating 가지가 무기한 살고(폐기 면제) reward 가 오염된다.
# ∴ fertility.py:22 의 novel_confirmed 게이트 정신을 그대로 — confirmed 'progressive' 만 적중.
# (progressive_conditional/former_canonical 은 PROGRESS_VERDICTS 의 다른 용처에 그대로 남는다.)
CONFIRMED_NOVEL_PROGRESS = frozenset({
    "progressive",
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
# 구조/행정 source(영수증 아님, force 없음 → SELF_REPORT-tier). 통제 어휘에 *명시* 등록(유령 금지).
STRUCTURAL_SOURCES = frozenset({'admin', 'kg_bootstrap', 'conjecture'})
# 별칭: 같은 영수증의 다른 이름 → 정본 토큰. dogfood judge() 하네스는 *실 .venv pytest 영수증*에서
#   점수를 낸다(self-report 아님) → scripted; cloc 측정은 결정론 실행 측정 → reproducible.
_SOURCE_ALIASES = {
    'dogfood': 'scripted',
    'cloc-measured': 'reproducible',
    'measured': 'reproducible',   # "MEASURED: pytest 38 passed; grep=0; byte-identical" = 결정론 실행 측정(재현)
}
# server 가 쓴 prose 영수증(예: "engine judge() over ... 93/93 PASSED")은 *선두 토큰*이 정본 source 다.
#   ★verdict_source 는 server-set-only 이므로 이 prose 는 신뢰된 주석 — client 입력이면 스키마가 막는다.
_CANONICAL_HEADS = FORCEFUL_SOURCES | INCONCLUSIVE_SOURCES | STRUCTURAL_SOURCES
VALID_VERDICT_SOURCES = _CANONICAL_HEADS   # 통제 어휘(레지스트리) — 새 토큰은 여기서만

# ── 쓰기측 어휘 SSOT-of-record (아키텍처 감사 2026-06-26, finding D3) ──────────────────────────
#   force_of(읽기)는 verdict_source 어휘를 한 곳에서 해석하는데, *쓰기*(서버 CAS: 승격/강등)의 'engine'/
#   'admin'/'former_canonical' 은 VALID_VERDICT_SOURCES 와 대조 검증된 적이 없었다(SSOT 단방향, D3).
#   ★주의: 쓰기 사이트의 그 문자열들은 *일부러 리터럴로 남긴다* — H9(test_design_audit_h9) 정적 스캐너가
#   `SET ... verdict='former_canonical'` / `verdict_source='scripted'` 리터럴을 grep 해 "모든 verdict-전이
#   write 에 CAS 가드"를 by-construction 강제하기 때문이다. 상수로 파라미터화하면 그 안전망이 눈머는다.
#   대신 이 상수는 어휘의 *명명 정본*이고, assert 는 읽기 어휘(force_of 의 frozenset)와의 동기화를 import
#   시점에 못 박으며, test_verdict_write_vocabulary 가 쓰기 사이트 리터럴을 레지스트리와 대조한다(양쪽 닫음).
SOURCE_ENGINE = 'engine'   # 엔진 결정(채점/게이트/자동강등)이 SET — force_of 에서 FORCEFUL(영수증)
SOURCE_ADMIN = 'admin'     # 구조/행정 SET(승격 표식 등) — force_of 에서 STRUCTURAL(force 없음)
VERDICT_FORMER_CANONICAL = 'former_canonical'   # CANONICAL 강등 표적(ADMIN∩PROGRESS 어휘)
assert SOURCE_ENGINE in FORCEFUL_SOURCES, 'SOURCE_ENGINE 가 통제 어휘(FORCEFUL_SOURCES)와 어긋남'
assert SOURCE_ADMIN in STRUCTURAL_SOURCES, 'SOURCE_ADMIN 가 통제 어휘(STRUCTURAL_SOURCES)와 어긋남'
assert VERDICT_FORMER_CANONICAL in ADMIN_VERDICTS, 'VERDICT_FORMER_CANONICAL 가 레지스트리와 어긋남'

_SOURCE_ABSENT = object()   # verdict_source 키 자체가 없음(레거시/픽스처) — None(영수증 미도래)과 구분


def normalize_source(raw: str) -> str:
    """raw verdict_source → 정본 토큰(통제 어휘). 별칭·prose 를 한 곳에서 흡수(force_of 의 단일 정규화 chokepoint).

    규칙(순서): (1) 정확 일치 → 그대로 · (2) 별칭 맵 · (3) 선두 토큰이 정본이면 그것(prose 영수증) · (4) 미상은
    선두 토큰 그대로 반환(force_of 가 SELF_REPORT 처리 — silent COUNTS 금지).
    """
    if not raw:
        return raw
    if raw in _CANONICAL_HEADS:
        return raw
    head = raw.strip().split()[0].lower().rstrip(':()')   # 'engine judge()...' → 'engine'
    if head in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[head]
    if head in _CANONICAL_HEADS:
        return head
    return head


def force_of(verdict: str, verdict_source=_SOURCE_ABSENT) -> str:
    """단일 영수증 술어 → 'COUNTS' | 'INCONCLUSIVE' | 'SELF_REPORT'. verdict_source 생략 = 키 부재(신뢰).

    verdict_source 는 normalize_source 로 정본화한 뒤 판정한다 — 별칭/prose drift 를 한 곳에서 흡수.
    """
    if verdict_source is _SOURCE_ABSENT:
        return 'SELF_REPORT'   # 키 부재 = 레거시/픽스처(force 없으나 inconclusive 도 아님 → 기존 집계 보존)
    if not verdict_source and verdict in PROGRESS_VERDICTS:
        return 'INCONCLUSIVE'   # 키 있고 빈 source + 진보어휘 = 영수증 미도래
    src = normalize_source(verdict_source)
    if src in FORCEFUL_SOURCES:
        return 'COUNTS'
    if src in INCONCLUSIVE_SOURCES:
        return 'INCONCLUSIVE'   # 명시적 무영수증 마커(legacy/prehistory) — NULL 진보어휘와 동일 취급
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


# ── G1 (git-흡수 2026-07-02): 내용주소 verdict 영수증 — 발행층 SSOT ──────────────────────────
#   git objects(odb/source-loose.c:614-621, object-file.c:408-472: hash-before-write · link(2) EEXIST
#   first-write-wins)를 verdict 에 이식: verdict-bearing 사실을 *불변 내용주소 :VerdictReceipt* 로 발행하고
#   노드의 e.verdict 는 체인 head 의 *파생 캐시*로 둔다. receipt_sha = sha256(버전드 타입헤더 + JCS canonical
#   JSON of 고정 필드셋) — 내용 편집→다른 sha→다른 노드라 *변조가 표현 불가능*(tamper self-evident, 정책 아님).
#   prev_receipt_sha 체인 = reflog append-only(refs/files-backend.c). fold_receipt_chain 이 head 에서 prev 를
#   거슬러 무결성 확인 후 현재 verdict 재유도 — e.verdict 캐시가 fold 와 어긋나면 변조 검출(rebuild_verify 의
#   verdict 판). ★인코딩 정본은 G4 미러(_node_content_sha)와 같은 json 규율을 공유하되(sync 가 이 primitive 를
#   import), metric_value/judged_at 정규화를 *blob 안에서* 강제해 write·rederive 경로가 표류 못 하게 한다
#   (int 3 ↔ float 3.0, mixed judged_at 타입이 다른 blob 을 내는 것을 봉쇄).
_RECEIPT_ENCODING_VERSION = 'v1'
_RECEIPT_ENCODING_VERSION_V2 = 'v2'
# 고정 필드셋 — 순서 무관(sort_keys), 그러나 집합은 규약. receipt_sha 자신은 제외(자기참조).
#   seq 불포함 의도: prev_receipt_sha 가 payload 에 있어 체인 위치가 sha 에 인코딩된다(같은 내용+같은 prev=
#   같은 receipt=멱등; 다른 prev=다른 sha). 순서는 prev-링크 walk 로 복원(fold 는 seq 불요) — git reflog 동형.
# jp1 (JP 캠페인 2026-07-08): v1 13필드는 *동결*(RECEIPT_FIELDS_V1 — 기존 코퍼스 전체의 재유도 정본,
#   legacy carve-out). v2 = v1 + engine_rule_sha(판관 정체성 봉인 — '어느 엔진 규칙이 이 verdict 를
#   찍었나'가 원장 수준에서 답 가능). 버전 판별자는 봉인 *안*의 engine_rule_sha 존재(non-null)로 추론
#   (C1 receipt_kind kind-smuggle 봉쇄 동형): v2 에서 필드를 떼면 v1-추론 재유도 ≠ stored v2 sha,
#   v1 에 주입하면 v2-추론 재유도 ≠ stored v1 sha — 어느 방향 위조도 recompute 가 검출. 별도 헤더로
#   v1/v2 sha-space 도메인 분리(충돌 불가).
RECEIPT_FIELDS_V1 = (
    'tree', 'tag', 'target_id', 'verdict', 'verdict_source', 'metric_name', 'metric_value',
    'novel_confirmed', 'lakatos_status', 'judged_at', 'judge_script_sha', 'prev_receipt_sha',
    # AG3/R-SOV V1 (측정주권 2026-07-03): 측정값 출처등급을 봉인 sha 에 포함 — 없으면 서버-재유도
    #   (server_regenerated)와 client-운반(client_asserted) 노드가 같은 receipt_sha 를 든다('운반만' 구멍).
    'measurement_grade',
)
RECEIPT_FIELDS = RECEIPT_FIELDS_V1 + ('engine_rule_sha',)


def _coerce_metric_value(v):
    """metric_value 정규화(blob 결정론): None 유지, 수치는 float 로 통일(int 3 == float 3.0), 비유한(NaN/inf)은
    None(json 직렬화 불가·무의미). write·rederive 양쪽이 이 함수를 거치므로 legacy int 가 sha 를 발산시키지 못한다."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _coerce_judged_at(v):
    """judged_at 정규화: ISO str 은 그대로(정본), 그 외(legacy dict/epoch=fsck MIXED_JUDGED_AT_TYPE)는 결정론 문자열."""
    if v is None or isinstance(v, str):
        return v
    return str(v)


def canonical_receipt_blob(fields: dict, *, fieldset: tuple | None = None) -> bytes:
    """verdict 영수증의 정본 바이트열 — 버전드 타입헤더 + JCS(sorted keys·compact·UTF-8) canonical JSON.

    필드셋은 RECEIPT_FIELDS(_V1) 로 고정하고 metric_value/judged_at 는 내부 정규화. 언어이식성(git
    typed-object name==content 모델)과 재유도 안정성을 위해 Python repr/pickle·float 모호성을 배제한다.

    jp1 presence-dispatch: engine_rule_sha 가 non-null 이면 v2(14필드+v2 헤더), 아니면 v1 경로
    *바이트 동일*(legacy carve-out by-construction — 기존 코퍼스 재유도·골든 전부 무변경).
    jp3 fieldset=: 명시 계보 필드셋으로 재유도(감사 recompute 전용 — 헤더는 engine_rule_sha 포함
    여부로 결정, 기본 None=presence-dispatch 그대로).
    """
    if fieldset is None:
        v2 = fields.get('engine_rule_sha') is not None
        keys = RECEIPT_FIELDS if v2 else RECEIPT_FIELDS_V1
    else:
        v2 = 'engine_rule_sha' in fieldset
        keys = fieldset
    ver = _RECEIPT_ENCODING_VERSION_V2 if v2 else _RECEIPT_ENCODING_VERSION
    payload = {k: fields.get(k) for k in keys}
    payload['metric_value'] = _coerce_metric_value(payload.get('metric_value'))
    payload['judged_at'] = _coerce_judged_at(payload.get('judged_at'))
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    header = f'verdict-receipt\x00{ver}\n'
    return header.encode('utf-8') + body.encode('utf-8')


def receipt_content_sha(fields: dict, *, fieldset: tuple | None = None) -> str:
    """내용주소 sha256(full 64-hex). 노드는 이 값을 current_receipt_sha 포인터로 든다. (G4 미러의 [:16] 절단은
    drift 알람 휴리스틱이라 별개 — 같은 primitive 를 공유하되 receipt 무결성은 full 해시.)"""
    return hashlib.sha256(canonical_receipt_blob(fields, fieldset=fieldset)).hexdigest()


# ── jp3 (JP 캠페인): 인코딩 계보 + read-time recompute 판별 ─────────────────────────────────
#   AG3(2026-07-03)가 measurement_grade 를 추가하며 헤더를 안 올렸다 — 그 이전 mint(12필드)는 저장된
#   버전 문자열이 존재하지 않는 *미선언 드리프트*. 반면 v1→v2(jp1)는 헤더 bump+carve-out 의 선언 전이.
#   따라서 STALE 은 미선언 계보(pre-ag3)에만, 선언 정본 가족(v2/v1 presence-dispatch)은 'current'.
RECEIPT_FIELDS_PRE_AG3 = tuple(f for f in RECEIPT_FIELDS_V1 if f != 'measurement_grade')
RECEIPT_FIELDSET_LINEAGE = (('pre-ag3', RECEIPT_FIELDS_PRE_AG3),)   # 신→구 (미선언 드리프트만)


def match_receipt_encoding(receipt: dict, stored_sha: str) -> str | None:
    """동봉 영수증의 stored sha 를 content 로부터 재유도해 어느 인코딩과 일치하는지 판별.

    반환: 'current'(선언 정본 가족 — v2/v1 presence-dispatch, prediction 은 자기 도메인 단일 대조) /
    계보 label(예: 'pre-ag3' — 정직 mint 이나 미선언 구-인코딩 = 필드드리프트) / None(어느 알려진
    인코딩과도 불일치 = in-place 변조/원장우회 위조). 변조된 content 는 어떤 정직 인코딩의 sha 도
    재현할 수 없다 — 판별자 자체가 위조 통로가 되지 않는다(receipt_kind 는 봉인 안, C1 동형)."""
    if receipt.get('receipt_kind') == 'prediction':
        return 'current' if prediction_content_sha(receipt) == stored_sha else None
    if receipt_content_sha(receipt) == stored_sha:
        return 'current'
    for label, fs in RECEIPT_FIELDSET_LINEAGE:
        if receipt_content_sha(receipt, fieldset=fs) == stored_sha:
            return label
    return None


# ── C1 S3-engine (2026-07-10): PredictionReceipt — 등록-시점 spec 봉인 ──────────────────────
#   preregistered 게이트의 back-fit residual("spec 이 결과를 보고 씌워졌다") 절반을 *해시-인과 순서*로
#   방전한다: register_prediction 이 예측 spec *전체*를 내용주소 receipt 로 mint 하고 노드 포인터를
#   전진 → submit 의 verdict receipt 는 이미 prev_receipt_sha 를 payload 에 봉인하므로(RECEIPT_FIELDS)
#   verdict 가 prediction sha 를 내용으로 커밋한다. spec 을 사후 수정하면 prediction sha 가 바뀌고
#   verdict 의 sealed prev 가 dangling → ReceiptChainBroken. verdict v1 sha-space 는 무변경(별도
#   타입헤더 = git typed-object 도메인 분리; verdict-receipt 와 어떤 입력에서도 sha 충돌 불가).
#   receipt_kind 판별자는 봉인 필드셋 *안*에 있다 — 판별자 변조도 sha 가 문다(kind-smuggle 봉쇄).
#   남는 residual(정직 경계): 체인 통째 위조는 authenticity(substrate-B Ed25519)·벽시계 순서는
#   temporal witness 의 몫 — 이 커널이 주는 것은 "spec-봉인 ≺ verdict-mint 의 해시-인과 순서"다.
_PREDICTION_ENCODING_VERSION = 'v1'
PREDICTION_RECEIPT_FIELDS = (
    'receipt_kind',   # 'prediction' 고정 — 도메인 판별자(봉인 안에 포함)
    'tree', 'tag',
    'metric_name', 'direction', 'baseline_value', 'noise_band', 'scale_type',
    'novel_prediction', 'novel_metric', 'novel_direction', 'novel_threshold',
    'judge_script_sha', 'closes_question', 'credence', 'baseline_lineage',
    'registered_at', 'prev_receipt_sha',
)
_PREDICTION_NUMERIC_FIELDS = ('baseline_value', 'noise_band', 'novel_threshold', 'credence')


def canonical_prediction_blob(fields: dict) -> bytes:
    """prediction 영수증의 정본 바이트열 — verdict blob 과 같은 JCS 규율, 다른 타입헤더(도메인 분리).

    수치 필드는 _coerce_metric_value(int/float 통일·비유한→None), registered_at 는 _coerce_judged_at
    — write·rederive 양쪽이 이 함수를 거쳐 legacy 타입이 sha 를 발산시키지 못한다(verdict 커널 동형)."""
    payload = {k: fields.get(k) for k in PREDICTION_RECEIPT_FIELDS}
    for k in _PREDICTION_NUMERIC_FIELDS:
        payload[k] = _coerce_metric_value(payload.get(k))
    payload['registered_at'] = _coerce_judged_at(payload.get('registered_at'))
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    header = f'prediction-receipt\x00{_PREDICTION_ENCODING_VERSION}\n'
    return header.encode('utf-8') + body.encode('utf-8')


def prediction_content_sha(fields: dict) -> str:
    """prediction 영수증 내용주소 sha256(full 64-hex) — 노드 pred_receipt_sha/체인 genesis 가 이 값."""
    return hashlib.sha256(canonical_prediction_blob(fields)).hexdigest()


class ReceiptChainBroken(Exception):
    """head_sha 가 체인에 없거나(dangling 포인터) prev 링크가 끊김(genesis 미도달) = 변조/부패."""


def fold_receipt_chain(receipts, head_sha, *, cache_verdict=None, cache_source=None) -> dict:
    """불변 영수증 체인을 head 에서 prev 로 거슬러 무결성 확인 후 현재 {verdict, verdict_source} 재유도.

    receipts: [{receipt_sha, prev_receipt_sha, verdict, verdict_source}, ...]. head_sha: 노드의 current 포인터.
    - 체인 빔 ∧ head 없음 = legacy 노드(영수증 체제 이전) → 캐시 신뢰(force_of 의 _SOURCE_ABSENT 아날로그).
    - head 가 체인에 없음 = dangling(변조) → ReceiptChainBroken.
    - head 에서 prev 를 거슬러 genesis(prev=None)까지 도달 못 함 = 끊긴 체인 → ReceiptChainBroken.
    반환: {'verdict','verdict_source','from_receipt': bool}. from_receipt=False 는 legacy 캐시 fallback.
    """
    by_sha = {r['receipt_sha']: r for r in receipts}
    if not head_sha and not by_sha:
        return {'verdict': cache_verdict, 'verdict_source': cache_source, 'from_receipt': False}
    if head_sha not in by_sha:
        raise ReceiptChainBroken(f'current_receipt_sha={head_sha!r} 가 체인에 없음(dangling/변조)')
    head = by_sha[head_sha]
    # reflog 무결성: head→prev→…→genesis 도달성 확인(사이클/끊김 검출).
    seen, cur = set(), head_sha
    while cur is not None:
        if cur in seen:
            raise ReceiptChainBroken(f'체인 사이클 감지 @ {cur!r}')
        seen.add(cur)
        node = by_sha.get(cur)
        if node is None:
            raise ReceiptChainBroken(f'prev 링크 {cur!r} 가 체인에 없음(끊김)')
        cur = node.get('prev_receipt_sha')
    return {'verdict': head.get('verdict'), 'verdict_source': head.get('verdict_source'), 'from_receipt': True}
