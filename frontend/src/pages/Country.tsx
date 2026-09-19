import { Clock, Database } from "lucide-react";
import { useEffect, useMemo } from "react";
import { CountrySearch } from "../components/CountrySearch";
import { Flag } from "../components/Flag";
import { Segment } from "../components/Segment";
import { ErrorBlock, PreparingBlock } from "../components/States";
import { formatDate, periodLabel } from "../lib/format";
import { query } from "../lib/api";
import { useResource } from "../lib/useResource";
import type { Country as CountryRow, MacroView, Meta, Summary } from "../types";
import { ProductDrawer } from "./drill/ProductDrawer";
import { PartnerDrawer } from "./drill/PartnerDrawer";
import { InsightsTab } from "./tabs/InsightsTab";
import { Overview } from "./tabs/Overview";
import { Partners } from "./tabs/Partners";
import { Products } from "./tabs/Products";

const TAB_IDS = ["overview", "products", "partners", "insights"] as const;
type TabId = (typeof TAB_IDS)[number];

type Props = {
  token: string;
  params: URLSearchParams;
  setParams: (params: Record<string, string | null>) => void;
  navigate: (path: string) => void;
  onMeta: (meta: Meta | null) => void;
};

export function Country({ token, params, setParams, navigate, onMeta }: Props) {
  const freq = (params.get("freq") === "M" ? "M" : "A") as "A" | "M";
  const range = params.get("range") ?? (freq === "A" ? "15" : "36");
  const monthWindow = params.get("window") ?? "r12";
  const tab = (TAB_IDS.find((t) => t === params.get("tab")) ?? "overview") as TabId;
  const product = params.get("product");
  const partner = params.get("partner");

  const countries = useResource<CountryRow[]>("/meta/countries");
  const summary = useResource<Summary>(
    `/country/${token}/summary${query({ freq, range, window: freq === "M" ? monthWindow : null })}`,
  );
  // Loaded independently: if the World Bank series is missing for a country the
  // trade dashboard is unaffected.
  const macro = useResource<MacroView>(`/country/${token}/macro`);
  const meta = summary.meta;

  useEffect(() => {
    onMeta(meta);
  }, [meta, onMeta]);

  useEffect(() => {
    const name = meta?.reporter.name;
    document.title = name ? `${name} trade — Global Trade Intelligence` : "Global Trade Intelligence";
  }, [meta?.reporter.name]);

  // When the summary request fails there is no meta, but the reporter list is
  // a separate request and usually still has the name — better than showing a
  // bare ISO code above an error message.
  const fallbackName = (countries.data ?? []).find(
    (entry) => entry.iso3 === token || String(entry.code) === token,
  )?.name;
  const countryName = meta?.reporter.name ?? fallbackName ?? token;
  const partialPeriods = useMemo(() => {
    const set = new Set<string>();
    if (freq === "A" && meta?.partial && meta.latest_annual) set.add(String(meta.latest_annual));
    return set;
  }, [freq, meta?.partial, meta?.latest_annual]);

  const monthlyAvailable = Boolean(meta?.monthly_available);

  return (
    <>
        <div className="country-header">
          <div className="country-title">
            <div className="country-flag" aria-hidden="true">
              {meta?.reporter.iso2 ? (
                <Flag iso2={meta.reporter.iso2} size={30} />
              ) : (
                meta?.reporter.iso3 ?? "··"
              )}
            </div>
            <div>
              <span className="eyebrow">Trade overview</span>
              <h1>{countryName}</h1>
              <p>UN Comtrade merchandise trade · values in current US dollars</p>
            </div>
          </div>
          <div className="provenance">
            <span>
              <Clock size={11} style={{ verticalAlign: -1, marginRight: 5 }} />
              Latest complete year: <b>{meta?.latest_complete_annual ?? "—"}</b>
            </span>
            <span>
              Latest monthly data: <b>{periodLabel(meta?.latest_monthly)}</b>
            </span>
            <span>
              <Database size={11} style={{ verticalAlign: -1, marginRight: 5 }} />
              Retrieved: <b>{formatDate(meta?.local_cache_updated_at)}</b>
            </span>
          </div>
        </div>

        <div className="control-rail">
          <div className="control-group">
            <span id="country-switch-label">Country</span>
            <div style={{ minWidth: 250 }}>
              <CountrySearch
                countries={countries.data ?? []}
                placeholder={countryName}
                onSelect={(country) => navigate(`/country/${country.iso3 ?? country.code}`)}
              />
            </div>
          </div>
          <div className="rail-divider" aria-hidden="true" />
          <div className="control-group">
            <span>Frequency</span>
            <Segment
              label="Data frequency"
              value={freq}
              onChange={(value) => setParams({ freq: value, range: null, window: null })}
              options={[
                { value: "A", label: "Annual" },
                {
                  value: "M",
                  label: "Monthly",
                  title: monthlyAvailable ? undefined : "Monthly data will be prepared on first use",
                },
              ]}
            />
          </div>
          {freq === "A" && (
            <div className="control-group">
              <span>Period</span>
              <Segment
                label="Annual range"
                value={range}
                onChange={(value) => setParams({ range: value })}
                options={[
                  { value: "5", label: "5Y" },
                  { value: "10", label: "10Y" },
                  { value: "15", label: "15Y" },
                  { value: "all", label: "All" },
                ]}
              />
            </div>
          )}
          {freq === "M" && (
            <div className="control-group">
              <span>Rankings</span>
              <Segment
                label="Ranking window"
                value={monthWindow}
                onChange={(value) => setParams({ window: value })}
                options={[
                  { value: "r12", label: "Last 12M" },
                  { value: "latest", label: "Latest month" },
                ]}
              />
            </div>
          )}
          <div className="rail-spacer" />
          {meta?.partial && <span className="badge partial">Latest period partial</span>}
        </div>

        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
          {summary.status === "error" && (
            <ErrorBlock message={summary.error ?? "Could not load this country"} onRetry={summary.reload} />
          )}

          {summary.status === "preparing" && (
            <PreparingBlock
              message={summary.job?.message ?? `Preparing trade data for ${countryName}`}
              progress={summary.job?.job.progress}
            />
          )}

          {(summary.status === "loading" || summary.status === "idle") && (
            <div className="grid grid-2">
              <div className="skeleton" />
              <div className="skeleton" />
            </div>
          )}

          {summary.status === "ready" && summary.data && (
            <>
              {tab === "overview" && (
                <Overview
                  macro={macro.status === "ready" ? macro.data : null}
                  summary={summary.data}
                  freq={freq}
                  countryName={countryName}
                  partial={Boolean(meta?.partial)}
                  partialPeriods={partialPeriods}
                  onProduct={(code) => setParams({ product: code, partner: null })}
                  onPartner={(code) => setParams({ partner: String(code), product: null })}
                />
              )}
              {tab === "products" && (
                <Products
                  token={token}
                  freq={freq}
                  window={monthWindow}
                  countryName={countryName}
                  onProduct={(code) => setParams({ product: code, partner: null })}
                />
              )}
              {tab === "partners" && (
                <Partners
                  token={token}
                  freq={freq}
                  window={monthWindow}
                  countryName={countryName}
                  onPartner={(code) => setParams({ partner: String(code), product: null })}
                />
              )}
              {tab === "insights" && (
                <InsightsTab
                  token={token}
                  freq={freq}
                  countryName={countryName}
                  monthlyAvailable={monthlyAvailable}
                />
              )}
            </>
          )}
        </div>

      {product && (
        <ProductDrawer
          token={token}
          hsCode={product}
          freq={freq}
          countryName={countryName}
          onClose={() => setParams({ product: null })}
          onProduct={(code) => setParams({ product: code })}
          onPartner={(code) => setParams({ partner: String(code), product: null })}
        />
      )}
      {partner && (
        <PartnerDrawer
          token={token}
          partnerCode={Number(partner)}
          freq={freq}
          countryName={countryName}
          onClose={() => setParams({ partner: null })}
          onProduct={(code) => setParams({ product: code, partner: null })}
        />
      )}
    </>
  );
}
