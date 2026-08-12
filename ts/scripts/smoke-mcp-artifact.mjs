import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { dirname, resolve } from "node:path";

const entrypoint = resolve(process.argv[2] ?? "dist/entrypoints/mcp.js");
const artifactRoot = resolve(dirname(entrypoint), "../..");
let toolCalls = 0;
const store = createServer((request, response) => {
  if (request.url === "/version") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ auth_posture: "open", stale: false }));
    return;
  }
  if (request.url === "/api/tree/smoke") {
    toolCalls += 1;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ name: "smoke", verified: true }));
    return;
  }
  response.writeHead(404, { "content-type": "text/plain" });
  response.end("not found");
});
await new Promise((resolveListen) => store.listen(0, "127.0.0.1", resolveListen));
const address = store.address();
assert.ok(address !== null && typeof address !== "string");

const child = spawn(process.execPath, ["--no-strip-types", entrypoint], {
  cwd: artifactRoot,
  env: {
    ...process.env,
    LAKATOS_STORE_URL: `http://127.0.0.1:${address.port}`,
    LAKATOS_STORE_BOOT_TIMEOUT_MS: "1000",
  },
  stdio: ["pipe", "pipe", "pipe"],
});

let stdout = "";
let stderr = "";
child.stdout.on("data", (chunk) => {
  stdout += chunk.toString("utf8");
});
child.stderr.on("data", (chunk) => {
  stderr += chunk.toString("utf8");
});

child.stdin.end(
  `${JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "artifact-smoke", version: "1" },
    },
  })}\n${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" })}\n${JSON.stringify({
    jsonrpc: "2.0",
    id: 3,
    method: "tools/call",
    params: { name: "get_tree", arguments: { name: "smoke" } },
  })}\n`,
);

const timeout = setTimeout(() => child.kill("SIGKILL"), 5_000);
const exitCode = await new Promise((resolveExit) => {
  child.once("exit", (code) => resolveExit(code));
});
clearTimeout(timeout);
await new Promise((resolveClose, rejectClose) => {
  store.close((error) => error === undefined ? resolveClose() : rejectClose(error));
});

assert.equal(exitCode, 0, `built MCP exited ${String(exitCode)}\n${stderr}`);
const replies = stdout
  .split("\n")
  .filter((line) => line.trim() !== "")
  .map((line) => JSON.parse(line));
const initialized = replies.find((reply) => reply.id === 1);
const listed = replies.find((reply) => reply.id === 2);
const called = replies.find((reply) => reply.id === 3);
assert.equal(initialized?.result?.serverInfo?.name, "lakatotree-ts");
assert.equal(initialized?.result?.protocolVersion, "2025-06-18");
assert.ok(Array.isArray(listed?.result?.tools));
assert.ok(listed.result.tools.some((tool) => tool.name === "get_tree"));
assert.ok(listed.result.tools.some((tool) => tool.name === "add_node"));
assert.equal(called?.result?.isError, false);
const page = JSON.parse(called?.result?.content?.[0]?.text ?? "null");
assert.equal(page?._tag, "ToolPage");
assert.equal(toolCalls, 1);
process.stdout.write(`artifact smoke ok: ${entrypoint}\n`);
