#!/usr/bin/env python3
"""Inert artifact fixture; relative data layout is part of the contract."""

from pathlib import Path


def read_data() -> str:
    """Read fixture data only if explicitly invoked by a human.

    Returns:
        Shared data in the original relative resource layout.
    """
    return (Path(__file__).parent / "../data/input.txt").read_text()
