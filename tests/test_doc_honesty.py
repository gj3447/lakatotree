"""PROM-D (prom-honesty): 문서 주장 ↔ 코드 1:1 — '영수증 없는 표어' 제거 드리프트 가드.

감사 발견(과장 3건):
  · bayes docstring '[0,1)' 인데 실제 1.0 으로 포화(distinct 강확증 다수).
  · README Rung.derived 가 "the whole receipt-not-self-report rule" 을 고정한다 과장 —
    실제 persisted verdict 는 dialectical_verdict(judge…) 가 감싸/덮어쓸 수 있고 novel 출처는
    Lean 증명 밖(Python 경계).
  · 매니페스토가 Wolfram 을 hard core 이론근거로 격상 — grounding.SOURCES 에 없고 Python 0줄.
이 가드는 정정이 *코드/문서 실재*와 일치하는지 매 커밋 검증한다(README 가 스스로 설파하는
"receipts, not claims" 를 README·매니페스토·docstring 에 적용).
# KG: span_lakatotree_grounding / LakatosTree_PromHonesty_20260620
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_doc_claims_match_code():
    """3건의 과장 정정이 유지되는지 — 문서 텍스트 실재로 확인."""
    bayes = (ROOT / "lakatos/quant/bayes.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    manifesto = (ROOT / "TOUCH_THE_SKY.md").read_text(encoding="utf-8")
    # 1. bayes 경계: '[0,1)' 과장 제거 + '(0,1]' 정정
    assert "반환 [0,1)" not in bayes, "bayes docstring still claims 반환 [0,1) (실제 1.0 포화)"
    assert "반환 (0,1]" in bayes
    # 2. README Rung.derived: 런타임 전체 고정 과장 완화(dialectical_verdict 오버라이드 명시)
    assert "dialectical_verdict" in readme, "README must disclose the dialectical_verdict runtime wrapper"
    assert 'the whole "receipt, not self-report" rule' not in readme, "README still overclaims Rung.derived"
    # 3. 매니페스토 Wolfram: 동기/이미지로 명시(이론근거 아님)
    assert "동기·이미지" in manifesto, "manifesto must flag Wolfram as motivation/imagery, not theory basis"


def test_wolfram_absent_from_grounding_sources():
    """매니페스토 주장('Wolfram 은 grounding.SOURCES 에 없다')을 코드로 검증 — claim↔code 1:1."""
    from lakatos.grounding import SOURCES
    assert not any("wolfram" in str(k).lower() for k in SOURCES), \
        "manifesto says Wolfram isn't in grounding.SOURCES — but a key contains it"


def _max_strength_credence(n):
    from lakatos.quant.bayes import branch_credence
    return branch_credence([{"verdict": "progressive", "delta": -1e6, "noise_band": 1e-9, "target": f"t{i}"}
                            for i in range(n)])


def test_bayes_saturation_claim_is_true():
    """bayes 가 실제로 정확히 1.0 에 도달(=상한 1.0 포함, (0,1] 가 정직). [0,1) 였다면 거짓.
    robust 마진(40, 임계 ~21 훨씬 위)으로 — n=20~25 경계는 1 ulp 차라 platform-fragile."""
    assert _max_strength_credence(40) == 1.0, "docstring (0,1] 는 1.0 도달을 전제"


def test_realistic_tree_depth_does_not_saturate():
    """docstring 의 'hedge' 를 *테스트*로 승격: 실 트리 정본경로 깊이(≤15, 그나마 전부 최대강도도 아님)
    로는 1.0 미도달 = 여전히 (0,1) 안. 포화는 ~21+ distinct 최대강도에서만(비현실적 깊이).
    robust 마진만 단언(15 미포화 ~1e-12, 40 포화) — n=20 은 1 ulp 차라 platform-fragile 이라 제외."""
    assert _max_strength_credence(15) < 1.0, "현실적 깊이에서 포화하면 dedup/경계 주장이 흔들린다"
    assert _max_strength_credence(40) == 1.0   # 충분히 깊으면(비현실적) 포화 — 상한 1.0 포함
