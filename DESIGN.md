# Design system

Both frontends — Global Trade Intelligence (`trade/frontend`) and the GDELT
Geopolitical Risk Observatory (`gdelt`) — are drawn from one design system,
**Analytics Observatory**.

The system was itself read out of this repository, so nothing in it is foreign
to the product: the warm-paper ground, the Source Serif 4 / Inter pairing, the
hairline-and-shadow card, the export-green and import-indigo semantics and the
five-band risk ramp are all the originals, preserved at their exact values.

## What lives where

Each app carries an identical copy of the system's token layer at
`src/tokens/`. Change both copies together and keep them in step with each
other.

| File | Holds |
| --- | --- |
| `tokens/index.css` | The import order. This is what `styles.css` pulls in. |
| `tokens/fonts.css` | Self-hosted faces via `@fontsource`, rather than loading them from Google Fonts. |
| `tokens/palette.css` | Raw scales — neutral, teal, indigo, coral, amber, cyan, violet, magenta, moss. |
| `tokens/typography.css` | Faces, the type ramp, tracking, optical sizes. |
| `tokens/spacing.css` | The 4px scale plus the composition rhythm — grid gutters, panel padding, `--rail-width`, `--bar-height`, shell measures. |
| `tokens/radius.css`, `elevation.css`, `motion.css` | Radii, the two shadows, durations and easings. |
| `tokens/charts.css` | The four chart families — see below. |
| `tokens/semantic.css` | The names components actually use: surfaces, ink, borders, flows, status, confidence. |

`src/styles.css` composes those and holds no raw values. Its `:root` block is an
alias layer mapping this app's older local names (`--ink`, `--muted`, `--rule`)
onto the tokens; it exists so existing rules keep working and is meant to
shrink. **New rules should name the token directly** — `--text-muted`, not
`--muted`.

## The four chart families

Never mix them in one chart. A categorical hue inside a sequential ramp reads as
a category; a sequential step in a categorical chart reads as an ordering.

| Family | Job |
| --- | --- |
| `--series-1..10` | Categorical, unordered — products, partners, drivers. Consecutive tokens are the pair furthest apart in hue and lightness. |
| `--seq-1..6` | Sequential magnitude, one hue, light to dark — choropleths, volume heatmaps. On a square-root scale, because trade and events are heavily skewed. |
| `--div-neg-2..--div-pos-2` | Diverging around zero — balances, net direction, z-scores. Always with the zero rule drawn. |
| `--risk-stable..--risk-critical` | The observatory's own five risk bands. Never re-derived. |

ECharts paints to a canvas and cannot read a CSS custom property, so both apps
mirror the values it needs in TypeScript — `C`, `SERIES_COLORS`,
`SEQUENTIAL_COLORS` and `SEQUENTIAL_IMPORT_COLORS` in
`trade/frontend/src/components/EChart.tsx`, and `colors` / `RISK_RAMP` in
`gdelt/src/components/Charts.tsx`. Each entry names the token it mirrors.
**Change the token first**, then the mirror.

### One local extension

The system ships a single sequential ramp, built on the brand teal. Exports are
green and imports are indigo everywhere else in the product, and the world map
is not the place to break that, so the import choropleth uses
`SEQUENTIAL_IMPORT_COLORS` — a ramp of the same shape cut from the existing
indigo scale (`--indigo-50` through `--indigo-900`). No new colour, only a new
ordering of existing ones. It is worth promoting into the token layer as `--seq-alt-*`.

## Rules the system is strict about

- **One theme, deliberately.** There is no dark mode. Warm paper is the brand.
- **Colour never carries a reading alone.** Every surplus/deficit marker also
  carries a word and a direction; every risk figure carries its band in words.
- **Figures are always tabular** (`font-variant-numeric: tabular-nums`), so a
  column aligns and a changing number does not jitter.
- **Mono is for strings, not words.** IBM Plex Mono (`--type-code`, or the
  `.code` class) sets HS codes, ISO codes and machine stamps — things matched
  against a source, not read.
- **Every grid child needs `min-width: 0`.** Without it a chart's intrinsic
  width pushes its panel past its column, which is what used to wrap panel
  titles onto two lines.
- **No imagery.** The product has none by choice. If a layout feels empty the
  answer is a chart with a real figure in it, not a picture.

The full guidance — content voice, visual foundations, iconography — is in the
design project's `guidelines/`.
