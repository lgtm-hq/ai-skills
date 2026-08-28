"""Vendor registry record."""

from __future__ import annotations

from dataclasses import dataclass

from vendor_registry.vendor_plugin import VendorPlugin


@dataclass(frozen=True)
class Vendor:
    """One SHA-pinned third-party skill vendor.

    ``display_ref`` is the optional consumer-facing pin (``displayRef``).
    Bake uses it as the plugin version when it is a tag; floating pins
    such as ``latest`` fall back to the short SHA.
    """

    id: str
    repo: str
    sha: str
    skill_roots: tuple[str, ...]
    license: str
    homepage: str
    display_ref: str | None = None
    plugins: tuple[VendorPlugin, ...] = ()
