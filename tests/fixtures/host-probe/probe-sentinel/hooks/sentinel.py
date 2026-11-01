"""Append the lifecycle sentinel inside the probe's isolated TMPDIR."""

import os
from pathlib import Path

with (Path(os.environ["TMPDIR"]) / "probe-hook.log").open(
    mode="a",
    encoding="utf-8",
) as stream:
    stream.write("PROBE-7f3a-lifecycle\n")
