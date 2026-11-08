"""
tests/test_cli_inprocess.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
In-process tests for FinamtCLI with FinanceAgent fully mocked.
"""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from finamt.cli import FinamtCLI, app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _success_result(
    mocker,
    *,
    cp_name="Test GmbH",
    amount=119,
    vat=19,
    category="software",
    items=None,
    receipt_type="purchase",
    receipt_date=None,
    vat_pct=19,
    proc_time=1.0,
):
    r = mocker.Mock()
    r.success = True
    r.duplicate = False
    r.data.receipt_type.__str__ = lambda self: receipt_type
    r.data.counterparty.name = cp_name
    r.data.total_amount = Decimal(str(amount))
    r.data.vat_amount = Decimal(str(vat))
    r.data.vat_percentage = vat_pct
    r.data.category = category
    r.data.items = items or []
    r.data.receipt_date = receipt_date
    r.processing_time = proc_time
    r.data.to_json.return_value = '{"vendor": "Test GmbH"}'
    r.to_dict.return_value = {"success": True}
    return r


def _fail_result(mocker):
    r = mocker.Mock()
    r.success = False
    r.duplicate = False
    r.error_message = "OCR failed"
    r.to_dict.return_value = {"success": False}
    return r


def _dup_result(mocker, cp_name="Test GmbH"):
    r = mocker.Mock()
    r.success = True
    r.duplicate = True
    r.existing_id = "abc123xyz"
    r.data.counterparty.name = cp_name
    r.to_dict.return_value = {"duplicate": True}
    return r


# ---------------------------------------------------------------------------
# print_version
# ---------------------------------------------------------------------------


class TestPrintVersion:
    def test_version_printed(self, capsys):
        FinamtCLI().print_version()
        assert "finamt version" in capsys.readouterr().out

    def test_version_fallback_when_package_missing(self, mocker, capsys):
        mocker.patch("finamt.cli.version", side_effect=Exception("not installed"))
        FinamtCLI().print_version()
        assert "unknown" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# process_receipt
# ---------------------------------------------------------------------------


class TestProcessReceipt:
    def test_success(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        assert FinamtCLI().process_receipt("r", tmp_path) == 0

    def test_success_with_verbose(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        FinamtCLI().process_receipt("r", tmp_path, verbose=True)
        assert "Processing" in capsys.readouterr().out

    def test_success_writes_json_to_output_dir(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        out_dir = tmp_path / "out"
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        rc = FinamtCLI().process_receipt("r", tmp_path, output_dir=out_dir)
        assert rc == 0
        assert (out_dir / "r_extracted.json").exists()

    def test_missing_file_returns_1(self, tmp_path):
        assert FinamtCLI().process_receipt("ghost", tmp_path) == 1

    def test_failure_returns_1(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _fail_result(mocker)
        assert FinamtCLI().process_receipt("r", tmp_path) == 1
        assert "failed" in capsys.readouterr().err.lower()

    def test_duplicate_returns_0(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _dup_result(mocker)
        assert FinamtCLI().process_receipt("r", tmp_path) == 0
        assert "Duplicate" in capsys.readouterr().out

    def test_no_db_flag(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        FinamtCLI().process_receipt("r", tmp_path, no_db=True)
        mock_cls.assert_called_once_with(db_path=None)

    def test_explicit_db_path(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        db = tmp_path / "custom.db"
        FinamtCLI().process_receipt("r", tmp_path, db_path=db)
        mock_cls.assert_called_once_with(db_path=db)

    def test_sale_type(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_instance = mocker.patch("finamt.cli.FinanceAgent").return_value
        mock_instance.process_receipt.return_value = _success_result(mocker, receipt_type="sale")
        FinamtCLI().process_receipt("r", tmp_path, receipt_type="sale")
        mock_instance.process_receipt.assert_called_once_with(
            tmp_path / "r.pdf", receipt_type="sale"
        )


# ---------------------------------------------------------------------------
# batch_process
# ---------------------------------------------------------------------------


class TestBatchProcess:
    def test_success_two_pdfs(self, mocker, tmp_path, capsys):
        for name in ("a.pdf", "b.pdf"):
            (tmp_path / name).write_text("x")
        res = _success_result(mocker, receipt_date=datetime(2024, 3, 15))
        mocker.patch("finamt.cli.FinanceAgent").return_value.process_receipt.return_value = res
        rc = FinamtCLI().batch_process(tmp_path)
        out = capsys.readouterr().out
        assert rc == 0
        assert "BATCH PROCESSING REPORT" in out

    def test_no_pdfs_returns_1(self, tmp_path):
        assert FinamtCLI().batch_process(tmp_path) == 1

    def test_failure_counted_in_report(self, mocker, tmp_path, capsys):
        (tmp_path / "bad.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _fail_result(mocker)
        rc = FinamtCLI().batch_process(tmp_path)
        assert rc == 1
        assert "✗" in capsys.readouterr().out

    def test_duplicate_in_batch(self, mocker, tmp_path, capsys):
        (tmp_path / "dup.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _dup_result(mocker)
        rc = FinamtCLI().batch_process(tmp_path)
        assert rc == 0
        assert "duplicate" in capsys.readouterr().out.lower()

    def test_writes_json_output(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        out_dir = tmp_path / "out"
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        FinamtCLI().batch_process(tmp_path, output_dir=out_dir)
        assert (out_dir / "r_extracted.json").exists()

    def test_verbose_mode(self, mocker, tmp_path, capsys):
        (tmp_path / "v.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        FinamtCLI().batch_process(tmp_path, verbose=True)
        assert "Processing" in capsys.readouterr().out

    def test_no_db_flag(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        FinamtCLI().batch_process(tmp_path, no_db=True)
        mock_cls.assert_called_once_with(db_path=None)

    def test_report_has_category_breakdown(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(
            mocker, category="software", amount=100, vat=19
        )
        FinamtCLI().batch_process(tmp_path)
        assert "software" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# ingest_receipts
# ---------------------------------------------------------------------------


class TestIngestReceipts:
    def test_no_pdfs(self, tmp_path, capsys):
        count = FinamtCLI().ingest_receipts(tmp_path)
        assert count == 0
        assert "No PDF" in capsys.readouterr().out

    def test_success_increments_saved(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        count = FinamtCLI().ingest_receipts(tmp_path)
        assert count == 1
        assert "saved" in capsys.readouterr().out

    def test_duplicate_increments_dupes(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _dup_result(mocker)
        count = FinamtCLI().ingest_receipts(tmp_path)
        assert count == 0
        out = capsys.readouterr().out
        assert "duplicate" in out.lower()

    def test_failure_not_counted(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _fail_result(mocker)
        count = FinamtCLI().ingest_receipts(tmp_path)
        assert count == 0

    def test_verbose_ok(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(
            mocker, receipt_date=datetime(2024, 1, 1)
        )
        FinamtCLI().ingest_receipts(tmp_path, verbose=True)
        assert "OK" in capsys.readouterr().out

    def test_verbose_duplicate(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _dup_result(mocker)
        FinamtCLI().ingest_receipts(tmp_path, verbose=True)
        assert "DUPLICATE" in capsys.readouterr().out

    def test_verbose_failed(self, mocker, tmp_path, capsys):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _fail_result(mocker)
        FinamtCLI().ingest_receipts(tmp_path, verbose=True)
        assert "FAILED" in capsys.readouterr().out

    def test_explicit_db_path(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        db = tmp_path / "custom.db"
        FinamtCLI().ingest_receipts(tmp_path, db_path=db)
        mock_cls.assert_called_once_with(db_path=db)


# ---------------------------------------------------------------------------
# _quarter_bounds
# ---------------------------------------------------------------------------


class TestQuarterBounds:
    @pytest.mark.parametrize(
        "q,start,end",
        [
            (1, (2024, 1, 1), (2024, 3, 31)),
            (2, (2024, 4, 1), (2024, 6, 30)),
            (3, (2024, 7, 1), (2024, 9, 30)),
            (4, (2024, 10, 1), (2024, 12, 31)),
        ],
    )
    def test_quarter_bounds(self, q, start, end):
        from datetime import date

        s, e = FinamtCLI._quarter_bounds(q, 2024)
        assert s == date(*start)
        assert e == date(*end)


# ---------------------------------------------------------------------------
# run_ustva
# ---------------------------------------------------------------------------


class TestRunUstva:
    def _mock_report(self, mocker):
        report = mocker.Mock()
        report.summary.return_value = "UStVA Q1 2024 summary"
        return report

    def test_no_receipts_returns_1(self, mocker, tmp_path, capsys):
        mocker.patch("finamt.cli.get_repository").__enter__ = mocker.Mock(
            return_value=mocker.Mock(find_by_period=mocker.Mock(return_value=[]))
        )
        # Patch via context manager protocol
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(find_by_period=MagicMock(return_value=[]))
        cm.__exit__.return_value = False
        mocker.patch("finamt.cli.get_repository", return_value=cm)
        rc = FinamtCLI().run_ustva(quarter=1, year=2024, db_path=tmp_path / "finamt.db")
        assert rc == 1
        assert "No receipts" in capsys.readouterr().out

    def test_generates_report(self, mocker, tmp_path, capsys):
        mock_receipt = mocker.Mock()
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(find_by_period=MagicMock(return_value=[mock_receipt]))
        cm.__exit__.return_value = False
        mocker.patch("finamt.cli.get_repository", return_value=cm)
        mocker.patch("finamt.cli.generate_ustva", return_value=self._mock_report(mocker))

        rc = FinamtCLI().run_ustva(quarter=1, year=2024)
        assert rc == 0
        assert "UStVA" in capsys.readouterr().out

    def test_saves_to_explicit_output(self, mocker, tmp_path, capsys):
        mock_receipt = mocker.Mock()
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(find_by_period=MagicMock(return_value=[mock_receipt]))
        cm.__exit__.return_value = False
        mocker.patch("finamt.cli.get_repository", return_value=cm)
        report = self._mock_report(mocker)
        mocker.patch("finamt.cli.generate_ustva", return_value=report)

        out_file = tmp_path / "report.json"
        FinamtCLI().run_ustva(quarter=2, year=2024, output=out_file)
        report.to_json.assert_called_once_with(out_file)

    def test_saves_to_output_dir(self, mocker, tmp_path, capsys):
        mock_receipt = mocker.Mock()
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(find_by_period=MagicMock(return_value=[mock_receipt]))
        cm.__exit__.return_value = False
        mocker.patch("finamt.cli.get_repository", return_value=cm)
        report = self._mock_report(mocker)
        mocker.patch("finamt.cli.generate_ustva", return_value=report)

        out_dir = tmp_path / "reports"
        FinamtCLI().run_ustva(quarter=3, year=2024, output_dir=out_dir)
        assert out_dir.is_dir()
        report.to_json.assert_called_once_with(out_dir / "ustva_q3_2024.json")


# ---------------------------------------------------------------------------
# Typer CLI integration (replaces TestBuildParser)
# ---------------------------------------------------------------------------


class TestTyperCLI:
    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "finamt version" in result.output

    def test_process_with_file_and_input_dir(self, mocker, tmp_path):
        (tmp_path / "r1.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        result = runner.invoke(app, ["process", "r1", "--input-dir", str(tmp_path)])
        assert result.exit_code == 0

    def test_batch_with_input_dir(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        result = runner.invoke(app, ["batch", "--input-dir", str(tmp_path)])
        assert result.exit_code == 0

    def test_type_sale(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker, receipt_type="sale")
        result = runner.invoke(
            app, ["process", "r", "--input-dir", str(tmp_path), "--type", "sale"]
        )
        assert result.exit_code == 0

    def test_ustva_quarter_and_year(self, mocker):
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(find_by_period=MagicMock(return_value=[]))
        cm.__exit__.return_value = False
        mocker.patch("finamt.cli.get_repository", return_value=cm)
        result = runner.invoke(app, ["ustva", "--quarter", "2", "--year", "2023"])
        assert result.exit_code == 1  # no receipts → non-zero

    def test_serve_args(self, mocker):
        mock_launch = mocker.patch("finamt.ui.server.launch")
        result = runner.invoke(app, ["serve", "--no-browser", "--port", "9000"])
        assert result.exit_code == 0
        mock_launch.assert_called_once()

    def test_db_option(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        db = str(tmp_path / "custom.db")
        result = runner.invoke(app, ["batch", "--input-dir", str(tmp_path), "--db", db])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# main() / app dispatch (via Typer CliRunner)
# ---------------------------------------------------------------------------


class TestMain:
    def test_version_flag_exits_0(self, mocker):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "finamt version" in result.output

    def test_no_args_shows_help_exits_0(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_single_receipt_dispatch(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        result = runner.invoke(app, ["process", "r", "--input-dir", str(tmp_path)])
        assert result.exit_code == 0

    def test_batch_dispatch(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        result = runner.invoke(app, ["batch", "--input-dir", str(tmp_path)])
        assert result.exit_code == 0

    def test_ustva_dispatch_no_receipts(self, mocker):
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(find_by_period=MagicMock(return_value=[]))
        cm.__exit__.return_value = False
        mocker.patch("finamt.cli.get_repository", return_value=cm)
        result = runner.invoke(app, ["ustva", "--quarter", "1", "--year", "2024"])
        assert result.exit_code == 1

    def test_ustva_dispatch_with_ingest(self, mocker, tmp_path):
        """finamt ustva --input-dir triggers ingest then UStVA."""
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(find_by_period=MagicMock(return_value=[]))
        cm.__exit__.return_value = False
        mocker.patch("finamt.cli.get_repository", return_value=cm)
        mocker.patch("finamt.cli.FinanceAgent")
        result = runner.invoke(
            app, ["ustva", "--input-dir", str(tmp_path), "--quarter", "1", "--year", "2024"]
        )
        assert result.exit_code == 1  # no receipts in DB → 1

    def test_verbose_enables_logging(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mocker.patch(
            "finamt.cli.FinanceAgent"
        ).return_value.process_receipt.return_value = _success_result(mocker)
        with patch("logging.basicConfig") as mock_log:
            runner.invoke(app, ["process", "r", "--input-dir", str(tmp_path), "--verbose"])
            mock_log.assert_called_once()

    def test_serve_dispatch(self, mocker):
        mock_launch = mocker.patch("finamt.ui.server.launch")
        result = runner.invoke(app, ["serve", "--no-browser"])
        assert result.exit_code == 0
        mock_launch.assert_called_once()

    def test_serve_dispatch_with_port_and_log_level(self, mocker):
        mock_launch = mocker.patch("finamt.ui.server.launch")
        result = runner.invoke(
            app, ["serve", "--port", "9000", "--log-level", "debug", "--no-browser"]
        )
        assert result.exit_code == 0
        call_kwargs = mock_launch.call_args
        assert call_kwargs.kwargs.get("port") == 9000 or call_kwargs.args[1] == 9000

    def test_no_db_flag_passed_through(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        runner.invoke(app, ["process", "r", "--input-dir", str(tmp_path), "--no-db"])
        mock_cls.assert_called_once_with(db_path=None)

    def test_db_flag_passed_through(self, mocker, tmp_path):
        (tmp_path / "r.pdf").write_text("x")
        db = str(tmp_path / "custom.db")
        mock_cls = mocker.patch("finamt.cli.FinanceAgent")
        mock_cls.return_value.process_receipt.return_value = _success_result(mocker)
        runner.invoke(app, ["process", "r", "--input-dir", str(tmp_path), "--db", db])
        mock_cls.assert_called_once_with(db_path=Path(db))
