/** Scenario TREE-1: 등록→제출→판정→CAS 재판정이 순수 이벤트 리플레이로 성립. */
import { describe, expect, it } from "vitest";
import type { FsmEvent } from "../../src/contracts/fsm.ts";
import { applyNodeEvent, initialNodeState, replay } from "../../src/domain/node.ts";
import { receiptSha, RECEIPT_TYPE_HEADER } from "../../src/domain/receipts.ts";

const register: FsmEvent = {
  type: "PREDICTION_REGISTERED",
  event_id: "e1",
  actor_role: "author",
  payload: {
    tree: "t", tag: "n1", metric: "m", spec_sha: "spec-sha",
    baseline: 0, direction: "higher", noise_band: 50_000,
  },
};

const submit = (value: number, eventId: string): FsmEvent => ({
  type: "RESULT_SUBMITTED",
  event_id: eventId,
  actor_role: "author",
  payload: { tree: "t", tag: "n1", value, bundle_sha: "b1" },
});

const rejudge = (value: number, supersedes: string, eventId: string): FsmEvent => ({
  type: "REJUDGE_SUBMITTED",
  event_id: eventId,
  actor_role: "author",
  payload: { tree: "t", tag: "n1", value, bundle_sha: "b2", supersedes_receipt_sha: supersedes },
});

describe("Scenario TREE-1", () => {
  it("register -> submit yields a judge-derived verdict, not an author-supplied one", () => {
    const afterRegister = applyNodeEvent(initialNodeState, register);
    expect(afterRegister.admitted).toBe(true);
    expect(afterRegister.next.spec).toEqual({
      baselineMicro: 0, direction: "higher", noiseBandMicro: 50_000,
    });

    const afterSubmit = applyNodeEvent(afterRegister.next, submit(87_000, "e2"));
    expect(afterSubmit.admitted).toBe(true);
    const seal = afterSubmit.commands.find((c) => c.effect === "SealVerdictReceipt");
    expect(seal?.payload["verdict"]).toBe("progressive_unverified");
    expect(afterSubmit.next.config.state).toBe("judged");
    // G1 read-time recompute: head must equal an independently recomputed content sha
    const expected = receiptSha({
      type_header: RECEIPT_TYPE_HEADER, tree: "t", tag: "n1",
      verdict: "progressive_unverified", value_micro: 87_000, bundle_sha: "b1",
      event_id: "e2", prev_receipt_sha: "",
    });
    expect(afterSubmit.next.config.context.head_receipt_sha).toBe(expected);
    expect(seal?.payload["receipt_sha"]).toBe(expected);
  });

  it("partial when delta is inside the noise band; rejected when negative", () => {
    const s = applyNodeEvent(initialNodeState, register).next;
    const partial = applyNodeEvent(s, submit(40_000, "e2"));
    expect(partial.commands[0]?.payload["verdict"]).toBe("partial");
    const rejected = applyNodeEvent(s, submit(-5, "e2b"));
    expect(rejected.commands[0]?.payload["verdict"]).toBe("rejected");
  });

  it("rejudge succeeds only against the exact current head (CAS), chain N.new == N+1.old", () => {
    const judged = replay([register, submit(87_000, "e2")]);
    const head1 = judged.config.context.head_receipt_sha;
    expect(head1.startsWith("sha256:")).toBe(true);
    const good = applyNodeEvent(judged, rejudge(10_000, head1, "e3"));
    expect(good.admitted).toBe(true);
    const head2 = good.next.config.context.head_receipt_sha;
    expect(head2.startsWith("sha256:")).toBe(true);
    expect(head2).not.toBe(head1);
    const cas = good.commands.find((c) => c.effect === "MovePointerCAS");
    expect(cas?.payload["expected_old"]).toBe(head1);
    expect(cas?.payload["new_value"]).toBe(head2);
    const seal = good.commands.find((c) => c.effect === "SealVerdictReceipt");
    expect(seal?.payload["prev_receipt_sha"]).toBe(head1);

    const stale = applyNodeEvent(good.next, rejudge(1, head1, "e4"));
    expect(stale.admitted).toBe(false);
    expect(stale.next.config.context.head_receipt_sha).toBe(head2);
  });

  it("submit without prereg and double-register are audited, state unchanged", () => {
    const noPrereg = applyNodeEvent(initialNodeState, submit(1, "e9"));
    expect(noPrereg.admitted).toBe(false);
    expect(noPrereg.next).toEqual(initialNodeState);

    const once = applyNodeEvent(initialNodeState, register).next;
    const twice = applyNodeEvent(once, register);
    expect(twice.admitted).toBe(false);
    expect(twice.next.config.state).toBe("preregistered");
  });

  it("replay determinism: same event log twice -> identical state", () => {
    const afterSubmit = replay([register, submit(87_000, "e2")]);
    const log = [register, submit(87_000, "e2"),
      rejudge(60_000, afterSubmit.config.context.head_receipt_sha, "e3")];
    expect(replay(log)).toEqual(replay(log));
    expect(replay(log).receiptCount).toBe(3);
  });
});
