"""Tests for autodev.core.config."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from autodev.core.config import Settings, load_config

EXAMPLE = Path(__file__).parent.parent / "examples" / "autodev.yaml"
REPO_CONFIG = Path(__file__).parent.parent / "autodev.yaml"


def test_missing_file_gives_empty_config(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nope.yaml").projects == []


def test_empty_file_gives_empty_config(tmp_path: Path) -> None:
    f = tmp_path / "a.yaml"
    f.write_text("")
    assert load_config(f).projects == []


@pytest.mark.parametrize("path", [EXAMPLE, REPO_CONFIG])
def test_shipped_configs_are_valid(path: Path) -> None:
    cfg = load_config(path)
    assert cfg.projects
    for project in cfg.projects:
        assert project.repos
        assert all("/" in r.name for r in project.repos)


def test_defaults(tmp_path: Path) -> None:
    f = tmp_path / "a.yaml"
    f.write_text("projects:\n  - slug: p\n    name: P\n    repos: [{name: o/r}]\n")
    project = load_config(f).projects[0]
    assert project.base_branch == "stage"
    assert project.prod_branch == "main"
    assert project.max_parallel == 1
    assert project.enabled is True
    assert project.repos[0].role == "app"


def test_env_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGE_HOST", "stage.example.com")
    f = tmp_path / "a.yaml"
    f.write_text(
        "projects:\n  - slug: p\n    name: P\n    stage_url: https://${STAGE_HOST}\n    repos: [{name: o/r}]\n"
    )
    assert load_config(f).projects[0].stage_url == "https://stage.example.com"


def test_unset_env_expands_to_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOPE_NOT_SET", raising=False)
    f = tmp_path / "a.yaml"
    f.write_text("projects:\n  - slug: p\n    name: P${NOPE_NOT_SET}\n    repos: [{name: o/r}]\n")
    assert load_config(f).projects[0].name == "P"


def test_project_requires_repos(tmp_path: Path) -> None:
    f = tmp_path / "a.yaml"
    f.write_text("projects:\n  - slug: p\n    name: P\n")
    with pytest.raises(ValidationError):
        load_config(f)


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTODEV_WORKER_SLOTS", "4")
    monkeypatch.setenv("GH_TOKEN", "t0k")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    s = Settings()
    assert s.worker_slots == 4
    assert s.github_token == "t0k"
