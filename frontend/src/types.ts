export type Meta = {
  source: string;
  frequency: "annual" | "monthly";
  classification: string;
  measure: string;
  reporter: { code: number; name: string; iso3: string | null; iso2: string | null };
  latest_complete_annual: number | null;
  latest_annual: number | null;
  latest_monthly: string | null;
  latest_complete_period: string | number | null;
  partial: boolean;
  last_source_update: string | null;
  local_cache_updated_at: string | null;
  dataset_version: number;
  stale: boolean;
  composition_period?: string | null;
  monthly_available?: boolean;
  hs4_available?: boolean;
  quota?: { calls_today: number; daily_budget: number };
};

export type Envelope<T> = { data: T; meta: Meta };

export type SeriesPoint = {
  period: string;
  year: number;
  month: number | null;
  exports: number | null;
  imports: number | null;
  balance: number | null;
  export_weight?: number | null;
  import_weight?: number | null;
};

export type RankItem = {
  key: string | number;
  code: string | number;
  name: string;
  iso3?: string | null;
  value: number;
  share: number | null;
  weight: number | null;
  unit_value?: number | null;
};

export type Ranking = {
  items: RankItem[];
  other: { value: number; share: number | null; count: number } | null;
  total: number | null;
  count: number;
  available: boolean;
};

export type JobState = {
  status: "preparing";
  message: string;
  job: { id: number; status: string; progress: string | null };
};

export type Summary = {
  status: "ready";
  kpis: {
    period: string | null;
    composition_period: string | null;
    exports: number | null;
    imports: number | null;
    balance: number | null;
    export_change: number | null;
    import_change: number | null;
    top_export_destination: RankItem | null;
    top_import_origin: RankItem | null;
  };
  series: SeriesPoint[];
  export_products: Ranking;
  import_products: Ranking;
  export_partners: Ranking;
  import_partners: Ranking;
};

export type Country = {
  code: number;
  name: string;
  iso2: string | null;
  iso3: string | null;
  is_group: boolean;
  cached: boolean;
  cached_monthly: boolean;
};

export type ConcentrationProfile = {
  hhi: number | null;
  hhi_scaled: number | null;
  effective_number: number | null;
  top1_share: number | null;
  top3_share: number | null;
  top5_share: number | null;
  categories: number;
};

export type GrowthEntry = {
  key: string | number;
  code: string | number;
  name: string;
  current: number;
  previous: number;
  absolute_change: number;
  percent_change: number | null;
  contribution: number | null;
};

export type GrowthTable = {
  available: boolean;
  current_period?: string[];
  previous_period?: string[];
  growing: GrowthEntry[];
  declining: GrowthEntry[];
};

export type Insights = {
  composition_period: string | null;
  dependency: {
    export_products: ConcentrationProfile;
    import_products: ConcentrationProfile;
    export_partners: ConcentrationProfile;
    import_partners: ConcentrationProfile;
  };
  concentration_history: {
    year: number;
    flow_code: string;
    dimension: string;
    hhi: number | null;
    effective_number: number | null;
    top1_share: number | null;
    top3_share: number | null;
    top5_share: number | null;
    categories: number;
  }[];
  product_growth: GrowthTable;
  import_growth: GrowthTable;
  partner_growth: GrowthTable;
  export_cagr: { value: number | null; from: string; to: string; years: number } | null;
  sentences: string[];
  top_export_products: RankItem[];
  top_import_products: RankItem[];
  top_export_partners: RankItem[];
  top_import_partners: RankItem[];
};

export type BalanceView = {
  series: { period: string; balance: number | null; exports: number | null; imports: number | null }[];
  composition_period: string | null;
  partner_surpluses: BalanceRow[];
  partner_deficits: BalanceRow[];
  product_surpluses: BalanceRow[];
  product_deficits: BalanceRow[];
};

export type BalanceRow = {
  key: string | number;
  code: string | number;
  name: string;
  iso3?: string | null;
  exports: number | null;
  imports: number | null;
  balance: number;
  complete: boolean;
};

export type ProductDetail = {
  code: string;
  name: string;
  level: number;
  flow: string;
  value: number | null;
  share_of_flow: number | null;
  change: number | null;
  series: (SeriesPoint & { period: string })[];
  children: Ranking;
  partners: Ranking;
  partners_status: "ready" | "preparing";
  unit_values: { period: string; unit_value: number | null }[];
  composition_period: string | null;
  classification_note: string;
};

export type PartnerDetail = {
  partner: { code: number; name: string; iso3: string | null; iso2: string | null };
  series: { period: string; exports: number | null; imports: number | null; balance: number | null }[];
  exports: number | null;
  imports: number | null;
  balance: number | null;
  period: string | null;
  export_share_of_total: number | null;
  import_share_of_total: number | null;
  export_change: number | null;
  import_change: number | null;
  export_products: Ranking;
  import_products: Ranking;
  products_status: "ready" | "preparing";
  composition_period: string | null;
};

export type NetworkView = {
  available: boolean;
  nodes: { name: string; kind: string; code?: string | number }[];
  links: { source: string; target: string; value: number }[];
  flow: string;
  composition_period: string | null;
};

export type AdvancedView = {
  year?: number;
  available_years?: number[];
  global_share: { available: boolean; items?: ShareRow[]; note?: string; reason?: string };
  rca: { available: boolean; items?: RcaRow[]; note?: string; reason?: string };
  similarity: { available: boolean; items?: SimilarityRow[]; note?: string; reason?: string };
  coverage: { available: boolean; reporters?: number; reporters_included?: number; coverage_note?: string };
};

export type ShareRow = { code: string; name: string; value: number; world_value: number | null; share: number };
export type RcaRow = ShareRow & { rca: number; country_share: number | null; world_share: number | null };
export type SimilarityRow = { code: number; name: string; iso3: string | null; similarity: number };

export type MirrorView = {
  available: boolean;
  reason?: string;
  reporter?: { code: number; name: string };
  counterpart?: { code: number; name: string };
  series?: { period: string; exports: number | null; imports: number | null; difference: number | null; relative_difference: number | null }[];
  note?: string;
  status?: string;
  job?: { id: number; status: string; progress: string | null };
};

export type AnomalyView = {
  available: boolean;
  reason?: string;
  months_observed?: number;
  min_months_required?: number;
  totals?: { period: string; value: number; yoy: number | null; robust_z: number; direction: string }[];
  products?: { code: string; name: string; period: string; value: number; yoy: number | null; robust_z: number; direction: string }[];
  note?: string;
};

export type WorldRow = {
  code: number;
  iso3: string | null;
  name: string;
  value: number;
  share?: number | null;
  change?: number | null;
  /** The opposite flow, so a directory can sort on it without a second list. */
  imports?: number | null;
};

export type WorldOverview = {
  available: boolean;
  reason?: string;
  year: number;
  years: number[];
  latest_complete: number | null;
  partial: boolean;
  totals: {
    exports: number | null;
    imports: number | null;
    balance: number | null;
    reporters: number;
    export_change: number | null;
    import_change: number | null;
  };
  series: { year: number; period: string; exports: number | null; imports: number | null; reporters: number }[];
  series_note?: string;
  coverage_by_year?: { year: number; reporters: number }[];
  map: WorldRow[];
  map_imports: WorldRow[];
  top_traders: WorldRow[];
  top_importers: WorldRow[];
  fastest_growing: WorldRow[];
  largest_declines: WorldRow[];
  products: {
    available: boolean;
    items?: { code: string; name: string; value: number; share: number | null }[];
    other?: { value: number; count: number; share: number | null };
    total?: number;
  };
  openness: {
    code: number;
    iso3: string | null;
    name: string;
    gdp_per_capita: number;
    openness: number;
    trade: number;
  }[];
  coverage: { reporters: number; note: string };
};

export type MacroView = {
  available: boolean;
  reason?: string;
  gdp_year?: number | null;
  gdp_usd?: number | null;
  population?: number | null;
  gdp_per_capita?: number | null;
  trade_openness?: number | null;
  exports_over_gdp?: number | null;
  imports_over_gdp?: number | null;
  balance_over_gdp?: number | null;
  exports_per_capita?: number | null;
  imports_per_capita?: number | null;
  trade_year?: number;
  exports?: number | null;
  imports?: number | null;
  history?: { year: number; openness: number | null; exports_over_gdp?: number | null; imports_over_gdp?: number | null; gdp_usd: number | null }[];
  note?: string;
  source?: string;
};


/**
 * The newest reading available, sourced from the IMF rather than UN Comtrade.
 *
 * Comtrade carries the partner and product detail the rest of the site is built
 * on, but a reference year takes one to two years to fill in. The IMF's ITG
 * collection publishes the same headline aggregates months earlier and for more
 * countries. The two are never summed — this payload is entirely IMF-sourced.
 */
export type WorldRecent = {
  available: boolean;
  reason?: string;
  year: number;
  countries: number;
  /** How many countries Comtrade holds for the same year, for comparison. */
  comtrade_countries: number;
  totals: {
    exports: number | null;
    imports: number | null;
    balance: number | null;
    export_change: number | null;
    import_change: number | null;
  };
  map: WorldRow[];
  top_traders: WorldRow[];
  monthly: { period: string; label: string; countries: number } | null;
  coverage: {
    countries: number;
    by_year: { year: number; countries: number }[];
    note: string;
  };
};


/**
 * The intra/extra-EU split, from Eurostat.
 *
 * Comtrade sees the Union as 27 reporters with bilateral partners and cannot
 * express this without summing 26 partners per country. Eurostat collects it
 * directly. Values are euro — never added to the dollar figures elsewhere on
 * the site — so the shares are what the interface leans on.
 */
export type EuropeSplit = {
  iso3: string;
  geo: string;
  name: string;
  period: string;
  label: string;
  exports_eur: number | null;
  imports_eur: number | null;
  intra_export_share: number | null;
  intra_import_share: number | null;
  extra_export_share: number | null;
  extra_import_share: number | null;
};

export type EuropeOverview = {
  available: boolean;
  reason?: string;
  period: string;
  label: string;
  member_states: number;
  union: {
    exports_eur: number | null;
    intra_share: number | null;
    extra_share: number | null;
  };
  members: EuropeSplit[];
  coverage: { note: string };
};


/** One HS chapter, as the product page reads it. */
export type WorldProduct = {
  available: boolean;
  reason?: string;
  code?: string;
  name?: string;
  year?: number;
  years?: number[];
  world_total?: number | null;
  world_import_total?: number | null;
  change?: number | null;
  concentration?: number | null;
  reporters?: number;
  import_reporters?: number;
  exporters?: {
    code: number;
    name: string;
    iso2: string | null;
    iso3: string | null;
    value: number;
    share: number | null;
  }[];
  importers?: WorldProduct["exporters"];
  series?: { year: number; period: string; value: number; reporters: number }[];
  coverage?: { note: string };
};
