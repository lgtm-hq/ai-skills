"""The vendor and revisions a re-pin report describes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VendorPin:
    """Identity of a re-pinned vendor and its old and new revisions.

    Attributes:
        id: Consumer vendor alias.
        repo: ``owner/name`` repository.
        publisher: Publisher namespace of the vendor's packages.
        display_ref: Consumer-facing ref, ``latest`` when unset.
        old_sha: Baseline revision, or None for a newly added vendor.
        new_sha: Target revision.
    """

    id: str
    repo: str
    publisher: str
    display_ref: str
    old_sha: str | None
    new_sha: str
