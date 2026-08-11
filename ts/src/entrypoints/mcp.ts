/** lakatotree-ts MCP stdio 서버 — Python mcp_server.py 51도구의 유계 게이트웨이 교체.
 * 프로토콜: newline-delimited JSON-RPC 2.0, UTF-8 (recon 실증: mcp/server/stdio.py:63-81 —
 * Content-Length 프레이밍 아님). stdout 은 프로토콜 전용, 로그는 stderr.
 * 2계층 오류 모델: 도구 실행 실패 = result.isError:true / 프로토콜 오류 = JSON-RPC error(-32601).
 * 운용: 병렬 이름(lakatotree-ts)으로 섀도 등록 → 무발산 확인 후 이름 스왑 (recon 리스크 #8).
 * 예산 캡은 env 로만 공급(도구 인자 아님 — self-raisable 봉쇄, 리스크 #5). 정지 후 복구는
 * gateway_rearm(새 runId 발급, stderr 원장 기재)로 — 프로세스 재시작 불요. */
import { createInterface } from "node:readline";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import type { Gateway, ToolSpec } from "../application/gateway.ts";
import { createGateway, type ToolArgs } from "../application/gateway.ts";
import { httpStorePort } from "../adapters/storehttp.ts";
import type { BudgetDeclaration } from "../domain/budget.ts";

interface SurfaceTool extends ToolSpec {
  readonly params: string;
  readonly note: string;
}

const here = dirname(fileURLToPath(import.meta.url));
const surface = JSON.parse(
  readFileSync(join(here, "..", "..", "spec", "tool-surface.v0.json"), "utf8"),
) as { count: number; tools: SurfaceTool[] };

const env = process.env;
const baseUrl = env["LAKATOS_STORE_URL"] ?? "http://127.0.0.1:55170";
const bearer = env["LAKATOS_API_TOKEN"] ?? null;

const intEnv = (key: string, fallback: number): number => {
  const raw = env[key];
  if (raw === undefined || raw === "") return fallback; // Number("")===0 오독 방지
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : fallback;
};

const log = (message: string): void => {
  process.stderr.write(`[lakatotree-ts] ${message}\n`);
};

const write = (message: unknown): void => {
  process.stdout.write(`${JSON.stringify(message)}\n`);
};

const declFor = (runId: string): BudgetDeclaration => ({
  _tag: "BudgetDeclared",
  runId,
  callCap: intEnv("LAKATOS_TS_CALL_CAP", 500),
  // tokenCap·wallMsCap 은 게이트웨이 경로에서 계량 불가(LLM 토큰·벽시계는 하네스 몫 —
  // spec not_mechanized 공시). 선언은 정직하게 사실상 무제한.
  tokenCap: intEnv("LAKATOS_TS_TOKEN_CAP", 1_000_000_000_000),
  wallMsCap: intEnv("LAKATOS_TS_WALL_MS_CAP", 1_000_000_000_000),
  emissionByteCap: intEnv("LAKATOS_TS_EMISSION_BYTE_CAP", 60_000),
  emissionItemCap: intEnv("LAKATOS_TS_EMISSION_ITEM_CAP", 500),
});

const port = httpStorePort(baseUrl);
let armCount = 0;
let gateway: Gateway;

const arm = (): string => {
  armCount += 1;
  const runId = `mcp-${process.pid}-r${armCount}`;
  const created = createGateway(surface.tools, declFor(runId), port, bearer);
  if ("_tag" in created) {
    log(`fatal: invalid budget declaration (${created.reason}) — fail-closed`);
    process.exit(1);
  }
  gateway = created;
  log(`armed runId=${runId} store=${baseUrl}`);
  return runId;
};
arm();

/** 기동 readback — /version 의 auth_posture·stale 을 stderr 로 공시.
 * token_required 인데 토큰 부재면 기동 거부 (fail-closed, recon 리스크 #6). */
const bootReadback = async (): Promise<void> => {
  const version = await port.request("GET", "/version", null, bearer);
  if (version.status !== 200) {
    log(`warn: /version readback failed (status ${version.status}) — store may be down`);
    return;
  }
  try {
    const info = JSON.parse(version.bodyText) as Record<string, unknown>;
    log(`store /version: auth_posture=${String(info["auth_posture"])} stale=${String(info["stale"])}`);
    if (info["auth_posture"] === "token_required" && bearer === null) {
      log("fatal: store requires Bearer but LAKATOS_API_TOKEN is unset — fail-closed");
      process.exit(1);
    }
  } catch {
    log("warn: /version body unparseable");
  }
};

const TOOL_LIST = [
  ...surface.tools.map((tool) => ({
    name: tool.name,
    description: `${tool.method} ${tool.path} — ${tool.params}`.slice(0, 400),
    inputSchema: { type: "object" as const },
  })),
  {
    name: "gateway_budget",
    description: "게이트웨이 예산·3평면 원장 상태 조회 (RunState 투영)",
    inputSchema: { type: "object" as const },
  },
  {
    name: "gateway_rearm",
    description: "정지된 게이트웨이 재무장 — 새 runId 발급 (이전 halt 보고 동봉, stderr 기재)",
    inputSchema: { type: "object" as const },
  },
];

const textResult = (payload: unknown, isError: boolean) => ({
  content: [{ type: "text" as const, text: JSON.stringify(payload) }],
  isError,
});

const sanitizeArgs = (raw: unknown): ToolArgs | null => {
  if (raw === undefined || raw === null) return {};
  if (typeof raw !== "object" || Array.isArray(raw)) return null;
  const out: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      out[key] = value;
    } else {
      return null;
    }
  }
  return out;
};

const handleCall = async (params: unknown): Promise<unknown> => {
  const p = (params ?? {}) as { name?: unknown; arguments?: unknown };
  const name = typeof p.name === "string" ? p.name : "";
  if (name === "gateway_budget") {
    const state = gateway.state();
    return textResult(
      {
        declared: state.declared,
        calls: state.calls,
        emission: state.emission,
        token: state.budget.token,
        compute: state.budget.compute,
        halt: state.halt,
      },
      false,
    );
  }
  if (name === "gateway_rearm") {
    const previousHalt = gateway.state().halt;
    const runId = arm();
    log(`rearm: previous halt=${JSON.stringify(previousHalt)}`);
    return textResult({ rearmed: true, runId, previous_halt: previousHalt }, false);
  }
  const args = sanitizeArgs(p.arguments);
  if (args === null) {
    return textResult(
      { _tag: "tool_error", reason: "invalid_call", detail: "arguments_must_be_flat_primitives" },
      true,
    );
  }
  const result = await gateway.call(name, args);
  return textResult(result, result._tag === "tool_error");
};

interface JsonRpcIn {
  readonly id?: number | string;
  readonly method?: string;
  readonly params?: unknown;
}

const handleLine = async (line: string): Promise<void> => {
  if (line.trim() === "") return;
  let message: JsonRpcIn;
  try {
    message = JSON.parse(line) as JsonRpcIn;
  } catch {
    log("warn: unparseable line dropped");
    return;
  }
  const { id, method, params } = message;
  if (method === "initialize") {
    const requested = (params as { protocolVersion?: unknown } | undefined)?.protocolVersion;
    write({
      jsonrpc: "2.0",
      id,
      result: {
        // 요청 버전 에코 — 클라이언트는 자기 미지원 버전을 받으면 세션을 끊는다 (recon 실증)
        protocolVersion: typeof requested === "string" ? requested : "2025-06-18",
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "lakatotree-ts", version: "0.1.0" },
      },
    });
    return;
  }
  if (method !== undefined && method.startsWith("notifications/")) {
    return; // 알림엔 절대 응답하지 않는다
  }
  if (method === "ping") {
    write({ jsonrpc: "2.0", id, result: {} });
    return;
  }
  if (method === "tools/list") {
    write({ jsonrpc: "2.0", id, result: { tools: TOOL_LIST } });
    return;
  }
  if (method === "tools/call") {
    write({ jsonrpc: "2.0", id, result: await handleCall(params) });
    return;
  }
  if (id !== undefined) {
    write({ jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } });
  }
};

void bootReadback().then(() => {
  const rl = createInterface({ input: process.stdin, terminal: false });
  rl.on("line", (line) => {
    void handleLine(line);
  });
  rl.on("close", () => {
    process.exit(0);
  });
});
