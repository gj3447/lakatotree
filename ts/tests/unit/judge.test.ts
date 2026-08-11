/** Scenario JUDGE-PURE: 결정론 판정 경계. */
import { describe, expect, it } from "vitest";
import { judge, type PredictionSpec } from "../../src/domain/judge.ts";

const spec: PredictionSpec = { baselineMicro: 0, direction: "higher", noiseBandMicro: 50_000 };

describe("judge boundaries (micro-int, floor-free exact)", () => {
  it("delta > band -> progressive (with receipt) / progressive_unverified (without)", () => {
    const withReceipt = judge(spec, 50_001, true);
    const withoutReceipt = judge(spec, 50_001, false);
    expect(withReceipt).toMatchObject({ metricVerdict: "progressive", finalVerdict: "progressive" });
    expect(withoutReceipt).toMatchObject({ finalVerdict: "progressive_unverified" });
  });

  it("delta == band -> partial (경계는 밴드 안)", () => {
    expect(judge(spec, 50_000, true)).toMatchObject({ metricVerdict: "partial" });
  });

  it("delta == 0 -> equivalent; delta < 0 -> rejected", () => {
    expect(judge(spec, 0, true)).toMatchObject({ metricVerdict: "equivalent" });
    expect(judge(spec, -1, true)).toMatchObject({ metricVerdict: "rejected" });
  });

  it("direction lower inverts delta", () => {
    const lower: PredictionSpec = { baselineMicro: 100, direction: "lower", noiseBandMicro: 10 };
    expect(judge(lower, 80, true)).toMatchObject({ deltaMicro: 20, metricVerdict: "progressive" });
    expect(judge(lower, 120, true)).toMatchObject({ deltaMicro: -20, metricVerdict: "rejected" });
  });

  it("non-integer / negative band -> typed error (총함수, throw 없음)", () => {
    expect(judge({ ...spec, noiseBandMicro: -1 }, 1, true)).toMatchObject({ _tag: "invalid_spec" });
    expect(judge(spec, 1.5, true)).toMatchObject({ _tag: "invalid_spec" });
  });
});
