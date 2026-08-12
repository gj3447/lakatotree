import { Context, Effect } from "effect";

export type StoreMethod = "GET" | "POST" | "PUT" | "DELETE";

export interface StoreRequest {
  readonly method: StoreMethod;
  readonly path: string;
  readonly body: string | null;
  readonly bearer: string | null;
  readonly timeoutMs: number;
  readonly extraHeaders?: Readonly<Record<string, string>>;
}

export interface StoreResponse {
  readonly status: number;
  readonly bodyText: string;
}

export interface StoreTransportError {
  readonly _tag: "store_transport_error";
  readonly reason: "connection_failed" | "timeout";
  readonly outcome: "unknown";
  readonly detail: string;
}

export interface StoreClient {
  readonly request: (
    request: StoreRequest,
  ) => Effect.Effect<StoreResponse, StoreTransportError>;
}

export const StoreClient = Context.GenericTag<StoreClient>("lakatotree/StoreClient");

export const requestStore = (
  request: StoreRequest,
): Effect.Effect<StoreResponse, StoreTransportError, StoreClient> =>
  Effect.flatMap(StoreClient, (client) => client.request(request));
