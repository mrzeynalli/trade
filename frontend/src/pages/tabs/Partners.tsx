import { useState } from "react";
import { BarList } from "../../components/BarList";
import { EChart } from "../../components/EChart";
import { FullListTable } from "../../components/FullListTable";
import { Panel } from "../../components/Panel";
import { sankeyOption } from "../../components/charts";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../../components/States";
import { query } from "../../lib/api";
import { useResource } from "../../lib/useResource";
import type { NetworkView, Ranking } from "../../types";

type Props = {
  token: string;
  freq: "A" | "M";
  window: string;
  countryName: string;
  onPartner: (code: number) => void;
};

export function Partners({ token, freq, window: monthWindow, countryName, onPartner }: Props) {
  const [showAll, setShowAll] = useState<"X" | "M" | null>(null);

  const exports = useResource<Ranking>(
    `/country/${token}/partners${query({ freq, flow: "X", window: monthWindow, top: 12 })}`,
  );
  const imports = useResource<Ranking>(
    `/country/${token}/partners${query({ freq, flow: "M", window: monthWindow, top: 12 })}`,
  );
  const network = useResource<NetworkView>(`/country/${token}/network${query({ freq, flow: "X" })}`);
  const full = useResource<Ranking>(
    showAll
      ? `/country/${token}/partners${query({ freq, flow: showAll, window: monthWindow, full: true })}`
      : null,
  );

  return (
    <>
      <div className="grid grid-2">
        <Panel
          eyebrow="Destinations"
          title={`Where does ${countryName} export to?`}
          description="Partner markets by reported export value. Select a partner for the bilateral view."
          bodyClassName="flush"
          footnote={
            exports.data?.available ? (
              <button type="button" className="link-button" onClick={() => setShowAll(showAll === "X" ? null : "X")}>
                {showAll === "X" ? "Hide full list" : `View all ${exports.data.count} partners`}
              </button>
            ) : undefined
          }
        >
          <RankBody state={exports} flow="X" onPartner={onPartner} />
        </Panel>

        <Panel
          eyebrow="Origins"
          title={`Where does ${countryName} import from?`}
          description="Source markets by reported import value."
          bodyClassName="flush"
          footnote={
            imports.data?.available ? (
              <button type="button" className="link-button" onClick={() => setShowAll(showAll === "M" ? null : "M")}>
                {showAll === "M" ? "Hide full list" : `View all ${imports.data.count} partners`}
              </button>
            ) : undefined
          }
        >
          <RankBody state={imports} flow="M" onPartner={onPartner} />
        </Panel>
      </div>

      {showAll && (
        <div style={{ marginTop: 11 }}>
          <Panel
            eyebrow="Full list"
            title={showAll === "X" ? "All export destinations" : "All import origins"}
          >
            {full.status === "ready" && full.data ? (
              <FullListTable
                items={full.data.items}
                label="partners"
                codeHeader="Code"
                onSelect={(item) => onPartner(Number(item.code))}
              />
            ) : (
              <LoadingBlock />
            )}
          </Panel>
        </div>
      )}

      <div style={{ marginTop: 11 }}>
        <Panel
          eyebrow="Network"
          title="Export flow structure"
          description={`Top product categories into ${countryName}'s export basket, and out to its largest destination markets. Everything outside the top ranks is aggregated as "Other".`}
        >
          {network.status === "error" && <ErrorBlock message={network.error ?? "Failed"} onRetry={network.reload} />}
          {network.status === "loading" && <div className="skeleton" />}
          {network.status === "ready" && network.data?.available ? (
            <EChart
              className="chart tall"
              option={sankeyOption(network.data.nodes, network.data.links, "X")}
              ariaLabel={`Sankey diagram of ${countryName} export flows from top product categories through to top destination markets, ${network.data.composition_period}.`}
            />
          ) : network.status === "ready" ? (
            <EmptyBlock title="Not enough data for a network view" />
          ) : null}
        </Panel>
      </div>
    </>
  );
}

function RankBody({
  state,
  flow,
  onPartner,
}: {
  state: ReturnType<typeof useResource<Ranking>>;
  flow: "X" | "M";
  onPartner: (code: number) => void;
}) {
  if (state.status === "error") return <ErrorBlock message={state.error ?? "Failed"} onRetry={state.reload} />;
  if (state.status !== "ready" || !state.data) return <LoadingBlock />;
  return (
    <BarList
      ranking={state.data}
      flow={flow}
      mode="value"
      onSelect={(item) => onPartner(Number(item.code))}
      emptyTitle="No reported partner data"
    />
  );
}
