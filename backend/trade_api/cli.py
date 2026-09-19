"""trade-admin: operational command line.

Administration lives here rather than behind HTTP endpoints, so nothing that
spends API quota or rewrites storage is reachable from the public internet.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import derive, etl, eurostat, imf, ingest, jobs, refs, state, store, worker, worldbank
from .comtrade import ComtradeClient
from .config import get_settings
from .logging_setup import configure_logging

app = typer.Typer(add_completion=False, help="Global Trade Intelligence administration")
console = Console()


def _reporter_or_exit(token: str) -> dict:
    reporter = refs.resolve_reporter(token)
    if reporter is None:
        console.print(f"[red]Unknown reporter:[/red] {token}")
        console.print("Run 'trade-admin bootstrap-refs' first if reference data is missing.")
        raise typer.Exit(2)
    return reporter


def _human(n: float | int | None) -> str:
    if n is None:
        return "-"
    value = float(n)
    for threshold, suffix in ((1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= threshold:
            return f"{value / threshold:.2f}{suffix}"
    return f"{value:.0f}"


@app.command()
def status() -> None:
    """Quota, worker, jobs, cached countries and disk usage."""
    configure_logging("WARNING")
    settings = get_settings()
    quota = state.quota_today()
    remaining_soft = max(0, settings.daily_call_budget - quota["calls_made"])
    normal_cap = settings.daily_call_budget - settings.interactive_reserve

    table = Table(title="Global Trade Intelligence — status", show_header=False)
    table.add_row("Data directory", str(settings.data_dir))
    table.add_row("Calls today", f"{quota['calls_made']} / {settings.daily_call_budget}")
    table.add_row("Remaining (soft budget)", str(remaining_soft))
    table.add_row("Remaining before reserve", str(max(0, normal_cap - quota["calls_made"])))
    table.add_row("Global backfill calls today",
                  f"{quota['backfill_calls']} / {settings.global_backfill_daily_budget}")

    beats = state.worker_status()
    table.add_row("Worker", f"{beats[0]['status']} @ {beats[0]['ts_utc']}" if beats else "never seen")

    summary = jobs.summary()
    table.add_row("Jobs", ", ".join(f"{k}={v}" for k, v in sorted(summary.items())) or "none")

    annual = store.cached_reporters("A")
    monthly = store.cached_reporters("M")
    table.add_row("Cached countries (annual)", str(len(annual)))
    table.add_row("Cached countries (monthly)", str(len(monthly)))
    table.add_row("Global HS2 years", ", ".join(str(y) for y in store.global_years()) or "none")

    usage = etl.disk_usage()
    table.add_row("Parquet", f"{_human(usage['parquet_bytes'])}B")
    table.add_row("Raw cache", f"{_human(usage['raw_bytes'])}B")
    table.add_row("Total data", f"{_human(usage['total_bytes'])}B")
    table.add_row("Disk used", f"{usage['disk_used_percent']}%")
    console.print(table)

    if annual:
        reporters = refs.load_reporters()
        lookup = {int(r["reporter_code"]): r["name"] for r in reporters.to_dicts()}
        names = ", ".join(sorted(lookup.get(c, str(c)) for c in annual))
        console.print(f"\n[dim]Cached: {names}[/dim]")

    conn = state.get_conn()
    last = conn.execute(
        "SELECT ts_utc, request_type, http_status FROM api_calls "
        "WHERE cache_status='miss' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last:
        console.print(f"[dim]Last remote call: {last['ts_utc']} "
                      f"({last['request_type']}, HTTP {last['http_status']})[/dim]")


@app.command("bootstrap-refs")
def bootstrap_refs() -> None:
    """Download reporter, partner and HS reference tables (no quota cost)."""
    configure_logging()
    with ComtradeClient() as client:
        counts = refs.refresh_reference_data(client)
    console.print(f"[green]Reference data refreshed:[/green] {counts}")


@app.command("cache-country")
def cache_country(
    token: str,
    monthly: bool = typer.Option(False, "--monthly", help="Fetch the monthly pack instead"),
    from_year: Optional[int] = typer.Option(None, "--from", help="First annual year"),
    to_year: Optional[int] = typer.Option(None, "--to", help="Last annual year"),
    months: Optional[int] = typer.Option(None, "--months", help="Monthly history length"),
    force: bool = typer.Option(False, "--force", help="Ignore the local raw cache"),
    background: bool = typer.Option(False, "--background", help="Queue instead of running now"),
) -> None:
    """Fetch and store a country's summary pack."""
    configure_logging()
    reporter = _reporter_or_exit(token)
    code = int(reporter["reporter_code"])

    if background:
        kind = "country_monthly" if monthly else "country_annual"
        payload = {"reporter": code, "force": force}
        if monthly:
            payload["months"] = months
        else:
            payload.update({"start_year": from_year, "end_year": to_year})
        job = jobs.enqueue(kind, payload)
        console.print(f"[green]Queued[/green] job {job['id']} ({kind}) for {reporter['name']}")
        return

    with ComtradeClient() as client:
        if monthly:
            results = ingest.country_monthly_pack(client, code, months=months, force=force,
                                                  progress=lambda m: console.print(f"[dim]{m}[/dim]"))
        else:
            results = ingest.country_annual_pack(client, code, start_year=from_year,
                                                 end_year=to_year, force=force,
                                                 progress=lambda m: console.print(f"[dim]{m}[/dim]"))
            derive.rebuild_all(code)

    table = Table(title=f"{reporter['name']} — {'monthly' if monthly else 'annual'} pack")
    table.add_column("Dataset"); table.add_column("Rows", justify="right")
    table.add_column("API calls", justify="right"); table.add_column("Notes")
    for result in results:
        table.add_row(result.dataset, str(result.rows), str(result.calls),
                      "; ".join(result.issues)[:80] or "-")
    console.print(table)


@app.command("cache-product")
def cache_product(token: str, hs_code: str,
                  freq: str = typer.Option("A", "--freq"),
                  force: bool = typer.Option(False, "--force")) -> None:
    """Fetch the partner breakdown for one HS chapter."""
    configure_logging()
    reporter = _reporter_or_exit(token)
    code = int(reporter["reporter_code"])
    latest = store.latest_period(code, freq)
    if not latest:
        console.print("[red]Cache the country first.[/red]")
        raise typer.Exit(2)
    periods = ([str(y) for y in sorted(latest["available"])[-12:]] if freq == "A"
               else sorted(latest["available"][:12]))
    with ComtradeClient() as client:
        result = ingest.ingest_product_partners(client, code, freq, hs_code, periods, force=force)
    console.print(f"[green]{result.dataset}[/green] rows={result.rows} calls={result.calls}")


@app.command("cache-partner")
def cache_partner(token: str, partner_token: str,
                  freq: str = typer.Option("A", "--freq"),
                  force: bool = typer.Option(False, "--force")) -> None:
    """Fetch the HS2 composition of one bilateral relationship."""
    configure_logging()
    reporter = _reporter_or_exit(token)
    partner = refs.resolve_partner(partner_token)
    if partner is None:
        console.print(f"[red]Unknown partner:[/red] {partner_token}")
        raise typer.Exit(2)
    code = int(reporter["reporter_code"])
    latest = store.latest_period(code, freq)
    if not latest:
        console.print("[red]Cache the country first.[/red]")
        raise typer.Exit(2)
    periods = ([str(y) for y in sorted(latest["available"])[-12:]] if freq == "A"
               else sorted(latest["available"][:12]))
    with ComtradeClient() as client:
        result = ingest.ingest_partner_products(client, code, freq,
                                                int(partner["partner_code"]), periods, force=force)
    console.print(f"[green]{result.dataset}[/green] rows={result.rows} calls={result.calls}")


@app.command("cache-hs4")
def cache_hs4(token: str, force: bool = typer.Option(False, "--force")) -> None:
    """Fetch HS4 detail for every chapter of a reporter (one request family)."""
    configure_logging()
    reporter = _reporter_or_exit(token)
    with ComtradeClient() as client:
        result = ingest.country_hs4_pack(client, int(reporter["reporter_code"]), force=force)
    console.print(f"[green]{result.dataset}[/green] rows={result.rows} calls={result.calls}")


@app.command("backfill-global-hs2")
def backfill_global(year: int, force: bool = typer.Option(False, "--force")) -> None:
    """Cache the whole reported world HS2 matrix for a year (one call per flow)."""
    configure_logging()
    with ComtradeClient() as client:
        result = ingest.ingest_global_hs2(client, year, force=force)
    console.print(f"[green]global_hs2 {year}[/green] rows={result.rows} calls={result.calls} "
                  f"coverage={result.reconciliation}")


@app.command()
def bootstrap(
    countries: Optional[str] = typer.Option(None, "--countries", help="Comma-separated ISO3 list"),
    monthly: bool = typer.Option(True, "--monthly/--no-monthly"),
    global_year: Optional[int] = typer.Option(None, "--global-year"),
) -> None:
    """Reference data plus the demonstration country set."""
    configure_logging()
    settings = get_settings()
    targets = [c.strip().upper() for c in countries.split(",")] if countries else settings.bootstrap_list

    with ComtradeClient() as client:
        console.print("[bold]Reference data[/bold]")
        refs.refresh_reference_data(client)
        for token in targets:
            reporter = refs.resolve_reporter(token)
            if reporter is None:
                console.print(f"[yellow]skip[/yellow] unknown reporter {token}")
                continue
            code = int(reporter["reporter_code"])
            console.print(f"[bold]{reporter['name']}[/bold] annual")
            ingest.country_annual_pack(client, code,
                                       progress=lambda m: console.print(f"  [dim]{m}[/dim]"))
            derive.rebuild_all(code)
            if monthly:
                console.print(f"[bold]{reporter['name']}[/bold] monthly")
                ingest.country_monthly_pack(client, code,
                                            progress=lambda m: console.print(f"  [dim]{m}[/dim]"))
        if global_year:
            console.print(f"[bold]Global HS2 matrix {global_year}[/bold]")
            ingest.ingest_global_hs2(client, global_year)
    console.print("[green]Bootstrap complete.[/green]")
    status()


@app.command("backfill-countries")
def backfill_countries(
    countries: Optional[str] = typer.Option(None, "--countries", help="Comma-separated list; default is every active reporter"),
    monthly: bool = typer.Option(False, "--monthly", help="Fetch the monthly pack instead of annual"),
    from_year: Optional[int] = typer.Option(None, "--from"),
    to_year: Optional[int] = typer.Option(None, "--to"),
    months: Optional[int] = typer.Option(None, "--months"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Only the first N reporters"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Cache many countries at once using multi-reporter requests.

    A single request may carry several reporters, so the whole world costs tens
    of calls rather than thousands.
    """
    configure_logging()
    settings = get_settings()
    if countries:
        codes = []
        for token in countries.split(","):
            entry = refs.resolve_reporter(token.strip())
            if entry is None:
                console.print(f"[yellow]skip[/yellow] unknown reporter {token}")
                continue
            codes.append(int(entry["reporter_code"]))
    else:
        codes = ingest.active_reporters(limit)

    console.print(f"[bold]{len(codes)}[/bold] reporters, "
                  f"{'monthly' if monthly else 'annual'} pack")
    with ComtradeClient() as client:
        if monthly:
            result = ingest.bulk_monthly_backfill(
                client, codes, months=months or settings.monthly_history_months,
                force=force, progress=lambda m: console.print(f"  [dim]{m}[/dim]"))
        else:
            from datetime import date

            result = ingest.bulk_annual_backfill(
                client, codes,
                start_year=from_year or settings.annual_history_start,
                end_year=to_year or date.today().year - 1,
                force=force, progress=lambda m: console.print(f"  [dim]{m}[/dim]"))
    console.print(f"[green]Backfill complete:[/green] {result}")
    console.print("Recomputing derived metrics...")
    rebuilt = 0
    for code in codes:
        if store.has_dataset("totals", code, "A"):
            derive.rebuild_concentration(code)
            rebuilt += 1
    console.print(f"[green]Rebuilt derived metrics for {rebuilt} countries.[/green]")


@app.command("refresh-macro")
def refresh_macro(
    from_year: Optional[int] = typer.Option(None, "--from"),
    to_year: Optional[int] = typer.Option(None, "--to"),
) -> None:
    """Refresh World Bank GDP and population (free, no Comtrade quota)."""
    configure_logging()
    rows = worldbank.refresh_macro(from_year, to_year)
    console.print(f"[green]Macro indicators refreshed:[/green] {rows} rows")


@app.command("refresh-imf")
def refresh_imf(
    from_year: Optional[int] = typer.Option(None, "--from",
                                            help="Earliest year to pull; default is six years back"),
) -> None:
    """Refresh IMF ITG headline totals (free, no Comtrade quota).

    Four requests cover every country, annual and monthly. This is the source
    that carries the recent end of the record, where Comtrade has not filled in
    yet; it has no partner or product detail.
    """
    configure_logging()
    result = imf.refresh(from_year)
    console.print(f"[green]IMF ITG refreshed:[/green] {result}")
    coverage = imf.annual_coverage()
    if coverage:
        recent = sorted(coverage)[-4:]
        console.print("  annual coverage: " +
                      ", ".join(f"{y} → {coverage[y]} countries" for y in recent))
    latest = imf.latest_month()
    if latest:
        console.print(f"  latest month held: {latest['period']}")


@app.command("refresh-eurostat")
def refresh_eurostat(
    months: int = typer.Option(36, "--months", help="How many months of history to hold"),
) -> None:
    """Refresh the Eurostat intra/extra-EU split (free, no Comtrade quota).

    One request covers all 27 member states. This is the only source here that
    can say how much of a member state's trade stays inside the single market.
    """
    configure_logging()
    result = eurostat.refresh(months)
    console.print(f"[green]Eurostat refreshed:[/green] {result}")


@app.command("rebuild-world")
def rebuild_world() -> None:
    """Recompute the world overview aggregates."""
    configure_logging()
    result = derive.rebuild_world_overview()
    console.print(f"[green]World overview rebuilt:[/green] {result}")


@app.command("sync-updates")
def sync_updates() -> None:
    """Source-aware refresh: find revised datasets and queue only those."""
    configure_logging()
    with ComtradeClient() as client:
        result = worker.run_sync(client)
    console.print(f"[green]Sync complete:[/green] {result}")


@app.command("run-worker")
def run_worker() -> None:
    """Run the ingestion worker in the foreground."""
    worker.main()


@app.command("work-once")
def work_once() -> None:
    """Process a single queued job and exit."""
    configure_logging()
    console.print("handled" if worker.run_once() else "queue empty")


@app.command("retry-failed-jobs")
def retry_failed_jobs() -> None:
    """Requeue every failed job."""
    configure_logging("WARNING")
    console.print(f"Requeued {jobs.retry_failed()} job(s)")


@app.command("jobs")
def list_jobs(limit: int = typer.Option(20, "--limit")) -> None:
    """Recent jobs."""
    configure_logging("WARNING")
    table = Table(title="Recent jobs")
    for column in ("ID", "Kind", "Status", "Attempts", "Created", "Progress/Error"):
        table.add_column(column)
    for job in jobs.recent(limit):
        table.add_row(str(job["id"]), job["kind"], job["status"], str(job["attempts"]),
                      (job["created_at"] or "")[:19],
                      (job["error"] or job["progress"] or "")[:60])
    console.print(table)


@app.command()
def compact(dataset: Optional[str] = typer.Option(None, "--dataset")) -> None:
    """Rewrite Parquet partitions deduplicated and sorted."""
    configure_logging("WARNING")
    names = [dataset] if dataset else list(etl.DATASETS)
    table = Table(title="Compaction")
    for column in ("Dataset", "Files", "Before", "After"):
        table.add_column(column)
    for name in names:
        result = etl.compact_dataset(name)
        table.add_row(name, str(result["files"]), f"{_human(result['bytes_before'])}B",
                      f"{_human(result['bytes_after'])}B")
    removed = etl.cleanup_temp_files(0)
    console.print(table)
    console.print(f"Removed {removed} stale temp file(s)")


@app.command("cache-size")
def cache_size() -> None:
    """Disk usage breakdown."""
    configure_logging("WARNING")
    usage = etl.disk_usage()
    table = Table(show_header=False)
    for key, value in usage.items():
        table.add_row(key, f"{_human(value)}B" if key.endswith("bytes") or key.startswith("disk_")
                      and not key.endswith("percent") else str(value))
    console.print(table)


@app.command("clear-cache")
def clear_cache(
    dataset: Optional[str] = typer.Option(None, "--dataset"),
    reporter: Optional[str] = typer.Option(None, "--reporter"),
    raw: bool = typer.Option(False, "--raw", help="Also drop compressed API responses"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Remove cached partitions so they can be rebuilt."""
    import shutil

    configure_logging("WARNING")
    settings = get_settings()
    targets = []
    names = [dataset] if dataset else list(etl.DATASETS)
    for name in names:
        root = settings.parquet_dir / name
        if reporter:
            entry = _reporter_or_exit(reporter)
            targets.extend(root.glob(f"freq=*/reporter={int(entry['reporter_code']):03d}"))
        elif root.exists():
            targets.append(root)
    if raw:
        targets.append(settings.raw_dir)

    if not targets:
        console.print("Nothing to remove.")
        return
    console.print("Will delete:")
    for target in targets:
        console.print(f"  {target}")
    if not yes and not typer.confirm("Proceed?"):
        raise typer.Abort()
    for target in targets:
        shutil.rmtree(target, ignore_errors=True)
    console.print("[green]Removed.[/green] Analytical data can be rebuilt with cache-country.")


@app.command()
def verify(token: str) -> None:
    """Reconciliation report for a cached country."""
    configure_logging("WARNING")
    reporter = _reporter_or_exit(token)
    code = int(reporter["reporter_code"])
    for dataset in ("partners", "products_hs2"):
        version = state.dataset_version(dataset, f"freq=A/reporter={code:03d}")
        if not version:
            console.print(f"[yellow]{dataset}: not cached[/yellow]")
            continue
        coverage = json.loads(version["coverage_json"]) if version.get("coverage_json") else {}
        console.print(f"[bold]{dataset}[/bold] v{version['version']} rows={version['rows']}")
        for key, value in coverage.items():
            console.print(f"  {key}: {value}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
