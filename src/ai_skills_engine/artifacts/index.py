"""Group resolved capability/resource metadata into the schema contract."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ai_skills_engine.artifacts.format import (
    ARTIFACT_FORMAT,
    Files,
    digest,
    files_digest,
    validate_index,
)
from ai_skills_engine.artifacts.snapshot import package_version


def build_index(
    *,
    records: list[dict[str, Any]],
    resource_records: list[dict[str, Any]],
    files: Files,
    snapshots: Mapping[tuple[str, str | None], tuple[Path, dict[str, Any]]],
    api_version: str,
    engine_version: str,
    root_package: str | None,
) -> dict[str, Any]:
    """Group already resolved capability records without embedding tar digests.

    Args:
        records: Resolved capability metadata actually present.
        resource_records: Complete standalone resources actually present.
        files: Actual payload and legal bytes, excluding index.json.
        snapshots: Bound version metadata.
        api_version: Manifest's independent API version.
        engine_version: Builder distribution version.
        root_package: Primary package for one tar; None for the catalog index.

    Returns:
        Schema-validated artifact index.
    """
    packages = []
    for package in sorted(
        {item["package"] for item in records}
        | {item["id"].split(":", 1)[0] for item in resource_records}
    ):
        prefix = "packages/" + package + "/"
        payload = {
            path: value for path, value in files.items() if path.startswith(prefix)
        }
        packages.append(
            {
                "id": package,
                "version": package_version(
                    publisher=package.split("/", 1)[0], snapshots=snapshots
                ),
                "treeDigest": files_digest(payload),
                "capabilities": [
                    item for item in records if item["package"] == package
                ],
                "resources": [
                    item
                    for item in resource_records
                    if item["id"].split(":", 1)[0] == package
                ],
            }
        )
    index = {
        "artifactFormat": ARTIFACT_FORMAT,
        "engineVersion": engine_version,
        "apiVersion": api_version,
        "rootPackage": root_package,
        "packages": packages,
        "legalFiles": [
            {"path": path, "digest": digest(data)}
            for path, (data, _mode) in sorted(files.items())
            if path == "NOTICE.md" or path.startswith("LICENSES/")
        ],
    }
    validate_index(index)
    return index
