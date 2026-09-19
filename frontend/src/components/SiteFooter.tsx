import { formatDate } from "../lib/format";
import type { Meta } from "../types";

export function SiteFooter({ meta }: { meta?: Meta | null }) {
  return (
    <footer className="site-footer">
      <div className="footer-grid">
        <div>
          <strong>Source: UN Comtrade</strong>
          Merchandise trade, HS classification as reported.
          <br />
          Values are nominal current US dollars.
          <br />
          Macroeconomic context: World Bank.
        </div>
        {meta && (
          <div>
            <strong>Data currency</strong>
            Latest complete annual data: {meta.latest_complete_annual ?? "—"}
            <br />
            Latest available monthly data:{" "}
            {meta.latest_monthly
              ? `${meta.latest_monthly.slice(4)}/${meta.latest_monthly.slice(0, 4)}`
              : "—"}
            <br />
            Retrieved: {formatDate(meta.local_cache_updated_at)}
          </div>
        )}
        <div>
          <strong>Scope</strong>
          An analytical visualisation layer over public statistics. Original Comtrade records are
          not redistributed here.
        </div>
      </div>
      <p className="footer-credit">
        Built by{" "}
        <a href="https://mrzeynalli.xyz" target="_blank" rel="noopener noreferrer">
          Elvin Zeynalli
        </a>{" "}
        for demonstration purposes only.
      </p>
    </footer>
  );
}
