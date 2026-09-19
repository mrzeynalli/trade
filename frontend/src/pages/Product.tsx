import { ArrowLeft, Boxes } from "lucide-react";
import { useEffect, useMemo } from "react";
import { EChart } from "../components/EChart";
import { Flag } from "../components/Flag";
import { InfoTip } from "../components/InfoTip";
import { Panel } from "../components/Panel";
import { Segment } from "../components/Segment";
import { EmptyBlock, ErrorBlock } from "../components/States";
import { productSeriesOption } from "../components/charts";
import { compactUsd, exactUsd, percent, signedPercent } from "../lib/format";
import { query } from "../lib/api";
import { useResource } from "../lib/useResource";
import type { Country, WorldProduct } from "../types";

type Props = {
  code: string;
  params: URLSearchParams;
  setParams: (params: Record<string, string | null>) => void;
  onSelectCountry: (iso: string) => void;
  onBack: () => void;
};

/**
 * A chapter's own page, reached the way a country's is.
 *
 * The chapter was previously a panel that swapped in below the list, which made
 * it impossible to link to and easy to miss. Everything here is read from the
 * global HS2 matrix, so the page has no preparation step of its own.
 */
export function Product({ code, params, setParams, onSelectCountry, onBack }: Props) {
  const year = params.get("year");
  const product = useResource<WorldProduct>(`/world/product/${code}${query({ year })}`);
  const countries = useResource<Country[]>("/meta/countries");
  const data = product.data;

  const iso2 = useMemo(() => {
    const map = new Map<number, string>();
    for (const entry of countries.data ?? []) if (entry.iso2) map.set(entry.code, entry.iso2);
    return map;
  }, [countries.data]);

  useEffect(() => {
    document.title = data?.name
      ? `${data.name} — Global Trade Intelligence`
      : `HS ${code} — Global Trade Intelligence`;
  }, [data?.name, code]);

  const trendOption = useMemo(() => {
    if (!data?.series?.length || data.series.length < 2) return null;
    return productSeriesOption(data.series);
  }, [data?.series]);

  return (
    <>
      <div className="country-header">
        <div className="country-title">
          <div className="country-flag" aria-hidden="true">
            <Boxes size={26} />
          </div>
          <div>
            <span className="eyebrow">Product chapter</span>
            <h1>{data?.name ?? `Chapter ${code}`}</h1>
            <p>
              <span className="code">HS {code}</span> · UN Comtrade merchandise trade · values in
              current US dollars
            </p>
          </div>
        </div>
        <div className="provenance">
          <button type="button" className="link-button" onClick={onBack}>
            <ArrowLeft size={14} style={{ verticalAlign: -2, marginRight: 6 }} />
            All chapters
          </button>
        </div>
      </div>

      {product.status === "error" && (
        <ErrorBlock
          message={product.error ?? "Could not load this chapter"}
          onRetry={product.reload}
        />
      )}

      {product.status === "loading" && <div className="skeleton" />}

      {product.status === "ready" && !data?.available && (
        <EmptyBlock title="No reported data for this chapter">{data?.reason}</EmptyBlock>
      )}

      {product.status === "ready" && data?.available && (
        <>
          {data.years && data.years.length > 1 && (
            <div className="control-rail">
              <div className="control-group">
                <span>Year</span>
                <Segment
                  label="Reference year"
                  value={String(data.year)}
                  onChange={(value) => setParams({ year: value })}
                  options={data.years.map((entry) => ({
                    value: String(entry),
                    label: String(entry),
                  }))}
                />
              </div>
              <div className="rail-spacer" />
            </div>
          )}

          <div className="stat-strip">
            <div>
              <span className="label">Reported world exports</span>
              <span className="value export serif numeric" title={exactUsd(data.world_total)}>
                {compactUsd(data.world_total)}
              </span>
              <span className="note">
                {data.change === null || data.change === undefined
                  ? `in ${data.year}`
                  : `${signedPercent(data.change)} on ${(data.year ?? 0) - 1}`}
              </span>
            </div>
            <div>
              <span className="label">Reported world imports</span>
              <span
                className="value import serif numeric"
                title={exactUsd(data.world_import_total)}
              >
                {compactUsd(data.world_import_total)}
              </span>
              <span className="note">cost, insurance and freight</span>
            </div>
            <div>
              <span className="label">Supplier concentration</span>
              <span className="value serif numeric">
                {data.concentration === null || data.concentration === undefined
                  ? "—"
                  : data.concentration.toFixed(3)}
              </span>
              <span className="note">
                {concentrationWord(data.concentration)} · Herfindahl index
              </span>
            </div>
            <div>
              <span className="label">Reporting countries</span>
              <span className="value serif numeric">{data.reporters ?? "—"}</span>
              <span className="note">published this chapter for {data.year}</span>
            </div>
          </div>

          {trendOption && (
            <div style={{ marginTop: 16 }}>
              <Panel
                eyebrow="Trajectory"
                title="Reported world trade in this chapter"
                description="The sum of what every reporting country published for each year."
                footnote="Years are only comparable where a similar set of countries reported. The reporter count travels with each point."
              >
                <EChart
                  option={trendOption}
                  className="chart short"
                  ariaLabel={`World exports of HS ${code} across ${data.series?.length ?? 0} years.`}
                />
              </Panel>
            </div>
          )}

          <div className="grid grid-2" style={{ marginTop: 16 }}>
            <Panel
              eyebrow="Supply"
              title="Who exports this?"
              description={`Largest reported exporters in ${data.year}. Select a country to open its full trade profile.`}
              action={
                <InfoTip title="Supplier concentration">
                  <p style={{ margin: 0 }}>
                    The Herfindahl index sums the squared share of every exporter. Below 0.15 is a
                    competitive market, 0.15–0.25 moderately concentrated, above 0.25 concentrated.
                    It is computed across every reporting country, not just the ones listed here.
                  </p>
                </InfoTip>
              }
              bodyClassName="flush"
              footnote={data.coverage?.note}
            >
              <RankList
                rows={data.exporters ?? []}
                iso2={iso2}
                tone="export"
                onSelect={onSelectCountry}
                measure="of reported world exports of this chapter"
              />
            </Panel>

            <Panel
              eyebrow="Demand"
              title="Who imports this?"
              description={`Largest reported importers in ${data.year}. ${data.import_reporters ?? 0} countries reported buying this chapter.`}
              bodyClassName="flush"
            >
              <RankList
                rows={data.importers ?? []}
                iso2={iso2}
                tone="import"
                onSelect={onSelectCountry}
                measure="of reported world imports of this chapter"
              />
            </Panel>
          </div>
        </>
      )}
    </>
  );
}

/** Below 0.15 competitive, 0.15–0.25 moderate, above concentrated. */
function concentrationWord(value: number | null | undefined): string {
  if (value === null || value === undefined) return "not computable";
  if (value < 0.15) return "Competitive";
  if (value < 0.25) return "Moderately concentrated";
  return "Concentrated";
}

function RankList({
  rows, iso2, tone, onSelect, measure,
}: {
  rows: NonNullable<WorldProduct["exporters"]>;
  iso2: Map<number, string>;
  tone: "export" | "import";
  onSelect: (iso: string) => void;
  measure: string;
}) {
  if (!rows.length) return <EmptyBlock title="No reported data" />;
  const max = rows[0].value || 1;
  return (
    <ul className="bar-list">
      {rows.map((row) => (
        <li key={row.code}>
          <button
            type="button"
            className="bar-row"
            onClick={() => row.iso3 && onSelect(row.iso3)}
            aria-label={`${row.name}, ${exactUsd(row.value)}, ${percent(row.share)} ${measure}`}
            style={{
              ["--bar-width" as string]: `${Math.max(2, (row.value / max) * 100)}%`,
              ["--bar-color" as string]: `var(--${tone}-wash)`,
            }}
          >
            <span className="label with-flag">
              <Flag iso2={row.iso2 ?? iso2.get(row.code)} />
              <span>{row.name}</span>
            </span>
            <span className="amount numeric">{compactUsd(row.value)}</span>
            <span className="pct numeric">{percent(row.share)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
