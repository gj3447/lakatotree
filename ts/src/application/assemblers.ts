/** 도구별 body 조립기 — Python mcp_server.py 의 클라이언트측 조립 셈 정확 이식 (recon 리스크 #2:
 * 제네릭 passthrough 는 서버 계약을 깬다). 각 함수 주석에 원본 def 를 인용. 전부 순수 총함수 —
 * JSON 파싱 실패·결합 위반은 서버 미호출 로컬 오류 값 (Python 과 동일한 fail-closed 관례). */

export type AssembleError = {
  readonly _tag: "assemble_error";
  readonly reason:
    | "invalid_freshen_binding"
    | "invalid_parent_edges"
    | "invalid_payload_json"
    | "invalid_longinus_refs_json"
    | "invalid_write_cert_json";
  readonly detail: string;
};

export type Assembled = {
  readonly _tag: "body";
  readonly body: Readonly<Record<string, unknown>>;
};

export type ToolArgs = Readonly<Record<string, string | number | boolean>>;
export type Assembler = (args: ToolArgs) => Assembled | AssembleError;

const str = (args: ToolArgs, key: string, fallback = ""): string => {
  const value = args[key];
  return value === undefined ? fallback : String(value);
};

const boolOf = (args: ToolArgs, key: string, fallback: boolean): boolean => {
  const value = args[key];
  if (typeof value === "boolean") return value;
  if (value === "true") return true;
  if (value === "false") return false;
  return fallback;
};

const numOf = (args: ToolArgs, key: string): number | undefined => {
  const value = args[key];
  return typeof value === "number" ? value : undefined;
};

/** bool | null 3치 — Python `bool | None = None` 파라미터 대응 (미제출=null 이 와이어에 실린다). */
const triBool = (args: ToolArgs, key: string): boolean | null => {
  const value = args[key];
  if (typeof value === "boolean") return value;
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
};

const csv = (raw: string): readonly string[] =>
  raw.split(",").map((x) => x.trim()).filter((x) => x !== "");

const ok = (body: Readonly<Record<string, unknown>>): Assembled => ({ _tag: "body", body });

const jsonParse = (raw: string): unknown | Error => {
  try {
    return JSON.parse(raw) as unknown;
  } catch (cause) {
    return cause instanceof Error ? cause : new Error("parse_failed");
  }
};

/** _parse_parent_edges_json 셈: 64KB·64엣지 상한, 필드 whitelist(tag/inferred/relation_kind/
 * evidence_ref), knowledge_inheritance 외 관계·inferred 엣지는 evidence_ref 필수. */
const PARENT_EDGE_FIELDS = new Set(["tag", "inferred", "relation_kind", "evidence_ref"]);
const parseParentEdges = (
  raw: string,
): readonly Record<string, unknown>[] | AssembleError => {
  const fail = (detail: string): AssembleError => ({
    _tag: "assemble_error", reason: "invalid_parent_edges", detail,
  });
  if (raw.length > 65_536) return fail("over_64kb");
  const parsed = jsonParse(raw);
  if (parsed instanceof Error || !Array.isArray(parsed)) return fail("not_a_json_array");
  if (parsed.length > 64) return fail("over_64_edges");
  const edges: Record<string, unknown>[] = [];
  for (const item of parsed) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      return fail("edge_not_object");
    }
    const edge = item as Record<string, unknown>;
    for (const key of Object.keys(edge)) {
      if (!PARENT_EDGE_FIELDS.has(key)) return fail(`unknown_field:${key}`);
    }
    if (typeof edge["tag"] !== "string" || edge["tag"] === "") return fail("edge_missing_tag");
    const relation = edge["relation_kind"];
    const inferred = edge["inferred"] === true;
    const typed = typeof relation === "string" && relation !== "knowledge_inheritance";
    if ((typed || inferred) && typeof edge["evidence_ref"] !== "string") {
      return fail("typed_or_inferred_edge_requires_evidence_ref");
    }
    edges.push(edge);
  }
  return edges;
};

export const ASSEMBLERS: Readonly<Record<string, Assembler>> = {
  /** parents = csv(parents_csv); parent 있으면 맨앞 삽입. parent_edges/result_path 조건부. */
  add_node: (args) => {
    const parents = [...csv(str(args, "parents_csv"))];
    const parent = str(args, "parent");
    if (parent !== "") parents.unshift(parent);
    const body: Record<string, unknown> = {
      tag: str(args, "tag"),
      parents,
      comment: str(args, "comment"),
      algorithm: str(args, "algorithm"),
      author: str(args, "author"),
    };
    const edgesRaw = str(args, "parent_edges_json");
    if (edgesRaw !== "") {
      const edges = parseParentEdges(edgesRaw);
      if (!Array.isArray(edges)) return edges as AssembleError;
      body["parent_edges"] = edges;
    }
    const resultPath = str(args, "result_path");
    if (resultPath !== "") body["result_path"] = resultPath;
    return ok(body);
  },

  /** metric→metric_name, baseline→baseline_value 개명. novel 블록·judge_script_sha·credence·
   * closes_question 은 조건부. direction 기본 'lower', novel_direction 기본 'higher'. */
  register_prediction: (args) => {
    const body: Record<string, unknown> = {
      metric_name: str(args, "metric"),
      direction: str(args, "direction", "lower"),
      baseline_value: numOf(args, "baseline") ?? 0,
      noise_band: numOf(args, "noise_band") ?? 0,
    };
    const novelMetric = str(args, "novel_metric");
    if (novelMetric !== "") {
      body["novel_metric"] = novelMetric;
      body["novel_direction"] = str(args, "novel_direction") || "higher";
      body["novel_threshold"] = numOf(args, "novel_threshold") ?? 0;
    }
    const scriptSha = str(args, "script_sha");
    if (scriptSha !== "") body["judge_script_sha"] = scriptSha;
    const credence = numOf(args, "credence");
    if (credence !== undefined) body["credence"] = credence;
    const closes = str(args, "closes_question");
    if (closes !== "") body["closes_question"] = closes;
    return ok(body);
  },

  /** value→metric_value. freshen ↔ supersedes 동시 결합(위반=서버 미호출 로컬 오류 — Python 동일).
   * lakatos 4축·ce_in_heuristic_spirit 은 3치(null=미제출), counterexample_* 빈문자→null. */
  submit_result: (args) => {
    const freshen = boolOf(args, "freshen", false);
    const supersedes = str(args, "supersedes_receipt_sha");
    if (freshen !== (supersedes !== "")) {
      return {
        _tag: "assemble_error",
        reason: "invalid_freshen_binding",
        detail: "freshen=true and supersedes_receipt_sha must be supplied together",
      };
    }
    const body: Record<string, unknown> = {
      metric_value: numOf(args, "value") ?? 0,
      script: str(args, "script"),
      freshen,
      data_branch: boolOf(args, "data_branch", false),
      data_replay_passed: boolOf(args, "data_replay_passed", true),
      human_verdict_required: boolOf(args, "human_verdict_required", false),
      lakatos_anomaly: triBool(args, "lakatos_anomaly"),
      lakatos_consequence: triBool(args, "lakatos_consequence"),
      lakatos_excess: triBool(args, "lakatos_excess"),
      lakatos_hardcore: triBool(args, "lakatos_hardcore"),
      touched_assumptions: csv(str(args, "touched_assumptions_csv")),
      implementation_complete: boolOf(args, "implementation_complete", true),
      counterexample_response: str(args, "counterexample_response") || null,
      counterexample_type: str(args, "counterexample_type") || null,
      ce_excess_content: boolOf(args, "ce_excess_content", false),
      ce_novel_corroborated: boolOf(args, "ce_novel_corroborated", false),
      ce_in_heuristic_spirit: triBool(args, "ce_in_heuristic_spirit"),
      ce_proof_concept_name: str(args, "ce_proof_concept_name"),
      ce_proof_born_from: str(args, "ce_proof_born_from"),
      ce_proof_incorporated_lemma: str(args, "ce_proof_incorporated_lemma"),
    };
    if (supersedes !== "") body["supersedes_receipt_sha"] = supersedes;
    const scriptSha = str(args, "script_sha");
    if (scriptSha !== "") body["script_sha"] = scriptSha;
    const novelMeasured = numOf(args, "novel_measured");
    if (novelMeasured !== undefined) body["novel_measured"] = novelMeasured;
    const novelScript = str(args, "novel_script");
    if (novelScript !== "") body["novel_script"] = novelScript;
    const writeCertRaw = str(args, "write_cert_json");
    if (writeCertRaw !== "") {
      const cert = jsonParse(writeCertRaw);
      if (cert instanceof Error) {
        return {
          _tag: "assemble_error", reason: "invalid_write_cert_json", detail: cert.message,
        };
      }
      body["write_cert"] = cert;
    }
    const resultPath = str(args, "result_path");
    if (resultPath !== "") body["result_path"] = resultPath;
    return ok(body);
  },

  /** payload={qname,body}; expected_gain/cost 는 값 있을 때만 (서버 파생값 보존). */
  open_question: (args) => {
    const body: Record<string, unknown> = {
      qname: str(args, "qname"),
      body: str(args, "body"),
    };
    const gain = numOf(args, "expected_gain");
    if (gain !== undefined) body["expected_gain"] = gain;
    const cost = numOf(args, "cost");
    if (cost !== undefined) body["cost"] = cost;
    return ok(body);
  },

  /** 전 필드 상시 포함(last-write-wins 셈 보존), assurance_tier ''→null, attestor csv ''→null. */
  create_tree: (args) => {
    const attestorRaw = str(args, "attestor_dids_csv").trim();
    const tier = str(args, "assurance_tier").trim();
    const body: Record<string, unknown> = {
      title: str(args, "title"),
      hard_core: str(args, "hard_core"),
      frontier_rule: str(args, "frontier_rule"),
      doc: str(args, "doc"),
      coverage_status: str(args, "coverage_status", "unknown"),
      coverage_statement: str(args, "coverage_statement"),
      coverage_backlog: csv(str(args, "coverage_backlog_csv")),
      ontology: str(args, "ontology"),
      require_novel_anchor: boolOf(args, "require_novel_anchor", false),
      assurance_tier: tier === "" ? null : tier,
      attestor_dids: attestorRaw === "" ? null : csv(attestorRaw),
      cycle_budget: numOf(args, "cycle_budget") ?? null,
    };
    return ok(body);
  },

  /** requirement_name→name 개명, csv 2종 → list. */
  add_foundation: (args) =>
    ok({
      name: str(args, "requirement_name"),
      kind: str(args, "kind"),
      question: str(args, "question"),
      why_needed: str(args, "why_needed"),
      acceptance_criteria: csv(str(args, "acceptance_csv")),
      evidence_refs: csv(str(args, "evidence_csv")),
      status: str(args, "status", "needed"),
      optional: boolOf(args, "optional", false),
      owner: str(args, "owner"),
      risk_if_missing: str(args, "risk_if_missing"),
    }),

  /** element_name→name 개명 (트리 name 충돌 회피). */
  add_element: (args) =>
    ok({
      name: str(args, "element_name"),
      definition: str(args, "definition"),
      implication: str(args, "implication"),
      lifecycle: str(args, "lifecycle"),
      scope: str(args, "scope", "domain-agnostic"),
    }),

  /** payload_json 파싱 실패 = 서버 미호출 로컬 오류 (Python invalid_payload_json 동일). */
  add_research_event: (args) => {
    const payload = jsonParse(str(args, "payload_json", "{}") || "{}");
    if (payload instanceof Error) {
      return { _tag: "assemble_error", reason: "invalid_payload_json", detail: payload.message };
    }
    return ok({
      event_id: str(args, "event_id"),
      realm: str(args, "realm"),
      actor: str(args, "actor"),
      action: str(args, "action"),
      evidence_refs: csv(str(args, "evidence_csv")),
      payload,
    });
  },

  /** inputs_csv 'path:sha' rsplit(':',1) — ':' 없는 항목 무음 드롭 (Python 셈 보존). */
  record_derivation: (args) => {
    const inputs = str(args, "inputs_csv")
      .split(",")
      .filter((p) => p.includes(":"))
      .map((p) => {
        const idx = p.lastIndexOf(":");
        return [p.slice(0, idx).trim(), p.slice(idx + 1).trim()];
      });
    return ok({
      output: str(args, "output"),
      output_sha: str(args, "output_sha"),
      producer: str(args, "producer"),
      producer_sha: str(args, "producer_sha"),
      inputs,
      kind: str(args, "kind", "intermediate"),
    });
  },

  /** 신뢰성분 8종 float 는 값 있을 때만, theory/rival/csv/longinus 조건부. */
  add_observation: (args) => {
    const body: Record<string, unknown> = {
      event_id: str(args, "event_id"),
      url: str(args, "url"),
      source_type: str(args, "source_type"),
      lakatos_location: str(args, "lakatos_location"),
      retrieved_at: str(args, "retrieved_at"),
      content_hash: str(args, "content_hash"),
      raw_snapshot_path: str(args, "raw_snapshot_path"),
      content: str(args, "content"),
    };
    const theory = str(args, "theory_basis");
    if (theory !== "") body["theory_basis"] = theory;
    const foundationRefs = str(args, "foundation_refs_csv");
    if (foundationRefs !== "") body["foundation_refs"] = csv(foundationRefs);
    for (const key of ["rival_name", "rival_relation", "rival_node"]) {
      const value = str(args, key);
      if (value !== "") body[key] = value;
    }
    const axes = str(args, "comparison_axes_csv");
    if (axes !== "") body["comparison_axes"] = csv(axes);
    const longinusRaw = str(args, "longinus_refs_json");
    if (longinusRaw !== "") {
      const refs = jsonParse(longinusRaw);
      if (refs instanceof Error) {
        return {
          _tag: "assemble_error", reason: "invalid_longinus_refs_json", detail: refs.message,
        };
      }
      body["longinus_refs"] = Array.isArray(refs) ? refs : [refs];
    }
    for (const key of [
      "trust", "link_authority", "source_class_weight", "primary_source_bonus",
      "provenance_score", "corroboration_score", "recency_score", "supply_chain_score",
    ]) {
      const value = numOf(args, key);
      if (value !== undefined) body[key] = value;
    }
    return ok(body);
  },

  /** exit_code 는 값 있을 때만 (None 생략 — Python 동일). */
  add_world_action: (args) => {
    const body: Record<string, unknown> = {
      event_id: str(args, "event_id"),
      command: str(args, "command"),
      cwd: str(args, "cwd"),
      stdout_summary: str(args, "stdout_summary"),
      stderr_summary: str(args, "stderr_summary"),
      git_diff_hash: str(args, "git_diff_hash"),
      require_git_diff: boolOf(args, "require_git_diff", false),
    };
    const exitCode = numOf(args, "exit_code");
    if (exitCode !== undefined) body["exit_code"] = exitCode;
    return ok(body);
  },
};
