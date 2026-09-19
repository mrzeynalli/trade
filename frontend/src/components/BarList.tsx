import { ChevronRight } from "lucide-react";
import { compactUsd, exactUsd, percent, signedPercent } from "../lib/format";
import type { Ranking, RankItem } from "../types";
import { EmptyBlock } from "./States";

type Mode = "value" | "share";

type Props = {
  ranking: Ranking;
  flow: "X" | "M";
  mode: Mode;
  onSelect?: (item: RankItem) => void;
  /** Renders the code line under the name, e.g. "HS 27". */
  codePrefix?: string;
  emptyTitle?: string;
  changeLookup?: Map<string | number, number | null>;
};

/**
 * Horizontal bars with the value and share on every row. The bar itself is a
 * background fill so the label stays readable at any width.
 */
export function BarList({ ranking, flow, mode, onSelect, codePrefix, emptyTitle, changeLookup }: Props) {
  if (!ranking.available || ranking.items.length === 0) {
    return <EmptyBlock title={emptyTitle ?? "No reported data"} />;
  }

  const color = flow === "X" ? "var(--export-wash)" : "var(--import-wash)";
  const max = Math.max(...ranking.items.map((item) => item.value), 0) || 1;

  return (
    <>
      <ul className="bar-list">
        {ranking.items.map((item) => {
          const width = `${Math.max(1.5, (item.value / max) * 100)}%`;
          const change = changeLookup?.get(item.key);
          const title = [
            item.name,
            codePrefix ? `${codePrefix} ${item.code}` : null,
            exactUsd(item.value),
            item.share !== null ? `${percent(item.share)} of ${flow === "X" ? "exports" : "imports"}` : null,
            change !== null && change !== undefined ? `${signedPercent(change)} YoY` : null,
          ]
            .filter(Boolean)
            .join(" · ");

          const content = (
            <>
              <span className="label">
                {item.name}
                {codePrefix && <small>{`${codePrefix} ${item.code}`}</small>}
              </span>
              <span className="amount numeric">{compactUsd(item.value)}</span>
              <span className="pct numeric">{percent(item.share)}</span>
            </>
          );

          if (!onSelect) {
            return (
              <li key={String(item.key)}>
                <div
                  className="bar-row"
                  title={title}
                  style={{ ["--bar-width" as string]: mode === "share" ? percent(item.share, 0) : width, ["--bar-color" as string]: color }}
                >
                  {content}
                </div>
              </li>
            );
          }
          return (
            <li key={String(item.key)}>
              <button
                type="button"
                className="bar-row"
                title={title}
                aria-label={title}
                onClick={() => onSelect(item)}
                style={{ ["--bar-width" as string]: mode === "share" ? percent(item.share, 0) : width, ["--bar-color" as string]: color }}
              >
                {content}
              </button>
            </li>
          );
        })}

        {ranking.other && ranking.other.value > 0 && (
          <li>
            <div
              className="bar-row other"
              title={`${ranking.other.count} further categories · ${exactUsd(ranking.other.value)}`}
              style={{
                ["--bar-width" as string]: `${Math.max(1.5, (ranking.other.value / max) * 100)}%`,
                ["--bar-color" as string]: "var(--chart-no-data)",
              }}
            >
              <span className="label">
                Other
                <small>{ranking.other.count} further categories</small>
              </span>
              <span className="amount numeric">{compactUsd(ranking.other.value)}</span>
              <span className="pct numeric">{percent(ranking.other.share)}</span>
            </div>
          </li>
        )}
      </ul>
      {onSelect && (
        <p className="list-footer">
          <span>Total {compactUsd(ranking.total)} across {ranking.count} categories</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            Select a row to drill down <ChevronRight size={13} />
          </span>
        </p>
      )}
    </>
  );
}
