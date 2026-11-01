"""Shared fixture setup for root parity and the isolated spike harness."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that

SPIKE = Path(__file__).resolve().parents[1]


@pytest.fixture
def prototype() -> ModuleType:
    """Import this checkout's prototype explicitly, independent of PYTHONPATH.

    Returns:
        Local Python installer module.
    """
    path = SPIKE / "py" / "prototype.py"
    spec = importlib.util.spec_from_file_location("spike_prototype", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load local prototype")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert_that(module.__file__).is_equal_to(str(path))
    return module


@pytest.fixture
def spike_fixture(tmp_path: Path) -> Path:
    """Copy the shared golden fixture for isolated mutations.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Writable fixture copy.
    """
    return Path(shutil.copytree(src=SPIKE / "fixtures", dst=tmp_path / "fixture"))


@pytest.fixture(autouse=True)
def non_utf8_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model Windows locale defaults without changing explicit UTF-8 reads.

    Args:
        monkeypatch: Reversible pathlib boundary change.
    """
    read_text = Path.read_text

    def locale_read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        """Use cp1252 when the caller omits its encoding.

        Args:
            path: File to read.
            encoding: Explicit encoding or locale default.
            errors: Decoder error handling.
            newline: Newline translation option.

        Returns:
            Text decoded with the specified encoding.
        """
        return read_text(
            path, encoding=encoding or "cp1252", errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "read_text", locale_read)
