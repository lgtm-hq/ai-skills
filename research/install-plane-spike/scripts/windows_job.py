"""Windows child ownership: assign suspended roots before any user code can run.

The narrow Popen adapter uses CPython's Windows pipe/communication implementation,
but retains CreateProcess's primary thread handle until job assignment succeeds.
No breakaway permission is enabled; descendants inherit job membership. Jobs are
unnamed and noninheritable, and kill-on-close is a final lifetime backstop.
"""

from __future__ import annotations

import ctypes
import importlib
import os
import subprocess  # nosec B404 - explicit argv, owned suspended launch only
from ctypes import wintypes
from typing import Any

# POSIX typeshed omits Win32 exports. Keep dynamic typing at this OS adapter
# boundary, which is imported for mocked lifecycle tests on every host.
WINDOWS_CTYPES: Any = ctypes
WINDOWS_SUBPROCESS: Any = subprocess


class BasicLimits(ctypes.Structure):
    """ABI layout of JOBOBJECT_BASIC_LIMIT_INFORMATION."""

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class ExtendedLimits(ctypes.Structure):
    """ABI layout of JOBOBJECT_EXTENDED_LIMIT_INFORMATION."""

    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", ctypes.c_ulonglong * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class Accounting(ctypes.Structure):
    """ABI layout of JOBOBJECT_BASIC_ACCOUNTING_INFORMATION."""

    _fields_ = [
        ("Times", ctypes.c_longlong * 4),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class WindowsJob:
    """Configure a non-breakaway job before creating any suspended child.

    Job membership survives the root's PID/lifetime.
    """

    def __init__(self) -> None:
        # Windows-only symbols are resolved at the platform adapter boundary;
        # importing this module for mocked tests on POSIX requires no Win32 API.
        self.api = WINDOWS_CTYPES.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                wintypes.BOOL,
            ),
            "QueryInformationJobObject": (
                [
                    wintypes.HANDLE,
                    ctypes.c_int,
                    ctypes.c_void_p,
                    wintypes.DWORD,
                    ctypes.c_void_p,
                ],
                wintypes.BOOL,
            ),
            "AssignProcessToJobObject": (
                [wintypes.HANDLE, wintypes.HANDLE],
                wintypes.BOOL,
            ),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise WINDOWS_CTYPES.WinError(WINDOWS_CTYPES.get_last_error())
        try:
            limits = ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            self.check(
                self.api.SetInformationJobObject(
                    self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
        except BaseException:
            self.close()
            raise

    def check(self, success: int) -> None:
        """Raise the exact Windows error for a rejected ownership operation.

        Args:
            success: Win32 BOOL result.
        """
        if not success:
            raise WINDOWS_CTYPES.WinError(WINDOWS_CTYPES.get_last_error())

    def assign(self, process: int) -> None:
        """Assign the still-suspended root; no child code has executed yet.

        Args:
            process: Retained CreateProcess handle, never a looked-up PID.
        """
        self.check(self.api.AssignProcessToJobObject(self.handle, process))

    def resume(self, thread: int) -> None:
        """Resume exactly the owned initial thread after successful assignment.

        Args:
            thread: Retained CreateProcess primary thread handle.
        """
        previous = self.api.ResumeThread(thread)
        if previous != 1:
            raise OSError(f"unexpected suspended-thread count: {previous}")

    def terminate(self) -> None:
        """Terminate all members, including descendants of an exited root."""
        self.check(self.api.TerminateJobObject(self.handle, 1))

    def active(self) -> int:
        """Query active membership without enumerating or acting on PIDs.

        Returns:
            Number of live processes in this job.
        """
        information = Accounting()
        self.check(
            self.api.QueryInformationJobObject(
                self.handle,
                1,
                ctypes.byref(information),
                ctypes.sizeof(information),
                None,
            )
        )
        return int(information.ActiveProcesses)

    def close(self) -> None:
        """Close once; kernel kill-on-close also covers unexpected caller failure."""
        if self.handle:
            self.check(self.api.CloseHandle(self.handle))
            self.handle = None


class JobPopen(subprocess.Popen[bytes]):
    """Use stdlib pipes/waits while retaining the suspended launch thread.

    Args:
        job: Already configured job.
        kwargs: Explicit Popen arguments, no shell or custom startup state.
    """

    def __init__(self, *, job: WindowsJob, **kwargs: Any) -> None:
        self.job = job
        super().__init__(**kwargs)

    def _execute_child(
        self,
        args: list[str],
        executable: str | None,
        preexec_fn: Any,
        close_fds: bool,
        pass_fds: Any,
        cwd: str | None,
        env: Any,
        startupinfo: Any,
        creationflags: int,
        shell: bool,
        p2cread: Any,
        p2cwrite: Any,
        c2pread: Any,
        c2pwrite: Any,
        errread: Any,
        errwrite: Any,
        *unused: Any,
    ) -> None:
        """Create suspended, assign, then resume using retained kernel handles.

        Args:
            args: Explicit argv list.
            executable: Optional explicit executable.
            preexec_fn: Unsupported callback.
            close_fds: Must retain the stdlib default.
            pass_fds: Unsupported descriptor inheritance.
            cwd: Child directory.
            env: Child environment.
            startupinfo: Unsupported caller startup state.
            creationflags: Unsupported caller flags, including breakaway.
            shell: Must be false.
            p2cread: Child input pipe handle.
            p2cwrite: Parent input pipe handle.
            c2pread: Parent output pipe handle.
            c2pwrite: Child output pipe handle.
            errread: Parent error pipe handle.
            errwrite: Child error pipe handle.
            unused: POSIX-only stdlib arguments.
        """
        # Import Windows-only stdlib dynamically at the OS boundary, so POSIX
        # type checking and mocked tests do not require Windows-only stubs.
        native = importlib.import_module("_winapi")

        if (
            shell
            or preexec_fn
            or pass_fds
            or startupinfo
            or creationflags
            or not close_fds
            or not isinstance(args, list)
        ):
            raise OSError("unsupported owned Windows launch options")
        startup = WINDOWS_SUBPROCESS.STARTUPINFO()
        if -1 not in (p2cread, c2pwrite, errwrite):
            startup.dwFlags |= native.STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = (
                p2cread,
                c2pwrite,
                errwrite,
            )
            # Popen's private Windows pipe hooks have no POSIX stub declarations.
            adapter: Any = self
            handles = adapter._filter_handle_list(
                [int(p2cread), int(c2pwrite), int(errwrite)]
            )
            startup.lpAttributeList = {"handle_list": handles}
        else:
            handles = []
        try:
            hp, ht, pid, _ = native.CreateProcess(
                executable,
                subprocess.list2cmdline(args),
                None,
                None,
                bool(handles),
                0x4,
                env,
                os.fsdecode(cwd) if cwd else None,
                startup,
            )  # CREATE_SUSPENDED: no target code before job ownership.
        finally:
            adapter = self
            adapter._close_pipe_fds(
                p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite
            )
        try:
            self.job.assign(hp)
            self.job.resume(ht)
        except BaseException:
            # The root is still suspended, or has just been resumed into our job.
            # Terminate by retained handle, never a reusable numeric PID.
            try:
                native.TerminateProcess(hp, 1)
                if native.WaitForSingleObject(hp, 2000) != native.WAIT_OBJECT_0:
                    raise OSError("suspended root cleanup timeout")
            finally:
                native.CloseHandle(hp)
            raise
        finally:
            native.CloseHandle(ht)
        self._handle = WINDOWS_SUBPROCESS.Handle(hp)
        self.pid = pid
        self._child_created = True
