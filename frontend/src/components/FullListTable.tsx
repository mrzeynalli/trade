import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { compactUsd, percent } from "../lib/format";
import type { RankItem } from "../types";

type Props = {
  items: RankItem[];
  label: string;
  codeHeader: string;
  onSelect?: (item: RankItem) => void;
};

/** Searchable "view all" table. Long lists belong here, not in a bar chart. */
export function FullListTable({ items, label, codeHeader, onSelect }: Props) {
  const [term, setTerm] = useState("");
  const filtered = useMemo(() => {
    const needle = term.trim().toLowerCase();
    if (!needle) return items;
    return items.filter(
      (item) => item.name.toLowerCase().includes(needle) || String(item.code).includes(needle),
    );
  }, [items, term]);

  return (
    <div>
      <div className="search-field" style={{ marginBottom: 10 }}>
        <Search size={15} />
        <input
          type="search"
          value={term}
          placeholder={`Search ${label.toLowerCase()}`}
          aria-label={`Search ${label}`}
          onChange={(event) => setTerm(event.target.value)}
        />
      </div>
      <div className="table-scroll">
        <table className="data-table">
          <caption className="skip-link">{label}</caption>
          <thead>
            <tr>
              <th className="num" scope="col">#</th>
              <th scope="col">{codeHeader}</th>
              <th scope="col">Name</th>
              <th className="num" scope="col">Value</th>
              <th className="num" scope="col">Share</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => (
              <tr key={String(item.key)}>
                <td className="num">{items.indexOf(item) + 1}</td>
                <td className="numeric">{item.code}</td>
                <td>
                  {onSelect ? (
                    <button type="button" className="link-button" onClick={() => onSelect(item)}>
                      {item.name}
                    </button>
                  ) : (
                    item.name
                  )}
                </td>
                <td className="num">{compactUsd(item.value)}</td>
                <td className="num">{percent(item.share)}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} style={{ color: "var(--muted)", textAlign: "center", padding: 20 }}>
                  Nothing matches “{term}”.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
