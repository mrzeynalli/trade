import { ArrowDownRight, ArrowUpRight, Minus, Scale, Ship, TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { BarList } from "../../components/BarList";
import { C, EChart } from "../../components/EChart";
import { InfoTip } from "../../components/InfoTip";
import { Panel } from "../../components/Panel";
import { Segment } from "../../components/Segment";
import {
  balanceOption, sparklineOption, totalSeriesOption, treemapOption,
} from "../../components/charts";
import { EmptyBlock } from "../../components/States";
import { MacroStrip } from "../../components/MacroStrip";
import { compactUsd, exactUsd, percent, periodLabel, signedPercent } from "../../lib/format";
import type { MacroView, RankItem, Ranking, Summary } from "../../types";

type Props = {
  summary: Summary;
  macro: MacroView | null;
  freq: "A" | "M";
  countryName: string;
  partial: boolean;
  partialPeriods: Set<string>;
  onProduct: (code: string) => void;
  onPartner: (code: number) => void;
};

export function Overview({
  summary,
  macro,
  freq,
  countryName,
  partial,
  partialPeriods,
  onProduct,
  onPartner,
}: Props) {
  const [view, setView] = useState<"treemap" | "bars">("treemap");
  const { kpis, series } = summary;

  const exportPoints = useMemo(
    () => series.map((point) => ({ period: point.period, value: point.exports })),
    [series],
  );
  const importPoints = useMemo(
    () => series.map((point) => ({ period: point.period, value: point.imports })),
    [series],
  );
  const balancePoints = useMemo(
    () => series.map((point) => ({ period: point.period, balance: point.balance })),
    [series],
  );

  const exportOption = useMemo(
    () => totalSeriesOption(exportPoints, "X", freq, partialPeriods),
    [exportPoints, freq, partialPeriods],
  );
  const importOption = useMemo(
    () => totalSeriesOption(importPoints, "M", freq, partialPeriods),
    [importPoints, freq, partialPeriods],
  );
  const balanceOpt = useMemo(() => balanceOption(balancePoints, freq), [balancePoints, freq]);

  const compositionPeriod = kpis.composition_period ?? "";
  const balanceLabel = kpis.balance === null ? "—" : kpis.balance >= 0 ? "Surplus" : "Deficit";

  return (
    <>
      <div className="kpi-grid">
        <Kpi
          label="Exports"
          value={compactUsd(kpis.exports)}
          exact={exactUsd(kpis.exports)}
          tone="export"
          change={kpis.export_change}
          period={kpis.period}
          partial={partial}
          spark={series.map((p) => p.exports)}
        />
        <Kpi
          label="Imports"
          value={compactUsd(kpis.imports)}
          exact={exactUsd(kpis.imports)}
          tone="import"
          change={kpis.import_change}
          period={kpis.period}
          partial={partial}
          spark={series.map((p) => p.imports)}
        />
        <div className="kpi-card">
          <header>
            <span>Trade balance</span>
            <Scale size={15} aria-hidden="true" />
          </header>
          <div className="value numeric" title={exactUsd(kpis.balance)}>
            {compactUsd(kpis.balance)}
          </div>
          <footer>
            <span className={`badge ${kpis.balance === null ? "neutral" : kpis.balance >= 0 ? "surplus" : "deficit"}`}>
              {kpis.balance !== null &&
                (kpis.balance >= 0 ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />)}
              {balanceLabel}
            </span>
            <span>{periodLabel(kpis.period)}</span>
          </footer>
        </div>
        <div className="kpi-card">
          <header>
            <span>Top export destination</span>
            <Ship size={15} aria-hidden="true" />
          </header>
          <div className="value" style={{ fontSize: 22 }}>
            {kpis.top_export_destination?.name ?? "—"}
          </div>
          <footer>
            <span className="sub numeric">
              {kpis.top_export_destination
                ? `${compactUsd(kpis.top_export_destination.value)} · ${percent(kpis.top_export_destination.share)}`
                : "No reported data"}
            </span>
          </footer>
        </div>
      </div>

      {macro?.available && <MacroStrip macro={macro} countryName={countryName} />}

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Panel
          eyebrow={freq === "A" ? "Annual" : "Monthly"}
          title="Total exports"
          description={`Reported merchandise exports, ${freq === "A" ? "one point per year" : "one point per month"}. Gaps mean no reported data.`}
          action={partial ? <span className="badge partial">Partial period</span> : undefined}
        >
          {exportPoints.some((p) => p.value !== null) ? (
            <EChart
              option={exportOption}
              ariaLabel={`Total exports for ${countryName}. Latest ${periodLabel(kpis.period)}: ${exactUsd(kpis.exports)}, ${signedPercent(kpis.export_change)} year on year.`}
            />
          ) : (
            <EmptyBlock title="No reported export data" />
          )}
        </Panel>

        <Panel
          eyebrow={freq === "A" ? "Annual" : "Monthly"}
          title="Total imports"
          description={`Reported merchandise imports, ${freq === "A" ? "one point per year" : "one point per month"}. Gaps mean no reported data.`}
          action={partial ? <span className="badge partial">Partial period</span> : undefined}
        >
          {importPoints.some((p) => p.value !== null) ? (
            <EChart
              option={importOption}
              ariaLabel={`Total imports for ${countryName}. Latest ${periodLabel(kpis.period)}: ${exactUsd(kpis.imports)}, ${signedPercent(kpis.import_change)} year on year.`}
            />
          ) : (
            <EmptyBlock title="No reported import data" />
          )}
        </Panel>
      </div>

      <div className="grid grid-2" style={{ marginTop: 11 }}>
        <Panel
          eyebrow="Composition"
          title={`What does ${countryName} export?`}
          description={`Top HS chapters, ${compositionPeriod}. Select a category to drill down.`}
          action={
            <Segment
              label="Composition view"
              value={view}
              onChange={setView}
              options={[
                { value: "treemap", label: "Treemap" },
                { value: "bars", label: "Bars" },
              ]}
            />
          }
          bodyClassName={view === "bars" ? "flush" : ""}
        >
          <Composition
            ranking={summary.export_products}
            flow="X"
            view={view}
            countryName={countryName}
            onProduct={onProduct}
            emptyTitle="No reported export composition"
          />
        </Panel>

        <Panel
          eyebrow="Composition"
          title={`What does ${countryName} import?`}
          description={`Top HS chapters, ${compositionPeriod}. Select a category to drill down.`}
          bodyClassName={view === "bars" ? "flush" : ""}
        >
          <Composition
            ranking={summary.import_products}
            flow="M"
            view={view}
            countryName={countryName}
            onProduct={onProduct}
            emptyTitle="No reported import composition"
          />
        </Panel>
      </div>

      <div className="grid grid-2" style={{ marginTop: 11 }}>
        <Panel
          eyebrow="Destinations"
          title={`Where does ${countryName} export to?`}
          description={`Top partner markets, ${compositionPeriod}. Select a partner for the bilateral view.`}
          bodyClassName="flush"
        >
          <BarList
            ranking={summary.export_partners}
            flow="X"
            mode="value"
            onSelect={(item: RankItem) => onPartner(Number(item.code))}
            emptyTitle="No reported partner data"
          />
        </Panel>

        <Panel
          eyebrow="Origins"
          title={`Where does ${countryName} import from?`}
          description={`Top source markets, ${compositionPeriod}. Select a partner for the bilateral view.`}
          bodyClassName="flush"
        >
          <BarList
            ranking={summary.import_partners}
            flow="M"
            mode="value"
            onSelect={(item: RankItem) => onPartner(Number(item.code))}
            emptyTitle="No reported partner data"
          />
        </Panel>
      </div>

      <div style={{ marginTop: 11 }}>
        <Panel
          eyebrow="Balance"
          title="Trade balance over time"
          description="Exports minus imports. A positive bar is a reported trade surplus, a negative bar a deficit."
          action={
            <InfoTip title="Comparing exports and imports">
              <p style={{ margin: 0 }}>
                Exports are generally reported on an FOB basis and imports on a CIF basis, so imports
                include freight and insurance that exports do not. A balance computed from these two
                measures carries that asymmetry.
              </p>
            </InfoTip>
          }
        >
          {balancePoints.some((p) => p.balance !== null) ? (
            <EChart
              option={balanceOpt}
              className="chart short"
              ariaLabel={`Trade balance for ${countryName}. Latest ${periodLabel(kpis.period)}: ${exactUsd(kpis.balance)}, a ${balanceLabel.toLowerCase()}.`}
            />
          ) : (
            <EmptyBlock title="No reported balance data" />
          )}
        </Panel>
      </div>
    </>
  );
}

/** Composition rendered either as a treemap (shape of the basket) or as bars
 *  (precise ranking). Both open the same drilldown. */
function Composition({
  ranking, flow, view, countryName, onProduct, emptyTitle,
}: {
  ranking: Ranking;
  flow: "X" | "M";
  view: "treemap" | "bars";
  countryName: string;
  onProduct: (code: string) => void;
  emptyTitle: string;
}) {
  const option = useMemo(
    () =>
      ranking.available && ranking.items.length
        ? treemapOption(
            ranking.items.map((item) => ({
              code: item.code, name: item.name, value: item.value, share: item.share,
            })),
            ranking.other ? { value: ranking.other.value, count: ranking.other.count } : null,
            flow,
          )
        : null,
    [ranking, flow],
  );

  if (!ranking.available || !ranking.items.length) return <EmptyBlock title={emptyTitle} />;

  if (view === "bars") {
    return (
      <BarList
        ranking={ranking}
        flow={flow}
        mode="value"
        codePrefix="HS"
        onSelect={(item: RankItem) => onProduct(String(item.code))}
        emptyTitle={emptyTitle}
      />
    );
  }

  return (
    <EChart
      option={option!}
      className="chart"
      ariaLabel={`Treemap of ${countryName} ${flow === "X" ? "exports" : "imports"} by HS chapter. Largest is ${ranking.items[0].name} at ${percent(ranking.items[0].share)}.`}
      onSelect={(params) => {
        const entry = params.data as { code?: string } | undefined;
        if (entry?.code && entry.code !== "__other__") onProduct(String(entry.code));
      }}
    />
  );
}

function Kpi({
  label,
  value,
  exact,
  tone,
  change,
  period,
  partial,
  spark,
}: {
  label: string;
  value: string;
  exact: string;
  tone: "export" | "import";
  change: number | null;
  period: string | null;
  partial: boolean;
  spark?: (number | null)[];
}) {
  const Icon = tone === "export" ? TrendingUp : TrendingDown;
  const direction = change === null ? "flat" : change > 0 ? "up" : change < 0 ? "down" : "flat";
  const sparkOption = useMemo(
    () => (spark && spark.filter((v) => v !== null).length > 2
      ? sparklineOption(spark, tone === "export" ? C.export : C.import)
      : null),
    [spark, tone],
  );
  return (
    <div className="kpi-card">
      <header>
        <span>{label}</span>
        <Icon size={15} aria-hidden="true" />
      </header>
      <div className={`value numeric ${tone}`} title={exact}>
        {value}
      </div>
      {sparkOption && (
        <EChart
          option={sparkOption}
          className="spark"
          ariaLabel={`${label} trend over the displayed period, ending at ${value}.`}
        />
      )}
      <footer>
        <span className={`delta ${direction}`}>
          {direction === "up" && <ArrowUpRight size={12} />}
          {direction === "down" && <ArrowDownRight size={12} />}
          {direction === "flat" && <Minus size={12} />}
          {signedPercent(change)}
        </span>
        <span>YoY · {periodLabel(period)}</span>
        {partial && <span className="badge partial">Partial</span>}
      </footer>
    </div>
  );
}
