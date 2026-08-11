/** StorePort 실 HTTP 어댑터 — 기존 :55170 엔진 API 프록시용. 상태·본문을 가감 없이 값으로
 * 반환하고 절대 throw 하지 않는다 — 판정(store_error 캡·유계)은 application 게이트웨이 몫.
 * Bearer 는 주입 시에만 부착 (LAKATOS_API_TOKEN 관례, auth_posture 존중). */
import type { StorePort, StoreResponse } from "../application/gateway.ts";

export const httpStorePort = (baseUrl: string): StorePort => ({
  request: async (
    method: string,
    path: string,
    body: string | null,
    bearer: string | null,
    extraHeaders?: Readonly<Record<string, string>>,
  ): Promise<StoreResponse> => {
    const headers: Record<string, string> = { ...extraHeaders };
    if (body !== null) headers["content-type"] = "application/json";
    if (bearer !== null) headers["authorization"] = `Bearer ${bearer}`;
    try {
      const init: RequestInit =
        body === null ? { method, headers } : { method, headers, body };
      const response = await fetch(baseUrl + path, init);
      return { status: response.status, bodyText: await response.text() };
    } catch (cause) {
      // 연결 실패도 값 — 게이트웨이가 store_error 로 유계 보고한다.
      return {
        status: 0,
        bodyText: `connection_failed: ${cause instanceof Error ? cause.message : "unknown"}`,
      };
    }
  },
});
