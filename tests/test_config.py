"""Tests for autodev.core.config — YAML project configuration."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from autodev.core.config import (
    AgentConfig,
    AgentTrigger,
    BranchStrategy,
    EnvironmentConfig,
    NotificationTarget,
    NotificationType,
    ProjectConfig,
    ReleaseConfig,
    RepoConfig,
    TriggerType,
    load_config,
    save_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_yaml(tmp_path: Path) -> Path:
    """A valid minimal config with only the required 'name' field."""
    cfg_file = tmp_path / "minimal.yaml"
    cfg_file.write_text("name: Minimal Project\n", encoding="utf-8")
    return cfg_file


@pytest.fixture()
def full_yaml(tmp_path: Path) -> Path:
    """A full config mirroring examples/autodev.yaml."""
    content = textwrap.dedent("""\
        name: Great Alerter

        repos:
          - name: backend
            url: github.com/great-alerter/backend
            language: python
            context_file: CLAUDE.md
            tests_command: "pytest tests/ -v"
            lint_command: "ruff check ."

        environments:
          - name: staging
            url: https://staging.great-alerter.com
            deploy_command: "./deploy.sh staging"
            requires_approval: false
          - name: production
            url: https://great-alerter.com
            deploy_command: "./deploy.sh production"
            requires_approval: true

        agents:
          - role: developer
            runner: claude-code
            model: claude-sonnet-4
            max_iterations: 20
            triggers:
              - type: event
                value: task.assigned
            instructions: "Write great code."
            tools: []

          - role: tester
            runner: claude-sonnet
            model: claude-sonnet-4
            max_iterations: 15
            triggers:
              - type: event
                value: pr.created
              - type: schedule
                value: "0 */6 * * *"
            instructions: "Test everything."
            tools:
              - playwright

        release:
          branch_strategy: gitflow
          min_prs: 8
          auto_deploy_staging: true
          require_human_approval: true

        notifications:
          targets:
            - type: telegram
              config:
                chat_id: "123456789"
            - type: slack
              config:
                channel: "#alerts"
            - type: webhook
              config:
                url: https://hooks.example.com
          events:
            - release.ready
            - bug.found
            - deploy.production
    """)
    cfg_file = tmp_path / "full.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    return cfg_file


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_minimal_loads(self, minimal_yaml: Path) -> None:
        cfg = load_config(str(minimal_yaml))
        assert cfg.name == "Minimal Project"

    def test_full_loads(self, full_yaml: Path) -> None:
        cfg = load_config(str(full_yaml))
        assert cfg.name == "Great Alerter"

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_repos_parsed(self, full_yaml: Path) -> None:
        cfg = load_config(str(full_yaml))
        assert len(cfg.repos) == 1
        repo = cfg.repos[0]
        assert repo.name == "backend"
        assert repo.url == "github.com/great-alerter/backend"
        assert repo.language == "python"
        assert repo.tests_command == "pytest tests/ -v"
        assert repo.lint_command == "ruff check ."

    def test_environments_parsed(self, full_yaml: Path) -> None:
        cfg = load_config(str(full_yaml))
        assert len(cfg.environments) == 2
        staging = cfg.environments[0]
        prod = cfg.environments[1]
        assert staging.name == "staging"
        assert staging.requires_approval is False
        assert prod.name == "production"
        assert prod.requires_approval is True

    def test_agents_parsed(self, full_yaml: Path) -> None:
        cfg = load_config(str(full_yaml))
        assert len(cfg.agents) == 2
        dev = cfg.agents[0]
        assert dev.role == "developer"
        assert dev.runner == "claude-code"
        assert dev.model == "claude-sonnet-4"
        assert dev.max_iterations == 20
        assert len(dev.triggers) == 1
        assert dev.triggers[0].type == TriggerType.event
        assert dev.triggers[0].value == "task.assigned"

    def test_tester_tools(self, full_yaml: Path) -> None:
        cfg = load_config(str(full_yaml))
        tester = cfg.agents[1]
        assert "playwright" in tester.tools

    def test_tester_multiple_triggers(self, full_yaml: Path) -> None:
        cfg = load_config(str(full_yaml))
        tester = cfg.agents[1]
        assert len(tester.triggers) == 2
        types = {t.type for t in tester.triggers}
        assert TriggerType.event in types
        assert TriggerType.schedule in types

    def test_release_parsed(self, full_yaml: Path) -> None:
        cfg = load_config(str(full_yaml))
        rel = cfg.release
        assert rel.branch_strategy == BranchStrategy.gitflow
        assert rel.min_prs == 8
        assert rel.auto_deploy_staging is True
        assert rel.require_human_approval is True

    def test_notifications_parsed(self, full_yaml: Path) -> None:
        cfg = load_config(str(full_yaml))
        notif = cfg.notifications
        assert len(notif.targets) == 3
        types = {t.type for t in notif.targets}
        assert NotificationType.telegram in types
        assert NotificationType.slack in types
        assert NotificationType.webhook in types
        assert "release.ready" in notif.events
        assert "bug.found" in notif.events


# ---------------------------------------------------------------------------
# save_config / round-trip
# ---------------------------------------------------------------------------


class TestSaveConfig:
    def test_roundtrip(self, full_yaml: Path, tmp_path: Path) -> None:
        original = load_config(str(full_yaml))
        out = tmp_path / "out.yaml"
        save_config(original, str(out))
        reloaded = load_config(str(out))
        assert reloaded.name == original.name
        assert len(reloaded.repos) == len(original.repos)
        assert len(reloaded.agents) == len(original.agents)
        assert reloaded.release.branch_strategy == original.release.branch_strategy

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        cfg = ProjectConfig(name="Test")
        dest = tmp_path / "deep" / "nested" / "config.yaml"
        save_config(cfg, str(dest))
        assert dest.exists()

    def test_saved_file_is_valid_yaml(self, full_yaml: Path, tmp_path: Path) -> None:
        cfg = load_config(str(full_yaml))
        out = tmp_path / "saved.yaml"
        save_config(cfg, str(out))
        data = yaml.safe_load(out.read_text())
        assert isinstance(data, dict)
        assert data["name"] == "Great Alerter"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_project_config_defaults(self) -> None:
        cfg = ProjectConfig(name="Defaults Test")
        assert cfg.repos == []
        assert cfg.environments == []
        assert cfg.agents == []
        assert cfg.release.branch_strategy == BranchStrategy.gitflow
        assert cfg.release.min_prs == 1
        assert cfg.release.auto_deploy_staging is True
        assert cfg.release.require_human_approval is True
        assert cfg.notifications.targets == []
        assert cfg.notifications.events == []

    def test_repo_defaults(self) -> None:
        repo = RepoConfig(name="svc", url="github.com/org/svc")
        assert repo.language == "python"
        assert repo.context_file == "CLAUDE.md"
        assert repo.tests_command == "pytest tests/"
        assert repo.lint_command == "ruff check ."

    def test_environment_not_requires_approval_by_default(self) -> None:
        env = EnvironmentConfig(
            name="staging",
            url="https://staging.example.com",
            deploy_command="./deploy.sh staging",
        )
        assert env.requires_approval is False

    def test_agent_defaults(self) -> None:
        agent = AgentConfig(role="developer")
        assert agent.runner == "claude-code"
        assert agent.model == "claude-sonnet-4"
        assert agent.max_iterations == 20
        assert agent.triggers == []
        assert agent.tools == []
        assert agent.instructions == ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_project_name_required(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig()  # type: ignore[call-arg]

    def test_trigger_type_enum(self) -> None:
        trigger = AgentTrigger(type="event", value="task.assigned")
        assert trigger.type == TriggerType.event

    def test_trigger_invalid_type(self) -> None:
        with pytest.raises(ValidationError):
            AgentTrigger(type="invalid", value="x")

    def test_branch_strategy_enum(self) -> None:
        rel = ReleaseConfig(branch_strategy="trunk")
        assert rel.branch_strategy == BranchStrategy.trunk

    def test_branch_strategy_invalid(self) -> None:
        with pytest.raises(ValidationError):
            ReleaseConfig(branch_strategy="unknown")

    def test_notification_type_enum(self) -> None:
        target = NotificationTarget(type="telegram", config={"chat_id": "123"})
        assert target.type == NotificationType.telegram

    def test_notification_type_invalid(self) -> None:
        with pytest.raises(ValidationError):
            NotificationTarget(type="discord", config={})

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: [unclosed", encoding="utf-8")
        with pytest.raises(Exception):  # yaml.YAMLError
            load_config(str(bad))

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "no_name.yaml"
        cfg_file.write_text("repos: []\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_config(str(cfg_file))


# ---------------------------------------------------------------------------
# Example file sanity check
# ---------------------------------------------------------------------------


class TestExampleFile:
    def test_example_autodev_yaml_is_valid(self) -> None:
        """The bundled examples/autodev.yaml must parse without errors."""
        example = Path(__file__).parent.parent / "examples" / "autodev.yaml"
        assert example.exists(), "examples/autodev.yaml not found"
        cfg = load_config(str(example))
        assert cfg.name == "Great Alerter"
        assert len(cfg.repos) >= 1
        assert len(cfg.agents) >= 1
