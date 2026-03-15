"""AutoDev Framework command-line interface.

Entry point for the ``autodev`` CLI command. Uses a lightweight argparse
setup to avoid pulling in Click/Typer as a hard dependency.

Available commands:
    autodev serve        Start the API server
    autodev worker       Start agent workers
    autodev migrate      Run database migrations
    autodev version      Print version

TODO: Add ``autodev task create`` sub-command.
TODO: Add ``autodev config show`` sub-command.
TODO: Add shell completion support.
TODO: Consider migrating to Typer for richer CLI UX.
"""

from __future__ import annotations

import argparse
import sys


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the FastAPI development server.

    TODO: Pass config (host, port, reload) from ProjectConfig.
    """
    import uvicorn

    from autodev.api.app import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def cmd_worker(args: argparse.Namespace) -> None:
    """Start agent worker processes.

    TODO: Implement worker startup with TaskQueue and EventBus wiring.
    TODO: Support selecting which agents to start via --agents flag.
    """
    print("Worker start not yet implemented.")
    # TODO: Implement worker startup
    sys.exit(1)


def cmd_migrate(args: argparse.Namespace) -> None:
    """Run Alembic database migrations.

    TODO: Run ``alembic upgrade head`` programmatically.
    """
    import subprocess

    result = subprocess.run(["alembic", "upgrade", "head"], check=False)
    sys.exit(result.returncode)


def cmd_version(_args: argparse.Namespace) -> None:
    """Print the package version."""
    from autodev import __version__

    print(f"AutoDev Framework v{__version__}")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the root argument parser."""
    parser = argparse.ArgumentParser(
        prog="autodev",
        description="AutoDev Framework — autonomous multi-agent development platform.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    serve_p = sub.add_parser("serve", help="Start the API server")
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--reload", action="store_true", help="Enable auto-reload")
    serve_p.set_defaults(func=cmd_serve)

    # worker
    worker_p = sub.add_parser("worker", help="Start agent workers")
    worker_p.set_defaults(func=cmd_worker)

    # migrate
    migrate_p = sub.add_parser("migrate", help="Run database migrations")
    migrate_p.set_defaults(func=cmd_migrate)

    # version
    version_p = sub.add_parser("version", help="Print version")
    version_p.set_defaults(func=cmd_version)

    return parser


def app() -> None:
    """CLI entry point invoked by ``autodev`` command."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    app()
