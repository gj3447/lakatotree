"""FE5 (측정주권 2026-07-03): 서버 쓰기 인증 자세(auth posture) 관측화 — 순수·stdlib only(무 DB import).

비평 #1(신원 open-write=co-fundamental A-blocker): 무인증 DEFAULT(LAKATOS_API_TOKEN 미설정 →
_bearer_auth no-op)는 blast-radius=전 연구그래프인데 *보이지 않았다*. FE5 는 자세를 관측화한다 —
확정결정 **open-but-observable**(무토큰 부팅거부 NO): /version 이 공시하고 open 부팅은 loud WARN.

3값 사다리(강→약): token_required > irreversible_attested > open.

이 모듈은 DB/HTTP 를 import 하지 않는다(순수 — 가드 hermetic). app.py 가 env 를 읽어 여기에 signal 로 넘긴다.
"""
from __future__ import annotations

POSTURES = ("token_required", "irreversible_attested", "open")


def classify(token_set: bool, irreversible_attested: bool = False) -> str:
    """전역 쓰기 인증 자세를 signal 에서 분류.

      token_required        : LAKATOS_API_TOKEN 설정 — 모든 mutating 요청 Bearer 강제(최강).
      irreversible_attested : 전역토큰 없으나 비가역 verb 는 attestor write-cert 강제 — AG5-IDENT 착륙 시 live
                              (현재는 taxonomy 슬롯만, 미착륙=dead).
      open                  : 둘 다 없음 — mutating 요청 무인증(현 기본, blast-radius=전 연구그래프).
    """
    if token_set:
        return "token_required"
    if irreversible_attested:
        return "irreversible_attested"
    return "open"


def open_posture_warning(posture: str) -> str | None:
    """open 자세면 loud WARN 메시지, 아니면 None. 부팅은 *안 막는다*(open-but-observable) — 경고로만 공시."""
    if posture == "open":
        return ("AUTH POSTURE=open — LAKATOS_API_TOKEN 미설정: 모든 mutating 요청이 무인증이다 "
                "(blast-radius=전 연구그래프). 정본 배포는 LAKATOS_API_TOKEN 설정(token_required) 권장. "
                "open-but-observable: 부팅은 막지 않되 이 경고로 공시한다(FE5).")
    return None
