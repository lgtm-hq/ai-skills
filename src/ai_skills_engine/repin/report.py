"""Complete deterministic re-pin delta for one vendor."""

from dataclasses import dataclass

from ai_skills_engine.repin.change import Change
from ai_skills_engine.repin.drift import Drift
from ai_skills_engine.repin.selector_status import SelectorStatus
from ai_skills_engine.repin.vendor_pin import VendorPin
from ai_skills_engine.semver_advice_result import SemverAdvice


@dataclass(frozen=True)
class RepinReport:
    """Every section of a re-pin PR body, already sorted.

    Attributes:
        pin: Vendor identity and revisions.
        status: ``updated``, ``unchanged``, ``failed`` or ``declined``.
        action_required: Failures a human must fix, in report order.
        semver: Advisory level and reasons, None when nothing was compared.
        capabilities: Added, removed, changed and declared-renamed capabilities.
        unapplied_moves: Identical content at a new ID without a declaration.
        files: Per-capability file deltas (``+``, ``-``, ``~``).
        resources: Standalone resource deltas.
        lineage: Lineage changes other than revision and digest bumps.
        legal: License and notice deltas.
        coverage: Capability counts plus newly uncovered/covered skill paths.
        collisions: New and resolved collision diagnostics.
        selectors: Consumer selectors with their match counts.
        drift: Path-drift reconciliations and failures.
        digests: Package ``treeDigest`` and ``artifactDigest`` changes.
    """

    pin: VendorPin
    status: str
    action_required: tuple[str, ...] = ()
    semver: SemverAdvice | None = None
    capabilities: tuple[Change, ...] = ()
    unapplied_moves: tuple[Change, ...] = ()
    files: tuple[Change, ...] = ()
    resources: tuple[Change, ...] = ()
    lineage: tuple[Change, ...] = ()
    legal: tuple[Change, ...] = ()
    coverage: tuple[Change, ...] = ()
    collisions: tuple[Change, ...] = ()
    selectors: tuple[SelectorStatus, ...] = ()
    drift: tuple[Drift, ...] = ()
    digests: tuple[Change, ...] = ()

    @property
    def failed(self) -> bool:
        """Whether the re-pin must stay red until a human fixes it.

        Returns:
            True when any action is required.
        """
        return bool(self.action_required)
