/** Scenario STORE-HTTP: Effect StoreClient Layer의 실 HTTP 왕복 (fake 재구현 아님).
 * Bearer 는 주입 시에만, GET 은 body 없음, 상태·본문을 가감 없이 반환 (판정은 application 몫). */
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { Effect, Either } from "effect";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { httpStoreLayer } from "../../src/adapters/storehttp.ts";
import { requestStore } from "../../src/application/store.ts";

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
      if (req.url === "/api/slow") {
        setTimeout(() => {
          res.writeHead(200, { "content-type": "application/json" });
          res.end("{}");
        }, 250);
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

describe("httpStoreLayer", () => {
  it("guard_mechanism: GET 왕복 — 상태·본문 그대로, body 없음, Bearer 없음", async () => {
    const response = await Effect.runPromise(requestStore({
      method: "GET", path: "/api/tree/t1", body: null, bearer: null, timeoutMs: 30_000,
    }).pipe(Effect.provide(httpStoreLayer(baseUrl))));
    expect(response.status).toBe(200);
    expect(response.bodyText).toBe(JSON.stringify({ echo: "/api/tree/t1", method: "GET" }));
    const last = seen.at(-1);
    expect(last).toMatchObject({ method: "GET", url: "/api/tree/t1", auth: undefined, body: "" });
  });

  it("guard_mechanism: POST — JSON body + Bearer 전달", async () => {
    await Effect.runPromise(requestStore({
      method: "POST",
      path: "/api/trees",
      body: JSON.stringify({ name: "t" }),
      bearer: "tok-9",
      timeoutMs: 30_000,
    }).pipe(Effect.provide(httpStoreLayer(baseUrl))));
    const last = seen.at(-1);
    expect(last).toMatchObject({
      method: "POST",
      url: "/api/trees",
      auth: "Bearer tok-9",
      body: JSON.stringify({ name: "t" }),
    });
  });

  it("5xx 도 값으로 반환 — throw 없음 (판정은 application 몫)", async () => {
    const response = await Effect.runPromise(requestStore({
      method: "GET", path: "/api/boom", body: null, bearer: null, timeoutMs: 30_000,
    }).pipe(Effect.provide(httpStoreLayer(baseUrl))));
    expect(response).toEqual({ status: 500, bodyText: "kaboom" });
  });

  it("유계 timeout — status=0 sentinel이 아니라 unknown typed failure", async () => {
    const result = await Effect.runPromise(Effect.either(requestStore({
      method: "GET", path: "/api/slow", body: null, bearer: null, timeoutMs: 25,
    }).pipe(Effect.provide(httpStoreLayer(baseUrl)))));
    expect(Either.isLeft(result)).toBe(true);
    if (Either.isLeft(result)) {
      expect(result.left).toEqual({
        _tag: "store_transport_error",
        reason: "timeout",
        outcome: "unknown",
        detail: "request_timeout",
      });
    }
  });
});
