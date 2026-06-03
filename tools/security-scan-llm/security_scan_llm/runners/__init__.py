"""Scanner runner contract. Invokes pre-installed binaries, returns parsed SARIF."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Env vars an agentic CLI subprocess (codex / claude) has no business seeing.
# The CLIs' own auth (CODEX_HOME, ~/.claude.json, PATH, HOME, …) is preserved;
# only secrets the read-only audit agent never needs are stripped.
_STRIP_FROM_AGENT_ENV = (
    # GitHub PAT — used only by the filer, never by the audit agent.
    "GITHUB_TOKEN", "GH_TOKEN",
    # Force subscription auth for the LLM CLIs: an API key in env would route to
    # a metered API, which this tool deliberately avoids.
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY",
    # Unrelated creds that may sit in the shell / CI env — no audit use for any.
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "NPM_TOKEN", "DOCKER_PASSWORD",
    "SLACK_BOT_TOKEN", "SLACK_WEBHOOK_URL",
    "SUPABASE_DB_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY",
)


def agent_env() -> dict[str, str]:
    """Process environment minus secrets the audit agent doesn't need."""
    return {k: v for k, v in os.environ.items() if k not in _STRIP_FROM_AGENT_ENV}


@dataclass
class RunnerResult:
    scanner: str
    sarif: dict | None
    completed: bool
    error: str | None = None


def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str, str]:
    """Wrap subprocess.run. Returns (returncode, stdout, stderr). Never logs args.
    Uses agent_env() so a caller can't accidentally leak the PAT to a child."""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=agent_env(),
    )
    return proc.returncode, proc.stdout, proc.stderr
