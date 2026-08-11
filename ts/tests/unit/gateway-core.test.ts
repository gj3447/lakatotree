/** Scenario GATEWAY-CORE: 도구 호출 파이프라인 — 모든 응답은 ToolPage 경유(유계 강제),
 * 호출마다 EmissionRecorded 실바이트 계량이 RUN-BUDGET 게이트를 통과하며, 정지 후에는
 * 백엔드 호출 자체가 일어나지 않는다 (돈 나가기 전에 차단). 함수형 코어 + 얇은 상태 셸. */
import { describe, expect, it } from "vitest";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import type { StorePort, StoreResponse } from "../../src/application/gateway.ts";
import { buildPath, createGateway, type ToolSpec } from "../../src/application/gateway.ts";

const decl: BudgetDeclaration = {
  _tag: "BudgetDeclared", runId: "gw1",
  callCap: 100, tokenCap: 1_000_000, wallMsCap: 3_600_000,
  emissionByteCap: 60_000, emissionItemCap: 500,
};

const SPECS: readonly ToolSpec[] = [
  { name: "get_tree", method: "GET", path: "/api/tree/{name}", kind: "read", capChars: 8 },
  { name: "add_node", method: "POST", path: "/api/tree/{tree}/nodes", kind: "write", capChars: 100 },
];

const fakePort = (
  handler: (method: string, path: string, body: string | null) => StoreResponse,
) => {
  const calls: { method: string; path: string; body: string | null; bearer: string | null }[] = [];
  const port: StorePort = {
    request: (method, path, body, bearer) => {
      calls.push({ method, path, body, bearer });
      return Promise.resolve(handler(method, path, body));
    },
  };
  return { port, calls };
};

describe("buildPath", () => {
  it("경로 템플릿 치환 + URL 인코딩", () => {
    expect(buildPath("/api/tree/{name}", { name: "한글 트리" })).toBe(
      "/api/tree/%ED%95%9C%EA%B8%80%20%ED%8A%B8%EB%A6%AC",
    );
  });

  it("guard_defect: 누락 파라미터는 fail-closed 오류 값", () => {
    expect(buildPath("/api/tree/{name}", {})).toEqual({
      _tag: "invalid_call", reason: "missing_param",
    });
  });
});

describe("gateway pipeline", () => {
  it("guard_mechanism: 응답은 ToolPage — cap 강제 + 보존 공시 + 커서 재개", async () => {
    const { port } = fakePort(() => ({ status: 200, bodyText: "0123456789ABCDEF" }));
    const gateway = createGateway(SPECS, decl, port, null);
    const first = await gateway.call("get_tree", { name: "t" });
    expect(first).toMatchObject({
      _tag: "ToolPage", body: "01234567", nextCursor: "8", totalChars: 16,
    });
    const second = await gateway.call("get_tree", { name: "t", cursor: "8" });
    expect(second).toMatchObject({ _tag: "ToolPage", body: "89ABCDEF", nextCursor: "" });
  });

  it("guard_mechanism: 호출마다 방출 계량 — 실바이트(UTF-8)가 원장에 쌓인다", async () => {
    const { port } = fakePort(() => ({ status: 200, bodyText: "가나다라마바사아자차" }));
    const gateway = createGateway(SPECS, decl, port, null);
    await gateway.call("get_tree", { name: "t" });
    const state = gateway.state();
    expect(state.calls).toBe(1);
    // 페이지 body = 앞 8자 = UTF-8 24바이트, 잘림 = 2자 = 6바이트
    expect(state.emission.emittedBytes).toBe(24);
    expect(state.emission.truncatedBytes).toBe(6);
  });

  it("guard_defect: 예산 정지 후에는 백엔드 호출 자체가 없다 — 돈 나가기 전 차단", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "x" }));
    const tight = { ...decl, callCap: 1 };
    const gateway = createGateway(SPECS, tight, port, null);
    await gateway.call("get_tree", { name: "a" });
    await gateway.call("get_tree", { name: "b" }); // 2번째 계량이 callCap 초과 → 기재 후 정지
    const before = calls.length;
    const refused = await gateway.call("get_tree", { name: "c" });
    expect(refused).toMatchObject({
      _tag: "tool_error", reason: "budget_halted",
      report: { _tag: "cap_halt", reason: "call_cap_exceeded" },
    });
    expect(calls.length).toBe(before); // 포트 미호출
  });

  it("write 도구: 경로 파라미터 외 인자를 JSON body 로, Bearer 는 주입 시 전달", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "{\"ok\":true}" }));
    const gateway = createGateway(SPECS, decl, port, "tok-1");
    await gateway.call("add_node", { tree: "t1", tag: "n1", comment: "c" });
    expect(calls[0]).toEqual({
      method: "POST", path: "/api/tree/t1/nodes",
      body: JSON.stringify({ tag: "n1", comment: "c" }),
      bearer: "tok-1",
    });
  });

  it("guard_defect: 미등록 도구·백엔드 오류는 닫힌 오류 값 (throw 없음)", async () => {
    const { port } = fakePort(() => ({ status: 500, bodyText: "boom" }));
    const gateway = createGateway(SPECS, decl, port, null);
    expect(await gateway.call("nope", {})).toEqual({
      _tag: "tool_error", reason: "unknown_tool",
    });
    expect(await gateway.call("get_tree", { name: "t" })).toMatchObject({
      _tag: "tool_error", reason: "store_error", status: 500,
    });
  });

  it("스토어 오류 detail 도 유계 — 오류 경로로 무제한 방출 불가", async () => {
    const { port } = fakePort(() => ({ status: 500, bodyText: "e".repeat(10_000) }));
    const gateway = createGateway(SPECS, decl, port, null);
    const error = await gateway.call("get_tree", { name: "t" });
    expect(error).toMatchObject({ _tag: "tool_error", reason: "store_error" });
    if (error._tag === "tool_error" && error.reason === "store_error") {
      expect(error.detail.length).toBeLessThanOrEqual(300);
    }
  });
});
