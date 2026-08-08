"""
finamt.ui.api
~~~~~~~~~~~~~~~~
FastAPI backend for the finamt web UI.

Every receipt/tax endpoint accepts an optional ``?db=`` query parameter
(absolute path to a .db file). If omitted, the default project is used (~/.finamt/default/finamt.db).
This lets the frontend switch between multiple databases without restarting.

Endpoints
---------
GET    /health
GET    /config
GET    /projects                   — list projects under ~/.finamt/
POST   /projects                   — create a new project folder
DELETE /projects/{name}            — delete a project (keeps PDFs optional)
GET    /databases                  — legacy alias for /projects
GET    /taxpayer                   — read taxpayer profile for a project
PUT    /taxpayer                   — save taxpayer profile for a project
DELETE /taxpayer                   — clear taxpayer profile for a project
POST   /receipts                   — create a manual receipt entry (no file)
POST   /receipts/upload
GET    /receipts
GET    /receipts/{id}
GET    /receipts/{id}/pdf
PATCH  /receipts/{id}
DELETE /receipts/{id}
POST   /receipts/{id}/counterparty    — reassign receipt to a different supplier (find-or-create)
GET    /counterparties                 — all counterparty rows
GET    /counterparties/verified        — deduplicated verified counterparties
DELETE /counterparties/{id}            — remove a counterparty row
PATCH  /counterparties/{id}/verify    — set verified flag
GET    /tax/ustva?quarter=1&year=2024
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import urllib.request
from datetime import date
from pathlib import Path
from typing import Annotated

# Load .env from the project directory (or any parent) at import time
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(override=False)  # does not overwrite already-set env vars
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# finamt integration
# ---------------------------------------------------------------------------
try:
    from finamt.agents.agent import FinanceAgent
    from finamt.agents.config import AgentsConfig, Config
    from finamt.agents.prompts import RECEIPT_CATEGORIES
    from finamt.storage.project import (
        DB_FILENAME,
        DEFAULT_PROJECT,
        FINAMT_HOME,
        layout_from_db_path,
        list_projects,
        resolve_project,
        validate_project_name,
    )
    from finamt.storage.sqlite import SQLiteRepository
    from finamt.tax.bilanz import generate_jahresabschluss
    from finamt.tax.ebilanz import EBilanzConfig, build_xbrl
    from finamt.tax.ustva import generate_ustva

    _LIB_AVAILABLE = True
    _cfg = Config()
    _agents_cfg = AgentsConfig()
except ImportError as _import_err:
    import sys
    import traceback

    print("\n[finamt] IMPORT ERROR — library failed to load:", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    print(file=sys.stderr)
    _LIB_AVAILABLE = False
    _cfg = None  # type: ignore
    _agents_cfg = None  # type: ignore
    RECEIPT_CATEGORIES = [
        "material",
        "equipment",
        "internet",
        "telecommunication",
        "software",
        "education",
        "travel",
        "utilities",
        "insurance",
        "taxes",
        "other",
    ]
    FINAMT_HOME = Path.home() / ".finamt"
    DB_FILENAME = "finamt.db"
    DEFAULT_PROJECT = "default"

    def list_projects():
        return []  # type: ignore

    def resolve_project(n=None):
        return None  # type: ignore

    def validate_project_name(n):
        return None  # type: ignore

    def layout_from_db_path(p):
        return None  # type: ignore


# Runtime config overrides — values set via PUT /config are stored here.
# Reconstructed Config / AgentsConfig objects are rebuilt on each update.
_runtime_cfg: dict = {}


def _effective_agents_cfg():
    """Return an AgentsConfig reflecting current runtime overrides."""
    if not _LIB_AVAILABLE or _agents_cfg is None:
        return None
    return AgentsConfig(**{**_agents_cfg.model_dump(), **_runtime_cfg})


def _effective_ocr_cfg():
    """Return a Config (OCR) reflecting current runtime overrides."""
    if not _LIB_AVAILABLE or _cfg is None:
        return None
    return Config(**{**_cfg.model_dump(), **_runtime_cfg})


# Computed once at startup — never relies on sqlite.py's DEFAULT_DB_PATH
_DEFAULT_LAYOUT = resolve_project(DEFAULT_PROJECT)
_DEFAULT_DB = _DEFAULT_LAYOUT.db_path

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
    "application/pdf",
}

# Maps file extension → MIME type for serving stored originals
_EXT_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}
# Extensions to probe when looking for a stored receipt file
_STORED_EXTS = list(_EXT_MIME.keys())

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="finamt API",
    version="0.2.0",
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_layout(db: str | None, project: str | None = None):
    """
    Resolve a ProjectLayout from either an explicit db path or a project name.
    Priority: explicit db path > project name > "default".
    Always returns a proper ProjectLayout — never the old flat path.
    """
    if db:
        p = Path(db)
        if p.suffix != ".db":
            raise HTTPException(status_code=400, detail="db must be a .db file path.")
        return layout_from_db_path(p)
    return resolve_project(project or DEFAULT_PROJECT)


def _resolve_db(db: str | None) -> Path:
    """Backward-compat shim — returns the db_path from _resolve_layout."""
    return _resolve_layout(db).db_path


def _pdf_dir(db_path: Path) -> Path:
    """PDFs live in pdfs/ inside the project root (sibling of finamt.db)."""
    layout = layout_from_db_path(db_path)
    return layout.pdfs_dir if layout else db_path.parent / "pdfs"


def _repo(db_path: Path) -> SQLiteRepository:
    if not _LIB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="finamt library not installed.",
        )
    return SQLiteRepository(db_path=db_path)


def _require_db(db_path: Path) -> None:
    """Raise 404 if the database file doesn't exist yet.
    Prevents SQLite from creating an empty file on read-only requests.
    The db is created lazily on first write (upload).
    """
    if not db_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No database at {db_path}. Upload a receipt to initialise it.",
        )


def _find_stored_file(receipt_id: str, db_path: Path) -> Path | None:
    """Return the stored original file path regardless of extension, or None."""
    base = _pdf_dir(db_path) / receipt_id
    for ext in _STORED_EXTS:
        p = base.with_suffix(ext)
        if p.exists():
            return p
    return None


def _receipt_to_response(r, db_path: Path) -> dict:
    d = r.to_dict()
    stored = _find_stored_file(r.id, db_path)
    d["pdf_url"] = f"/receipts/{r.id}/pdf" if stored else None
    return d


def _project_entry(layout, active_db: str | None = None) -> dict:
    """Serialise a ProjectLayout to a JSON-safe dict."""
    receipt_count = 0
    size_kb = 0.0
    if layout.db_path.exists():
        size_kb = round(layout.db_path.stat().st_size / 1024, 1)
        if _LIB_AVAILABLE:
            try:
                with SQLiteRepository(db_path=layout.db_path) as repo:
                    receipt_count = sum(1 for _ in repo.list_all())
            except Exception:
                pass
    is_active = active_db == str(layout.db_path) or (active_db is None and layout.is_default)
    return {
        "name": layout.name,
        "path": str(layout.db_path),
        "root": str(layout.root),
        "size_kb": size_kb,
        "receipts": receipt_count,
        "is_default": layout.is_default,
        "is_active": is_active,
        "exists": layout.db_path.exists(),
    }


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "library_available": _LIB_AVAILABLE,
        "db_path": str(_DEFAULT_DB),
        "db_exists": _DEFAULT_DB.exists(),
    }


@app.get("/fx-rate", tags=["meta"])
def fx_rate(
    from_currency: str = Query(..., alias="from"), to: str = "EUR", date: str | None = None
):
    """Proxy Frankfurter exchange-rate lookup so the browser avoids CORS issues.
    When `date` (YYYY-MM-DD) is supplied the historical rate for that day is
    returned; otherwise the latest available rate is used."""
    segment = date if date else "latest"
    url = f"https://api.frankfurter.dev/v1/{segment}?from={from_currency.upper()}&to={to.upper()}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "finamt/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Rate lookup failed: {exc}") from exc
    rate = (data.get("rates") or {}).get(to.upper())
    if rate is None:
        raise HTTPException(status_code=404, detail=f"No rate for {from_currency} → {to}")
    return {"base": from_currency.upper(), "to": to.upper(), "rate": rate, "date": data.get("date")}


@app.get("/config", tags=["meta"])
def get_config():
    if not _LIB_AVAILABLE or _cfg is None or _agents_cfg is None:
        return {"error": "finamt library not available", "categories": RECEIPT_CATEGORIES}
    effective_agents = _effective_agents_cfg()
    effective_ocr = _effective_ocr_cfg()
    ac = effective_agents.get_agent_config()
    return {
        # agent settings
        "agent_model": ac.model,
        "agent_timeout": ac.timeout,
        "agent_num_ctx": ac.num_ctx,
        "agent_max_retries": ac.max_retries,
        # OCR settings
        "ocr_language": effective_ocr.ocr_language,
        "ocr_timeout": effective_ocr.ocr_timeout,
        "ocr_preprocess": effective_ocr.ocr_preprocess,
        "tesseract_cmd": effective_ocr.tesseract_cmd,
        "pdf_dpi": effective_ocr.pdf_dpi,
        # meta
        "categories": RECEIPT_CATEGORIES,
        "default_db": str(_DEFAULT_DB),
    }


@app.put("/config", tags=["meta"])
def put_config(body: dict = Body(...)):
    """Update runtime config overrides. Accepts any subset of config keys."""
    global _runtime_cfg
    if not _LIB_AVAILABLE or _agents_cfg is None or _cfg is None:
        raise HTTPException(status_code=503, detail="finamt library not available")
    # Allowed keys — map frontend names to pydantic field names
    _AGENT_KEYS = {
        "agent_model": str,
        "agent_timeout": int,
        "agent_num_ctx": int,
        "agent_max_retries": int,
    }
    _OCR_KEYS = {
        "ocr_language": str,
        "ocr_timeout": int,
        "ocr_preprocess": bool,
        "tesseract_cmd": str,
        "pdf_dpi": int,
    }
    allowed = {**_AGENT_KEYS, **_OCR_KEYS}
    updates: dict = {}
    for k, cast in allowed.items():
        if k in body:
            try:
                updates[k] = cast(body[k])
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"Invalid value for {k}: {exc}"
                ) from exc
    _runtime_cfg = {**_runtime_cfg, **updates}
    return get_config()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@app.get("/projects", tags=["projects"])
def list_projects_endpoint(active_db: str | None = Query(default=None)):
    """
    List all projects under ~/.finamt/.
    Each project is a subdirectory containing finamt.db.
    """
    projects = list_projects()
    return {
        "projects": [_project_entry(p, active_db) for p in projects],
        "finamt_home": str(FINAMT_HOME),
        "default_db": str(_DEFAULT_DB),
    }


@app.post("/projects", status_code=status.HTTP_201_CREATED, tags=["projects"])
def create_project(body: dict = Body(...)):
    """
    Create a new project folder and initialise its SQLite database.
    Body: { "name": "acme-gmbh-2025" }
    """
    name = (body.get("name") or "").strip().lower()
    err = validate_project_name(name)
    if err:
        raise HTTPException(status_code=400, detail=err)

    layout = resolve_project(name)
    if layout.db_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Project '{name}' already exists.",
        )

    # Create directories and initialise DB (SQLite creates on first connect)
    layout.create_dirs()
    if _LIB_AVAILABLE:
        try:
            with SQLiteRepository(db_path=layout.db_path):
                pass  # schema init happens in __init__
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"DB init failed: {exc}") from exc

    return _project_entry(layout)


@app.delete("/projects/{name}", status_code=status.HTTP_204_NO_CONTENT, tags=["projects"])
def delete_project(name: str, keep_pdfs: bool = Query(default=True)):
    """
    Delete a project's database (and optionally its debug folder).
    PDFs are kept by default (keep_pdfs=true).
    The 'default' project cannot be deleted.
    """
    if name == "default":
        raise HTTPException(status_code=403, detail="Cannot delete the default project.")

    layout = resolve_project(name)
    if not layout.db_path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found.")

    import shutil

    layout.db_path.unlink(missing_ok=True)
    if layout.debug_dir.exists():
        shutil.rmtree(layout.debug_dir, ignore_errors=True)
    if not keep_pdfs and layout.pdfs_dir.exists():
        shutil.rmtree(layout.pdfs_dir, ignore_errors=True)
    # Remove project root only if now empty
    try:
        layout.root.rmdir()
    except OSError:
        pass  # not empty — PDFs still there, leave it


# Legacy alias — the frontend used /databases before the project refactor
@app.get("/databases", tags=["projects"])
def list_databases(active_db: str | None = Query(default=None)):
    """Legacy alias for GET /projects — kept for backwards compatibility."""
    return list_projects_endpoint(active_db=active_db)


# ---------------------------------------------------------------------------
# Taxpayer profile  (stored in project_metadata under the key "taxpayer")
# ---------------------------------------------------------------------------

_TAXPAYER_KEY = "taxpayer"


@app.get("/taxpayer", tags=["projects"])
def get_taxpayer(db: str | None = Query(default=None)):
    """Return the taxpayer profile stored in this project's DB, or null."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"taxpayer": None}
    with _repo(db_path) as repo:
        profile = repo.get_metadata(_TAXPAYER_KEY)
    return {"taxpayer": profile}


@app.put("/taxpayer", tags=["projects"])
def set_taxpayer(body: dict = Body(...), db: str | None = Query(default=None)):
    """Save the taxpayer profile into this project's DB."""
    db_path = _resolve_db(db)
    # Initialise DB if it doesn't exist yet
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _repo(db_path) as repo:
        repo.set_metadata(_TAXPAYER_KEY, body)
    return {"taxpayer": body}


@app.delete("/taxpayer", status_code=status.HTTP_204_NO_CONTENT, tags=["projects"])
def delete_taxpayer(db: str | None = Query(default=None)):
    """Remove the taxpayer profile from this project's DB."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return
    with _repo(db_path) as repo:
        repo.delete_metadata(_TAXPAYER_KEY)


# ---------------------------------------------------------------------------
# Submissions log  (stored in project_metadata under the key "submissions")
# ---------------------------------------------------------------------------

_SUBMISSIONS_KEY = "submissions"


@app.get("/submissions", tags=["projects"])
def get_submissions(db: str | None = Query(default=None)):
    """Return all recorded submission events for this project."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"submissions": []}
    with _repo(db_path) as repo:
        records = repo.get_metadata(_SUBMISSIONS_KEY) or []
    return {"submissions": records}


@app.post("/submissions", tags=["projects"])
def add_submission(body: dict = Body(...), db: str | None = Query(default=None)):
    """Append a submission record {type, year, submitted_at, note?}."""
    db_path = _resolve_db(db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _repo(db_path) as repo:
        records = repo.get_metadata(_SUBMISSIONS_KEY) or []
        records.append(body)
        repo.set_metadata(_SUBMISSIONS_KEY, records)
    return {"submission": body, "total": len(records)}


@app.delete("/submissions", tags=["projects"])
def remove_submission(
    type: str = Query(...), year: int = Query(...), db: str | None = Query(default=None)
):
    """Remove all submission records matching {type, year}."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"removed": 0}
    with _repo(db_path) as repo:
        records = repo.get_metadata(_SUBMISSIONS_KEY) or []
        before = len(records)
        records = [r for r in records if not (r.get("type") == type and r.get("year") == year)]
        repo.set_metadata(_SUBMISSIONS_KEY, records)
    return {"removed": before - len(records), "total": len(records)}


@app.get("/submissions/file", tags=["projects"])
def get_submission_file(filename: str = Query(...), db: str | None = Query(default=None)):
    """Return the contents of a saved submitted-return XML by filename."""
    from fastapi.responses import Response as _Resp

    layout = _resolve_layout(db)
    file_path = layout.submitted_returns_dir / filename
    # Security: ensure the resolved path is inside submitted_returns_dir
    try:
        file_path.resolve().relative_to(layout.submitted_returns_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename.") from None
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return _Resp(content=file_path.read_bytes(), media_type="text/xml; charset=UTF-8")


# ---------------------------------------------------------------------------
# Geocode cache  (stored in project_metadata under the key "geocode_cache")
# Maps query strings → [lat, lon] or null; persisted so Nominatim is only
# called once per address across sessions.
# ---------------------------------------------------------------------------

_GEOCODE_CACHE_KEY = "geocode_cache"


@app.get("/geocode-cache", tags=["projects"])
def get_geocode_cache(db: str | None = Query(default=None)):
    """Return the full geocode cache for this project."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"cache": {}}
    with _repo(db_path) as repo:
        cache = repo.get_metadata(_GEOCODE_CACHE_KEY) or {}
    return {"cache": cache}


@app.post("/geocode-cache", tags=["projects"])
def upsert_geocode_entry(body: dict = Body(...), db: str | None = Query(default=None)):
    """Upsert a single geocode entry: {query, lat, lon} — lat/lon may be null."""
    query = body.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    lat = body.get("lat")
    lon = body.get("lon")
    coords = [lat, lon] if lat is not None and lon is not None else None
    db_path = _resolve_db(db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _repo(db_path) as repo:
        cache = repo.get_metadata(_GEOCODE_CACHE_KEY) or {}
        cache[query] = coords
        repo.set_metadata(_GEOCODE_CACHE_KEY, cache)
    return {"query": query, "coords": coords}


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


class ManualReceiptBody(BaseModel):
    """Payload for the manual receipt entry endpoint."""

    date: str | None = None  # ISO-8601 date string
    vendor: str | None = None
    vendor_verified: bool = False
    receipt_type: str = "purchase"  # "purchase" | "sale"
    category: str = "other"
    subcategory: str | None = None
    net_amount: float = 0.0
    vat_percentage: float = 0.0
    description: str | None = None
    currency: str = "EUR"


@app.post("/receipts", status_code=status.HTTP_201_CREATED, tags=["receipts"])
def create_manual_receipt(
    body: ManualReceiptBody,
    db: str | None = Query(default=None),
):
    """Create a receipt record from manually entered data (no file required)."""
    import uuid as _uuid
    from datetime import datetime as _dt
    from decimal import Decimal as _D

    from finamt.models import (  # type: ignore[import]
        Counterparty,
        ReceiptCategory,
        ReceiptData,
        ReceiptType,
    )

    # Build a unique raw_text so the SHA-256 id is always distinct
    unique_seed = _uuid.uuid4().hex
    raw_text = (
        f"MANUAL:{body.receipt_type}:{body.date or ''}:"
        f"{body.net_amount}:{body.vendor or ''}:{unique_seed}"
    )
    if body.description:
        raw_text += f":{body.description}"

    net = _D(str(body.net_amount))
    vat = _D(str(body.vat_percentage))
    total = (net * (1 + vat / _D("100"))).quantize(_D("0.01"))
    vat_amount = (total - net).quantize(_D("0.01"))

    counterparty = Counterparty(name=body.vendor) if body.vendor else None

    receipt_date = None
    if body.date:
        try:
            receipt_date = _dt.fromisoformat(body.date)
        except ValueError:
            pass

    try:
        rtype = ReceiptType(body.receipt_type)
    except ValueError:
        rtype = ReceiptType.purchase

    try:
        rcat = ReceiptCategory(body.category)
    except ValueError:
        rcat = ReceiptCategory.other

    receipt = ReceiptData(
        raw_text=raw_text,
        receipt_type=rtype,
        counterparty=counterparty,
        receipt_date=receipt_date,
        total_amount=total if total else None,
        vat_percentage=vat if vat else None,
        vat_amount=vat_amount if vat else None,
        category=rcat,
        currency=body.currency,
    )
    receipt.subcategory = body.subcategory or None
    receipt.description = body.description or ""

    db_path = _resolve_layout(db).db_path
    with _repo(db_path) as repo:
        repo.save(receipt)
        receipt = repo.get(receipt.id)  # re-fetch to normalise any DB defaults
        if body.vendor_verified and receipt and receipt.counterparty:
            repo.set_counterparty_verified(receipt.counterparty.id, True)
            receipt = repo.get(receipt.id)  # re-fetch to pick up verified flag

    return _receipt_to_response(receipt, db_path)


@app.post("/receipts/upload/stream", tags=["receipts"])
async def upload_receipt_stream(
    file: Annotated[UploadFile, File(description="Receipt PDF or image")],
    receipt_type: str = Query(default="purchase", enum=["purchase", "sale"]),
    db: str | None = Query(default=None, description="DB file path"),
    taxpayer_name: str | None = Query(default=None, description="Taxpayer's own name"),
    taxpayer_vat_id: str | None = Query(default=None, description="Taxpayer's own VAT ID"),
    taxpayer_tax_number: str | None = Query(default=None, description="Taxpayer's own tax number"),
    taxpayer_address: str | None = Query(
        default=None, description="Taxpayer's own composite address (legacy, unused)"
    ),
    taxpayer_street: str | None = Query(default=None, description="Taxpayer's own street & number"),
    taxpayer_address_supplement: str | None = Query(
        default=None, description="Taxpayer's own address supplement"
    ),
    taxpayer_postcode: str | None = Query(default=None, description="Taxpayer's own postcode"),
    taxpayer_city: str | None = Query(default=None, description="Taxpayer's own city"),
    taxpayer_state: str | None = Query(default=None, description="Taxpayer's own state/region"),
    taxpayer_country: str | None = Query(default=None, description="Taxpayer's own country"),
):
    """Upload a receipt and stream back Server-Sent Events with progress and result.

    Event types emitted:
    - ``progress`` — one line of text from the processing pipeline.
    - ``result``   — JSON payload identical to the non-streaming upload endpoint.
    - ``error``    — string error message.
    """
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{file.content_type}'.",
        )
    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not installed.")

    from finamt import progress as _progress

    layout = _resolve_layout(db)
    db_path = layout.db_path
    suffix = Path(file.filename or "receipt").suffix or ".pdf"

    file_bytes = await file.read()

    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    _taxpayer_info: dict | None = None
    if any(
        [
            taxpayer_name,
            taxpayer_vat_id,
            taxpayer_tax_number,
            taxpayer_address,
            taxpayer_street,
            taxpayer_address_supplement,
            taxpayer_postcode,
            taxpayer_city,
            taxpayer_state,
            taxpayer_country,
        ]
    ):
        _taxpayer_info = {
            "name": taxpayer_name or "",
            "vat_id": taxpayer_vat_id or "",
            "tax_number": taxpayer_tax_number or "",
            "address": taxpayer_address or "",
            "street": taxpayer_street or "",
            "address_supplement": taxpayer_address_supplement or "",
            "postcode": taxpayer_postcode or "",
            "city": taxpayer_city or "",
            "state": taxpayer_state or "",
            "country": taxpayer_country or "",
        }

    def _run() -> None:
        import tempfile as _tf

        with _tf.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)
        try:
            _progress.set_callback(lambda msg: loop.call_soon_threadsafe(queue.put_nowait, msg))
            agent = FinanceAgent(
                db_path=db_path,
                config=_effective_ocr_cfg(),
                agents_cfg=_effective_agents_cfg(),
            )
            result = agent.process_receipt(
                tmp_path, receipt_type=receipt_type, taxpayer_info=_taxpayer_info
            )
        except Exception as exc:
            _progress.clear_callback()
            tmp_path.unlink(missing_ok=True)
            loop.call_soon_threadsafe(queue.put_nowait, f"__error__:{exc}")
            loop.call_soon_threadsafe(queue.put_nowait, None)
            return
        else:
            _progress.clear_callback()
            tmp_path.unlink(missing_ok=True)

        if not result.success:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                f"__error__:Extraction failed: {result.error_message}",
            )
            loop.call_soon_threadsafe(queue.put_nowait, None)
            return

        response = _receipt_to_response(result.data, db_path)
        response["duplicate"] = result.duplicate
        if result.duplicate:
            response["message"] = "A receipt with identical content already exists."
        loop.call_soon_threadsafe(
            queue.put_nowait,
            f"__result__:{json.dumps(response)}",
        )
        loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, _run)

    async def _event_stream():
        while True:
            item = await queue.get()
            if item is None:
                break
            if item.startswith("__result__:"):
                payload = item[len("__result__:") :]
                yield f"event: result\ndata: {payload}\n\n"
                break
            if item.startswith("__error__:"):
                payload = item[len("__error__:") :]
                yield f"event: error\ndata: {json.dumps(payload)}\n\n"
                break
            yield f"event: progress\ndata: {json.dumps(item)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/receipts/upload", status_code=status.HTTP_201_CREATED, tags=["receipts"])
async def upload_receipt(
    file: Annotated[UploadFile, File(description="Receipt PDF or image")],
    receipt_type: str = Query(default="purchase", enum=["purchase", "sale"]),
    db: str | None = Query(default=None, description="DB file path"),
):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{file.content_type}'.",
        )
    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not installed.")

    layout = _resolve_layout(db)
    db_path = layout.db_path
    suffix = Path(file.filename or "receipt").suffix or ".pdf"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        # Pass db_path explicitly so FinanceAgent uses this exact layout.
        # layout_from_db_path in agent.py will re-derive the project folder
        # correctly from the path we resolved above.
        agent = FinanceAgent(
            db_path=db_path,
            config=_effective_ocr_cfg(),
            agents_cfg=_effective_agents_cfg(),
        )
        result = agent.process_receipt(tmp_path, receipt_type=receipt_type)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Extraction failed: {result.error_message}",
        )

    response = _receipt_to_response(result.data, db_path)
    response["duplicate"] = result.duplicate
    if result.duplicate:
        response["message"] = "A receipt with identical content already exists."
    return response


@app.get("/receipts", tags=["receipts"])
def list_receipts(
    receipt_type: str | None = Query(default=None, alias="type", enum=["purchase", "sale"]),
    category: str | None = Query(default=None),
    quarter: int | None = Query(default=None, ge=1, le=4),
    year: int | None = Query(default=None, ge=2000, le=2100),
    db: str | None = Query(default=None),
):
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"receipts": [], "total": 0}
    with _repo(db_path) as repo:
        if quarter and year:
            starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
            ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
            ms, ds = starts[quarter]
            me, de = ends[quarter]
            receipts = list(repo.find_by_period(date(year, ms, ds), date(year, me, de)))
        elif receipt_type:
            receipts = list(repo.find_by_type(receipt_type))
        elif category:
            receipts = list(repo.find_by_category(category))
        else:
            receipts = list(repo.list_all())

    if receipt_type:
        receipts = [r for r in receipts if str(r.receipt_type) == receipt_type]
    if category:
        receipts = [r for r in receipts if str(r.category) == category]

    return {
        "receipts": [_receipt_to_response(r, db_path) for r in receipts],
        "total": len(receipts),
    }


@app.get("/receipts/{receipt_id}", tags=["receipts"])
def get_receipt(receipt_id: str, db: str | None = Query(default=None)):
    db_path = _resolve_db(db)
    _require_db(db_path)
    with _repo(db_path) as repo:
        receipt = repo.get(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    return _receipt_to_response(receipt, db_path)


@app.get("/receipts/{receipt_id}/pdf", tags=["receipts"])
def get_receipt_pdf(receipt_id: str, db: str | None = Query(default=None)):
    db_path = _resolve_db(db)
    stored = _find_stored_file(receipt_id, db_path)
    if not stored:
        raise HTTPException(status_code=404, detail="File not found.")
    mime = _EXT_MIME.get(stored.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=stored,
        media_type=mime,
        headers={"Content-Disposition": "inline"},
    )


@app.patch("/receipts/{receipt_id}", tags=["receipts"])
def update_receipt(
    receipt_id: str,
    fields: dict,
    db: str | None = Query(default=None),
):
    db_path = _resolve_db(db)
    with _repo(db_path) as repo:
        updated = repo.update(receipt_id, fields)
        if not updated:
            raise HTTPException(status_code=404, detail="Receipt not found.")
        receipt = repo.get(receipt_id)
    return _receipt_to_response(receipt, db_path)


@app.delete("/receipts/{receipt_id}", status_code=204, tags=["receipts"])
def delete_receipt(receipt_id: str, db: str | None = Query(default=None)):
    db_path = _resolve_db(db)
    with _repo(db_path) as repo:
        if not repo.delete(receipt_id):
            raise HTTPException(status_code=404, detail="Receipt not found.")


@app.post("/receipts/{receipt_id}/counterparty", tags=["receipts"])
def reassign_receipt_counterparty(
    receipt_id: str,
    body: dict = Body(...),
    db: str | None = Query(default=None),
):
    """Find-or-create a counterparty by name/VAT-ID and link *only* this receipt to it.

    The old counterparty row is left untouched so other receipts sharing it are
    unaffected.  Accepts the same flat field names as PATCH /counterparties/{id}
    plus an optional nested ``address`` object.
    """
    db_path = _resolve_db(db)
    _require_db(db_path)
    flat: dict = {}
    for k, v in body.items():
        if k == "address" and isinstance(v, dict):
            flat.update(v)
        else:
            flat[k] = v
    with _repo(db_path) as repo:
        if not repo.relink_counterparty(receipt_id, flat):
            raise HTTPException(status_code=404, detail="Receipt not found.")
        receipt = repo.get(receipt_id)
    return _receipt_to_response(receipt, db_path)


# ---------------------------------------------------------------------------
# Tax
# ---------------------------------------------------------------------------


@app.get("/counterparties", tags=["counterparties"])
def list_all_counterparties(db: str | None = Query(default=None)):
    """Return every counterparty row (verified and unverified)."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"counterparties": []}
    with _repo(db_path) as repo:
        rows = repo.list_all_counterparties()
    return {"counterparties": rows}


@app.get("/counterparties/verified", tags=["counterparties"])
def list_verified_counterparties(db: str | None = Query(default=None)):
    """Return deduplicated verified counterparties (one per VAT-ID or name)."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"counterparties": []}
    with _repo(db_path) as repo:
        rows = repo.list_verified_counterparties()
    return {"counterparties": rows}


@app.get("/counterparties/{cp_id}/defaults", tags=["counterparties"])
def get_counterparty_defaults(cp_id: str, db: str | None = Query(default=None)):
    """Return the most-used category and subcategory for a given counterparty."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {}
    with _repo(db_path) as repo:
        return repo.get_category_defaults_for_counterparty(cp_id)


@app.delete("/counterparties/{cp_id}", status_code=204, tags=["counterparties"])
def delete_counterparty(cp_id: str, db: str | None = Query(default=None)):
    """Permanently delete a counterparty row."""
    db_path = _resolve_db(db)
    with _repo(db_path) as repo:
        if not repo.delete_counterparty(cp_id):
            raise HTTPException(status_code=404, detail="Counterparty not found.")


@app.patch("/counterparties/{cp_id}", tags=["counterparties"])
def update_counterparty(
    cp_id: str,
    body: dict = Body(...),
    db: str | None = Query(default=None),
):
    """Update name, tax_number, vat_id, verified, and address fields of a counterparty."""
    db_path = _resolve_db(db)
    # Flatten address sub-dict into top-level fields expected by the repo
    flat: dict = {}
    for k, v in body.items():
        if k == "address" and isinstance(v, dict):
            flat.update(v)
        else:
            flat[k] = v
    with _repo(db_path) as repo:
        if not repo.update_counterparty(cp_id, flat):
            raise HTTPException(status_code=404, detail="Counterparty not found.")
        # Re-fetch and return the saved row so the frontend doesn't rely on
        # stale local state (especially for cleared fields like vat_id).
        rows = repo.list_all_counterparties()
    updated = next((r for r in rows if r["id"] == cp_id), None)
    return updated if updated is not None else {"ok": True}


@app.patch("/counterparties/{cp_id}/verify", tags=["counterparties"])
def set_counterparty_verified(
    cp_id: str,
    body: dict = Body(...),
    db: str | None = Query(default=None),
):
    """Set verified=true/false on a counterparty."""
    db_path = _resolve_db(db)
    verified = bool(body.get("verified", True))
    with _repo(db_path) as repo:
        repo.set_counterparty_verified(cp_id, verified)
    return {"ok": True, "cp_id": cp_id, "verified": verified}


@app.get("/tax/ustva", tags=["tax"])
def get_ustva(
    quarter: int = Query(..., ge=1, le=4),
    year: int = Query(..., ge=2000, le=2100),
    db: str | None = Query(default=None),
):
    db_path = _resolve_db(db)
    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    ms, ds = starts[quarter]
    me, de = ends[quarter]
    start, end = date(year, ms, ds), date(year, me, de)

    if not db_path.exists():
        return generate_ustva([], start, end).to_dict()
    with _repo(db_path) as repo:
        receipts = list(repo.find_by_period(start, end))

    return generate_ustva(receipts, start, end).to_dict()


# ---------------------------------------------------------------------------
# UStVA — Voranmeldung submit / XML preview (quarterly and monthly)
# ---------------------------------------------------------------------------


class UStVASubmitRequest(BaseModel):
    year: int
    quarter: int | None = None  # 1–4 (mutually exclusive with month)
    month: int | None = None  # 1–12 (mutually exclusive with quarter)
    steuernummer: str = ""
    bundesland_kz: str = ""
    finanzamt_nr: str = ""
    hersteller_id: str = ""
    cert_path: str | None = None
    cert_data_b64: str | None = None
    cert_password: str | None = None
    use_test: bool = True
    validate_only: bool = False
    is_berichtigung: bool = False
    company_name: str = ""
    street: str = ""
    house_number: str = ""
    postal_code: str = ""
    city: str = ""


def _ustva_period_info(
    year: int, quarter: int | None, month: int | None
) -> tuple[int, date, date, str]:
    """Return (eric_period, start, end, submission_type_key)."""
    import calendar
    from datetime import date as _d

    if month:
        eric_period = month  # 1–12
        start = _d(year, month, 1)
        end = _d(year, month, calendar.monthrange(year, month)[1])
        sub_type = f"ustva_m{month:02d}"
    elif quarter:
        eric_period = 40 + quarter  # 41–44
        q_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        q_ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
        ms, ds = q_starts[quarter]
        me, de = q_ends[quarter]
        start = _d(year, ms, ds)
        end = _d(year, me, de)
        sub_type = f"ustva_q{quarter}"
    else:
        raise ValueError("Either quarter or month must be specified")
    return eric_period, start, end, sub_type


@app.post("/tax/ustva/submit", tags=["tax"])
def post_ustva_submit(
    body: UStVASubmitRequest,
    db: str | None = Query(default=None),
):
    """
    Build, sign, and transmit a UStVA (quarterly or monthly VAT pre-return)
    via the ERiC library.  Set use_test=false for legally binding filings.
    """
    import base64 as _b64
    import datetime as _dt
    import os as _os

    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not available")

    if not body.quarter and not body.month:
        raise HTTPException(
            status_code=400, detail="Provide either 'quarter' (1-4) or 'month' (1-12)."
        )

    from finamt.tax.elster import ElsterConfig, ElsterEricClient

    year = body.year
    layout = _resolve_layout(db)
    db_path = layout.db_path

    try:
        eric_period, start, end, sub_type = _ustva_period_info(year, body.quarter, body.month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    receipts = []
    if db_path.exists():
        with _repo(db_path) as repo:
            receipts = list(repo.find_by_period(start, end))
    report = generate_ustva(receipts, start, end)

    # ── Resolve cert ──────────────────────────────────────────────────
    stored_cert = layout.root / "elster_cert.pfx"
    cert_path = body.cert_path or _os.path.expanduser(
        _os.environ.get("FINAMT_ELSTER_CERT_PATH") or ""
    )
    cert_password = body.cert_password or _os.environ.get("FINAMT_ELSTER_CERT_PASSWORD", "")

    if body.cert_data_b64:
        raw_cert = _b64.b64decode(body.cert_data_b64)
        layout.create_dirs()
        stored_cert.write_bytes(raw_cert)
        cert_path = str(stored_cert)

    if not cert_path and stored_cert.exists():
        cert_path = str(stored_cert)

    if not cert_path:
        raise HTTPException(
            status_code=400,
            detail="ELSTER certificate not configured. Upload a .pfx file or set FINAMT_ELSTER_CERT_PATH.",
        )

    # ── Resolve ELSTER params ─────────────────────────────────────────
    steuernummer = body.steuernummer or _os.environ.get("FINAMT_ELSTER_STEUERNUMMER", "")
    finanzamt_nr = body.finanzamt_nr or _os.environ.get("FINAMT_ELSTER_FINANZAMT_NR", "")
    bundesland_kz = body.bundesland_kz or _os.environ.get("FINAMT_ELSTER_BUNDESLAND_KZ", "")
    hersteller_id = body.hersteller_id or _os.environ.get("FINAMT_ELSTER_HERSTELLER_ID", "")

    if not hersteller_id and db_path.exists():
        with _repo(db_path) as _r:
            _misc = _r.get_metadata("elster_misc") or {}
        hersteller_id = _misc.get("hersteller_id") or ""

    if not hersteller_id:
        raise HTTPException(
            status_code=400,
            detail="ELSTER Hersteller-ID not configured. Set FINAMT_ELSTER_HERSTELLER_ID or pass hersteller_id in the request.",
        )

    if not bundesland_kz and db_path.exists():
        from finamt.tax.elster import bundesland_kz_from_city as _bkz

        with _repo(db_path) as _r:
            _tp = _r.get_metadata("taxpayer") or {}
        for _field in ("state", "city"):
            _kz = _bkz(_tp.get(_field) or "")
            if _kz:
                bundesland_kz = _kz
                break

    company_name = body.company_name
    street = body.street
    house_number = body.house_number
    postal_code = body.postal_code
    city = body.city
    if db_path.exists() and not all([company_name, street, postal_code, city]):
        with _repo(db_path) as _r:
            _tp2 = _r.get_metadata("taxpayer") or {}
        company_name = company_name or _tp2.get("name") or ""
        street = street or _tp2.get("street") or ""
        house_number = house_number or ""
        postal_code = postal_code or _tp2.get("postcode") or ""
        city = city or _tp2.get("city") or ""
        if not steuernummer:
            steuernummer = _tp2.get("tax_number") or ""

    elster_cfg = ElsterConfig(
        cert_path=cert_path,
        cert_password=cert_password,
        steuernummer=steuernummer,
        finanzamt_nr=finanzamt_nr,
        bundesland_kz=bundesland_kz,
        hersteller_id=hersteller_id,
        company_name=company_name,
        street=street,
        house_number=house_number,
        postal_code=postal_code,
        city=city,
    )

    eric_home = _os.environ.get("FINAMT_ERIC_HOME", "")
    if not eric_home and db_path.exists():
        with _repo(db_path) as _r:
            _em = _r.get_metadata("elster_eric_home") or {}
        eric_home = _em.get("path") or ""
    if not eric_home:
        raise HTTPException(
            status_code=400,
            detail="ERiC library path not configured. Set FINAMT_ERIC_HOME environment variable.",
        )

    eric_log_dir = str(layout.root / "eric_logs")
    client = ElsterEricClient(
        elster_cfg, eric_home=eric_home, use_test=body.use_test, log_dir=eric_log_dir
    )

    try:
        if body.validate_only:
            result = client.validate_ust(
                report, year=year, period=eric_period, is_berichtigung=body.is_berichtigung
            )
            return {
                "success": result.success,
                "validate_only": True,
                "message": result.error_message or "ERiC validation passed — not submitted.",
                "error_code": result.error_code,
            }
        result = client.submit_ust(
            report, year=year, period=eric_period, is_berichtigung=body.is_berichtigung
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    xml_filename: str | None = None

    if result.success:
        try:
            from finamt.tax.elster import ElsterXMLBuilder as _Builder

            _xml_bytes = _Builder(elster_cfg).build_ustva(
                report,
                year,
                eric_period,
                is_berichtigung=body.is_berichtigung,
                use_test=body.use_test,
            )
            layout.submitted_returns_dir.mkdir(parents=True, exist_ok=True)
            _ts = _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            _mode = "test" if body.use_test else "prod"
            _period_label = f"Q{body.quarter}" if body.quarter else f"M{body.month:02d}"
            xml_filename = f"UStVA_{year}_{_period_label}_{_ts}_{_mode}.xml"
            (layout.submitted_returns_dir / xml_filename).write_bytes(_xml_bytes)
        except Exception:
            xml_filename = None

        if db_path.exists():
            with _repo(db_path) as _r:
                _records = _r.get_metadata("submissions") or []
                _records.append(
                    {
                        "type": sub_type,
                        "year": year,
                        "submitted_at": _dt.datetime.utcnow().isoformat(),
                        "telenummer": result.telenummer,
                        "use_test": body.use_test,
                        "xml_filename": xml_filename,
                    }
                )
                _r.set_metadata("submissions", _records)

    return {
        "success": result.success,
        "telenummer": result.telenummer,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "use_test": body.use_test,
        "xml_filename": xml_filename,
    }


@app.post("/tax/ustva/xml", tags=["tax"])
def post_ustva_xml(
    body: UStVASubmitRequest,
    db: str | None = Query(default=None),
):
    """Build and return the UStVA XML (no submission)."""
    import os as _os

    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not available")
    if not body.quarter and not body.month:
        raise HTTPException(status_code=400, detail="Provide either 'quarter' or 'month'.")

    from fastapi.responses import Response

    from finamt.tax.elster import ElsterConfig, ElsterXMLBuilder

    year = body.year
    layout = _resolve_layout(db)
    db_path = layout.db_path

    try:
        eric_period, start, end, _ = _ustva_period_info(year, body.quarter, body.month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    receipts = []
    if db_path.exists():
        with _repo(db_path) as r:
            receipts = list(r.find_by_period(start, end))
    report = generate_ustva(receipts, start, end)

    cert_path = body.cert_path or _os.path.expanduser(
        _os.environ.get("FINAMT_ELSTER_CERT_PATH") or ""
    )
    cert_password = body.cert_password or _os.environ.get("FINAMT_ELSTER_CERT_PASSWORD", "")
    steuernummer = body.steuernummer or _os.environ.get("FINAMT_ELSTER_STEUERNUMMER", "")
    finanzamt_nr = body.finanzamt_nr or _os.environ.get("FINAMT_ELSTER_FINANZAMT_NR", "")
    bundesland_kz = body.bundesland_kz or _os.environ.get("FINAMT_ELSTER_BUNDESLAND_KZ", "")
    hersteller_id = body.hersteller_id or _os.environ.get("FINAMT_ELSTER_HERSTELLER_ID", "")

    if not bundesland_kz and db_path.exists():
        from finamt.tax.elster import bundesland_kz_from_city as _bkz

        with _repo(db_path) as _r:
            _tp = _r.get_metadata("taxpayer") or {}
        for _f in ("state", "city"):
            _kz = _bkz(_tp.get(_f) or "")
            if _kz:
                bundesland_kz = _kz
                break

    company_name, street, house_number, postal_code, city = (
        body.company_name,
        body.street,
        body.house_number,
        body.postal_code,
        body.city,
    )
    if db_path.exists() and not all([company_name, street, postal_code, city]):
        with _repo(db_path) as _r:
            _tp2 = _r.get_metadata("taxpayer") or {}
        company_name = company_name or _tp2.get("name") or ""
        street = street or _tp2.get("street") or ""
        postal_code = postal_code or _tp2.get("postcode") or ""
        city = city or _tp2.get("city") or ""
        if not steuernummer:
            steuernummer = _tp2.get("tax_number") or ""

    elster_cfg = ElsterConfig(
        cert_path=cert_path or "",
        cert_password=cert_password,
        steuernummer=steuernummer,
        finanzamt_nr=finanzamt_nr,
        bundesland_kz=bundesland_kz,
        hersteller_id=hersteller_id or "00000",
        company_name=company_name,
        street=street,
        house_number=house_number,
        postal_code=postal_code,
        city=city,
    )
    try:
        xml_bytes = ElsterXMLBuilder(elster_cfg).build_ustva(
            report, year, eric_period, is_berichtigung=body.is_berichtigung, use_test=body.use_test
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(content=xml_bytes, media_type="text/xml; charset=UTF-8")


# ---------------------------------------------------------------------------
# UStE — Umsatzsteuerjahreserklärung (annual VAT return, period=0 / Zeitraum 00)
# ---------------------------------------------------------------------------


class UStESubmitRequest(BaseModel):
    year: int
    steuernummer: str = ""
    bundesland_kz: str = ""
    finanzamt_nr: str = ""
    hersteller_id: str = ""
    cert_path: str | None = None
    cert_data_b64: str | None = None  # base64-encoded .pfx
    cert_password: str | None = None
    use_test: bool = True
    validate_only: bool = False
    # Annual USt 2A address / tax fields
    company_name: str = ""
    street: str = ""
    house_number: str = ""
    postal_code: str = ""
    city: str = ""
    besteuerungsart: str = "1"  # 1=vereinbarte, 2=vereinnahmte, 3=mixed
    vorauszahlungssoll: float = 0.0


@app.post("/tax/uste/submit", tags=["tax"])
def post_uste_submit(
    body: UStESubmitRequest,
    db: str | None = Query(default=None),
):
    """
    Build the Umsatzsteuerjahreserklärung (USt 2A) XML with
    Zeitraum=00 (period 0 = annual), sign it, and transmit via
    the ELSTER HTTP upload endpoint.

    Set use_test=false ONLY for production filings — legally binding!
    Set validate_only=true to build + sign without network submission.
    """
    import base64 as _b64
    import os as _os

    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not available")

    from datetime import date as _date

    from finamt.tax.elster import ElsterConfig, ElsterEricClient

    year = body.year
    layout = _resolve_layout(db)
    db_path = layout.db_path
    start = _date(year, 1, 1)
    end = _date(year, 12, 31)

    # ── Receipts ──────────────────────────────────────────────────────
    receipts = []
    if db_path.exists():
        with _repo(db_path) as repo:
            receipts = list(repo.find_by_period(start, end))
    report = generate_ustva(receipts, start, end)

    # ── Resolve cert ──────────────────────────────────────────────────
    stored_cert = layout.root / "elster_cert.pfx"
    cert_path = body.cert_path or _os.path.expanduser(
        _os.environ.get("FINAMT_ELSTER_CERT_PATH") or ""
    )
    cert_password = body.cert_password or _os.environ.get("FINAMT_ELSTER_CERT_PASSWORD", "")

    if body.cert_data_b64:
        raw_cert = _b64.b64decode(body.cert_data_b64)
        layout.create_dirs()
        stored_cert.write_bytes(raw_cert)
        cert_path = str(stored_cert)

    if not cert_path and stored_cert.exists():
        cert_path = str(stored_cert)

    if not cert_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "ELSTER certificate not configured. "
                "Upload a .pfx file or set FINAMT_ELSTER_CERT_PATH."
            ),
        )

    # ── Resolve ELSTER params ─────────────────────────────────────────
    steuernummer = body.steuernummer or _os.environ.get("FINAMT_ELSTER_STEUERNUMMER", "")
    finanzamt_nr = body.finanzamt_nr or _os.environ.get("FINAMT_ELSTER_FINANZAMT_NR", "")
    bundesland_kz = body.bundesland_kz or _os.environ.get("FINAMT_ELSTER_BUNDESLAND_KZ", "")
    hersteller_id = body.hersteller_id or _os.environ.get("FINAMT_ELSTER_HERSTELLER_ID", "")

    if not hersteller_id and db_path.exists():
        with _repo(db_path) as _r:
            _misc = _r.get_metadata("elster_misc") or {}
        hersteller_id = _misc.get("hersteller_id") or ""

    if not hersteller_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "ELSTER Hersteller-ID not configured. "
                "Set FINAMT_ELSTER_HERSTELLER_ID or pass hersteller_id in the request."
            ),
        )

    # Derive bundesland_kz from taxpayer profile when not supplied
    if not bundesland_kz and db_path.exists():
        from finamt.tax.elster import bundesland_kz_from_city as _bkz

        with _repo(db_path) as _r:
            _tp = _r.get_metadata("taxpayer") or {}
        for _field in ("state", "city"):
            _kz = _bkz(_tp.get(_field) or "")
            if _kz:
                bundesland_kz = _kz
                break

    # Load address + tax details from taxpayer profile if not in request
    company_name = body.company_name
    street = body.street
    house_number = body.house_number
    postal_code = body.postal_code
    city = body.city
    if db_path.exists() and not all([company_name, street, postal_code, city]):
        with _repo(db_path) as _r:
            _tp2 = _r.get_metadata("taxpayer") or {}
        company_name = company_name or _tp2.get("name") or ""
        street = street or _tp2.get("street") or ""
        house_number = house_number or ""
        postal_code = postal_code or _tp2.get("postcode") or ""
        city = city or _tp2.get("city") or ""
        if not steuernummer:
            steuernummer = _tp2.get("tax_number") or ""

    from decimal import Decimal as _Decimal

    elster_cfg = ElsterConfig(
        cert_path=cert_path,
        cert_password=cert_password,
        steuernummer=steuernummer,
        finanzamt_nr=finanzamt_nr,
        bundesland_kz=bundesland_kz,
        hersteller_id=hersteller_id,
        company_name=company_name,
        street=street,
        house_number=house_number,
        postal_code=postal_code,
        city=city,
        besteuerungsart=body.besteuerungsart,
        vorauszahlungssoll=_Decimal(str(body.vorauszahlungssoll)),
    )

    # ── ERiC home ─────────────────────────────────────────────────────
    eric_home = _os.environ.get("FINAMT_ERIC_HOME", "")
    if not eric_home and db_path.exists():
        with _repo(db_path) as _r:
            _em = _r.get_metadata("elster_eric_home") or {}
        eric_home = _em.get("path") or ""
    if not eric_home:
        raise HTTPException(
            status_code=400,
            detail="ERiC library path not configured. Set FINAMT_ERIC_HOME environment variable.",
        )

    eric_log_dir = str(layout.root / "eric_logs")
    client = ElsterEricClient(
        elster_cfg, eric_home=eric_home, use_test=body.use_test, log_dir=eric_log_dir
    )

    try:
        if body.validate_only:
            result = client.validate_ust(report, year=year, period=0)
            return {
                "success": result.success,
                "validate_only": True,
                "message": result.error_message or "ERiC validation passed — not submitted.",
                "error_code": result.error_code,
            }
        result = client.submit_ust(report, year=year, period=0)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    import datetime as _dt

    xml_filename: str | None = None

    # On success: save a copy of the submitted XML and record the submission
    if result.success:
        # Build the XML for archiving (same builder as used internally by submit_ust)
        try:
            from finamt.tax.elster import ElsterXMLBuilder as _Builder

            _xml_bytes = _Builder(elster_cfg).build_ustva(
                report, year=year, period=0, use_test=body.use_test
            )
            layout.submitted_returns_dir.mkdir(parents=True, exist_ok=True)
            _ts = _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            _mode = "test" if body.use_test else "prod"
            xml_filename = f"USt_{year}_{_ts}_{_mode}.xml"
            (layout.submitted_returns_dir / xml_filename).write_bytes(_xml_bytes)
        except Exception:
            xml_filename = None  # non-fatal — submission already succeeded

        if db_path.exists():
            with _repo(db_path) as _r:
                _records = _r.get_metadata("submissions") or []
                _records.append(
                    {
                        "type": "uste",
                        "year": year,
                        "submitted_at": _dt.datetime.utcnow().isoformat(),
                        "telenummer": result.telenummer,
                        "use_test": body.use_test,
                        "xml_filename": xml_filename,
                    }
                )
                _r.set_metadata("submissions", _records)

    return {
        "success": result.success,
        "telenummer": result.telenummer,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "use_test": body.use_test,
        "xml_filename": xml_filename,
    }


# ---------------------------------------------------------------------------
# UStE XML preview
# ---------------------------------------------------------------------------


@app.post("/tax/uste/xml", tags=["tax"])
def post_uste_xml(
    body: UStESubmitRequest,
    db: str | None = Query(default=None),
):
    """
    Build and sign the Umsatzsteuerjahreserklärung XML (period=0, annual)
    and return it as text/xml — no network submission.
    """
    import base64 as _b64
    import os as _os
    from datetime import date as _date

    from fastapi.responses import Response

    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not available")

    from finamt.tax.elster import ElsterConfig, ElsterXMLBuilder

    year = body.year
    layout = _resolve_layout(db)
    db_path = layout.db_path
    start = _date(year, 1, 1)
    end = _date(year, 12, 31)

    receipts = []
    if db_path.exists():
        with _repo(db_path) as r:
            receipts = list(r.find_by_period(start, end))

    from finamt.tax.ustva import generate_ustva

    report = generate_ustva(receipts, start, end)

    # ── Resolve cert ──────────────────────────────────────────────────
    cert_path: str | None = body.cert_path
    if body.cert_data_b64:
        import base64 as _b64
        import tempfile as _tmp

        cert_bytes = _b64.b64decode(body.cert_data_b64)
        tf = _tmp.NamedTemporaryFile(suffix=".pfx", delete=False)
        tf.write(cert_bytes)
        tf.close()
        cert_path = tf.name
    if not cert_path:
        cert_path = _os.path.expanduser(_os.environ.get("FINAMT_ELSTER_CERT_PATH", ""))

    cert_password = body.cert_password or _os.environ.get("FINAMT_ELSTER_CERT_PASSWORD", "")
    steuernummer = body.steuernummer or _os.environ.get("FINAMT_ELSTER_STEUERNUMMER", "")
    finanzamt_nr = body.finanzamt_nr or _os.environ.get("FINAMT_ELSTER_FINANZAMT_NR", "")
    bundesland_kz = body.bundesland_kz or _os.environ.get("FINAMT_ELSTER_BUNDESLAND_KZ", "")
    hersteller_id = body.hersteller_id or _os.environ.get("FINAMT_ELSTER_HERSTELLER_ID", "")

    if not hersteller_id:
        raise HTTPException(status_code=400, detail="ELSTER Hersteller-ID not configured")

    # Derive bundesland_kz from taxpayer profile when not supplied
    if not bundesland_kz and db_path.exists():
        from finamt.tax.elster import bundesland_kz_from_city as _bkz2

        with _repo(db_path) as _r:
            _tp_bkz = _r.get_metadata("taxpayer") or {}
        for _f in ("state", "city"):
            _kz = _bkz2(_tp_bkz.get(_f) or "")
            if _kz:
                bundesland_kz = _kz
                break

    # Load address + tax details from taxpayer profile if not in request
    company_name = body.company_name
    street = body.street
    house_number = body.house_number
    postal_code = body.postal_code
    city = body.city
    if db_path.exists() and not all([company_name, street, postal_code, city]):
        with _repo(db_path) as _r:
            _tp_xml = _r.get_metadata("taxpayer") or {}
        company_name = company_name or _tp_xml.get("name") or ""
        street = street or _tp_xml.get("street") or ""
        house_number = house_number or ""
        postal_code = postal_code or _tp_xml.get("postcode") or ""
        city = city or _tp_xml.get("city") or ""
        if not steuernummer:
            steuernummer = _tp_xml.get("tax_number") or ""

    from decimal import Decimal as _Decimal

    elster_cfg = ElsterConfig(
        cert_path=cert_path,
        cert_password=cert_password,
        steuernummer=steuernummer,
        finanzamt_nr=finanzamt_nr,
        bundesland_kz=bundesland_kz,
        hersteller_id=hersteller_id,
        company_name=company_name,
        street=street,
        house_number=house_number,
        postal_code=postal_code,
        city=city,
        besteuerungsart=body.besteuerungsart,
        vorauszahlungssoll=_Decimal(str(body.vorauszahlungssoll)),
    )
    try:
        xml_bytes = ElsterXMLBuilder(elster_cfg).build_ustva(
            report, year=year, period=0, use_test=body.use_test
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(content=xml_bytes, media_type="text/xml; charset=UTF-8")


# ---------------------------------------------------------------------------
# E-Bilanz XBRL
# ---------------------------------------------------------------------------


class EBilanzRequest(BaseModel):
    year: int
    steuernummer: str
    elster_id: str = ""  # 13-digit ELSTER number for XBRL context identifier
    company_name: str
    legal_form: str = "GmbH"
    fiscal_year_start: str = ""
    fiscal_year_end: str = ""
    stammkapital: float = 25000.0
    eingezahltes_kapital: float = 12500.0
    vortrag: float = 0.0
    nettomethode: bool = True
    preparer: str = ""


@app.post("/tax/ebilanz/xbrl", tags=["tax"])
def post_ebilanz_xbrl(
    body: EBilanzRequest,
    db: str | None = Query(default=None),
):
    """
    Generate an E-Bilanz XBRL instance document (§ 5b EStG).
    Uses HGB taxonomy v6 (MicroBilG, § 267a HGB).

    Returns the .xbrl file as an attachment ready for ERiC transmission.
    """
    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not available")

    from datetime import date as _date
    from decimal import Decimal

    year = body.year
    db_path = _resolve_db(db)
    start = _date(year, 1, 1)
    end = _date(year, 12, 31)

    receipts = []
    if db_path.exists():
        with _repo(db_path) as repo:
            # Fetch all receipts since founding (needed for Gewinnvortrag calc)
            receipts = list(repo.find_by_period(_date(2000, 1, 1), end))

    cfg = EBilanzConfig(
        steuernummer=body.steuernummer,
        elster_id=body.elster_id,
        company_name=body.company_name,
        legal_form=body.legal_form,
        fiscal_year_start=body.fiscal_year_start or str(start),
        fiscal_year_end=body.fiscal_year_end or str(end),
        preparer=body.preparer,
    )

    jab = generate_jahresabschluss(
        receipts=[r for r in receipts if r.receipt_date and r.receipt_date.year == year],
        year=year,
        stammkapital=Decimal(str(body.stammkapital)),
        eingezahltes_kapital=Decimal(str(body.eingezahltes_kapital)),
        vortrag_gewinnverlust=Decimal(str(body.vortrag)),
        nettomethode=body.nettomethode,
    )

    try:
        xml_bytes = build_xbrl(jab, cfg)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    filename = f"ebilanz_{year}_{body.steuernummer.replace('/', '-')}.xbrl"
    return StreamingResponse(
        iter([xml_bytes]),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class EBilanzEnvelopeRequest(EBilanzRequest):
    """Minimal request for building the ELSTER envelope (no ERiC / cert needed)."""

    bundesland_kz: str = ""
    hersteller_id: str = ""
    finanzamt_nr: str = ""
    use_test: bool = True


@app.post("/tax/ebilanz/envelope", tags=["tax"])
def post_ebilanz_envelope(
    body: EBilanzEnvelopeRequest,
    db: str | None = Query(default=None),
):
    """
    Build the E-Bilanz XBRL and wrap it in the ELSTER transmission envelope —
    the exact XML that ERiC would send to Finanzamt.  No ERiC / certificate
    required; suitable for previewing the full payload before a real filing.

    If ``hersteller_id`` is absent the placeholder ``"00000"`` is used so the
    preview still works without a registered publisher ID.
    """
    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not available")

    import os as _os
    from datetime import date as _date
    from decimal import Decimal

    from finamt.tax.elster import EBilanzEnvelopeBuilder, ElsterConfig

    year = body.year
    layout = _resolve_layout(db)
    db_path = layout.db_path
    start = _date(year, 1, 1)
    end = _date(year, 12, 31)

    receipts = []
    if db_path.exists():
        with _repo(db_path) as repo:
            receipts = list(repo.find_by_period(_date(2000, 1, 1), end))

    cfg = EBilanzConfig(
        steuernummer=body.steuernummer,
        elster_id=body.elster_id,
        company_name=body.company_name,
        legal_form=body.legal_form,
        fiscal_year_start=body.fiscal_year_start or str(start),
        fiscal_year_end=body.fiscal_year_end or str(end),
        preparer=body.preparer,
    )

    jab = generate_jahresabschluss(
        receipts=[r for r in receipts if r.receipt_date and r.receipt_date.year == year],
        year=year,
        stammkapital=Decimal(str(body.stammkapital)),
        eingezahltes_kapital=Decimal(str(body.eingezahltes_kapital)),
        vortrag_gewinnverlust=Decimal(str(body.vortrag)),
        nettomethode=body.nettomethode,
    )

    try:
        xbrl_bytes = build_xbrl(jab, cfg)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # ── Resolve bundesland_kz ──────────────────────────────────────────
    bundesland_kz = body.bundesland_kz or _os.environ.get("FINAMT_ELSTER_BUNDESLAND_KZ", "")
    if not bundesland_kz and db_path.exists():
        from finamt.tax.elster import bundesland_kz_from_city as _bkz

        with _repo(db_path) as _r:
            _tp = _r.get_metadata("taxpayer") or {}
        for _field in ("state", "city"):
            _kz = _bkz(_tp.get(_field) or "")
            if _kz:
                bundesland_kz = _kz
                break
    # Last resort: derive from steuernummer prefix
    if not bundesland_kz and len(body.steuernummer) >= 2:
        _prefix_map = {
            "11": "BE",
            "12": "BB",
            "28": "HB",
            "20": "HH",
            "06": "HE",
            "13": "MV",
            "23": "NI",
            "10": "SL",
            "09": "BY",
            "08": "BW",
            "05": "NW",
            "07": "RP",
            "03": "NI",
            "04": "HH",
            "01": "SH",
            "14": "SN",
            "15": "ST",
            "16": "TH",
        }
        bundesland_kz = _prefix_map.get(body.steuernummer[:2], "")

    # ── Resolve hersteller_id ──────────────────────────────────────────
    hersteller_id = body.hersteller_id or _os.environ.get("FINAMT_ELSTER_HERSTELLER_ID", "")
    if not hersteller_id and db_path.exists():
        with _repo(db_path) as _r:
            _misc = _r.get_metadata("elster_misc") or {}
        hersteller_id = _misc.get("hersteller_id") or ""
    if not hersteller_id:
        hersteller_id = "00000"  # preview placeholder — no ERiC call made

    # ── Resolve finanzamt_nr ───────────────────────────────────────────
    finanzamt_nr = body.finanzamt_nr or _os.environ.get("FINAMT_ELSTER_FINANZAMT_NR", "")

    elster_cfg = ElsterConfig(
        cert_path="",
        cert_password="",
        steuernummer=body.steuernummer,
        finanzamt_nr=finanzamt_nr,
        bundesland_kz=bundesland_kz,
        hersteller_id=hersteller_id,
    )

    try:
        env_bytes = EBilanzEnvelopeBuilder(elster_cfg).build(
            xbrl_bytes, year=year, use_test=body.use_test
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = f"elster_envelope_{year}_{body.steuernummer.replace('/', '-')}.xml"
    return StreamingResponse(
        iter([env_bytes]),
        media_type="application/xml",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/tax/ebilanz/settings", tags=["tax"])
def get_ebilanz_settings(db: str | None = Query(default=None)):
    """Return all persisted ELSTER settings for this project."""
    import os as _os

    layout = _resolve_layout(db)
    if not layout.db_path.exists():
        eric_home_env = _os.environ.get("FINAMT_ERIC_HOME") or None
        hersteller_id_env = _os.environ.get("FINAMT_ELSTER_HERSTELLER_ID") or None
        return {
            "eric_home": eric_home_env,
            "elster_id": None,
            "cert_pin": None,
            "hersteller_id": hersteller_id_env,
        }
    with _repo(layout.db_path) as repo:
        eric = repo.get_metadata("elster_eric_home") or {}
        misc = repo.get_metadata("elster_misc") or {}
    # Fall back to environment variables when the project DB has no stored value
    hersteller_id = (
        misc.get("hersteller_id") or _os.environ.get("FINAMT_ELSTER_HERSTELLER_ID") or None
    )
    eric_home = eric.get("path") or _os.environ.get("FINAMT_ERIC_HOME") or None
    return {
        "eric_home": eric_home,
        "elster_id": misc.get("elster_id") or None,
        "cert_pin": misc.get("cert_pin") or None,
        "hersteller_id": hersteller_id,
    }


@app.post("/tax/ebilanz/settings", status_code=200, tags=["tax"])
def post_ebilanz_settings(body: dict = Body(...), db: str | None = Query(default=None)):
    """Persist ELSTER misc settings (elster_id, cert_pin) in the project DB."""
    layout = _resolve_layout(db)
    layout.create_dirs()
    with _repo(layout.db_path) as repo:
        existing = repo.get_metadata("elster_misc") or {}
        if "elster_id" in body:
            existing["elster_id"] = body["elster_id"]
        if "cert_pin" in body:
            existing["cert_pin"] = body["cert_pin"]
        if "hersteller_id" in body:
            existing["hersteller_id"] = body["hersteller_id"]
        repo.set_metadata("elster_misc", existing)
    return {"ok": True}


@app.get("/tax/ebilanz/eric-home", tags=["tax"])
def get_ebilanz_eric_home(db: str | None = Query(default=None)):
    """Return the ERiC lib/ path stored for this project (if any)."""
    layout = _resolve_layout(db)
    if not layout.db_path.exists():
        return {"stored": False, "path": None}
    with _repo(layout.db_path) as repo:
        meta = repo.get_metadata("elster_eric_home")
    path = (meta or {}).get("path", "") or ""
    return {"stored": bool(path), "path": path or None}


@app.post("/tax/ebilanz/eric-home", status_code=200, tags=["tax"])
def post_ebilanz_eric_home(body: dict = Body(...), db: str | None = Query(default=None)):
    """Persist the ERiC lib/ path in the project database."""
    path = (body or {}).get("eric_home", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="eric_home is required")
    layout = _resolve_layout(db)
    layout.create_dirs()
    with _repo(layout.db_path) as repo:
        repo.set_metadata("elster_eric_home", {"path": path})
    return {"stored": True, "path": path}


@app.get("/tax/ebilanz/cert", tags=["tax"])
def get_ebilanz_cert(db: str | None = Query(default=None)):
    """Check whether a stored ELSTER certificate (.pfx) exists for this project."""
    layout = _resolve_layout(db)
    cert = layout.root / "elster_cert.pfx"
    return {"stored": cert.exists(), "path": str(cert) if cert.exists() else None}


@app.post("/tax/ebilanz/cert", status_code=200, tags=["tax"])
def post_ebilanz_cert(body: dict = Body(...), db: str | None = Query(default=None)):
    """
    Persist an ELSTER certificate (.pfx) in the project folder
    (~/.finamt/{project}/elster_cert.pfx).  Accepts base64-encoded bytes
    so the browser does not have to perform a multipart upload.
    """
    import base64 as _b64

    cert_b64 = (body or {}).get("cert_data_b64", "")
    if not cert_b64:
        raise HTTPException(status_code=400, detail="cert_data_b64 is required")
    layout = _resolve_layout(db)
    layout.create_dirs()
    raw = _b64.b64decode(cert_b64)
    dest = layout.root / "elster_cert.pfx"
    dest.write_bytes(raw)
    return {"stored": True, "path": str(dest)}


class EBilanzSubmitRequest(EBilanzRequest):
    """
    Extended E-Bilanz request body that also carries the ERIC / certificate
    parameters needed for transmission.
    """

    # ERiC library home dir — defaults to FINAMT_ERIC_HOME env var
    eric_home: str | None = None
    # Certificate — either a server-side path OR base64-encoded bytes from the browser
    cert_path: str | None = None
    cert_data_b64: str | None = None  # base64 .pfx uploaded by the browser
    cert_password: str | None = None
    # Steuernummer for ElsterConfig (already in EBilanzRequest as steuernummer)
    finanzamt_nr: str = ""
    bundesland_kz: str = ""
    hersteller_id: str = ""
    # Submission mode
    use_test: bool = True
    validate_only: bool = False


@app.post("/tax/ebilanz/submit", tags=["tax"])
def post_ebilanz_submit(
    body: EBilanzSubmitRequest,
    db: str | None = Query(default=None),
):
    """
    Build the E-Bilanz XBRL, wrap it in the ELSTER envelope, and transmit
    it to ELSTER via the ERiC shared library.

    Required environment variables (or body fields):
    - ``FINAMT_ERIC_HOME``            — path to ERiC lib/ directory
    - ``FINAMT_ELSTER_CERT_PATH``     — path to PKCS#12 certificate (.pfx)
    - ``FINAMT_ELSTER_CERT_PASSWORD`` — certificate PIN
    - ``FINAMT_ELSTER_FINANZAMT_NR``  — 4-digit Finanzamtsnummer
    - ``FINAMT_ELSTER_BUNDESLAND_KZ`` — 2-digit Länderkennzeichen

    Set ``validate_only=true`` to check the XML with ERiC without sending.
    Set ``use_test=false`` only for production filings (legally binding!).
    """
    import os as _os

    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finamt library not available")

    from datetime import date as _date
    from decimal import Decimal

    from finamt.tax.elster import ElsterConfig, ElsterEricClient

    year = body.year
    layout = _resolve_layout(db)
    db_path = layout.db_path
    start = _date(year, 1, 1)
    end = _date(year, 12, 31)
    eric_log_dir = str(layout.root / "eric_logs")

    # ── Resolve ERiC home ──────────────────────────────────────────────
    def _load_stored_eric() -> str | None:
        if not layout.db_path.exists():
            return None
        with _repo(layout.db_path) as _r:
            _m = _r.get_metadata("elster_eric_home")
        return (_m or {}).get("path") or None

    eric_home = body.eric_home or _os.environ.get("FINAMT_ERIC_HOME") or _load_stored_eric()
    # Persist whenever the user supplies a value (so it auto-loads next time)
    if body.eric_home:
        layout.create_dirs()
        with _repo(layout.db_path) as _r:
            _r.set_metadata("elster_eric_home", {"path": body.eric_home})
    if not eric_home:
        raise HTTPException(
            status_code=400,
            detail=(
                "ERiC home directory not configured. "
                "Set FINAMT_ERIC_HOME or pass eric_home in the request body."
            ),
        )

    # ── Resolve certificate ────────────────────────────────────────────
    import base64 as _b64

    stored_cert = layout.root / "elster_cert.pfx"

    cert_path = body.cert_path or _os.path.expanduser(
        _os.environ.get("FINAMT_ELSTER_CERT_PATH") or ""
    )
    cert_password = body.cert_password or _os.environ.get("FINAMT_ELSTER_CERT_PASSWORD", "")
    finanzamt_nr = body.finanzamt_nr or _os.environ.get("FINAMT_ELSTER_FINANZAMT_NR", "")
    bundesland_kz = body.bundesland_kz or _os.environ.get("FINAMT_ELSTER_BUNDESLAND_KZ", "")
    hersteller_id = body.hersteller_id or _os.environ.get("FINAMT_ELSTER_HERSTELLER_ID", "")
    # Fallback: load from stored settings
    if not hersteller_id and db_path.exists():
        with _repo(db_path) as _r:
            _misc = _r.get_metadata("elster_misc") or {}
        hersteller_id = _misc.get("hersteller_id") or ""
    if not hersteller_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "ELSTER Hersteller-ID not configured. "
                "Register at https://www.elster.de/eportal/softwareentwickler "
                "then pass hersteller_id in the request or set "
                "FINAMT_ELSTER_HERSTELLER_ID."
            ),
        )
    # Last-resort: derive from the taxpayer profile city/state stored in the DB
    if not bundesland_kz and db_path.exists():
        from finamt.tax.elster import bundesland_kz_from_city as _bkz_from_city

        with _repo(db_path) as _r:
            _tp = _r.get_metadata("taxpayer") or {}
        for _field in ("state", "city"):
            _kz = _bkz_from_city(_tp.get(_field) or "")
            if _kz:
                bundesland_kz = _kz
                break

    # New cert uploaded — save to project folder for future re-use (no temp file)
    if body.cert_data_b64:
        raw_cert = _b64.b64decode(body.cert_data_b64)
        stored_cert.write_bytes(raw_cert)
        cert_path = str(stored_cert)

    # Fall back to the previously stored project cert
    if not cert_path and stored_cert.exists():
        cert_path = str(stored_cert)

    if not cert_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "ELSTER certificate not configured. "
                "Upload a .pfx file or set FINAMT_ELSTER_CERT_PATH."
            ),
        )

    # ── Load receipts ─────────────────────────────────────────────────
    receipts = []
    if db_path.exists():
        with _repo(db_path) as repo:
            receipts = list(repo.find_by_period(_date(2000, 1, 1), end))

    # ── Build XBRL ───────────────────────────────────────────────────
    cfg_xbrl = EBilanzConfig(
        steuernummer=body.steuernummer,
        elster_id=body.elster_id,
        company_name=body.company_name,
        legal_form=body.legal_form,
        fiscal_year_start=body.fiscal_year_start or str(start),
        fiscal_year_end=body.fiscal_year_end or str(end),
        preparer=body.preparer,
    )

    jab = generate_jahresabschluss(
        receipts=[r for r in receipts if r.receipt_date and r.receipt_date.year == year],
        year=year,
        stammkapital=Decimal(str(body.stammkapital)),
        eingezahltes_kapital=Decimal(str(body.eingezahltes_kapital)),
        vortrag_gewinnverlust=Decimal(str(body.vortrag)),
        nettomethode=body.nettomethode,
    )

    try:
        xbrl_bytes = build_xbrl(jab, cfg_xbrl)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # ── ElsterConfig for ElsterEricClient ─────────────────────────────
    elster_cfg = ElsterConfig(
        cert_path=cert_path,
        cert_password=cert_password,
        steuernummer=body.steuernummer,
        finanzamt_nr=finanzamt_nr,
        bundesland_kz=bundesland_kz,
        hersteller_id=hersteller_id,
    )

    client = ElsterEricClient(
        config=elster_cfg,
        eric_home=eric_home,
        use_test=body.use_test,
        log_dir=eric_log_dir,
    )

    # ── Validate or submit ────────────────────────────────────────────
    if body.validate_only:
        result = client.validate_ebilanz(xbrl_bytes, year=year)
    else:
        result = client.submit_ebilanz(xbrl_bytes, year=year)

    return {
        "success": result.success,
        "telenummer": result.telenummer,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "validate_only": body.validate_only,
        "use_test": body.use_test,
    }


# ---------------------------------------------------------------------------
# Static SPA (must be last)
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
else:

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_not_built(full_path: str):
        return {"error": "Frontend not built yet."}
