"""Immutable, deterministic build-plane selection result."""

import json
from dataclasses import asdict, dataclass

from ai_skills_engine.selection.diagnostic import SelectionDiagnostic
from ai_skills_engine.selection.entry import SelectionEntry


@dataclass(frozen=True)
class SelectionResult:
    """Complete explain surface; no lock, deduplication or installation effects."""

    capabilities: tuple[SelectionEntry, ...]
    resources: tuple[SelectionEntry, ...]
    diagnostics: tuple[SelectionDiagnostic, ...]
    dangling_related: tuple[tuple[str, str], ...] = ()
    namespace: tuple[tuple[str, str, tuple[str, ...]], ...] = ()

    @property
    def valid(self) -> bool:
        """Whether the result can be consumed by a later lock/build stage.

        Returns:
            False if any error was retained.
        """
        return not any(not item.warning for item in self.diagnostics)

    def to_json(self) -> str:
        """Serialize the full trace with stable keys and a trailing newline.

        Returns:
            Machine-readable explain output.
        """
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"
