import { useMemo } from "react";
import { EChart } from "../components/EChart";
import { Panel } from "../components/Panel";
import { treemapOption } from "../components/charts";
import { EmptyBlock, ErrorBlock } from "../components/States";
import { compactUsd, exactUsd, percent } from "../lib/format";
import { query } from "../lib/api";
import { useResource } from "../lib/useResource";
import type { WorldOverview } from "../types";

type Props = { onProduct: (code: string) => void };

/** World product explorer: pick an HS chapter, see who supplies it. */
export function Products({ onProduct }: Props) {
  const world = useResource<WorldOverview>(`/world/overview${query({ top: 20 })}`);
  const data = world.data;

  const treeOption = useMemo(() => {
    if (!data?.products?.available || !data.products.items) return null;
    return treemapOption(data.products.items, data.products.other ?? null, "X");
  }, [data?.products]);

  return (
    <>
      <div className="page-head">
        <span className="eyebrow">Composition</span>
        <h1>Products</h1>
        <p>
          What the world exports, by HS chapter. Select a chapter to open it
          and how concentrated that supply is.
        </p>
      </div>

      {world.status === "error" && (
        <ErrorBlock message={world.error ?? "Could not load products"} onRetry={world.reload} />
      )}
      {world.status === "loading" && <div className="skeleton" />}

      {world.status === "ready" && !data?.products?.available && (
        <EmptyBlock title="World product data not available">
          The world HS2 matrix has not been built for a comparable year yet.
        </EmptyBlock>
      )}

      {world.status === "ready" && data?.products?.available && treeOption && (
        <>
          <Panel
            eyebrow="World"
            title={`What the world exports, ${data.year}`}
            description="Area encodes reported world export value. Select a chapter to open it."
          >
            <EChart
              option={treeOption}
              className="chart tall"
              ariaLabel={`Treemap of world exports by HS chapter in ${data.year}. Largest is ${data.products.items?.[0]?.name}.`}
              onSelect={(params) => {
                const entry = params.data as { code?: string } | undefined;
                if (entry?.code && entry.code !== "__other__") onProduct(String(entry.code));
              }}
            />
          </Panel>

          <div style={{ marginTop: 16 }}>
            <Panel
              eyebrow="Chapters"
              title="Every chapter, ranked"
              description="Reported world exports by HS chapter."
              bodyClassName="flush"
            >
              <ul className="bar-list">
                {data.products.items?.map((item) => {
                  const max = data.products.items?.[0]?.value ?? 1;
                  return (
                    <li key={item.code}>
                      <button
                        type="button"
                        className="bar-row"
                        onClick={() => onProduct(item.code)}
                        aria-label={`${item.name}, HS ${item.code}, ${exactUsd(item.value)}`}
                        style={{
                          ["--bar-width" as string]: `${Math.max(2, (item.value / max) * 100)}%`,
                          ["--bar-color" as string]: "var(--export-wash)",
                        }}
                      >
                        <span className="label">
                          {item.name}
                          <small>HS {item.code}</small>
                        </span>
                        <span className="amount numeric">{compactUsd(item.value)}</span>
                        <span className="pct numeric">{percent(item.share)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Panel>
          </div>
        </>
      )}

    </>
  );
}
