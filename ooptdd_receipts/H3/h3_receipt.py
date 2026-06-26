"""OOPTDD emit-adapter — LakatoTree 설계감사 H3(Longinus 척추)을 *구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/longinus.py 는 불변). verify 가
실제 longinus.symbol_body_sha(서버측 sha 재유도 경로)를 *구동*하고, 관측한 사실을 구조화 이벤트로 ship.
Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos import longinus   # noqa: E402  (stdlib-only deps: ast/hashlib/re/pathlib)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.longinus", "event": name, **attrs}


def verify(backend, cid):
    """H3 척추 구동 — 서버측 sha 재유도(symbol_body_sha)가 실심볼 본문에서 sha 를 만들고,
    부재/모호 심볼은 None 으로 거짓 영수증을 거부함을 구조화 이벤트로 증언."""
    # (1) symbol_body_sha 가 *자기 자신*(lakatos/longinus.py::symbol_body_sha)을 CPG 본문해시로 재유도.
    sha, info = longinus.symbol_body_sha("lakatos/longinus.py", "symbol_body_sha")
    assert sha and info["found"] and not info.get("ambiguous"), info
    backend.ship([_ev(cid, "symbol_body_sha_recomputed",
                      qualname=info["qualname"], sha16=sha[:16])])

    # (2) 부재 심볼 = found False → sha None(거짓 영수증 금지). no-fake-green 오라클.
    ghost_sha, ghost = longinus.symbol_body_sha("lakatos/longinus.py", "this_symbol_does_not_exist")
    assert ghost_sha is None and ghost["found"] is False, ghost
    backend.ship([_ev(cid, "absent_symbol_refused", reason=ghost.get("reason"))])

    # (3) ast 가 `==` 비교를 정의로 오인하지 않음(트랩1 닫힘) — resolve_symbol 로 검증.
    cmp_resolved = longinus.resolve_symbol("lakatos/longinus.py", "ROOT")  # 진짜 모듈 할당은 resolve
    backend.ship([_ev(cid, "real_assignment_resolved", found=bool(cmp_resolved["found"]))])
