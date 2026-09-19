import { AlertTriangle, Lightbulb, TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { EChart } from "../../components/EChart";
import { InfoTip } from "../../components/InfoTip";
import { Panel } from "../../components/Panel";
import { Segment } from "../../components/Segment";
import { concentrationOption } from "../../components/charts";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../../components/States";
import { compactUsd, percent, periodLabel, signedPercent } from "../../lib/format";
import { query } from "../../lib/api";
import { useResource } from "../../lib/useResource";
import type { AdvancedView, AnomalyView, BalanceView, ConcentrationProfile, GrowthTable, Insights } from "../../types";

type Props = { token: string; freq: "A" | "M"; countryName: string; monthlyAvailable: boolean };

export function InsightsTab({ token, freq, countryName, monthlyAvailable }: Props) {
  const [dimension, setDimension] = useState<"product" | "partner">("product");
  const insights = useResource<Insights>(`/country/${token}/insights${query({ freq })}`);
  const balance = useResource<BalanceView>(`/country/${token}/balance${query({ freq })}`);
  const advanced = useResource<AdvancedView>(`/country/${token}/advanced`);
  const anomalies = useResource<AnomalyView>(monthlyAvailable ? `/country/${token}/anomalies` : null);

  if (insights.status === "error") {
    return <ErrorBlock message={insights.error ?? "Could not load insights"} onRetry={insights.reload} />;
  }
  if (insights.status !== "ready" || !insights.data) return <LoadingBlock label="Computing insights" />;

  const data = insights.data;
  const history = data.concentration_history.filter(
    (row) => row.flow_code === "X" && row.dimension === dimension,
  );

  return (
    <>
      {data.sentences.length > 0 && (
        <Panel
          eyebrow="Summary"
          title="What the data says"
          description="Generated from the same figures shown in the charts on this page."
        >
          <ul className="insight-list">
            {data.sentences.map((sentence) => (
              <li key={sentence}>
                <Lightbulb size={15} aria-hidden="true" />
                <span>{sentence}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <div className="grid grid-2" style={{ marginTop: 11 }}>
        <Panel
          eyebrow="Dependency"
          title="How concentrated is trade?"
          description={`Share of ${countryName}'s reported flows held by the largest categories and partners, ${data.composition_period}.`}
          action={
            <InfoTip title="Concentration measures">
              <p style={{ margin: "0 0 8px" }}>
                <b>HHI</b> is the sum of squared shares, on a 0–1 scale. Higher means more
                concentrated.
              </p>
              <p style={{ margin: 0 }}>
                <b>Effective number of categories</b> is 1 / HHI: how many equally sized categories
                would produce the same concentration.
              </p>
            </InfoTip>
          }
        >
          <div className="metric-grid">
            <DependencyMetric label="Export products" profile={data.dependency.export_products} />
            <DependencyMetric label="Export partners" profile={data.dependency.export_partners} />
            <DependencyMetric label="Import products" profile={data.dependency.import_products} />
            <DependencyMetric label="Import partners" profile={data.dependency.import_partners} />
          </div>
        </Panel>

        <Panel
          eyebrow="Diversification"
          title="Export concentration over time"
          description="Whether the export basket is becoming more concentrated or more diversified."
          action={
            <Segment
              label="Concentration dimension"
              value={dimension}
              onChange={setDimension}
              options={[
                { value: "product", label: "Products" },
                { value: "partner", label: "Partners" },
              ]}
            />
          }
        >
          {history.length >= 2 ? (
            <EChart
              className="chart short"
              option={concentrationOption(
                history.map((row) => ({
                  year: row.year,
                  hhi: row.hhi,
                  effective: row.effective_number,
                })),
              )}
              ariaLabel={`Export ${dimension} concentration for ${countryName} from ${history[0].year} to ${history[history.length - 1].year}, HHI moving from ${history[0].hhi?.toFixed(2)} to ${history[history.length - 1].hhi?.toFixed(2)}.`}
            />
          ) : (
            <EmptyBlock title="Not enough history" >Concentration needs at least two years of data.</EmptyBlock>
          )}
        </Panel>
      </div>

      <div className="grid grid-2" style={{ marginTop: 11 }}>
        <GrowthPanel
          title="Export change by category"
          table={data.product_growth}
          freq={freq}
        />
        <GrowthPanel
          title="Export change by partner"
          table={data.partner_growth}
          freq={freq}
        />
      </div>

      {data.export_cagr?.value !== null && data.export_cagr && (
        <div style={{ marginTop: 11 }}>
          <Panel
            eyebrow="Long run"
            title="Compound annual export growth"
            description={`Computed over ${data.export_cagr.years} years, ${data.export_cagr.from} to ${data.export_cagr.to}. Nominal US dollars, not adjusted for inflation.`}
          >
            <div className="stat-row">
              <div className="stat">
                <span>CAGR</span>
                <strong className="numeric">{signedPercent(data.export_cagr.value)}</strong>
                <small>per year, {data.export_cagr.from}–{data.export_cagr.to}</small>
              </div>
            </div>
          </Panel>
        </div>
      )}

      <div className="grid grid-2" style={{ marginTop: 11 }}>
        <Panel
          eyebrow="Balance"
          title="Largest bilateral gaps"
          description={`Reported surpluses and deficits by partner, ${balance.data?.composition_period ?? ""}.`}
        >
          {balance.status === "ready" && balance.data ? (
            <div className="rank-columns">
              <div>
                <h3>Largest surpluses</h3>
                <BalanceList rows={balance.data.partner_surpluses} />
              </div>
              <div>
                <h3>Largest deficits</h3>
                <BalanceList rows={balance.data.partner_deficits} />
              </div>
            </div>
          ) : (
            <LoadingBlock />
          )}
        </Panel>

        <Panel
          eyebrow="Balance"
          title="Largest product gaps"
          description="HS chapters where reported exports and imports diverge most."
        >
          {balance.status === "ready" && balance.data ? (
            <div className="rank-columns">
              <div>
                <h3>Largest surpluses</h3>
                <BalanceList rows={balance.data.product_surpluses} />
              </div>
              <div>
                <h3>Largest deficits</h3>
                <BalanceList rows={balance.data.product_deficits} />
              </div>
            </div>
          ) : (
            <LoadingBlock />
          )}
        </Panel>
      </div>

      <div className="grid grid-2" style={{ marginTop: 11 }}>
        <Panel
          eyebrow="Global position"
          title="Share of reported world exports"
          description={
            advanced.data?.year
              ? `Where ${countryName} sits in reported global exports, ${advanced.data.year}.`
              : "Requires world product data for a comparable year."
          }
          action={
            <InfoTip title="Reported world exports">
              <p style={{ margin: 0 }}>
                The denominator covers only the reporters that had published for that year. It is
                reported world trade, not a complete world total.
              </p>
            </InfoTip>
          }
          footnote={advanced.data?.coverage?.reporters ? `Denominator covers ${advanced.data.coverage.reporters} reporting countries.` : undefined}
        >
          {advanced.status !== "ready" ? (
            <LoadingBlock />
          ) : advanced.data?.global_share.available ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">HS</th>
                  <th scope="col">Category</th>
                  <th className="num" scope="col">Value</th>
                  <th className="num" scope="col">World share</th>
                </tr>
              </thead>
              <tbody>
                {advanced.data.global_share.items?.slice(0, 8).map((row) => (
                  <tr key={row.code}>
                    <td className="numeric">{row.code}</td>
                    <td>{row.name}</td>
                    <td className="num">{compactUsd(row.value)}</td>
                    <td className="num">{percent(row.share, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyBlock title="Not enough data">
              World product data is not available for a comparable year yet.
            </EmptyBlock>
          )}
        </Panel>

        <Panel
          eyebrow="Specialisation"
          title="Revealed comparative advantage"
          description="Balassa index over HS chapters. Above 1 means the category is a larger share of this country's exports than of reported world exports."
          action={
            <InfoTip title="Balassa RCA">
              <p style={{ margin: 0 }}>
                RCA = (country share of a product in its own exports) ÷ (that product's share of
                reported world exports). It describes a trade pattern; it is not a measure of
                efficiency or of production capability.
              </p>
            </InfoTip>
          }
        >
          {advanced.status !== "ready" ? (
            <LoadingBlock />
          ) : advanced.data?.rca.available ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">HS</th>
                  <th scope="col">Category</th>
                  <th className="num" scope="col">RCA</th>
                </tr>
              </thead>
              <tbody>
                {advanced.data.rca.items?.slice(0, 8).map((row) => (
                  <tr key={row.code}>
                    <td className="numeric">{row.code}</td>
                    <td>{row.name}</td>
                    <td className="num">{row.rca.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyBlock title="Not enough data">
              Comparative advantage needs world product data for a comparable year.
            </EmptyBlock>
          )}
        </Panel>
      </div>

      <div className="grid grid-2" style={{ marginTop: 11 }}>
        <Panel
          eyebrow="Peers"
          title="Countries with a similar export basket"
          description="Finger-Kreinin similarity over HS2 export shares. 100 would mean identical baskets."
        >
          {advanced.status !== "ready" ? (
            <LoadingBlock />
          ) : advanced.data?.similarity.available ? (
            <ul className="change-list">
              {advanced.data.similarity.items?.slice(0, 8).map((row) => (
                <li key={row.code}>
                  <span className="name">{row.name}</span>
                  <span className="abs numeric">{row.similarity.toFixed(1)}</span>
                  <span className="rel">/ 100</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyBlock title="Not enough data">
              Export similarity needs world product data.
            </EmptyBlock>
          )}
        </Panel>

        <Panel
          eyebrow="Monthly signals"
          title="Unusual monthly movements"
          description="Months whose year-on-year growth sits far from this series' own history."
          action={
            <InfoTip title="How this is detected">
              <p style={{ margin: 0 }}>
                Year-on-year growth removes trend and seasonality; the remaining values are scored
                with a median/MAD robust z-score. A flag marks a statistical outlier only. It says
                nothing about why the movement happened.
              </p>
            </InfoTip>
          }
        >
          {!monthlyAvailable ? (
            <EmptyBlock title="Monthly data not available">
              Switch the frequency control to Monthly to load it.
            </EmptyBlock>
          ) : anomalies.status !== "ready" ? (
            <LoadingBlock />
          ) : anomalies.data?.available ? (
            <ul className="change-list">
              {anomalies.data.totals?.map((row) => (
                <li key={`t-${row.period}`}>
                  <span className="name">
                    <AlertTriangle size={12} style={{ verticalAlign: -1, marginRight: 6, color: "var(--status-partial)" }} />
                    Total exports, {periodLabel(row.period)}
                  </span>
                  <span className={`abs ${row.direction === "high" ? "up" : "down"}`}>
                    {signedPercent(row.yoy)}
                  </span>
                  <span className="rel">z {row.robust_z.toFixed(1)}</span>
                </li>
              ))}
              {anomalies.data.products?.map((row) => (
                <li key={`p-${row.code}-${row.period}`}>
                  <span className="name">
                    {row.name}, {periodLabel(row.period)}
                  </span>
                  <span className={`abs ${row.direction === "high" ? "up" : "down"}`}>
                    {signedPercent(row.yoy)}
                  </span>
                  <span className="rel">z {row.robust_z.toFixed(1)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyBlock title="No unusual movements found">
              {`Detected on ${anomalies.data?.months_observed ?? 0} months of history; at least ${anomalies.data?.min_months_required ?? 24} are required.`}
            </EmptyBlock>
          )}
        </Panel>
      </div>
    </>
  );
}

function DependencyMetric({ label, profile }: { label: string; profile: ConcentrationProfile }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className="numeric">{profile.hhi === null ? "—" : profile.hhi.toFixed(2)}</strong>
      <small>
        HHI · {profile.effective_number === null ? "—" : profile.effective_number.toFixed(1)} effective
        categories
        <br />
        Top 1 {percent(profile.top1_share)} · Top 3 {percent(profile.top3_share)} · Top 5{" "}
        {percent(profile.top5_share)}
      </small>
    </div>
  );
}

function GrowthPanel({ title, table, freq }: { title: string; table: GrowthTable; freq: "A" | "M" }) {
  const periodNote = useMemo(() => {
    if (!table.current_period?.length) return "";
    if (freq === "A") return `${table.previous_period?.[0]} → ${table.current_period[0]}`;
    return "Last 12 months vs the 12 before";
  }, [table, freq]);

  return (
    <Panel
      eyebrow="Change"
      title={title}
      description={
        table.available
          ? `${periodNote}. Categories below a minimum baseline are excluded so a tiny base cannot produce a misleading percentage.`
          : "Not enough comparable periods."
      }
    >
      {!table.available ? (
        <EmptyBlock title="Not enough data" />
      ) : (
        <div className="rank-columns">
          <div>
            <h3>
              <TrendingUp size={12} style={{ verticalAlign: -1, marginRight: 5 }} /> Fastest growing
            </h3>
            <ul className="change-list">
              {table.growing.map((entry) => (
                <li key={String(entry.key)}>
                  <span className="name">{entry.name}</span>
                  <span className="abs up numeric">+{compactUsd(entry.absolute_change).replace("$", "$")}</span>
                  <span className="rel">{signedPercent(entry.percent_change)}</span>
                </li>
              ))}
              {table.growing.length === 0 && <li style={{ color: "var(--muted)" }}>None above the baseline</li>}
            </ul>
          </div>
          <div>
            <h3>
              <TrendingDown size={12} style={{ verticalAlign: -1, marginRight: 5 }} /> Largest declines
            </h3>
            <ul className="change-list">
              {table.declining.map((entry) => (
                <li key={String(entry.key)}>
                  <span className="name">{entry.name}</span>
                  <span className="abs down numeric">{compactUsd(entry.absolute_change)}</span>
                  <span className="rel">{signedPercent(entry.percent_change)}</span>
                </li>
              ))}
              {table.declining.length === 0 && <li style={{ color: "var(--muted)" }}>None above the baseline</li>}
            </ul>
          </div>
        </div>
      )}
    </Panel>
  );
}

function BalanceList({ rows }: { rows: BalanceView["partner_surpluses"] }) {
  if (!rows.length) return <p style={{ color: "var(--muted)", fontSize: 12 }}>No reported data</p>;
  return (
    <ul className="change-list">
      {rows.map((row) => (
        <li key={String(row.key)}>
          <span className="name">{row.name}</span>
          <span className={`abs numeric ${row.balance >= 0 ? "up" : "down"}`}>{compactUsd(row.balance)}</span>
          <span className="rel">{row.balance >= 0 ? "surplus" : "deficit"}</span>
        </li>
      ))}
    </ul>
  );
}
