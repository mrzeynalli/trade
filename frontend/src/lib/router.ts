/**
 * Minimal history router. Analytical state lives in the URL so a view can be
 * refreshed, bookmarked, shared, and walked back through with the browser's
 * own back button.
 */

import { useCallback, useEffect, useState } from "react";
import { BASE } from "./api";

export type Route = {
  path: string;
  params: URLSearchParams;
};

function read(): Route {
  const raw = window.location.pathname.replace(/\/+$/, "") || "/";
  const path = raw.startsWith(BASE) ? raw.slice(BASE.length) || "/" : raw;
  return { path, params: new URLSearchParams(window.location.search) };
}

export function useRoute() {
  const [route, setRoute] = useState<Route>(read);

  useEffect(() => {
    const update = () => setRoute(read());
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  const navigate = useCallback(
    (path: string, params?: Record<string, string | null>, options?: { replace?: boolean; keepScroll?: boolean }) => {
      const search = new URLSearchParams(params ? {} : window.location.search);
      if (params) {
        for (const [key, value] of Object.entries(params)) {
          if (value === null || value === "") search.delete(key);
          else search.set(key, value);
        }
      }
      const text = search.toString();
      const url = `${BASE}${path === "/" ? "" : path}${text ? `?${text}` : ""}` || BASE;
      if (options?.replace) window.history.replaceState({}, "", url);
      else window.history.pushState({}, "", url);
      setRoute(read());
      if (!options?.keepScroll) window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [],
  );

  const setParams = useCallback(
    (params: Record<string, string | null>, options?: { replace?: boolean }) => {
      const search = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(params)) {
        if (value === null || value === "") search.delete(key);
        else search.set(key, value);
      }
      const text = search.toString();
      const url = `${window.location.pathname}${text ? `?${text}` : ""}`;
      if (options?.replace) window.history.replaceState({}, "", url);
      else window.history.pushState({}, "", url);
      setRoute(read());
    },
    [],
  );

  return { route, navigate, setParams };
}
