/** lakatotree-ts 순수성 방화벽 — domain 금지 API를 문법 수준에서 차단 (AGENTS.md §Architecture).
 * 규칙은 전부 ESLint 코어(no-restricted-*)라 타입 정보가 필요 없다. */
import tsParser from "@typescript-eslint/parser";

const tsFiles = (files, rules) => ({
  files,
  languageOptions: { parser: tsParser, ecmaVersion: 2023, sourceType: "module" },
  rules,
});

export default [
  { ignores: ["node_modules/**", "dist/**"] },
  tsFiles(["src/**/*.ts", "tests/**/*.ts", "vitest.config.ts"], {
    "no-eval": "error",
    "no-implied-eval": "error",
    "no-var": "error",
    "prefer-const": "error",
  }),
  tsFiles(["src/domain/**/*.ts"], {
    // domain 은 순수: ambient 시각·난수·IO·비동기·throw 금지. 시각은 이벤트 데이터로 들어온다.
    "no-restricted-globals": [
      "error",
      "Date", "fetch", "process", "crypto", "setTimeout", "setInterval",
      "queueMicrotask", "performance", "console",
    ],
    "no-restricted-properties": [
      "error",
      { object: "Math", property: "random", message: "domain 난수 금지" },
      { object: "JSON", property: "parse", message: "파싱은 contracts/adapters 몫" },
    ],
    "no-restricted-imports": [
      "error",
      {
        patterns: [
          { group: ["node:*"], message: "domain 은 플랫폼 import 금지" },
          { group: ["zod"], message: "domain 은 zod 런타임 금지 (type-only 는 contracts 타입으로)" },
          { group: ["../application/*", "../adapters/*", "../entrypoints/*"], message: "역방향 import 금지" },
        ],
      },
    ],
    "no-restricted-syntax": [
      "error",
      { selector: "ThrowStatement", message: "domain throw 금지 — 오류는 값(Decision)으로" },
      { selector: "FunctionDeclaration[async=true]", message: "domain async 금지" },
      { selector: "ArrowFunctionExpression[async=true]", message: "domain async 금지" },
      { selector: "AwaitExpression", message: "domain await 금지" },
      { selector: "ClassDeclaration", message: "domain 은 데이터+함수 — class 금지" },
    ],
  }),
];
