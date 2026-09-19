import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

type Props = { title: string; children: ReactNode };

/**
 * Explanatory note that works by click as well as hover, so the content is
 * reachable on a touch screen.
 */
export function InfoTip({ title, children }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const container = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocument = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocument);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocument);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <span className="info-tip" ref={container}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`About ${title}`}
        onClick={() => setOpen((current) => !current)}
      >
        i
      </button>
      {open && (
        <span className="tip-body" id={id} role="note">
          <h4>{title}</h4>
          {children}
        </span>
      )}
    </span>
  );
}
