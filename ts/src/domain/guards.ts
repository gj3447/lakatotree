/** 가드 — 전부 순수·동기. actor_role 권위표는 FSM_DESIGN_v0.md §2. */
import type { Configuration, FsmEvent, GuardName } from "../contracts/fsm.ts";

export type GuardFn = (config: Configuration, event: FsmEvent) => boolean;

const str = (event: FsmEvent, key: string): string => {
  const value = event.payload[key];
  return typeof value === "string" ? value : "";
};

export const GUARDS: Readonly<Record<GuardName, GuardFn>> = {
  is_author: (_config, event) => event.actor_role === "author",
  is_engine_auditor: (_config, event) => event.actor_role === "engine_auditor",
  is_human_owner: (_config, event) => event.actor_role === "human_owner",
  from_judgment_seam: (_config, event) =>
    event.actor_role === "judgment_seam" && str(event, "origin") === "judgment_seam",
  supersedes_matches_head: (config, event) =>
    config.context.head_receipt_sha !== "" &&
    config.context.head_receipt_sha === str(event, "supersedes_receipt_sha"),
  sha_matches: (_config, event) =>
    str(event, "bundle_sha") !== "" &&
    str(event, "bundle_sha") === str(event, "recomputed_sha"),
};
