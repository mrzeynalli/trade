"""Normalisation, atomic writes, validation and double-count protection."""

from __future__ import annotations

import polars as pl
import pytest

from conftest import comtrade_rows
from trade_api import etl


class TestNormalisation:
    def test_basic_record(self):
        frame = etl.normalise_rows([comtrade_rows(primaryValue=1234.5)])
        assert frame.height == 1
        row = frame.row(0, named=True)
        assert row["reporter_code"] == 31
        assert row["year"] == 2024
        assert row["month"] == 0
        assert row["flow_code"] == "X"
        assert row["primary_value"] == pytest.approx(1234.5)
        assert row["hs_code"] == "TOTAL"
        assert row["hs_level"] == 0

    def test_hs_leading_zero_survives(self):
        frame = etl.normalise_rows([comtrade_rows(cmdCode="01")])
        assert frame.row(0, named=True)["hs_code"] == "01"
        assert frame.row(0, named=True)["hs_level"] == 2

    def test_monthly_period_is_split(self):
        frame = etl.normalise_rows(
            [comtrade_rows(freqCode="M", period="202503", refYear=2025, refMonth=3)]
        )
        row = frame.row(0, named=True)
        assert row["year"] == 2025
        assert row["month"] == 3

    def test_a_row_without_a_value_is_dropped_not_zeroed(self):
        frame = etl.normalise_rows([comtrade_rows(primaryValue=None)])
        assert frame.height == 0

    def test_reported_zero_is_kept(self):
        frame = etl.normalise_rows([comtrade_rows(primaryValue=0.0)])
        assert frame.height == 1
        assert frame.row(0, named=True)["primary_value"] == 0.0

    def test_filler_weight_and_quantity_become_null(self):
        frame = etl.normalise_rows([comtrade_rows(netWgt=0.0, qty=0.0)])
        row = frame.row(0, named=True)
        assert row["net_weight"] is None
        assert row["quantity"] is None

    def test_real_weight_is_kept(self):
        frame = etl.normalise_rows([comtrade_rows(netWgt=5000.0)])
        assert frame.row(0, named=True)["net_weight"] == pytest.approx(5000.0)

    def test_unknown_flow_codes_are_ignored(self):
        frame = etl.normalise_rows([comtrade_rows(flowCode="ZZ")])
        assert frame.height == 0

    def test_impossible_month_is_rejected(self):
        frame = etl.normalise_rows(
            [comtrade_rows(freqCode="M", period="202513", refYear=2025, refMonth=13)]
        )
        assert frame.height == 0

    def test_empty_input_returns_typed_empty_frame(self):
        frame = etl.normalise_rows([])
        assert frame.height == 0
        assert "primary_value" in frame.columns


class TestAtomicWrites:
    def test_write_is_visible_only_when_complete(self, settings):
        target = settings.parquet_dir / "probe" / "part.parquet"
        frame = pl.DataFrame({"a": [1, 2, 3]})
        etl.atomic_write_parquet(frame, target)
        assert target.exists()
        assert pl.read_parquet(target).height == 3
        assert not list(target.parent.glob(".*tmp*"))

    def test_a_failed_write_leaves_no_temp_file(self, settings, monkeypatch):
        target = settings.parquet_dir / "probe2" / "part.parquet"

        def explode(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(pl.DataFrame, "write_parquet", explode)
        with pytest.raises(OSError):
            etl.atomic_write_parquet(pl.DataFrame({"a": [1]}), target)
        assert not target.exists()
        assert not list(target.parent.glob(".*tmp*"))

    def test_zstd_is_the_stored_compression(self, settings):
        import pyarrow.parquet as pq

        target = settings.parquet_dir / "probe3" / "part.parquet"
        etl.atomic_write_parquet(pl.DataFrame({"a": list(range(1000))}), target)
        metadata = pq.ParquetFile(target).metadata
        assert metadata.row_group(0).column(0).compression.upper() == "ZSTD"


class TestMerge:
    def test_merge_deduplicates_on_the_logical_key(self, settings):
        rows = etl.normalise_rows([comtrade_rows(primaryValue=100.0)])
        etl.merge_into_partition("totals", rows, freq="A", reporter=31)
        newer = etl.normalise_rows([comtrade_rows(primaryValue=200.0)])
        path, count = etl.merge_into_partition("totals", newer, freq="A", reporter=31)
        assert count == 1
        assert pl.read_parquet(path).row(0, named=True)["primary_value"] == pytest.approx(200.0)

    def test_replace_scope_removes_rows_the_source_dropped(self, settings):
        first = etl.normalise_rows([
            comtrade_rows(refYear=2024, period="2024", cmdCode="27"),
            comtrade_rows(refYear=2024, period="2024", cmdCode="84"),
        ])
        etl.merge_into_partition("products_hs2", first, freq="A", reporter=31)
        # A revision in which chapter 84 no longer appears for 2024.
        revised = etl.normalise_rows([comtrade_rows(refYear=2024, period="2024", cmdCode="27")])
        path, count = etl.merge_into_partition(
            "products_hs2", revised, freq="A", reporter=31, replace_scope=[("year", [2024])]
        )
        assert count == 1
        assert pl.read_parquet(path)["hs_code"].to_list() == ["27"]

    def test_other_years_are_untouched_by_a_scoped_replace(self, settings):
        etl.merge_into_partition(
            "totals",
            etl.normalise_rows([
                comtrade_rows(refYear=2023, period="2023"),
                comtrade_rows(refYear=2024, period="2024"),
            ]),
            freq="A", reporter=31,
        )
        path, count = etl.merge_into_partition(
            "totals",
            etl.normalise_rows([comtrade_rows(refYear=2024, period="2024", primaryValue=999.0)]),
            freq="A", reporter=31, replace_scope=[("year", [2024])],
        )
        frame = pl.read_parquet(path).sort("year")
        assert count == 2
        assert frame["year"].to_list() == [2023, 2024]
        assert frame.row(1, named=True)["primary_value"] == pytest.approx(999.0)


class TestValidation:
    def test_world_rows_are_rejected_from_a_bilateral_dataset(self):
        frame = etl.normalise_rows([comtrade_rows(partnerCode=0)])
        report = etl.validate_facts("partners", frame, scope="t", expect_partner="bilateral")
        assert not report.ok
        assert any("double-count" in issue for issue in report.issues)

    def test_bilateral_rows_are_rejected_from_a_world_dataset(self):
        frame = etl.normalise_rows([comtrade_rows(partnerCode=380)])
        report = etl.validate_facts("totals", frame, scope="t", expect_partner="world")
        assert not report.ok

    def test_a_clean_frame_passes(self):
        frame = etl.normalise_rows([comtrade_rows(partnerCode=0)])
        report = etl.validate_facts("totals", frame, scope="t", expect_partner="world")
        assert report.ok
        assert report.rows == 1

    def test_invalid_reporter_is_fatal(self):
        frame = etl.normalise_rows([comtrade_rows(reporterCode=0)])
        report = etl.validate_facts("totals", frame, scope="t")
        assert not report.ok

    def test_malformed_commodity_codes_are_reported(self):
        frame = etl.normalise_rows([comtrade_rows(cmdCode="27X")])
        report = etl.validate_facts("products_hs2", frame, scope="t")
        assert any("malformed" in issue for issue in report.issues)


class TestReconciliation:
    def test_difference_is_reported_not_corrected(self):
        result = etl.reconcile_components(105.0, 100.0)
        assert result["difference"] == pytest.approx(5.0)
        assert result["relative_difference"] == pytest.approx(0.05)

    def test_exact_agreement(self):
        result = etl.reconcile_components(100.0, 100.0)
        assert result["difference"] == pytest.approx(0.0)

    def test_missing_side_gives_no_verdict(self):
        assert etl.reconcile_components(None, 100.0)["difference"] is None
        assert etl.reconcile_components(100.0, 0.0)["difference"] is None


class TestHousekeeping:
    def test_compaction_deduplicates(self, settings):
        path = etl.partition_path("totals", freq="A", reporter=31)
        rows = etl.normalise_rows([comtrade_rows()])
        etl.atomic_write_parquet(pl.concat([rows, rows]), path)
        assert pl.read_parquet(path).height == 2
        result = etl.compact_dataset("totals")
        assert result["files"] == 1
        assert pl.read_parquet(path).height == 1

    def test_temp_cleanup(self, settings):
        stale = settings.parquet_dir / ".part.parquet.tmp999"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"x")
        assert etl.cleanup_temp_files(older_than_seconds=0) >= 1
        assert not stale.exists()

    def test_disk_usage_reports_each_area(self, settings):
        usage = etl.disk_usage()
        for key in ("raw_bytes", "parquet_bytes", "total_bytes", "disk_free", "disk_used_percent"):
            assert key in usage
