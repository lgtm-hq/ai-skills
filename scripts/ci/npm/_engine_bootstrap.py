"""Bootstrap checkout shims through one boundary outside the engine package.

This lives beside the deepest shim so direct script execution can import it
there, while root-level scripts import it through the ``ci.npm`` namespace.
Only checkout launchers use this path setup. Installed CLI and engine imports
remain ordinary package imports, with one canonical module identity.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _bind_checkout_source() -> None:
    """Prefer checkout imports without replacing any cached engine identities.

    Raises:
        RuntimeError: If a cached engine module belongs to another source.
    """
    source = Path(__file__).resolve().parents[3] / "src"
    for name, cached in sys.modules.copy().items():
        if name != "ai_skills_engine" and not name.startswith("ai_skills_engine."):
            continue
        expected = source.joinpath(*name.split("."))
        package = expected.is_dir()
        expected_file = (
            expected / "__init__.py" if package else expected.with_suffix(".py")
        )
        origin = getattr(cached, "__file__", None)
        search_paths = tuple(
            Path(path).resolve() for path in getattr(cached, "__path__", ())
        )
        if (
            origin is None
            or Path(origin).resolve() != expected_file
            or search_paths != ((expected,) if package else ())
        ):
            msg = (
                f"Cached engine module {name!r} is incompatible with "
                f"checkout {source}; "
                "run the shim in a fresh Python process."
            )
            raise RuntimeError(msg)
    # Membership alone does not establish precedence over another installation.
    sys.path[:] = [str(source), *(entry for entry in sys.path if entry != str(source))]


def run(module: str) -> int:
    """Load this checkout's engine and invoke one compatibility entry point.

    Args:
        module: Fully qualified engine module exposing ``main``.

    Returns:
        The entry point's exit status.

    Raises:
        RuntimeError: If cached engine modules conflict with this checkout.
        ValueError: If the module is not a supported compatibility entry point.
    """
    _bind_checkout_source()
    # Import only the selected implementation. In particular, manifest backfills
    # must stay stdlib-only even though other commands need runtime dependencies.
    match module:
        case "ai_skills_engine.generate.skills_manifest":
            from ai_skills_engine.generate.skills_manifest import main
        case "ai_skills_engine.generate.agents_md":
            from ai_skills_engine.generate.agents_md import main
        case "ai_skills_engine.generate.marketplace":
            from ai_skills_engine.generate.marketplace import main
        case "ai_skills_engine.generate.readme":
            from ai_skills_engine.generate.readme import main
        case "ai_skills_engine.bake.vendor_indexes":
            from ai_skills_engine.bake.vendor_indexes import main
        case "ai_skills_engine.bake.vendor_plugins":
            from ai_skills_engine.bake.vendor_plugins import main
        case "ai_skills_engine.vendors.manage":
            from ai_skills_engine.vendors.manage import main
        case "ai_skills_engine.vendors.repin":
            from ai_skills_engine.vendors.repin import main
        case "ai_skills_engine.validate_skills":
            from ai_skills_engine.validate_skills import main
        case "ai_skills_engine.package_sync":
            from ai_skills_engine.package_sync import main
        case _:
            msg = f"Unknown compatibility module: {module}"
            raise ValueError(msg)
    return main()
