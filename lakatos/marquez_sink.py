"""Marquez(OpenLineage 레퍼런스 서버) 전송 — 완성본 계보를 생태계 표준으로 ship.

직렬화(OpenLineage event 생성)는 adapters 가 한다. 이 sink 는 *전송*만 담당하고
env-gate 한다: MARQUEZ_URL 없으면 no-op(어댑터 직렬화는 여전히 가능 — 골방 아님,
인터넷/생태계로 흘려보내되 자격증명 없으면 조용히 멈춤). 토큰은 env(MARQUEZ_TOKEN)
로만 — oo_sink 와 동형(코드/문서 baked default 금지).
# KG: span_lakatotree_marquez_sink / q-lkt-dead-adapters
"""
import os

from .adapters import send_openlineage_events_to_marquez


def enabled() -> bool:
    """전송 활성 여부 — MARQUEZ_URL env 있을 때만."""
    return bool(os.getenv("MARQUEZ_URL"))


def ship(events: list, *, opener=None, timeout: float = 10.0) -> list | None:
    """OpenLineage event 들을 Marquez `/api/v1/lineage` 로 전송.

    MARQUEZ_URL 미설정이거나 events 비면 no-op(None). opener 주입 시 네트워크 없이 테스트.
    """
    if not enabled() or not events:
        return None
    kwargs = {
        "base_url": os.environ["MARQUEZ_URL"],
        "timeout": timeout,
        "token": os.getenv("MARQUEZ_TOKEN"),
    }
    if opener is not None:
        kwargs["opener"] = opener
    return send_openlineage_events_to_marquez(events, **kwargs)
