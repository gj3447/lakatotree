/** L층 — 보증 VAL(L0~L3) 읽기 시점 파생. 절대 저장하지 않는다 (SLSA 규칙, FSM_DESIGN_v0 §1).
 * 규칙은 정본 엔진 verdicts.py:373-406 의 사다리를 v0 로 이식. dead-σ: 부재는 강등 사유가 아니다 —
 * 오직 양성 반증(chain broken, replay mismatch)만이 캡을 씌운다. */

export type ValLevel =
  | "client_asserted"
  | "receipted"
  | "replay_verified"
  | "attested_witnessed";

export type MeasurementGrade =
  | "server_regenerated"
  | "attested"
  | "authored"
  | "client_asserted";

export interface SealedFacts {
  readonly chainOk: boolean;
  readonly replayStatus: "verified" | "mismatch" | "not_attempted";
  readonly measurementGrade: MeasurementGrade;
  readonly measurementLockBound: boolean;
  readonly tierAnchored: boolean;
  readonly attestorAllowed: boolean;
  readonly engineRuleInFloor: boolean;
  readonly temporalWitness: boolean;
}

export interface Assurance {
  readonly level: ValLevel;
  readonly basis: readonly string[];
}

export const deriveAssurance = (facts: SealedFacts): Assurance => {
  if (!facts.chainOk) {
    return { level: "client_asserted", basis: ["receipt_chain_broken"] };
  }
  if (facts.replayStatus === "mismatch") {
    return { level: "client_asserted", basis: ["replay_refuted"] };
  }
  const receipted =
    facts.measurementGrade === "attested" ||
    (facts.measurementGrade === "server_regenerated" && facts.replayStatus === "verified");
  if (!receipted) {
    return { level: "client_asserted", basis: ["client_asserted_unverified"] };
  }
  const replayVerified =
    facts.measurementGrade === "server_regenerated" &&
    facts.replayStatus === "verified" &&
    facts.measurementLockBound;
  if (!replayVerified) {
    return { level: "receipted", basis: ["receipt_minted"] };
  }
  const witnessed =
    facts.tierAnchored &&
    facts.attestorAllowed &&
    facts.engineRuleInFloor &&
    facts.temporalWitness;
  if (!witnessed) {
    return { level: "replay_verified", basis: ["measurement_lock_bound"] };
  }
  return { level: "attested_witnessed", basis: ["temporal_witness_quorum"] };
};
