"""
finamt.storage.project
~~~~~~~~~~~~~~~~~~~~~~~~~
Project layout resolution — maps a project name to its three paths:

  ~/.finamt/<project>/finamt.db   — SQLite database
  ~/.finamt/<project>/pdfs/          — original PDF archive
  ~/.finamt/<project>/debug/         — per-receipt agent debug output

Usage::

    from finamt.storage.project import resolve_project, layout_from_db_path

    layout = resolve_project()                   # uses "default" or FINAMT_PROJECT env var
    layout = resolve_project("acme-gmbh-2025")   # explicit project name
    layout = layout_from_db_path(Path("..."))    # reverse: infer layout from db path

Migration note (breaking change in 0.x)
----------------------------------------
Previous versions stored data at ``~/.finamt/finamt.db`` (flat layout).
The new structure requires data to live under a project subfolder.
To migrate an existing installation::

    mkdir -p ~/.finamt/default
    mv ~/.finamt/finamt.db ~/.finamt/default/
    mv ~/.finamt/pdfs         ~/.finamt/default/
    mv ~/.finamt/debug        ~/.finamt/default/
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

FINAMT_HOME = Path.home() / ".finamt"
DEFAULT_PROJECT = "default"
DB_FILENAME = "finamt.db"

# Project names: lowercase alphanumeric + hyphens + underscores, 1–64 chars
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class ProjectLayout:
    """All paths belonging to a single project."""

    name: str
    root: Path  # ~/.finamt/<name>/
    db_path: Path  # root/finamt.db
    pdfs_dir: Path  # root/pdfs/
    debug_dir: Path  # root/debug/
    submitted_returns_dir: Path  # root/submitted_returns/

    def create_dirs(self) -> None:
        """Ensure all project directories exist."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.submitted_returns_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_PROJECT

    @property
    def exists(self) -> bool:
        """True if the db file has been created."""
        return self.db_path.exists()


def resolve_project(
    project: str | None = None,
    *,
    env_var: bool = True,
) -> ProjectLayout:
    """
    Resolve a project name to its layout.

    Priority order:
      1. Explicit ``project`` argument
      2. ``FINAMT_PROJECT`` environment variable (when env_var=True)
      3. ``"default"``
    """
    name = project or (os.environ.get("FINAMT_PROJECT") if env_var else None) or DEFAULT_PROJECT
    return _make_layout(name)


def layout_from_db_path(db_path: Path) -> ProjectLayout:
    """
    Infer a ProjectLayout from an explicit db path.

    If the db lives at ``~/.finamt/<name>/finamt.db`` the project name
    is taken from the containing directory.  Any other path uses the db file's
    stem as the project name, rooting everything in the db's parent directory.
    """
    db_path = db_path.resolve()
    parent = db_path.parent

    if parent.parent == FINAMT_HOME and db_path.name == DB_FILENAME:
        name = parent.name
    else:
        name = db_path.stem

    return ProjectLayout(
        name=name,
        root=parent,
        db_path=db_path,
        pdfs_dir=parent / "pdfs",
        debug_dir=parent / "debug",
        submitted_returns_dir=parent / "submitted_returns",
    )


def validate_project_name(name: str) -> str | None:
    """
    Validate a proposed project name.
    Returns an error message string on failure, None on success.
    """
    if not name or not name.strip():
        return "Name cannot be empty."
    if not _NAME_RE.match(name):
        return (
            "Use only lowercase letters, digits, hyphens and underscores. "
            "Must start with a letter or digit (max 64 characters)."
        )
    return None


def list_projects() -> list[ProjectLayout]:
    """
    Scan FINAMT_HOME for project subdirectories.
    Returns layouts sorted: default first, then alphabetically.
    """
    if not FINAMT_HOME.exists():
        return []

    layouts = []
    for subdir in sorted(FINAMT_HOME.iterdir()):
        if not subdir.is_dir():
            continue
        db = subdir / DB_FILENAME
        layouts.append(
            ProjectLayout(
                name=subdir.name,
                root=subdir,
                db_path=db,
                pdfs_dir=subdir / "pdfs",
                debug_dir=subdir / "debug",
                submitted_returns_dir=subdir / "submitted_returns",
            )
        )

    # default first
    layouts.sort(key=lambda p: (0 if p.is_default else 1, p.name))
    return layouts


# ---------------------------------------------------------------------------
# Module-level default (used by sqlite.py and agent.py as the fallback)
# ---------------------------------------------------------------------------
def _make_layout(name: str) -> ProjectLayout:
    root = FINAMT_HOME / name
    return ProjectLayout(
        name=name,
        root=root,
        db_path=root / DB_FILENAME,
        pdfs_dir=root / "pdfs",
        debug_dir=root / "debug",
        submitted_returns_dir=root / "submitted_returns",
    )


__all__ = [
    "FINAMT_HOME",
    "DEFAULT_PROJECT",
    "ProjectLayout",
    "resolve_project",
    "layout_from_db_path",
    "validate_project_name",
    "list_projects",
]
