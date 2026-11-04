"""The complete committed resolution lock."""

from dataclasses import dataclass
from typing import Any

from ai_skills_engine.lockmodel.builder import Builder
from ai_skills_engine.lockmodel.locked_package import LockedPackage
from ai_skills_engine.lockmodel.locked_vendor import LockedVendor
from ai_skills_engine.lockmodel.manifest_record import ManifestRecord

LOCK_VERSION = 1


@dataclass(frozen=True)
class Lock:
    """Everything needed to rebuild the artifacts byte for byte.

    Attributes:
        builder: Builder identity.
        manifest: Manifest and local-input digests.
        vendors: Resolved vendor sources, sorted by alias.
        packages: Built packages, sorted by ID.
    """

    builder: Builder
    manifest: ManifestRecord
    vendors: tuple[LockedVendor, ...]
    packages: tuple[LockedPackage, ...]

    def to_json(self) -> dict[str, Any]:
        """Encode the lock with its field names.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "lockVersion": LOCK_VERSION,
            "builder": self.builder.to_json(),
            "manifest": self.manifest.to_json(),
            "vendors": [
                item.to_json() for item in sorted(self.vendors, key=lambda v: v.id)
            ],
            "packages": [
                item.to_json() for item in sorted(self.packages, key=lambda p: p.id)
            ],
        }
