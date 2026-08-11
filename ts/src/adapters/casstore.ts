/** 콘텐츠 주소 증거 번들 스토어 — 파일시스템 CAS: <root>/<sha[0:2]>/<sha>.
 * G1 계승: 이름=내용(put 이 sha 를 도출 — 클라이언트 선언 sha 를 받지 않는다), write-once
 * (재put 동일 바이트 = freshen), 읽기 시 재해시(저장 이름 불신 — RECEIPT_SHA_CONTENT_MISMATCH
 * 관례), 원자 발행(임시 파일 + rename — finalize_object_file 관례). 오류는 전부 값, throw 없음.
 * 크기 상한은 호출자(application) 몫 — 이 층은 바이트를 가감 없이 봉인한다. */
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { sha256Hex } from "../contracts/sha256.ts";

export interface CasPutResult {
  readonly sha: string;
  readonly existed: boolean;
}

export type CasError = {
  readonly _tag: "cas_error";
  readonly reason: "invalid_sha" | "not_found" | "content_mismatch" | "io_error";
  readonly detail: string;
};

export interface BundleStore {
  readonly put: (bytes: Uint8Array) => Promise<CasPutResult | CasError>;
  readonly get: (sha: string) => Promise<Uint8Array | CasError>;
}

const SHA_PATTERN = /^[0-9a-f]{64}$/;

const equalBytes = (a: Uint8Array, b: Uint8Array): boolean => {
  if (a.length !== b.length) return false;
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) return false;
  }
  return true;
};

const ioError = (cause: unknown): CasError => ({
  _tag: "cas_error",
  reason: "io_error",
  detail: cause instanceof Error ? cause.message.slice(0, 200) : "unknown",
});

let tmpSeq = 0;

export const fileCasStore = (root: string): BundleStore => {
  const pathFor = (sha: string): string => join(root, sha.slice(0, 2), sha);

  const put = async (bytes: Uint8Array): Promise<CasPutResult | CasError> => {
    const sha = sha256Hex(bytes);
    const target = pathFor(sha);
    try {
      const existing = await readFile(target).catch(() => null);
      if (existing !== null) {
        // 같은 이름에 다른 내용 = 저장층 변조 — freshen 이 아니라 divergence 오류다.
        return equalBytes(new Uint8Array(existing), bytes)
          ? { sha, existed: true }
          : { _tag: "cas_error", reason: "content_mismatch", detail: sha };
      }
      await mkdir(dirname(target), { recursive: true, mode: 0o700 });
      tmpSeq += 1;
      const tmp = `${target}.tmp-${process.pid}-${tmpSeq}`;
      await writeFile(tmp, bytes, { mode: 0o444 });
      await rename(tmp, target);
      return { sha, existed: false };
    } catch (cause) {
      return ioError(cause);
    }
  };

  const get = async (sha: string): Promise<Uint8Array | CasError> => {
    if (!SHA_PATTERN.test(sha)) {
      return { _tag: "cas_error", reason: "invalid_sha", detail: sha.slice(0, 80) };
    }
    let raw: Buffer;
    try {
      raw = await readFile(pathFor(sha));
    } catch (cause) {
      const code = (cause as { code?: string }).code;
      return code === "ENOENT"
        ? { _tag: "cas_error", reason: "not_found", detail: sha }
        : ioError(cause);
    }
    const bytes = new Uint8Array(raw);
    // 읽기 시 재도출 — 파일명이 아니라 내용이 정체성이다.
    if (sha256Hex(bytes) !== sha) {
      return { _tag: "cas_error", reason: "content_mismatch", detail: sha };
    }
    return bytes;
  };

  return { put, get };
};
