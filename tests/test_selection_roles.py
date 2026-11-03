"""Actual selection-boundary controls for typed rejected role eligibility."""

from dataclasses import replace
from pathlib import Path

import pytest
from assertpy import assert_that
from selection_helpers import PREFIX
from test_selection_revision import run_plan

from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.identity import Role
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.policy import Policy
from ai_skills_engine.selection import select

pytest_plugins = ["inventory_helpers"]


def role_policy_case(
    *, root: Path, role: str, rejected: bool, allowed: bool, control: str
) -> tuple[str, int, tuple[str, ...]]:
    """Prepare genuine declared configuration payloads and consumer role controls.

    Args:
        root: Copied publisher fixture.
        role: Existing integration or lifecycle declaration.
        rejected: Remove that declaration's actual payload.
        allowed: Permit the target role alongside skills.
        control: Default, explicit selection/exclusion/narrowing or dependency case.

    Returns:
        Target identity, expected status and shortest dependency witness.
    """
    document = read_document(root / "ai-skills.yaml")
    package = document["packages"][0]
    record = next(item for item in package["capabilities"] if item.get("role") == role)
    target = f"fixture/tools:{role}/{record['id']}"
    document["policy"] = {"roles": ["skill", role] if allowed else ["skill"]}
    if rejected:
        (root / record["path"]).unlink()
    if control != "default":
        package["include"] = [PREFIX + "stable"]
    if control in {"selected", "excluded"}:
        package["include"].append(target)
    if control == "excluded":
        package["exclude"] = [target]
    chain: tuple[str, ...] = ()
    if control in {"required", "transitive"}:
        document["vendors"][0]["include"] = []
        helper = document["vendors"][0]["mapping"]["packages"][0]["capabilities"][
            "help"
        ]
        helper["requires"] = [target]
        chain = (PREFIX + "stable", "vendor/tools:skill/helper", target)
        if control == "required":
            package["capabilities"][0]["requires"].append(target)
            chain = (PREFIX + "stable", target)
    retained = control not in {"excluded", "narrow"}
    expected = int((not allowed and bool(chain)) or (allowed and rejected and retained))
    (root / "ai-skills.yaml").write_text(dump_document(document))
    (root / "ai-skills.lock").write_bytes(b"unchanged lock\n")
    (root / "installed-generation").write_bytes(b"unchanged generation\n")
    return target, expected, chain


@pytest.mark.parametrize("role", ["integration", "lifecycle"])
@pytest.mark.parametrize("rejected", [False, True], ids=["valid", "rejected"])
@pytest.mark.parametrize("allowed", [False, True], ids=["disallowed", "allowed"])
@pytest.mark.parametrize(
    "control", ["default", "selected", "excluded", "narrow", "required", "transitive"]
)
def test_plan_role_eligibility_precedes_closure(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    rejected: bool,
    allowed: bool,
    control: str,
) -> None:
    """Payload validity cannot bypass roles, trim dependencies or weaken inventory."""
    root, vendor = inventory_repo
    target, expected, chain = role_policy_case(
        root=root, role=role, rejected=rejected, allowed=allowed, control=control
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        """Reject any vendor execution or acquisition during actual planning."""
        pytest.fail("Role selection must not execute code or acquire inputs")

    monkeypatch.setattr("subprocess.run", forbidden)
    inventory = load_inventory(
        root, vendor_roots={"vendor": vendor}, selection_candidates=True
    )
    payload_errors = [
        item
        for item in inventory.diagnostics
        if item.location == target and item.code == "inventory.invalid-payload"
    ]
    assert_that(bool(payload_errors)).is_equal_to(rejected)
    if rejected:
        assert_that(inventory.rejected).contains(CapabilityId.parse(target))
        assert_that(payload_errors[0].warning).is_false()
    output = run_plan(root=root, vendor=vendor, capsys=capsys, expected=expected)
    entry = next(item for item in output["capabilities"] if item["id"] == target)
    state = "unsupported" if not allowed else "selected"
    if allowed and control in {"excluded", "narrow"}:
        state = "excluded"
    elif allowed and chain:
        state = "pulled-in"
    assert_that(entry["state"]).is_equal_to(state)
    if not allowed:
        assert_that(entry["reason"]).contains("policy.roles")
    codes = [item["code"] for item in output["diagnostics"]]
    assert_that(codes).does_not_contain("selection.selector-unmatched")
    if chain:
        code = (
            "selection.required-unsupported"
            if not allowed
            else "selection.required-missing"
        )
        if not allowed or rejected:
            finding = next(
                item for item in output["diagnostics"] if item["code"] == code
            )
            assert_that(finding["chain"]).is_equal_to(list(chain))
            assert_that(finding["fix"]).is_not_empty()
    assert_that("inventory.invalid-payload" in codes).is_equal_to(
        allowed and rejected and control not in {"excluded", "narrow"}
    )
    guide = next(
        item
        for item in output["resources"]
        if item["id"] == "fixture/tools:resource/guide"
    )
    assert_that(guide["state"]).is_equal_to("pulled-in")


@pytest.mark.parametrize("rejected", [False, True], ids=["valid", "rejected"])
def test_role_veto_preserves_evidenced_origin_deny_precedence(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    rejected: bool,
) -> None:
    """Origin vetoes outrank roles only when actual origin evidence is available."""
    root, vendor = inventory_repo
    target, _, _ = role_policy_case(
        root=root,
        role="integration",
        rejected=rejected,
        allowed=False,
        control="excluded",
    )
    document = read_document(root / "ai-skills.yaml")
    document["policy"]["deny"] = {"origins": ["github.com/fixture/catalog"]}
    (root / "ai-skills.yaml").write_text(dump_document(document))
    output = run_plan(root=root, vendor=vendor, capsys=capsys, expected=0)
    entry = next(item for item in output["capabilities"] if item["id"] == target)
    assert_that(entry["state"]).is_equal_to("unsupported" if rejected else "denied")


@pytest.mark.parametrize(
    "code",
    [
        "inventory.invalid-payload",
        "inventory.duplicate-id",
        "inventory.vendor-unavailable",
    ],
)
@pytest.mark.parametrize(
    "known", [False, True], ids=["unknown-identity", "rejected-id"]
)
def test_role_veto_keeps_structural_acquisition_and_unknown_identity_errors(
    inventory_repo: tuple[Path, Path], code: str, known: bool
) -> None:
    """Typed candidates alone permit payload trimming; other failures remain fatal."""
    root, vendor = inventory_repo
    target, _, _ = role_policy_case(
        root=root, role="integration", rejected=True, allowed=False, control="default"
    )
    inventory = load_inventory(
        root, vendor_roots={"vendor": vendor}, selection_candidates=True
    )
    identity = target if known else "fixture/tools:integration/unknown"
    result = select(
        replace(
            inventory,
            diagnostics=(*inventory.diagnostics, Diagnostic(code, identity, "failure")),
        ),
        policy=Policy(roles=(Role.SKILL,)),
    )
    assert_that(result.valid).is_equal_to(known and code == "inventory.invalid-payload")
    matches = [
        item
        for item in result.diagnostics
        if item.code == code and item.location == identity
    ]
    assert_that(bool(matches)).is_equal_to(
        not (known and code == "inventory.invalid-payload")
    )
