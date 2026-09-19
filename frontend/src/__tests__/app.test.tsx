import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

const COUNTRIES = {
  data: [
    { code: 31, name: "Azerbaijan", iso2: "AZ", iso3: "AZE", is_group: false, expired: false, cached: true, cached_monthly: true },
    { code: 276, name: "Germany", iso2: "DE", iso3: "DEU", is_group: false, expired: false, cached: true, cached_monthly: false },
    { code: 704, name: "Viet Nam", iso2: "VN", iso3: "VNM", is_group: false, expired: false, cached: false, cached_monthly: false },
  ],
  meta: { source: "UN Comtrade", count: 3, cached_countries: 2, available: true },
};

const META = {
  source: "UN Comtrade",
  frequency: "annual",
  classification: "HS (as reported)",
  measure: "Trade value (current USD)",
  reporter: { code: 31, name: "Azerbaijan", iso3: "AZE", iso2: "AZ" },
  latest_complete_annual: 2025,
  latest_annual: 2025,
  latest_monthly: "202606",
  latest_complete_period: 2025,
  partial: false,
  last_source_update: "2026-03-08T18:14:05",
  local_cache_updated_at: "2026-09-04T18:57:30+00:00",
  dataset_version: 2,
  stale: false,
  composition_period: "2025",
  monthly_available: true,
  hs4_available: false,
};

const ranking = (items: unknown[]) => ({
  items,
  other: { value: 10, share: 0.05, count: 40 },
  total: 200,
  count: 42,
  available: true,
});

const SUMMARY = {
  data: {
    status: "ready",
    kpis: {
      period: "2025",
      composition_period: "2025",
      exports: 25_042_007_312,
      imports: 24_372_944_335,
      balance: 669_062_977,
      export_change: -0.0569,
      import_change: 0.1576,
      top_export_destination: { key: 380, code: 380, name: "Italy", value: 11_342_330_408, share: 0.4529, weight: null },
      top_import_origin: { key: 156, code: 156, name: "China", value: 4_789_863_624, share: 0.1965, weight: null },
    },
    series: [
      { period: "2023", year: 2023, month: null, exports: 33_898_554_855, imports: 17_278_236_451, balance: 16_620_318_403 },
      { period: "2024", year: 2024, month: null, exports: 26_554_056_764, imports: 21_054_831_458, balance: 5_499_225_306 },
      { period: "2025", year: 2025, month: null, exports: 25_042_007_312, imports: 24_372_944_335, balance: 669_062_977 },
    ],
    export_products: ranking([
      { key: "27", code: "27", name: "Mineral fuels", value: 21_520_000_000, share: 0.859, weight: null },
      { key: "08", code: "08", name: "Edible fruit and nuts", value: 660_000_000, share: 0.026, weight: null },
    ]),
    import_products: ranking([
      { key: "84", code: "84", name: "Machinery", value: 4_000_000_000, share: 0.164, weight: null },
    ]),
    export_partners: ranking([
      { key: 380, code: 380, name: "Italy", value: 11_342_330_408, share: 0.4529, weight: null, iso3: "ITA" },
      { key: 792, code: 792, name: "Türkiye", value: 3_380_000_000, share: 0.135, weight: null, iso3: "TUR" },
    ]),
    import_partners: ranking([
      { key: 156, code: 156, name: "China", value: 4_789_863_624, share: 0.1965, weight: null, iso3: "CHN" },
    ]),
  },
  meta: META,
};

const PRODUCT_DETAIL = {
  data: {
    code: "27",
    name: "Mineral fuels",
    level: 2,
    flow: "X",
    value: 21_520_000_000,
    share_of_flow: 0.859,
    change: -0.06,
    series: [{ period: "2025", year: 2025, month: null, exports: 21_520_000_000, imports: 100, export_weight: null, import_weight: null }],
    children: { items: [], other: null, total: null, count: 0, available: false },
    partners: ranking([{ key: 380, code: 380, name: "Italy", value: 10_000_000_000, share: 0.46, weight: null }]),
    partners_status: "ready",
    unit_values: [],
    composition_period: "2025",
    classification_note: "HS revisions change over time.",
  },
  meta: META,
};

const PARTNER_DETAIL = {
  data: {
    partner: { code: 380, name: "Italy", iso3: "ITA", iso2: "IT" },
    series: [{ period: "2025", exports: 11_342_330_408, imports: 500_000_000, balance: 10_842_330_408 }],
    exports: 11_342_330_408,
    imports: 500_000_000,
    balance: 10_842_330_408,
    period: "2025",
    export_share_of_total: 0.4529,
    import_share_of_total: 0.0205,
    export_change: 0.03,
    import_change: -0.01,
    export_products: ranking([{ key: "27", code: "27", name: "Mineral fuels", value: 10_000_000_000, share: 0.9, weight: null }]),
    import_products: ranking([{ key: "84", code: "84", name: "Machinery", value: 200_000_000, share: 0.4, weight: null }]),
    products_status: "ready",
    composition_period: "2025",
  },
  meta: META,
};


const WORLD = {
  data: {
    available: true,
    year: 2024,
    years: [2022, 2023, 2024],
    latest_complete: 2024,
    partial: false,
    totals: { exports: 22_107_427_854_665, imports: 22_400_000_000_000, balance: -292_572_145_335, reporters: 165, export_change: 0.042, import_change: 0.031 },
    series: [
      { year: 2022, period: "2022", exports: 21_000_000_000_000, imports: 21_400_000_000_000, reporters: 167 },
      { year: 2023, period: "2023", exports: 21_200_000_000_000, imports: 21_700_000_000_000, reporters: 165 },
      { year: 2024, period: "2024", exports: 22_107_427_854_665, imports: 22_400_000_000_000, reporters: 165 },
    ],
    map: [
      { code: 156, iso3: "CHN", name: "China", value: 3_380_000_000_000, share: 0.153, change: 0.059 },
      { code: 842, iso3: "USA", name: "USA", value: 2_065_000_000_000, share: 0.093, change: 0.021 },
      { code: 31, iso3: "AZE", name: "Azerbaijan", value: 25_042_007_312, share: 0.0011, change: -0.057 },
    ],
    top_traders: [
      { code: 156, iso3: "CHN", name: "China", value: 3_380_000_000_000, share: 0.153, change: 0.059 },
      { code: 842, iso3: "USA", name: "USA", value: 2_065_000_000_000, share: 0.093, change: 0.021 },
    ],
    top_importers: [{ code: 842, iso3: "USA", name: "USA", value: 3_100_000_000_000 }],
    fastest_growing: [{ code: 704, iso3: "VNM", name: "Viet Nam", value: 400_000_000_000, change: 0.184 }],
    largest_declines: [{ code: 31, iso3: "AZE", name: "Azerbaijan", value: 25_042_007_312, change: -0.057 }],
    products: {
      available: true,
      items: [
        { code: "85", name: "Electrical machinery", value: 3_100_000_000_000, share: 0.14 },
        { code: "84", name: "Machinery", value: 2_800_000_000_000, share: 0.127 },
      ],
      other: { value: 16_000_000_000_000, count: 95, share: 0.72 },
      total: 22_107_427_854_665,
    },
    openness: [
      { code: 31, iso3: "AZE", name: "Azerbaijan", gdp_per_capita: 7294, openness: 66.4, trade: 49_414_951_648 },
      { code: 156, iso3: "CHN", name: "China", gdp_per_capita: 12600, openness: 37.2, trade: 6_100_000_000_000 },
    ],
    coverage: { reporters: 165, note: "Reported coverage only." },
  },
  meta: { source: "UN Comtrade", year: 2024, available: true },
};

let routes: Record<string, { status: number; body: unknown }>;

function setRoute(pattern: string, body: unknown, status = 200) {
  routes[pattern] = { status, body };
}

beforeEach(() => {
  routes = {};
  setRoute("/meta/countries", COUNTRIES);
  setRoute("/world/overview", WORLD);
  setRoute("/country/AZE/summary", SUMMARY);
  setRoute("/country/AZE/product/27", PRODUCT_DETAIL);
  setRoute("/country/AZE/partner/380", PARTNER_DETAIL);
  setRoute("/country/AZE/macro", {
    data: {
      available: true,
      gdp_year: 2024,
      gdp_usd: 74_426_000_000,
      population: 10_202_830,
      gdp_per_capita: 7294.64,
      trade_openness: 0.664,
      exports_over_gdp: 0.336,
      imports_over_gdp: 0.327,
      balance_over_gdp: 0.009,
      exports_per_capita: 2454,
      imports_per_capita: 2389,
      trade_year: 2024,
      history: [],
      source: "World Bank",
    },
    meta: META,
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const path = url.replace("/trade/api", "").split("?")[0];
      const match = routes[path];
      if (!match) {
        return new Response(JSON.stringify({ data: {}, meta: META }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(match.body), {
        status: match.status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  // jsdom does not implement these; ECharts and the drawer both need them.
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  window.scrollTo = vi.fn();
  window.history.replaceState({}, "", "/trade");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("world overview (landing)", () => {
  it("leads with the world headline figure and a country selector", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: /What the world/i })).toBeTruthy();
    expect(await screen.findByRole("combobox", { name: /search for a country/i })).toBeTruthy();
    // The figure appears in the hero and again in the stat strip.
    expect((await screen.findAllByText("$22.11T")).length).toBe(2);
  });

  it("shows world totals, reporter coverage and the largest traders", async () => {
    render(<App />);
    expect(await screen.findByText(/reported world exports in/)).toBeTruthy();
    expect((await screen.findAllByText("165")).length).toBeGreaterThan(0);
    expect(await screen.findByText(/Who trades most/)).toBeTruthy();
    expect((await screen.findAllByText("China")).length).toBeGreaterThan(0);
  });

  it("opens a country from a world ranking row", async () => {
    const user = userEvent.setup();
    render(<App />);
    const rows = await screen.findAllByRole("button", { name: /^China, \$3,380/ });
    await user.click(rows[0]);
    await waitFor(() => expect(window.location.pathname).toBe("/trade/country/CHN"));
  });

  it("reports missing world data instead of showing zeros", async () => {
    setRoute("/world/overview", {
      data: { available: false, reason: "No countries cached yet" },
      meta: { source: "UN Comtrade", available: false },
    });
    render(<App />);
    expect(await screen.findByText("No country data yet")).toBeTruthy();
  });

  it("finds a country by ISO alpha-3 code", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = await screen.findByRole("combobox", { name: /search for a country/i });
    await user.type(input, "DEU");
    const list = await screen.findByRole("listbox");
    expect(within(list).getByText(/Germany/)).toBeTruthy();
  });

  it("finds a country by name", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = await screen.findByRole("combobox", { name: /search for a country/i });
    await user.type(input, "viet");
    const list = await screen.findByRole("listbox");
    expect(within(list).getByText(/Viet Nam/)).toBeTruthy();
  });

  it("navigates to the country route on selection", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = await screen.findByRole("combobox", { name: /search for a country/i });
    await user.type(input, "Azerbaijan");
    const list = await screen.findByRole("listbox");
    await user.click(within(list).getByText(/Azerbaijan/));
    await waitFor(() => expect(window.location.pathname).toBe("/trade/country/AZE"));
  });
});

describe("country dashboard", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/trade/country/AZE");
  });

  it("renders the KPI row with compact values", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Azerbaijan" })).toBeTruthy();
    expect(await screen.findByText("$25.04B")).toBeTruthy();
    expect(await screen.findByText("$24.37B")).toBeTruthy();
  });

  it("shows the provenance stamp for the data it served", async () => {
    render(<App />);
    const stamp = (await screen.findByText(/Latest complete year/)).closest("span");
    expect(stamp?.textContent).toContain("2025");
    // The stamp appears in the header and again in the source footer.
    expect((await screen.findAllByText(/Retrieved/)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/4 Sept 2026/)).length).toBeGreaterThan(0);
  });

  it("renders both composition sections and the Other bucket", async () => {
    render(<App />);
    expect(await screen.findByText(/What does Azerbaijan export\?/)).toBeTruthy();
    expect(await screen.findByText(/What does Azerbaijan import\?/)).toBeTruthy();
    expect((await screen.findAllByText("Other")).length).toBeGreaterThan(0);
  });

  it("puts the frequency into the URL when toggled", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Azerbaijan" });
    await user.click(screen.getByRole("button", { name: "Monthly" }));
    await waitFor(() => expect(window.location.search).toContain("freq=M"));
  });

  it("puts the tab into the URL", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Azerbaijan" });
    await user.click(screen.getByRole("button", { name: "Partners" }));
    await waitFor(() => expect(window.location.search).toContain("tab=partners"));
  });

  it("restores state from the URL on load", async () => {
    window.history.replaceState({}, "", "/trade/country/AZE?tab=insights&freq=A");
    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Insights" }).getAttribute("aria-current"),
      ).toBe("page"),
    );
  });

  it("switches composition to bars and opens a product drilldown", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Azerbaijan" });
    // Composition defaults to the treemap; the bars view is the accessible
    // path to the same drilldown.
    await user.click(screen.getAllByRole("button", { name: "Bars" })[0]);
    const bar = await screen.findByRole("button", { name: /Mineral fuels · HS 27/ });
    await user.click(bar);
    await waitFor(() => expect(window.location.search).toContain("product=27"));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("renders the trade-to-GDP ratios when World Bank data is available", async () => {
    render(<App />);
    expect(await screen.findByText("Trade openness")).toBeTruthy();
    expect(await screen.findByText("66.4%")).toBeTruthy();
    expect((await screen.findAllByText(/World Bank, 2024/)).length).toBe(2);
  });

  it("opens a bilateral drilldown when a partner is clicked", async () => {
    const user = userEvent.setup();
    render(<App />);
    const bar = await screen.findByRole("button", { name: /^Italy · \$11/ });
    await user.click(bar);
    await waitFor(() => expect(window.location.search).toContain("partner=380"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Azerbaijan ↔ Italy/)).toBeTruthy();
  });

  it("closes the drilldown and clears the URL parameter", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/trade/country/AZE?product=27");
    render(<App />);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /close panel/i }));
    await waitFor(() => expect(window.location.search).not.toContain("product=27"));
  });
});

describe("loading and degraded states", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/trade/country/AZE");
  });

  it("shows a preparing state for a country that is not cached", async () => {
    setRoute(
      "/country/AZE/summary",
      {
        data: {
          status: "preparing",
          message: "Preparing trade data for Azerbaijan",
          job: { id: 7, status: "queued", progress: null },
        },
        meta: META,
      },
      202,
    );
    render(<App />);
    expect(await screen.findByText("Preparing trade data for Azerbaijan")).toBeTruthy();
    expect(await screen.findByText(/Fetching annual trade summary/)).toBeTruthy();
  });

  it("shows an error without blanking the page", async () => {
    setRoute("/country/AZE/summary", { detail: "Backend unavailable" }, 500);
    render(<App />);
    expect(await screen.findByText("Backend unavailable")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "Azerbaijan" })).toBeTruthy();
  });

  it("marks an incomplete period as partial", async () => {
    setRoute("/country/AZE/summary", {
      ...SUMMARY,
      meta: { ...META, partial: true, latest_annual: 2026, latest_complete_annual: 2025 },
    });
    render(<App />);
    expect((await screen.findAllByText(/Partial/)).length).toBeGreaterThan(0);
  });

  it("renders an empty ranking as 'no reported data', not zero", async () => {
    setRoute("/country/AZE/summary", {
      ...SUMMARY,
      data: {
        ...SUMMARY.data,
        export_products: { items: [], other: null, total: null, count: 0, available: false },
      },
    });
    render(<App />);
    expect(await screen.findByText("No reported export composition")).toBeTruthy();
  });

  it("renders a missing KPI as an em dash", async () => {
    setRoute("/country/AZE/summary", {
      ...SUMMARY,
      data: { ...SUMMARY.data, kpis: { ...SUMMARY.data.kpis, balance: null } },
    });
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Azerbaijan" });
    expect((await screen.findAllByText("—")).length).toBeGreaterThan(0);
  });
});

describe("methodology", () => {
  it("is reachable and explains the mirror caveat", async () => {
    window.history.replaceState({}, "", "/trade/methodology");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Methodology" })).toBeTruthy();
    expect(await screen.findByText(/CIF versus FOB valuation/)).toBeTruthy();
  });
});
