"""Map the gateway's ``--skill``/``--bundle``/``--vendor`` to package selection.

A plugin ID names one package: either its qualified ``publisher/package`` ID or
the unique package whose second segment equals it (``git-pr`` selects
``lgtm-hq/git-pr``). A vendor ID selects every package that vendor publishes.
"""

from collections.abc import Sequence

from ai_skills_engine.install.errors import InstallError


def _plugin(plugin: str, packages: Sequence[str]) -> str:
    """Resolve one plugin ID to exactly one catalog package.

    Args:
        plugin: Legacy plugin ID or qualified package ID.
        packages: Catalog package IDs.

    Returns:
        Package ID.

    Raises:
        InstallError: If the ID matches no package or several.
    """
    if plugin in packages:
        return plugin
    matches = [item for item in packages if item.split("/", 1)[1] == plugin]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise InstallError(
            f"ambiguous plugin {plugin!r}: use one of {', '.join(sorted(matches))}"
        )
    raise InstallError(f"Unknown plugin: {plugin}")


def select_packages(
    *,
    packages: Sequence[str],
    skills: Sequence[str],
    bundle: str | None,
    vendor: str | None,
) -> tuple[str, ...]:
    """Choose package artifacts from legacy selectors; default to all.

    Args:
        packages: Catalog package IDs.
        skills: ``--skill`` plugin IDs.
        bundle: ``--bundle`` plugin ID.
        vendor: ``--vendor`` publisher ID.

    Returns:
        Sorted, de-duplicated package IDs.

    Raises:
        InstallError: For conflicting selectors or unknown IDs.
    """
    if vendor and (bundle or skills):
        raise InstallError(
            "Vendor installs are plugin-atomic; omit --skill and --bundle"
        )
    if bundle and skills:
        raise InstallError("Choose plugins via --skill or --bundle, not both")
    if vendor:
        selected = [item for item in packages if item.split("/", 1)[0] == vendor]
        if not selected:
            raise InstallError(f"Unknown vendor: {vendor}")
        return tuple(sorted(selected))
    plugins = [bundle] if bundle else list(skills)
    if not plugins:
        return tuple(sorted(packages))
    return tuple(sorted({_plugin(item, packages) for item in plugins}))
