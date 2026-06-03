"""Config loader for the host-side LLM lane.

YAML on disk at `<repo>/.security-scan/config-llm.yaml`. Secrets via env
(never on disk). Schema is intentionally NARROW — LLM-lane fields only. The
deterministic container reads its own `<repo>/.security-scan/config.yaml`.

Lanes are GENERIC: a `lanes:` list where each entry picks a `backend`
(codex-cli / claude-cli / ollama) and a `model`. Any two lanes cross-validate
each other. Legacy `scanners:` + `codex:`/`claude:`/`gemma:` configs are
auto-migrated in `load_config` so old files keep working unchanged.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from security_scan_llm.models import SEVERITY_ORDER
from security_scan_llm.redact import is_local_url


class ConfigError(ValueError):
    """Bad config — surfaced to the user with a clear message."""


# Backends a lane can run on. Each maps to a runner in `runners/`.
#   codex-cli  -> `codex` CLI (ChatGPT/Codex subscription, agentic, reads repo)
#   claude-cli -> `claude` CLI (Claude Max/Pro subscription, agentic, reads repo)
#   ollama     -> local Ollama (any model; file-batched prompt)
BACKENDS = ("codex-cli", "claude-cli", "ollama")
_AGENTIC_BACKENDS = ("codex-cli", "claude-cli")
_DEFAULT_BINARY = {"codex-cli": "codex", "claude-cli": "claude"}


@dataclass
class LaneConfig:
    """One LLM lane. `name` is the scanner id + rule-id prefix (so a lane named
    `qwen` files findings as `qwen.*`). `backend` selects the runner."""
    name: str
    backend: str                         # one of BACKENDS
    model: str | None = None             # None => the backend CLI's default
    timeout: int = 1200                  # primary-scan timeout (seconds)
    validate_timeout: int = 300          # per-finding cross-validation timeout
    binary: str | None = None            # codex-cli / claude-cli only
    # ollama-only knobs:
    base_url: str = "http://localhost:11434"   # MUST be loopback or RFC1918
    keep_alive: str = "5m"
    max_files: int = 60
    max_file_bytes: int = 12_000
    max_total_bytes: int = 200_000


@dataclass
class CrossValidateConfig:
    """Bidirectional review across lanes: each finding is reviewed by a
    different enabled lane. No effect unless at least TWO lanes run. Per-lane
    validation timeouts live on each LaneConfig (`validate_timeout`)."""
    enabled: bool = True


@dataclass
class TriageConfig:
    """Ollama-driven post-processing. All flags default off-ish to keep cost
    down. Ollama URL/model default to the first `ollama` lane when not set."""
    enabled: bool = False
    base_url: str = "http://localhost:11434"
    model: str = "gemma4:26b"
    keep_alive: str = "5m"
    timeout: int = 600
    prewarm: bool = True
    intro_timeout: int = 120
    intro_enabled: bool = True       # 1 chat call/run; ~free
    prose_enabled: bool = False      # 1 chat call/finding; expensive
    fuzzy_dup_enabled: bool = False  # 1 chat call/finding; expensive


@dataclass
class PathsConfig:
    exclude: list[str] = field(default_factory=list)


@dataclass
class SlackConfig:
    enabled: bool = False
    channel_id_env: str | None = None
    webhook_url_env: str | None = None
    bot_token_env: str | None = None


@dataclass
class ProjectConfig:
    """Target GitHub Projects v2 board."""
    owner: str
    number: int


@dataclass
class Config:
    repo: str
    ref: str
    project: ProjectConfig
    github_token: str   # resolved from env; never logged
    lanes: list[LaneConfig]
    paths: PathsConfig
    severity_floor: str
    slack: SlackConfig
    cross_validate: CrossValidateConfig = field(default_factory=CrossValidateConfig)
    triage: TriageConfig = field(default_factory=TriageConfig)

    @property
    def repo_owner(self) -> str:
        return self.repo.split("/", 1)[0]

    @property
    def repo_name(self) -> str:
        return self.repo.split("/", 1)[1]


def _require(d: dict, key: str, path: str) -> object:
    if key not in d or d[key] in (None, ""):
        raise ConfigError(
            f"config: missing required field '{path}.{key}'" if path
            else f"config: missing required field '{key}'"
        )
    return d[key]


def load_config(path: str | Path) -> Config:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"config: file not found: {p}")
    raw = yaml.safe_load(p.read_text()) or {}
    return _from_dict(raw)


def _from_dict(raw: dict) -> Config:
    repo = str(_require(raw, "repo", ""))
    if "/" not in repo:
        raise ConfigError(f"config: 'repo' must be 'owner/name', got: {repo!r}")
    ref = str(_require(raw, "ref", ""))

    project_raw = raw.get("project") or {}
    if not isinstance(project_raw, dict):
        raise ConfigError("config: 'project' must be a mapping with 'owner' and 'number'")
    project_owner = str(_require(project_raw, "owner", "project"))
    try:
        project_number = int(_require(project_raw, "number", "project"))
    except (TypeError, ValueError) as e:
        raise ConfigError(f"config: 'project.number' must be an integer: {e}") from e
    project = ProjectConfig(owner=project_owner, number=project_number)

    token_env = str(raw.get("github_token_env") or "GITHUB_TOKEN")
    token = os.environ.get(token_env, "")
    if not token:
        raise ConfigError(f"config: env var '{token_env}' is empty or unset (holds the GitHub PAT)")

    floor = str(raw.get("severity_floor") or "low").lower()
    if floor not in SEVERITY_ORDER:
        raise ConfigError(f"config: severity_floor must be one of {list(SEVERITY_ORDER)}, got {floor!r}")

    # Lanes: new `lanes:` list, or auto-migrated from the legacy schema.
    if raw.get("lanes"):
        lanes = [_parse_lane(item, i) for i, item in enumerate(raw["lanes"])]
    else:
        lanes = _migrate_legacy_lanes(raw)
    _validate_lanes(lanes)

    cv_raw = raw.get("cross_validate") or {}
    cv_cfg = CrossValidateConfig(enabled=bool(cv_raw.get("enabled", True)))

    paths_raw = raw.get("paths") or {}
    paths = PathsConfig(exclude=list(paths_raw.get("exclude") or []))

    # Triage Ollama defaults inherit from the first `ollama` lane so the user
    # configures Ollama once. Explicit `triage.<field>` still wins.
    first_ollama = next((ln for ln in lanes if ln.backend == "ollama"), None)
    ol_url = first_ollama.base_url if first_ollama else "http://localhost:11434"
    ol_model = first_ollama.model if (first_ollama and first_ollama.model) else "gemma4:26b"
    ol_keep = first_ollama.keep_alive if first_ollama else "5m"
    triage_raw = raw.get("triage") or {}
    triage_cfg = TriageConfig(
        enabled=bool(triage_raw.get("enabled", False)),
        base_url=str(triage_raw.get("base_url") or ol_url),
        model=str(triage_raw.get("model") or ol_model),
        keep_alive=str(triage_raw.get("keep_alive") or ol_keep),
        timeout=int(triage_raw.get("timeout") or 600),
        prewarm=bool(triage_raw.get("prewarm", True)),
        intro_timeout=int(triage_raw.get("intro_timeout") or 120),
        intro_enabled=bool(triage_raw.get("intro_enabled", True)),
        prose_enabled=bool(triage_raw.get("prose_enabled", False)),
        fuzzy_dup_enabled=bool(triage_raw.get("fuzzy_dup_enabled", False)),
    )
    # Same loopback policy as ollama lanes: triage must not send snippets to a
    # remote Ollama. Enforced at load time when triage is on (not just runtime).
    if triage_cfg.enabled and not is_local_url(triage_cfg.base_url):
        raise ConfigError(
            f"config: triage.base_url {triage_cfg.base_url!r} is not loopback/RFC1918 — "
            "triage must not send content to a remote Ollama"
        )

    slack_raw = raw.get("slack") or {}
    slack = SlackConfig(
        enabled=bool(slack_raw.get("enabled", False)),
        channel_id_env=slack_raw.get("channel_id_env"),
        webhook_url_env=slack_raw.get("webhook_url_env"),
        bot_token_env=slack_raw.get("bot_token_env") or "SLACK_BOT_TOKEN",
    )

    return Config(
        repo=repo,
        ref=ref,
        project=project,
        github_token=token,
        lanes=lanes,
        paths=paths,
        severity_floor=floor,
        slack=slack,
        cross_validate=cv_cfg,
        triage=triage_cfg,
    )


def _parse_lane(item: dict, idx: int) -> LaneConfig:
    if not isinstance(item, dict):
        raise ConfigError(f"config: lanes[{idx}] must be a mapping")
    name = str(_require(item, "name", f"lanes[{idx}]"))
    backend = str(_require(item, "backend", f"lanes[{idx}]"))
    if backend not in BACKENDS:
        raise ConfigError(
            f"config: lanes[{idx}].backend must be one of {list(BACKENDS)}, got {backend!r}"
        )
    binary = item.get("binary") or (_DEFAULT_BINARY.get(backend))
    return LaneConfig(
        name=name,
        backend=backend,
        model=(str(item["model"]) if item.get("model") else None),
        timeout=int(item.get("timeout") or 1200),
        validate_timeout=int(item.get("validate_timeout") or 300),
        binary=binary,
        base_url=str(item.get("base_url") or "http://localhost:11434"),
        keep_alive=str(item.get("keep_alive") or "5m"),
        max_files=int(item.get("max_files") or 60),
        max_file_bytes=int(item.get("max_file_bytes") or 12_000),
        max_total_bytes=int(item.get("max_total_bytes") or 200_000),
    )


def _validate_lanes(lanes: list[LaneConfig]) -> None:
    if not lanes:
        raise ConfigError(
            "config: no lanes enabled — add at least one entry under `lanes:` "
            "(or set a legacy scanners.* toggle). Two lanes are needed for cross-validation."
        )
    seen: set[str] = set()
    for ln in lanes:
        # name becomes the SARIF driver name + rule-id prefix + issue-title text;
        # keep it to a safe kebab/alnum set so it can't malform downstream output.
        if not re.fullmatch(r"[A-Za-z0-9_-]+", ln.name):
            raise ConfigError(
                f"config: lane name {ln.name!r} must match [A-Za-z0-9_-]+ (short kebab-case)"
            )
        if ln.name in seen:
            raise ConfigError(f"config: duplicate lane name {ln.name!r} — names must be unique")
        seen.add(ln.name)
        # binary must be a bare command resolved on PATH, never a path to an
        # arbitrary on-disk executable.
        if ln.binary and os.path.basename(ln.binary) != ln.binary:
            raise ConfigError(
                f"config: lane {ln.name!r} binary {ln.binary!r} must be a bare command name, not a path"
            )
        if ln.backend == "ollama" and not is_local_url(ln.base_url):
            raise ConfigError(
                f"config: lane {ln.name!r} base_url {ln.base_url!r} is not loopback/RFC1918 — "
                "source content must not cross a public boundary to a remote Ollama"
            )


def _migrate_legacy_lanes(raw: dict) -> list[LaneConfig]:
    """Synthesize a `lanes:` list from the legacy schema (scanners.* toggles +
    codex:/claude:/gemma: blocks + cross_validate.<lane>_timeout). Keeps old
    config files working without an edit."""
    scanners = raw.get("scanners") or {}
    cv = raw.get("cross_validate") or {}
    lanes: list[LaneConfig] = []

    if scanners.get("codex"):
        c = raw.get("codex") or {}
        lanes.append(LaneConfig(
            name="codex", backend="codex-cli",
            model=(str(c["model"]) if c.get("model") else None),
            timeout=int(c.get("timeout") or 1200),
            validate_timeout=int(cv.get("codex_timeout") or 300),
            binary=str(c.get("binary") or "codex"),
        ))
    if scanners.get("claude"):
        c = raw.get("claude") or {}
        lanes.append(LaneConfig(
            name="claude", backend="claude-cli",
            model=(str(c["model"]) if c.get("model") else None),
            timeout=int(c.get("timeout") or 1200),
            validate_timeout=int(cv.get("claude_timeout") or 300),
            binary=str(c.get("binary") or "claude"),
        ))
    if scanners.get("gemma"):
        g = raw.get("gemma") or {}
        lanes.append(LaneConfig(
            name="gemma", backend="ollama",
            model=str(g.get("model") or "gemma4:26b"),
            timeout=int(g.get("timeout") or 1800),
            validate_timeout=int(cv.get("gemma_timeout") or 180),
            base_url=str(g.get("base_url") or "http://localhost:11434"),
            keep_alive=str(g.get("keep_alive") or "5m"),
            max_files=int(g.get("max_files") or 60),
            max_file_bytes=int(g.get("max_file_bytes") or 12_000),
            max_total_bytes=int(g.get("max_total_bytes") or 200_000),
        ))

    if lanes:
        print(
            "config: migrated legacy `scanners:` config to "
            f"{len(lanes)} lane(s) ({', '.join(ln.name for ln in lanes)}). "
            "Consider rewriting config-llm.yaml to the `lanes:` list — see the manifest.",
            file=sys.stderr,
        )
    return lanes
