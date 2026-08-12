/** Scenario GATEWAY-CORE: 도구 호출 파이프라인 — 모든 응답은 ToolPage 경유(유계 강제),
 * 호출마다 EmissionRecorded 실바이트 계량이 RUN-BUDGET 게이트를 통과하며, 정지 후에는
 * 백엔드 호출 자체가 일어나지 않는다 (돈 나가기 전에 차단). 무효 예산 선언은 게이트웨이
 * 자체를 만들지 않는다 (fail-closed 기동 — 무예산 fail-open 봉쇄). */
import { describe, expect, it } from "vitest";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import type { Gateway, StorePort, StoreResponse, ToolSpec } from "../../src/application/gateway.ts";
import { buildPath, createGateway } from "../../src/application/gateway.ts";

const decl: BudgetDeclaration = {
  _tag: "BudgetDeclared", runId: "gw1",
  callCap: 100, tokenCap: 1_000_000, wallMsCap: 3_600_000,
  emissionByteCap: 60_000, emissionItemCap: 500,
};

const SPECS: readonly ToolSpec[] = [
  { name: "get_tree", method: "GET", path: "/api/tree/{name}", kind: "read", bodyMode: "none", capBytes: 8 },
  { name: "critique", method: "POST", path: "/api/tree/{tree}/critique", kind: "write", bodyMode: "flat", capBytes: 100 },
  { name: "run_cycle", method: "POST", path: "/api/tree/{name}/cycle", kind: "write", bodyMode: "spec_json", capBytes: 100 },
  { name: "longinus_audit", method: "LOCAL", path: "LOCAL", kind: "local", bodyMode: "local", capBytes: 100 },
  {
    name: "fsck", method: "GET", path: "/api/ops/fsck", kind: "ops", bodyMode: "none", capBytes: 100,
    query: [{ name: "tree", mode: "omit_empty" }, { name: "emit_skiplist", mode: "one_flag" }],
  },
  {
    name: "delete_tree", method: "DELETE", path: "/api/tree/{name}", kind: "write", bodyMode: "none",
    capBytes: 100, query: [{ name: "cascade", mode: "true_only" }], idempotencyHeader: true,
  },
  {
    name: "leaderboard", method: "GET", path: "/api/leaderboard", kind: "read", bodyMode: "none",
    capBytes: 100,
    query: [
      { name: "trees", argName: "trees_csv", mode: "required" },
      { name: "snapshot", mode: "bool_always" },
    ],
  },
  {
    name: "paradigm", method: "GET", path: "/api/paradigm", kind: "read", bodyMode: "none",
    capBytes: 100,
    query: [
      { name: "incumbent", mode: "required" },
      { name: "rivals", argName: "rivals_csv", mode: "required" },
    ],
  },
];

const mustGateway = (g: ReturnType<typeof createGateway>): Gateway => {
  if ("_tag" in g) throw new Error(`gateway not created: ${g.reason}`);
  return g;
};

const fakePort = (
  handler: (method: string, path: string, body: string | null) => StoreResponse,
) => {
  const calls: {
    method: string; path: string; body: string | null; bearer: string | null;
    extraHeaders?: Readonly<Record<string, string>>;
  }[] = [];
  const port: StorePort = {
    request: (method, path, body, bearer, extraHeaders) => {
      calls.push(
        extraHeaders === undefined
          ? { method, path, body, bearer }
          : { method, path, body, bearer, extraHeaders },
      );
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
  it("guard_defect: 무효 선언(빈 runId·음수 캡)은 게이트웨이를 만들지 않는다 — fail-closed 기동", () => {
    const { port } = fakePort(() => ({ status: 200, bodyText: "x" }));
    expect(createGateway(SPECS, { ...decl, runId: "" }, port, null)).toEqual({
      _tag: "invalid_declaration", reason: "empty_run_id",
    });
    expect(createGateway(SPECS, { ...decl, callCap: -1 }, port, null)).toEqual({
      _tag: "invalid_declaration", reason: "negative_or_non_integer_cap",
    });
  });

  it("guard_mechanism: 응답은 ToolPage — 바이트 cap 강제 + 보존 공시 + 커서 재개", async () => {
    const { port } = fakePort(() => ({ status: 200, bodyText: "0123456789ABCDEF" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    const first = await gateway.call("get_tree", { name: "t" });
    expect(first).toMatchObject({
      _tag: "ToolPage", body: "01234567", nextCursor: "8", totalBytes: 16,
    });
    const second = await gateway.call("get_tree", { name: "t", cursor: "8" });
    expect(second).toMatchObject({ _tag: "ToolPage", body: "89ABCDEF", nextCursor: "" });
  });

  it("guard_mechanism: 호출마다 방출 계량 — 페이지 공시 실바이트가 그대로 원장에 쌓인다", async () => {
    const { port } = fakePort(() => ({ status: 200, bodyText: "가나다라마" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    await gateway.call("get_tree", { name: "t" });
    const state = gateway.state();
    expect(state.calls).toBe(1);
    // cap 8B → body '가나' = 6B 방출, 잔여 '다라마' = 9B 잘림 공시
    expect(state.emission.emittedBytes).toBe(6);
    expect(state.emission.truncatedBytes).toBe(9);
  });

  it("guard_defect: 예산 정지 후에는 백엔드 호출 자체가 없다 — 돈 나가기 전 차단", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "xyzw" }));
    const tight = { ...decl, callCap: 1 };
    const gateway = mustGateway(createGateway(SPECS, tight, port, null));
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

  it("동시 호출도 직렬로 예산을 소비해 call cap 뒤의 포트 호출을 막는다", async () => {
    const releases: Array<() => void> = [];
    let active = 0;
    let maxActive = 0;
    let portCalls = 0;
    const port: StorePort = {
      request: () => new Promise<StoreResponse>((resolve) => {
        portCalls += 1;
        active += 1;
        maxActive = Math.max(maxActive, active);
        releases.push(() => {
          active -= 1;
          resolve({ status: 200, bodyText: "ok" });
        });
      }),
    };
    const gateway = mustGateway(createGateway(SPECS, { ...decl, callCap: 1 }, port, null));
    const calls = [
      gateway.call("get_tree", { name: "a" }),
      gateway.call("get_tree", { name: "b" }),
      gateway.call("get_tree", { name: "c" }),
    ];

    const waitForRelease = async (): Promise<void> => {
      for (let turn = 0; turn < 10 && releases.length === 0; turn += 1) {
        await Promise.resolve();
      }
    };
    await waitForRelease();
    expect(releases).toHaveLength(1);
    releases.shift()?.();
    await waitForRelease();
    expect(releases).toHaveLength(1);
    releases.shift()?.();

    const results = await Promise.all(calls);
    expect(maxActive).toBe(1);
    expect(portCalls).toBe(2);
    expect(results[2]).toMatchObject({ _tag: "tool_error", reason: "budget_halted" });
  });

  it("flat write 도구: 경로 파라미터 외 인자를 JSON body 로, Bearer 는 주입 시 전달", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "{\"ok\":true}" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, "tok-1"));
    await gateway.call("critique", { tree: "t1", arg_id: "a1", attacks: "root" });
    expect(calls[0]).toMatchObject({
      method: "POST", path: "/api/tree/t1/critique",
      body: JSON.stringify({ arg_id: "a1", attacks: "root" }),
      bearer: "tok-1",
    });
  });

  it("spec_json 도구: 파싱 실패는 서버 미호출 로컬 오류 — Python invalid_spec_json 파리티", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "{}" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    const error = await gateway.call("run_cycle", { name: "t", spec_json: "{broken" });
    expect(error).toEqual({
      _tag: "tool_error", reason: "assemble_error", detail: "invalid_spec_json",
    });
    expect(calls.length).toBe(0);
    await gateway.call("run_cycle", { name: "t", spec_json: "{\"dry_run\":true}" });
    expect(calls[0]).toMatchObject({ body: JSON.stringify({ dry_run: true }) });
  });

  it("local 도구는 typed unsupported — 조용한 오프록시 없음 (정직 공시)", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "{}" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    const error = await gateway.call("longinus_audit", {});
    expect(error).toMatchObject({ _tag: "tool_error", reason: "unsupported_local_tool" });
    expect(calls.length).toBe(0);
  });

  it("쿼리 직렬화 셈: omit_empty·one_flag·true_only — Python 생략 셈 이식", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "{}" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    await gateway.call("fsck", {});
    expect(calls.at(-1)).toMatchObject({ path: "/api/ops/fsck" });
    await gateway.call("fsck", { tree: "t1", emit_skiplist: true });
    expect(calls.at(-1)).toMatchObject({ path: "/api/ops/fsck?tree=t1&emit_skiplist=1" });
  });

  it("delete_tree: Idempotency-Key 헤더 필수(누락=미호출) + cascade true_only", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "{}" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    const missing = await gateway.call("delete_tree", { name: "t" });
    expect(missing).toEqual({
      _tag: "tool_error", reason: "invalid_call", detail: "missing_param",
    });
    expect(calls.length).toBe(0);
    await gateway.call("delete_tree", { name: "t", idempotency_key: "k1", cascade: true });
    expect(calls[0]).toMatchObject({
      method: "DELETE", path: "/api/tree/t?cascade=true",
      extraHeaders: { "Idempotency-Key": "k1" },
    });
  });

  it("A-5 footgun 봉합: 경로 파라미터 name 부재 시 tree= alias 수용 (외부리뷰 2026-07-24)", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "ok" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    const result = await gateway.call("get_tree", { tree: "t9" });
    expect(result).toMatchObject({ _tag: "ToolPage" });
    expect(calls[0]).toMatchObject({ path: "/api/tree/t9" });
    // name 이 명시되면 alias 는 무시된다 (한 개념 한 표현 — name 이 정본)
    await gateway.call("get_tree", { name: "n1", tree: "t9" });
    expect(calls[1]).toMatchObject({ path: "/api/tree/n1" });
  });

  it("READONLY-POSTURE: 무토큰∧token_required 기동 — read 만 서빙, write/ops 는 백엔드 미접촉 차단", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "ok" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null, "read_only"));
    // read 도구는 정상 서빙
    expect(await gateway.call("get_tree", { name: "t" })).toMatchObject({ _tag: "ToolPage" });
    // write 도구는 로컬 typed 차단 — 포트 호출 없음 (fail-closed, 401 왕복도 없다)
    const before = calls.length;
    const blocked = await gateway.call("critique", { tree: "t", arg_id: "a", attacks: "r" });
    expect(blocked).toMatchObject({ _tag: "tool_error", reason: "auth_required" });
    expect(calls.length).toBe(before);
    // ops 도 차단 (fsck 는 kind ops)
    expect(await gateway.call("fsck", {})).toMatchObject({
      _tag: "tool_error", reason: "auth_required",
    });
    expect(calls.length).toBe(before);
  });

  it("READONLY-POSTURE: side-effect GET leaderboard snapshot=true도 백엔드 미접촉 차단", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "ok" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null, "read_only"));
    const blocked = await gateway.call("leaderboard", { trees_csv: "a,b", snapshot: true });
    expect(blocked).toMatchObject({ _tag: "tool_error", reason: "auth_required" });
    expect(calls.length).toBe(0);

    expect(
      await gateway.call("leaderboard", { trees_csv: "a,b", snapshot: false }),
    ).toMatchObject({ _tag: "ToolPage" });
    expect(calls[0]).toMatchObject({ path: "/api/leaderboard?trees=a%2Cb&snapshot=false" });
  });

  it("공개 *_csv 인자를 backend query key로 명시 변환한다", async () => {
    const { port, calls } = fakePort(() => ({ status: 200, bodyText: "ok" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    expect(
      await gateway.call("paradigm", { incumbent: "old", rivals_csv: "new-a,new-b" }),
    ).toMatchObject({ _tag: "ToolPage" });
    expect(calls[0]).toMatchObject({ path: "/api/paradigm?incumbent=old&rivals=new-a%2Cnew-b" });
  });

  it("guard_defect: 미등록 도구·백엔드 오류는 닫힌 오류 값 (throw 없음)", async () => {
    const { port } = fakePort(() => ({ status: 500, bodyText: "boom" }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    expect(await gateway.call("nope", {})).toEqual({
      _tag: "tool_error", reason: "unknown_tool",
    });
    expect(await gateway.call("get_tree", { name: "t" })).toMatchObject({
      _tag: "tool_error", reason: "store_error", status: 500,
    });
  });

  it("스토어 오류 detail 도 유계 — 오류 경로로 무제한 방출 불가", async () => {
    const { port } = fakePort(() => ({ status: 500, bodyText: "e".repeat(10_000) }));
    const gateway = mustGateway(createGateway(SPECS, decl, port, null));
    const error = await gateway.call("get_tree", { name: "t" });
    expect(error).toMatchObject({ _tag: "tool_error", reason: "store_error" });
    if (error._tag === "tool_error" && error.reason === "store_error") {
      expect(error.detail.length).toBeLessThanOrEqual(300);
    }
  });
});
