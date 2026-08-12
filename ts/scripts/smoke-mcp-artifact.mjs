import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { resolve } from "node:path";

const entrypoint = resolve(process.argv[2] ?? "dist/entrypoints/mcp.js");
const child = spawn(process.execPath, [entrypoint], {
  env: {
    ...process.env,
    LAKATOS_STORE_URL: "http://127.0.0.1:1",
    LAKATOS_STORE_BOOT_TIMEOUT_MS: "100",
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
  })}\n${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" })}\n`,
);

const timeout = setTimeout(() => child.kill("SIGKILL"), 5_000);
const exitCode = await new Promise((resolveExit) => {
  child.once("exit", (code) => resolveExit(code));
});
clearTimeout(timeout);

assert.equal(exitCode, 0, `built MCP exited ${String(exitCode)}\n${stderr}`);
const replies = stdout
  .split("\n")
  .filter((line) => line.trim() !== "")
  .map((line) => JSON.parse(line));
const initialized = replies.find((reply) => reply.id === 1);
const listed = replies.find((reply) => reply.id === 2);
assert.equal(initialized?.result?.serverInfo?.name, "lakatotree-ts");
assert.equal(initialized?.result?.protocolVersion, "2025-06-18");
assert.ok(Array.isArray(listed?.result?.tools));
assert.ok(listed.result.tools.some((tool) => tool.name === "get_tree"));
assert.ok(!listed.result.tools.some((tool) => tool.name === "add_node"));
process.stdout.write(`artifact smoke ok: ${entrypoint}\n`);
