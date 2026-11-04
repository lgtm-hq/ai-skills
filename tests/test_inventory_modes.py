"""Canonical payload modes survive real acquisition without losing exec identity."""

import json
import os
import shutil
import stat
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.inventory import load_inventory
from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.resource_record import Resource

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize(
    ("mode", "canonical"),
    [
        (0o600, 0o644),
        (0o644, 0o644),
        (0o664, 0o644),
        (0o660, 0o644),
        (0o674, 0o644),
        (0o645, 0o644),
        (0o675, 0o644),
        (0o1764, None),
        (0o700, 0o755),
        (0o751, 0o755),
        (0o775, 0o755),
        (0o4755, None),
    ],
)
def test_real_tarball_acquisition_preserves_canonical_modes(
    inventory_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
    canonical: int | None,
) -> None:
    """Only owner execution is Git identity; tar's data filter agrees with it."""
    from inventory_helpers import inventory_snapshot, inventory_tarball

    root, vendor = inventory_repo
    targets = [
        vendor / "skills/help/danger.py",
        vendor / "agents/reviewer.md",
        vendor / "NOTICE.md",
        root / "shared/guide.md",
    ]
    for path in targets:
        path.chmod(mode)
    # Matched ordinary and executable controls remain in the same skill payload.
    (vendor / "skills/help/SKILL.md").chmod(0o664)
    control = vendor / "skills/help/control.py"
    control.write_bytes(targets[0].read_bytes())
    control.chmod(0o775)
    before = inventory_snapshot(root, vendor)
    archive: bytes = inventory_tarball(vendor)
    requests: list[str] = []

    def download(*, host: str, path: str, **kwargs: object) -> bytes:
        """Stub only HTTP bytes; retain the real fetch, extraction and validation."""
        requests.append(f"{host}{path}")
        return archive

    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", download)
    if canonical is None:
        # #572 rejects special bits before the old data-filter normalization.
        for kwargs in ({"vendor_roots": {"vendor": vendor}}, {"fetch_vendors": True}):
            with pytest.raises(ValueError, match="special mode bits"):
                load_inventory(root, **kwargs)
        assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)
        return
    offline = load_inventory(root, vendor_roots={"vendor": vendor})
    fetched = load_inventory(root, fetch_vendors=True)
    assert_that(requests).is_length(1)
    assert_that(requests[0]).contains("0123456789abcdef0123456789abcdef01234567")
    assert_that([item for item in fetched.diagnostics if not item.warning]).is_empty()
    assert_that(fetched.capabilities).is_equal_to(offline.capabilities)
    assert_that(fetched.resources).is_equal_to(offline.resources)
    observations: tuple[Capability | Resource, ...] = (
        *fetched.capabilities,
        *fetched.resources,
    )
    records = {str(item.id): item for item in observations}
    helper = records["vendor/tools:skill/helper"]
    modes = {str(item.path): item.mode for item in helper.payload}
    assert_that(modes).is_equal_to(
        {"SKILL.md": 0o644, "danger.py": canonical, "control.py": 0o755}
    )
    assert_that(helper.payload[1].sha256).is_equal_to(helper.payload[2].sha256)
    for identity in (
        "vendor/tools:specialist/reviewer",
        "vendor/tools:resource/notice",
        "fixture/tools:resource/guide",
    ):
        assert_that(records[identity].payload[0].mode).is_equal_to(canonical)
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)
    assert_that(list(root.rglob("MUST-NOT-EXECUTE"))).is_empty()
    assert_that(list(vendor.rglob("MUST-NOT-EXECUTE"))).is_empty()


def test_umask_snapshots_have_identical_public_inventory_json(
    inventory_repo: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Snapshots created under 002 and 022 retain equal public JSON and digests."""
    from inventory_helpers import inventory_snapshot

    root, vendor = inventory_repo
    (vendor / "skills/help/danger.py").chmod(0o775)
    snapshots = []
    for mask in (0o002, 0o022):
        destination = tmp_path / f"umask-{mask:o}"

        def checkout(source: str, target: str, mask: int = mask) -> str:
            """Create fresh bytes under this umask, preserving Git exec identity."""
            incoming, outgoing = Path(source), Path(target)
            outgoing.write_bytes(incoming.read_bytes())
            if incoming.stat().st_mode & stat.S_IXUSR:
                outgoing.chmod(0o777 & ~mask)
            return target

        previous = os.umask(mask)
        try:
            for tree in (root, vendor):
                shutil.copytree(
                    src=tree, dst=destination / tree.name, copy_function=checkout
                )
        finally:
            os.umask(previous)
        snapshots.append((destination / root.name, destination / vendor.name))
    outputs = []
    for publisher, snapshot in snapshots:
        before = inventory_snapshot(publisher, snapshot)
        assert_that(
            cli.main(
                [
                    "inventory",
                    "--repo-root",
                    str(publisher),
                    "--vendor-root",
                    f"vendor={snapshot}",
                    "--json",
                ]
            )
        ).is_zero()
        outputs.append(capsys.readouterr().out)
        assert_that(inventory_snapshot(publisher, snapshot)).is_equal_to(before)
    assert_that(outputs[0]).is_equal_to(outputs[1])
    modes = [
        stat.S_IMODE((snapshot / "skills/help/SKILL.md").stat().st_mode)
        for _, snapshot in snapshots
    ]
    assert_that(modes).is_equal_to([0o664, 0o644])
    assert_that(json.loads(outputs[0])["capabilities"]).is_not_empty()


@pytest.mark.parametrize(
    ("relative", "identity"),
    [
        ("skills/help/danger.py", "vendor/tools:skill/helper"),
        ("agents/reviewer.md", "vendor/tools:specialist/reviewer"),
        ("NOTICE.md", "vendor/tools:resource/notice"),
        ("../publisher/shared/guide.md", "fixture/tools:resource/guide"),
    ],
)
def test_public_loader_distinguishes_bytes_and_owner_execute_bit(
    inventory_repo: tuple[Path, Path], relative: str, identity: str
) -> None:
    """Permission noise is inert; byte changes and exec identity change the digest."""
    root, vendor = inventory_repo
    target = vendor / relative

    def digest() -> str:
        """Observe the actual capability or resource through the public loader."""
        inventory = load_inventory(root, vendor_roots={"vendor": vendor})
        records: tuple[Capability | Resource, ...] = (
            *inventory.capabilities,
            *inventory.resources,
        )
        return next(item.tree_digest for item in records if str(item.id) == identity)

    target.chmod(0o664)
    ordinary = digest()
    for mode in (0o644, 0o600, 0o675):
        target.chmod(mode)
        assert_that(digest()).is_equal_to(ordinary)
    target.chmod(0o775)
    executable = digest()
    assert_that(executable).is_not_equal_to(ordinary)
    for mode in (0o755, 0o751, 0o700):
        target.chmod(mode)
        assert_that(digest()).is_equal_to(executable)
    target.write_bytes(target.read_bytes() + b"\n# changed bytes\n")
    assert_that(digest()).is_not_equal_to(executable)
