"""Per-plugin copy accounting before any selected file is copied or parsed."""

from dataclasses import dataclass

from ai_skills_engine.registry.ingest_checks import fail_limit
from ai_skills_engine.registry.ingest_limits import IngestLimits


@dataclass
class IngestBudget:
    """Count selected source bytes before copying into a private staging tree."""

    vendor: str
    limits: IngestLimits
    total: int = 0

    def reserve(self, *, size: int, path: str) -> None:
        """Reject a file or aggregate overflow before copy allocation.

        Args:
            size: Source size observed through an open descriptor.
            path: Source path for diagnostics.
        """
        for key, actual, maximum in (
            ("fileBytes", size, self.limits.file_bytes),
            ("pluginBytes", self.total + size, self.limits.plugin_bytes),
        ):
            if actual > maximum:
                fail_limit(vendor=self.vendor, path=path, limit=key, maximum=maximum)
        self.total += size
