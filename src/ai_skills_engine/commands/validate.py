"""``ai-skills-engine validate``: the complete offline check for any repository.

Stages run in order: schema and manifest terminology lint (``--terminology``
also holds ``docs/**/*.md`` to this catalog's glossary), inventory (including host
frontmatter), selection closure and selectors, provenance (``--strict`` fails
missing lineage), ingest checks on the repository's own content, the ADR 0006
internal link check, the collision report, export checks, ``lock --check`` and
``generate --check``. Vendor ``policy``, trust grants and ``overrides`` are
reported as ignored and never applied. Nothing is fetched or executed: vendor
inputs come from ``--vendor-root`` or the verified source cache (fill it with
``ai-skills-engine lock --fetch``). Any error exits non-zero.
"""

import argparse
import io
import sys
from collections.abc import Callable, Mapping
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ai_skills_engine.commands import validate_checks
from ai_skills_engine.commands.mapping_scaffold import ACCEPT_HINT, unaccepted_mappings
from ai_skills_engine.commands.validate_report import (
    Finding,
    Report,
    Severity,
    captured_findings,
)
from ai_skills_engine.inventory.cli import vendor_roots
from ai_skills_engine.lockfile import LOCK_FILENAME, LOCK_HINT
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.load import load_consumer, read_document
from ai_skills_engine.manifest.terminology import lint_descriptions, lint_terminology
from ai_skills_engine.registry.ingest_checks import safe_diagnostic
from ai_skills_engine.source_cache import SourceCache

FAILURES = (OSError, RuntimeError, TypeError, ValueError, KeyError)
_MANIFEST_CODES = frozenset(
    {
        "schema",
        "duplicate-id",
        "invalid-id",
        "invalid-selector",
        "mapping-on-manifest-vendor",
    }
)


def _finding(item: Diagnostic, *, strict: bool = False) -> Finding:
    """Convert an engine diagnostic, applying strict lineage policy.

    Args:
        item: Manifest, inventory or provenance diagnostic.
        strict: Whether missing lineage fails validation.

    Returns:
        Report finding.
    """
    escalate = strict and item.code == "provenance.missing-lineage"
    return Finding(
        item.code,
        item.location,
        item.message,
        Severity.WARNING if item.warning and not escalate else Severity.ERROR,
    )


def _schema(
    *, root: Path, report: Report, roots: Mapping[str, Path], terminology: bool
) -> tuple[dict[str, Any], list[Finding]] | None:
    """Run stage 1 and collect export diagnostics for stage 8.

    Manifest descriptions are always linted. The docs glossary lint holds
    ``docs/**/*.md`` to this catalog's canonical vocabulary, so it runs only
    when the caller opts in; a vendor's own ``docs/glossary.md`` is not ours.

    Args:
        root: Repository root.
        report: Report receiving findings.
        roots: Available vendor trees.
        terminology: Also lint docs against ``docs/glossary.md``.

    Returns:
        Parsed manifest and dangling exports, or None when nothing else can run.
    """
    stage = report.stages["schema"]
    path = root / "ai-skills.yaml"
    try:
        document = read_document(path)
        _, _, diagnostics = load_consumer(path, vendor_roots=roots)
    except FAILURES as error:
        message = safe_diagnostic(str(error)).replace(str(root), ".")
        stage.add(Finding("schema", "ai-skills.yaml", message))
        report.skip_from("inventory", reason="blocked by schema errors")
        return None
    dangling: list[Finding] = []
    for item in diagnostics:
        if item.code == "vendor-authority-ignored":
            report.ignored.append(
                Finding(
                    item.code,
                    item.location,
                    "never applied to this consumer: vendor policy, trust grants "
                    "and overrides grant nothing downstream",
                    Severity.WARNING,
                )
            )
        elif item.code == "dangling-export":
            dangling.append(_finding(item))
        else:
            stage.add(_finding(item))
    vocabulary = (
        lint_terminology(root, document) if terminology else lint_descriptions(document)
    )
    for item in vocabulary:
        stage.add(_finding(item))
    for alias in unaccepted_mappings(document):
        stage.add(
            Finding(
                "mapping.unaccepted",
                f"/vendors/{alias}",
                f"consumer-asserted mapping scaffold is not accepted; {ACCEPT_HINT}",
            )
        )
    if any(item.severity is Severity.ERROR for item in stage.findings):
        report.skip_from("inventory", reason="blocked by schema errors")
        return None
    return document, dangling


def _graph(
    *,
    root: Path,
    report: Report,
    roots: Mapping[str, Path],
    document: dict[str, Any],
    dangling: list[Finding],
) -> None:
    """Run stages 2 to 8 from one inventory and selection observation.

    Args:
        root: Repository root.
        report: Report receiving findings.
        roots: Available vendor trees.
        document: Parsed manifest.
        dangling: Dangling export diagnostics from stage 1.
    """
    from ai_skills_engine.selection.load import load_inputs

    stages = report.stages
    try:
        inventory, selection = load_inputs(root, vendor_roots=roots)
        consumer = load_consumer(root / "ai-skills.yaml", vendor_roots=roots)[0]
    except FAILURES as error:
        stages["inventory"].add(
            Finding(
                "inventory.invalid-input",
                "ai-skills.yaml",
                safe_diagnostic(str(error)).replace(str(root), "."),
            )
        )
        report.skip_from("selection", reason="blocked by inventory errors")
        stages["ingest"].skipped = None
        stages["ingest"].findings.extend(
            validate_checks.own_ingest(root=root, document=document)
        )
        return
    seen: set[tuple[str, str]] = set()
    for item in inventory.diagnostics:
        seen.add((item.code, item.message))
        if item.code.startswith("provenance."):
            stages["provenance"].add(_finding(item, strict=report.strict))
        elif item.code not in {"vendor-authority-ignored", "dangling-export"} and (
            _finding(item) not in stages["schema"].findings
        ):
            # Stage 1 already reports manifest codes and ignored vendor authority.
            stages["inventory"].add(_finding(item))
    for entry in selection.diagnostics:
        if (entry.code, entry.message) in seen:
            continue
        finding = Finding(
            entry.code,
            entry.location,
            f"{entry.message} (fix: {entry.fix})" if entry.fix else entry.message,
            Severity.WARNING if entry.warning else Severity.ERROR,
        )
        if entry.code.startswith("selection.namespace"):
            stages["collisions"].add(finding)
        elif entry.code.startswith("provenance."):
            stages["provenance"].add(finding)
        else:
            stages["selection"].add(finding)
    publisher = consumer.publisher.id
    stages["ingest"].findings.extend(
        validate_checks.own_ingest(root=root, document=document)
    )
    stages["links"].findings.extend(
        validate_checks.own_links(root=root, inventory=inventory, publisher=publisher)
    )
    stages["collisions"].findings.extend(validate_checks.collisions(selection))
    stages["exports"].findings.extend(
        validate_checks.exports(
            consumer=consumer,
            inventory=inventory,
            selection=selection,
            roots=roots,
            dangling=dangling,
        )
    )


def _delegate(*, handler: Callable[[list[str] | None], int], argv: list[str]) -> str:
    """Run a public command, capturing its diagnostics instead of printing them.

    Args:
        handler: Command entry point.
        argv: Its arguments.

    Returns:
        Captured output when the command fails, otherwise an empty string.
    """
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        status = handler(argv)
    return "" if status == 0 else output.getvalue()


def _gates(*, root: Path, report: Report) -> None:
    """Run stages 9 and 10 through the real ``lock`` and ``generate`` commands.

    Args:
        root: Repository root.
        report: Report receiving findings.
    """
    from ai_skills_engine.commands import lock as lock_command
    from ai_skills_engine.generate import marketplace

    lock_stage = report.stages["lock"]
    if lock_stage.skipped is not None:
        return
    if (root / LOCK_FILENAME).exists(follow_symlinks=False):
        failure = _delegate(
            handler=lock_command.main, argv=["--repo-root", str(root), "--check"]
        )
        lock_stage.findings.extend(
            captured_findings(
                code="lock.check",
                location=LOCK_FILENAME,
                output=failure.replace(str(root), "."),
            )
            if failure
            else ()
        )
    else:
        lock_stage.skipped = f"no {LOCK_FILENAME}; {LOCK_HINT} to create one"
    generate_stage = report.stages["generate"]
    adapters = (
        marketplace.marketplace_output_path(repo_root=root),
        marketplace.cursor_marketplace_output_path(repo_root=root),
        marketplace.codex_marketplace_output_path(repo_root=root),
    )
    if not any(path.exists(follow_symlinks=False) for path in adapters):
        generate_stage.skipped = "no committed host marketplaces"
        return
    failure = _delegate(
        handler=marketplace.main, argv=["--check", "--repo-root", str(root)]
    )
    if failure:
        generate_stage.findings.extend(
            captured_findings(
                code="generate.check",
                location="marketplaces",
                output=failure.replace(str(root), "."),
            )
        )


def run(
    *,
    root: Path,
    strict: bool,
    supplied: Mapping[str, Path] | None = None,
    terminology: bool = False,
) -> Report:
    """Run every stage in order without writing to the repository.

    Args:
        root: Repository containing ``ai-skills.yaml``.
        strict: Fail missing lineage.
        supplied: Explicit offline vendor trees; otherwise the source cache.
        terminology: Also lint ``docs/**/*.md`` against ``docs/glossary.md``.

    Returns:
        Complete report.
    """
    report = Report(strict=strict)
    if not (root / "ai-skills.yaml").is_file():
        report.stages["schema"].add(
            Finding(
                "schema",
                "ai-skills.yaml",
                "ai-skills.yaml not found; run `ai-skills-engine init`",
            )
        )
        report.skip_from("inventory", reason="blocked by schema errors")
        return report
    with TemporaryDirectory(prefix="ai-skills-validate-") as temporary:
        roots: dict[str, Path]
        availability: list[Finding]
        unreadable: str | None = None
        if supplied:
            roots, availability = dict(supplied), []
        else:
            try:
                roots, availability = validate_checks.cached_sources(
                    root=root,
                    cache=SourceCache.default(),
                    scratch=Path(temporary),
                )
            except FAILURES as error:
                # A malformed manifest is reported by the schema stage; any other
                # cache failure is surfaced below rather than silently dropped.
                roots, availability = {}, []
                unreadable = safe_diagnostic(str(error))
        for item in availability:
            report.stages["inventory"].add(item)
        loaded = _schema(root=root, report=report, roots=roots, terminology=terminology)
        if loaded is None:
            return report
        if unreadable is not None:
            report.stages["inventory"].add(
                Finding(
                    "validate.vendor-source-unavailable",
                    "/vendors",
                    f"could not read declared vendor sources: {unreadable}; "
                    "vendor checks ran without them",
                    Severity.WARNING,
                )
            )
        document, dangling = loaded
        _graph(
            root=root,
            report=report,
            roots=roots,
            document=document,
            dangling=dangling,
        )
    _gates(root=root, report=report)
    return report


def main(argv: list[str] | None = None) -> int:
    """Validate a repository's declarations, content, lock and adapters.

    Args:
        argv: Command arguments.

    Returns:
        Zero when every stage passed or was skipped, one otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="ai-skills-engine validate", description=__doc__
    )
    parser.add_argument("--repo-root", type=Path, help="Default: current directory")
    parser.add_argument("--strict", action="store_true", help="Fail on missing lineage")
    parser.add_argument(
        "--terminology",
        action="store_true",
        help="Also lint docs/**/*.md against this catalog's docs/glossary.md",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--vendor-root",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="Explicit offline vendor tree (default: the source cache)",
    )
    args = parser.parse_args(argv)
    root = (args.repo_root or Path.cwd()).resolve()
    try:
        supplied = vendor_roots(args.vendor_root)
    except ValueError as error:
        parser.error(str(error))
    # Shared loaders may print acquisition notes; keep stdout machine-readable.
    with redirect_stdout(sys.stderr):
        report = run(
            root=root,
            strict=args.strict,
            supplied=supplied,
            terminology=args.terminology,
        )
    print(report.to_json() if args.format == "json" else report.to_text(), end="")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
