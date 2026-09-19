import type { EChartsOption } from "echarts";
import {
  C, SEQUENTIAL_COLORS, SEQUENTIAL_IMPORT_COLORS, SERIES_COLORS, areaGradient, axisStyle,
  chartBase, hexAlpha, mapRegionId, rampColor, tipRow, tipTitle,
} from "./EChart";
import { compactUsd, exactUsd, percent, periodLabel, signedPercent } from "../lib/format";

type Point = { period: string; value: number | null };

function periodAxisLabel(freq: "A" | "M") {
  return (value: string) => (freq === "M" ? periodLabel(value).replace(" 20", " ’") : value);
}

function yoy(points: Point[], step: number): Map<string, number | null> {
  const out = new Map<string, number | null>();
  points.forEach((point, index) => {
    const base = points[index - step]?.value;
    out.set(
      point.period,
      point.value === null || base === null || base === undefined || base <= 0
        ? null
        : (point.value - base) / base,
    );
  });
  return out;
}

/* ------------------------------------------------------------------ series */

/** Single flow over time. Nulls stay null so a gap means "not reported". */
export function totalSeriesOption(
  points: Point[],
  flow: "X" | "M",
  freq: "A" | "M",
  partialPeriods: Set<string>,
): EChartsOption {
  const color = flow === "X" ? C.export : C.import;
  const changes = yoy(points, freq === "M" ? 12 : 1);

  return {
    ...chartBase,
    tooltip: {
      ...chartBase.tooltip,
      formatter: (params: unknown) => {
        const list = params as { axisValue: string; value: [string, number | null] }[];
        const first = list[0];
        if (!first) return "";
        const value = first.value?.[1];
        if (value === null || value === undefined) {
          return tipTitle(periodLabel(first.axisValue)) + `<span style="color:${C.muted}">No reported data</span>`;
        }
        const change = changes.get(first.axisValue);
        return (
          tipTitle(periodLabel(first.axisValue) + (partialPeriods.has(first.axisValue) ? " · partial" : "")) +
          tipRow(flow === "X" ? "Exports" : "Imports", exactUsd(value), color) +
          (change === null || change === undefined ? "" : tipRow("Year on year", signedPercent(change)))
        );
      },
    },
    xAxis: {
      type: "category",
      ...axisStyle,
      splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: C.rule } },
      axisLabel: { ...axisStyle.axisLabel, formatter: periodAxisLabel(freq), hideOverlap: true },
    },
    yAxis: {
      type: "value",
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => compactUsd(v, 0) },
    },
    series: [
      {
        type: "line",
        name: flow === "X" ? "Exports" : "Imports",
        data: points.map((p) => [p.period, p.value]),
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 6,
        showSymbol: points.length <= 26,
        connectNulls: false,
        lineStyle: { width: 2.5, color },
        itemStyle: { color, borderColor: C.surface, borderWidth: 2 },
        areaStyle: { color: areaGradient(color, 0.24) },
        emphasis: { focus: "series", scale: 1.4 },
        animationDuration: 620,
        animationEasing: "cubicOut",
      },
    ],
  };
}

/** Exports and imports together, with the gap between them shaded. */
export function dualSeriesOption(
  points: { period: string; exports: number | null; imports: number | null }[],
  freq: "A" | "M",
  options?: { showBalanceBand?: boolean },
): EChartsOption {
  return {
    ...chartBase,
    grid: { ...chartBase.grid, top: 40 },
    legend: {
      show: true,
      top: 0,
      right: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 18,
      textStyle: { color: C.muted, fontSize: 12 },
    },
    tooltip: {
      ...chartBase.tooltip,
      formatter: (params: unknown) => {
        const list = params as { axisValue: string; seriesName: string; value: [string, number | null] }[];
        if (!list.length) return "";
        const exports = list.find((e) => e.seriesName === "Exports")?.value?.[1];
        const imports = list.find((e) => e.seriesName === "Imports")?.value?.[1];
        const balance =
          exports !== null && exports !== undefined && imports !== null && imports !== undefined
            ? exports - imports
            : null;
        return (
          tipTitle(periodLabel(list[0].axisValue)) +
          tipRow("Exports", exports === null || exports === undefined ? "No reported data" : exactUsd(exports), C.export) +
          tipRow("Imports", imports === null || imports === undefined ? "No reported data" : exactUsd(imports), C.import) +
          (balance === null
            ? ""
            : tipRow(balance >= 0 ? "Surplus" : "Deficit", exactUsd(Math.abs(balance))))
        );
      },
    },
    xAxis: {
      type: "category",
      ...axisStyle,
      splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: C.rule } },
      axisLabel: { ...axisStyle.axisLabel, formatter: periodAxisLabel(freq), hideOverlap: true },
    },
    yAxis: {
      type: "value",
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => compactUsd(v, 0) },
    },
    series: [
      {
        type: "line",
        name: "Exports",
        data: points.map((p) => [p.period, p.exports]),
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 5,
        showSymbol: points.length <= 22,
        connectNulls: false,
        lineStyle: { width: 2.5, color: C.export },
        itemStyle: { color: C.export, borderColor: C.surface, borderWidth: 2 },
        areaStyle: options?.showBalanceBand ? { color: areaGradient(C.export, 0.14) } : undefined,
        emphasis: { focus: "series" },
        animationDuration: 620,
      },
      {
        type: "line",
        name: "Imports",
        data: points.map((p) => [p.period, p.imports]),
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 5,
        showSymbol: points.length <= 22,
        connectNulls: false,
        lineStyle: { width: 2.5, color: C.import },
        itemStyle: { color: C.import, borderColor: C.surface, borderWidth: 2 },
        emphasis: { focus: "series" },
        animationDuration: 620,
        animationDelay: 90,
      },
    ],
  };
}

/** Balance columns around a zero rule. Colour is backed up by the tooltip word. */
export function balanceOption(
  points: { period: string; balance: number | null }[],
  freq: "A" | "M",
): EChartsOption {
  return {
    ...chartBase,
    tooltip: {
      ...chartBase.tooltip,
      formatter: (params: unknown) => {
        const list = params as { axisValue: string; value: [string, number | null] }[];
        const value = list[0]?.value?.[1];
        if (value === null || value === undefined) {
          return tipTitle(periodLabel(list[0]?.axisValue)) + "No reported data";
        }
        return (
          tipTitle(periodLabel(list[0].axisValue)) +
          tipRow(value >= 0 ? "Trade surplus" : "Trade deficit", exactUsd(Math.abs(value)),
                 value >= 0 ? C.export : C.red)
        );
      },
    },
    xAxis: {
      type: "category",
      ...axisStyle,
      splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: C.rule } },
      axisLabel: { ...axisStyle.axisLabel, formatter: periodAxisLabel(freq), hideOverlap: true },
    },
    yAxis: {
      type: "value",
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => compactUsd(v, 0) },
    },
    series: [
      {
        type: "bar",
        name: "Trade balance",
        data: points.map((p) => [p.period, p.balance]),
        barMaxWidth: 26,
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: (params: { value?: unknown }) => {
            const pair = params.value as [string, number | null] | undefined;
            const value = pair?.[1];
            return value !== null && value !== undefined && value >= 0 ? C.export : C.red;
          },
        },
        markLine: {
          silent: true,
          symbol: "none",
          data: [{ yAxis: 0 }],
          lineStyle: { color: C.ruleStrong },
          label: { show: false },
        },
        animationDuration: 560,
        animationDelay: (index: number) => index * 18,
      },
    ],
  };
}

/** Tiny inline trend for a KPI card. No axes, no interaction. */
export function sparklineOption(values: (number | null)[], color: string): EChartsOption {
  return {
    animation: false,
    grid: { top: 3, right: 2, bottom: 3, left: 2 },
    xAxis: { type: "category", show: true, boundaryGap: false, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { show: false },
    series: [
      {
        type: "line",
        data: values,
        smooth: 0.35,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 1.8, color },
        areaStyle: { color: areaGradient(color, 0.2) },
        silent: true,
      },
    ],
  };
}

/* ------------------------------------------------------------------ composition */

/** Treemap: area encodes value, so the shape of an export basket is legible
 *  at a glance in a way a bar list is not. */
export function treemapOption(
  items: { code: string | number; name: string; value: number; share: number | null }[],
  other: { value: number; count: number } | null,
  flow: "X" | "M",
): EChartsOption {
  const base = flow === "X" ? C.export : C.import;
  const data = items.map((item, index) => ({
    name: item.name,
    value: item.value,
    code: item.code,
    share: item.share,
    itemStyle: {
      color: hexAlpha(SERIES_COLORS[index % SERIES_COLORS.length], 0.92),
      borderColor: C.surface,
      borderWidth: 2,
      gapWidth: 2,
    },
  }));
  if (other && other.value > 0) {
    data.push({
      name: "Other",
      value: other.value,
      code: "__other__",
      share: null,
      // Muted, but dark enough that the white label still reads on it.
      itemStyle: { color: hexAlpha(C.faint, 0.85), borderColor: C.surface, borderWidth: 2, gapWidth: 2 },
    });
  }

  return {
    tooltip: {
      ...chartBase.tooltip,
      trigger: "item",
      formatter: (params: unknown) => {
        const entry = params as { name: string; value: number; data: { code?: string; share?: number | null } };
        return (
          tipTitle(entry.name) +
          (entry.data.code && entry.data.code !== "__other__"
            ? tipRow("HS chapter", String(entry.data.code))
            : "") +
          tipRow(flow === "X" ? "Exports" : "Imports", exactUsd(entry.value), base) +
          (entry.data.share === null || entry.data.share === undefined
            ? ""
            : tipRow("Share", percent(entry.data.share)))
        );
      },
    },
    series: [
      {
        type: "treemap",
        data,
        top: 4, right: 4, bottom: 4, left: 4,
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        animationDuration: 620,
        animationEasing: "cubicOut",
        label: {
          show: true,
          fontFamily: '"Inter Variable", Inter, sans-serif',
          fontSize: 12,
          color: "#ffffff",
          overflow: "truncate",
          formatter: (params: unknown) => {
            const entry = params as { name: string; value: number };
            return `{name|${entry.name}}\n{value|${compactUsd(entry.value)}}`;
          },
          rich: {
            name: { fontSize: 12, fontWeight: 600, color: "#ffffff", lineHeight: 17 },
            value: { fontSize: 11, color: "rgba(255,255,255,.82)", lineHeight: 15 },
          },
        },
        upperLabel: { show: false },
        itemStyle: { borderRadius: 5 },
        emphasis: { itemStyle: { borderColor: C.ink, borderWidth: 2 } },
      },
    ],
  };
}

/* ------------------------------------------------------------------ world map */

/**
 * Choropleth keyed on UN M49 codes.
 *
 * Colours are computed per region rather than delegated to a visualMap: trade
 * is extremely skewed, and an explicit ramp makes the treatment of "no data"
 * unambiguous instead of leaving it to the component's defaults.
 *
 * Magnitude is carried by a true sequential ramp rather than by varying the
 * alpha of one flow colour: a faded fill loses contrast against warm paper at
 * the low end, where most countries sit.
 */
export function worldMapOption(
  rows: { code: number; name: string; value: number; share: number | null }[],
  flow: "X" | "M",
  regionNames: Map<string, string>,
): EChartsOption {
  const color = flow === "X" ? C.export : C.import;
  const ramp = flow === "X" ? SEQUENTIAL_COLORS : SEQUENTIAL_IMPORT_COLORS;
  const values = rows.map((r) => r.value).filter((v) => v > 0);
  const max = values.length ? Math.max(...values) : 1;
  // Square root compresses the long tail so mid-sized traders remain visible.
  const intensity = (value: number) => Math.min(1, Math.sqrt(value / max));

  return {
    tooltip: {
      ...chartBase.tooltip,
      trigger: "item",
      formatter: (params: unknown) => {
        const entry = params as {
          name: string;
          data?: { displayName?: string; raw?: number; share?: number | null };
        };
        const label = entry.data?.displayName ?? regionNames.get(entry.name) ?? entry.name;
        if (!entry.data || entry.data.raw === undefined) {
          return tipTitle(label) + `<span style="color:${C.muted}">No cached data</span>`;
        }
        return (
          tipTitle(label) +
          tipRow(flow === "X" ? "Exports" : "Imports", exactUsd(entry.data.raw), color) +
          (entry.data.share === null || entry.data.share === undefined
            ? ""
            : tipRow("Share of world", percent(entry.data.share, 2)))
        );
      },
    },
    series: [
      {
        type: "map",
        map: "world",
        roam: false,
        selectedMode: false,
        // The geometry arrives already projected, so ECharts must not apply its
        // default 0.75 vertical squash on top of it.
        aspectScale: 1,
        left: 0, right: 0, top: 6, bottom: 6,
        // Regions absent from the data keep this neutral fill.
        itemStyle: { areaColor: C.noData, borderColor: C.surface, borderWidth: 0.6 },
        emphasis: {
          itemStyle: { areaColor: C.amber, borderColor: C.surface, borderWidth: 0.8 },
          label: { show: false },
        },
        data: rows.map((row) => ({
          name: mapRegionId(row.code),
          value: row.value,
          raw: row.value,
          code: row.code,
          share: row.share,
          displayName: row.name,
          itemStyle: {
            areaColor: rampColor(ramp, intensity(row.value)),
            borderColor: C.surface,
            borderWidth: 0.6,
          },
        })),
        animationDuration: 700,
      },
    ],
  };
}

/** Legend steps for the choropleth, drawn in HTML beside the map. */
export function mapLegendStops(flow: "X" | "M"): { color: string; label: string }[] {
  const ramp = flow === "X" ? SEQUENTIAL_COLORS : SEQUENTIAL_IMPORT_COLORS;
  return [0.08, 0.3, 0.55, 0.8, 1].map((step, index) => ({
    color: rampColor(ramp, step),
    label: index === 0 ? "Less" : index === 4 ? "More" : "",
  }));
}

/* ------------------------------------------------------------------ scatter */

/** Trade openness against income: each bubble is a country, sized by trade. */
export function opennessScatterOption(
  rows: { code: number; name: string; gdpPerCapita: number; openness: number; trade: number; highlight?: boolean }[],
): EChartsOption {
  const maxTrade = Math.max(...rows.map((r) => r.trade), 1);
  return {
    ...chartBase,
    grid: { ...chartBase.grid, left: 62, right: 26, top: 26, bottom: 48 },
    tooltip: {
      ...chartBase.tooltip,
      trigger: "item",
      formatter: (params: unknown) => {
        const entry = params as { data: { name: string; value: [number, number, number] } };
        const [income, openness, trade] = entry.data.value;
        return (
          tipTitle(entry.data.name) +
          tipRow("GDP per capita", `$${Math.round(income).toLocaleString("en-US")}`) +
          tipRow("Trade openness", percent(openness / 100), C.import) +
          tipRow("Total trade", exactUsd(trade), C.export)
        );
      },
    },
    xAxis: {
      type: "log",
      name: "GDP per capita (US$, log scale)",
      nameLocation: "middle",
      nameGap: 32,
      nameTextStyle: { color: C.faint, fontSize: 11 },
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => (v >= 1000 ? `$${v / 1000}k` : `$${v}`) },
    },
    yAxis: {
      type: "value",
      name: "Trade as % of GDP",
      nameLocation: "middle",
      nameGap: 46,
      nameTextStyle: { color: C.faint, fontSize: 11 },
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => `${v}%` },
    },
    series: [
      {
        type: "scatter",
        data: rows.map((row) => ({
          name: row.name,
          code: row.code,
          value: [row.gdpPerCapita, row.openness, row.trade],
          itemStyle: {
            color: row.highlight ? C.red : hexAlpha(C.import, 0.5),
            borderColor: row.highlight ? C.red : hexAlpha(C.import, 0.8),
            borderWidth: row.highlight ? 2 : 1,
          },
        })),
        symbolSize: (value: number[]) => 6 + 34 * Math.sqrt(value[2] / maxTrade),
        emphasis: { focus: "self", itemStyle: { color: C.amber, borderColor: C.ink, borderWidth: 1.5 } },
        animationDuration: 700,
      },
    ],
  };
}

/* ------------------------------------------------------------------ misc */

export function concentrationOption(
  points: { year: number; hhi: number | null; effective: number | null }[],
): EChartsOption {
  return {
    ...chartBase,
    grid: { ...chartBase.grid, right: 52 },
    tooltip: {
      ...chartBase.tooltip,
      formatter: (params: unknown) => {
        const list = params as { axisValue: string; value: number | null; seriesName: string }[];
        const hhi = list.find((e) => e.seriesName === "HHI")?.value;
        const effective = list.find((e) => e.seriesName.startsWith("Effective"))?.value;
        return (
          tipTitle(String(list[0]?.axisValue)) +
          tipRow("HHI", hhi === null || hhi === undefined ? "—" : Number(hhi).toFixed(3), C.amber) +
          (effective === null || effective === undefined
            ? ""
            : tipRow("Effective categories", Number(effective).toFixed(1)))
        );
      },
    },
    xAxis: {
      type: "category",
      ...axisStyle,
      splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: C.rule } },
      data: points.map((p) => String(p.year)),
    },
    yAxis: [
      { type: "value", ...axisStyle, min: 0, max: 1,
        axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => v.toFixed(1) } },
      { type: "value", ...axisStyle, splitLine: { show: false },
        axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => v.toFixed(0) } },
    ],
    series: [
      {
        type: "line",
        name: "HHI",
        data: points.map((p) => p.hhi),
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 6,
        connectNulls: false,
        lineStyle: { width: 2.5, color: C.amber },
        itemStyle: { color: C.amber, borderColor: C.surface, borderWidth: 2 },
        areaStyle: { color: areaGradient(C.amber, 0.16) },
      },
      {
        type: "line",
        name: "Effective categories",
        yAxisIndex: 1,
        data: points.map((p) => p.effective),
        smooth: 0.3,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 1.6, color: C.faint, type: "dashed" },
        itemStyle: { color: C.faint },
      },
    ],
  };
}

export function sankeyOption(
  nodes: { name: string; kind: string }[],
  links: { source: string; target: string; value: number }[],
  flow: "X" | "M",
): EChartsOption {
  const accent = flow === "X" ? C.export : C.import;
  return {
    tooltip: {
      ...chartBase.tooltip,
      trigger: "item",
      formatter: (params: unknown) => {
        const entry = params as {
          dataType: string; name: string; value: number; data: { source?: string; target?: string };
        };
        if (entry.dataType === "edge") {
          return tipTitle(`${entry.data.source} → ${entry.data.target}`) +
            tipRow("Value", exactUsd(entry.value), accent);
        }
        return tipTitle(entry.name) + tipRow("Total", exactUsd(entry.value), accent);
      },
    },
    series: [
      {
        type: "sankey",
        left: 6, right: 8, top: 10, bottom: 10,
        nodeGap: 11,
        nodeWidth: 12,
        emphasis: { focus: "adjacency" },
        data: nodes.map((node, index) => ({
          name: node.name,
          itemStyle: {
            borderWidth: 0,
            color:
              node.kind === "country"
                ? C.ink
                : node.kind.endsWith("other")
                  ? C.faint
                  : node.kind === "product"
                    ? SERIES_COLORS[index % SERIES_COLORS.length]
                    : accent,
          },
        })),
        links,
        label: { color: C.inkSoft, fontSize: 11, overflow: "truncate", width: 140 },
        lineStyle: { color: "gradient", opacity: 0.32, curveness: 0.5 },
        animationDuration: 700,
      },
    ],
  };
}

export function mirrorOption(
  points: { period: string; exports: number | null; imports: number | null; relative_difference: number | null }[],
  reporterName: string,
  counterpartName: string,
): EChartsOption {
  return {
    ...chartBase,
    grid: { ...chartBase.grid, top: 42, right: 54 },
    legend: {
      show: true, top: 0, right: 0, icon: "roundRect",
      itemWidth: 10, itemHeight: 10, itemGap: 16,
      textStyle: { color: C.muted, fontSize: 11.5 },
    },
    tooltip: {
      ...chartBase.tooltip,
      formatter: (params: unknown) => {
        const list = params as { axisValue: string; seriesName: string; value: number | null }[];
        if (!list.length) return "";
        let html = tipTitle(periodLabel(list[0].axisValue));
        for (const entry of list) {
          if (entry.seriesName.startsWith("Relative")) {
            html += tipRow(entry.seriesName, entry.value === null ? "—" : percent(Number(entry.value)), C.amber);
          } else {
            html += tipRow(
              entry.seriesName,
              entry.value === null ? "No reported data" : exactUsd(Number(entry.value)),
              entry.seriesName.includes(reporterName) ? C.export : C.import,
            );
          }
        }
        return html;
      },
    },
    xAxis: {
      type: "category", ...axisStyle, splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: C.rule } },
      data: points.map((p) => p.period),
    },
    yAxis: [
      { type: "value", ...axisStyle,
        axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => compactUsd(v, 0) } },
      { type: "value", ...axisStyle, splitLine: { show: false },
        axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
    ],
    series: [
      {
        type: "bar",
        name: "Relative difference",
        yAxisIndex: 1,
        data: points.map((p) => p.relative_difference),
        barMaxWidth: 18,
        itemStyle: { color: hexAlpha(C.amber, 0.28), borderRadius: [3, 3, 0, 0] },
      },
      {
        type: "line",
        name: `${reporterName} reports exports`,
        data: points.map((p) => p.exports),
        smooth: 0.3, symbol: "circle", symbolSize: 5, connectNulls: false,
        lineStyle: { width: 2.5, color: C.export },
        itemStyle: { color: C.export, borderColor: C.surface, borderWidth: 2 },
      },
      {
        type: "line",
        name: `${counterpartName} reports imports`,
        data: points.map((p) => p.imports),
        smooth: 0.3, symbol: "circle", symbolSize: 5, connectNulls: false,
        lineStyle: { width: 2.5, color: C.import },
        itemStyle: { color: C.import, borderColor: C.surface, borderWidth: 2 },
      },
    ],
  };
}


/** World trade in one HS chapter across the years the matrix holds. */
export function productSeriesOption(
  points: { year: number; period: string; value: number; reporters: number }[],
): EChartsOption {
  const reporters = new Map(points.map((p) => [p.period, p.reporters]));
  return {
    ...chartBase,
    grid: { ...chartBase.grid, left: 66 },
    tooltip: {
      ...chartBase.tooltip,
      formatter: (params: unknown) => {
        const list = params as { axisValue: string; value: [string, number] }[];
        const first = list[0];
        if (!first) return "";
        return (
          tipTitle(first.axisValue) +
          tipRow("Reported world exports", exactUsd(first.value?.[1]), C.export) +
          tipRow("Reporting countries", String(reporters.get(first.axisValue) ?? "—"))
        );
      },
    },
    xAxis: {
      type: "category",
      ...axisStyle,
      splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: C.rule } },
    },
    yAxis: {
      type: "value",
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => compactUsd(v, 0) },
    },
    series: [
      {
        type: "line",
        name: "Reported world exports",
        data: points.map((p) => [p.period, p.value]),
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { width: 2.5, color: C.export },
        itemStyle: { color: C.export, borderColor: C.surface, borderWidth: 2 },
        areaStyle: { color: areaGradient(C.export, 0.16) },
      },
    ],
  };
}
