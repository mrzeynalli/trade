import { vi } from "vitest";

/**
 * jsdom has no canvas implementation, so a real ECharts instance cannot
 * initialise. These tests are about the surrounding application — routing,
 * state, drilldowns, degraded states — so the chart renders as its accessible
 * description instead, which is what a screen reader would receive anyway.
 */
vi.mock("../components/EChart", async () => {
  const actual = await vi.importActual<typeof import("../components/EChart")>("../components/EChart");
  return {
    ...actual,
    EChart: ({ ariaLabel, className }: { ariaLabel: string; className?: string }) => (
      <div role="img" aria-label={ariaLabel} className={className} data-testid="chart" />
    ),
  };
});
