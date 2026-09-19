import { InfoTip } from "./InfoTip";
import { compactNumber, compactUsd, percent, plainUsd } from "../lib/format";
import type { MacroView } from "../types";

/**
 * Trade set against the size of the economy behind it. Without this, a $25B
 * export figure says nothing about whether trade is central or marginal to the
 * country.
 */
export function MacroStrip({ macro, countryName }: { macro: MacroView; countryName: string }) {
  if (!macro.available) return null;

  const gdpLag =
    macro.gdp_year !== null && macro.gdp_year !== undefined &&
    macro.trade_year !== undefined && macro.gdp_year !== macro.trade_year;

  return (
    <section className="macro-strip" aria-label={`${countryName} trade relative to its economy`}>
      <header>
        <span className="eyebrow">Trade and the economy</span>
        <InfoTip title="How these ratios are built">
          <p style={{ margin: "0 0 8px" }}>
            Trade comes from UN Comtrade and GDP and population from the World Bank. The two are
            published on different schedules, so the GDP year is stated separately rather than
            assumed to match the trade year.
          </p>
          <p style={{ margin: 0 }}>
            Openness is (exports + imports) ÷ GDP. Values above 100% are normal for small and
            re-exporting economies, because trade is measured gross while GDP is value added.
          </p>
        </InfoTip>
      </header>
      <div className="macro-items">
        <Item
          label="Trade openness"
          value={percent(macro.trade_openness)}
          note={`exports + imports ÷ GDP${gdpLag ? ` (GDP ${macro.gdp_year})` : ""}`}
          accent="import"
        />
        <Item label="Exports ÷ GDP" value={percent(macro.exports_over_gdp)} note="share of output exported" accent="export" />
        <Item
          label="Balance ÷ GDP"
          value={percent(macro.balance_over_gdp)}
          note={
            macro.balance_over_gdp === null || macro.balance_over_gdp === undefined
              ? "not computable"
              : macro.balance_over_gdp >= 0
                ? "reported surplus"
                : "reported deficit"
          }
          accent={(macro.balance_over_gdp ?? 0) >= 0 ? "export" : "deficit"}
        />
        <Item label="Exports per person" value={plainUsd(macro.exports_per_capita)} note="per head of population" />
        <Item label="GDP" value={compactUsd(macro.gdp_usd)} note={`World Bank, ${macro.gdp_year ?? "—"}`} />
        <Item label="Population" value={compactNumber(macro.population)} note={`World Bank, ${macro.gdp_year ?? "—"}`} />
      </div>
    </section>
  );
}

function Item({
  label, value, note, accent,
}: {
  label: string;
  value: string;
  note: string;
  accent?: "export" | "import" | "deficit";
}) {
  return (
    <div>
      <span className="label">{label}</span>
      <span className={`value numeric ${accent ?? ""}`}>{value}</span>
      <span className="note">{note}</span>
    </div>
  );
}
