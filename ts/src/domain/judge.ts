/** 결정론 판정 — 순수 총함수. 값은 마이크로 단위 정수(1e6 스케일), float 금지.
 * v0 자체 계약 — Python 오라클 파리티는 별도 게이트로 승격 전까지 주장하지 않는다 (AGENTS.md §오라클 경계).
 * dead-σ: 측정 부재는 이 함수에 도달하지 않는다 — 부재≠반증은 standing 파생(derive.ts)이 소유. */

export const METRIC_SCALE = 1_000_000;

export type Direction = "higher" | "lower";

export type MetricVerdict = "progressive" | "partial" | "equivalent" | "rejected";

export interface PredictionSpec {
  readonly baselineMicro: number;
  readonly direction: Direction;
  readonly noiseBandMicro: number;
}

export interface Judgment {
  readonly deltaMicro: number;
  readonly metricVerdict: MetricVerdict;
  readonly qualitativeReceipt: boolean;
  readonly finalVerdict: MetricVerdict | "progressive_unverified";
}

export type JudgeError = { readonly _tag: "invalid_spec"; readonly reason: string };

const isInt = (n: number): boolean => Number.isSafeInteger(n);

export const judge = (
  spec: PredictionSpec,
  valueMicro: number,
  qualitativeReceipt: boolean,
): Judgment | JudgeError => {
  if (!isInt(spec.baselineMicro) || !isInt(valueMicro) || !isInt(spec.noiseBandMicro)) {
    return { _tag: "invalid_spec", reason: "non_integer_micro" };
  }
  if (spec.noiseBandMicro < 0) {
    return { _tag: "invalid_spec", reason: "negative_noise_band" };
  }
  const deltaMicro =
    spec.direction === "higher"
      ? valueMicro - spec.baselineMicro
      : spec.baselineMicro - valueMicro;
  const metricVerdict: MetricVerdict =
    deltaMicro > spec.noiseBandMicro
      ? "progressive"
      : deltaMicro > 0
        ? "partial"
        : deltaMicro === 0
          ? "equivalent"
          : "rejected";
  const finalVerdict =
    metricVerdict === "progressive" && !qualitativeReceipt
      ? "progressive_unverified"
      : metricVerdict;
  return { deltaMicro, metricVerdict, qualitativeReceipt, finalVerdict };
};
