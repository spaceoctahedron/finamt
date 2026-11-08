"""
tests/test_eric_wrapper.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.tax.eric_wrapper — pure helpers, constants, EricError,
and the context-manager classes with the ERiC library mocked out.

No real ERiC shared library is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from finamt.tax.eric_wrapper import (
    ERIC_DRUCKE,
    ERIC_PRUEFE_HINWEISE,
    ERIC_SENDE,
    ERIC_VALIDIERE,
    EricBuffer,
    EricCertificate,
    EricError,
    EricSession,
    _dec,
    _enc,
    _lib_name,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_eric_validiere_bit(self):
        assert ERIC_VALIDIERE == 1 << 1

    def test_eric_sende_bit(self):
        assert ERIC_SENDE == 1 << 2

    def test_eric_drucke_bit(self):
        assert ERIC_DRUCKE == 1 << 5

    def test_eric_pruefe_hinweise_bit(self):
        assert ERIC_PRUEFE_HINWEISE == 1 << 7

    def test_flags_are_distinct(self):
        flags = {ERIC_VALIDIERE, ERIC_SENDE, ERIC_DRUCKE, ERIC_PRUEFE_HINWEISE}
        assert len(flags) == 4


# ---------------------------------------------------------------------------
# _enc / _dec
# ---------------------------------------------------------------------------


class TestEnc:
    def test_bytes_passthrough(self):
        assert _enc(b"hello") == b"hello"

    def test_str_encoded(self):
        assert _enc("hello") == b"hello"

    def test_none_returns_none(self):
        assert _enc(None) is None

    def test_unicode_str(self):
        assert _enc("München") == "München".encode()


class TestDec:
    def test_bytes_decoded(self):
        assert _dec(b"hello") == "hello"

    def test_raises_on_non_bytes(self):
        with pytest.raises(TypeError):
            _dec("already a string")  # type: ignore[arg-type]

    def test_empty_bytes(self):
        assert _dec(b"") == ""


# ---------------------------------------------------------------------------
# _lib_name
# ---------------------------------------------------------------------------


class TestLibName:
    def test_darwin_dylib(self):
        with patch("platform.system", return_value="Darwin"):
            name = _lib_name("ericapi")
        assert name == "libericapi.dylib"

    def test_linux_so(self):
        with patch("platform.system", return_value="Linux"):
            name = _lib_name("ericapi")
        assert name == "libericapi.so"

    def test_windows_dll(self):
        with patch("platform.system", return_value="Windows"):
            name = _lib_name("ericapi")
        assert name == "ericapi.dll"


# ---------------------------------------------------------------------------
# EricError
# ---------------------------------------------------------------------------


class TestEricError:
    def test_stores_code(self):
        err = EricError(610301010)
        assert err.code == 610301010

    def test_str_contains_code(self):
        err = EricError(42, "something went wrong")
        assert "42" in str(err)
        assert "something went wrong" in str(err)

    def test_is_exception(self):
        with pytest.raises(EricError):
            raise EricError(999)


# ---------------------------------------------------------------------------
# EricSession (mocked library)
# ---------------------------------------------------------------------------


def _mock_lib() -> MagicMock:
    """Return a MagicMock mimicking the ERiC CDLL."""
    lib = MagicMock()
    lib.EricInitialisiere.return_value = 0
    lib.EricBeende.return_value = 0
    # Buffer helpers
    _sentinel = object()  # non-None handle placeholder
    lib.EricRueckgabepufferErzeugen.return_value = _sentinel
    lib.EricRueckgabepufferFreigeben.return_value = 0
    lib.EricRueckgabepufferLaenge.return_value = 0
    lib.EricRueckgabepufferInhalt.return_value = None
    return lib


class TestEricSession:
    def test_enter_calls_initialisiere(self, tmp_path):
        lib = _mock_lib()
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                lib.EricInitialisiere.assert_called_once()
                assert session._lib is lib

    def test_exit_calls_beende(self, tmp_path):
        lib = _mock_lib()
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)):
                pass
        lib.EricBeende.assert_called_once()

    def test_init_failure_raises_eric_error(self, tmp_path):
        lib = _mock_lib()
        lib.EricInitialisiere.return_value = 610101010  # non-zero → failure
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with pytest.raises(EricError) as exc_info:
                with EricSession(str(tmp_path)):
                    pass
        assert exc_info.value.code == 610101010

    def test_missing_library_raises_os_error(self, tmp_path):
        with pytest.raises(OSError):
            with EricSession(str(tmp_path / "nonexistent")):
                pass

    def test_buf_create_and_free(self, tmp_path):
        lib = _mock_lib()
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                handle = session._buf_create()
                assert handle is not None
                session._buf_free(handle)
                lib.EricRueckgabepufferFreigeben.assert_called_once_with(handle)

    def test_buf_read_empty(self, tmp_path):
        lib = _mock_lib()
        lib.EricRueckgabepufferLaenge.return_value = 0
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                h = session._buf_create()
                assert session._buf_read(h) == b""

    def test_buf_read_nonempty(self, tmp_path):
        from ctypes import create_string_buffer

        lib = _mock_lib()
        data = b"hello eric"
        lib.EricRueckgabepufferLaenge.return_value = len(data)
        # string_at(ptr, n) needs a real pointer; use create_string_buffer
        buf = create_string_buffer(data)
        from ctypes import POINTER, c_char
        from ctypes import cast as ctypes_cast

        lib.EricRueckgabepufferInhalt.return_value = ctypes_cast(buf, POINTER(c_char))
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                h = session._buf_create()
                content = session._buf_read(h)
        assert content == data

    def test_get_error_text(self, tmp_path):
        lib = _mock_lib()
        lib.EricRueckgabepufferLaenge.return_value = 0
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                text = session.get_error_text(610301010)
                assert isinstance(text, str)

    def test_make_verschluesselungs_parameter(self, tmp_path):
        lib = _mock_lib()
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                params = session.make_verschluesselungs_parameter(42, "pin123")
                assert params.version == 3
                assert params.zertifikatHandle == 42  # stored as plain int in ctypes struct
                assert params.pin == b"pin123"

    def test_load_certificate_failure_raises(self, tmp_path):
        lib = _mock_lib()
        lib.EricGetHandleToCertificate.return_value = 610201010  # non-zero
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                with pytest.raises(EricError):
                    session.load_certificate("/path/to/cert.pfx", "pin")

    def test_bearbeite_vorgang_validate_only(self, tmp_path):
        lib = _mock_lib()
        lib.EricBearbeiteVorgang.return_value = 0
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                rc, th = session.bearbeite_vorgang(
                    b"<xml/>",
                    datenart_version="Bilanz_6_9",
                    flags=ERIC_VALIDIERE,
                )
                assert rc == 0
                assert th is None  # no ERIC_SENDE → no transfer handle

    def test_bearbeite_vorgang_with_send(self, tmp_path):
        lib = _mock_lib()
        lib.EricBearbeiteVorgang.return_value = 0
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                rc, th = session.bearbeite_vorgang(
                    b"<xml/>",
                    datenart_version="Bilanz_6_9",
                    flags=ERIC_VALIDIERE | ERIC_SENDE,
                )
                assert rc == 0
                assert th is not None  # transfer handle returned


# ---------------------------------------------------------------------------
# EricBuffer context manager
# ---------------------------------------------------------------------------


class TestEricBuffer:
    def test_enter_creates_handle(self, tmp_path):
        lib = _mock_lib()
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                with EricBuffer(session) as buf:
                    assert buf.handle() is not None

    def test_exit_frees_handle(self, tmp_path):
        lib = _mock_lib()
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                with EricBuffer(session):
                    pass
                lib.EricRueckgabepufferFreigeben.assert_called()

    def test_handle_raises_outside_context(self, tmp_path):
        lib = _mock_lib()
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                buf = EricBuffer(session)
                with pytest.raises(AssertionError):
                    buf.handle()

    def test_content_returns_bytes(self, tmp_path):
        lib = _mock_lib()
        lib.EricRueckgabepufferLaenge.return_value = 0
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                with EricBuffer(session) as buf:
                    assert isinstance(buf.content(), bytes)


# ---------------------------------------------------------------------------
# EricCertificate context manager
# ---------------------------------------------------------------------------


class TestEricCertificate:
    def test_enter_loads_certificate(self, tmp_path):
        lib = _mock_lib()
        lib.EricGetHandleToCertificate.return_value = 0  # success
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                with EricCertificate(session, "/path/cert.pfx", "pin") as cert:
                    assert cert._handle is not None
                    assert cert.verschluesselungs_parameter is not None

    def test_exit_closes_handle(self, tmp_path):
        lib = _mock_lib()
        lib.EricGetHandleToCertificate.return_value = 0
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                with EricCertificate(session, "/path/cert.pfx", "pin"):
                    pass
                lib.EricCloseHandleToCertificate.assert_called()

    def test_exit_clears_params(self, tmp_path):
        lib = _mock_lib()
        lib.EricGetHandleToCertificate.return_value = 0
        with patch("finamt.tax.eric_wrapper._load_library", return_value=lib):
            with EricSession(str(tmp_path)) as session:
                cert = EricCertificate(session, "/path/cert.pfx", "pin")
                with cert:
                    pass
                assert cert._handle is None
                assert cert.verschluesselungs_parameter is None
