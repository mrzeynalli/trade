import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { EChart } from "../components/EChart";
import { Flag } from "../components/Flag";
import { Panel } from "../components/Panel";
import { Segment } from "../components/Segment";
import { mapLegendStops, worldMapOption } from "../components/charts";
import { worldRegionNames } from "../components/EChart";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/States";
import { compactUsd, exactUsd, percent, signedPercent } from "../lib/format";
import { query } from "../lib/api";
import { useResource } from "../lib/useResource";
import type { Country, WorldOverview, WorldRow } from "../types";

type Props = { onSelect: (iso: string) => void };

type SortKey = "exports" | "imports" | "name" | "change";

export function Countries({ onSelect }: Props) {
  const [term, setTerm] = useState("");
  const [sort, setSort] = useState<SortKey>("exports");
  const [mapFlow, setMapFlow] = useState<"X" | "M">("X");

  const world = useResource<WorldOverview>(`/world/overview${query({ top: 25 })}`);
  const countries = useResource<Country[]>("/meta/countries");
  const data = world.data;

  const iso2 = useMemo(() => {
    const map = new Map<number, string>();
    for (const entry of countries.data ?? []) if (entry.iso2) map.set(entry.code, entry.iso2);
    return map;
  }, [countries.data]);

  const rows = useMemo(() => {
    const needle = term.trim().toLowerCase();
    const base = (data?.map ?? []).filter(
      (row) =>
        !needle ||
        row.name.toLowerCase().includes(needle) ||
        (row.iso3 ?? "").toLowerCase().includes(needle) ||
        (iso2.get(row.code) ?? "").toLowerCase().includes(needle),
    );
    // Countries with nothing to sort on go last whichever way the column
    // sorts, rather than being treated as zero or as the largest value.
    const rank = (row: WorldRow): number | null => {
      if (sort === "change") return row.change ?? null;
      if (sort === "imports") return row.imports ?? null;
      return row.value ?? null;
    };
    const sorted = [...base];
    if (sort === "name") sorted.sort((a, b) => a.name.localeCompare(b.name));
    else
      sorted.sort((a, b) => {
        const left = rank(a);
        const right = rank(b);
        if (left === null && right === null) return a.name.localeCompare(b.name);
        if (left === null) return 1;
        if (right === null) return -1;
        return right - left;
      });
    return sorted;
  }, [data?.map, term, sort, iso2]);

  const mapOption = useMemo(() => {
    if (!data?.map?.length) return null;
    const source = mapFlow === "X" ? data.map : (data.map_imports ?? []);
    return worldMapOption(
      source.map((r) => ({ code: r.code, name: r.name, value: r.value, share: r.share ?? null })),
      mapFlow,
      worldRegionNames,
    );
  }, [data?.map, data?.map_imports, mapFlow]);

  return (
    <>
      <div className="page-head">
        <span className="eyebrow">Browse</span>
        <h1>Countries</h1>
        <p>
          Every country that reported merchandise trade for {data?.year ?? "the latest available year"}.
          Select a country to open its full trade profile.
        </p>
      </div>

      {world.status === "error" && (
        <ErrorBlock message={world.error ?? "Could not load countries"} onRetry={world.reload} />
      )}
      {world.status === "loading" && <div className="skeleton" />}

      {world.status === "ready" && data?.available && (
        <>
          <Panel
            eyebrow="Geography"
            title={mapFlow === "X" ? "Exports by country" : "Imports by country"}
            description="Equal-area projection. Select a country to open it."
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
            {mapOption && (
              <EChart
                option={mapOption}
                className="chart map"
                needsMap
                ariaLabel={`World map shaded by reported ${mapFlow === "X" ? "exports" : "imports"} in ${data.year}.`}
                onSelect={(params) => {
                  const entry = params.data as { code?: number } | undefined;
                  const code = entry?.code ?? Number(params.name);
                  const match = data.map.find((r) => r.code === code);
                  if (match?.iso3) onSelect(match.iso3);
                }}
              />
            )}
          </Panel>

          <div style={{ marginTop: 16 }}>
            <Panel
              eyebrow="Directory"
              title={`${rows.length} reporting ${rows.length === 1 ? "country" : "countries"}`}
              description={`Reported values for ${data.year}.`}
              action={
                <Segment
                  label="Sort"
                  value={sort}
                  onChange={setSort}
                  options={[
                    { value: "exports", label: "Exports" },
                    { value: "imports", label: "Imports" },
                    { value: "change", label: "Growth" },
                    { value: "name", label: "A–Z" },
                  ]}
                />
              }
            >
              <div className="search-field" style={{ marginBottom: 14 }}>
                <Search size={16} />
                <input
                  type="search"
                  value={term}
                  placeholder="Filter by country name or ISO code"
                  aria-label="Filter countries"
                  onChange={(event) => setTerm(event.target.value)}
                />
              </div>

              {rows.length === 0 ? (
                <EmptyBlock title={`Nothing matches “${term}”`} />
              ) : (
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th className="num">#</th>
                        <th>Country</th>
                        <th className="num">Exports</th>
                        <th className="num">Imports</th>
                        <th className="num">Share of world</th>
                        <th className="num">YoY</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, index) => (
                        <tr key={row.code}>
                          <td className="num rank">{index + 1}</td>
                          <td>
                            <span className="with-flag">
                              <Flag iso2={iso2.get(row.code)} />
                              <button
                                type="button"
                                className="row-link"
                                onClick={() => row.iso3 && onSelect(row.iso3)}
                              >
                                {row.name}
                              </button>
                            </span>
                          </td>
                          <td className="num" title={exactUsd(row.value)}>{compactUsd(row.value)}</td>
                          <td className="num" title={exactUsd(row.imports ?? null)}>{compactUsd(row.imports ?? null)}</td>
                          <td className="num">{percent(row.share, 2)}</td>
                          <td className="num">
                            <span
                              className={
                                row.change === null || row.change === undefined
                                  ? ""
                                  : row.change >= 0 ? "delta up" : "delta down"
                              }
                            >
                              {signedPercent(row.change)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
      {world.status === "ready" && !data?.available && (
        <EmptyBlock title="No country data yet" />
      )}
      {countries.status === "loading" && <LoadingBlock />}
    </>
  );
}
