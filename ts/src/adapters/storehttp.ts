/** 기존 :55170 엔진 API를 위한 Effect StoreClient Layer. HTTP 상태는 값으로 보존하고,
 * transport/timeout만 typed unknown-outcome failure로 분리한다. 자동 재시도는 없다. */
import { Effect, Layer } from "effect";
import {
  StoreClient,
  type StoreRequest,
  type StoreResponse,
  type StoreTransportError,
} from "../application/store.ts";

const DEFAULT_TIMEOUT_MS = 30_000;

const detailOf = (cause: unknown): string =>
  cause instanceof Error ? cause.message : "unknown";

const connectionFailure = (cause: unknown): StoreTransportError => ({
  _tag: "store_transport_error",
  reason: "connection_failed",
  outcome: "unknown",
  detail: detailOf(cause),
});

const timeoutFailure = (): StoreTransportError => ({
  _tag: "store_transport_error",
  reason: "timeout",
  outcome: "unknown",
  detail: "request_timeout",
});

const boundedTimeout = (timeoutMs: number): number =>
  Number.isSafeInteger(timeoutMs) && timeoutMs > 0 ? timeoutMs : DEFAULT_TIMEOUT_MS;

const request = (baseUrl: string, request: StoreRequest) => {
  const headers: Record<string, string> = { ...request.extraHeaders };
  if (request.body !== null) headers["content-type"] = "application/json";
  if (request.bearer !== null) headers["authorization"] = `Bearer ${request.bearer}`;
  return Effect.tryPromise({
    try: async (signal): Promise<StoreResponse> => {
      const init: RequestInit = request.body === null
        ? { method: request.method, headers, signal }
        : { method: request.method, headers, body: request.body, signal };
      const response = await fetch(baseUrl + request.path, init);
      return { status: response.status, bodyText: await response.text() };
    },
    catch: connectionFailure,
  }).pipe(
    Effect.timeoutFail({
      duration: boundedTimeout(request.timeoutMs),
      onTimeout: timeoutFailure,
    }),
  );
};

export const httpStoreLayer = (baseUrl: string) =>
  Layer.succeed(StoreClient, { request: (input) => request(baseUrl, input) });
