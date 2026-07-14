"""FE5 (측정주권 2026-07-03): 서버 쓰기 인증 자세(auth posture) 관측화 — 순수·stdlib only(무 DB import).

비평 #1(신원 open-write=co-fundamental A-blocker): 무인증 DEFAULT(LAKATOS_API_TOKEN 미설정 →
_bearer_auth no-op)는 blast-radius=전 연구그래프인데 *보이지 않았다*. FE5 는 자세를 관측화한다 —
확정결정 **open-but-observable**: /version 이 공시하고 loopback open 부팅은 loud WARN.
AB1은 이 정책을 listener 경계에서 좁혀 loopback 밖 bind만 token 없이는 부팅 거부한다.

3값 사다리(강→약): token_required > irreversible_attested > open.

이 모듈은 DB/HTTP 를 import 하지 않는다(순수 — 가드 hermetic). app.py 가 env 를 읽어 여기에 signal 로 넘긴다.
"""
from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import os
import sys

POSTURES = ("token_required", "irreversible_attested", "open")
_LISTENER_FLAGS = frozenset({"--host", "--fd", "--uds"})
_LISTENER_ENV = ("UVICORN_FD", "UVICORN_UDS")


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


def is_loopback_bind(host: str) -> bool:
    """IPv4/IPv6 loopback와 ``localhost``만 로컬 open listener로 인정한다."""
    value = str(host or "").strip()
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def require_safe_bind(host: str, token: str | None) -> str:
    """loopback 밖 listener는 비어 있지 않은 API token을 요구한다.

    앱의 ``open-but-observable`` 개발 정책은 loopback에서 보존하고, 네트워크 노출 경계만
    fail-closed 한다. Bearer는 mutating 요청 인증이며 TLS/GET 기밀성을 대신하지 않는다.
    """
    value = str(host or "").strip()
    if not value:
        raise ValueError("LAKATOS_BIND_HOST가 비어 있다")
    if value.startswith("[") or value.endswith("]"):
        raise ValueError("LAKATOS_BIND_HOST는 대괄호 없는 IPv6 주소를 사용해야 한다(예: ::1)")
    if not is_loopback_bind(value) and not str(token or "").strip():
        raise ValueError(
            f"외부 bind({value})에는 LAKATOS_API_TOKEN이 필요하다; "
            "무토큰 개발은 loopback만 허용")
    return host


def validate_listener_args(args: list[str] | tuple[str, ...]) -> None:
    """uvicorn passthrough가 검증된 host를 ``--host/--fd/--uds``로 우회하지 못하게 한다."""
    for arg in args:
        if arg in _LISTENER_FLAGS or any(arg.startswith(flag + "=") for flag in _LISTENER_FLAGS):
            raise ValueError(f"listener override 인자 금지: {arg}; LAKATOS_BIND_HOST를 사용하라")


def validate_listener_env(environ: Mapping[str, str] | None = None) -> None:
    """Uvicorn auto-env가 검증된 host 대신 fd/UDS listener를 열지 못하게 한다."""
    env = os.environ if environ is None else environ
    for name in _LISTENER_ENV:
        if str(env.get(name) or "").strip():
            raise ValueError(
                f"listener override 환경변수 금지: {name}; LAKATOS_BIND_HOST를 사용하라"
            )


def _launcher_main(argv: list[str] | None = None) -> int:
    """두 shell launcher가 공유하는 stdlib-only preflight."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("LAKATOS_BIND_HOST 인자가 필요하다", file=sys.stderr)
        return 2
    try:
        require_safe_bind(argv[0], os.environ.get("LAKATOS_API_TOKEN"))
        validate_listener_args(argv[1:])
        validate_listener_env()
    except ValueError as exc:
        print(f"[lakatotree launcher] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_launcher_main())
