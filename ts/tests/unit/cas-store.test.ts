/** Scenario FILE-CAS: 콘텐츠 주소 증거 번들 스토어 — 이름=내용, write-once, 읽기 시 재해시.
 * guard_mechanism: put→get 왕복 + sha=sha256Hex 일치 + 재put=freshen(existed) + 2글자 팬아웃 배치.
 * guard_defect: 디스크 변조 → get 이 content_mismatch (읽기 시 재도출 검증 — 저장된 이름을
 * 신뢰하는 경로가 없음을 실증) · 비정형 sha/경로 탈출 → invalid_sha (스토어 루트 밖 접근 불가) ·
 * 미존재 → not_found · 산출 파일은 쓰기 불가 모드 (불변 강제). */
import { chmod, mkdtemp, readFile, writeFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fileCasStore } from "../../src/adapters/casstore.ts";
import { sha256Hex } from "../../src/contracts/sha256.ts";

const bytes = (text: string): Uint8Array => new TextEncoder().encode(text);

const freshStore = async () => fileCasStore(await mkdtemp(join(tmpdir(), "lakatos-cas-")));

describe("Scenario FILE-CAS", () => {
  it("guard_mechanism: put→get 왕복, sha 는 콘텐츠의 sha256, 팬아웃 배치", async () => {
    const store = await freshStore();
    const payload = bytes('{"evidence":"한글 증거 본문"}');
    const put = await store.put(payload);
    if ("_tag" in put) throw new Error(`put failed: ${JSON.stringify(put)}`);
    expect(put.sha).toBe(sha256Hex(payload));
    expect(put.existed).toBe(false);
    const got = await store.get(put.sha);
    expect(got).toBeInstanceOf(Uint8Array);
    expect([...(got as Uint8Array)]).toEqual([...payload]);
  });

  it("guard_mechanism: 같은 바이트 재put = freshen (existed=true, 내용 보존)", async () => {
    const store = await freshStore();
    const payload = bytes("idempotent");
    const first = await store.put(payload);
    const second = await store.put(payload);
    if ("_tag" in first || "_tag" in second) throw new Error("put failed");
    expect(second.sha).toBe(first.sha);
    expect(second.existed).toBe(true);
    expect([...((await store.get(first.sha)) as Uint8Array)]).toEqual([...payload]);
  });

  it("guard_defect: 디스크 변조는 get 에서 content_mismatch — 이름을 신뢰하지 않는다", async () => {
    const root = await mkdtemp(join(tmpdir(), "lakatos-cas-"));
    const store = fileCasStore(root);
    const payload = bytes("tamper-target");
    const put = await store.put(payload);
    if ("_tag" in put) throw new Error("put failed");
    const onDisk = join(root, put.sha.slice(0, 2), put.sha);
    await chmod(onDisk, 0o644);
    await writeFile(onDisk, bytes("tampered!"));
    expect(await store.get(put.sha)).toMatchObject({ _tag: "cas_error", reason: "content_mismatch" });
  });

  it("guard_defect: 비정형 sha·경로 탈출 → invalid_sha (루트 밖 접근 경로 부재)", async () => {
    const store = await freshStore();
    for (const bad of ["", "xyz", "ABCDEF", "../../etc/passwd", "a".repeat(63), "g".repeat(64)]) {
      expect(await store.get(bad)).toMatchObject({ _tag: "cas_error", reason: "invalid_sha" });
    }
  });

  it("guard_defect: 미존재 sha → not_found", async () => {
    const store = await freshStore();
    expect(await store.get("0".repeat(64))).toMatchObject({ _tag: "cas_error", reason: "not_found" });
  });

  it("불변 강제: 산출 파일은 쓰기 비트가 없다 (write-once)", async () => {
    const root = await mkdtemp(join(tmpdir(), "lakatos-cas-"));
    const store = fileCasStore(root);
    const put = await store.put(bytes("immutable"));
    if ("_tag" in put) throw new Error("put failed");
    const mode = (await stat(join(root, put.sha.slice(0, 2), put.sha))).mode;
    expect(mode & 0o222).toBe(0);
    // 검증 편의: readFile 로는 여전히 읽힌다
    expect((await readFile(join(root, put.sha.slice(0, 2), put.sha))).length).toBeGreaterThan(0);
  });
});
