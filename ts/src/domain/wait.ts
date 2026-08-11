/** B4 대기 ≠ 계산 — CLAUDE.md §5: '대기는 1회 스케줄/완료 알림으로 처리한다. 폴링 루프에 토큰을
 * 태우지 않는다.' 열린 대상 재스케줄 = 폴링의 기계적 부정. 대기 이벤트는 원장 어느 평면에도
 * 접촉하지 않는다 (property 게이트). target 은 문자열 완전 일치 — 표기 정규화는 어댑터 책임
 * (대상을 바꿔가며 재스케줄하면 미검출: 조문 직역의 한계, 과잉 일반화와 맞바꿈). */

export interface WaitScheduled {
  readonly _tag: "WaitScheduled";
  readonly runId: string;
  readonly target: string;
}

export interface WaitCompleted {
  readonly _tag: "WaitCompleted";
  readonly runId: string;
  readonly target: string;
}

export type WaitEvent = WaitScheduled | WaitCompleted;

export type WaitOutcome =
  | { readonly _tag: "ok"; readonly openWaits: readonly string[] }
  | { readonly _tag: "invalid_wait"; readonly reason: "duplicate_wait_poll" | "wait_not_open" };

export const applyWait = (
  openWaits: readonly string[],
  event: WaitEvent,
): WaitOutcome => {
  if (event._tag === "WaitScheduled") {
    return openWaits.includes(event.target)
      ? { _tag: "invalid_wait", reason: "duplicate_wait_poll" }
      : { _tag: "ok", openWaits: [...openWaits, event.target] };
  }
  return openWaits.includes(event.target)
    ? { _tag: "ok", openWaits: openWaits.filter((t) => t !== event.target) }
    : { _tag: "invalid_wait", reason: "wait_not_open" };
};
