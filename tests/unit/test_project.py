"""
tests/test_project.py
~~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.storage.project — ProjectLayout and resolution helpers.
"""

from __future__ import annotations

import pytest

from finamt.storage.project import (
    DEFAULT_PROJECT,
    FINAMT_HOME,
    ProjectLayout,
    layout_from_db_path,
    list_projects,
    resolve_project,
    validate_project_name,
)

# ---------------------------------------------------------------------------
# resolve_project
# ---------------------------------------------------------------------------


class TestResolveProject:
    def test_no_args_returns_default(self):
        layout = resolve_project(env_var=False)
        assert layout.name == DEFAULT_PROJECT

    def test_explicit_name(self):
        layout = resolve_project("my-project", env_var=False)
        assert layout.name == "my-project"

    def test_paths_are_under_finamt_home(self):
        layout = resolve_project("acme", env_var=False)
        assert layout.root == FINAMT_HOME / "acme"
        assert layout.db_path == FINAMT_HOME / "acme" / "finamt.db"
        assert layout.pdfs_dir == FINAMT_HOME / "acme" / "pdfs"
        assert layout.debug_dir == FINAMT_HOME / "acme" / "debug"

    def test_env_var_used_when_no_arg(self, monkeypatch):
        monkeypatch.setenv("FINAMT_PROJECT", "env-proj")
        layout = resolve_project()
        assert layout.name == "env-proj"

    def test_explicit_arg_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("FINAMT_PROJECT", "env-proj")
        layout = resolve_project("explicit")
        assert layout.name == "explicit"


# ---------------------------------------------------------------------------
# ProjectLayout properties
# ---------------------------------------------------------------------------


class TestProjectLayout:
    def _layout(self, name="myproject"):
        return resolve_project(name, env_var=False)

    def test_is_default_true_for_default(self):
        assert resolve_project(DEFAULT_PROJECT, env_var=False).is_default is True

    def test_is_default_false_for_other(self):
        assert self._layout("other").is_default is False

    def test_exists_false_when_no_db(self, tmp_path):
        layout = ProjectLayout(
            name="test",
            root=tmp_path / "test",
            db_path=tmp_path / "test" / "finamt.db",
            pdfs_dir=tmp_path / "test" / "pdfs",
            debug_dir=tmp_path / "test" / "debug",
        )
        assert layout.exists is False

    def test_exists_true_when_db_present(self, tmp_path):
        db = tmp_path / "finamt.db"
        db.touch()
        layout = ProjectLayout(
            name="test",
            root=tmp_path,
            db_path=db,
            pdfs_dir=tmp_path / "pdfs",
            debug_dir=tmp_path / "debug",
        )
        assert layout.exists is True

    def test_create_dirs(self, tmp_path):
        layout = ProjectLayout(
            name="new",
            root=tmp_path / "new",
            db_path=tmp_path / "new" / "finamt.db",
            pdfs_dir=tmp_path / "new" / "pdfs",
            debug_dir=tmp_path / "new" / "debug",
        )
        layout.create_dirs()
        assert layout.root.is_dir()
        assert layout.pdfs_dir.is_dir()
        assert layout.debug_dir.is_dir()


# ---------------------------------------------------------------------------
# layout_from_db_path
# ---------------------------------------------------------------------------


class TestLayoutFromDbPath:
    def test_standard_path_extracts_project_name(self, tmp_path, monkeypatch):
        """~/.finamt/<name>/finamt.db should resolve to project name == <name>"""
        # Monkeypatch FINAMT_HOME to tmp_path
        import finamt.storage.project as proj_mod

        monkeypatch.setattr(proj_mod, "FINAMT_HOME", tmp_path)
        db = tmp_path / "myproject" / "finamt.db"
        db.parent.mkdir(parents=True)
        db.touch()
        layout = proj_mod.layout_from_db_path(db)
        assert layout.name == "myproject"

    def test_non_standard_path_uses_stem(self, tmp_path):
        db = tmp_path / "custom.db"
        db.touch()
        layout = layout_from_db_path(db)
        assert layout.name == "custom"
        assert layout.db_path == db.resolve()


# ---------------------------------------------------------------------------
# validate_project_name
# ---------------------------------------------------------------------------


class TestValidateProjectName:
    @pytest.mark.parametrize("name", ["default", "my-project", "acme2025", "a", "a_b"])
    def test_valid_names_return_none(self, name):
        assert validate_project_name(name) is None

    def test_empty_name_returns_error(self):
        assert validate_project_name("") is not None

    def test_whitespace_only_returns_error(self):
        assert validate_project_name("   ") is not None

    @pytest.mark.parametrize("name", ["UPPER", "has space", "has.dot", "-starts-hyphen"])
    def test_invalid_names_return_error(self, name):
        assert validate_project_name(name) is not None


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


class TestListProjects:
    def test_empty_when_no_home(self, tmp_path, monkeypatch):
        import finamt.storage.project as proj_mod

        monkeypatch.setattr(proj_mod, "FINAMT_HOME", tmp_path / "nonexistent")
        assert list_projects() == []

    def test_lists_project_subdirs(self, tmp_path, monkeypatch):
        import finamt.storage.project as proj_mod

        monkeypatch.setattr(proj_mod, "FINAMT_HOME", tmp_path)
        (tmp_path / "default").mkdir()
        (tmp_path / "proj-a").mkdir()
        (tmp_path / "proj-b").mkdir()
        layouts = list_projects()
        names = [p.name for p in layouts]
        assert names[0] == "default"
        assert "proj-a" in names
        assert "proj-b" in names

    def test_default_sorted_first(self, tmp_path, monkeypatch):
        import finamt.storage.project as proj_mod

        monkeypatch.setattr(proj_mod, "FINAMT_HOME", tmp_path)
        for name in ("zzz", "aaa", "default"):
            (tmp_path / name).mkdir()
        layouts = list_projects()
        assert layouts[0].name == "default"

    def test_files_not_included(self, tmp_path, monkeypatch):
        import finamt.storage.project as proj_mod

        monkeypatch.setattr(proj_mod, "FINAMT_HOME", tmp_path)
        (tmp_path / "proj").mkdir()
        (tmp_path / "some-file.txt").touch()
        layouts = list_projects()
        assert all(p.name != "some-file.txt" for p in layouts)
