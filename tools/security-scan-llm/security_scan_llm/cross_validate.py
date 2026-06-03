"""Cross-validate LLM findings across lanes (codex / claude / gemma).

Each finding is reviewed by a DIFFERENT enabled lane than the one that produced
it — a Codex finding is judged by Claude (or Gemma), a Claude finding by Codex,
and so on. With any two lanes enabled you get a true bidirectional second
opinion; the dispatch is lane-agnostic, so adding a lane only needs a verdict
function plus an entry in the validator registry.

Verdicts:
  - "real"           — validator agrees, keep severity as-is
  - "false_positive" — validator disagrees, downgrade severity one notch (high→medium,
                       medium→low, low→info; critical stays critical because the cost
                       of missing a real critical is too high to auto-downgrade).
  - "uncertain"      — validator couldn't decide; severity unchanged, flag with note.

The verdict + reason is written to `finding.extra["cross_validation"]` so the
project board (and humans) see both opinions. Findings are NEVER suppressed —
the project board is the single source of triage truth.

Why each lane is good for what:
  - Codex (cloud, ChatGPT subscription) and Claude (cloud, Max/Pro
    subscription) are both strong at deep multi-file reasoning, framework
    idioms, and subtle business-logic / auth bugs — each is an excellent
    independent reviewer of the other's flags.
  - Gemma (local Ollama, free) is fast and has no quota, but is heavy on a
    small host; it's the optional third lane when hardware allows.

Two cloud lanes catch each other's blind spots while keeping source on the
user's subscription rather than a metered API.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from security_scan_llm.config import LaneConfig
from security_scan_llm.models import SEVERITY_ORDER, Finding
from security_scan_llm.redact import is_local_url, redact_text
from security_scan_llm.runners import agent_env

# Severity downgrade ladder. Critical is intentionally NOT downgraded — the
# asymmetry is deliberate (worst case for FP-on-critical is one extra issue
# in the board; worst case for missed-real-critical is a shipped RCE).
_DOWNGRADE = {
    "high": "medium",
    "medium": "low",
    "low": "info",
    "info": "info",
    "critical": "critical",
}

_REVIEW_PROMPT = """You are a senior security reviewer. Another tool has flagged this finding.
Decide whether it is a real, exploitable issue or a false positive.

Finding:
{finding_json}

File excerpt (if available):
{snippet}

Answer with strict JSON only:
{{
  "verdict": "real" | "false_positive" | "uncertain",
  "reason": "one sentence, plain English"
}}

Be skeptical: if the finding is speculative, depends on caller behavior you
can't see, or describes a generic best-practice without exploit impact,
mark it false_positive. If you genuinely can't tell from the excerpt, say
uncertain. Otherwise: real."""

# Strict structured-output schema for a verdict, shared by the codex and claude
# validators. Both OpenAI (codex `--output-schema`) and Anthropic (claude
# `--json-schema`) reject the request unless every object sets
# additionalProperties:false and lists every property key in `required`.
_VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reason"],
    "properties": {
        "verdict": {"type": "string", "enum": ["real", "false_positive", "uncertain"]},
        "reason": {"type": "string"},
    },
}


def cross_validate(
    findings: list[Finding],
    *,
    repo_dir: Path,
    lanes: list[LaneConfig],
) -> list[Finding]:
    """Mutate `findings` in place with a `cross_validation` extra and possibly
    a downgraded severity. Returns the same list for convenience.

    Needs at least two reachable validator lanes — with one lane there is
    nothing to compare against. Each finding is validated by the first lane (in
    `lanes` order) whose name differs from its own scanner. Lanes that are
    unreachable at validation time (missing CLI, Ollama down) are silently
    dropped from the registry.
    """
    # Registry of reachable validators: lane-name -> fn(finding)->(verdict,reason).
    # `L=lane` default-binds each lane into its lambda (avoids loop late-binding).
    validators = {}
    for lane in lanes:
        if lane.backend == "codex-cli" and shutil.which(lane.binary or "codex") is not None:
            validators[lane.name] = lambda f, L=lane: _codex_verdict(
                f, repo_dir=repo_dir, binary=L.binary or "codex",
                model=L.model, timeout=L.validate_timeout,
            )
        elif lane.backend == "claude-cli" and shutil.which(lane.binary or "claude") is not None:
            validators[lane.name] = lambda f, L=lane: _claude_verdict(
                f, repo_dir=repo_dir, binary=L.binary or "claude",
                model=L.model, timeout=L.validate_timeout,
            )
        elif lane.backend == "ollama":
            # Defence-in-depth: refuse the Ollama direction if base_url isn't
            # local, even though snippets are redacted. Cross-validation pays
            # out at the margin; a remote round-trip of source does not.
            if not is_local_url(lane.base_url):
                print(
                    f"cross-validate: lane {lane.name!r} skipped — base_url "
                    f"{lane.base_url!r} is not loopback/private",
                    file=sys.stderr,
                )
            elif _ping_ollama(lane.base_url):
                validators[lane.name] = lambda f, L=lane: _gemma_verdict(
                    f, repo_dir=repo_dir, url=L.base_url, model=L.model or "gemma4:26b",
                    keep_alive=L.keep_alive, timeout=L.validate_timeout,
                )

    if len(validators) < 2:
        return findings

    # Deterministic preference (lanes order) when more than one lane could validate.
    order = [lane.name for lane in lanes if lane.name in validators]
    for f in findings:
        validator = next((name for name in order if name != f.scanner), None)
        if validator is None:
            continue
        verdict, reason = validators[validator](f)
        _apply_verdict(f, validator=validator, verdict=verdict, reason=reason)
    return findings


def _apply_verdict(f: Finding, *, validator: str, verdict: str, reason: str) -> None:
    verdict = verdict.lower() if isinstance(verdict, str) else "uncertain"
    if verdict not in ("real", "false_positive", "uncertain"):
        verdict = "uncertain"
    original_severity = f.severity
    if verdict == "false_positive":
        f.severity = _DOWNGRADE.get(f.severity, f.severity)
    f.extra = {
        **(f.extra or {}),
        "cross_validation": {
            "validator": validator,
            "verdict": verdict,
            "reason": (reason or "").strip()[:300],
            "original_severity": original_severity,
        },
    }


# ---- Gemma verdict (Ollama) -----------------------------------------------


def _ping_ollama(url: str) -> bool:
    try:
        r = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        return r.status_code < 500
    except requests.RequestException:
        return False


def _gemma_verdict(
    f: Finding, *, repo_dir: Path, url: str, model: str, keep_alive: str, timeout: int,
) -> tuple[str, str]:
    snippet = _read_snippet(repo_dir, f.file_path, f.line) or (f.extra or {}).get("snippet", "")
    prompt = _REVIEW_PROMPT.format(
        finding_json=json.dumps(_finding_summary(f), indent=2),
        snippet=redact_text(str(snippet))[:1200] or "(unavailable)",
    )
    try:
        r = requests.post(
            f"{url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "keep_alive": keep_alive,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        content = ((r.json() or {}).get("message") or {}).get("content") or ""
        data = json.loads(content) if content else {}
    except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
        print(f"cross-validate: gemma review failed for {f.rule_id}: {e}", file=sys.stderr)
        return ("uncertain", "validator unavailable")
    verdict = str((data or {}).get("verdict", "uncertain"))
    reason = str((data or {}).get("reason", ""))
    return (verdict, reason)


# ---- Codex verdict (subprocess) -------------------------------------------


def _codex_verdict(
    f: Finding, *, repo_dir: Path, binary: str, model: str | None, timeout: int,
) -> tuple[str, str]:
    snippet = _read_snippet(repo_dir, f.file_path, f.line) or (f.extra or {}).get("snippet", "")
    # Codex is a cloud LLM (ChatGPT subscription) — always redact before send.
    prompt = _REVIEW_PROMPT.format(
        finding_json=json.dumps(_finding_summary(f), indent=2),
        snippet=redact_text(str(snippet))[:1200] or "(unavailable)",
    )
    with tempfile.TemporaryDirectory(prefix="codex-validate-") as td:
        schema = Path(td) / "schema.json"
        out = Path(td) / "out.json"
        schema.write_text(json.dumps(_VERDICT_SCHEMA))
        cmd = [
            binary, "exec",
            "-s", "read-only",
            "-C", str(repo_dir),
            "--color", "never",
            "--ephemeral",
            "--skip-git-repo-check",
            "--output-schema", str(schema),
            "-o", str(out),
        ]
        if model:
            cmd += ["-m", model]
        cmd.append(prompt)
        try:
            r = subprocess.run(
                cmd, cwd=str(repo_dir), capture_output=True, text=True,
                timeout=timeout, check=False, env=agent_env(),
            )
        except subprocess.TimeoutExpired:
            return ("uncertain", "validator timeout")
        except Exception as e:
            print(f"cross-validate: codex review failed for {f.rule_id}: {e}", file=sys.stderr)
            return ("uncertain", "validator unavailable")
        if r.returncode != 0 or not out.is_file():
            return ("uncertain", "validator failed")
        try:
            data = json.loads(out.read_text() or "{}")
        except json.JSONDecodeError:
            return ("uncertain", "validator parse error")
    verdict = str((data or {}).get("verdict", "uncertain"))
    reason = str((data or {}).get("reason", ""))
    return (verdict, reason)


# ---- Claude verdict (subprocess) ------------------------------------------


def _claude_verdict(
    f: Finding, *, repo_dir: Path, binary: str, model: str | None, timeout: int,
) -> tuple[str, str]:
    snippet = _read_snippet(repo_dir, f.file_path, f.line) or (f.extra or {}).get("snippet", "")
    # Claude is a cloud LLM (Max/Pro subscription) — always redact before send.
    prompt = _REVIEW_PROMPT.format(
        finding_json=json.dumps(_finding_summary(f), indent=2),
        snippet=redact_text(str(snippet))[:1200] or "(unavailable)",
    )
    cmd = [
        binary, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(_VERDICT_SCHEMA),
    ]
    if model:
        cmd += ["--model", model]
    # Read-only tools so the validator can inspect the file for itself, parity
    # with codex's `-s read-only -C <repo>`. Prompt is fed on stdin.
    cmd += ["--allowedTools", "Read", "Grep", "Glob"]
    try:
        r = subprocess.run(
            cmd, cwd=str(repo_dir), input=prompt, capture_output=True, text=True,
            timeout=timeout, check=False, env=agent_env(),
        )
    except subprocess.TimeoutExpired:
        return ("uncertain", "validator timeout")
    except Exception as e:
        print(f"cross-validate: claude review failed for {f.rule_id}: {e}", file=sys.stderr)
        return ("uncertain", "validator unavailable")
    if r.returncode != 0:
        return ("uncertain", "validator failed")
    try:
        envelope = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return ("uncertain", "validator parse error")
    data = envelope.get("structured_output") or {}
    verdict = str((data or {}).get("verdict", "uncertain"))
    reason = str((data or {}).get("reason", ""))
    return (verdict, reason)


# ---- helpers --------------------------------------------------------------


def _finding_summary(f: Finding) -> dict:
    """The factual fields we hand to a validator. NEVER include raw secrets — the
    Finding model masks those already, but be defensive. We also run `message`
    through `redact_text` since some scanner messages echo the matched value."""
    return {
        "scanner": f.scanner,
        "category": f.category,
        "rule_id": f.rule_id,
        "severity": f.severity,
        "file": f.file_path,
        "line": f.line,
        "title": f.title,
        "message": redact_text(f.message or ""),
        "masked_preview": f.masked_preview,
    }


def _read_snippet(repo_dir: Path, file_path: str, line: int | None, ctx: int = 6) -> str:
    """Pull a small context window around `line` from the cloned repo. Returns
    empty string on any read failure (the validator can still decide from the
    finding's message).

    Defensive against a scanner emitting absolute or `..`-relative paths that
    could read outside `repo_dir` (e.g. `/etc/passwd`, `../../secrets`)."""
    if not file_path:
        return ""
    p = (repo_dir / file_path).resolve()
    try:
        repo_resolved = repo_dir.resolve()
        if not p.is_relative_to(repo_resolved):
            return ""  # path escape attempt — refuse to read
        if not p.is_file():
            return ""
        lines = p.read_text(errors="ignore").splitlines()
    except OSError:
        return ""
    if not lines:
        return ""
    line = max(1, int(line or 1))
    start = max(0, line - 1 - ctx)
    end = min(len(lines), line - 1 + ctx + 1)
    return "\n".join(f"{i + 1:4d}: {lines[i]}" for i in range(start, end))


# Ensure SEVERITY_ORDER import is actually used downstream — keeps the linter happy
# while signaling that this module respects the canonical severity vocabulary.
assert "critical" in SEVERITY_ORDER
