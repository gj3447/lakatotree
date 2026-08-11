/** Scenario STORE-HTTP: StorePort 의 실 HTTP 어댑터 — 로컬 실서버 왕복 (fake 재구현 아님).
 * Bearer 는 주입 시에만, GET 은 body 없음, 상태·본문을 가감 없이 반환 (판정은 application 몫). */
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { httpStorePort } from "../../src/adapters/storehttp.ts";

interface Seen {
  method: string | undefined;
  url: string | undefined;
  auth: string | undefined;
  body: string;
}

let server: Server;
let baseUrl = "";
const seen: Seen[] = [];

beforeAll(async () => {
  server = createServer((req: IncomingMessage, res: ServerResponse) => {
    let body = "";
    req.on("data", (chunk: Buffer) => {
      body += chunk.toString("utf8");
    });
    req.on("end", () => {
      seen.push({
        method: req.method,
        url: req.url,
        auth: req.headers.authorization,
        body,
      });
      if (req.url === "/api/boom") {
        res.writeHead(500, { "content-type": "text/plain" });
        res.end("kaboom");
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ echo: req.url, method: req.method }));
    });
  });
  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("no port");
  baseUrl = `http://127.0.0.1:${address.port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve, reject) => {
    server.close((err) => (err ? reject(err) : resolve()));
  });
});

describe("httpStorePort", () => {
  it("guard_mechanism: GET 왕복 — 상태·본문 그대로, body 없음, Bearer 없음", async () => {
    const port = httpStorePort(baseUrl);
    const response = await port.request("GET", "/api/tree/t1", null, null);
    expect(response.status).toBe(200);
    expect(response.bodyText).toBe(JSON.stringify({ echo: "/api/tree/t1", method: "GET" }));
    const last = seen.at(-1);
    expect(last).toMatchObject({ method: "GET", url: "/api/tree/t1", auth: undefined, body: "" });
  });

  it("guard_mechanism: POST — JSON body + Bearer 전달", async () => {
    const port = httpStorePort(baseUrl);
    await port.request("POST", "/api/trees", JSON.stringify({ name: "t" }), "tok-9");
    const last = seen.at(-1);
    expect(last).toMatchObject({
      method: "POST",
      url: "/api/trees",
      auth: "Bearer tok-9",
      body: JSON.stringify({ name: "t" }),
    });
  });

  it("5xx 도 값으로 반환 — throw 없음 (판정은 application 몫)", async () => {
    const port = httpStorePort(baseUrl);
    const response = await port.request("GET", "/api/boom", null, null);
    expect(response).toEqual({ status: 500, bodyText: "kaboom" });
  });
});
