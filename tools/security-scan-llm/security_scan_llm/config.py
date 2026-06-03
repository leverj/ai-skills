"""Config loader for the host-side LLM lane.

YAML on disk at `<repo>/.security-scan/config-llm.yaml`. Secrets via env
(never on disk). Schema is intentionally NARROW — LLM-lane fields only. The
deterministic container reads its own `<repo>/.security-scan/config.yaml`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from security_scan_llm.models import SEVERITY_ORDER


class ConfigError(ValueError):
    """Bad config — surfaced to the user with a clear message."""


@dataclass
class ScannersConfig:
    """Which LLM lanes to run. Independent toggles.

    Both default OFF — the host tool is "the LLM lane substrate." A user
    invoking it with neither toggle on gets a clear error rather than a
    silent no-op."""
    codex: bool = False     # OpenAI Codex via local `codex` CLI (subscription)
    claude: bool = False    # Anthropic Claude via local `claude` CLI (subscription)
    gemma: bool = False     # Local Gemma via Ollama


@dataclass
class CodexConfig:
    """Tunables for the local Codex CLI runner. Auth is `codex login`
    (ChatGPT subscription); the tool never sees an API key."""
    binary: str = "codex"
    model: str | None = None    # None => use codex's configured default
    timeout: int = 1200         # seconds


@dataclass
class ClaudeConfig:
    """Tunables for the local Claude CLI runner. Auth is `claude` OAuth login
    (Max/Pro subscription); the tool never sees an API key."""
    binary: str = "claude"
    model: str | None = None    # None => use the claude CLI's configured default
    timeout: int = 1200         # seconds


@dataclass
class GemmaConfig:
    """Tunables for the Ollama-backed Gemma SAST runner."""
    base_url: str = "http://localhost:11434"   # loopback by default; refused if non-local
    model: str = "gemma4:26b"
    keep_alive: str = "5m"
    timeout: int = 1800
    max_files: int = 60
    max_file_bytes: int = 12_000
    max_total_bytes: int = 200_000


@dataclass
class CrossValidateConfig:
    """Bidirectional review: each LLM lane's findings are reviewed by a different
    enabled lane (e.g. codex<->claude, codex<->gemma). No effect unless at least
    TWO of scanners.codex / scanners.claude / scanners.gemma are enabled."""
    enabled: bool = True
    codex_timeout: int = 300
    claude_timeout: int = 300
    gemma_timeout: int = 180


@dataclass
class TriageConfig:
    """Gemma-driven post-processing. All flags default off-ish to keep cost down."""
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
    scanners: ScannersConfig
    paths: PathsConfig
    severity_floor: str
    slack: SlackConfig
    codex: CodexConfig = field(default_factory=CodexConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    gemma: GemmaConfig = field(default_factory=GemmaConfig)
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

    scanners_raw = raw.get("scanners") or {}
    scanners = ScannersConfig(
        codex=bool(scanners_raw.get("codex", False)),
        claude=bool(scanners_raw.get("claude", False)),
        gemma=bool(scanners_raw.get("gemma", False)),
    )

    codex_raw = raw.get("codex") or {}
    codex_cfg = CodexConfig(
        binary=str(codex_raw.get("binary") or "codex"),
        model=(str(codex_raw.get("model")) if codex_raw.get("model") else None),
        timeout=int(codex_raw.get("timeout") or 1200),
    )

    claude_raw = raw.get("claude") or {}
    claude_cfg = ClaudeConfig(
        binary=str(claude_raw.get("binary") or "claude"),
        model=(str(claude_raw.get("model")) if claude_raw.get("model") else None),
        timeout=int(claude_raw.get("timeout") or 1200),
    )

    gemma_raw = raw.get("gemma") or {}
    gemma_cfg = GemmaConfig(
        base_url=str(gemma_raw.get("base_url") or "http://localhost:11434"),
        model=str(gemma_raw.get("model") or "gemma4:26b"),
        keep_alive=str(gemma_raw.get("keep_alive") or "5m"),
        timeout=int(gemma_raw.get("timeout") or 1800),
        max_files=int(gemma_raw.get("max_files") or 60),
        max_file_bytes=int(gemma_raw.get("max_file_bytes") or 12_000),
        max_total_bytes=int(gemma_raw.get("max_total_bytes") or 200_000),
    )

    cv_raw = raw.get("cross_validate") or {}
    cv_cfg = CrossValidateConfig(
        enabled=bool(cv_raw.get("enabled", True)),
        codex_timeout=int(cv_raw.get("codex_timeout") or 300),
        claude_timeout=int(cv_raw.get("claude_timeout") or 300),
        gemma_timeout=int(cv_raw.get("gemma_timeout") or 180),
    )

    paths_raw = raw.get("paths") or {}
    paths = PathsConfig(exclude=list(paths_raw.get("exclude") or []))

    triage_raw = raw.get("triage") or {}
    # Triage Ollama defaults inherit from `gemma:` so the user configures
    # Ollama once. Explicit `triage.<field>` still wins.
    triage_cfg = TriageConfig(
        enabled=bool(triage_raw.get("enabled", False)),
        base_url=str(triage_raw.get("base_url") or gemma_cfg.base_url),
        model=str(triage_raw.get("model") or gemma_cfg.model),
        keep_alive=str(triage_raw.get("keep_alive") or gemma_cfg.keep_alive),
        timeout=int(triage_raw.get("timeout") or 600),
        prewarm=bool(triage_raw.get("prewarm", True)),
        intro_timeout=int(triage_raw.get("intro_timeout") or 120),
        intro_enabled=bool(triage_raw.get("intro_enabled", True)),
        prose_enabled=bool(triage_raw.get("prose_enabled", False)),
        fuzzy_dup_enabled=bool(triage_raw.get("fuzzy_dup_enabled", False)),
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
        scanners=scanners,
        paths=paths,
        severity_floor=floor,
        slack=slack,
        codex=codex_cfg,
        claude=claude_cfg,
        gemma=gemma_cfg,
        cross_validate=cv_cfg,
        triage=triage_cfg,
    )
