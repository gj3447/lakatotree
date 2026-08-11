/** Scenario MCP-STDIO: 엔트리포인트 실기동 스모크 — 실 프로세스 spawn + NDJSON JSON-RPC 왕복.
 * initialize 버전 에코 · tools/list 53종(51+메타 2) · tools/call 이 유계 ToolPage 반환 ·
 * 도구 오류는 isError 2계층 · 미등록 메서드 -32601. 백엔드는 로컬 fake store. */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createServer, type Server } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const entrypoint = join(here, "..", "..", "src", "entrypoints", "mcp.ts");

let store: Server;
let child: ChildProcessWithoutNullStreams;
const responses = new Map<number, unknown>();
let buffer = "";

const send = (message: unknown): void => {
  child.stdin.write(`${JSON.stringify(message)}\n`);
};

const waitFor = async (id: number, timeoutMs = 5000): Promise<unknown> => {
  const start = Date.now();
  for (;;) {
    const found = responses.get(id);
    if (found !== undefined) return found;
    if (Date.now() - start > timeoutMs) throw new Error(`timeout waiting for id ${id}`);
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
};

beforeAll(async () => {
  store = createServer((req, res) => {
    if (req.url === "/version") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ auth_posture: "open", stale: false }));
      return;
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ echo: req.url, filler: "x".repeat(50) }));
  });
  await new Promise<void>((resolve) => {
    store.listen(0, "127.0.0.1", resolve);
  });
  const address = store.address();
  if (address === null || typeof address === "string") throw new Error("no port");
  child = spawn(process.execPath, [entrypoint], {
    env: {
      ...process.env,
      LAKATOS_STORE_URL: `http://127.0.0.1:${address.port}`,
      LAKATOS_TS_EMISSION_BYTE_CAP: "60000",
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk: Buffer) => {
    buffer += chunk.toString("utf8");
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim() === "") continue;
      const message = JSON.parse(line) as { id?: number };
      if (message.id !== undefined) responses.set(message.id, message);
    }
  });
});

afterAll(async () => {
  child.kill();
  await new Promise<void>((resolve, reject) => {
    store.close((err) => (err ? reject(err) : resolve()));
  });
});

describe("MCP stdio smoke", () => {
  it("initialize — 요청 버전 에코 + tools capability + 알림 무응답", async () => {
    send({
      jsonrpc: "2.0", id: 1, method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "smoke", version: "0" },
      },
    });
    send({ jsonrpc: "2.0", method: "notifications/initialized" });
    const reply = await waitFor(1);
    expect(reply).toMatchObject({
      id: 1,
      result: {
        protocolVersion: "2025-06-18",
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "lakatotree-ts" },
      },
    });
  });

  it("tools/list — 51 도구 + 메타 2종 = 53", async () => {
    send({ jsonrpc: "2.0", id: 2, method: "tools/list" });
    const reply = (await waitFor(2)) as { result: { tools: { name: string }[] } };
    expect(reply.result.tools.length).toBe(53);
    const names = new Set(reply.result.tools.map((t) => t.name));
    expect(names.has("get_tree")).toBe(true);
    expect(names.has("gateway_budget")).toBe(true);
    expect(names.has("gateway_rearm")).toBe(true);
  });

  it("tools/call get_tree — 유계 ToolPage 가 text content 로 반환", async () => {
    send({
      jsonrpc: "2.0", id: 3, method: "tools/call",
      params: { name: "get_tree", arguments: { name: "t1" } },
    });
    const reply = (await waitFor(3)) as {
      result: { isError: boolean; content: { type: string; text: string }[] };
    };
    expect(reply.result.isError).toBe(false);
    const page = JSON.parse(reply.result.content[0]?.text ?? "{}") as Record<string, unknown>;
    expect(page).toMatchObject({ _tag: "ToolPage", surface: "get_tree" });
    expect(page["totalBytes"]).toBeGreaterThan(0);
  });

  it("도구 오류는 isError=true (2계층 오류 모델) — 미등록 도구", async () => {
    send({
      jsonrpc: "2.0", id: 4, method: "tools/call",
      params: { name: "no_such_tool", arguments: {} },
    });
    const reply = (await waitFor(4)) as {
      result: { isError: boolean; content: { text: string }[] };
    };
    expect(reply.result.isError).toBe(true);
    expect(JSON.parse(reply.result.content[0]?.text ?? "{}")).toEqual({
      _tag: "tool_error", reason: "unknown_tool",
    });
  });

  it("gateway_budget — 예산·원장 상태 투영", async () => {
    send({
      jsonrpc: "2.0", id: 5, method: "tools/call",
      params: { name: "gateway_budget", arguments: {} },
    });
    const reply = (await waitFor(5)) as { result: { content: { text: string }[] } };
    const state = JSON.parse(reply.result.content[0]?.text ?? "{}") as Record<string, unknown>;
    expect(state["declared"]).toMatchObject({ _tag: "BudgetDeclared" });
    expect(state["halt"]).toBeNull();
  });

  it("미등록 메서드는 JSON-RPC -32601 (프로토콜 오류 계층)", async () => {
    send({ jsonrpc: "2.0", id: 6, method: "prompts/list" });
    const reply = await waitFor(6);
    expect(reply).toMatchObject({ id: 6, error: { code: -32601 } });
  });
});

describe("READONLY-POSTURE: token_required 스토어 + 무토큰", () => {
  let roStore: Server;
  let roChild: ChildProcessWithoutNullStreams;
  const roResponses = new Map<number, unknown>();
  const roHits: string[] = [];
  let roBuffer = "";

  const roSend = (message: unknown): void => {
    roChild.stdin.write(`${JSON.stringify(message)}\n`);
  };
  const roWait = async (id: number, timeoutMs = 5000): Promise<unknown> => {
    const start = Date.now();
    for (;;) {
      const found = roResponses.get(id);
      if (found !== undefined) return found;
      if (Date.now() - start > timeoutMs) throw new Error(`timeout ro id ${id}`);
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  };

  beforeAll(async () => {
    roStore = createServer((req, res) => {
      roHits.push(`${req.method} ${req.url}`);
      if (req.url === "/version") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ auth_posture: "token_required", stale: false }));
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    });
    await new Promise<void>((resolve) => {
      roStore.listen(0, "127.0.0.1", resolve);
    });
    const address = roStore.address();
    if (address === null || typeof address === "string") throw new Error("no port");
    const childEnv: Record<string, string | undefined> = {
      ...process.env,
      LAKATOS_STORE_URL: `http://127.0.0.1:${address.port}`,
    };
    delete childEnv["LAKATOS_API_TOKEN"];
    roChild = spawn(process.execPath, [entrypoint], { env: childEnv, stdio: ["pipe", "pipe", "pipe"] });
    roChild.stdout.on("data", (chunk: Buffer) => {
      roBuffer += chunk.toString("utf8");
      const lines = roBuffer.split("\n");
      roBuffer = lines.pop() ?? "";
      for (const line of lines) {
        if (line.trim() === "") continue;
        const message = JSON.parse(line) as { id?: number };
        if (message.id !== undefined) roResponses.set(message.id, message);
      }
    });
  });

  afterAll(async () => {
    roChild.kill();
    await new Promise<void>((resolve, reject) => {
      roStore.close((err) => (err ? reject(err) : resolve()));
    });
  });

  it("기동은 막히지 않고 read 는 서빙, write 는 백엔드 미접촉 auth_required", async () => {
    roSend({
      jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "ro", version: "0" } },
    });
    await roWait(1);
    roSend({
      jsonrpc: "2.0", id: 2, method: "tools/call",
      params: { name: "get_tree", arguments: { name: "t" } },
    });
    const read = (await roWait(2)) as { result: { isError: boolean } };
    expect(read.result.isError).toBe(false);
    const hitsBefore = roHits.length;
    roSend({
      jsonrpc: "2.0", id: 3, method: "tools/call",
      params: { name: "add_node", arguments: { name: "t", tag: "n1" } },
    });
    const write = (await roWait(3)) as {
      result: { isError: boolean; content: { text: string }[] };
    };
    expect(write.result.isError).toBe(true);
    expect(JSON.parse(write.result.content[0]?.text ?? "{}")).toMatchObject({
      _tag: "tool_error", reason: "auth_required",
    });
    expect(roHits.length).toBe(hitsBefore); // 백엔드 미접촉
  });
});
