---
name: lintro-add
description: Guide for adding new linting/formatting tools to lintro. Use when implementing shellcheck, shfmt, sqlfluff, taplo, semgrep, gitleaks, or any new tool plugin.
---

# Adding a New Tool to Lintro

This document serves as a comprehensive guide for adding a new tool to Lintro.

## Related Skills

- **stand-py**: Follow Python coding standards (type hints, docstrings, trailing commas)
- **test**: Follow pytest best practices (no classes, use fixtures, parametrize)
- **commit**: Use semantic commit format when committing changes

## Quick Reference

### New files (paths)

```text
lintro/parsers/<tool>/__init__.py
lintro/parsers/<tool>/<tool>_issue.py
lintro/parsers/<tool>/<tool>_parser.py
lintro/tools/definitions/<tool>.py
test_samples/tools/<category>/<tool>/<tool>_violations.<ext>
tests/unit/parsers/test_<tool>_parser.py
tests/unit/tools/<tool>/__init__.py
tests/unit/tools/<tool>/test_<tool>_plugin.py
```

### Updated files (paths)

```text
lintro/enums/tool_name.py              # Add to ToolName enum
lintro/tools/core/version_parsing.py   # Add to TOOLS_WITH_SIMPLE_VERSION_PATTERN
lintro/tools/core/version_checking.py  # Add install hints
lintro/_tool_versions.py               # Add version (external tools only)
lintro/tools/manifest.json             # Add tool entry (version MUST match _tool_versions.py)
lintro/cli_utils/commands/doctor.py    # Add to TOOL_COMMANDS for health check
package.json                           # Add version for npm tools (must match _tool_versions.py)
renovate.json                          # Add custom managers for BOTH _tool_versions.py AND manifest.json
pyproject.toml                         # Add parser package
Dockerfile                             # Add to verification step (tool --version)
Dockerfile.tools                       # Add to verification step (tool --version)
scripts/utils/install-tools.sh         # Add installation command (external tools)
scripts/ci/homebrew/templates/lintro.rb.template  # Add depends_on + update caveats (if Homebrew-installable)
```

### Version Consistency (CRITICAL for external tools)

For external tools (not bundled Python packages), versions must be consistent across:

1. **`lintro/_tool_versions.py`** - Source of truth for install-tools.sh
2. **`lintro/tools/manifest.json`** - Must match \_tool_versions.py for
   binary/cargo/rustup tools
3. **`package.json`** - For npm tools, must match \_tool_versions.py
4. **Plugin `min_version`** - In tool definition, should match or be <=
   \_tool_versions.py
5. **`renovate.json`** - Must have custom managers to update BOTH \_tool_versions.py AND
   manifest.json

CI runs `python3 scripts/ci/generate-tool-versions.py --check` on every PR (a single
generator with `--check`, per `/stand-ci` — no verify-sync scripts). It regenerates the
derived version artifacts from `package.json`, `pyproject.toml`, and `TOOL_VERSIONS` in
`lintro/_tool_versions.py`, and exits 1 with a unified diff if `manifest.json` or
`lintro/_generated_versions.py` have drifted.

**PRs will fail if versions drift between these files.** Run the generator locally
(without `--check`) to rewrite the derived files.

Example for npm tool:

```python
# lintro/_tool_versions.py
TOOL_VERSIONS = {
    "oxfmt": "0.27.0",  # Source of truth
}

# lintro/tools/definitions/oxfmt.py
min_version="0.27.0",  # Must match

# package.json
"oxfmt": "^0.27.0"  # Must match major.minor

# renovate.json - add custom managers for BOTH files
{
    "customType": "regex",
    "managerFilePatterns": ["lintro/_tool_versions\\.py"],
    "matchStrings": ["\"oxfmt\":\\s*\"(?<currentValue>[0-9]+\\.[0-9]+\\.[0-9]+)\""],
    "datasourceTemplate": "npm",
    "packageNameTemplate": "oxfmt"
},
{
    "customType": "regex",
    "managerFilePatterns": ["lintro/tools/manifest\\.json"],
    "matchStrings": ["\"name\":\\s*\"oxfmt\"[^}]*\"version\":\\s*\"(?<currentValue>[0-9]+\\.[0-9]+\\.[0-9]+)\""],
    "datasourceTemplate": "npm",
    "packageNameTemplate": "oxfmt"
}
```

### Homebrew Formula (for Homebrew-installable tools)

If the tool is available as a Homebrew formula, add it to the Homebrew formula template:

1. **`scripts/ci/homebrew/templates/lintro.rb.template`** — add `depends_on "<tool>"`
2. **Update caveats** in the same file to list the new tool under the appropriate
   category
3. **Note**: Bundled Python tools (ruff, black, mypy, bandit, yamllint) are excluded
   from
   the Homebrew venv via `generate_resources.py --exclude`. They are installed as separate
   Homebrew formulae and discovered via PATH (`shutil.which`), NOT via `python -m`.
   The `PythonBundledBuilder` in `command_builders.py` handles this automatically.

## Project Context

Lintro is a unified CLI for code linting/formatting. It uses a plugin architecture where
tools are:

1. Defined in `lintro/tools/definitions/<tool>.py` - uses `@register_tool` decorator
2. Parsed by `lintro/parsers/<tool>/<tool>_parser.py` and `<tool>_issue.py`
3. Tested in `tests/unit/` (parser + plugin tests) and `tests/integration/`
4. Have sample violation files in `test_samples/tools/`

---

## Files to Create

### 1. Tool Definition (`lintro/tools/definitions/<tool>.py`)

```python
"""<Tool> tool definition.

<Brief description of what the tool does.>
"""

from __future__ import annotations

import subprocess  # nosec B404 - used safely with shell disabled
from dataclasses import dataclass
from typing import Any

from lintro.enums.tool_type import ToolType
from lintro.models.core.tool_result import ToolResult
from lintro.parsers.<tool>.<tool>_parser import parse_<tool>_output
from lintro.plugins.base import BaseToolPlugin
from lintro.plugins.protocol import ToolDefinition
from lintro.plugins.registry import register_tool

# Constants
<TOOL>_DEFAULT_TIMEOUT: int = 30
<TOOL>_DEFAULT_PRIORITY: int = 50  # Lower = runs first
<TOOL>_FILE_PATTERNS: list[str] = ["*.ext"]


@register_tool
@dataclass
class <Tool>Plugin(BaseToolPlugin):
    """<Tool> plugin for Lintro."""

    @property
    def definition(self) -> ToolDefinition:
        """Return the tool definition."""
        return ToolDefinition(
            name="<tool>",
            description="<One-line description>",
            can_fix=False,  # True if tool supports --fix
            tool_type=ToolType.LINTER,  # | ToolType.FORMATTER, SECURITY, etc.
            file_patterns=<TOOL>_FILE_PATTERNS,
            priority=<TOOL>_DEFAULT_PRIORITY,
            conflicts_with=[],
            native_configs=["<config-file>"],  # e.g., ".eslintrc", "pyproject.toml"
            version_command=["<tool>", "--version"],  # Some tools use "version" not "--version"
            min_version="<min-ver>",
            default_options={
                "timeout": <TOOL>_DEFAULT_TIMEOUT,
            },
            default_timeout=<TOOL>_DEFAULT_TIMEOUT,
        )

    def set_options(self, **kwargs: Any) -> None:
        """Set tool-specific options."""
        super().set_options(**kwargs)

    def _build_command(self) -> list[str]:
        """Build the tool command."""
        return ["<tool>"]

    def check(self, paths: list[str], options: dict[str, object]) -> ToolResult:
        """Check files with <tool>."""
        ctx = self._prepare_execution(paths, options)
        if ctx.should_skip:
            return ctx.early_result  # type: ignore[return-value]

        # Run tool and parse output
        cmd = self._build_command() + ctx.rel_files
        try:
            success, output = self._run_subprocess(cmd, timeout=ctx.timeout, cwd=ctx.cwd)
        except subprocess.TimeoutExpired:
            return ToolResult(
                name=self.definition.name,
                success=False,
                output=f"<Tool> timed out after {ctx.timeout}s",
                issues_count=0,
            )

        issues = parse_<tool>_output(output)

        return ToolResult(
            name=self.definition.name,
            success=success and len(issues) == 0,
            output=output if not success else None,
            issues_count=len(issues),
            issues=issues,
        )

    def fix(self, paths: list[str], options: dict[str, object]) -> ToolResult:
        """<Tool> cannot fix issues."""
        raise NotImplementedError("<Tool> does not support auto-fixing.")
```

### 2. Issue Class (`lintro/parsers/<tool>/<tool>_issue.py`)

```python
"""Issue model for <tool> output."""

from dataclasses import dataclass, field
from typing import ClassVar

from lintro.parsers.base_issue import BaseIssue


@dataclass
class <Tool>Issue(BaseIssue):
    """Represents a <tool> issue.

    Attributes:
        code: Rule code/ID.
        level: Severity level (e.g., "error", "warning").
    """

    # Map non-standard field names to display keys
    # Only needed if your field names differ from: code, severity, fixable, message
    DISPLAY_FIELD_MAP: ClassVar[dict[str, str]] = {
        **BaseIssue.DISPLAY_FIELD_MAP,
        "severity": "level",  # Maps self.level to severity output
    }

    level: str = field(default="error")
    code: str = field(default="")
```

### 3. Parser (`lintro/parsers/<tool>/<tool>_parser.py`)

```python
"""Parser for <tool> output."""

from __future__ import annotations

import re

from lintro.parsers.<tool>.<tool>_issue import <Tool>Issue

# Regex to match tool output format
_LINE_RE: re.Pattern[str] = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.*)$"
)


def parse_<tool>_output(output: str | None) -> list[<Tool>Issue]:
    """Parse <tool> output into issues.

    Args:
        output: Raw stdout/stderr from <tool>.

    Returns:
        List of parsed issues.
    """
    if not output:
        return []

    issues: list[<Tool>Issue] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        issues.append(
            <Tool>Issue(
                file=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col")),
                message=m.group("msg"),
            )
        )
    return issues
```

### 4. Parser `__init__.py` (`lintro/parsers/<tool>/__init__.py`)

```python
"""<Tool> parser package.

Exports issue types and the parse function so imports match ``skills/lintro-verify``.
"""

from lintro.parsers.<tool>.<tool>_issue import <Tool>Issue
from lintro.parsers.<tool>.<tool>_parser import parse_<tool>_output

__all__ = [
    "<Tool>Issue",
    "parse_<tool>_output",
]
```

### 5. Sample Violation File (`test_samples/tools/<category>/<tool>/<tool>_violations.<ext>`)

Create a minimal file that triggers at least one violation from the tool.

### 6. Parser Unit Tests (`tests/unit/parsers/test_<tool>_parser.py`)

See the `test` skill for pytest conventions. Use pytest-style functions, fixtures, and
parametrization.

```python
"""Unit tests for <tool> parser."""

from __future__ import annotations

import pytest
from assertpy import assert_that

from lintro.parsers.<tool>.<tool>_parser import parse_<tool>_output


@pytest.mark.parametrize(
    ("output", "expected_count"),
    [
        pytest.param(None, 0, id="none_input"),
        pytest.param("", 0, id="empty_string"),
        pytest.param("   \n\n  ", 0, id="whitespace_only"),
    ],
)
def test_parse_<tool>_output_empty_cases(output: str | None, expected_count: int) -> None:
    """Parser returns empty list for empty/None input."""
    result = parse_<tool>_output(output)
    assert_that(result).is_length(expected_count)


def test_parse_<tool>_output_single_issue() -> None:
    """Parser extracts single issue correctly."""
    output = "file.ext:10:5: Some error message"
    result = parse_<tool>_output(output)

    assert_that(result).is_length(1)
    assert_that(result[0].file).is_equal_to("file.ext")
    assert_that(result[0].line).is_equal_to(10)
    assert_that(result[0].column).is_equal_to(5)
    assert_that(result[0].message).is_equal_to("Some error message")


def test_parse_<tool>_output_multiple_issues() -> None:
    """Parser handles multiple issues."""
    output = """file1.ext:1:1: First error
file2.ext:20:10: Second error"""
    result = parse_<tool>_output(output)

    assert_that(result).is_length(2)
```

### 7. Plugin Unit Tests (`tests/unit/tools/<tool>/test_<tool>_plugin.py`)

```python
"""Unit tests for <tool> plugin."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from assertpy import assert_that

from lintro.tools.definitions.<tool> import (
    <TOOL>_DEFAULT_TIMEOUT,
    <Tool>Plugin,
)

if TYPE_CHECKING:
    from lintro.models.core.tool_result import ToolResult


@pytest.fixture
def <tool>_plugin() -> <Tool>Plugin:
    """Create a <Tool>Plugin instance with mocked version check."""
    with patch(
        "lintro.plugins.execution_preparation.verify_tool_version",
        return_value=None,
    ):
        return <Tool>Plugin()


# Default options tests

@pytest.mark.parametrize(
    ("option_name", "expected_value"),
    [
        pytest.param("timeout", <TOOL>_DEFAULT_TIMEOUT, id="timeout_default"),
        # Add other default options here
    ],
)
def test_default_options(
    <tool>_plugin: <Tool>Plugin,
    option_name: str,
    expected_value: object,
) -> None:
    """Default options have correct values."""
    assert_that(<tool>_plugin.options.get(option_name)).is_equal_to(expected_value)


# Check method tests

def test_check_success(
    <tool>_plugin: <Tool>Plugin,
    tmp_path: Path,
) -> None:
    """Check returns success when no issues found."""
    test_file = tmp_path / "test.ext"
    test_file.write_text("valid content")

    with patch(
        "lintro.plugins.execution_preparation.verify_tool_version",
        return_value=None,
    ):
        with patch.object(
            <tool>_plugin,
            "_run_subprocess",
            return_value=(True, ""),
        ):
            result = <tool>_plugin.check([str(test_file)], {})

    assert_that(result.success).is_true()
    assert_that(result.issues_count).is_equal_to(0)


def test_check_with_issues(
    <tool>_plugin: <Tool>Plugin,
    tmp_path: Path,
) -> None:
    """Check returns issues when violations found."""
    test_file = tmp_path / "test.ext"
    test_file.write_text("invalid content")

    mock_output = "test.ext:1:1: Some error"

    with patch(
        "lintro.plugins.execution_preparation.verify_tool_version",
        return_value=None,
    ):
        with patch.object(
            <tool>_plugin,
            "_run_subprocess",
            return_value=(False, mock_output),
        ):
            result = <tool>_plugin.check([str(test_file)], {})

    assert_that(result.issues_count).is_greater_than(0)


def test_check_timeout(
    <tool>_plugin: <Tool>Plugin,
    tmp_path: Path,
) -> None:
    """Check handles timeout correctly."""
    test_file = tmp_path / "test.ext"
    test_file.write_text("content")

    with patch(
        "lintro.plugins.execution_preparation.verify_tool_version",
        return_value=None,
    ):
        with patch.object(
            <tool>_plugin,
            "_run_subprocess",
            side_effect=subprocess.TimeoutExpired(cmd=["<tool>"], timeout=30),
        ):
            result = <tool>_plugin.check([str(test_file)], {})

    assert_that(result.success).is_false()
    assert_that(result.output).contains("timed out")


# Fix method tests

def test_fix_raises_not_implemented(<tool>_plugin: <Tool>Plugin) -> None:
    """Fix raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        <tool>_plugin.fix(["."], {})
```

### 8. Plugin Test `__init__.py` (`tests/unit/tools/<tool>/__init__.py`)

```python
"""<Tool> plugin tests."""
```

---

## Files to Update

### 1. Add to ToolName Enum (`lintro/enums/tool_name.py`)

```python
class ToolName(StrEnum):
    # ... existing tools ...
    <TOOL> = auto()  # Add in alphabetical order
```

### 2. Add to Version Parsing (`lintro/tools/core/version_parsing.py`)

For tools with simple version output (just a version number):

```python
TOOLS_WITH_SIMPLE_VERSION_PATTERN: set[ToolName] = {
    # ... existing tools ...
    ToolName.<TOOL>,
}
```

### 3. Add Install Hints (`lintro/tools/core/version_checking.py`)

In the `get_install_hints()` function, add:

```python
hints.update(
    {
        # ... existing hints ...
        "<tool>": (
            f"Install via: <install-command> "
            f"(v{versions.get('<tool>', '<default-version>')}+)"
        ),
    },
)
```

### 4. Update pyproject.toml

Add parser package to `[tool.setuptools]`:

```toml
[tool.setuptools]
packages = [
    # ... existing packages ...
    "lintro.parsers.<tool>",
]
```

Add version to `[tool.lintro.versions]`:

```toml
[tool.lintro.versions]
# ... existing versions ...
<tool> = "<min-version>"
```

### 5. Add to manifest.json (`lintro/tools/manifest.json`)

Add a new entry to the `tools` array (in alphabetical order):

```json
{
  "name": "<tool>",
  "version": "<version>",
  "install": { "type": "<pip|npm|cargo|binary|rustup>" },
  "tier": "tools"
}
```

For npm tools, include the package name and binary:

```json
{
  "name": "<tool>",
  "version": "<version>",
  "install": { "type": "npm", "package": "<npm-package>", "bin": "<binary>" },
  "tier": "tools"
}
```

### 6. Add to doctor health check (`lintro/cli_utils/commands/doctor.py`)

Add the tool's version command to the `TOOL_COMMANDS` dict (in alphabetical order):

```python
TOOL_COMMANDS: dict[str, list[str]] = {
    # ... existing entries ...
    "<tool>": ["<tool>", "--version"],
}
```

This ensures `lintro doctor` can verify the tool is installed and report its version.

### 7. Add to Docker verification steps

**`Dockerfile`** — Add to the root-user verification block:

```dockerfile
RUN echo "Verifying tools..." && \
    # ... existing tools ...
    <tool> --version && \
    echo "All tools verified!"
```

And to the non-root user verification block:

```dockerfile
RUN echo "Verifying tools as non-root user..." && \
    # ... existing tools ...
    <tool> --version && \
    echo "All tools verified for non-root user!"
```

**`Dockerfile.tools`** — Add to the verification block:

```dockerfile
RUN echo "=== Verifying all tools ===" && \
    # ... existing tools ...
    echo "<tool>: $(<tool> --version)" && \
    echo "=== All tools verified! ==="
```

### 8. Add to install-tools.sh (`scripts/utils/install-tools.sh`)

Add the installation command for the new tool. The install method depends on tool type:

- **pip tools**: `uv pip install "<tool>==$VERSION"`
- **npm tools**: `bun add -g "<package>@$VERSION"`
- **cargo tools**: `cargo install "<crate>" --version "$VERSION"`
- **binary tools**: Download from GitHub releases

Follow the existing patterns in `install-tools.sh` for the appropriate tool type.

---

## ToolType Options

```python
ToolType.LINTER          # Code quality checker
ToolType.FORMATTER       # Code formatter
ToolType.TYPE_CHECKER    # Type checking (mypy)
ToolType.DOCUMENTATION   # Doc checker (darglint)
ToolType.SECURITY        # Security scanner (bandit, semgrep, gitleaks)
ToolType.INFRASTRUCTURE  # IaC linter (hadolint, actionlint)
ToolType.TEST_RUNNER     # Test framework (pytest)
```

Can be combined: `ToolType.LINTER | ToolType.FORMATTER`

---

## Common Gotchas

1. **Version command variations**: Some tools use `version` instead of `--version`
   (e.g., `gitleaks version`). Check the tool's CLI.

2. **ToolResult invariant for fix operations**: When returning fix results, must
   satisfy:

   ```text
   initial_issues_count = fixed_issues_count + remaining_issues_count
   ```

3. **Test mocking patterns**:

   ```python
   # Mock version check (use this in most tests)
   patch("lintro.plugins.execution_preparation.verify_tool_version", return_value=None)

   # Mock subprocess calls
   patch.object(plugin, "_run_subprocess", return_value=(True, "output"))
   patch.object(plugin, "_run_subprocess", side_effect=subprocess.TimeoutExpired(...))
   ```

4. **File discovery**: `_prepare_execution()` handles file filtering by `file_patterns`.
   Use `ctx.rel_files` for the filtered list.

5. **Subprocess safety**: Always use list args, never `shell=True`. Add `# nosec B404`
   comment on subprocess import.

6. **Return early**: If `ctx.should_skip` is True, return `ctx.early_result`
   immediately.

7. **Parser function naming**: Must be `parse_<tool>_output(output: str | None) ->
list[<Tool>Issue]`.

8. **Issue class**: Must inherit from `BaseIssue`. Use `DISPLAY_FIELD_MAP` for custom
   field name mappings.

---

## Deprecated Patterns to Avoid

- Do NOT create tool-specific formatters (use unified formatter)
- Do NOT modify `lintro/tools/tool_enum.py` (deleted - registry is automatic)
- Do NOT modify `lintro/tools/core/tool_base.py` (deleted - use BaseToolPlugin)

---

## Verification Checklist

After adding the tool:

- [ ] `lintro tools` shows the new tool
- [ ] `lintro check --tools <tool> .` runs without error
- [ ] `lintro doctor` shows the tool with correct version (no "No cmd defined")
- [ ] Tool detects violations in sample file
- [ ] Parser unit tests pass: `pytest tests/unit/parsers/test_<tool>_parser.py -v`
- [ ] Plugin unit tests pass: `pytest tests/unit/tools/<tool>/ -v`
- [ ] Coverage >80% on new code: `pytest --cov=lintro/parsers/<tool>
--cov=lintro/tools/definitions/<tool>`
- [ ] No linting errors: `lintro fmt && lintro chk`
- [ ] Version artifacts in sync: `python3 scripts/ci/generate-tool-versions.py --check`
- [ ] Tool added to `Dockerfile` verification step (both root and non-root)
- [ ] Tool added to `Dockerfile.tools` verification step
- [ ] Tool added to `install-tools.sh` (external tools only)
- [ ] Tool added to `lintro/tools/manifest.json` (version matches \_tool_versions.py)
- [ ] Renovate managers added for BOTH `_tool_versions.py` and `manifest.json`
- [ ] Homebrew formula updated with `depends_on` + caveats (if Homebrew-installable)
- [ ] Docker image builds successfully: `docker build -t py-lintro:test .`

---

## Reference Examples

See existing implementations for reference:

- **Simple tool (no fix)**: `lintro/tools/definitions/actionlint.py`,
  `lintro/tools/definitions/hadolint.py`
- **Tool with fix support**: `lintro/tools/definitions/ruff.py`,
  `lintro/tools/definitions/black.py`
- **Security scanner**: `lintro/tools/definitions/bandit.py`,
  `lintro/tools/definitions/semgrep.py`
- **Shell tools**: `lintro/tools/definitions/shellcheck.py`,
  `lintro/tools/definitions/shfmt.py`
