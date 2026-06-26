"""쓰기측 verdict_source 어휘 검증 (아키텍처 감사 2026-06-26, finding D3 — SSOT 양방향 닫기).

force_of(읽기)는 verdict_source 를 VALID_VERDICT_SOURCES 통제어휘로 해석하는데, *쓰기*(서버 CAS:
승격/강등/채점)가 SET 하는 verdict_source 리터럴은 그 레지스트리와 대조 검증된 적이 없었다(SSOT 단방향).
이 가드가 양방향을 닫는다 — 서버가 SET 하는 모든 verdict_source 리터럴은 VALID_VERDICT_SOURCES 안에
있어야 하고(유령 토큰/오타 차단), 명명 정본 SOURCE_ENGINE/SOURCE_ADMIN 는 실제 쓰기에 살아있어야 한다.

★리터럴은 *일부러* 유지한다(상수 파라미터화 금지): H9(test_design_audit_h9) 정적 스캐너가 verdict-전이
SET 리터럴을 grep 해 "모든 전이 write 에 CAS 가드"를 by-construction 강제한다 → 파라미터화하면 그
안전망이 눈먼다. 그래서 D3 의 SSOT 는 '값 통일'이 아니라 '값 *검증*'으로 닫는다(H9 와 양립).
"""
import re
from pathlib import Path

from lakatos.verdicts import SOURCE_ADMIN, SOURCE_ENGINE, VALID_VERDICT_SOURCES

_ROOT = Path(__file__).resolve().parent.parent
_LIT = re.compile(r"verdict_source\s*=\s*'([a-z_]+)'")   # Cypher SET 리터럴(WHERE 의 <> / IS NULL 은 제외)


def _server_write_sources() -> set[str]:
    found: set[str] = set()
    for py in (_ROOT / "server").rglob("*.py"):
        found |= set(_LIT.findall(py.read_text(encoding="utf-8")))
    return found


def test_server_write_verdict_sources_are_in_registry():
    """서버가 SET 하는 모든 verdict_source 리터럴 ⊆ VALID_VERDICT_SOURCES (유령 토큰/오타 차단)."""
    found = _server_write_sources()
    assert len(found) >= 2, f"verdict_source 쓰기 리터럴 스캔 실패({sorted(found)}) — 가드가 vacuous"
    unknown = found - VALID_VERDICT_SOURCES
    assert not unknown, (
        f"통제어휘 밖 verdict_source 쓰기 리터럴(유령 토큰/오타): {sorted(unknown)}. "
        f"force_of 는 이를 보수적으로 SELF_REPORT 강등하지만(fail-safe), 쓰기 의도와 어긋난다 — "
        f"VALID_VERDICT_SOURCES 에 등록하거나 오타 수정.")


def test_named_write_source_constants_are_live():
    """SOURCE_ENGINE/SOURCE_ADMIN 명명 정본이 실제 서버 쓰기에 살아있는지(죽은 상수 금지, 정본↔현실 결속)."""
    found = _server_write_sources()
    assert SOURCE_ENGINE in found, f"SOURCE_ENGINE 가 서버 쓰기에서 사라짐: {sorted(found)}"
    assert SOURCE_ADMIN in found, f"SOURCE_ADMIN 가 서버 쓰기에서 사라짐: {sorted(found)}"
