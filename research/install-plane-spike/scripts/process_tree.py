"""Bound shutdown to the explicitly owned process group or Windows process tree."""

from __future__ import annotations

import os
import signal
import subprocess  # nosec B404 - explicit owned PID cleanup, never a shell
import time
from typing import Any

from windows_job import JobPopen, WindowsJob


def launch_process(**kwargs: Any) -> subprocess.Popen[Any]:
    """Launch with durable ownership before executing target code.

    Args:
        kwargs: Explicit Popen arguments, without ownership flags.

    Returns:
        Owned child; Windows refuses launch if job setup/assignment fails.
    """
    if os.name != "nt":
        return subprocess.Popen(
            **kwargs, start_new_session=True
        )  # nosec B603 - explicit argv
    job = WindowsJob()
    try:
        return JobPopen(job=job, **kwargs)
    except BaseException:
        job.close()
        raise


def close_process(process: subprocess.Popen[Any]) -> None:
    """Release child streams and Windows handles on normal and failure paths.

    Args:
        process: Owned process after bounded shutdown/reap.
    """
    try:
        if job := getattr(process, "job", None):
            job.close()
    finally:
        if handle := getattr(process, "_handle", None):
            handle.Close()
        for name in ("stdin", "stdout", "stderr"):
            thread = getattr(process, name + "_thread", None)
            if thread is not None and thread.is_alive():
                raise OSError(f"{name} reader still active after bounded cleanup")
            if stream := getattr(process, name, None):
                stream.close()


def stop_windows_job(
    process: subprocess.Popen[Any], *, budget: float
) -> dict[str, Any]:
    """Terminate and observe only the retained job, even after the root exits.

    Args:
        process: Root retaining its job, not an arbitrary process/PID.
        budget: Maximum termination observation and reap time in seconds.

    Returns:
        Exact termination, membership and reap evidence; errors never pass.
    """
    previous: dict[str, Any] | None = getattr(process, "_tree_termination", None)
    if previous:
        return previous
    result: dict[str, Any] = {
        "status": "unverified",
        "actions": [],
        "parent_reaped": False,
        "scope": "owned non-breakaway Windows Job Object",
    }
    job = getattr(process, "job", None)
    if job is None:
        result["error"] = "Windows process has no owned job; refusing PID cleanup"
        return result
    deadline = time.monotonic() + budget
    try:
        job.terminate()
        result["actions"].append({"operation": "TerminateJobObject", "success": True})
        while (active := job.active()) and time.monotonic() < deadline:
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        result["active_processes"] = active
        result["descendants"] = (
            "owned job empty" if active == 0 else "owned job still active"
        )
        process.wait(timeout=max(0, deadline - time.monotonic()))
        result["parent_reaped"] = True
        if active == 0:
            result["status"] = "pass"
    except (OSError, subprocess.TimeoutExpired) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            job.close()  # KILL_ON_JOB_CLOSE backstop, even if termination/query fails.
            result["job_handle_closed"] = True
        except OSError as error:
            result.update(status="unverified", close_error=str(error))
    result["exit"] = process.returncode
    process.__dict__["_tree_termination"] = result
    return result


def stop_process_tree(
    process: subprocess.Popen[Any], *, grace: float = 2, forced: float = 2
) -> dict[str, Any]:
    """Try graceful then forced tree termination and report bounded reap failures.

    Args:
        process: Child returned by launch_process, never an arbitrary PID.
        grace: Maximum graceful wait in seconds.
        forced: Maximum forced wait in seconds.

    Returns:
        Exact cleanup actions, parent reap and descendant observation. Escaped
        sessions (notably sudo's PTY worker) cannot be certified by this boundary.
    """
    if os.name == "nt":
        return stop_windows_job(process, budget=grace + forced)
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
