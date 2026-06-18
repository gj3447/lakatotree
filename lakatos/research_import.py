"""외부 연구 import — 인터넷 검색으로 수집한 외부 연구 레코드를 라카토트리 연구 트리에 *게이트 통과*시켜 적재.

상계(read-only) reader(인간/agent)가 WebSearch/WebFetch 로 외부 연구(HALCON 3D 분석 등)를 수집해
구조화 레코드(axis/method/prediction/measured/rival/lakatos_role/sources)로 넘기면, 이 모듈이 *기존
게이트*를 통해 ResearchFrame(연구 트리)에 import 한다. **새 게이트를 만들지 않는다** — 이미 강제되는
``world_gates.web_gate`` + ``world_gates.scan_prompt_injection`` + ``engine.SourceCredibilityScore`` +
``engine.CredibilityPromotionGate`` 를 *조립*한다(헥사고날 조립, 본 모듈은 어댑터).

    검색(상계 reader)  →  scan_prompt_injection(untrusted content)  →  web_gate(승격자격 전수)  →
    SourceCredibilityScore(분해 trust, 인젝션 derate)  →  ResearchEvent(realm=INTERNET)  →
    ResearchFrame.record_event(트리 노드 부착).

★정직 한계(나생문): 상계는 untrusted 다. import 는 차단이 아니라 *게이트 + 분해신뢰 + 인젝션 risk 부착*
이다(고위험 content 의 최종 KG-claim 승격은 ``CredibilityPromotionGate`` 가 인간판정 없이는 막는다).
``web_gate`` 미통과 레코드는 트리에 적재되지 않고 ``rejected`` 로 보고된다(silent drop 금지).

KG identity: 본 모듈은 *새 게이트 노드가 아니라* world_gates 의 G-Web 스팬을 강제하는 import-adapter
다 → 그 스팬 anchor 를 가리킨다(전용 노드 신설 대신 기존 노드 재사용 = orphan 0).
# KG: span_lakatotree_world_gates / Doctrine_InternetFirst_RequestSecond_ReasonJoyThird_20260612
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from lakatos.engine import (
    LAKATOS_LOCATIONS,
    Possibility,
    Realm,
    ResearchEvent,
    ResearchFrame,
    SourceCredibilityScore,
)
from lakatos.world_gates import scan_prompt_injection, web_gate

# 외부 프로그램의 lakatos_role → *우리 트리* 안의 lakatos_location.
# hard_core 레코드 = (우리가 곧 HALCON 프로그램이므로) 우리 hard core. rival_programme = 우리
# protective belt 의 경쟁지형 증거(우리 보조가설이 설명/능가해야 할 대상). 인자로 덮어쓸 수 있다.
_DEFAULT_LOCATION_MAP = {
    "hard_core": "hard_core",
    "protective_belt": "protective_belt",
    "positive_heuristic": "positive_heuristic",
    "negative_heuristic": "negative_heuristic",
    "rival_programme": "protective_belt",
}

# 신뢰도 라벨(레코드 confidence) → source_class_weight 바닥값.
_CONFIDENCE_WEIGHT = {"HIGH": 0.9, "MEDIUM": 0.65, "LOW": 0.4}


def _source_type(url: str) -> str:
    """URL 도메인 → 출처 종류(분해신뢰의 source class)."""
    u = (url or "").lower()
    if "mvtec.com" in u:
        return "vendor_primary_doc"          # HALCON 거동의 1차 출처(벤더 공식 문서)
    if "arxiv.org" in u:
        return "preprint"
    if any(d in u for d in ("sciencedirect", "springer", "frontiersin", "ncbi.nlm.nih.gov",
                            "/pmc/", "openaccess.thecvf", "link.springer")):
        return "peer_reviewed"
    return "web"


def _credibility(record: dict, *, injection_risk: float) -> SourceCredibilityScore:
    """레코드 + 인젝션 risk → 분해 SourceCredibilityScore(엔진 모델, opaque 점수 금지).

    인터넷(http) 출처만 source-class/corroboration 에 센다(로컬 corroboration 은 별도 강함이나
    *인터넷* 신뢰 성분은 아니다 — overclaim 금지)."""
    sources = [s for s in (record.get("sources") or []) if s.startswith("http")]
    types = {_source_type(s) for s in sources}
    has_primary = "vendor_primary_doc" in types
    n_independent = len({s.split("/")[2] for s in sources if "/" in s})  # 고유 도메인 수
    return SourceCredibilityScore(
        source_class_weight=_CONFIDENCE_WEIGHT.get(record.get("confidence", "MEDIUM"), 0.65),
        link_authority=0.9 if (has_primary or "peer_reviewed" in types) else 0.55,
        primary_source_bonus=0.85 if has_primary else 0.3,
        provenance_score=0.7,                       # url + retrieved_at + content_hash 보존
        corroboration_score=min(1.0, n_independent / 5.0),  # 독립 출처 다수 = 교차검증
        recency_score=0.6,
        supply_chain_score=0.5,
        injection_penalty=injection_risk,           # 상계 untrusted → 실제 derate
    )


def record_content(record: dict) -> str:
    """레코드의 자연어 content(인젝션 스캔 + content_hash 대상)."""
    return "\n".join(str(record.get(k, "")) for k in
                     ("axis", "method", "how_it_works", "prediction", "measured", "rival"))


@dataclass
class ImportReport:
    """import 결과 — silent drop 없이 적재/거부/인젝션-flag 전수 보고."""

    imported: list = field(default_factory=list)          # [(tag, tier)]
    rejected: list = field(default_factory=list)          # [{tag, reasons}]  web_gate 미통과
    injection_flagged: list = field(default_factory=list)  # [{tag, signals, risk}]
    n_events: int = 0
    n_sources: int = 0

    @property
    def n_imported(self) -> int:
        return len(self.imported)


def import_research_records(
    frame: ResearchFrame,
    records: list,
    *,
    retrieved_at: str,
    actor: str = "상계_reader",
    parent: str | None = None,
    location_map: dict | None = None,
    tag_of=lambda r: r.get("_id") or r.get("axis", "")[:24],
) -> ImportReport:
    """외부 연구 레코드들을 연구 트리(frame)에 게이트 통과시켜 import.

    각 레코드마다: (1) 트리 노드(Possibility) 생성 — 없으면, (2) untrusted content 인젝션 스캔,
    (3) ``web_gate`` 전수(미통과면 적재 안 하고 rejected), (4) 분해 SourceCredibilityScore(인젝션
    derate), (5) ``ResearchEvent(realm=INTERNET)`` 으로 *실 출처 URL* 을 evidence_refs 에 담아
    트리 노드에 record_event. 반환 = ImportReport(적재/거부/flag 전수).
    """
    loc_map = {**_DEFAULT_LOCATION_MAP, **(location_map or {})}
    report = ImportReport()

    for rec in records:
        tag = tag_of(rec)
        content = record_content(rec)
        injection = scan_prompt_injection(content)
        if injection["risk"] > 0.0:
            report.injection_flagged.append(
                {"tag": tag, "signals": injection["signals"], "risk": injection["risk"]})

        location = loc_map.get(rec.get("lakatos_role"), "protective_belt")
        sources = rec.get("sources") or []
        # ★인터넷 검색 기반 import: obs.url 은 *인터넷(http) 출처*여야 한다. 로컬 코드베이스 경로
        # (consumer_b/consumer_a 파일 등)는 corroboration 으로 evidence_refs 엔 남되 G-Web url 자격은 없다.
        # 인터넷 출처가 0 이면 web_gate(url 누락)가 거부 → "no internet provenance" 로 리젝.
        http_sources = [s for s in sources if s.startswith("http")]
        obs = {
            "url": http_sources[0] if http_sources else "",
            "retrieved_at": retrieved_at,
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "source_type": _source_type(http_sources[0]) if http_sources else "",
            "source_class_weight": _CONFIDENCE_WEIGHT.get(rec.get("confidence", "MEDIUM"), 0.65),
            "link_authority": 0.9,
            "lakatos_location": location,
        }
        gate = web_gate(obs, injection=injection)
        if not gate.passed:
            report.rejected.append({"tag": tag, "reasons": list(gate.reasons)})
            continue

        # 트리 노드(가능성) 생성 — 게이트 통과한 레코드만 트리에 자리 얻음.
        if tag not in {p.name for p in frame.possibilities()}:
            frame.open_possibility(Possibility(
                name=tag, question=rec.get("axis", ""), parent=parent,
                evidence_refs=tuple(sources)))

        cred = _credibility(rec, injection_risk=injection["risk"])
        event = ResearchEvent(
            name=f"import:{tag}",
            realm=Realm.INTERNET,
            actor=actor,
            action="import_external_research",
            target=tag,
            evidence_refs=tuple(sources),     # 실 인터넷 출처 URL
            payload=(
                ("axis", rec.get("axis", "")),
                ("lakatos_role", rec.get("lakatos_role", "")),
                ("lakatos_location", location),
                ("confidence", rec.get("confidence", "")),
                ("novel", str(rec.get("novel"))),
                ("trust", f"{cred.trust:.3f}"),
                ("tier", cred.tier.value),
                ("injection_risk", str(injection["risk"])),
                ("content_hash", obs["content_hash"]),
            ),
        )
        frame.record_event(event)
        report.imported.append((tag, cred.tier.value))
        report.n_events += 1
        report.n_sources += len(sources)

    # import 한 location 이 전부 유효한 lakatos location 인지 self-check(어휘 drift 차단).
    assert all(loc_map.get(r.get("lakatos_role"), "protective_belt") in LAKATOS_LOCATIONS
               for r in records)
    return report
