/** B3 무진전 정지 — CLAUDE.md §5: '같은 게이트가 3회 연속 같은 이유로 RED면 정지하고 증거를
 * 보고한다. 밤새 같은 벽을 때리지 않는다.' 상수는 조문 그대로 — 설정화 금지 (spec-pin).
 * 스트릭은 게이트별 독립(인터리빙 무영향), 배열 순서는 최초 등록 순(리플레이 결정론 핀).
 * reason 은 관측 데이터(열린 문자열) — 어댑터가 정규화 책임을 진다 (타임스탬프·경로 섞으면
 * '같은 이유' 비교가 영원히 안 터진다). */

export const NO_PROGRESS_RED_LIMIT = 3;

export interface GateResult {
  readonly _tag: "GateResultRecorded";
  readonly runId: string;
  readonly gateId: string;
  readonly outcome: "green" | "red";
  readonly reason: string;
}

export interface GateStreak {
  readonly gateId: string;
  readonly reason: string;
  readonly consecutiveReds: number;
}

export const reduceStreaks = (
  streaks: readonly GateStreak[],
  result: GateResult,
): readonly GateStreak[] => {
  if (result.outcome === "green") {
    return streaks.filter((s) => s.gateId !== result.gateId);
  }
  const existing = streaks.find((s) => s.gateId === result.gateId);
  if (existing === undefined) {
    return [...streaks, { gateId: result.gateId, reason: result.reason, consecutiveReds: 1 }];
  }
  return streaks.map((s) =>
    s.gateId !== result.gateId
      ? s
      : s.reason === result.reason
        ? { gateId: s.gateId, reason: s.reason, consecutiveReds: s.consecutiveReds + 1 }
        : { gateId: s.gateId, reason: result.reason, consecutiveReds: 1 },
  );
};

export const streakOf = (
  streaks: readonly GateStreak[],
  gateId: string,
): GateStreak | undefined => streaks.find((s) => s.gateId === gateId);
