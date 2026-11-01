"""Bound shutdown to the explicitly owned process group or Windows process tree."""

from __future__ import annotations

import os
import signal
import subprocess  # nosec B404 - explicit owned PID cleanup, never a shell
import time
from typing import Any


def process_tree_options() -> dict[str, Any]:
    """Create a separate ownership boundary for a command or long-lived server.

    Returns:
        Popen options for a POSIX session or Windows process group.
    """
    return {
        "start_new_session": os.name != "nt",
        "creationflags": (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        ),
    }


def stop_process_tree(
    process: subprocess.Popen[Any], *, grace: float = 2, forced: float = 2
) -> dict[str, Any]:
    """Try graceful then forced tree termination and report bounded reap failures.

    Args:
        process: Child launched with process_tree_options, never an arbitrary PID.
        grace: Maximum graceful wait in seconds.
        forced: Maximum forced wait in seconds.

    Returns:
        Exact cleanup actions, parent reap and descendant observation. Escaped
        sessions (notably sudo's PTY worker) cannot be certified by this boundary.
    """
    result: dict[str, Any] = {
        "status": "unverified",
        "actions": [],
        "parent_reaped": False,
    }

    def group_present() -> bool:
        """Check only our process group, including unreaped zombie descendants.

        Returns:
            Whether the owned process group still exists.
        """
        try:
            os.killpg(process.pid, 0)
            return True
        except ProcessLookupError:
            return False

    for force, budget in ((False, grace), (True, forced)):
        action: dict[str, Any] = {"force": force}
        result["actions"].append(action)
        try:
            if os.name == "nt":
                argv = ["taskkill.exe", "/PID", str(process.pid), "/T"]
                if force:
                    argv.append("/F")
                killed = (
                    subprocess.run(  # nosec B603 - fixed taskkill for owned PID only
                        args=argv,
                        capture_output=True,
                        timeout=max(budget, 1),
                        check=False,
                    )
                )
                action.update(
                    argv=argv,
                    exit=killed.returncode,
                    stdout=killed.stdout.decode("utf-8", errors="replace"),
                    stderr=killed.stderr.decode("utf-8", errors="replace"),
                )
            else:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
                action["signal"] = "SIGKILL" if force else "SIGTERM"
        except ProcessLookupError:
            action["group_absent"] = True
        except (OSError, subprocess.TimeoutExpired) as error:
            action["error"] = f"{type(error).__name__}: {error}"
        try:
            process.wait(timeout=budget)
            result["parent_reaped"] = True
        except (OSError, subprocess.TimeoutExpired) as error:
            action["reap_error"] = f"{type(error).__name__}: {error}"
        if os.name == "nt":
            absent = action.get("exit") == 0
            result["descendants"] = (
                "taskkill /T succeeded"
                if absent
                else "unverified: taskkill /T did not succeed"
            )
        else:
            try:
                deadline = time.monotonic() + budget
                while group_present() and time.monotonic() < deadline:
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                absent = not group_present()
                result["descendants"] = (
                    "owned process group absent"
                    if absent
                    else "unverified: group remains (possibly unreaped zombies)"
                )
            except OSError as error:
                absent = False
                result["descendants"] = f"unverified: {type(error).__name__}: {error}"
        if absent and result["parent_reaped"]:
            result["status"] = "pass"
            break
    result["exit"] = process.returncode
    result["scope"] = (
        "owned group/tree only; descendants escaping this boundary unverified"
    )
    return result
