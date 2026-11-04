"""Aggregate accounting shared by independent declaration scans in one package."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IngestScanBudget:
    """Count each physical payload path once, including rejected scan attempts."""

    total: int = 0
    sizes: dict[Path, int] = field(default_factory=dict)

    def observe(self, *, path: Path, size: int) -> None:
        """Reserve newly observed bytes without double counting overlapping roots.

        Args:
            path: Physical payload file, already checked by the safe tree boundary.
            size: Size observed before or after bounded reading.
        """
        previous = self.sizes.get(path, 0)
        self.total += max(0, size - previous)
        self.sizes[path] = max(previous, size)
