import {
  BarChart3, BookOpen, Boxes, ChevronLeft, Globe2, Handshake, LayoutDashboard, Lightbulb, X,
} from "lucide-react";
import type { ReactNode } from "react";
import { Flag } from "./Flag";

export type SidebarSection = {
  label: string;
  items: {
    id: string;
    label: string;
    icon: ReactNode;
    active: boolean;
    onSelect: () => void;
  }[];
};

export const ICONS = {
  dashboard: <LayoutDashboard size={16} />,
  countries: <Globe2 size={16} />,
  products: <Boxes size={16} />,
  partners: <Handshake size={16} />,
  insights: <Lightbulb size={16} />,
  overview: <BarChart3 size={16} />,
  methodology: <BookOpen size={16} />,
};

type Props = {
  sections: SidebarSection[];
  open: boolean;
  onToggle: () => void;
  /** Whether the rail is actually visible: off-canvas when open, or in the grid. */
  shown?: boolean;
  /** Shown as a context header when a country is selected. */
  context?: { name: string; iso2?: string | null; onClear: () => void } | null;
};

export function Sidebar({ sections, open, onToggle, shown = true, context }: Props) {
  return (
    <>
      {open && <div className="sidebar-scrim" onClick={onToggle} aria-hidden="true" />}
      <aside
        id="section-rail"
        className={`sidebar ${open ? "is-open" : ""}`}
        aria-label="Sections"
        // Taken out of the tab order whenever the rail is not on screen — either
        // off-canvas on a narrow screen or collapsed on a wide one — so focus
        // cannot disappear into a panel the reader cannot see.
        inert={!shown}
      >
        <div className="sidebar-head">
          <span>Sections</span>
          <button type="button" className="sidebar-close" onClick={onToggle} aria-label="Close sections">
            <X size={15} />
          </button>
        </div>

        {context && (
          <div className="sidebar-context">
            <Flag iso2={context.iso2} size={16} />
            <span className="context-name">{context.name}</span>
            <button type="button" onClick={context.onClear} aria-label="Leave country view">
              <ChevronLeft size={14} />
            </button>
          </div>
        )}

        <nav>
          {sections.map((section) => (
            <div className="sidebar-group" key={section.label}>
              <h2>{section.label}</h2>
              <ul>
                {section.items.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={item.active ? "active" : ""}
                      aria-current={item.active ? "page" : undefined}
                      onClick={item.onSelect}
                    >
                      {item.icon}
                      {item.label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}
