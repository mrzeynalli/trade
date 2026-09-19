"""Runtime configuration.

Every operational constant that an operator may reasonably want to change
lives here and is overridable through the environment, so that nothing has to
be hunted for in the source tree.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("TRADE_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Secrets -------------------------------------------------------
    # Server-side only. Never rendered into a response, a log line or a bundle.
    comtrade_api_key: str = Field(default="", alias="COMTRADE_API_KEY")
    comtrade_api_key_secondary: str = Field(default="", alias="COMTRADE_API_KEY_SECONDARY")
    imf_api_key: str = Field(default="", alias="IMF_API_KEY")
    imf_api_key_secondary: str = Field(default="", alias="IMF_API_KEY_SECONDARY")

    # --- Storage -------------------------------------------------------
    data_dir: Path = Field(default=Path("/var/lib/analytics-trade"), alias="TRADE_DATA_DIR")

    # --- Comtrade endpoints --------------------------------------------
    comtrade_base_url: str = Field(default="https://comtradeapi.un.org", alias="COMTRADE_BASE_URL")
    comtrade_reference_path: str = Field(
        default="/files/v1/app/reference", alias="COMTRADE_REFERENCE_PATH"
    )

    # --- Call budget ----------------------------------------------------
    daily_call_budget: int = Field(default=450, alias="COMTRADE_DAILY_CALL_BUDGET")
    interactive_reserve: int = Field(default=50, alias="COMTRADE_INTERACTIVE_RESERVE")
    global_backfill_daily_budget: int = Field(default=100, alias="COMTRADE_GLOBAL_BACKFILL_BUDGET")
    min_request_interval_seconds: float = Field(
        default=1.2, alias="COMTRADE_MIN_REQUEST_INTERVAL_SECONDS"
    )

    # --- API mechanics (verified against the live service) ---------------
    # The service silently truncates at exactly 100000 records and rejects
    # more than 12 periods per request. Both were confirmed empirically.
    max_records_per_request: int = Field(default=100_000, alias="COMTRADE_MAX_RECORDS")
    max_periods_per_request: int = Field(default=12, alias="COMTRADE_MAX_PERIODS")

    connect_timeout_seconds: float = Field(default=10.0, alias="COMTRADE_CONNECT_TIMEOUT")
    read_timeout_seconds: float = Field(default=180.0, alias="COMTRADE_READ_TIMEOUT")
    total_timeout_seconds: float = Field(default=240.0, alias="COMTRADE_TOTAL_TIMEOUT")
    max_retries: int = Field(default=4, alias="COMTRADE_MAX_RETRIES")
    retry_base_delay_seconds: float = Field(default=2.0, alias="COMTRADE_RETRY_BASE_DELAY")
    retry_max_delay_seconds: float = Field(default=60.0, alias="COMTRADE_RETRY_MAX_DELAY")

    # --- Ingestion defaults ---------------------------------------------
    annual_history_start: int = Field(default=2010, alias="TRADE_ANNUAL_HISTORY_START")
    monthly_history_months: int = Field(default=36, alias="TRADE_MONTHLY_HISTORY_MONTHS")
    bootstrap_countries: str = Field(
        default="AZE,CHN,USA,DEU,JPN,GBR,TUR,ITA,FRA,KOR",
        alias="TRADE_BOOTSTRAP_COUNTRIES",
    )

    # --- Analytics thresholds -------------------------------------------
    growth_min_baseline_usd: float = Field(default=1_000_000.0, alias="TRADE_GROWTH_MIN_BASELINE")
    growth_min_baseline_share: float = Field(default=0.0005, alias="TRADE_GROWTH_MIN_SHARE")
    anomaly_min_months: int = Field(default=24, alias="TRADE_ANOMALY_MIN_MONTHS")
    anomaly_z_threshold: float = Field(default=3.0, alias="TRADE_ANOMALY_Z_THRESHOLD")

    # --- Service ---------------------------------------------------------
    host: str = Field(default="127.0.0.1", alias="TRADE_HOST")
    port: int = Field(default=8092, alias="TRADE_PORT")
    base_path: str = Field(default="/trade", alias="TRADE_BASE_PATH")
    static_dir: Path | None = Field(default=None, alias="TRADE_STATIC_DIR")
    log_level: str = Field(default="INFO", alias="TRADE_LOG_LEVEL")
    lru_cache_entries: int = Field(default=256, alias="TRADE_LRU_CACHE_ENTRIES")
    lru_cache_max_bytes: int = Field(default=64 * 1024 * 1024, alias="TRADE_LRU_CACHE_MAX_BYTES")

    # --- Abuse protection -------------------------------------------------
    job_rate_limit_per_hour: int = Field(default=12, alias="TRADE_JOB_RATE_LIMIT_PER_HOUR")

    # --- Development ------------------------------------------------------
    use_fixture_data: bool = Field(default=False, alias="USE_FIXTURE_DATA")
    fixture_dir: Path | None = Field(default=None, alias="TRADE_FIXTURE_DIR")

    # --- Worker -----------------------------------------------------------
    worker_poll_seconds: float = Field(default=3.0, alias="TRADE_WORKER_POLL_SECONDS")
    raw_retention_versions: int = Field(default=2, alias="TRADE_RAW_RETENTION_VERSIONS")
    disk_warn_percent: float = Field(default=90.0, alias="TRADE_DISK_WARN_PERCENT")

    @field_validator("base_path")
    @classmethod
    def _normalise_base(cls, value: str) -> str:
        value = "/" + value.strip("/")
        return "" if value == "/" else value

    @property
    def bootstrap_list(self) -> list[str]:
        return [c.strip().upper() for c in self.bootstrap_countries.split(",") if c.strip()]

    @property
    def state_db(self) -> Path:
        return self.data_dir / "state" / "state.sqlite3"

    @property
    def refs_dir(self) -> Path:
        return self.data_dir / "refs"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def parquet_dir(self) -> Path:
        return self.data_dir / "parquet"

    @property
    def manifest_dir(self) -> Path:
        return self.data_dir / "manifests"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir / "state",
            self.refs_dir,
            self.raw_dir,
            self.parquet_dir,
            self.manifest_dir,
            self.tmp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def redact(text: str, settings: Settings | None = None) -> str:
    """Remove any occurrence of a configured subscription key from *text*.

    Applied to every string that can reach a log file, an error payload or an
    HTTP response.
    """
    settings = settings or get_settings()
    for key in (settings.comtrade_api_key, settings.comtrade_api_key_secondary,
                settings.imf_api_key, settings.imf_api_key_secondary):
        if key and len(key) >= 8:
            text = text.replace(key, "***REDACTED***")
    return text
