import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";

export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state" aria-live="polite">
      <div className="spinner" />
      <strong>{label}</strong>
    </div>
  );
}

/**
 * Shown while a country is being ingested for the first time. The steps
 * describe what the user is waiting for without exposing API internals.
 */
export function PreparingBlock({
  message,
  progress,
  steps,
}: {
  message: string;
  progress?: string | null;
  steps?: string[];
}) {
  const list = steps ?? [
    "Fetching annual trade summary",
    "Fetching product composition",
    "Fetching partner data",
  ];
  const activeIndex = progress ? list.findIndex((s) => progress.toLowerCase().includes(s.split(" ")[1] ?? "")) : 0;
  return (
    <div className="state" aria-live="polite">
      <div className="spinner" />
      <strong>{message}</strong>
      <ul className="steps">
        {list.map((step, index) => (
          <li key={step} className={index <= Math.max(activeIndex, 0) ? "active" : ""}>
            <i />
            {step}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EmptyBlock({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <Inbox size={22} />
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="inline-error" role="status">
      <AlertTriangle size={16} />
      <div>
        <div>{message}</div>
        {onRetry && (
          <button type="button" className="link-button" style={{ marginTop: 8 }} onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
