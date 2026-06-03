"""Claude SAST runner — shells out to the locally-installed `claude` CLI.

Uses the user's Claude subscription (Max/Pro via `claude` OAuth login); the tool
never sees an API key. We invoke `claude -p` (headless print mode) with
`--json-schema` to force a schema-conforming response and read the
`structured_output` field of the result envelope (`--output-format json`).

Symmetric with codex.py: the agent reads the repo itself with read-only tools
(Read/Grep/Glob), so the audit prompt and output schema are SHARED with codex —
both produce the identical findings shape, and `_to_sarif` is reused with a
`claude` namespace. The result is wrapped in a synthetic SARIF doc so the
existing normalize.py pipeline consumes it like any other scanner.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from security_scan_llm.redact import redact_text

from . import RunnerResult, agent_env
from .codex import _PROMPT, _SCHEMA, _to_sarif

# Read-only toolset the agent is allowed to use during the audit. No Bash/Edit/
# Write — the runner must never mutate the scanned repo.
_ALLOWED_TOOLS = ("Read", "Grep", "Glob")


def run(
    repo_dir: Path,
    scanner: str = "claude",
    binary: str = "claude",
    model: str | None = None,
    timeout: int = 1200,
    extra_args: list[str] | None = None,
) -> RunnerResult:
    """Invoke claude on `repo_dir` and return its findings as a SARIF doc.

    `scanner` is the lane name — it labels the RunnerResult and namespaces
    rule ids (so a lane named `audit` files `audit.*`).

    Failure modes (all return completed=False with a clear error string):
      - binary missing on PATH
      - claude exits non-zero
      - envelope reports is_error / no structured_output (e.g. tool denial)
      - schema enforcement fails (no `findings` key)
    """
    if shutil.which(binary) is None:
        return RunnerResult(scanner, None, False, f"binary not found: {binary}")

    cmd = [
        binary, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(_SCHEMA),
    ]
    if model:
        cmd += ["--model", model]
    if extra_args:
        cmd += list(extra_args)
    # Variadic flag goes LAST so it can't swallow another arg; prompt is fed on
    # stdin (not argv) to sidestep the positional/variadic ambiguity entirely.
    cmd += ["--allowedTools", *_ALLOWED_TOOLS]

    try:
        r = subprocess.run(
            cmd,
            cwd=str(repo_dir),
            input=_PROMPT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=agent_env(),
        )
    except subprocess.TimeoutExpired:
        return RunnerResult(scanner, None, False, f"timeout after {timeout}s")
    except FileNotFoundError:
        return RunnerResult(scanner, None, False, f"binary not found: {binary}")
    except Exception as e:
        return RunnerResult(scanner, None, False, f"{type(e).__name__}: {e}")

    if r.returncode != 0:
        err = redact_text((r.stderr or r.stdout or "").strip())
        return RunnerResult(scanner, None, False, f"exit {r.returncode}: {err[:300]}")

    try:
        envelope = json.loads(r.stdout or "{}")
    except json.JSONDecodeError as e:
        return RunnerResult(scanner, None, False, f"output parse error: {e}")

    if envelope.get("is_error"):
        return RunnerResult(
            scanner, None, False,
            f"claude reported error: {str(envelope.get('result'))[:200]}",
        )

    structured = envelope.get("structured_output")
    if not isinstance(structured, dict):
        denials = envelope.get("permission_denials") or []
        if denials:
            return RunnerResult(
                scanner, None, False,
                f"claude blocked by tool-permission denials: {denials[:3]}",
            )
        return RunnerResult(scanner, None, False, "claude produced no structured_output")

    findings = structured.get("findings") or []
    if not isinstance(findings, list):
        return RunnerResult(scanner, None, False, "output schema mismatch: 'findings' not a list")

    return RunnerResult(scanner, _to_sarif(findings, scanner), True, None)
