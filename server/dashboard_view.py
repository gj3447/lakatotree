"""HTML dashboard rendering for the Lakatos server."""

from __future__ import annotations

import html
from urllib.parse import quote


VERDICT_COLORS = {
    "CANONICAL": "#1a7f37",
    "canonical_stage": "#2da44e",
    "former_canonical": "#6e7781",
    "rejected": "#cf222e",
    "partial": "#bf8700",
    "equivalent": "#0969da",
    "proof": "#8250df",
    "repurposed_measurement": "#bc4c00",
}


def render_dashboard(
    *,
    trees,
    tree_data,
    compute_metrics,
    build_leaderboard,
    competitor_for_tree,
    tree_stack_lifecycle,
) -> str:
    """Render the dashboard from injected query/application functions."""
    out = [
        '<html><head><meta charset="utf-8"><title>라카토스 서버</title><style>'
        "body{font-family:monospace;margin:24px;background:#fafafa}"
        "h2{border-bottom:2px solid #333}.n{margin:2px 0;padding:2px 6px;border-radius:4px}"
        "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 8px;font-size:13px}"
        ".lay{background:#fff;border:1px solid #ddd;border-radius:5px;padding:6px 10px;margin:6px 0;font-size:13px}"
        "a.api{color:#0969da;text-decoration:none;font-size:11px;margin-left:6px}"
        "</style></head><body><h1>라카토스 서버 — 연구 프로그램 트리</h1>"
    ]
    all_trees = trees()
    names = [t["name"] for t in all_trees]
    if len(names) >= 2:
        try:
            lb = build_leaderboard([competitor_for_tree(n) for n in names])
            front = set(lb.get("pareto_front") or [])
            out.append("<h2>🏆 리더보드 (Pareto+Borda 다기준)</h2><ol>")
            for row in lb.get("rows", []):
                nm = row.get("name", "?")
                out.append(
                    f"<li><b>{html.escape(str(nm))}</b>"
                    f"{' <span style=color:#1a7f37>◆Pareto</span>' if nm in front else ''}</li>"
                )
            out.append(
                f"</ol><p><small>shift_candidate 는 인간 안건 — "
                f"<a class=api href='/api/paradigm?incumbent={html.escape(names[0])}"
                f"&rivals={html.escape(','.join(names[1:]))}'>/api/paradigm</a> "
                f"(스냅샷 축적 필요)</small></p>"
            )
        except Exception as e:
            out.append(f"<p><small>리더보드 산출 불가: {html.escape(type(e).__name__)}</small></p>")

    for t in all_trees:
        td = tree_data(t["name"])
        m = compute_metrics(td)
        nm = html.escape(t["name"])
        out.append(f"<h2>{nm}</h2><p>{html.escape(td['title'] or '')}</p>")
        out.append(f"<p><b>정본 경로</b>: {' → '.join(m['canonical_path'])}</p>")
        prog = m["progress"]
        out.append("<table><tr><th>진보율</th><th>기각률</th><th>퇴행깊이</th><th>frontier</th><th>주석</th></tr>")
        out.append(
            f"<tr><td>{(str(prog['improvement_pct'])+'%') if prog else '—'}</td>"
            f"<td>{m['rejection_ratio']}</td><td>{m['max_degeneration_depth']}</td>"
            f"<td>OPEN {m['frontier']['open']} / CLOSED {m['frontier']['closed']}</td>"
            f"<td>{m['annotation_coverage']}</td></tr></table>"
        )
        fert, bayes, cov = m["fertility"], m["bayes"], m["coverage"]
        out.append(
            f"<div class='lay'>📊 <b>베이즈 신뢰도</b> {bayes['canonical_credence']} · "
            f"<b>발전성</b> 적중 {fert.get('hits','?')}/{fert.get('registered','?')} "
            f"(nobel_grade={fert.get('nobel_grade')}) · "
            f"<b>커버리지</b> backlog {cov['backlog_count']}건"
            f"{' (전수)' if cov['exhaustive'] else ''}</div>"
        )
        sl = tree_stack_lifecycle(td)
        if sl:
            leaf, sv, ls = sl
            sc = {"abandon": "#cf222e", "retain": "#1a7f37", "undecided": "#bf8700"}.get(sv.decision, "#333")
            lc = {"extinct": "#cf222e", "diverging": "#bf8700", "harvesting": "#0969da", "active": "#1a7f37"}.get(
                ls.state, "#333"
            )
            votes = " ".join(f"{v.layer}={v.vote}" for v in sv.votes)
            out.append(
                f"<div class='lay'>⚖️ <b>3층 스택</b>(leaf {html.escape(leaf)}): "
                f"<span style='color:{sc}'>{sv.decision}</span> "
                f"<small>[{votes}{', conflict' if sv.conflict else ''}]</small> · "
                f"🔄 <b>lifecycle</b> <span style='color:{lc}'>{ls.state}</span> "
                f"<small>{html.escape(ls.reason[:80])}</small>"
                f"<a class=api href='/api/tree/{nm}/stack'>stack</a>"
                f"<a class=api href='/api/tree/{nm}/lifecycle'>lifecycle</a></div>"
            )
        if m["multiplicity"]:
            out.append(
                "<div class='lay'>🔬 <b>다중비교(gap8)</b>: "
                + " · ".join(
                    f"{html.escape(k)}: improved {v['family_size']} → BH생존 {len(v['survivors_bh'])}/"
                    f"Bonf {len(v['survivors_bonferroni'])}"
                    for k, v in m["multiplicity"].items()
                )
                + "</div>"
            )
        lf = m.get("layer_flips")
        if lf:
            out.append(
                "<div class='lay'>🔁 <b>층 flip</b>(판결 뒤집은 가지수 / "
                f"{lf['branches_evaluated']}가지 평가, 반사실적 피벗): "
                f"popper {lf['popper']['flips']} · bayes {lf['bayes']['flips']} · "
                f"laudan {lf['laudan']['flips']}</div>"
            )
        for a in m["alerts"]:
            out.append(f"<p style='color:#cf222e'>⚠ {a}</p>")
        kids = {}
        for r in td["nodes"]:
            kids.setdefault(r.get("parent"), []).append(r)

        def render(tag, depth, seen):
            if tag in seen:
                out.append(
                    f"<div class='n' style='margin-left:{depth*26}px'>"
                    f"<small>↺ {html.escape(tag)} (cycle)</small></div>"
                )
                return
            seen = seen | {tag}
            r = next(x for x in td["nodes"] if x["tag"] == tag)
            col = VERDICT_COLORS.get(r["verdict"], "#333")
            mv = f" <small>[{r['metric_name']}={r['metric_value']}]</small>" if r.get("metric_value") else ""
            et = html.escape(tag)
            links = (
                f"<a class=api href='/api/tree/{nm}/node/{et}/certificate'>cert</a>"
                f"<a class=api href='/api/tree/{nm}/node/{et}/claim-standing'>standing</a>"
                f"<a class=api href='/api/tree/{nm}/node/{et}/provenance'>prov</a>"
            )
            rp = r.get("result_path")
            if rp:
                qrp = quote(rp, safe="")
                links += (
                    f"<a class=api href='/api/lineage/{qrp}'>lineage</a>"
                    f"<a class=api href='/api/rebuild-verify/{qrp}'>rebuild</a>"
                )
            out.append(
                f"<div class='n' style='margin-left:{depth*26}px'>"
                f"<span style='color:{col}'>●</span> <b>{et}</b> "
                f"<span style='color:{col}'>{html.escape(r['verdict'])}</span>{mv}{links}"
                f"<br><small style='margin-left:14px;color:#555'>"
                f"{html.escape((r.get('comment') or '')[:120])}</small></div>"
            )
            for c in sorted(kids.get(tag, []), key=lambda x: x["tag"]):
                render(c["tag"], depth + 1, seen)

        for root in sorted(kids.get(None, []), key=lambda x: x["tag"]):
            render(root["tag"], 0, set())
        out.append("<h3>Frontier (열린 질문)</h3><ul>")
        for q in td["frontier"]:
            mark = "🟢" if q["status"] == "OPEN" else "✅"
            out.append(f"<li>{mark} <b>{html.escape(q['name'])}</b> — {html.escape((q['body'] or '')[:150])}</li>")
        out.append("</ul>")
        out.append(
            f"<p><a class=api href='/api/tree/{nm}/directions'>다음 방향(VoI)</a> "
            f"<a class=api href='/api/tree/{nm}/calibration'>보정</a> "
            f"<a class=api href='/api/tree/{nm}/metrics'>전체 지표</a></p>"
        )
    out.append("</body></html>")
    return "".join(out)

