import { Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { Country } from "../types";

type Props = {
  countries: Country[];
  onSelect: (country: Country) => void;
  autoFocus?: boolean;
  placeholder?: string;
};

/**
 * Combobox over the reporter list. Matches on name and on ISO alpha-2/alpha-3,
 * and is fully operable from the keyboard.
 */
export function CountrySearch({ countries, onSelect, autoFocus, placeholder }: Props) {
  const [term, setTerm] = useState("");
  const [highlight, setHighlight] = useState(0);
  // The list opens on focus or on typing. Leaving it permanently open would
  // bury the controls that sit below it in the country header.
  const [open, setOpen] = useState(Boolean(autoFocus));
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoFocus) input.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  const matches = useMemo(() => {
    const needle = term.trim().toLowerCase();
    const pool = countries;
    if (!needle) return pool.filter((c) => c.cached).slice(0, 12);
    const scored = pool
      .map((country) => {
        const name = country.name.toLowerCase();
        let score = -1;
        if (country.iso3?.toLowerCase() === needle || country.iso2?.toLowerCase() === needle) score = 0;
        else if (name.startsWith(needle)) score = 1;
        else if (name.includes(needle)) score = 2;
        return { country, score };
      })
      .filter((entry) => entry.score >= 0)
      .sort((a, b) => a.score - b.score || a.country.name.localeCompare(b.country.name));
    return scored.slice(0, 40).map((entry) => entry.country);
  }, [countries, term]);

  useEffect(() => setHighlight(0), [term]);

  const choose = (country: Country) => {
    setOpen(false);
    onSelect(country);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setHighlight((current) => Math.min(current + 1, matches.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter" && open && matches[highlight]) {
      event.preventDefault();
      choose(matches[highlight]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  const expanded = open && matches.length > 0;

  return (
    <div ref={container} className="country-search">
      <div className="search-field">
        <Search size={17} aria-hidden="true" />
        <input
          ref={input}
          type="search"
          role="combobox"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label="Search for a country"
          placeholder={placeholder ?? "Search a country or ISO code — Azerbaijan, DEU, JP…"}
          value={term}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setTerm(event.target.value);
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      {expanded && (
        <ul className="suggestions" id={listId} role="listbox" aria-label="Country results">
          {matches.map((country, index) => (
            <li key={country.code} role="option" aria-selected={index === highlight}>
              <button
                type="button"
                onClick={() => choose(country)}
                onMouseEnter={() => setHighlight(index)}
                style={index === highlight ? { background: "var(--accent-wash)" } : undefined}
              >
                <span className="name">
                  {country.name} <span className="iso">{country.iso3 ?? ""}</span>
                </span>
                <span className={country.cached ? "ready" : "lazy"}>
                  {country.cached ? "Ready" : "Loads on demand"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && term.trim() && matches.length === 0 && (
        <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 12 }}>
          No reporter matches “{term}”.
        </p>
      )}
    </div>
  );
}
