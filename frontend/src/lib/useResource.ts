/**
 * Data hook with independent failure. One section failing must not blank the
 * page, so every consumer gets its own status.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchJson, type PreparingPayload, type Result } from "./api";
import type { Meta } from "../types";

export type ResourceState<T> = {
  data: T | null;
  meta: Meta | null;
  status: "idle" | "loading" | "ready" | "preparing" | "error";
  error: string | null;
  job: PreparingPayload | null;
  reload: () => void;
};

const POLL_MS = 2500;
// A preparation job that never reaches a terminal state must not leave the
// interface spinning indefinitely. Roughly five minutes of polling is longer
// than any real ingestion here takes.
const MAX_POLLS = 120;

export function useResource<T>(path: string | null, options?: { enabled?: boolean }): ResourceState<T> {
  const [data, setData] = useState<T | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [status, setStatus] = useState<ResourceState<T>["status"]>("idle");
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<PreparingPayload | null>(null);
  const [nonce, setNonce] = useState(0);
  const timer = useRef<number | null>(null);

  const enabled = options?.enabled !== false && path !== null;

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled || path === null) {
      setStatus("idle");
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    let polls = 0;

    const run = async () => {
      try {
        const result: Result<T> = await fetchJson<T>(path, controller.signal);
        if (cancelled) return;
        setMeta(result.meta);
        // The job failed and the server is not retrying it yet. Say why and
        // stop, rather than polling a spinner that will never resolve.
        if (result.kind === "unavailable") {
          setJob(null);
          setStatus("error");
          setError(result.detail.message);
          return;
        }
        if (result.kind === "preparing") {
          setJob(result.job);
          setStatus("preparing");
          setError(null);
          polls += 1;
          if (polls >= MAX_POLLS) {
            setStatus("error");
            setError("This is taking longer than expected. Try again in a moment.");
            return;
          }
          timer.current = window.setTimeout(run, POLL_MS);
          return;
        }
        setData(result.data);
        setJob(null);
        setStatus("ready");
        setError(null);
      } catch (exc) {
        if (cancelled || (exc instanceof DOMException && exc.name === "AbortError")) return;
        setStatus("error");
        setError(exc instanceof ApiError ? exc.message : "Could not load this section");
      }
    };

    setStatus((current) => (current === "ready" ? "ready" : "loading"));
    void run();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [path, enabled, nonce]);

  return { data, meta, status, error, job, reload };
}
