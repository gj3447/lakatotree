/** Scenario ASSEMBLERS: Python mcp_server.py 클라이언트측 body 조립 셈의 정확 이식 —
 * 개명·csv 분해·조건부 포함(3치 null 포함)·로컬 fail-closed(서버 미호출). 각 기대값은
 * 원본 def 에서 도출 (recon 리스크 #2: 제네릭 passthrough 는 서버 계약을 깬다). */
import { describe, expect, it } from "vitest";
import { ASSEMBLERS } from "../../src/application/assemblers.ts";

const call = (name: string, args: Record<string, string | number | boolean>) => {
  const assemble = ASSEMBLERS[name];
  if (assemble === undefined) throw new Error(`no assembler: ${name}`);
  return assemble(args);
};

describe("assemblers — Python 셈 이식", () => {
  it("add_node: parent 는 parents_csv 앞에 삽입, result_path 조건부", () => {
    expect(call("add_node", { tag: "n1", parent: "root", parents_csv: "a, b" })).toEqual({
      _tag: "body",
      body: { tag: "n1", parents: ["root", "a", "b"], comment: "", algorithm: "", author: "" },
    });
  });

  it("add_node parent_edges: whitelist 밖 필드·evidence_ref 누락 typed edge 는 fail-closed", () => {
    expect(
      call("add_node", {
        tag: "n", parent_edges_json: JSON.stringify([{ tag: "r", relation_kind: "FORMALIZES" }]),
      }),
    ).toMatchObject({ _tag: "assemble_error", reason: "invalid_parent_edges" });
    expect(
      call("add_node", { tag: "n", parent_edges_json: JSON.stringify([{ tag: "r", bogus: 1 }]) }),
    ).toMatchObject({ _tag: "assemble_error", detail: "unknown_field:bogus" });
  });

  it("register_prediction: metric→metric_name·baseline→baseline_value 개명 + novel 블록 조건부", () => {
    expect(
      call("register_prediction", {
        metric: "loss", baseline: 1.5, novel_metric: "acc", script_sha: "s1", credence: 0.7,
      }),
    ).toEqual({
      _tag: "body",
      body: {
        metric_name: "loss", direction: "lower", baseline_value: 1.5, noise_band: 0,
        novel_metric: "acc", novel_direction: "higher", novel_threshold: 0,
        judge_script_sha: "s1", credence: 0.7,
      },
    });
  });

  it("submit_result: freshen ↔ supersedes 결합 위반은 서버 미호출 로컬 오류", () => {
    expect(call("submit_result", { value: 1, script: "s", freshen: true })).toMatchObject({
      _tag: "assemble_error", reason: "invalid_freshen_binding",
    });
    expect(
      call("submit_result", { value: 1, script: "s", supersedes_receipt_sha: "x".repeat(64) }),
    ).toMatchObject({ _tag: "assemble_error", reason: "invalid_freshen_binding" });
  });

  it("submit_result: 3치 미제출=null 이 와이어에 실린다 (lakatos 4축·counterexample)", () => {
    const result = call("submit_result", { value: 2.5, script: "judge.py" });
    expect(result._tag).toBe("body");
    if (result._tag !== "body") return;
    expect(result.body).toMatchObject({
      metric_value: 2.5, script: "judge.py", freshen: false,
      lakatos_anomaly: null, lakatos_consequence: null,
      counterexample_response: null, counterexample_type: null,
      ce_in_heuristic_spirit: null,
      data_replay_passed: true, implementation_complete: true,
      touched_assumptions: [],
    });
    expect("supersedes_receipt_sha" in result.body).toBe(false);
    expect("script_sha" in result.body).toBe(false);
  });

  it("create_tree: assurance_tier ''→null(불변) vs 값(선언), attestor csv ''→null", () => {
    const result = call("create_tree", { name: "t", attestor_dids_csv: "did:a, did:b" });
    expect(result._tag).toBe("body");
    if (result._tag !== "body") return;
    expect(result.body).toMatchObject({
      assurance_tier: null, attestor_dids: ["did:a", "did:b"],
      coverage_status: "unknown", require_novel_anchor: false, cycle_budget: null,
    });
  });

  it("open_question: expected_gain/cost 는 값 있을 때만 (서버 파생값 보존)", () => {
    expect(call("open_question", { qname: "q1", expected_gain: 0.4 })).toEqual({
      _tag: "body", body: { qname: "q1", body: "", expected_gain: 0.4 },
    });
  });

  it("record_derivation: 'path:sha' rsplit — ':' 없는 항목 무음 드롭 (Python 셈 보존)", () => {
    const result = call("record_derivation", {
      output: "o.csv", output_sha: "abc",
      inputs_csv: "raw/a.csv:s1, weird-no-colon, dir:x/b.csv:s2",
    });
    expect(result).toMatchObject({
      _tag: "body",
      body: { inputs: [["raw/a.csv", "s1"], ["dir:x/b.csv", "s2"]] },
    });
  });

  it("add_research_event: payload_json 파싱 실패는 로컬 오류 (invalid_payload_json 파리티)", () => {
    expect(
      call("add_research_event", { tag: "n", event_id: "e", realm: "r", action: "a", payload_json: "{x" }),
    ).toMatchObject({ _tag: "assemble_error", reason: "invalid_payload_json" });
  });

  it("add_observation: 신뢰성분 float 는 값 있을 때만, longinus 비배열은 배열 래핑", () => {
    const result = call("add_observation", {
      tag: "n", event_id: "e", trust: 0.5, longinus_refs_json: "{\"l\":1}",
    });
    expect(result._tag).toBe("body");
    if (result._tag !== "body") return;
    expect(result.body).toMatchObject({ trust: 0.5, longinus_refs: [{ l: 1 }] });
    expect("link_authority" in result.body).toBe(false);
  });

  it("add_world_action: exit_code 는 값 있을 때만 (None 생략)", () => {
    const withCode = call("add_world_action", { tag: "n", event_id: "e", exit_code: 0 });
    expect(withCode).toMatchObject({ _tag: "body", body: { exit_code: 0 } });
    const without = call("add_world_action", { tag: "n", event_id: "e" });
    expect(without._tag).toBe("body");
    if (without._tag !== "body") return;
    expect("exit_code" in without.body).toBe(false);
  });

  it("add_foundation·add_element: requirement_name/element_name → name 개명", () => {
    expect(call("add_foundation", { requirement_name: "req1", kind: "data" })).toMatchObject({
      _tag: "body", body: { name: "req1", kind: "data", status: "needed", optional: false },
    });
    expect(call("add_element", { element_name: "el1" })).toMatchObject({
      _tag: "body", body: { name: "el1", scope: "domain-agnostic" },
    });
  });
});
