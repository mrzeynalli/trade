import { useEffect, useState } from "react";

/** Mirrors the 1000px breakpoint at which the rail leaves the grid. */
const WIDE = "(min-width: 1001px)";

/**
 * True while the layout is wide enough for the section rail to sit in the grid
 * rather than off-canvas.
 *
 * The rail toggle means two different things either side of that breakpoint —
 * on a narrow screen it opens a drawer, on a wide one it collapses a column —
 * so the shell has to know which it is looking at.
 */
export function useWideLayout(): boolean {
  const [wide, setWide] = useState(() =>
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? true
      : window.matchMedia(WIDE).matches,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(WIDE);
    const update = (event: MediaQueryListEvent) => setWide(event.matches);
    setWide(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return wide;
}
