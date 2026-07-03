"""Longinus 바인딩 — 사람이 "언제든지 열람"하는 정적 구조화 대시보드.

코드↔KG Longinus 바인딩(docs/longinus_bindings.json)을 **의존성 0 인라인 HTML**로 구운
정적 페이지로 만든다 — 서버·DB·graphviz·인터넷 전부 불필요, 브라우저로 열기만.
three_d_dashboard.py 와 동일 철학(오프라인·재생성가능·결정적).

구조화 2축: ① layer(섹션) ② drift status(색칠 칩: ok 초록 / L4 빨강 / L6 주황 / line-stale 회색).
각 행 = sourceId | file:line | kind | status | sha[:8] | frege_sinn(의미). 헤더에 audit 요약.

기본은 매니페스트 + audit 만 읽는다(네트워크 0 = "언제든지 열람" 보장). --kg/online_kg=True 면
NEO4J_* 환경이 있을 때만 KG 미러(ReferenceSite:Longinus)·deprecated(PrismLonginusBinding) 통계
1줄을 헤더에 보강(없으면 조용히 skip).

실행: python -m lakatos.longinus_dashboard   → longinus_bindings.html
"""
from __future__ import annotations

import html
import os
import pathlib

from lakatos.longinus import audit, _load

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent      # lakatotree repo root
HTML_PATH = OUT_DIR / 'longinus_bindings.html'

_STATUS = {  # status → (배경, 글자, 라벨)
    'ok': ('#86efac', '#063', 'OK'),
    'L4': ('#fecaca', '#7f1d1d', 'L4 심볼소멸'),
    'L6': ('#fed7aa', '#7c2d12', 'L6 시그니처변경'),
    'line-stale': ('#e5e7eb', '#374151', 'line-stale(캐시)'),
}


def _by_layer(bindings: list[dict]) -> dict[str, list[dict]]:
    """layer → 바인딩 리스트 (구조화 주축). layer명, 그 안 sourceId 정렬."""
    out: dict[str, list[dict]] = {}
    for b in bindings:
        out.setdefault(b.get('layer', '(no-layer)'), []).append(b)
    return {k: sorted(v, key=lambda b: b.get('sourceId', '')) for k, v in sorted(out.items())}


def _enrich(audit_result: dict, bindings: list[dict]) -> list[dict]:
    """각 binding 에 drift status 부착. audit_result(l4_drift/l6_drift/bindings_ok)를 sourceId로 조인."""
    l4 = {d['sourceId'] for d in audit_result.get('l4_drift', [])}
    l6 = {d['sourceId'] for d in audit_result.get('l6_drift', [])}
    stale = {d['sourceId'] for d in audit_result.get('bindings_ok', []) if d.get('line_drift')}
    out = []
    for b in bindings:
        sid = b.get('sourceId')
        st = 'L4' if sid in l4 else 'L6' if sid in l6 else 'line-stale' if sid in stale else 'ok'
        out.append({**b, '_status': st})
    return out


def _status_badge(status: str) -> str:
    bg, fg, label = _STATUS.get(status, _STATUS['ok'])
    return f'<span class="chip" style="background:{bg};color:{fg}">{html.escape(label)}</span>'


def _layer_section(layer: str, rows: list[dict]) -> str:
    n = len(rows)
    okc = sum(1 for r in rows if r['_status'] == 'ok' or r['_status'] == 'line-stale')
    trs = []
    for r in rows:
        loc = f"{html.escape(r.get('file',''))}:{r.get('line_hint','')}"
        trs.append(
            f"<tr><td class=q>{html.escape(r.get('sourceId',''))}</td>"
            f"<td class=loc>{loc}</td>"
            f"<td>{html.escape(r.get('kind',''))}</td>"
            f"<td>{_status_badge(r['_status'])}</td>"
            f"<td class=sha>{html.escape(str(r.get('sha256',''))[:8])}</td>"
            f"<td class=muted>{html.escape(str(r.get('frege_sinn','')))}</td></tr>")
    return (f"<h3>{html.escape(layer)} <small>({okc}/{n})</small></h3>"
            f"<table><tr><th>sourceId</th><th>file:line</th><th>kind</th><th>status</th>"
            f"<th>sha</th><th>frege_sinn (의미)</th></tr>{''.join(trs)}</table>")


def _summary_header(audit_result: dict, n_layers: int, kg_line: str = '') -> str:
    a = audit_result
    ok = '✅' if a.get('ok') else '❌ DRIFT'
    stale = sum(1 for d in a.get('bindings_ok', []) if d.get('line_drift'))
    return (f"<div class=hdr><b>Longinus 감사 {a.get('passed')}/{a.get('total')} {ok}</b>"
            f" · L4={len(a.get('l4_drift', []))} L6={len(a.get('l6_drift', []))}"
            f" line-stale={stale} · layers={n_layers}</div>{kg_line}")


def _kg_stats() -> str:
    """online_kg: NEO4J_* 있을 때만 KG 통계 1줄. 실패/부재 시 ''(항상-열람 불변식 유지)."""
    if not os.environ.get('NEO4J_URI'):
        return ''
    try:
        from neo4j import GraphDatabase  # type: ignore
        drv = GraphDatabase.driver(os.environ['NEO4J_URI'],
                                   auth=(os.environ.get('NEO4J_USER', 'neo4j'),
                                         os.environ.get('NEO4J_PASSWORD', '')))
        with drv.session() as s:
            rs = s.run("MATCH (r:ReferenceSite:Longinus) WHERE r.repo CONTAINS 'lakatotree' "
                       "RETURN count(r) AS n").single()['n']
            dep = s.run("MATCH (lb:PrismLonginusBinding) WHERE lb.deprecated=true "
                        "RETURN count(lb) AS n").single()['n']
        drv.close()
        return (f"<div class=hdr kg>KG 미러 ReferenceSite:Longinus={rs} · "
                f"deprecated PrismLonginusBinding={dep} (data-artifact tier는 KG에서 열람)</div>")
    except Exception as e:  # noqa: BLE001 — KG 없거나 실패해도 본문은 항상 렌더
        return f"<div class=hdr muted>KG 조회 skip: {html.escape(str(e)[:60])}</div>"


def build_html(audit_result: dict, bindings: list[dict],
               extra_sections: list[tuple[str, str]] | None = None) -> str:
    enriched = _enrich(audit_result, bindings)
    layers = _by_layer(enriched)
    kg_line = _kg_stats() if extra_sections is None else ''
    body = '\n'.join(_layer_section(L, rows) for L, rows in layers.items())
    extra = '\n'.join(f"<h2>{html.escape(t)}</h2>{h}" for t, h in (extra_sections or []))
    return f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<title>Longinus 바인딩</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1f2937;background:#f8fafc}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:22px;border-bottom:2px solid #e5e7eb;padding-bottom:4px}}
 h3{{font-size:13px;margin:16px 0 4px;color:#334155}}
 table{{border-collapse:collapse;width:100%;margin:4px 0 12px;background:#fff}}
 td,th{{border:1px solid #e5e7eb;padding:4px 8px;text-align:left;vertical-align:top;font-size:12px}}
 .q{{font-family:ui-monospace,monospace;white-space:nowrap}} .loc{{font-family:ui-monospace,monospace;color:#475569}}
 .sha{{font-family:ui-monospace,monospace;color:#64748b}} .muted{{color:#6b7280}}
 .chip{{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px}}
 .hdr{{background:#fff;border:1px solid #e5e7eb;border-radius:6px;padding:8px 12px;margin:6px 0;font-variant-numeric:tabular-nums}}
 .hdr.kg{{background:#eff6ff}}
</style></head><body>
<h1>🔗 Longinus 바인딩 — 코드↔KG 관통</h1>
<small>의존성0·오프라인·재생성 — <code>python -m lakatos.longinus_dashboard</code>. 정본=docs/longinus_bindings.json (symbol-resolved, 매 커밋 drift 가드).</small>
{_summary_header(audit_result, len(layers), kg_line)}
<h2>code-symbol bindings (layer 별)</h2>
{body}
{extra}
</body></html>"""


def run(write: bool = True, online_kg: bool = False) -> dict:
    """audit() → enrich → build_html → (write 면 HTML_PATH). online_kg=False(기본)=네트워크0."""
    bindings = _load().get('bindings', [])
    a = audit()
    extra = None  # online_kg 면 _kg_stats() 가 헤더에 KG 줄 추가(build_html 내부)
    page = build_html(a, bindings, extra_sections=None if online_kg else [])
    if write:
        HTML_PATH.write_text(page, encoding='utf-8')
        print(f"✅ Longinus 대시보드(오프라인·의존성0): {HTML_PATH}")
        print(f"   audit {a['passed']}/{a['total']} {'OK' if a['ok'] else 'DRIFT'} · layers={len(_by_layer(bindings))}")
    return dict(html=page, html_path=str(HTML_PATH), audit=a, layers=len(_by_layer(bindings)))


if __name__ == '__main__':
    import sys
    run(write=True, online_kg=('--kg' in sys.argv))
