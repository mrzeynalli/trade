import { Globe2, TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { CountrySearch } from "../components/CountrySearch";
import { Flag } from "../components/Flag";
import { EChart } from "../components/EChart";
import { InfoTip } from "../components/InfoTip";
import { Panel } from "../components/Panel";
import { Segment } from "../components/Segment";
import { EmptyBlock, ErrorBlock } from "../components/States";
import {
  dualSeriesOption, mapLegendStops, opennessScatterOption, treemapOption, worldMapOption,
} from "../components/charts";
import { worldRegionNames } from "../components/EChart";
import { compactUsd, exactUsd, percent, signedPercent } from "../lib/format";
import { query } from "../lib/api";
import { useResource } from "../lib/useResource";
import type {
  Country, EuropeOverview, WorldOverview as WorldOverviewData, WorldRecent, WorldRow,
} from "../types";

type Props = { onSelect: (iso: string) => void; onBrowseAll: () => void };

export function Dashboard({ onSelect, onBrowseAll }: Props) {
  const [mapFlow, setMapFlow] = useState<"X" | "M">("X");
  const world = useResource<WorldOverviewData>(`/world/overview${query({ top: 12 })}`);
  const countries = useResource<Country[]>("/meta/countries");
  const recent = useResource<WorldRecent>("/world/recent");
  const europe = useResource<EuropeOverview>("/world/europe");
  const data = world.data;
  const fresh = recent.data?.available ? recent.data : null;
  const eu = europe.data?.available ? europe.data : null;

  const nameByCode = useMemo(() => {
    const map = new Map<number, string>();
    for (const row of data?.map ?? []) map.set(row.code, row.name);
    return map;
  }, [data?.map]);

  const isoByCode = useMemo(() => {
    const map = new Map<number, string>();
    for (const row of data?.map ?? []) if (row.iso3) map.set(row.code, row.iso3);
    return map;
  }, [data?.map]);

  // Flags are keyed on ISO alpha-2, which only the reporter list carries.
  const isoTwoByCode = useMemo(() => {
    const map = new Map<number, string>();
    for (const entry of countries.data ?? []) if (entry.iso2) map.set(entry.code, entry.iso2);
    return map;
  }, [countries.data]);

  // Eurostat identifies member states by ISO alpha-3, so the flag lookup needs
  // that key rather than the reporter code the rest of this page uses.
  const isoTwoByIso3 = useMemo(() => {
    const map = new Map<string, string>();
    for (const entry of countries.data ?? []) {
      if (entry.iso3 && entry.iso2) map.set(entry.iso3, entry.iso2);
    }
    return map;
  }, [countries.data]);

  const open = (code: number) => {
    const iso = isoByCode.get(code);
    if (iso) onSelect(iso);
  };

  const trendOption = useMemo(() => {
    if (!data?.series?.length) return null;
    return dualSeriesOption(
      data.series.map((point) => ({
        period: String(point.year),
        exports: point.exports,
        imports: point.imports,
      })),
      "A",
      { showBalanceBand: true },
    );
  }, [data?.series]);

  const mapOption = useMemo(() => {
    if (!data?.map?.length) return null;
    const rows = mapFlow === "X" ? data.map : (data.map_imports ?? []);
    return worldMapOption(
      rows.map((r) => ({ code: r.code, name: r.name, value: r.value, share: r.share ?? null })),
      mapFlow,
      worldRegionNames,
    );
  }, [data?.map, data?.map_imports, mapFlow]);

  const treeOption = useMemo(() => {
    if (!data?.products?.available || !data.products.items) return null;
    return treemapOption(data.products.items, data.products.other ?? null, "X");
  }, [data?.products]);

  const scatterOption = useMemo(() => {
    if (!data?.openness?.length) return null;
    return opennessScatterOption(
      data.openness.map((row) => ({
        code: row.code,
        name: row.name,
        gdpPerCapita: row.gdp_per_capita,
        openness: row.openness,
        trade: row.trade,
      })),
    );
  }, [data?.openness]);

  return (
    <>
      <section className="hero">
          <div className="hero-kicker">
            <span className="eyebrow"><Globe2 size={13} /> UN Comtrade · World Bank</span>
            {data?.partial && <span className="badge partial">Partial year</span>}
          </div>
          <h1 className="serif">
            What the world <em>trades</em>.
          </h1>

          {world.status === "ready" && data?.available && (
            <div className="headline-figure">
              <span className="amount serif">{compactUsd(data.totals.exports)}</span>
              <span className="caption">
                reported world exports in <b>{data.year}</b>, from{" "}
                <b>{data.totals.reporters}</b> reporting countries
                {data.totals.export_change !== null && (
                  <>
                    {" · "}
                    <b className={data.totals.export_change >= 0 ? "delta up" : "delta down"}>
                      {signedPercent(data.totals.export_change)}
                    </b>{" "}
                    on {data.year - 1}
                  </>
                )}
              </span>
            </div>
          )}

          {fresh && (
            <p className="recency-note">
              <span className="eyebrow">Most recent reading</span>
              <span>
                <b>{compactUsd(fresh.totals.exports)}</b> world exports in{" "}
                <b>{fresh.year}</b> across <b>{fresh.countries}</b> countries, from the{" "}
                <b>IMF</b>. UN Comtrade — the source for everything below, and the only
                one with partner and product detail — has published{" "}
                <b>{fresh.comtrade_countries}</b> countries for {fresh.year} so far
                {fresh.monthly && (
                  <>, and IMF monthly figures reach <b>{fresh.monthly.label}</b></>
                )}
                . The two are never added together.
              </span>
            </p>
          )}

          <div style={{ maxWidth: 620, marginTop: 30 }}>
            <CountrySearch
              countries={countries.data ?? []}
              onSelect={(country) => onSelect(country.iso3 ?? String(country.code))}
              placeholder="Search any country — Azerbaijan, DEU, Japan…"
            />
          </div>
      </section>

      <div>
          {world.status === "error" && (
            <ErrorBlock message={world.error ?? "Could not load the world overview"} onRetry={world.reload} />
          )}
          {world.status === "loading" && <div className="skeleton" />}
          {world.status === "ready" && !data?.available && (
            <EmptyBlock title="No country data yet">
              Run the backfill to populate the world view.
            </EmptyBlock>
          )}

          {world.status === "ready" && data?.available && (
            <>
              <div className="stat-strip">
                <div>
                  <span className="label">World exports</span>
                  <span className="value export serif numeric" title={exactUsd(data.totals.exports)}>
                    {compactUsd(data.totals.exports)}
                  </span>
                  <span className="note">{signedPercent(data.totals.export_change)} on {data.year - 1}</span>
                </div>
                <div>
                  <span className="label">World imports</span>
                  <span className="value import serif numeric" title={exactUsd(data.totals.imports)}>
                    {compactUsd(data.totals.imports)}
                  </span>
                  <span className="note">{signedPercent(data.totals.import_change)} on {data.year - 1}</span>
                </div>
                <div>
                  <span className="label">Reported gap</span>
                  <span className={`value serif numeric ${(data.totals.balance ?? 0) < 0 ? "negative" : ""}`}>
                    {compactUsd(data.totals.balance)}
                  </span>
                  <span className="note">exports less imports, as reported</span>
                </div>
                <div>
                  <span className="label">Reporting countries</span>
                  <span className="value serif numeric">{data.totals.reporters}</span>
                  <span className="note">published for {data.year}</span>
                </div>
              </div>

              <div className="grid grid-hero" style={{ marginTop: 22 }}>
                <Panel
                  eyebrow="Trajectory"
                  title="Reported world trade"
                  description="The sum of what every reporting country published each year."
                  footnote={data.series_note}
                >
                  {trendOption ? (
                    <EChart
                      option={trendOption}
                      className="chart tall"
                      ariaLabel={`Reported world exports and imports from ${data.series[0]?.year} to ${data.year}. Exports reached ${exactUsd(data.totals.exports)} in ${data.year}.`}
                    />
                  ) : (
                    <EmptyBlock title="No series available" />
                  )}
                </Panel>

                <Panel
                  eyebrow="Largest traders"
                  title={`Who trades most, ${data.year}`}
                  description="Select a country to open its full trade profile."
                  bodyClassName="flush"
                >
                  <RankList rows={data.top_traders} onSelect={open} flow="X" showShare flags={isoTwoByCode} />
                </Panel>
              </div>

              <div style={{ marginTop: 16 }}>
                <Panel
                  eyebrow="Geography"
                  title={mapFlow === "X" ? "Exports by country" : "Imports by country"}
                  description="Shading is on a square-root scale, because trade is heavily skewed towards a handful of economies. Select a country to open it."
                  action={
                    <Segment
                      label="Map flow"
                      value={mapFlow}
                      onChange={setMapFlow}
                      options={[
                        { value: "X", label: "Exports" },
                        { value: "M", label: "Imports" },
                      ]}
                    />
                  }
                  footnote={data.coverage.note}
                >
                  <div className="map-legend" aria-hidden="true">
                    <span>Less</span>
                    {mapLegendStops(mapFlow).map((stop) => (
                      <i key={stop.color} style={{ background: stop.color }} />
                    ))}
                    <span>More</span>
                    <em>No reported data</em>
                    <i className="no-data" />
                  </div>
                  {mapOption ? (
                    <EChart
                      option={mapOption}
                      className="chart map"
                      needsMap
                      ariaLabel={`World map shaded by reported ${mapFlow === "X" ? "exports" : "imports"} in ${data.year}, covering ${data.coverage.reporters} reporting countries.`}
                      onSelect={(params) => {
                        // The region's name is the topology's id, which is not
                        // always the reporter code — read the code the datum
                        // carries and fall back only for regions without one.
                        const entry = params.data as { code?: number } | undefined;
                        const code = entry?.code ?? Number(params.name);
                        if (nameByCode.has(code)) open(code);
                      }}
                    />
                  ) : (
                    <EmptyBlock title="Map unavailable" />
                  )}
                </Panel>
              </div>

              <div className="grid grid-2" style={{ marginTop: 16 }}>
                <Panel
                  eyebrow="Momentum"
                  title="Fastest-growing exporters"
                  description={`Year-on-year change among countries exporting at least $5B, ${data.year - 1} to ${data.year}.`}
                >
                  <ChangeList rows={data.fastest_growing} onSelect={open} direction="up" flags={isoTwoByCode} />
                </Panel>
                <Panel
                  eyebrow="Momentum"
                  title="Largest export declines"
                  description="The same threshold applies, so a small base cannot produce a misleading percentage."
                >
                  <ChangeList rows={data.largest_declines} onSelect={open} direction="down" flags={isoTwoByCode} />
                </Panel>
              </div>

              {treeOption && (
                <div style={{ marginTop: 16 }}>
                  <Panel
                    eyebrow="Composition"
                    title={`What the world exports, ${data.year}`}
                    description="HS chapters sized by reported world export value. Area encodes value, so the shape of global trade is legible at a glance."
                  >
                    <EChart
                      option={treeOption}
                      className="chart tall"
                      ariaLabel={`Treemap of world exports by HS chapter in ${data.year}. The largest is ${data.products.items?.[0]?.name} at ${percent(data.products.items?.[0]?.share)}.`}
                    />
                  </Panel>
                </div>
              )}

              {scatterOption && (
                <div style={{ marginTop: 16 }}>
                  <Panel
                    eyebrow="Trade and income"
                    title="How open is each economy?"
                    description="Total trade as a share of GDP, against income per head. Each bubble is a country, sized by total trade."
                    action={
                      <InfoTip title="Trade openness">
                        <p style={{ margin: "0 0 8px" }}>
                          Openness is (exports + imports) ÷ GDP. Small economies and entrepôts
                          routinely exceed 100%, because goods can cross a border more than once
                          and trade is measured gross while GDP is measured as value added.
                        </p>
                        <p style={{ margin: 0 }}>
                          Trade comes from UN Comtrade and GDP from the World Bank; the two are
                          published on different schedules.
                        </p>
                      </InfoTip>
                    }
                    footnote="Trade: UN Comtrade. GDP and population: World Bank. Countries missing either source are omitted rather than estimated."
                  >
                    <EChart
                      option={scatterOption}
                      className="chart tall"
                      ariaLabel={`Scatter plot of trade openness against GDP per capita for ${data.openness.length} countries in ${data.year}.`}
                      onSelect={(params) => {
                        const entry = params.data as { code?: number } | undefined;
                        if (entry?.code) open(entry.code);
                      }}
                    />
                  </Panel>
                </div>
              )}

              {eu && (
                <div style={{ marginTop: 16 }}>
                  <Panel
                    eyebrow="Single market"
                    title="How much of Europe's trade stays inside Europe?"
                    description={`Share of each member state's goods exports going to the rest of the EU rather than beyond it, ${eu.label}. Across the Union as a whole, ${percent(eu.union.intra_share)} stays inside.`}
                    action={
                      <InfoTip title="Intra and extra-EU trade">
                        <p style={{ margin: "0 0 8px" }}>
                          Intra-EU movements are collected through Intrastat declarations and
                          extra-EU movements at the customs frontier, so this split is reported
                          rather than derived. UN Comtrade cannot express it: it sees the Union
                          as 27 separate reporters, and reconstructing the split would mean
                          summing 26 bilateral partners per country.
                        </p>
                        <p style={{ margin: 0 }}>
                          Eurostat publishes about six weeks after month end, so this is the
                          most recent trade reading on the site. Values are euro and are never
                          added to the dollar figures elsewhere.
                        </p>
                      </InfoTip>
                    }
                    footnote={eu.coverage.note}
                  >
                    <ul className="bar-list">
                      {eu.members.map((member) => (
                        <li key={member.iso3}>
                          <div
                            className="bar-row"
                            title={`${member.name}: ${percent(member.intra_export_share)} inside the EU, ${percent(member.extra_export_share)} beyond it`}
                            style={{
                              ["--bar-width" as string]: `${(member.intra_export_share ?? 0) * 100}%`,
                              ["--bar-color" as string]: "var(--export-wash)",
                            }}
                          >
                            <span className="label with-flag">
                              <Flag iso2={isoTwoByIso3.get(member.iso3)} />
                              {member.name}
                            </span>
                            <span className="value numeric">{percent(member.intra_export_share)}</span>
                            <span className="pct numeric">{percent(member.extra_export_share)} beyond</span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </Panel>
                </div>
              )}

              <div style={{ marginTop: 16 }}>
                <Panel
                  eyebrow="Browse"
                  title="Every reporting country"
                  description={`${data.map.length} countries reported for ${data.year}, with exports, imports, world share and growth.`}
                >
                  <button type="button" className="link-button" onClick={onBrowseAll}>
                    Open the country directory
                  </button>
                </Panel>
              </div>
            </>
          )}
      </div>
    </>
  );
}

function RankList({
  rows, onSelect, flow, showShare, flags,
}: {
  rows: WorldRow[];
  onSelect: (code: number) => void;
  flow: "X" | "M";
  showShare?: boolean;
  flags: Map<number, string>;
}) {
  if (!rows.length) return <EmptyBlock title="No reported data" />;
  const max = Math.max(...rows.map((r) => r.value), 1);
  const wash = flow === "X" ? "var(--export-wash)" : "var(--import-wash)";
  return (
    <ul className="bar-list">
      {rows.map((row) => (
        <li key={row.code}>
          <button
            type="button"
            className="bar-row"
            onClick={() => onSelect(row.code)}
            aria-label={`${row.name}, ${exactUsd(row.value)}${showShare ? `, ${percent(row.share)} of world exports` : ""}`}
            style={{
              ["--bar-width" as string]: `${Math.max(2, (row.value / max) * 100)}%`,
              ["--bar-color" as string]: wash,
            }}
          >
            <span className="label with-flag">
              <Flag iso2={flags.get(row.code)} />
              <span>{row.name}</span>
            </span>
            <span className="amount numeric">{compactUsd(row.value)}</span>
            {showShare && <span className="pct numeric">{percent(row.share)}</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}

function ChangeList({
  rows, onSelect, direction, flags,
}: {
  rows: WorldRow[];
  onSelect: (code: number) => void;
  direction: "up" | "down";
  flags: Map<number, string>;
}) {
  if (!rows.length) return <EmptyBlock title="Not enough comparable data" />;
  const Icon = direction === "up" ? TrendingUp : TrendingDown;
  return (
    <ul className="change-list">
      {rows.map((row) => (
        <li key={row.code}>
          <span className="name with-flag">
            <Flag iso2={flags.get(row.code)} />
            <button type="button" className="row-link" onClick={() => onSelect(row.code)}>
              {row.name}
            </button>
          </span>
          <span className={`abs ${direction} numeric`}>
            <Icon size={12} style={{ verticalAlign: -1, marginRight: 4 }} />
            {signedPercent(row.change)}
          </span>
          <span className="rel">{compactUsd(row.value)}</span>
        </li>
      ))}
    </ul>
  );
}
