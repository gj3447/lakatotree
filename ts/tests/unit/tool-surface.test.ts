/** Scenario TOOL-SURFACE: 51도구 등록 테이블의 기계 정본(spec/tool-surface.v0.json) conform —
 * Python MCP 표면(recon 실측 51개)과의 결손이 diff 로 보인다. assembler 분류 ↔ 구현 완전 동치. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import { ASSEMBLERS } from "../../src/application/assemblers.ts";
import { MIN_CAP_BYTES } from "../../src/domain/page.ts";
import type { ToolSpec } from "../../src/application/gateway.ts";

const here = dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(
  readFileSync(join(here, "..", "..", "spec", "tool-surface.v0.json"), "utf8"),
) as {
  schema_version: string;
  count: number;
  tools: (ToolSpec & { verification?: boolean; params: string; note: string })[];
};

describe("spec-pin: tool-surface", () => {
  it("Python MCP 표면 전수 — 51개 (recon 실측), 결손 없음, 이름 유일", () => {
    expect(spec.schema_version).toBe("tool-surface/v1");
    expect(spec.count).toBe(51);
    expect(spec.tools.length).toBe(51);
    expect(new Set(spec.tools.map((t) => t.name)).size).toBe(51);
  });

  it("assembler 분류 ↔ 구현 완전 동치 (한쪽만 고치면 RED)", () => {
    const declared = spec.tools.filter((t) => t.bodyMode === "assembler").map((t) => t.name);
    expect([...declared].sort()).toEqual([...Object.keys(ASSEMBLERS)].sort());
  });

  it("local 도구는 정확히 2종 — HTTP 프록시 불가 정직 공시", () => {
    expect(spec.tools.filter((t) => t.bodyMode === "local").map((t) => t.name).sort()).toEqual([
      "longinus_audit", "manifest_verify",
    ]);
  });

  it("모든 비로컬 도구: /api 경로 + 유효 메서드 + cap ≥ MIN_CAP_BYTES", () => {
    for (const tool of spec.tools) {
      if (tool.bodyMode === "local") {
        expect(tool.path).toBe("LOCAL");
        continue;
      }
      expect(tool.path.startsWith("/api")).toBe(true);
      expect(["GET", "POST", "DELETE"]).toContain(tool.method);
      expect(tool.capBytes).toBeGreaterThanOrEqual(MIN_CAP_BYTES);
      expect(tool.path.includes("?")).toBe(false); // 쿼리는 query 정의로만 — 한 개념 한 표현
    }
  });

  it("verification 도구는 봉인 단위 미만 페이지화 금지 — 대형 cap 500000", () => {
    const verification = spec.tools.filter((t) => t.verification === true).map((t) => t.name);
    expect(verification.sort()).toEqual([
      "certificate", "consilience", "node_receipts", "provenance", "verify_verdict",
    ]);
    for (const tool of spec.tools.filter((t) => t.verification === true)) {
      expect(tool.capBytes).toBe(500_000);
    }
  });

  it("파괴적 도구는 idempotencyHeader 강제", () => {
    const deleteTree = spec.tools.find((t) => t.name === "delete_tree");
    expect(deleteTree).toMatchObject({ idempotencyHeader: true, method: "DELETE" });
  });

});
