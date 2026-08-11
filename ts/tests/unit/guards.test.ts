/** 프로덕션 가드 단위 게이트 — 권위표 FSM_DESIGN_v0.md §2 의 순수 가드 6종. */
import { describe, expect, it } from "vitest";
import type { ActorRole, Configuration, FsmEvent } from "../../src/contracts/fsm.ts";
import { GUARDS } from "../../src/domain/guards.ts";

const configWithHead = (head: string): Configuration => ({
  state: "judged",
  context: { head_receipt_sha: head, prediction_sealed: true, last_verdict: "" },
});

const event = (
  actor: ActorRole,
  payload: Readonly<Record<string, string | number>> = {},
): FsmEvent => ({
  type: "RESULT_SUBMITTED",
  event_id: "e-guard",
  actor_role: actor,
  payload,
});

describe("actor-role guards", () => {
  it("is_author admits only author", () => {
    expect(GUARDS.is_author(configWithHead(""), event("author"))).toBe(true);
    expect(GUARDS.is_author(configWithHead(""), event("human_owner"))).toBe(false);
  });

  it("is_engine_auditor admits only engine_auditor", () => {
    expect(GUARDS.is_engine_auditor(configWithHead(""), event("engine_auditor"))).toBe(true);
    expect(GUARDS.is_engine_auditor(configWithHead(""), event("author"))).toBe(false);
  });

  it("is_human_owner admits only human_owner", () => {
    expect(GUARDS.is_human_owner(configWithHead(""), event("human_owner"))).toBe(true);
    expect(GUARDS.is_human_owner(configWithHead(""), event("judgment_seam"))).toBe(false);
  });
});

describe("from_judgment_seam", () => {
  it("requires seam actor AND origin payload together", () => {
    const seamBoth = event("judgment_seam", { origin: "judgment_seam" });
    const seamActorOnly = event("judgment_seam");
    const originOnly = event("author", { origin: "judgment_seam" });
    expect(GUARDS.from_judgment_seam(configWithHead(""), seamBoth)).toBe(true);
    expect(GUARDS.from_judgment_seam(configWithHead(""), seamActorOnly)).toBe(false);
    expect(GUARDS.from_judgment_seam(configWithHead(""), originOnly)).toBe(false);
  });
});

describe("supersedes_matches_head (CAS)", () => {
  it("empty head never matches — first receipt cannot be superseded", () => {
    const evt = event("author", { supersedes_receipt_sha: "" });
    expect(GUARDS.supersedes_matches_head(configWithHead(""), evt)).toBe(false);
  });

  it("admits only an exact head match", () => {
    const match = event("author", { supersedes_receipt_sha: "sha-head" });
    const stale = event("author", { supersedes_receipt_sha: "sha-old" });
    expect(GUARDS.supersedes_matches_head(configWithHead("sha-head"), match)).toBe(true);
    expect(GUARDS.supersedes_matches_head(configWithHead("sha-head"), stale)).toBe(false);
  });
});

describe("sha_matches (bundle fail-closed)", () => {
  it("empty shas never seal", () => {
    const evt = event("anchor_verifier", { bundle_sha: "", recomputed_sha: "" });
    expect(GUARDS.sha_matches(configWithHead(""), evt)).toBe(false);
  });

  it("admits only an exact recomputed match", () => {
    const match = event("anchor_verifier", { bundle_sha: "b1", recomputed_sha: "b1" });
    const forged = event("anchor_verifier", { bundle_sha: "b1", recomputed_sha: "b2" });
    expect(GUARDS.sha_matches(configWithHead(""), match)).toBe(true);
    expect(GUARDS.sha_matches(configWithHead(""), forged)).toBe(false);
  });
});
