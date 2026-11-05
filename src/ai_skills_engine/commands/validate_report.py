"""Ordered ``validate`` stages, findings and their text/JSON renderings."""

import json
from dataclasses import dataclass, field
from enum import StrEnum, auto

STAGES = (
    ("schema", "schema and terminology lint"),
    ("inventory", "inventory and host frontmatter"),
    ("selection", "selection closure and selectors"),
    ("provenance", "provenance and lineage"),
    ("ingest", "ingest checks on own content"),
    ("links", "ADR 0006 internal link check"),
    ("collisions", "collision report"),
    ("exports", "export checks"),
    ("lock", "lock --check"),
    ("generate", "generate --check"),
)
_MAX_LINES = 60


class Severity(StrEnum):
    """How a finding affects the exit status.

    Attributes:
        ERROR: Fails validation.
        WARNING: Reported only.
        INFO: Report entry, such as a shared destination name.
    """

    ERROR = auto()
    WARNING = auto()
    INFO = auto()


class Status(StrEnum):
    """Outcome of one stage.

    Attributes:
        PASSED: Ran without errors.
        FAILED: Ran and found at least one error.
        SKIPPED: Did not run; ``note`` says why.
    """

    PASSED = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass(frozen=True)
class Finding:
    """One diagnostic at a manifest pointer, identity or path."""

    code: str
    location: str
    message: str
    severity: Severity = Severity.ERROR


@dataclass
class Stage:
    """Findings of one pipeline stage."""

    name: str
    title: str
    findings: list[Finding] = field(default_factory=list)
    skipped: str | None = None
    note: str | None = None

    @property
    def status(self) -> Status:
        """Derive the stage outcome.

        Returns:
            Skipped, failed on any error, otherwise passed.
        """
        if self.skipped is not None:
            return Status.SKIPPED
        if any(item.severity is Severity.ERROR for item in self.findings):
            return Status.FAILED
        return Status.PASSED

    def add(self, finding: Finding) -> None:
        """Record a finding once.

        Args:
            finding: Diagnostic to append.
        """
        if finding not in self.findings:
            self.findings.append(finding)


@dataclass
class Report:
    """Complete ordered pipeline outcome."""

    strict: bool
    stages: dict[str, Stage] = field(
        default_factory=lambda: {
            name: Stage(name=name, title=title) for name, title in STAGES
        }
    )
    ignored: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether no stage failed.

        Returns:
            True when every stage passed or was skipped.
        """
        return all(stage.status is not Status.FAILED for stage in self.stages.values())

    def skip_from(self, name: str, *, reason: str) -> None:
        """Skip a stage and every later stage that has not produced findings.

        Args:
            name: First stage to skip.
            reason: Why the stages could not run.
        """
        names = [item for item, _ in STAGES]
        for later in names[names.index(name) :]:
            stage = self.stages[later]
            if not stage.findings and stage.skipped is None:
                stage.skipped = reason

    def errors(self) -> int:
        """Count error findings.

        Returns:
            Number of errors across all stages.
        """
        return sum(
            item.severity is Severity.ERROR
            for stage in self.stages.values()
            for item in stage.findings
        )

    def to_json(self) -> str:
        """Render stable machine-readable diagnostics.

        Returns:
            Indented JSON with a trailing newline.
        """

        def finding(item: Finding) -> dict[str, str]:
            """Serialize one finding."""
            return {
                "severity": str(item.severity),
                "code": item.code,
                "location": item.location,
                "message": item.message,
            }

        document = {
            "ok": self.ok,
            "strict": self.strict,
            "errors": self.errors(),
            "stages": [
                {
                    "stage": position,
                    "name": stage.name,
                    "title": stage.title,
                    "status": str(stage.status),
                    "note": stage.skipped or stage.note,
                    "diagnostics": [finding(item) for item in stage.findings],
                }
                for position, stage in enumerate(self.stages.values(), start=1)
            ],
            "ignored": [finding(item) for item in self.ignored],
        }
        return json.dumps(document, indent=2) + "\n"

    def to_text(self) -> str:
        """Render a human-readable summary.

        Returns:
            One line per stage, its findings, ignored vendor authority and verdict.
        """
        lines = [f"validate: {'strict' if self.strict else 'standard'} mode"]
        total = len(self.stages)
        for position, stage in enumerate(self.stages.values(), start=1):
            detail = stage.skipped or stage.note
            suffix = f" ({detail})" if detail else ""
            lines.append(f"[{position}/{total}] {stage.title}: {stage.status}{suffix}")
            lines.extend(
                f"  {item.severity} {item.code} {item.location}: {item.message}"
                for item in stage.findings
            )
        lines.extend(
            f"ignored {item.code} {item.location}: {item.message}"
            for item in self.ignored
        )
        lines.append(
            "validate: passed"
            if self.ok
            else f"validate: FAILED with {self.errors()} error(s)"
        )
        return "\n".join(lines) + "\n"


def captured_findings(*, code: str, location: str, output: str) -> list[Finding]:
    """Turn a delegated command's diagnostic output into bounded findings.

    Args:
        code: Stage diagnostic code.
        location: Checked file.
        output: Captured stdout/stderr text.

    Returns:
        One error per non-empty line, truncated with a count of omitted lines.
    """
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        lines = ["command failed without diagnostics"]
    findings = [Finding(code, location, line) for line in lines[:_MAX_LINES]]
    if len(lines) > _MAX_LINES:
        findings.append(
            Finding(code, location, f"... {len(lines) - _MAX_LINES} more line(s)")
        )
    return findings
