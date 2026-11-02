"""Private source observations retained until explicit edges can be resolved."""

from dataclasses import dataclass
from pathlib import Path

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.manifest.capability import Capability as Declaration


@dataclass(frozen=True)
class PendingCapability:
    """Observed capability, physical source, and original explicit selectors."""

    capability: Capability
    source: Path
    declaration: Declaration
