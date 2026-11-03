"""Actual installed-wheel provenance, schema-resource and public CLI controls."""

import json
from pathlib import Path

import pytest
from assertpy import assert_that
from inventory_helpers import snapshot
from provenance_helpers import change_policy, missing_copy, unbound_copy
from test_manifest_wheel import _run, _venv_executable

from ai_skills_engine import cli

pytest_plugins = ["test_manifest_wheel"]


@pytest.mark.parametrize(
    "control", ["denied", "missing", "accepted", "unverifiable", "unbound-copy"]
)
def test_installed_plan_provenance_matches_source(
    installed_command: Path,
    provenance_repo: Path,
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Installed/source text and JSON agree, with all input bytes and modes intact."""
    root = provenance_repo
    if control in {"missing", "accepted"}:
        missing_copy(root=root, statement=True)
        change_policy(root=root / "z", accept=control == "accepted")
    elif control == "unverifiable":
        change_policy(root=root / "z")
        path = root / "y/ai-skills.lineage.json"
        records = json.loads(path.read_text())
        records[0]["lineage"][-1]["rev"] = "c" * 40
        path.write_text(json.dumps(records))
    elif control == "unbound-copy":
        change_policy(root=root / "z")
        unbound_copy(root)
    expected = 0 if control == "accepted" else 1
    (root / "z/ai-skills.lock").write_bytes(b"preserved lock\n")
    (root / "z/installed-generation").write_bytes(b"preserved generation\n")
    before = snapshot(root)
    operands = [
        "--repo-root",
        str(root / "z"),
        "--vendor-root",
        f"y={root / 'y'}",
        "--vendor-root",
        f"y/x={root / 'x'}",
    ]
    for command in (["plan", "--json"], ["plan"]):
        installed = _run(
            args=[str(installed_command), *command, *operands],
            cwd=root.parent,
            expected=expected,
        )
        assert_that(cli.main([*command, *operands])).is_equal_to(expected)
        source = capsys.readouterr()
        assert_that((installed.stdout, installed.stderr)).is_equal_to(
            (source.out, source.err)
        )
        repeated = _run(
            args=[str(installed_command), *command, *operands],
            cwd=root.parent,
            expected=expected,
        )
        assert_that(repeated.stdout).is_equal_to(installed.stdout)
        if control == "unbound-copy":
            assert_that(installed.stdout).contains("inventory.undeclared-resource")
    assert_that(snapshot(root)).is_equal_to(before)


def test_installed_schema_resource_is_bound_to_the_wheel(
    installed_command: Path, tmp_path: Path
) -> None:
    """Installed provenance and schema resolve within the wheel outside the checkout."""
    environment = installed_command.parent.parent
    probe = _run(
        args=[
            str(_venv_executable(environment, "python")),
            "-I",
            "-c",
            (
                "import json; from ai_skills_engine.provenance import ingest; "
                "print(json.dumps([ingest.__file__, ingest.schema()]))"
            ),
        ],
        cwd=tmp_path,
    )
    path, schema = json.loads(probe.stdout)
    assert_that(Path(path).is_relative_to(environment)).is_true()
    assert_that(schema["properties"]).contains("lineage", "id")
    assert_that(schema["properties"]["lineage"]["minItems"]).is_equal_to(1)
