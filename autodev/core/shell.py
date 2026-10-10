"""Async subprocess helpers."""

from __future__ import annotations

import asyncio
import os


class CommandError(RuntimeError):
    def __init__(self, cmd: str, returncode: int, output: str) -> None:
        super().__init__(f"`{cmd}` failed (rc={returncode}):\n{output[-3000:]}")
        self.cmd = cmd
        self.returncode = returncode
        self.output = output


async def run(
    *args: str,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 300,
    check: bool = True,
) -> str:
    """Run a command (no shell) and return combined stdout+stderr."""
    return await _exec(list(args), " ".join(args), cwd, env, timeout, check)


async def sh(
    script: str,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 600,
    check: bool = True,
) -> str:
    """Run a bash script and return combined stdout+stderr."""
    return await _exec(["/bin/bash", "-c", script], script.strip().splitlines()[0][:80], cwd, env, timeout, check)


async def _exec(
    argv: list[str], label: str, cwd: str | None, env: dict[str, str] | None, timeout: float, check: bool
) -> str:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise CommandError(label, -1, f"timed out after {timeout}s") from None
    output = out.decode(errors="replace")
    if check and proc.returncode != 0:
        raise CommandError(label, proc.returncode or -1, output)
    return output


def git_env(token: str, base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for git/gh/claude: GitHub auth without putting the token in URLs."""
    env = dict(base if base is not None else os.environ)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": env.get("GIT_AUTHOR_NAME", "AutoDev"),
            "GIT_AUTHOR_EMAIL": env.get("GIT_AUTHOR_EMAIL", "autodev@users.noreply.github.com"),
            "GIT_COMMITTER_NAME": env.get("GIT_COMMITTER_NAME", "AutoDev"),
            "GIT_COMMITTER_EMAIL": env.get("GIT_COMMITTER_EMAIL", "autodev@users.noreply.github.com"),
        }
    )
    if token:
        env["GITHUB_TOKEN"] = token
        env["GH_TOKEN"] = token
        # Credential helper via env-injected config (git >= 2.31).
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "credential.https://github.com.helper"
        env["GIT_CONFIG_VALUE_0"] = '!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f'
    return env
