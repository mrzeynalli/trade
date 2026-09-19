import { useState } from "react";
import { BarList } from "../../components/BarList";
import { FullListTable } from "../../components/FullListTable";
import { Panel } from "../../components/Panel";
import { Segment } from "../../components/Segment";
import { ErrorBlock, LoadingBlock, PreparingBlock } from "../../components/States";
import { query } from "../../lib/api";
import { useResource } from "../../lib/useResource";
import type { Ranking } from "../../types";

type Props = {
  token: string;
  freq: "A" | "M";
  window: string;
  countryName: string;
  onProduct: (code: string) => void;
};

export function Products({ token, freq, window: monthWindow, countryName, onProduct }: Props) {
  const [level, setLevel] = useState<"2" | "4">("2");
  const [showAll, setShowAll] = useState<"X" | "M" | null>(null);

  const exports = useResource<Ranking>(
    `/country/${token}/products${query({ freq, flow: "X", level, window: monthWindow, top: 12 })}`,
  );
  const imports = useResource<Ranking>(
    `/country/${token}/products${query({ freq, flow: "M", level, window: monthWindow, top: 12 })}`,
  );
  const allExports = useResource<Ranking>(
    showAll === "X"
      ? `/country/${token}/products${query({ freq, flow: "X", level, window: monthWindow, full: true })}`
      : null,
  );
  const allImports = useResource<Ranking>(
    showAll === "M"
      ? `/country/${token}/products${query({ freq, flow: "M", level, window: monthWindow, full: true })}`
      : null,
  );

  const levelControl = (
    <Segment
      label="HS detail level"
      value={level}
      onChange={setLevel}
      options={[
        { value: "2", label: "HS2" },
        { value: "4", label: "HS4" },
      ]}
    />
  );

  return (
    <>
      <div className="grid grid-2">
        <Panel
          eyebrow="Exports"
          title={`${countryName} export composition`}
          description={
            level === "2"
              ? "HS chapters. Select a row to open the category detail."
              : "HS4 headings. More granular, and less comparable across HS revisions."
          }
          action={levelControl}
          bodyClassName="flush"
          footnote={
            exports.data?.available ? (
              <button type="button" className="link-button" onClick={() => setShowAll(showAll === "X" ? null : "X")}>
                {showAll === "X" ? "Hide full list" : `View all ${exports.data.count} categories`}
              </button>
            ) : undefined
          }
        >
          <SectionBody state={exports} onProduct={onProduct} flow="X" />
        </Panel>

        <Panel
          eyebrow="Imports"
          title={`${countryName} import composition`}
          description={level === "2" ? "HS chapters." : "HS4 headings."}
          bodyClassName="flush"
          footnote={
            imports.data?.available ? (
              <button type="button" className="link-button" onClick={() => setShowAll(showAll === "M" ? null : "M")}>
                {showAll === "M" ? "Hide full list" : `View all ${imports.data.count} categories`}
              </button>
            ) : undefined
          }
        >
          <SectionBody state={imports} onProduct={onProduct} flow="M" />
        </Panel>
      </div>

      {showAll === "X" && (
        <div style={{ marginTop: 11 }}>
          <Panel eyebrow="Full list" title="All exported categories">
            {allExports.status === "ready" && allExports.data ? (
              <FullListTable
                items={allExports.data.items}
                label="exported categories"
                codeHeader="HS"
                onSelect={(item) => onProduct(String(item.code))}
              />
            ) : (
              <LoadingBlock />
            )}
          </Panel>
        </div>
      )}
      {showAll === "M" && (
        <div style={{ marginTop: 11 }}>
          <Panel eyebrow="Full list" title="All imported categories">
            {allImports.status === "ready" && allImports.data ? (
              <FullListTable
                items={allImports.data.items}
                label="imported categories"
                codeHeader="HS"
                onSelect={(item) => onProduct(String(item.code))}
              />
            ) : (
              <LoadingBlock />
            )}
          </Panel>
        </div>
      )}
    </>
  );
}

function SectionBody({
  state,
  onProduct,
  flow,
}: {
  state: ReturnType<typeof useResource<Ranking>>;
  onProduct: (code: string) => void;
  flow: "X" | "M";
}) {
  if (state.status === "preparing") {
    return (
      <PreparingBlock
        message={state.job?.message ?? "Preparing detailed product data"}
        progress={state.job?.job.progress}
        steps={["Fetching HS4 detail", "Normalising records", "Building the local table"]}
      />
    );
  }
  if (state.status === "error") return <ErrorBlock message={state.error ?? "Failed"} onRetry={state.reload} />;
  if (state.status !== "ready" || !state.data) return <LoadingBlock />;
  return (
    <BarList
      ranking={state.data}
      flow={flow}
      mode="value"
      codePrefix="HS"
      onSelect={(item) => onProduct(String(item.code))}
    />
  );
}
