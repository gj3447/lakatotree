/** lakatotree-ts MCP stdio 서버 — Python mcp_server.py 51도구의 유계 게이트웨이 교체.
 * 프로토콜: newline-delimited JSON-RPC 2.0, UTF-8 (recon 실증: mcp/server/stdio.py:63-81 —
 * Content-Length 프레이밍 아님). stdout 은 프로토콜 전용, 로그는 stderr.
 * 2계층 오류 모델: 도구 실행 실패 = result.isError:true / 프로토콜 오류 = JSON-RPC error(-32601).
 * 운용: 기본 로컬 MCP 프로세스는 TS로 컷오버. HTTP 스토어는 레거시 오라클 어댑터이며 전체
 * Python 파리티는 아직 주장하지 않는다. auth posture 확인 전에는 fail-closed read-only 표면.
 * 예산 캡은 env 로만 공급(도구 인자 아님 — self-raisable 봉쇄, 리스크 #5). 정지 후 복구는
 * gateway_rearm(새 runId 발급, stderr 원장 기재)로 — 프로세스 재시작 불요. */
import { createInterface } from "node:readline";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import type { Gateway, GatewayPosture, ToolSpec } from "../application/gateway.ts";
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
const packageInfo = JSON.parse(
  readFileSync(join(here, "..", "..", "package.json"), "utf8"),
) as { version: string };

const env = process.env;
const baseUrl = env["LAKATOS_STORE_URL"] ?? "http://127.0.0.1:55170";
const bearer = env["LAKATOS_API_TOKEN"] ?? null;

const intEnv = (key: string, fallback: number): number => {
  const raw = env[key];
  if (raw === undefined || raw === "") return fallback; // Number("")===0 오독 방지
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : fallback;
};

const positiveIntEnv = (key: string, fallback: number): number => {
  const value = intEnv(key, fallback);
  return value > 0 ? value : fallback;
};

const inFlightCap = positiveIntEnv("LAKATOS_TS_IN_FLIGHT_CAP", 8);

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

const port = httpStorePort(baseUrl, positiveIntEnv("LAKATOS_STORE_CALL_TIMEOUT_MS", 30_000));
const bootPort = httpStorePort(baseUrl, positiveIntEnv("LAKATOS_STORE_BOOT_TIMEOUT_MS", 5_000));
let armCount = 0;
let gateway: Gateway;
let posture: GatewayPosture = "read_only";

const arm = (): string => {
  armCount += 1;
  const runId = `mcp-${process.pid}-r${armCount}`;
  const created = createGateway(surface.tools, declFor(runId), port, bearer, posture);
  if ("_tag" in created) {
    log(`fatal: invalid budget declaration (${created.reason}) — fail-closed`);
    process.exit(1);
  }
  gateway = created;
  log(`armed runId=${runId} store=${baseUrl} posture=${posture}`);
  return runId;
};

/** 기동 readback — /version 의 auth_posture·stale 을 stderr 로 공시. 기본은 read-only이고
 * 명시적 open 또는 token_required+토큰일 때만 full 승격한다. 실패·손상·미지 posture는
 * read-only 유지: kind:read 만 서빙하고 write/ops는 로컬 auth_required 차단. */
const bootReadback = async (): Promise<void> => {
  const version = await bootPort.request("GET", "/version", null, bearer);
  if (version.status !== 200) {
    log(`warn: /version readback failed (status ${version.status}) — store may be down`);
    return;
  }
  try {
    const info = JSON.parse(version.bodyText) as Record<string, unknown>;
    const authPosture = info["auth_posture"];
    log(`store /version: auth_posture=${String(authPosture)} stale=${String(info["stale"])}`);
    if (authPosture === "open" || (authPosture === "token_required" && bearer !== null)) {
      posture = "full";
    } else if (authPosture === "token_required" && bearer === null) {
      log("read-only 기동: store token_required + LAKATOS_API_TOKEN 부재 — write/ops 는 auth_required 로컬 차단");
    } else {
      log("warn: unknown auth_posture — fail-closed read-only 유지");
    }
  } catch {
    log("warn: /version body unparseable");
  }
};

const toolList = () => [
  ...(posture === "read_only"
    ? surface.tools.filter((tool) => tool.kind === "read")
    : surface.tools
  ).map((tool) => ({
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

const requestIdOf = (line: string): number | string | undefined => {
  try {
    const id = (JSON.parse(line) as JsonRpcIn).id;
    return typeof id === "number" || typeof id === "string" ? id : undefined;
  } catch {
    return undefined;
  }
};

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
        serverInfo: { name: "lakatotree-ts", version: packageInfo.version },
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
    write({ jsonrpc: "2.0", id, result: { tools: toolList() } });
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
  arm(); // posture 확정 후 무장 — read-only 여부가 게이트웨이에 각인된다
  // one-shot 파이프 지원: stdin 종료 시 in-flight 응답을 전부 드레인한 뒤 종료
  // (드레인 없이 exit 하면 느린 백엔드 호출의 응답이 조용히 유실된다 — 제3자 리뷰 노트 채택).
  let inFlight = 0;
  let stdinClosed = false;
  const exitIfDrained = (): void => {
    if (stdinClosed && inFlight === 0) process.exit(0);
  };
  const rl = createInterface({ input: process.stdin, terminal: false });
  rl.on("line", (line) => {
    if (inFlight >= inFlightCap) {
      const id = requestIdOf(line);
      if (id !== undefined) {
        write({ jsonrpc: "2.0", id, error: { code: -32000, message: "Server busy" } });
      }
      return;
    }
    inFlight += 1;
    void handleLine(line).finally(() => {
      inFlight -= 1;
      exitIfDrained();
    });
  });
  rl.on("close", () => {
    stdinClosed = true;
    exitIfDrained();
  });
});
