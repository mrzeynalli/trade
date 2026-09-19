
export function Methodology() {
  return (
    <>
      <div className="methodology shell-narrow">
        <span className="eyebrow">Reference</span>
        <h1>Methodology</h1>
        <p>
          What this application measures, where the numbers come from, and the limits that apply to
          each derived figure.
        </p>

        <h2>Source</h2>
        <p>
          All figures come from the UN Comtrade database of merchandise trade statistics. Countries
          report their own customs records to the United Nations Statistics Division, which
          standardises and publishes them. This application maintains a local analytical cache of
          that data; it does not republish the underlying records.
        </p>

        <h2>Reporter and partner</h2>
        <p>
          Every figure is reported by one country, the <b>reporter</b>, about its trade with
          another, the <b>partner</b>. When you select a country you are looking at what that
          country itself reported. The special partner code <code>World</code> is an aggregate
          published by the source; individual partner values are never summed together with it,
          because that would count the same trade twice.
        </p>

        <h2>Classification</h2>
        <p>
          Products follow the Harmonized System (HS) as reported by each country for each period.
          The dashboard uses HS chapters (HS2, 97 broad categories) because they are legible and
          stable enough for long comparisons. Drilldowns go to HS4 headings.
        </p>
        <p>
          HS is revised every few years. Codes shown for a given period are the ones the source
          reported for that period; they are not converted between revisions. A multi-year HS4
          series can therefore contain a definitional break, and is presented as reported rather
          than silently harmonised.
        </p>

        <h2>Imports, exports and valuation</h2>
        <p>
          Exports are generally reported free on board (FOB) and imports cost, insurance and freight
          (CIF). Import values therefore include transport and insurance costs that the matching
          export value does not. Any comparison between a country's imports and its exports — the
          trade balance included — carries that asymmetry.
        </p>

        <h2>Values</h2>
        <p>
          All values are <b>trade value in current US dollars</b> as reported. They are nominal: no
          inflation adjustment, no constant-price conversion, no exchange-rate restatement. Growth
          across many years therefore includes price change as well as volume change.
        </p>

        <h2>Missing data</h2>
        <p>
          A period a country did not report is missing, not zero. Charts leave a gap and tables show
          a dash. Nothing is interpolated, back-filled or estimated. A zero appears only where the
          source reported one.
        </p>

        <h2>Current and partial periods</h2>
        <p>
          Annual charts default to the latest <em>complete</em> year. Where an incomplete period is
          shown it is labelled <b>partial</b>, because a part-year total is not comparable with a
          full year. Monthly data runs to the latest month the source has published, which is
          usually several months behind the present.
        </p>

        <h2>Concentration</h2>
        <p>
          The Herfindahl-Hirschman Index is the sum of squared shares, on a 0–1 scale:
        </p>
        <span className="formula">HHI = Σ sᵢ²</span>
        <p>
          The <b>effective number of categories</b> is 1 / HHI — how many equally sized categories
          would produce the same concentration. Shares of 0.5, 0.3 and 0.2 give an HHI of 0.38 and
          about 2.6 effective categories. Top-1, top-3 and top-5 shares are reported alongside,
          since they are easier to reason about directly.
        </p>

        <h2>Growth and decline</h2>
        <p>
          Growth rankings compare a period with the one before it and report absolute change,
          percentage change, and contribution to the total change. A category qualifies only if its
          baseline clears a minimum, so a category that grew from a negligible base cannot dominate
          the list with an enormous percentage.
        </p>
        <p>
          Compound annual growth rate is computed only where both endpoints are positive and enough
          periods separate them; the interval used is always stated.
        </p>

        <h2>Share of reported world exports</h2>
        <p>
          The denominator is the sum of exports reported by every country present in the
          global matrix for that year. Countries that had not published for the period are absent
          from it. This is <em>reported</em> world trade, and the number of contributing reporters
          is shown alongside the figure.
        </p>

        <h2>Revealed comparative advantage</h2>
        <span className="formula">RCA = (X꜀ₚ / X꜀) ÷ (X_wₚ / X_w)</span>
        <p>
          A value above 1 means the product is a larger share of this country's export basket than
          it is of reported world exports. It describes an observed trade pattern. It does not
          demonstrate efficiency, productivity or capability, and it inherits the coverage limits of
          the world denominator above.
        </p>

        <h2>Export similarity and complementarity</h2>
        <p>
          Export similarity uses the Finger-Kreinin index, the sum over products of the smaller of
          the two countries' shares, scaled to 0–100. Trade complementarity compares one country's
          export mix with another's import mix:
        </p>
        <span className="formula">TCI = 100 × (1 − 0.5 × Σ |mₖ − xₖ|)</span>
        <p>with both share vectors normalised to sum to 1.</p>

        <h2>Mirror statistics</h2>
        <p>
          Country A's reported exports to B do not have to equal B's reported imports from A, and
          usually do not. Contributing causes include:
        </p>
        <ul>
          <li>CIF versus FOB valuation, so the importer's figure includes freight and insurance;</li>
          <li>shipments crossing a period boundary;</li>
          <li>re-exports and goods moving through a third country;</li>
          <li>rules of origin and how each customs authority attributes a partner;</li>
          <li>different customs practices and thresholds;</li>
          <li>revisions published at different times.</li>
        </ul>
        <p>
          The application reports the difference and a symmetric relative difference,
          <code> (X − M) / ((X + M) / 2)</code>. A discrepancy is a measurement artefact until
          independent evidence says otherwise; it is not presented as evidence of misreporting.
        </p>

        <h2>Unit value proxy</h2>
        <p>
          Where net weight is reported, value divided by weight gives a unit value proxy in dollars
          per kilogram. It averages over whatever mix of goods sits inside the category and over all
          partners, so it moves with composition as well as with prices. It is not a market price.
        </p>

        <h2>Unusual monthly movements</h2>
        <p>
          Month-on-month levels are dominated by trend and seasonality, so detection runs on
          year-on-year growth instead, scored with a median/MAD robust z-score against the series'
          own history. At least 24 months are required. A flag identifies a statistical outlier and
          says nothing about its cause.
        </p>

        <h2>Caching and updates</h2>
        <p>
          Data is fetched from UN Comtrade by a background process only — never in response to a
          page view. A country is ingested once, stored as compressed columnar files, and served
          locally from then on. A scheduled nightly job asks the source which datasets were
          republished and refreshes only those; historical periods that have not been revised are
          not refetched.
        </p>

        <h2>Scope</h2>
        <p>
          This is a demonstration analytics project built on public statistics. It is not a data
          redistribution service, and it is not a substitute for the official UN Comtrade database.
        </p>
      </div>
    </>
  );
}
