/** 콘텐츠 주소 영수증 — G1: 이름=내용, prev 사슬(N.new == N+1.old), 불변 append-only.
 * receipt_sha = sha256(canonical({type_header, ...fields})). 자기 sha 는 프리이미지에서 제외. */
import { canonicalBytes, type CanonicalError } from "../contracts/canonical.ts";
import { sha256Hex } from "../contracts/sha256.ts";

export const RECEIPT_TYPE_HEADER = "lakatotree-ts-verdict-receipt/v0";
export const PREDICTION_TYPE_HEADER = "lakatotree-ts-prediction-receipt/v0";

export interface VerdictReceipt {
  readonly type_header: typeof RECEIPT_TYPE_HEADER;
  readonly tree: string;
  readonly tag: string;
  readonly verdict: string;
  readonly value_micro: number;
  readonly bundle_sha: string;
  readonly event_id: string;
  readonly prev_receipt_sha: string;
}

export interface PredictionReceipt {
  readonly type_header: typeof PREDICTION_TYPE_HEADER;
  readonly tree: string;
  readonly tag: string;
  readonly metric: string;
  readonly baseline_micro: number;
  readonly direction: string;
  readonly noise_band_micro: number;
  readonly spec_sha: string;
  readonly event_id: string;
}

export const receiptSha = (
  receipt: VerdictReceipt | PredictionReceipt,
): string | CanonicalError => {
  const record: Record<string, string | number> = Object.fromEntries(
    Object.entries(receipt),
  );
  const bytes = canonicalBytes(record);
  if (!(bytes instanceof Uint8Array)) return bytes;
  return `sha256:${sha256Hex(bytes)}`;
};
