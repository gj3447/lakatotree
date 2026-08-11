/** lakatotree-ts 계층 방향 강제 — 역방향 import = error (AGENTS.md §Architecture). */
module.exports = {
  forbidden: [
    {
      name: "domain-is-pure",
      severity: "error",
      comment: "domain 은 domain|contracts 만 import 한다",
      from: { path: "^src/domain" },
      to: { pathNot: "^src/(domain|contracts)" },
    },
    {
      name: "contracts-only-contracts",
      severity: "error",
      comment: "contracts 는 contracts 만 import 한다 (type-only 예외)",
      from: { path: "^src/contracts" },
      to: { pathNot: "^src/contracts", dependencyTypesNot: ["type-only"] },
    },
    {
      name: "application-no-adapters-upward",
      severity: "error",
      comment: "application 은 entrypoints 를 모른다",
      from: { path: "^src/application" },
      to: { path: "^src/entrypoints" },
    },
  ],
  options: {
    tsPreCompilationDeps: true,
    doNotFollow: { path: "node_modules" },
    tsConfig: { fileName: "tsconfig.json" },
  },
};
