#!/usr/bin/env python3
"""Parse the spike Python pin with the runner's bootstrap interpreter."""

import argparse
import json
from pathlib import Path


def python_pin(path: Path) -> str:
    """Read a nonempty version string, independent of JSON layout or newlines.

    Args:
        path: Spike settings JSON.

    Returns:
        Python runtime version.

    Raises:
        ValueError: If the Python pin is invalid.
    """
    value = json.loads(path.read_text(encoding="utf-8"))["python"]
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError("invalid Python pin")
    return value


def test_dependencies(path: Path) -> list[str]:
    """Read exact isolated-test dependency versions from the repository lock.

    Args:
        path: Repository uv.lock, parsed using the runner's standard library.

    Returns:
        Pinned requirements for the small isolated CI environment.
    """
    # Only the pinned test interpreter needs TOML; pins.sh's runner bootstrap
    # may be older than Python 3.11 and only reads settings JSON.
    import tomllib

    packages = tomllib.loads(path.read_text(encoding="utf-8"))["package"]
    versions = {}
    for name in ("pytest", "assertpy", "pyyaml"):
        candidates = {item["version"] for item in packages if item["name"] == name}
        if len(candidates) != 1:
            raise ValueError(f"expected one locked version for {name}")
        versions[name] = candidates.pop()
    return [f"{name}=={versions[name]}" for name in ("pytest", "assertpy", "pyyaml")]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-dependencies", action="store_true")
    spike = Path(__file__).resolve().parents[1]
    if parser.parse_args().test_dependencies:
        print("\n".join(test_dependencies(spike.parents[1] / "uv.lock")))
    else:
        print(f"python={python_pin(spike / 'settings.json')}")
