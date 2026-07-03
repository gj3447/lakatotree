"""감독 유지보수 러너(git-흡수 G2 메커니즘축, S5).

git gc(builtin/gc.c:718-783,1700-1828)의 배경-upkeep 패턴 이식: 스케줄 태스크를 (1) pid+host lock 하에 돌리되
staleness+liveness 로 stale lock 을 탈취하고, (2) 태스크 실패는 latch(poison-pill)로 남겨 다음 실행을 *차단*하며
사람이 명시적으로 clear 할 때까지 재실행 불가, (3) 모든 skip 을 기록(무음 skip 금지).

★anti-absorption(설계에 박음): git 의 무음 skip-on-contention/volume-triggered auto-gc 는 이식하지 않는다 —
인식적 행동을 자동 트리거하지 않고 *표현 upkeep*(rebuild_verify·미러싱크·stale-브랜치 리포트)만 스케줄하며,
경합/실패는 반드시 기록한다. 순수 상태기계 — now()·lock store·latch store 를 주입받아 결정론적으로 단위검증.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field


@dataclass
class RunOutcome:
    ran: list[str] = field(default_factory=list)          # 이번에 실행된 태스크
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (사유, 상세) — 무음 아님
    latched: str | None = None                            # 이번 실행이 latch 를 걸었으면 원인 태스크
    lock_owner: str | None = None                         # 실행 시점 lock 소유자


# lock 이 stale 로 간주되는 시간(초). git gc 의 12h 기본을 이식.
LOCK_STALE_SECONDS = 12 * 3600


class MaintenanceRunner:
    """단일-writer 유지보수 실행기. 순수(I/O 주입): now(단조 초), lock/latch store(dict-like), liveness 프로브."""

    def __init__(
        self,
        *,
        tasks: Mapping[str, Callable[[], None]],
        lock_store: MutableMapping[str, dict],
        latch_store: MutableMapping[str, dict],
        now: Callable[[], float],
        host: str,
        pid: int,
        is_alive: Callable[[int], bool] = lambda _pid: True,
        lock_stale_seconds: float = LOCK_STALE_SECONDS,
    ):
        self.tasks = dict(tasks)
        self.lock_store = lock_store
        self.latch_store = latch_store
        self.now = now
        self.host = host
        self.pid = pid
        self.is_alive = is_alive
        self.lock_stale_seconds = lock_stale_seconds

    # ── lock: pid+host, staleness+liveness 로 탈취 가능 ──────────────────────────────────
    def _held_by_other(self) -> dict | None:
        lk = self.lock_store.get("maintenance")
        if not lk:
            return None
        if lk.get("host") == self.host and lk.get("pid") == self.pid:
            return None                                   # 내 lock(재진입)
        age = self.now() - lk.get("acquired_at", self.now())
        # 같은 host 의 죽은 pid → stale · 어떤 host 든 stale_seconds 초과 → stale(탈취 허용)
        dead = lk.get("host") == self.host and not self.is_alive(lk.get("pid", -1))
        if dead or age >= self.lock_stale_seconds:
            return None
        return lk                                          # 살아있는 타 소유자 → 양보

    def _acquire(self) -> None:
        self.lock_store["maintenance"] = {"host": self.host, "pid": self.pid, "acquired_at": self.now()}

    def _release(self) -> None:
        lk = self.lock_store.get("maintenance")
        if lk and lk.get("host") == self.host and lk.get("pid") == self.pid:
            del self.lock_store["maintenance"]

    # ── latch: 실패가 다음 실행을 차단(사람이 clear 할 때까지) ─────────────────────────────
    def is_latched(self) -> bool:
        return bool(self.latch_store.get("maintenance"))

    def latch_info(self) -> dict | None:
        return self.latch_store.get("maintenance")

    def clear_latch(self) -> bool:
        """사람이 명시적으로 latch 해제(acknowledge). 해제 대상이 있었으면 True."""
        return self.latch_store.pop("maintenance", None) is not None

    def _set_latch(self, task: str, detail: str) -> None:
        self.latch_store["maintenance"] = {"task": task, "detail": detail, "at": self.now()}

    # ── run: latch 차단 → lock 경합 → 순차 실행(실패 시 latch, 이후 태스크 skip) ──────────
    def run(self) -> RunOutcome:
        out = RunOutcome()

        if self.is_latched():                              # (1) poison-pill: clear 전엔 재실행 불가
            info = self.latch_info() or {}
            out.skipped.append(("latched", f"prior failure in '{info.get('task')}' — clear_latch() 필요"))
            return out

        other = self._held_by_other()                     # (2) lock 경합 — 무음 아님, 기록
        if other is not None:
            out.lock_owner = f"{other.get('host')}:{other.get('pid')}"
            out.skipped.append(("lock_contended", f"held by {out.lock_owner}"))
            return out

        self._acquire()
        out.lock_owner = f"{self.host}:{self.pid}"
        try:
            for name, fn in self.tasks.items():            # (3) 순차 실행 — 실패는 latch + 잔여 skip
                if out.latched:
                    out.skipped.append(("after_latch", name))
                    continue
                try:
                    fn()
                    out.ran.append(name)
                except Exception as e:                     # noqa: BLE001 — 유지보수 태스크는 어떤 실패든 latch
                    self._set_latch(name, f"{type(e).__name__}: {e}")
                    out.latched = name
        finally:
            self._release()
        return out
