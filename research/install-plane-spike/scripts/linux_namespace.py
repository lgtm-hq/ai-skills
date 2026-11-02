#!/usr/bin/env python3
"""Permission controls confined to one owned, disposable Linux network namespace."""

from __future__ import annotations

import shutil
import uuid
from typing import Any

from common import command
from network_control import TARGET


def prepare(
    *, state: dict[str, Any], records: list[dict[str, Any]], consumer: dict[str, Any]
) -> list[str] | None:
    """Create a routed namespace, prohibit egress, then drop all worker privileges.

    Args:
        state: Mutable ownership/setup evidence, also used for final cleanup.
        records: Raw command records shared with the collector.
        consumer: Observed original POSIX identity; never an environment username.

    Returns:
        One shared namespace/identity prefix, or None on any setup failure.
    """
    located = {name: shutil.which(name) for name in ("sudo", "ip", "setpriv", "env")}
    missing = [name for name, path in located.items() if path is None]
    uid, gid = consumer.get("effective_uid"), consumer.get("effective_gid")
    if missing:
        state["reason"] = f"Linux namespace tools unavailable: {', '.join(missing)}"
        return None
    tools = {name: path for name, path in located.items() if path is not None}
    if not (isinstance(uid, int) and uid > 0 and isinstance(gid, int) and gid > 0):
        state["reason"] = "Linux namespace requires an original nonroot UID/GID"
        return None
    name = f"install-plane-{uuid.uuid4()}"
    admin = [tools["sudo"], "-n", tools["ip"], "netns"]
    inside = [*admin, "exec", name]
    state.update(name=name, admin=admin, setup={}, consumer=consumer)
    existing = command(argv=[*admin, "list"], records=records)
    if existing["exit"] != 0 or name in {
        line.split()[0]
        for line in existing.get("stdout", "").splitlines()
        if line.strip()
    }:
        state["reason"] = "Cannot establish fresh namespace ownership"
        return None
    state["fresh_name"] = True
    # Every route/rule mutation runs behind `ip netns exec <owned-name>`.
    # A valid loopback-only route avoids accidental ENETUNREACH proof. Explicit
    # policy-routing prohibit returns EACCES; nft OUTPUT DROP can merely time out.
    steps = [
        ("create", [*admin, "add", name]),
        ("loopback", [*inside, tools["ip"], "link", "set", "lo", "up"]),
        ("route", [*inside, tools["ip"], "route", "add", f"{TARGET}/32", "dev", "lo"]),
        ("route_control", [*inside, tools["ip"], "route", "get", TARGET]),
        (
            "filter_ipv4",
            [*inside, tools["ip"], "-4", "rule", "add", "priority", "1", "prohibit"],
        ),
        (
            "filter_ipv6",
            [*inside, tools["ip"], "-6", "rule", "add", "priority", "1", "prohibit"],
        ),
        ("rules_ipv4", [*inside, tools["ip"], "-4", "rule", "show"]),
        ("rules_ipv6", [*inside, tools["ip"], "-6", "rule", "show"]),
    ]
    for stage, argv in steps:
        if stage == "create":
            state["creation_attempted"] = True
        result = command(argv=argv, records=records)
        state["setup"][stage] = result
        if result["exit"] != 0:
            if stage in {"filter_ipv6", "rules_ipv6"}:
                state["ipv6_limitation"] = (
                    "IPv4 setup records retained; complete offline verification "
                    "unverified because IPv6 setup is unavailable"
                )
            state["reason"] = f"Linux namespace setup failed at {stage}"
            return None
        if stage == "create":
            state["created"] = True
    prefix = [
        *inside,
        tools["setpriv"],
        "--reuid",
        str(uid),
        "--regid",
        str(gid),
        "--clear-groups",
        "--bounding-set=-all",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--no-new-privs",
        "--",
        tools["env"],
        "-i",
    ]
    state["prefix"] = prefix
    return prefix


def cleanup(*, state: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Delete only our successfully created namespace and verify its name absent.

    Args:
        state: Ownership and setup evidence from prepare.
        records: Raw command records shared with the collector.

    Returns:
        Verified removal or an explicit failure; never deletes preexisting names.
    """
    if not state.get("created") and not (
        state.get("fresh_name") and state.get("creation_attempted")
    ):
        return {"status": "not created"}
    members = command(argv=[*state["admin"], "pids", state["name"]], records=records)
    if members["exit"] != 0 or members.get("stdout", "").strip():
        return {
            "status": "unverified removal",
            "members": members,
            "reason": "namespace membership not empty/verified; name retained",
        }
    removed = command(argv=[*state["admin"], "delete", state["name"]], records=records)
    remaining = command(argv=[*state["admin"], "list"], records=records)
    absent = state["name"] not in {
        line.split()[0]
        for line in remaining.get("stdout", "").splitlines()
        if line.strip()
    }
    return {
        "status": (
            "verified removed"
            if removed["exit"] == remaining["exit"] == 0 and absent
            else "unverified removal"
        ),
        "remove": removed,
        "remaining": remaining,
        "members": members,
    }
