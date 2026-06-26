"""3D 형상 검출 나무 — 사람이 "가끔 확인"하는 정적 대시보드 생성기.

방법론 THREE_D_RESEARCH_METHOD.md §3·§5: 판결은 엔진이, 사람은 *나무를 본다*.
이 스크립트는 통합 트리(three_d_detection.UNIFIED_*)를 **의존성 0 인라인 SVG**로 구운
정적 HTML 로 만든다 — 서버·DB·graphviz·인터넷 전부 불필요, 브라우저로 열기만.

화면 = §3 점검 체크리스트(본류 진보/ frontier 수지/ 퇴행깊이/ 신뢰도) + frontier 표
+ 색칠된 나무(초록=본류 / 빨강=퇴행·기각 / 노랑=partial / 회색=살아있는 가지).

실행: python -m examples.three_d_dashboard   → three_d_detection.html
"""
from __future__ import annotations

import html
import pathlib

from lakatos.quant.metrics import tree_metrics
from examples.three_d_detection import TITLE, HARD_CORE, UNIFIED_NODES, UNIFIED_FRONTIER
from server.graph_view import tree_graph, tree_dot

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent     # lakatotree repo root
HTML_PATH = OUT_DIR / 'three_d_detection.html'
DOT_PATH = OUT_DIR / 'three_d_detection.dot'

VERDICT_FILL = {
    'CANONICAL': ('#16a34a', '#fff'), 'progressive': ('#86efac', '#063'),
    'canonical_stage': ('#bfdbfe', '#1e3a5f'), 'partial': ('#fde68a', '#713f12'),
    'degenerating': ('#fecaca', '#7f1d1d'), 'rejected': ('#fecaca', '#7f1d1d'),
}
DEFAULT_FILL = ('#e5e7eb', '#374151')


def _depths(nodes):
    by = {n['tag']: n for n in nodes}
    depth: dict[str, int] = {}

    def d(tag, seen=()):                      # parent walk, 사이클 가드
        if tag in depth:
            return depth[tag]
        n = by.get(tag)
        p = n.get('parent') if n else None
        depth[tag] = 0 if (not p or p not in by or tag in seen) else d(p, seen + (tag,)) + 1
        return depth[tag]

    for n in nodes:
        d(n['tag'])
    return depth


def _inline_svg(nodes, m) -> str:
    """순수 파이썬 계층 트리 SVG — depth→열, 형제→행. 색=verdict. 결정적(테스트 가능)."""
    depth = _depths(nodes)
    canon = set(m.get('canonical_path') or [])
    cols: dict[int, list] = {}
    for n in nodes:
        cols.setdefault(depth[n['tag']], []).append(n['tag'])

    COLW, ROWH, NW, NH, PADX, PADY = 230, 46, 188, 28, 24, 30
    pos: dict[str, tuple[int, int]] = {}
    for dpt, tags in cols.items():
        for i, tag in enumerate(tags):
            pos[tag] = (PADX + dpt * COLW, PADY + i * ROWH)
    width = PADX * 2 + (max(cols) + 1) * COLW
    height = PADY * 2 + max(len(v) for v in cols.values()) * ROWH

    by = {n['tag']: n for n in nodes}
    edges = []
    for n in nodes:
        p = n.get('parent')
        if p in pos:
            x1, y1 = pos[p]; x2, y2 = pos[n['tag']]
            hot = p in canon and n['tag'] in canon
            edges.append(f'<path d="M{x1+NW},{y1+NH//2} C{x1+NW+40},{y1+NH//2} {x2-40},{y2+NH//2} '
                         f'{x2},{y2+NH//2}" fill="none" stroke="{"#16a34a" if hot else "#cbd5e1"}" '
                         f'stroke-width="{3 if hot else 1.5}"/>')
    boxes = []
    for tag, (x, y) in pos.items():
        fill, fg = VERDICT_FILL.get(by[tag].get('verdict'), DEFAULT_FILL)
        stroke = '#16a34a' if tag in canon else '#94a3b8'
        label = tag if len(tag) <= 24 else tag[:23] + '…'
        boxes.append(
            f'<g><rect x="{x}" y="{y}" rx="6" width="{NW}" height="{NH}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{2 if tag in canon else 1}"/>'
            f'<text x="{x+9}" y="{y+18}" font-size="12" font-family="ui-monospace,monospace" '
            f'fill="{fg}">{html.escape(label)}</text></g>')
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'xmlns="http://www.w3.org/2000/svg">{"".join(edges)}{"".join(boxes)}</svg>')


def _verdict_counts(nodes):
    c: dict[str, int] = {}
    for n in nodes:
        c[n.get('verdict', '?')] = c.get(n.get('verdict', '?'), 0) + 1
    return c


def build_html(m: dict, svg: str) -> str:
    counts = _verdict_counts(UNIFIED_NODES)
    fr = m['frontier']
    prog = m.get('progress') or {}
    open_qs = [q for q in UNIFIED_FRONTIER if q.get('status') == 'OPEN']
    closed_qs = [q for q in UNIFIED_FRONTIER if q.get('status') == 'CLOSED']

    def esc(s):
        return html.escape(str(s))

    checks = [
        ('본류(CANONICAL)', esc(m['canonical']), '유일하게 공차이하 확증된 마디'),
        ('본류 진보율', f"{prog.get('improvement_pct')}% ({prog.get('first', {}).get('m')}→{prog.get('last', {}).get('m')}mm)",
         '↑면 건강, 정체면 frontier 전환'),
        ('frontier 수지', f"{m['laudan']['frontier_balance']} (closed {fr['closed']} − open {fr['open']})",
         'open만 쌓이면 측정이 안 따라오는 것'),
        ('최대 퇴행깊이', f"{m['max_degeneration_depth']}", '≥3 경보 — 폐기 합의 검토'),
        ('정본경로 신뢰도', f"{m['bayes']['canonical_credence']}", '베이즈 누적 신뢰'),
    ]
    rows_checks = '\n'.join(
        f'<tr><td>{esc(k)}</td><td class="v">{v}</td><td class="muted">{esc(note)}</td></tr>'
        for k, v, note in checks)
    legend = '  '.join(f'<span class="chip {esc(k)}">{esc(k)}: {n}</span>' for k, n in sorted(counts.items()))
    alerts = '\n'.join(f'<li>{esc(a)}</li>' for a in (m.get('alerts') or [])) or '<li>없음</li>'
    open_rows = '\n'.join(
        f'<tr><td class="q">{esc(q["name"])}</td><td>{esc(q.get("body",""))[:160]}</td></tr>' for q in open_qs)
    closed_rows = '\n'.join(
        f'<tr><td class="q ok">{esc(q["name"])}</td><td>{esc(q.get("closed_by") or ["?"])}</td></tr>' for q in closed_qs)
    hardcore = '\n'.join(f'<li>{esc(h)}</li>' for h in HARD_CORE)

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{esc(TITLE)} — 나무</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1f2937;background:#f8fafc}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:26px;border-bottom:2px solid #e5e7eb;padding-bottom:4px}}
 table{{border-collapse:collapse;width:100%;margin:8px 0;background:#fff}}
 td,th{{border:1px solid #e5e7eb;padding:6px 9px;text-align:left;vertical-align:top}}
 td.v{{font-weight:600;font-variant-numeric:tabular-nums}} .muted{{color:#6b7280}}
 .q{{font-family:ui-monospace,monospace;white-space:nowrap}} .q.ok{{color:#15803d}}
 .chip{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;margin:2px;background:#e5e7eb}}
 .chip.CANONICAL{{background:#16a34a;color:#fff}} .chip.progressive{{background:#86efac}}
 .chip.degenerating,.chip.rejected{{background:#fecaca}} .chip.partial{{background:#fde68a}}
 .chip.canonical_stage{{background:#bfdbfe}}
 .svg{{overflow:auto;border:1px solid #e5e7eb;background:#fff;padding:10px;border-radius:6px}}
 .grid{{display:flex;gap:24px;flex-wrap:wrap}} .grid>div{{flex:1;min-width:320px}} small{{color:#6b7280}}
</style></head><body>
<h1>🌳 {esc(TITLE)}</h1>
<small>BPC 줄기 + SX3i·LX3 개화 가지 — 한 그루의 나무. 판결=엔진, 당신=나무를 본다(방향만).
정적·오프라인 — <code>python -m examples.three_d_dashboard</code> 재실행으로 갱신.</small>

<div class="grid">
 <div>
  <h2>① 점검 체크리스트 (방법론 §3)</h2>
  <table>{rows_checks}</table>
  <p><b>노드 verdict</b><br>{legend}</p>
  <h2>경보</h2><ul>{alerts}</ul>
  <h2>Hard core (공유·반증불가)</h2><ul>{hardcore}</ul>
 </div>
 <div>
  <h2>② frontier — OPEN {len(open_qs)} / CLOSED {len(closed_qs)}</h2>
  <table><tr><th>열린 질문</th><th>내용</th></tr>{open_rows}</table>
  <table><tr><th>닫힌 질문</th><th>closed_by</th></tr>{closed_rows}</table>
 </div>
</div>

<h2>③ 나무 (초록=본류 / 빨강=퇴행·기각 / 노랑=partial / 회색=살아있는 가지)</h2>
<div class="svg">{svg}</div>
<p><small>DOT 원본: three_d_detection.dot (graphviz <code>dot -Tsvg</code> 로도 렌더 가능).</small></p>
</body></html>"""


def run(write: bool = True) -> dict:
    m = tree_metrics(UNIFIED_NODES, UNIFIED_FRONTIER)
    svg = _inline_svg(UNIFIED_NODES, m)
    dot = tree_dot(tree_graph({'nodes': UNIFIED_NODES, 'frontier': UNIFIED_FRONTIER}, m))
    page = build_html(m, svg)
    if write:
        HTML_PATH.write_text(page, encoding='utf-8')
        DOT_PATH.write_text(dot, encoding='utf-8')
        print(f"✅ 대시보드 생성(오프라인·의존성0):\n  HTML : {HTML_PATH}\n  DOT  : {DOT_PATH}")
        print("브라우저로 HTML 열기. 갱신 = 이 스크립트 재실행.")
    return dict(html=page, svg=svg, dot=dot, metrics=m, html_path=str(HTML_PATH))


if __name__ == '__main__':
    run()
