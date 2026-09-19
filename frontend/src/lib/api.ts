/**
 * Backend client. Every call is same-origin under the app's base path, so the
 * browser never talks to UN Comtrade and no subscription key exists here.
 */

import type { Envelope } from "../types";

export const BASE = "/trade";
const API = `${BASE}/api`;

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export type Result<T> =
  | { kind: "ready"; data: T; meta: Envelope<T>["meta"] }
  | { kind: "preparing"; job: PreparingPayload; meta: Envelope<unknown>["meta"] }
  | { kind: "unavailable"; detail: UnavailablePayload; meta: Envelope<unknown>["meta"] };

export type PreparingPayload = {
  status: "preparing";
  message: string;
  job: { id: number; status: string; progress: string | null };
};

/**
 * A preparation job that failed and is not being retried yet.
 *
 * Distinct from an error: nothing is broken, the data simply could not be
 * fetched — most often because the day's Comtrade quota is spent. The caller
 * stops polling and says so rather than spinning.
 */
export type UnavailablePayload = {
  status: "unavailable";
  message: string;
  temporary: boolean;
  retry_after: number;
};

export async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<Result<T>> {
  const response = await fetch(`${API}${path}`, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok && response.status !== 202) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
      else if (body?.error) detail = String(body.error);
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, response.status);
  }
  const payload = (await response.json()) as Envelope<T | PreparingPayload>;
  const data = payload.data as T & Partial<PreparingPayload>;
  if (data && (data as unknown as UnavailablePayload).status === "unavailable") {
    return {
      kind: "unavailable",
      detail: data as unknown as UnavailablePayload,
      meta: payload.meta,
    };
  }
  if (response.status === 202 || (data && (data as PreparingPayload).status === "preparing")) {
    return { kind: "preparing", job: data as unknown as PreparingPayload, meta: payload.meta };
  }
  return { kind: "ready", data: data as T, meta: payload.meta };
}

export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
