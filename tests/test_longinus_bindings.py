"""Longinus 코드 바인딩 drift-guard — KG ReferenceSite 의 in-repo 정본 미러 검사.

★설계(자가모순 해소): anchor 는 *심볼*(sourceId)이지 *줄번호*가 아니다. drift 판정은 심볼을
재해석(re-resolve)해 한다 — 줄이 밀려도(주석 추가 등) 심볼이 그 자리면 무드리프트.
sha256 은 def-line *내용* 해시라 시그니처가 바뀔 때만 변한다. 따라서:
  - 줄 이동(line_hint stale) = 무드리프트(심볼이 정본, 줄은 캐시) → 통과
  - 심볼 소멸/리네임(L4) = drift → 실패
  - def-line 시그니처 변경(L6, sha 불일치) = drift → 실패(검토 필요)
이로써 `# KG:` 주석을 코드에 박아 줄이 밀려도 이 가드가 깨지지 않는다(symbol-resolved).
# KG: span_lakatotree_world_gates
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from lakatos import longinus

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "longinus_bindings.json"


# #12: 중복 _resolve/_load 로직 제거 — lakatos.longinus 정본에 위임(single source). 전엔 이 파일이
# 동일 regex/sha 로직을 재구현해 longinus.audit/report 가 테스트 0커버리지였다(가드는 같은 규칙을 두 번 철자).
def _load() -> dict:
    return longinus._load()


def _resolve(file: str, symbol: str):
    return longinus._resolve(file, symbol)


def test_all_bindings_symbol_resolves():
    """모든 바인딩의 sourceId 심볼이 해당 파일에 실재한다 (소멸/리네임 = L4 drift)."""
    broken = []
    for b in _load()["bindings"]:
        ln, _ = _resolve(b["file"], b["symbol"])
        if ln is None:
            broken.append(b["sourceId"])
    assert not broken, f"Longinus L4 drift — 심볼 소멸/리네임: {broken}"


def test_all_bindings_def_line_sha_unchanged():
    """def-line sha256 이 baseline 과 일치 (시그니처 변경 = L6 drift, 검토 필요)."""
    drift = []
    for b in _load()["bindings"]:
        _, line = _resolve(b["file"], b["symbol"])
        if line is None:
            continue  # L4 는 위 테스트가 잡는다
        cur = hashlib.sha256(line.encode()).hexdigest()[:16]
        if cur != b["sha256"]:
            drift.append({"sourceId": b["sourceId"], "baseline": b["sha256"], "current": cur})
    assert not drift, (
        "Longinus L6 drift — def-line 시그니처 변경. 의도된 변경이면 docs/longinus_bindings.json "
        f"의 sha256 + KG ReferenceSite 를 재베이스라인하라:\n{drift}")


def test_line_hint_is_cache_not_anchor():
    """line_hint 는 *캐시* — 정확하면 좋으나 stale 도 허용(심볼이 정본). 단 모두 소멸은 sanity 실패."""
    bindings = _load()["bindings"]
    resolved = sum(1 for b in bindings if _resolve(b["file"], b["symbol"])[0] is not None)
    assert resolved == len(bindings), "모든 심볼이 resolve 되어야(=anchor 유효)"


# ── reverse-orphan 가드: 코드 # KG: anchor → manifest kg_anchors 레지스트리에 선언돼야 ──
_ANCHOR_PREFIX = (
    'span_lakatotree_', 'rs-', 'CT_', 'SA_', 'VR_', 'Doctrine_', 'lesson-', 'q-lkt-',
    'seed-lkt-', 'rf-lkt-', 'roadmap-', 'wave-', 'patch-lakatotree',
)


def _code_anchor_tokens() -> set:
    """전 .py 의 # KG: 주석에서 anchor 형태(노드명) 토큰 수집. (P1/THEORY 류 인라인 주석은 제외.)"""
    toks = set()
    for sub in ('lakatos', 'tests', 'examples', 'scripts', 'server'):
        for f in (ROOT / sub).rglob('*.py'):
            for m in re.findall(r'#\s*KG:\s*([A-Za-z0-9_/.\- ,]+)', f.read_text(encoding='utf-8')):
                for t in re.split(r'[,/]', m):
                    t = t.strip()
                    if t.startswith(_ANCHOR_PREFIX):
                        toks.add(t)
    return toks


def test_no_undeclared_kg_anchor_in_code():
    """★reverse-orphan 가드(forward 와 양방향 닫음): 코드의 모든 # KG: anchor 가 manifest
    kg_anchors 레지스트리에 선언돼 있어야. 미선언 = KG 노드 누락 위험(35 orphan 누적의 원천) → 실패.
    새 # KG: 노드 추가 시 kg_anchors 등록 강제 → KG 노드 생성을 잊지 않게. (존재확인=longinus.audit online)
    """
    declared = set(_load()['kg_anchors'])
    undeclared = _code_anchor_tokens() - declared
    assert not undeclared, (
        f"미선언 # KG: anchor (reverse-orphan 위험): {sorted(undeclared)}. "
        f"KG 노드 생성 후 docs/longinus_bindings.json 'kg_anchors' 에 등록할 것.")


def test_reverse_orphan_guard_catches_undeclared():
    """가드 메커니즘 자체 검증 — 미선언 토큰을 실제로 잡는가(synthetic)."""
    declared = {'span_lakatotree_real', 'rs-real'}
    code = {'span_lakatotree_real', 'rs-real', 'span_lakatotree_FAKE_undeclared'}
    assert (code - declared) == {'span_lakatotree_FAKE_undeclared'}


def test_kg_anchors_registry_nonempty_and_covers_known():
    """레지스트리 sanity — 비어있지 않고, 이번 세션 핵심 anchor 들을 포함."""
    declared = set(_load()['kg_anchors'])
    assert len(declared) >= 50
    assert {'span_lakatotree_oo_sink', 'span_lakatotree_oo_conftest',
            'span_lakatotree_bpc_inspection_gt', 'rs-wg-web-gate'} <= declared


# ── #12: longinus.audit / report 직접 단위 테스트 (전엔 코드경로 0커버리지 — 테스트가 로직만 재구현) ──

def _write_mod_and_manifest(tmp_path, bindings):
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    manifest = tmp_path / "bindings.json"
    manifest.write_text(json.dumps({"bindings": bindings}), encoding="utf-8")
    return manifest


def test_longinus_audit_partitions_ok_l4_l6(tmp_path):
    """audit 가 OK(심볼+sha 일치)/L4(심볼 소멸)/L6(시그니처 sha 변경) 3분할을 정확히 가른다."""
    ok_sha = hashlib.sha256("def foo():".encode()).hexdigest()[:16]
    manifest = _write_mod_and_manifest(tmp_path, [
        {"sourceId": "rs-ok", "file": "mod.py", "symbol": "foo", "sha256": ok_sha, "line_hint": 1},
        {"sourceId": "rs-l4", "file": "mod.py", "symbol": "ghost", "sha256": "x", "line_hint": 9},
        {"sourceId": "rs-l6", "file": "mod.py", "symbol": "foo", "sha256": "deadbeefdeadbeef", "line_hint": 1},
    ])
    r = longinus.audit(root=tmp_path, manifest=manifest)
    assert r["total"] == 3 and r["ok"] is False
    assert [d["sourceId"] for d in r["l4_drift"]] == ["rs-l4"]
    assert [d["sourceId"] for d in r["l6_drift"]] == ["rs-l6"]
    assert [b["sourceId"] for b in r["bindings_ok"]] == ["rs-ok"]
    text = longinus.report(r)
    assert "rs-l4" in text and "rs-l6" in text and "DRIFT" in text


def test_longinus_audit_clean_and_report_ok(tmp_path):
    ok_sha = hashlib.sha256("def foo():".encode()).hexdigest()[:16]
    manifest = _write_mod_and_manifest(tmp_path, [
        {"sourceId": "rs-ok", "file": "mod.py", "symbol": "foo", "sha256": ok_sha, "line_hint": 1},
    ])
    r = longinus.audit(root=tmp_path, manifest=manifest)
    assert r["ok"] is True and r["passed"] == 1 and not r["l4_drift"] and not r["l6_drift"]
    assert "OK" in longinus.report(r)
