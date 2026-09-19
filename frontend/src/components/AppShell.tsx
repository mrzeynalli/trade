import { ArrowLeft, Menu } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useWideLayout } from "../lib/useWideLayout";
import { Brand } from "./Brand";
import { Sidebar, type SidebarSection } from "./Sidebar";
import { SiteFooter } from "./SiteFooter";
import type { Meta } from "../types";

type Props = {
  sections: SidebarSection[];
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  context?: { name: string; iso2?: string | null; onClear: () => void } | null;
  meta?: Meta | null;
  children: ReactNode;
};

/**
 * Two-column application shell: a persistent section rail on the left and the
 * working area on the right.
 *
 * The rail toggle does different work either side of the 1000px breakpoint. On
 * a narrow screen the rail is off-canvas and the button opens it; on a wide one
 * the rail sits in the grid and the button collapses it to give the working
 * area the full width. Collapsing is deliberately not reset by navigation — it
 * is a preference for the session, not a state of the page.
 */
export function AppShell({
  sections, sidebarOpen, onToggleSidebar, context, meta, children,
}: Props) {
  const wide = useWideLayout();
  const [railCollapsed, setRailCollapsed] = useState(false);
  const railShown = wide ? !railCollapsed : sidebarOpen;

  return (
    <div className={`app-shell ${sidebarOpen ? "sidebar-open" : ""} ${
      wide && railCollapsed ? "rail-collapsed" : ""
    }`}>
      <header className="app-bar">
        <div className="app-bar-left">
          <button
            type="button"
            className="sidebar-toggle"
            onClick={() => (wide ? setRailCollapsed((value) => !value) : onToggleSidebar())}
            aria-label={railShown ? "Hide sections" : "Show sections"}
            aria-expanded={railShown}
            aria-controls="section-rail"
          >
            <Menu size={17} />
          </button>
          <Brand />
        </div>
        <nav aria-label="Primary">
          <a className="back-link" href="/">
            <ArrowLeft size={15} /> Project index
          </a>
          <a href="https://mrzeynalli.xyz" target="_blank" rel="noopener noreferrer">
            About me
          </a>
        </nav>
      </header>

      <Sidebar
        sections={sections}
        open={sidebarOpen}
        onToggle={onToggleSidebar}
        shown={railShown}
        context={context}
      />

      <main className="app-main" id="main">
        {children}
        <SiteFooter meta={meta} />
      </main>
    </div>
  );
}
