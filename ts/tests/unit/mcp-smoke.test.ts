/** Scenario MCP-STDIO: 엔트리포인트 실기동 스모크 — 실 프로세스 spawn + NDJSON JSON-RPC 왕복.
 * initialize 버전 에코 · 정본에서 유도한 full/read-only tools/list ·
 * tools/call 이 유계 ToolPage 반환 ·
 * 도구 오류는 isError 2계층 · 미등록 메서드 -32601. 백엔드는 로컬 fake store. */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const tsRoot = join(here, "..", "..");
const entrypoint = join(here, "..", "..", "src", "entrypoints", "mcp.ts");
const surface = JSON.parse(
  readFileSync(join(tsRoot, "spec", "tool-surface.v0.json"), "utf8"),
) as { tools: { kind: "read" | "write" | "ops" }[] };
const packageInfo = JSON.parse(
  readFileSync(join(tsRoot, "package.json"), "utf8"),
) as { version: string };
const gatewayMetaToolCount = 2;
const fullToolCount = surface.tools.length + gatewayMetaToolCount;
const readOnlyToolCount = surface.tools.filter((tool) => tool.kind === "read").length
  + gatewayMetaToolCount;

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
        serverInfo: { name: "lakatotree-ts", version: packageInfo.version },
      },
    });
  });

  it("tools/list — 정본 도구 + gateway 메타 도구", async () => {
    send({ jsonrpc: "2.0", id: 2, method: "tools/list" });
    const reply = (await waitFor(2)) as { result: { tools: { name: string }[] } };
    expect(reply.result.tools.length).toBe(fullToolCount);
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

describe("one-shot 파이프: stdin 종료 후에도 in-flight 응답을 드레인하고 종료", () => {
  it("느린 백엔드 + 즉시 stdin.end() → tools/call 응답이 유실되지 않는다", async () => {
    const slowStore = createServer((req, res) => {
      if (req.url === "/version") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ auth_posture: "open", stale: false }));
        return;
      }
      setTimeout(() => {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ slow: true }));
      }, 150);
    });
    await new Promise<void>((resolve) => {
      slowStore.listen(0, "127.0.0.1", resolve);
    });
    const address = slowStore.address();
    if (address === null || typeof address === "string") throw new Error("no port");
    const oneShot = spawn(process.execPath, [entrypoint], {
      env: { ...process.env, LAKATOS_STORE_URL: `http://127.0.0.1:${address.port}` },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let out = "";
    oneShot.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString("utf8");
    });
    oneShot.stdin.write(
      `${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "os", version: "0" } } })}\n` +
      `${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "get_tree", arguments: { name: "t" } } })}\n`,
    );
    oneShot.stdin.end(); // 응답 도착 전 즉시 종료 신호
    const exitCode = await new Promise<number | null>((resolve) => {
      oneShot.on("exit", (code) => resolve(code));
    });
    await new Promise<void>((resolve, reject) => {
      slowStore.close((err) => (err ? reject(err) : resolve()));
    });
    expect(exitCode).toBe(0);
    const ids = out.split("\n").filter((l) => l.trim() !== "")
      .map((l) => (JSON.parse(l) as { id?: number }).id);
    expect(ids).toContain(2); // in-flight 응답이 드레인됐다
  }, 10_000);

  it("in-flight cap을 넘는 요청은 대기 작업을 만들지 않고 즉시 server-busy로 거부한다", async () => {
    let toolCalls = 0;
    const slowStore = createServer((req, res) => {
      if (req.url === "/version") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ auth_posture: "open", stale: false }));
        return;
      }
      toolCalls += 1;
      setTimeout(() => {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ slow: true }));
      }, 100);
    });
    await new Promise<void>((resolve) => {
      slowStore.listen(0, "127.0.0.1", resolve);
    });
    const address = slowStore.address();
    if (address === null || typeof address === "string") throw new Error("no port");
    const oneShot = spawn(process.execPath, [entrypoint], {
      env: {
        ...process.env,
        LAKATOS_STORE_URL: `http://127.0.0.1:${address.port}`,
        LAKATOS_TS_IN_FLIGHT_CAP: "1",
      },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let out = "";
    oneShot.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString("utf8");
    });
    oneShot.stdin.end(
      `${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "get_tree", arguments: { name: "a" } } })}\n` +
      `${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "get_tree", arguments: { name: "b" } } })}\n`,
    );
    const exitCode = await new Promise<number | null>((resolve) => {
      oneShot.on("exit", (code) => resolve(code));
    });
    await new Promise<void>((resolve, reject) => {
      slowStore.close((err) => (err ? reject(err) : resolve()));
    });
    expect(exitCode).toBe(0);
    const replies = out.split("\n").filter((line) => line.trim() !== "")
      .map((line) => JSON.parse(line) as { id: number; result?: unknown; error?: { code: number } });
    expect(replies.find((reply) => reply.id === 1)?.result).toBeDefined();
    expect(replies.find((reply) => reply.id === 2)?.error?.code).toBe(-32000);
    expect(toolCalls).toBe(1);
  }, 10_000);

  it.each([
    { label: "readback 503", status: 503, body: "down" },
    { label: "readback JSON 손상", status: 200, body: "{broken" },
  ])("$label → 무토큰 기동은 fail-closed read-only 표면", async ({ status, body }) => {
    const brokenStore = createServer((_req, res) => {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(body);
    });
    await new Promise<void>((resolve) => {
      brokenStore.listen(0, "127.0.0.1", resolve);
    });
    const address = brokenStore.address();
    if (address === null || typeof address === "string") throw new Error("no port");
    const childEnv: Record<string, string | undefined> = {
      ...process.env,
      LAKATOS_STORE_URL: `http://127.0.0.1:${address.port}`,
    };
    delete childEnv["LAKATOS_API_TOKEN"];
    const oneShot = spawn(process.execPath, [entrypoint], {
      env: childEnv,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let out = "";
    oneShot.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString("utf8");
    });
    oneShot.stdin.end(
      `${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" })}\n` +
      `${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "add_node", arguments: { name: "t", tag: "n" } } })}\n`,
    );
    const exitCode = await new Promise<number | null>((resolve) => {
      oneShot.on("exit", (code) => resolve(code));
    });
    await new Promise<void>((resolve, reject) => {
      brokenStore.close((err) => (err ? reject(err) : resolve()));
    });
    expect(exitCode).toBe(0);
    const replies = out.split("\n").filter((line) => line.trim() !== "")
      .map((line) => JSON.parse(line) as {
        id: number;
        result: { tools?: { name: string }[]; isError?: boolean; content?: { text: string }[] };
      });
    const listed = replies.find((reply) => reply.id === 1)?.result.tools ?? [];
    expect(listed.length).toBe(readOnlyToolCount);
    expect(listed.some((tool) => tool.name === "add_node")).toBe(false);
    const write = replies.find((reply) => reply.id === 2)?.result;
    expect(write?.isError).toBe(true);
    expect(JSON.parse(write?.content?.[0]?.text ?? "{}")).toMatchObject({
      _tag: "tool_error", reason: "auth_required",
    });
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

  it("tools/list도 read-only 표면만 광고한다 — write/ops/local 이름은 숨김", async () => {
    roSend({ jsonrpc: "2.0", id: 4, method: "tools/list" });
    const reply = (await roWait(4)) as { result: { tools: { name: string }[] } };
    const names = reply.result.tools.map((tool) => tool.name);
    expect(names.length).toBe(readOnlyToolCount);
    expect(names).toContain("list_trees");
    expect(names).toContain("gateway_budget");
    expect(names).toContain("gateway_rearm");
    expect(names).not.toContain("add_node");
    expect(names).not.toContain("fsck");
    expect(names).not.toContain("manifest_verify");
    expect(names).not.toContain("longinus_audit");
  });
});
