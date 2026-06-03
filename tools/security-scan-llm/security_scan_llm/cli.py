"""LLM-only orchestrator: codex + gemma SAST + cross-validate + Projects v2 filer.

Complement to the deterministic GitHub Action (leverj/security-scanner). The Action
runs the deterministic lanes (semgrep/gitleaks/trivy/...) inside CI; this runs the
LLM lanes from the developer's host where codex CLI and Ollama are reachable.

Both substrates file into the SAME Projects v2 board with the SAME fingerprint
scheme, so findings dedup across substrates.

Usage:
    security-scan-llm --config /path/to/config.yaml [--repo-dir .] [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from security_scan_llm.config import Config, ConfigError, load_config
from security_scan_llm.cross_validate import cross_validate
from security_scan_llm.github import GitHub, GitHubError
from security_scan_llm.models import Finding
from security_scan_llm.normalize import normalize_sarif
from security_scan_llm.notify import post_digest
from security_scan_llm.runners import RunnerResult
from security_scan_llm.runners import codex as codex_runner
from security_scan_llm.runners import gemma as gemma_runner
from security_scan_llm.sync import sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="security-scan-llm",
        description="Run LLM SAST (codex + gemma) and file findings into a GitHub Projects v2 board.",
    )
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="Scan this directory instead of cloning. Default: clone the repo named in config.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run scanners but file nothing")
    parser.add_argument("--work-dir", default=None, help="Tempdir for the clone (when --repo-dir is unset)")
    parser.add_argument("--keep-work", action="store_true", help="Keep the cloned tree after the run")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not (cfg.scanners.codex or cfg.scanners.gemma):
        print("error: neither scanners.codex nor scanners.gemma is enabled in config.yaml", file=sys.stderr)
        return 2

    return run(cfg, repo_dir=args.repo_dir, dry_run=args.dry_run, work_dir=args.work_dir, keep_work=args.keep_work)


def run(
    cfg: Config,
    repo_dir: str | None = None,
    dry_run: bool = False,
    work_dir: str | None = None,
    keep_work: bool = False,
) -> int:
    gh = GitHub(cfg.github_token, cfg.repo_owner, cfg.repo_name, dry_run=dry_run)

    cloned = False
    work_root: Path | None = None
    if repo_dir:
        target = Path(repo_dir).resolve()
        if not target.exists():
            print(f"error: --repo-dir {target} does not exist", file=sys.stderr)
            return 2
    else:
        work_root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="security-scan-llm-"))
        target = work_root / cfg.repo_name
        if target.exists():
            shutil.rmtree(target)
        try:
            print(f"clone: {cfg.repo}@{cfg.ref} -> {target}", file=sys.stderr)
            gh.clone(cfg.ref, target, shallow=True)
            cloned = True
        except GitHubError as e:
            print(f"github: {e}", file=sys.stderr)
            return 4

    try:
        findings: list[Finding] = []
        completed: list[str] = []
        failed: list[tuple[str, str]] = []

        if cfg.scanners.codex:
            print("scan: codex", file=sys.stderr)
            r = codex_runner.run(
                target,
                binary=cfg.codex.binary,
                model=cfg.codex.model,
                timeout=cfg.codex.timeout,
            )
            _absorb(r, findings, completed, failed)

        if cfg.scanners.gemma:
            print("scan: gemma", file=sys.stderr)
            r = gemma_runner.run(
                target,
                base_url=cfg.gemma.base_url,
                model=cfg.gemma.model,
                keep_alive=cfg.gemma.keep_alive,
                timeout=cfg.gemma.timeout,
                max_files=cfg.gemma.max_files,
                max_file_bytes=cfg.gemma.max_file_bytes,
                max_total_bytes=cfg.gemma.max_total_bytes,
                exclude=cfg.paths.exclude,
            )
            _absorb(r, findings, completed, failed)

        if cfg.cross_validate.enabled and "codex" in completed and "gemma" in completed:
            before = sum(1 for f in findings if f.scanner in ("codex", "gemma"))
            print(f"cross-validate: reviewing {before} LLM finding(s) bidirectionally", file=sys.stderr)
            cross_validate(
                findings,
                repo_dir=target,
                codex_enabled=True,
                gemma_enabled=True,
                codex_binary=cfg.codex.binary,
                codex_model=cfg.codex.model,
                codex_timeout=cfg.cross_validate.codex_timeout,
                ollama_url=cfg.gemma.base_url,
                gemma_model=cfg.gemma.model,
                gemma_keep_alive=cfg.gemma.keep_alive,
                gemma_timeout=cfg.cross_validate.gemma_timeout,
            )

        triage = _maybe_triage(cfg)

        project = gh.resolve_project(cfg.project.owner, cfg.project.number)
        print(f"project: {cfg.project.owner}/projects/{cfg.project.number} resolved", file=sys.stderr)

        if dry_run:
            print(
                f"DRY-RUN: would sync {len(findings)} findings into "
                f"{cfg.project.owner}/projects/{cfg.project.number}",
                file=sys.stderr,
            )
        result = sync(findings, gh, project, severity_floor=cfg.severity_floor, triage=triage)

        if cfg.slack.enabled:
            intro = (
                triage.write_slack_intro(
                    result.created_findings, result, cfg.repo, cfg.ref,
                    cfg.project.owner, cfg.project.number,
                )
                if (triage and triage.enabled)
                else None
            )
            post_digest(
                cfg.slack, result.created_findings, result,
                cfg.repo, cfg.ref, cfg.project.owner, cfg.project.number, intro=intro,
            )

        _print_summary(result, completed, failed, dry_run)

        if not completed:
            print("error: no LLM scanner completed successfully", file=sys.stderr)
            return 3
        return 0

    except GitHubError as e:
        print(f"github: {e}", file=sys.stderr)
        return 4
    finally:
        if cloned and not keep_work and work_root is not None:
            shutil.rmtree(target, ignore_errors=True)
            if work_dir is None and work_root.exists():
                shutil.rmtree(work_root, ignore_errors=True)


def _absorb(r: RunnerResult, findings: list[Finding], completed: list[str], failed: list[tuple[str, str]]) -> None:
    if r.completed and r.sarif:
        norm = normalize_sarif(r.scanner, r.sarif)
        findings.extend(norm)
        completed.append(r.scanner)
        print(f"  -> {r.scanner}: {len(norm)} finding(s)", file=sys.stderr)
    else:
        failed.append((r.scanner, r.error or "unknown error"))
        print(f"  -> {r.scanner}: FAILED ({r.error})", file=sys.stderr)


def _maybe_triage(cfg: Config):
    if not cfg.triage.enabled:
        return None
    from security_scan_llm.triage import Triage
    return Triage(cfg.triage)


def _print_summary(result, completed: list[str], failed: list[tuple[str, str]], dry_run: bool) -> None:
    print("", file=sys.stderr)
    print(f"completed: {', '.join(completed) or '(none)'}", file=sys.stderr)
    if failed:
        for name, err in failed:
            print(f"failed: {name}: {err}", file=sys.stderr)
    print(
        f"summary: total={result.total_findings} "
        f"created={len(result.created)} "
        f"dup={result.skipped_dup} "
        f"fuzzy={result.skipped_fuzzy_dup} "
        f"below-floor={result.skipped_floor}"
        + (" (dry-run)" if dry_run else ""),
        file=sys.stderr,
    )
