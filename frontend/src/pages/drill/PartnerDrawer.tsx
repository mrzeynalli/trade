import { ArrowLeftRight, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { BarList } from "../../components/BarList";
import { Drawer } from "../../components/Drawer";
import { EChart } from "../../components/EChart";
import { InfoTip } from "../../components/InfoTip";
import { Panel } from "../../components/Panel";
import { Segment } from "../../components/Segment";
import { dualSeriesOption, mirrorOption } from "../../components/charts";
import { EmptyBlock, ErrorBlock, LoadingBlock, PreparingBlock } from "../../components/States";
import { compactUsd, exactUsd, percent, periodLabel, signedPercent } from "../../lib/format";
import { query } from "../../lib/api";
import { useResource } from "../../lib/useResource";
import type { MirrorView, PartnerDetail } from "../../types";

type Props = {
  token: string;
  partnerCode: number;
  freq: "A" | "M";
  countryName: string;
  onClose: () => void;
  onProduct: (code: string) => void;
};

type Complementarity = {
  available: boolean;
  year?: number;
  index?: number | null;
  reporter?: string;
  partner?: string;
  note?: string;
  reason?: string;
};

export function PartnerDrawer({ token, partnerCode, freq, countryName, onClose, onProduct }: Props) {
  const [tab, setTab] = useState<"overview" | "mirror">("overview");
  const state = useResource<PartnerDetail>(`/country/${token}/partner/${partnerCode}${query({ freq })}`);
  const mirror = useResource<MirrorView>(
    tab === "mirror" ? `/pair/${token}/${partnerCode}/mirror${query({ freq })}` : null,
  );
  const tci = useResource<Complementarity>(
    tab === "mirror" ? `/pair/${token}/${partnerCode}/complementarity` : null,
  );
  const detail = state.data;

  const seriesOption = useMemo(() => {
    if (!detail?.series.length) return null;
    return dualSeriesOption(detail.series, freq);
  }, [detail, freq]);

  const partnerName = detail?.partner.name ?? `Partner ${partnerCode}`;

  return (
    <Drawer
      title={`${countryName} ↔ ${partnerName}`}
      subtitle={detail?.composition_period ? `Bilateral trade, ${detail.composition_period}` : undefined}
      breadcrumb={
        <>
          <span>Partners</span>
          <ChevronRight size={11} />
          <span>{partnerName}</span>
        </>
      }
      onClose={onClose}
    >
      <Segment
        label="Bilateral view"
        value={tab}
        onChange={setTab}
        options={[
          { value: "overview", label: "Overview" },
          { value: "mirror", label: "Mirror & fit" },
        ]}
      />

      {state.status === "preparing" && (
        <PreparingBlock message={state.job?.message ?? "Preparing bilateral data"} progress={state.job?.job.progress} />
      )}
      {state.status === "error" && <ErrorBlock message={state.error ?? "Failed"} onRetry={state.reload} />}
      {state.status === "loading" && <LoadingBlock />}

      {state.status === "ready" && detail && tab === "overview" && (
        <>
          <div className="stat-row">
            <div className="stat">
              <span>Exports to {partnerName}</span>
              <strong className="numeric" title={exactUsd(detail.exports)}>
                {compactUsd(detail.exports)}
              </strong>
              <small>
                {percent(detail.export_share_of_total)} of exports · {signedPercent(detail.export_change)} YoY
              </small>
            </div>
            <div className="stat">
              <span>Imports from {partnerName}</span>
              <strong className="numeric" title={exactUsd(detail.imports)}>
                {compactUsd(detail.imports)}
              </strong>
              <small>
                {percent(detail.import_share_of_total)} of imports · {signedPercent(detail.import_change)} YoY
              </small>
            </div>
            <div className="stat">
              <span>Bilateral balance</span>
              <strong className="numeric">{compactUsd(detail.balance)}</strong>
              <small>
                {detail.balance === null ? "—" : detail.balance >= 0 ? "Reported surplus" : "Reported deficit"} ·{" "}
                {periodLabel(detail.period)}
              </small>
            </div>
          </div>

          <Panel eyebrow="Trend" title={`${countryName} and ${partnerName} over time`}>
            {seriesOption ? (
              <EChart
                className="chart short"
                option={seriesOption}
                ariaLabel={`Exports to and imports from ${partnerName} over ${detail.series.length} periods.`}
              />
            ) : (
              <EmptyBlock title="No reported series" />
            )}
          </Panel>

          {detail.products_status === "preparing" ? (
            <Panel eyebrow="Composition" title="What is traded">
              <PreparingBlock
                message="Preparing bilateral product composition"
                steps={["Fetching bilateral detail", "Normalising records", "Building the local table"]}
              />
            </Panel>
          ) : (
            <div className="grid grid-2">
              <Panel
                eyebrow="Composition"
                title={`Exported to ${partnerName}`}
                bodyClassName="flush"
              >
                <BarList
                  ranking={detail.export_products}
                  flow="X"
                  mode="value"
                  codePrefix="HS"
                  onSelect={(item) => onProduct(String(item.code))}
                  emptyTitle="No reported composition"
                />
              </Panel>
              <Panel
                eyebrow="Composition"
                title={`Imported from ${partnerName}`}
                bodyClassName="flush"
              >
                <BarList
                  ranking={detail.import_products}
                  flow="M"
                  mode="value"
                  codePrefix="HS"
                  onSelect={(item) => onProduct(String(item.code))}
                  emptyTitle="No reported composition"
                />
              </Panel>
            </div>
          )}
        </>
      )}

      {tab === "mirror" && (
        <>
          <Panel
            eyebrow="Mirror statistics"
            title="Two reports of the same relationship"
            description={`${countryName}'s reported exports to ${partnerName}, against ${partnerName}'s own reported imports from ${countryName}.`}
            action={
              <InfoTip title="Why the two differ">
                <p style={{ margin: "0 0 8px" }}>
                  Exports are usually valued FOB and imports CIF, so the importing side includes
                  freight and insurance. Shipments can also cross a period boundary, goods may be
                  re-exported through a third country, and rules of origin and partner attribution
                  differ between customs authorities. Both sides revise their figures.
                </p>
                <p style={{ margin: 0 }}>A gap is expected. It is not evidence of misreporting.</p>
              </InfoTip>
            }
          >
            {mirror.status === "preparing" && (
              <PreparingBlock message={`Fetching ${partnerName}'s own reporting`} />
            )}
            {mirror.status === "loading" && <LoadingBlock />}
            {mirror.status === "error" && <ErrorBlock message={mirror.error ?? "Failed"} onRetry={mirror.reload} />}
            {mirror.status === "ready" && mirror.data?.available && mirror.data.series ? (
              <>
                <EChart
                  className="chart short"
                  option={mirrorOption(
                    mirror.data.series.map((row) => ({
                      period: row.period,
                      exports: row.exports,
                      imports: row.imports,
                      relative_difference: row.relative_difference,
                    })),
                    mirror.data.reporter?.name ?? countryName,
                    mirror.data.counterpart?.name ?? partnerName,
                  )}
                  ariaLabel={`Comparison of ${countryName}'s reported exports to ${partnerName} with ${partnerName}'s reported imports, across ${mirror.data.series.length} periods.`}
                />
                <p className="panel-footnote" style={{ padding: "12px 0 0" }}>
                  {mirror.data.note}
                </p>
              </>
            ) : mirror.status === "ready" ? (
              <EmptyBlock title="Mirror data not available">
                {mirror.data?.reason ?? "The counterpart does not report this relationship."}
              </EmptyBlock>
            ) : null}
          </Panel>

          <Panel
            eyebrow="Fit"
            title="Trade complementarity"
            description={`How well ${countryName}'s export mix matches ${partnerName}'s import mix.`}
          >
            {tci.status === "preparing" && <PreparingBlock message="Preparing partner product data" />}
            {tci.status === "loading" && <LoadingBlock />}
            {tci.status === "ready" && tci.data?.available && tci.data.index !== null ? (
              <>
                <div className="stat-row">
                  <div className="stat">
                    <span>
                      <ArrowLeftRight size={11} style={{ verticalAlign: -1, marginRight: 5 }} />
                      TCI {tci.data.year}
                    </span>
                    <strong className="numeric">{tci.data.index?.toFixed(1)}</strong>
                    <small>0 = no overlap · 100 = identical structure</small>
                  </div>
                </div>
                <p className="panel-footnote" style={{ padding: "12px 0 0" }}>
                  {tci.data.note}
                </p>
              </>
            ) : tci.status === "ready" ? (
              <EmptyBlock title="Not enough data">
                {tci.data?.reason ?? "The partner's own product composition is not available yet."}
              </EmptyBlock>
            ) : null}
          </Panel>
        </>
      )}
    </Drawer>
  );
}
