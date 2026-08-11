/** 게이트웨이 파이프라인 — 함수형 코어(emitPage·applyRunEvent)를 감싸는 얇은 상태 셸.
 * 모든 도구 응답은 ToolPage 경유(무제한 응답이 반환 타입으로 표현 불가), 호출마다
 * EmissionRecorded 실바이트(UTF-8) 계량이 RUN-BUDGET 게이트를 통과한다. 정지 후에는
 * 백엔드 포트 호출 자체가 없다(선차단). 초과를 만든 그 응답은 전달·기재된다(소비는 사실 —
 * 기재 후 정지). 오류 detail 은 [:300] 캡 — mcp_server.py 오류 캡 선례. truncatedBytes 는
 * '이 방출 시점의 미전달 잔여'(offset 이후 보존: emitted+truncated = offset 이후 원본). */
import type { BudgetDeclaration } from "../domain/budget.ts";
import type { EmissionRecorded } from "../domain/emission.ts";
import { emitPage, type ToolPage } from "../domain/page.ts";
import {
  applyRunEvent,
  initialRunState,
  type HaltReport,
  type RunState,
} from "../domain/run.ts";

export interface ToolSpec {
  readonly name: string;
  readonly method: "GET" | "POST" | "PUT" | "DELETE";
  readonly path: string;
  readonly kind: "read" | "write" | "ops";
  readonly capChars: number;
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
  ) => Promise<StoreResponse>;
}

export type CallError = {
  readonly _tag: "invalid_call";
  readonly reason: "missing_param";
};

export type ToolError =
  | { readonly _tag: "tool_error"; readonly reason: "unknown_tool" }
  | { readonly _tag: "tool_error"; readonly reason: "invalid_call"; readonly detail: string }
  | { readonly _tag: "tool_error"; readonly reason: "budget_halted"; readonly report: HaltReport }
  | {
      readonly _tag: "tool_error";
      readonly reason: "store_error";
      readonly status: number;
      readonly detail: string;
    };

export type ToolArgs = Readonly<Record<string, string | number>>;

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

const ERROR_DETAIL_CAP = 300;

export interface Gateway {
  readonly call: (name: string, args: ToolArgs) => Promise<ToolPage | ToolError>;
  readonly state: () => RunState;
}

export const createGateway = (
  specs: readonly ToolSpec[],
  decl: BudgetDeclaration,
  port: StorePort,
  bearer: string | null,
): Gateway => {
  const byName = new Map(specs.map((s) => [s.name, s]));
  const encoder = new TextEncoder();
  let state: RunState = applyRunEvent(initialRunState, decl).next;

  const call = async (name: string, args: ToolArgs): Promise<ToolPage | ToolError> => {
    const spec = byName.get(name);
    if (spec === undefined) {
      return { _tag: "tool_error", reason: "unknown_tool" };
    }
    if (state.halt !== null) {
      return { _tag: "tool_error", reason: "budget_halted", report: state.halt };
    }
    const path = buildPath(spec.path, args);
    if (typeof path !== "string") {
      return { _tag: "tool_error", reason: "invalid_call", detail: path.reason };
    }
    const cursorRaw = args["cursor"];
    const cursor = typeof cursorRaw === "string" ? cursorRaw : "";
    const pathParams = pathParamNames(spec.path);
    const bodyEntries = Object.entries(args).filter(
      ([key]) => !pathParams.has(key) && key !== "cursor",
    );
    const body =
      spec.method === "GET" ? null : JSON.stringify(Object.fromEntries(bodyEntries));
    const response = await port.request(spec.method, path, body, bearer);
    if (response.status < 200 || response.status >= 300) {
      return {
        _tag: "tool_error",
        reason: "store_error",
        status: response.status,
        detail: response.bodyText.slice(0, ERROR_DETAIL_CAP),
      };
    }
    const page = emitPage(name, response.bodyText, spec.capChars, cursor);
    if (page._tag === "invalid_page") {
      return { _tag: "tool_error", reason: "invalid_call", detail: page.reason };
    }
    const remainderText = response.bodyText.slice(page.offsetChars + page.body.length);
    const emission: EmissionRecorded = {
      _tag: "EmissionRecorded",
      runId: decl.runId,
      surface: name,
      emittedBytes: encoder.encode(page.body).length,
      emittedItems: 1,
      truncatedBytes: encoder.encode(remainderText).length,
      truncatedItems: page.remainingChars > 0 ? 1 : 0,
    };
    state = applyRunEvent(state, emission).next;
    return page;
  };

  return { call, state: () => state };
};
