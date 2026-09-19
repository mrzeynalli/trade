import { ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { BarList } from "../../components/BarList";
import { Drawer } from "../../components/Drawer";
import { EChart } from "../../components/EChart";
import { InfoTip } from "../../components/InfoTip";
import { Panel } from "../../components/Panel";
import { Segment } from "../../components/Segment";
import { dualSeriesOption, totalSeriesOption } from "../../components/charts";
import { EmptyBlock, ErrorBlock, LoadingBlock, PreparingBlock } from "../../components/States";
import { compactUsd, exactUsd, percent, periodLabel, signedPercent, unitValue } from "../../lib/format";
import { query } from "../../lib/api";
import { useResource } from "../../lib/useResource";
import type { ProductDetail } from "../../types";

type Props = {
  token: string;
  hsCode: string;
  freq: "A" | "M";
  countryName: string;
  onClose: () => void;
  onPartner: (code: number) => void;
  onProduct: (code: string) => void;
};

export function ProductDrawer({ token, hsCode, freq, countryName, onClose, onPartner, onProduct }: Props) {
  const [flow, setFlow] = useState<"X" | "M">("X");
  const [hs4Requested, setHs4Requested] = useState(false);
  const state = useResource<ProductDetail>(
    `/country/${token}/product/${hsCode}${query({ freq, flow })}`,
  );
  // Requesting HS4 enqueues the ingestion job; the product detail then picks
  // the data up on its next poll.
  const hs4 = useResource<unknown>(
    hs4Requested ? `/country/${token}/products${query({ freq, flow, level: 4 })}` : null,
  );
  const detail = state.data;

  useEffect(() => {
    if (hs4.status === "ready" && !detail?.children.available) state.reload();
  }, [hs4.status]);

  const seriesOption = useMemo(() => {
    if (!detail) return null;
    return dualSeriesOption(
      detail.series.map((point) => ({
        period: point.period,
        exports: point.exports,
        imports: point.imports,
      })),
      freq,
    );
  }, [detail, freq]);

  const unitOption = useMemo(() => {
    if (!detail?.unit_values.length) return null;
    return totalSeriesOption(
      detail.unit_values.map((point) => ({ period: point.period, value: point.unit_value })),
      flow,
      freq,
      new Set(),
    );
  }, [detail, flow, freq]);

  return (
    <Drawer
      title={detail ? detail.name : `HS ${hsCode}`}
      subtitle={detail ? `HS ${detail.code} · ${countryName}` : undefined}
      breadcrumb={
        <>
          <span>Products</span>
          <ChevronRight size={11} />
          <span>{hsCode}</span>
        </>
      }
      onClose={onClose}
    >
      {state.status === "preparing" && (
        <PreparingBlock
          message={state.job?.message ?? "Preparing detailed product data"}
          progress={state.job?.job.progress}
          steps={["Fetching HS4 detail", "Normalising records", "Building the local table"]}
        />
      )}
      {state.status === "error" && <ErrorBlock message={state.error ?? "Failed"} onRetry={state.reload} />}
      {state.status === "loading" && <LoadingBlock />}

      {state.status === "ready" && detail && (
        <>
          <div className="stat-row">
            <div className="stat">
              <span>{flow === "X" ? "Exports" : "Imports"}</span>
              <strong className="numeric" title={exactUsd(detail.value)}>
                {compactUsd(detail.value)}
              </strong>
              <small>{detail.composition_period}</small>
            </div>
            <div className="stat">
              <span>Share of {flow === "X" ? "exports" : "imports"}</span>
              <strong className="numeric">{percent(detail.share_of_flow)}</strong>
              <small>of {countryName}'s total</small>
            </div>
            <div className="stat">
              <span>Change</span>
              <strong className="numeric">{signedPercent(detail.change)}</strong>
              <small>year on year</small>
            </div>
          </div>

          <Segment
            label="Trade flow"
            value={flow}
            onChange={setFlow}
            options={[
              { value: "X", label: "Exports" },
              { value: "M", label: "Imports" },
            ]}
          />

          <Panel eyebrow="Trend" title={`HS ${detail.code} over time`}>
            {seriesOption && detail.series.length ? (
              <EChart
                className="chart short"
                option={seriesOption}
                ariaLabel={`Exports and imports of ${detail.name} for ${countryName} over ${detail.series.length} periods.`}
              />
            ) : (
              <EmptyBlock title="No reported series" />
            )}
          </Panel>

          {detail.level === 2 && (
            <Panel
              eyebrow="Breakdown"
              title="HS4 subcategories"
              description={`Detail inside chapter ${detail.code}, ${detail.composition_period}.`}
              bodyClassName="flush"
            >
              {detail.children.available ? (
                <BarList
                  ranking={detail.children}
                  flow={flow}
                  mode="value"
                  codePrefix="HS"
                  onSelect={(item) => onProduct(String(item.code))}
                />
              ) : hs4Requested ? (
                <PreparingBlock
                  message="Preparing HS4 detail"
                  progress={hs4.job?.job.progress}
                  steps={["Fetching HS4 detail", "Normalising records", "Building the local table"]}
                />
              ) : (
                <EmptyBlock title="Detailed breakdown not available yet">
                  <button
                    type="button"
                    className="link-button"
                    style={{ marginTop: 10 }}
                    onClick={() => setHs4Requested(true)}
                  >
                    Load HS4 detail
                  </button>
                </EmptyBlock>
              )}
            </Panel>
          )}

          <Panel
            eyebrow={flow === "X" ? "Destinations" : "Origins"}
            title={
              flow === "X"
                ? `Where does ${countryName} export this?`
                : `Where does ${countryName} import this from?`
            }
            description={`Partners for HS ${detail.code}, ${detail.composition_period}.`}
            bodyClassName="flush"
          >
            {detail.partners_status === "preparing" ? (
              <PreparingBlock
                message="Preparing partner detail for this category"
                steps={["Fetching partner detail", "Normalising records", "Building the local table"]}
              />
            ) : detail.partners.available ? (
              <BarList
                ranking={detail.partners}
                flow={flow}
                mode="value"
                onSelect={(item) => onPartner(Number(item.code))}
              />
            ) : (
              <EmptyBlock title="No reported partner detail" />
            )}
          </Panel>

          {unitOption && (
            <Panel
              eyebrow="Unit value"
              title="Unit value proxy"
              description="Reported trade value divided by reported net weight."
              action={
                <InfoTip title="Unit value proxy">
                  <p style={{ margin: 0 }}>
                    This is an average across whatever mix of goods sits inside the category and
                    across all partners. It is not a market price, and it moves with composition as
                    well as with prices.
                  </p>
                </InfoTip>
              }
              footnote={`Latest: ${unitValue(detail.unit_values[detail.unit_values.length - 1]?.unit_value)}`}
            >
              <EChart
                className="chart short"
                option={unitOption}
                ariaLabel={`Unit value proxy in dollars per kilogram for ${detail.name}.`}
              />
            </Panel>
          )}

          <p className="panel-footnote" style={{ padding: 0 }}>
            {detail.classification_note} Latest period shown: {periodLabel(detail.composition_period)}.
          </p>
        </>
      )}
    </Drawer>
  );
}
