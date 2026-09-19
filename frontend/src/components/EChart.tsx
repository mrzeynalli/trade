import { BarChart, LineChart, MapChart, SankeyChart, ScatterChart, TreemapChart } from "echarts/charts";
import {
  GeoComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { useEffect, useRef, useState } from "react";

echarts.use([
  BarChart,
  LineChart,
  MapChart,
  SankeyChart,
  ScatterChart,
  TreemapChart,
  GeoComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

/**
 * The design-system palette, in the form ECharts needs.
 *
 * ECharts paints to a canvas and cannot read a CSS custom property, so the
 * token values are mirrored here rather than referenced. Every value below is
 * one of the tokens in `src/tokens/` — keep the two in step, and change the
 * token first.
 */
export const C = {
  export: "#24544c", // --flow-export      / --teal-800
  exportMid: "#3d7d70", // --accent-mid    / --teal-600
  exportWash: "#e7efec", // --flow-export-wash / --teal-50
  import: "#5864de", // --flow-import      / --indigo-600
  importMid: "#7b85e8", // --indigo-500
  importWash: "#eceefb", // --flow-import-wash / --indigo-50
  red: "#d8483b", // --flow-deficit        / --coral-600
  redWash: "#fbecea", // --coral-50
  amber: "#c98a2e", // --amber-600
  ink: "#16211e", // --text-strong         / --n-900
  inkSoft: "#3c4a45", // --text-body       / --n-700
  muted: "#5c6b66", // --text-muted        / --n-600
  faint: "#8a9691", // --text-faint        / --n-500
  rule: "#e4e0d8", // --chart-grid         / --n-200
  ruleStrong: "#cfc9bd", // --chart-crosshair / --n-300
  noData: "#efece4", // --chart-no-data    / --n-150
  surface: "#ffffff", // --chart-marker-stroke / --n-0
  paper: "#fbfaf7", // --surface-page      / --n-25
} as const;

/**
 * Categorical, unordered: products, partners, regions. Consecutive entries are
 * the pair furthest apart in hue and lightness, because consecutive entries are
 * the pair most likely to sit adjacent. Mirrors `--series-1..10`.
 */
export const SERIES_COLORS = [
  "#24544c", "#5864de", "#c98a2e", "#cf4f88", "#2b9cc4",
  "#7a5be0", "#5d9440", "#d8483b", "#8fb3aa", "#a7aef0",
];

/**
 * Sequential magnitude, one hue, light to dark. Choropleths and volume
 * heatmaps — never a categorical chart, where an ordering would be read into
 * it. Mirrors `--seq-1..6`.
 */
export const SEQUENTIAL_COLORS = [
  "#e7efec", "#c3ded5", "#95c5b8", "#5fa494", "#35786a", "#1c4a42",
];

/**
 * The indigo counterpart to SEQUENTIAL_COLORS, for the import choropleth.
 *
 * The design system ships one sequential ramp, built on the brand teal — but
 * exports are green and imports are indigo in every other view, and a map is
 * not the place to break that. So the import map gets a ramp of the same shape
 * cut from the indigo scale (`--indigo-50` through `--indigo-900`). Nothing
 * here is a new colour; only a new ordering of existing ones.
 */
export const SEQUENTIAL_IMPORT_COLORS = [
  "#eceefb", "#d8dbf8", "#a7aef0", "#7b85e8", "#5864de", "#2d3488",
];

/**
 * Diverging around zero: balances, net direction, z-scores. Always drawn with
 * the zero rule visible. Mirrors `--div-neg-2..--div-pos-2`.
 */
export const DIVERGING_COLORS = [
  "#b03528", "#e08d84", "#efece4", "#8fb3aa", "#24544c",
];

/** Interpolate a ramp at `t` in [0, 1]. Used for choropleth fills. */
export function rampColor(ramp: readonly string[], t: number): string {
  const clamped = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
  const position = clamped * (ramp.length - 1);
  const low = Math.floor(position);
  const high = Math.min(ramp.length - 1, low + 1);
  return mixHex(ramp[low], ramp[high], position - low);
}

const FONT = '"Inter Variable", Inter, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif';
const SERIF = '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif';

export const chartBase = {
  grid: { top: 22, right: 16, bottom: 28, left: 62, containLabel: false },
  textStyle: { fontFamily: FONT, color: C.muted },
  tooltip: {
    trigger: "axis" as const,
    backgroundColor: C.surface,
    borderColor: C.ruleStrong,
    borderWidth: 1,
    padding: [12, 14] as [number, number],
    textStyle: { color: C.ink, fontSize: 12.5, fontFamily: FONT },
    extraCssText:
      "box-shadow: 0 12px 40px -8px rgba(22,33,30,.22); border-radius: 10px; line-height: 1.6;",
    axisPointer: { lineStyle: { color: C.ruleStrong, type: "dashed" as const } },
  },
};

export const axisStyle = {
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: C.faint, fontSize: 11, fontFamily: FONT },
  splitLine: { lineStyle: { color: C.rule, type: "solid" as const } },
};

/** Tooltip heading in the display serif, so charts speak the page's voice. */
export function tipTitle(text: string): string {
  return `<div style="font-family:${SERIF};font-size:15px;font-weight:600;margin-bottom:6px;letter-spacing:-.01em">${text}</div>`;
}

export function tipRow(label: string, value: string, color?: string): string {
  const dot = color
    ? `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${color};margin-right:7px"></span>`
    : "";
  return `<div style="display:flex;justify-content:space-between;gap:20px"><span style="color:${C.muted}">${dot}${label}</span><b style="font-variant-numeric:tabular-nums">${value}</b></div>`;
}

/** A soft vertical gradient used under area lines. */
export function areaGradient(color: string, opacity = 0.22) {
  return {
    type: "linear" as const,
    x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [
      { offset: 0, color: hexAlpha(color, opacity) },
      { offset: 1, color: hexAlpha(color, 0) },
    ],
  };
}

export function hexAlpha(hex: string, alpha: number): string {
  const [r, g, b] = rgb(hex);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Blend two hexes in sRGB. Only used to interpolate between ramp steps. */
export function mixHex(from: string, to: string, t: number): string {
  const a = rgb(from);
  const b = rgb(to);
  const channel = (index: number) =>
    Math.round(a[index] + (b[index] - a[index]) * t)
      .toString(16)
      .padStart(2, "0");
  return `#${channel(0)}${channel(1)}${channel(2)}`;
}

function rgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ];
}

/**
 * Comtrade reporter codes that differ from the ISO 3166-1 numeric ids the world
 * topology is keyed on.
 *
 * Comtrade reports a handful of economies as a customs territory rather than a
 * country, and gives that territory its own code: 842 is the USA including
 * Puerto Rico and the US Virgin Islands, 251 is France including Monaco, 757 is
 * Switzerland including Liechtenstein, 579 is Norway including Svalbard, and
 * 699 is India on its pre-2000 code. Each maps onto exactly one polygon, so the
 * value is drawn on the territory a reader expects — the alternative was the
 * USA, France, Switzerland, Norway and India silently going unshaded, which is
 * what this map did before.
 *
 * Singapore, Hong Kong and Macao are deliberately absent: the 110m topology has
 * no polygon for them at all, and folding them into China would attribute one
 * economy's trade to another.
 */
const REGION_ALIASES: Record<string, string> = {
  "842": "840", // USA (incl. Puerto Rico, US Virgin Isds)
  "251": "250", // France (incl. Monaco)
  "757": "756", // Switzerland (incl. Liechtenstein)
  "579": "578", // Norway (incl. Svalbard and Jan Mayen)
  "699": "356", // India
};

/**
 * The topology's id for a reporter code.
 *
 * Feature ids are three-digit strings, so a code below 100 has to be padded
 * before it will match — without which every reporter from Albania to Brunei
 * failed to join.
 */
export function mapRegionId(code: number | string): string {
  const padded = String(code).padStart(3, "0");
  return REGION_ALIASES[padded] ?? padded;
}

let mapReady: Promise<Map<string, string>> | null = null;

/**
 * The world topology is ~105 KB, so it loads only when a map is actually
 * rendered.
 *
 * The geometry is projected with d3's Equal Earth projection before it reaches
 * ECharts. Feeding raw longitude/latitude to a chart library stretches the map
 * badly — ECharts also applies a 0.75 aspect squash to geo coordinates by
 * default — whereas d3's stream pipeline projects *and* clips at the
 * antimeridian, so Russia no longer smears across the whole frame. Equal Earth
 * is equal-area, which is the honest choice when area is being read as a
 * quantity.
 *
 * Feature ids are UN M49 codes, exactly the numbers Comtrade uses for
 * reporters, so each feature is renamed to its code and the English name is
 * returned separately for tooltips.
 */
export function ensureWorldMap(): Promise<Map<string, string>> {
  if (!mapReady) {
    mapReady = (async () => {
      const [{ default: topology }, topo, { geoEqualEarth }, { geoProject }] = await Promise.all([
        import("world-atlas/countries-110m.json"),
        import("topojson-client"),
        import("d3-geo"),
        import("d3-geo-projection"),
      ]);

      const geo = topo.feature(
        topology as never,
        (topology as never as { objects: { countries: never } }).objects.countries,
      ) as unknown as {
        type: string;
        features: { id?: string; properties: { name?: string }; geometry: unknown }[];
      };

      // Antarctica has no trade and its polygon dominates any world projection.
      geo.features = geo.features.filter((entry) => entry.id !== "010");

      const names = new Map<string, string>();
      for (const entry of geo.features) {
        const code = String(entry.id ?? "");
        names.set(code, entry.properties.name ?? code);
        entry.properties.name = code;
      }

      const projected = geoProject(geo as never, geoEqualEarth()) as unknown as {
        features: { geometry: { coordinates: unknown } | null }[];
      };
      // d3 returns screen coordinates with y increasing downward; ECharts reads
      // the second ordinate as northing, so the sign is flipped once here.
      for (const entry of projected.features) {
        if (entry.geometry) flipVertical(entry.geometry.coordinates);
      }

      echarts.registerMap("world", projected as never);
      return names;
    })();
  }
  return mapReady;
}

function flipVertical(coordinates: unknown): void {
  if (!Array.isArray(coordinates)) return;
  if (typeof coordinates[0] === "number") {
    (coordinates as number[])[1] = -(coordinates as number[])[1];
    return;
  }
  for (const child of coordinates) flipVertical(child);
}

/** Region code to English name, available once the topology has loaded. */
export let worldRegionNames: Map<string, string> = new Map();

type Props = {
  option: EChartsOption;
  className?: string;
  /** Read aloud in place of the chart; state the headline finding, not "a chart". */
  ariaLabel: string;
  onSelect?: (params: { name: string; data: unknown; value: unknown }) => void;
  /** Wait for the world topology before first render. */
  needsMap?: boolean;
};

export function EChart({ option, className = "chart", ariaLabel, onSelect, needsMap }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const instance = useRef<echarts.ECharts | null>(null);
  const handler = useRef(onSelect);
  handler.current = onSelect;
  const [mapLoaded, setMapLoaded] = useState(!needsMap);

  useEffect(() => {
    if (!needsMap) return;
    let cancelled = false;
    void ensureWorldMap().then((names) => {
      worldRegionNames = names;
      if (!cancelled) setMapLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [needsMap]);

  useEffect(() => {
    if (!element.current || !mapLoaded) return;
    const chart = echarts.init(element.current, undefined, { renderer: "canvas" });
    instance.current = chart;
    chart.on("click", (params) => {
      handler.current?.({
        name: (params as { name: string }).name,
        data: (params as { data: unknown }).data,
        value: (params as { value: unknown }).value,
      });
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, [mapLoaded]);

  useEffect(() => {
    if (!mapLoaded) return;
    instance.current?.setOption(option, { notMerge: true });
  }, [option, mapLoaded]);

  return <div ref={element} className={className} role="img" aria-label={ariaLabel} />;
}
