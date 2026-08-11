/** 게이트웨이 파이프라인 — 함수형 코어(emitPage·applyRunEvent)를 감싸는 얇은 상태 셸.
 * 모든 도구 응답은 ToolPage 경유(무제한 응답이 반환 타입으로 표현 불가), 호출마다
 * EmissionRecorded 실바이트(UTF-8) 계량이 RUN-BUDGET 게이트를 통과한다. 정지 후에는
 * 백엔드 포트 호출 자체가 없다(선차단). 초과를 만든 그 응답은 전달·기재된다(소비는 사실 —
 * 기재 후 정지). 오류 detail 은 [:300] 캡 — mcp_server.py 오류 캡 선례. truncatedBytes 는
 * '이 방출 시점의 미전달 잔여'(offset 이후 보존: emitted+truncated = offset 이후 원본). */
import type { BudgetDeclaration, DeclarationError } from "../domain/budget.ts";
import { validateBudgetDeclaration } from "../domain/budget.ts";
import type { EmissionRecorded } from "../domain/emission.ts";
import { emitPage, type ToolPage } from "../domain/page.ts";
import { ASSEMBLERS, type ToolArgs } from "./assemblers.ts";

export type { ToolArgs } from "./assemblers.ts";
import {
  applyRunEvent,
  initialRunState,
  type HaltReport,
  type RunState,
} from "../domain/run.ts";

export type QueryMode =
  | "required"
  | "omit_empty"
  | "bool_always"
  | "true_only"
  | "false_only"
  | "one_flag";

export interface QueryDef {
  readonly name: string;
  readonly mode: QueryMode;
}

export type BodyMode = "none" | "empty" | "flat" | "spec_json" | "assembler" | "local";

export interface ToolSpec {
  readonly name: string;
  readonly method: "GET" | "POST" | "PUT" | "DELETE" | "LOCAL";
  readonly path: string;
  readonly kind: "read" | "write" | "ops" | "local";
  readonly bodyMode: BodyMode;
  readonly capBytes: number;
  readonly query?: readonly QueryDef[];
  readonly idempotencyHeader?: boolean;
}

export interface StoreResponse {
  readonly status: number;
  readonly bodyText: string;
}

export interface StorePort {
  readonly request: (
    method: string,
    path: string,
    body: string | null,
    bearer: string | null,
    extraHeaders?: Readonly<Record<string, string>>,
  ) => Promise<StoreResponse>;
}

export type CallError = {
  readonly _tag: "invalid_call";
  readonly reason: "missing_param";
};

/** read_only: token_required 스토어 + 토큰 부재 기동 — kind:read 만 서빙, write/ops 는
 * 백엔드 미접촉 로컬 차단 (401 왕복조차 없음). Python 브리지의 사실상 무토큰 읽기 운용과 파리티. */
export type GatewayPosture = "full" | "read_only";

export type ToolError =
  | { readonly _tag: "tool_error"; readonly reason: "unknown_tool" }
  | { readonly _tag: "tool_error"; readonly reason: "auth_required"; readonly detail: string }
  | { readonly _tag: "tool_error"; readonly reason: "invalid_call"; readonly detail: string }
  | { readonly _tag: "tool_error"; readonly reason: "budget_halted"; readonly report: HaltReport }
  | { readonly _tag: "tool_error"; readonly reason: "unsupported_local_tool"; readonly detail: string }
  | { readonly _tag: "tool_error"; readonly reason: "assemble_error"; readonly detail: string }
  | {
      readonly _tag: "tool_error";
      readonly reason: "store_error";
      readonly status: number;
      readonly detail: string;
    };

const PARAM_PATTERN = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

export const buildPath = (
  template: string,
  params: ToolArgs,
): string | CallError => {
  let missing = false;
  const path = template.replace(PARAM_PATTERN, (_match, key: string) => {
    const value = params[key];
    if (value === undefined) {
      missing = true;
      return "";
    }
    return encodeURIComponent(String(value));
  });
  return missing ? { _tag: "invalid_call", reason: "missing_param" } : path;
};

const pathParamNames = (template: string): ReadonlySet<string> =>
  new Set([...template.matchAll(PARAM_PATTERN)].map((m) => m[1] ?? ""));

const truthy = (value: string | number | boolean | undefined): boolean =>
  value === true || value === "true" || value === 1 || value === "1";

/** 쿼리 직렬화 — Python 클라이언트의 도구별 생략 셈(spec query mode 표)을 그대로 이식. */
export const buildQuery = (
  defs: readonly QueryDef[],
  args: ToolArgs,
): string | CallError => {
  const pairs: string[] = [];
  for (const def of defs) {
    const raw = args[def.name];
    if (def.mode === "required") {
      if (raw === undefined || raw === "") {
        return { _tag: "invalid_call", reason: "missing_param" };
      }
      pairs.push(`${def.name}=${encodeURIComponent(String(raw))}`);
    } else if (def.mode === "omit_empty") {
      if (raw !== undefined && raw !== "") {
        pairs.push(`${def.name}=${encodeURIComponent(String(raw))}`);
      }
    } else if (def.mode === "bool_always") {
      pairs.push(`${def.name}=${truthy(raw) ? "true" : "false"}`);
    } else if (def.mode === "true_only") {
      if (truthy(raw)) pairs.push(`${def.name}=true`);
    } else if (def.mode === "false_only") {
      if (raw !== undefined && !truthy(raw)) pairs.push(`${def.name}=false`);
    } else {
      if (truthy(raw)) pairs.push(`${def.name}=1`);
    }
  }
  return pairs.length === 0 ? "" : `?${pairs.join("&")}`;
};

const ERROR_DETAIL_CAP = 300;

export interface Gateway {
  readonly call: (name: string, args: ToolArgs) => Promise<ToolPage | ToolError>;
  readonly state: () => RunState;
}

/** fail-closed 기동: 무효 선언은 게이트웨이를 만들지 않는다 — 무예산 fail-open 경로 봉쇄
 * (B1: 예산 없는 자율 실행은 시작하지 않는다. 제3자 리뷰 실결함 채택). */
export const createGateway = (
  specs: readonly ToolSpec[],
  decl: BudgetDeclaration,
  port: StorePort,
  bearer: string | null,
  posture: GatewayPosture = "full",
): Gateway | DeclarationError => {
  const invalid = validateBudgetDeclaration(decl);
  if (invalid !== null) {
    return invalid;
  }
  const byName = new Map(specs.map((s) => [s.name, s]));
  let state: RunState = applyRunEvent(initialRunState, decl).next;

  const call = async (name: string, rawArgs: ToolArgs): Promise<ToolPage | ToolError> => {
    const spec = byName.get(name);
    if (spec === undefined) {
      return { _tag: "tool_error", reason: "unknown_tool" };
    }
    // A-5 footgun 봉합(외부리뷰 2026-07-24): 경로의 {name}=트리명인데 직관과 반대라 반복 혼동 —
    // name 부재 시 tree= alias 를 수용한다. name 명시 시 alias 무시 (name 이 정본).
    let args = rawArgs;
    if (
      spec.path.includes("{name}") &&
      rawArgs["name"] === undefined &&
      rawArgs["tree"] !== undefined
    ) {
      const { tree, ...rest } = rawArgs;
      args = { ...rest, name: tree };
    }
    if (state.halt !== null) {
      return { _tag: "tool_error", reason: "budget_halted", report: state.halt };
    }
    if (spec.bodyMode === "local" || spec.method === "LOCAL") {
      return {
        _tag: "tool_error",
        reason: "unsupported_local_tool",
        detail: "HTTP 아닌 로컬 함수 — .venv CLI 사용, TS 이식은 별도 슬라이스 (spec not_mechanized)",
      };
    }
    if (posture === "read_only" && spec.kind !== "read") {
      return {
        _tag: "tool_error",
        reason: "auth_required",
        detail: "read-only 기동(store token_required + 토큰 부재) — write/ops 는 로컬 차단, LAKATOS_API_TOKEN 공급 후 재기동",
      };
    }
    const path = buildPath(spec.path, args);
    if (typeof path !== "string") {
      return { _tag: "tool_error", reason: "invalid_call", detail: path.reason };
    }
    const query = buildQuery(spec.query ?? [], args);
    if (typeof query !== "string") {
      return { _tag: "tool_error", reason: "invalid_call", detail: query.reason };
    }
    const cursorRaw = args["cursor"];
    const cursor = typeof cursorRaw === "string" ? cursorRaw : "";
    let body: string | null;
    if (spec.bodyMode === "none") {
      body = null;
    } else if (spec.bodyMode === "empty") {
      body = "{}";
    } else if (spec.bodyMode === "spec_json") {
      const raw = args["spec_json"];
      let parsed: unknown;
      try {
        parsed = JSON.parse(typeof raw === "string" ? raw : "");
      } catch {
        // Python 파리티: json.loads 실패 시 서버 미호출 로컬 오류 (invalid_spec_json)
        return { _tag: "tool_error", reason: "assemble_error", detail: "invalid_spec_json" };
      }
      body = JSON.stringify(parsed);
    } else if (spec.bodyMode === "assembler") {
      const assemble = ASSEMBLERS[name];
      if (assemble === undefined) {
        return { _tag: "tool_error", reason: "assemble_error", detail: "assembler_missing" };
      }
      const assembled = assemble(args);
      if (assembled._tag === "assemble_error") {
        return {
          _tag: "tool_error",
          reason: "assemble_error",
          detail: `${assembled.reason}:${assembled.detail}`.slice(0, ERROR_DETAIL_CAP),
        };
      }
      body = JSON.stringify(assembled.body);
    } else {
      const pathParams = pathParamNames(spec.path);
      const queryNames = new Set((spec.query ?? []).map((q) => q.name));
      const bodyEntries = Object.entries(args).filter(
        ([key]) =>
          !pathParams.has(key) && !queryNames.has(key) &&
          key !== "cursor" && key !== "idempotency_key",
      );
      body = JSON.stringify(Object.fromEntries(bodyEntries));
    }
    let extraHeaders: Readonly<Record<string, string>> | undefined;
    if (spec.idempotencyHeader === true) {
      const key = args["idempotency_key"];
      if (typeof key !== "string" || key === "") {
        return { _tag: "tool_error", reason: "invalid_call", detail: "missing_param" };
      }
      extraHeaders = { "Idempotency-Key": key };
    }
    const response = await port.request(spec.method, path + query, body, bearer, extraHeaders);
    if (response.status < 200 || response.status >= 300) {
      return {
        _tag: "tool_error",
        reason: "store_error",
        status: response.status,
        detail: response.bodyText.slice(0, ERROR_DETAIL_CAP),
      };
    }
    const page = emitPage(name, response.bodyText, spec.capBytes, cursor);
    if (page._tag === "invalid_page") {
      return { _tag: "tool_error", reason: "invalid_call", detail: page.reason };
    }
    // 계량은 페이지가 이미 공시한 실바이트를 그대로 쓴다 — 한 개념 한 표현 (이중 인코딩 없음).
    const emission: EmissionRecorded = {
      _tag: "EmissionRecorded",
      runId: decl.runId,
      surface: name,
      emittedBytes: page.emittedBytes,
      emittedItems: 1,
      truncatedBytes: page.remainingBytes,
      truncatedItems: page.remainingBytes > 0 ? 1 : 0,
    };
    state = applyRunEvent(state, emission).next;
    return page;
  };

  return { call, state: () => state };
};
