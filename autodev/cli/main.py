"""AutoDev command-line interface.

autodev start [--role api|worker|all]   run the service
autodev status                          projects and agents
autodev task add TITLE [-p project]     queue a task
autodev task list [-p project]          list tasks
autodev release PROJECT                 ship stage to production
"""

from __future__ import annotations

import os

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="autodev", help="AutoDev — autonomous development pipeline.", no_args_is_help=True)
task_app = typer.Typer(help="Tasks.", no_args_is_help=True)
app.add_typer(task_app, name="task")

console = Console()


def get_api_url() -> str:
    return os.environ.get("AUTODEV_API_URL", "http://localhost:8000").rstrip("/")


def _request(method: str, path: str, **kwargs) -> dict | list:
    try:
        response = httpx.request(method, f"{get_api_url()}{path}", timeout=30, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]{exc.response.status_code}: {exc.response.text}[/red]")
        raise typer.Exit(code=1) from exc
    except httpx.HTTPError as exc:
        console.print(f"[red]API error: {exc}[/red]")
        raise typer.Exit(code=1) from exc


def api_get(path: str, **params) -> dict | list:
    return _request("GET", path, params={k: v for k, v in params.items() if v is not None})


def api_post(path: str, data: dict | None = None) -> dict | list:
    return _request("POST", path, json=data or {})


@app.command()
def start(role: str = typer.Option(None, "--role", help="api, worker or all (default: AUTODEV_ROLE or all)")) -> None:
    """Run AutoDev (migrations, then the API and/or the worker)."""
    if role:
        os.environ["AUTODEV_ROLE"] = role
    from autodev.main import run

    run()


@app.command()
def status() -> None:
    """Show projects with task counts and agents."""
    table = Table(title="Projects")
    for col in ("project", "queued", "working", "on stage", "failed"):
        table.add_column(col)
    for p in api_get("/api/projects/"):
        c = p.get("task_counts", {})
        working = sum(c.get(s, 0) for s in ("in_progress", "ci", "deploying"))
        table.add_row(
            p["id"], str(c.get("queued", 0)), str(working), str(c.get("on_stage", 0)), str(c.get("failed", 0))
        )
    console.print(table)

    agents = Table(title="Agents")
    for col in ("agent", "status", "enabled", "task"):
        agents.add_column(col)
    for a in api_get("/api/agents/"):
        agents.add_row(a["id"], a["status"], "yes" if a["enabled"] else "no", a.get("current_task_title") or "")
    console.print(agents)


@task_app.command("add")
def task_add(
    title: str = typer.Argument(..., help="Task title"),
    description: str = typer.Option("", "--description", "-d"),
    project: str | None = typer.Option(None, "--project", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="repo name or role"),
    priority: str = typer.Option("normal", "--priority"),
    pm: bool | None = typer.Option(None, "--pm/--no-pm", help="PM thinks it through first (default: the project's)"),
) -> None:
    """Queue a task."""
    task = api_post(
        "/api/tasks/",
        {
            "title": title,
            "description": description,
            "project_id": project,
            "repo": repo,
            "priority": priority,
            "pm": pm,
        },
    )
    console.print(f"[green]✓[/green] #{task['ticket_number']} {task['title']} ({task['project_id']})")


@task_app.command("list")
def task_list(
    project: str | None = typer.Option(None, "--project", "-p"),
    status: str | None = typer.Option(None, "--status", "-s"),
    limit: int = typer.Option(30, "--limit", "-n"),
) -> None:
    """List recent tasks."""
    table = Table()
    for col in ("#", "status", "project", "title", "PR"):
        table.add_column(col)
    for t in api_get("/api/tasks/", project_id=project, status=status, limit=limit):
        table.add_row(str(t["ticket_number"]), t["status"], t["project_id"] or "", t["title"][:60], t["pr_url"] or "")
    console.print(table)


@task_app.command("refresh-plan")
def task_refresh_plan(tickets: list[int] = typer.Argument(..., help="Ticket numbers of main tasks")) -> None:
    """Rebuild the test plan of main tasks from the task, its follow-ups and the code on stage."""
    by_number = {t["ticket_number"]: t for t in api_get("/api/tasks/", limit=1000)}
    for number in tickets:
        task = by_number.get(number)
        if task is None:
            console.print(f"[red]#{number}: no such task[/red]")
            raise typer.Exit(code=1)
        api_post(f"/api/tasks/{task['id']}/plan/refresh")
        console.print(f"[green]✓[/green] #{number} {task['title'][:60]}: plan rebuild queued")


@app.command()
def release(project: str = typer.Argument(..., help="Project id")) -> None:
    """Open stage→prod PRs; the worker merges them when checks pass."""
    rel = api_post(f"/api/projects/{project}/release")
    console.print(f"[green]✓[/green] Release {rel['version']} started")
    for pr in rel.get("release_prs", []):
        console.print(f"  {pr['pr_url']}")


if __name__ == "__main__":
    app()
