import { X } from "lucide-react";
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

type Props = {
  title: string;
  subtitle?: string;
  breadcrumb?: ReactNode;
  onClose: () => void;
  children: ReactNode;
};

/** Modal side panel used for product and bilateral drilldowns. */
export function Drawer({ title, subtitle, breadcrumb, onClose, children }: Props) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [onClose]);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <div
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={panel}
      >
        <header className="drawer-head">
          <div>
            {breadcrumb && <div className="breadcrumb">{breadcrumb}</div>}
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Close panel">
            <X size={16} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </div>
    </>
  );
}
