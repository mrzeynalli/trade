import { lazy, Suspense, useEffect, useState } from "react";
import { AppShell } from "./components/AppShell";
import { ICONS, type SidebarSection } from "./components/Sidebar";
import { LoadingBlock } from "./components/States";
import { useRoute } from "./lib/router";
import { useResource } from "./lib/useResource";
import type { Country as CountryRow, Meta } from "./types";

const Dashboard = lazy(() => import("./pages/Dashboard").then((m) => ({ default: m.Dashboard })));
const Countries = lazy(() => import("./pages/Countries").then((m) => ({ default: m.Countries })));
const Products = lazy(() => import("./pages/Products").then((m) => ({ default: m.Products })));
const Country = lazy(() => import("./pages/Country").then((m) => ({ default: m.Country })));
const Product = lazy(() => import("./pages/Product").then((m) => ({ default: m.Product })));
const Methodology = lazy(() =>
  import("./pages/Methodology").then((m) => ({ default: m.Methodology })),
);

const COUNTRY_TABS = [
  { id: "overview", label: "Overview", icon: ICONS.overview },
  { id: "products", label: "Products", icon: ICONS.products },
  { id: "partners", label: "Partners", icon: ICONS.partners },
  { id: "insights", label: "Insights", icon: ICONS.insights },
] as const;

export default function App() {
  const { route, navigate, setParams } = useRoute();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [meta, setMeta] = useState<Meta | null>(null);

  const countryMatch = route.path.match(/^\/country\/([A-Za-z0-9]{2,4})$/);
  const token = countryMatch?.[1]?.toUpperCase() ?? null;
  // HS chapters are two digits, and are their own page rather than a panel.
  const productCode = route.path.match(/^\/product\/(\d{2})$/)?.[1] ?? null;
  const tab = route.params.get("tab") ?? "overview";

  // Only needed for the country name and flag beside the section rail.
  const countries = useResource<CountryRow[]>("/meta/countries");
  const selected = token
    ? (countries.data ?? []).find(
        (entry) => entry.iso3 === token || entry.iso2 === token || String(entry.code) === token,
      )
    : undefined;

  useEffect(() => {
    setSidebarOpen(false);
  }, [route.path]);

  const go = (path: string) => navigate(path);

  const sections: SidebarSection[] = [
    {
      label: "World",
      items: [
        {
          id: "dashboard",
          label: "Dashboard",
          icon: ICONS.dashboard,
          active: route.path === "/",
          onSelect: () => go("/"),
        },
        {
          id: "countries",
          label: "Countries",
          icon: ICONS.countries,
          active: route.path === "/countries",
          onSelect: () => go("/countries"),
        },
        {
          id: "products",
          label: "Products",
          icon: ICONS.products,
          active: route.path === "/products" || productCode !== null,
          onSelect: () => go("/products"),
        },
      ],
    },
  ];

  if (token) {
    sections.push({
      label: "Country",
      items: COUNTRY_TABS.map((entry) => ({
        id: entry.id,
        label: entry.label,
        icon: entry.icon,
        active: tab === entry.id,
        onSelect: () => setParams({ tab: entry.id === "overview" ? null : entry.id }),
      })),
    });
  }

  sections.push({
    label: "Reference",
    items: [
      {
        id: "methodology",
        label: "Methodology",
        icon: ICONS.methodology,
        active: route.path === "/methodology",
        onSelect: () => go("/methodology"),
      },
    ],
  });

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <AppShell
        sections={sections}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((open) => !open)}
        meta={meta}
        context={
          token
            ? {
                name: selected?.name ?? token,
                iso2: selected?.iso2,
                onClear: () => go("/countries"),
              }
            : null
        }
      >
        <Suspense fallback={<LoadingBlock label="Loading" />}>
          {token ? (
            <Country
              key={token}
              token={token}
              params={route.params}
              setParams={setParams}
              navigate={navigate}
              onMeta={setMeta}
            />
          ) : route.path === "/countries" ? (
            <Countries onSelect={(iso) => go(`/country/${iso}`)} />
          ) : productCode ? (
            <Product
              key={productCode}
              code={productCode}
              params={route.params}
              setParams={setParams}
              onSelectCountry={(iso) => go(`/country/${iso}`)}
              onBack={() => go("/products")}
            />
          ) : route.path === "/products" ? (
            <Products onProduct={(code) => go(`/product/${code}`)} />
          ) : route.path === "/methodology" ? (
            <Methodology />
          ) : (
            <Dashboard
              onSelect={(iso) => go(`/country/${iso}`)}
              onBrowseAll={() => go("/countries")}
            />
          )}
        </Suspense>
      </AppShell>
    </>
  );
}
