"""AutoDev Framework command-line interface.

Entry point for the ``autodev`` CLI command. Uses Typer for rich CLI UX.

Available commands:
    autodev init                    Create autodev.yaml template
    autodev start                   Start the FastAPI server
    autodev status                  Show agents and tasks status
    autodev task add DESC           Create a task via API
    autodev task list               List tasks via API
    autodev agent trigger ID        Trigger an agent via API
    autodev release create          Create a release via API
    autodev release approve VERSION Approve a release via API
    autodev logs                    Tail logs
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import httpx
import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="autodev",
    help="AutoDev Framework — autonomous multi-agent development platform.",
    no_args_is_help=True,
)

task_app = typer.Typer(help="Task management commands.")
agent_app = typer.Typer(help="Agent management commands.")
release_app = typer.Typer(help="Release management commands.")

app.add_typer(task_app, name="task")
app.add_typer(agent_app, name="agent")
app.add_typer(release_app, name="release")

console = Console()


def get_api_url() -> str:
    """Return the API base URL from environment or default."""
    return os.environ.get("AUTODEV_API_URL", "http://localhost:8000")


def api_get(path: str) -> dict:
    """Perform a GET request to the API."""
    url = f"{get_api_url()}{path}"
    try:
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]API error: {exc}[/red]")
        raise typer.Exit(code=1) from exc


def api_post(path: str, data: dict) -> dict:
    """Perform a POST request to the API."""
    url = f"{get_api_url()}{path}"
    try:
        response = httpx.post(url, json=data, timeout=10)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]API error: {exc}[/red]")
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# autodev init
# ---------------------------------------------------------------------------

@app.command()
def init(
    output: Path | None = typer.Option(None, "--output", "-o", help="Output path for autodev.yaml"),
) -> None:
    """Create an autodev.yaml template in the current directory."""
    # Locate the examples/autodev.yaml relative to this file's package root
    this_dir = Path(__file__).parent
    # Walk up to find examples/autodev.yaml
    search = this_dir
    example_file: Path | None = None
    for _ in range(6):
        candidate = search / "examples" / "autodev.yaml"
        if candidate.exists():
            example_file = candidate
            break
        search = search.parent

    dest = output or (Path.cwd() / "autodev.yaml")

    if dest.exists():
        overwrite = typer.confirm(f"{dest} already exists. Overwrite?", default=False)
        if not overwrite:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit()

    if example_file and example_file.exists():
        shutil.copy(example_file, dest)
        console.print(f"[green]✓[/green] Created [bold]{dest}[/bold] from template.")
    else:
        # Fallback minimal template
        template = """\
# AutoDev Framework configuration
name: my-project

repos:
  - name: backend
    url: github.com/user/backend
    language: python

agents:
  - role: developer
    runner: claude-code
    model: claude-sonnet-4

release:
  branch_strategy: gitflow
  require_human_approval: true
"""
        dest.write_text(template)
        console.print(f"[green]✓[/green] Created [bold]{dest}[/bold] (minimal template).")


# ---------------------------------------------------------------------------
# autodev start
# ---------------------------------------------------------------------------

@app.command()
def start(
    config: str = typer.Option("autodev.yaml", "--config", "-c", help="Path to config file"),
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
) -> None:
    """Start AutoDev orchestrator + API server."""
    import asyncio

    from autodev.orchestrator import Orchestrator

    console.print(f"[green]Starting AutoDev orchestrator (config={config}, {host}:{port})[/green]")
    orchestrator = Orchestrator(config_path=config, host=host, port=port)
    asyncio.run(orchestrator.start())


# ---------------------------------------------------------------------------
# autodev status
# ---------------------------------------------------------------------------

@app.command()
def status() -> None:
    """Show status of agents and tasks."""
    api_url = get_api_url()
    console.print(f"[bold]AutoDev status[/bold] — [dim]{api_url}[/dim]\n")

    # Health check
    try:
        health = httpx.get(f"{api_url}/health", timeout=5)
        if health.status_code == 200:
            console.print("[green]● Server:[/green] Online")
        else:
            console.print(f"[yellow]● Server:[/yellow] HTTP {health.status_code}")
    except httpx.HTTPError:
        console.print("[red]● Server:[/red] Unreachable")
        raise typer.Exit(code=1)

    console.print()

    # Agents
    try:
        agents_data = api_get("/api/agents")
        agents = agents_data if isinstance(agents_data, list) else agents_data.get("agents", [])

        table = Table(title="Agents", show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim")
        table.add_column("Role")
        table.add_column("Status")
        table.add_column("Current Task", style="dim")

        status_colors = {
            "idle": "green",
            "running": "yellow",
            "failed": "red",
            "paused": "dim",
        }

        for agent in agents:
            agent_status = agent.get("status", "unknown")
            color = status_colors.get(agent_status, "white")
            table.add_row(
                str(agent.get("id", "")),
                agent.get("role", ""),
                f"[{color}]{agent_status}[/{color}]",
                str(agent.get("current_task_id", "") or "—"),
            )
        console.print(table)
    except typer.Exit:
        console.print("[red]Failed to fetch agents[/red]")

    console.print()

    # Tasks summary
    try:
        tasks_data = api_get("/api/tasks")
        tasks = tasks_data if isinstance(tasks_data, list) else tasks_data.get("tasks", [])

        status_counts: dict[str, int] = {}
        for t in tasks:
            s = t.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        table2 = Table(title="Task Summary", show_header=True, header_style="bold cyan")
        table2.add_column("Status")
        table2.add_column("Count", justify="right")

        for s, cnt in sorted(status_counts.items()):
            table2.add_row(s, str(cnt))
        if not status_counts:
            table2.add_row("[dim]No tasks[/dim]", "0")
        console.print(table2)
    except typer.Exit:
        console.print("[red]Failed to fetch tasks[/red]")


# ---------------------------------------------------------------------------
# autodev task add / list
# ---------------------------------------------------------------------------

@task_app.command("add")
def task_add(
    description: str = typer.Argument(..., help="Task description"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Target repository"),
    priority: str = typer.Option(
        "normal", "--priority", "-p", help="Priority: critical/high/normal/low"
    ),
) -> None:
    """Create a new task via the API."""
    payload: dict = {
        "description": description,
        "title": description[:80],
        "source": "manual",
        "priority": priority,
    }
    if repo:
        payload["repo"] = repo

    result = api_post("/api/tasks", payload)
    task_id = result.get("id", "?")
    console.print(f"[green]✓[/green] Task created: [bold]{task_id}[/bold]")
    if result.get("status"):
        console.print(f"  Status: [cyan]{result['status']}[/cyan]")


@task_app.command("list")
def task_list(
    status_filter: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Filter by repo"),
) -> None:
    """List tasks via the API."""
    params: list[str] = []
    if status_filter:
        params.append(f"status={status_filter}")
    if repo:
        params.append(f"repo={repo}")
    qs = "?" + "&".join(params) if params else ""

    data = api_get(f"/api/tasks{qs}")
    tasks = data if isinstance(data, list) else data.get("tasks", [])

    if not tasks:
        console.print("[dim]No tasks found.[/dim]")
        return

    table = Table(title="Tasks", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("Repo", style="dim")
    table.add_column("Assigned", style="dim")

    status_colors = {
        "queued": "yellow",
        "assigned": "blue",
        "in_progress": "cyan",
        "review": "magenta",
        "done": "green",
        "failed": "red",
    }

    for task in tasks:
        s = task.get("status", "")
        color = status_colors.get(s, "white")
        table.add_row(
            str(task.get("id", ""))[:12],
            task.get("title", task.get("description", ""))[:60],
            f"[{color}]{s}[/{color}]",
            task.get("priority", ""),
            task.get("repo", "") or "—",
            task.get("assigned_to", "") or "—",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# autodev agent trigger
# ---------------------------------------------------------------------------

@agent_app.command("trigger")
def agent_trigger(
    agent_id: str = typer.Argument(..., help="Agent ID or role to trigger"),
    task_id: str | None = typer.Option(None, "--task", "-t", help="Task ID to assign"),
) -> None:
    """Trigger an agent via POST /api/agents/{id}/trigger."""
    payload: dict = {}
    if task_id:
        payload["task_id"] = task_id

    result = api_post(f"/api/agents/{agent_id}/trigger", payload)
    console.print(f"[green]✓[/green] Agent [bold]{agent_id}[/bold] triggered.")
    if result:
        rprint(result)


# ---------------------------------------------------------------------------
# autodev release create / approve
# ---------------------------------------------------------------------------

@release_app.command("create")
def release_create(
    version: str | None = typer.Option(None, "--version", "-v", help="Release version"),
    notes: str | None = typer.Option(None, "--notes", "-n", help="Release notes"),
) -> None:
    """Create a new release via the API."""
    payload: dict = {}
    if version:
        payload["version"] = version
    if notes:
        payload["release_notes"] = notes

    result = api_post("/api/releases", payload)
    release_id = result.get("id", "?")
    release_version = result.get("version", version or "?")
    console.print(
        f"[green]✓[/green] Release [bold]{release_version}[/bold] created (id: {release_id})."
    )


@release_app.command("approve")
def release_approve(
    version: str = typer.Argument(..., help="Release version to approve"),
    approved_by: str | None = typer.Option(None, "--by", help="Approver name"),
) -> None:
    """Approve a release via POST /api/releases/{id}/approve."""
    # First look up the release by version
    data = api_get("/api/releases")
    releases = data if isinstance(data, list) else data.get("releases", [])
    release = next((r for r in releases if r.get("version") == version), None)

    if release is None:
        console.print(f"[red]Release '{version}' not found.[/red]")
        raise typer.Exit(code=1)

    release_id = release["id"]
    payload: dict = {}
    if approved_by:
        payload["approved_by"] = approved_by

    api_post(f"/api/releases/{release_id}/approve", payload)
    console.print(f"[green]✓[/green] Release [bold]{version}[/bold] approved.")


# ---------------------------------------------------------------------------
# autodev logs
# ---------------------------------------------------------------------------

@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow/tail logs"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    log_file: Path | None = typer.Option(None, "--file", help="Log file path"),
) -> None:
    """Show or tail AutoDev logs."""
    # Try to find a log file
    candidates = [
        log_file,
        Path("autodev.log"),
        Path("/var/log/autodev.log"),
        Path.home() / ".autodev" / "autodev.log",
    ]
    found: Path | None = None
    for c in candidates:
        if c and c.exists():
            found = c
            break

    if found:
        if follow:
            console.print(f"[dim]Tailing {found} (Ctrl+C to stop)[/dim]")
            try:
                subprocess.run(["tail", "-f", "-n", str(lines), str(found)], check=False)
            except KeyboardInterrupt:
                pass
        else:
            try:
                subprocess.run(["tail", "-n", str(lines), str(found)], check=False)
            except FileNotFoundError:
                content = found.read_text()
                tail_lines = content.splitlines()[-lines:]
                console.print("\n".join(tail_lines))
    else:
        console.print(
            "[yellow]No log file found. Start the server with `autodev start` first.[/yellow]"
        )
        console.print(
            "[dim]Hint: set --file path/to/autodev.log or use AUTODEV_LOG_FILE env var.[/dim]"
        )
        if follow:
            raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
