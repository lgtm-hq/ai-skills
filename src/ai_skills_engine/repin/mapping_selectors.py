"""Consumer mapping selectors at a new revision: match counts and path drift.

A mapping path that vanished is reconciled only when exactly one path at the
new revision has the old content digest and the same final name, so the
capability ID derived from that name never changes. Zero or several candidates
fail closed and are listed. Identical content under a different name is an
identity change; it is reported and never applied.
"""

from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Any

from ai_skills_engine.registry.registry import GLOB_METACHARS
from ai_skills_engine.repin.change import Change
from ai_skills_engine.repin.drift import Drift
from ai_skills_engine.repin.selector_plan import SelectorPlan
from ai_skills_engine.repin.selector_status import SelectorStatus
from ai_skills_engine.repin.source_tree import SourceTree


class _Outcome:
    """Mutable accumulator for one declaration's selector outcomes."""

    def __init__(self) -> None:
        self.statuses: list[SelectorStatus] = []
        self.drifts: list[Drift] = []
        self.moves: set[Change] = set()
        self.failures: list[str] = []

    def status(
        self,
        *,
        location: str,
        selector: str,
        matches: int,
        state: str,
        detail: str = "",
    ) -> None:
        """Record one selector and fail on a dead selector.

        Args:
            location: Manifest location.
            selector: Selector value.
            matches: Matched upstream items.
            state: ``ok``, ``dead`` or ``reconciled``.
            detail: Rewrite description.
        """
        self.statuses.append(
            SelectorStatus(
                location=location,
                selector=selector,
                matches=matches,
                status=state,
                detail=detail,
            )
        )
        if state == "dead":
            self.failures.append(
                f"Dead selector {location}: {selector!r} matches nothing at the "
                "new revision"
            )


def _expand(tree: SourceTree | None, pattern: str) -> tuple[str, ...]:
    """Resolve a literal or single-segment glob directory pattern.

    Args:
        tree: Hashed vendor tree.
        pattern: ``skillsRoot`` or ``skillRoots`` value.

    Returns:
        Matching relative directories, sorted.
    """
    if tree is None:
        return ()
    if not any(char in GLOB_METACHARS for char in pattern):
        return (pattern,) if pattern.strip("/") in tree.directories else ()
    parts = pattern.strip("/").split("/")
    return tuple(
        sorted(
            directory
            for directory in tree.directories
            if len(directory.split("/")) == len(parts)
            and all(
                fnmatchcase(segment, part)
                for segment, part in zip(directory.split("/"), parts, strict=True)
            )
        )
    )


def _skills_under(tree: SourceTree, root: str) -> tuple[str, ...]:
    """Discover skills like the baker: the first ``SKILL.md`` directory wins.

    Args:
        tree: Hashed vendor tree.
        root: Expanded skills root.

    Returns:
        Skill paths relative to ``root``.
    """
    prefix = root.strip("/") + "/"
    found = sorted(
        path[len(prefix) :]
        for path in tree.skill_directories()
        if path.startswith(prefix)
    )
    return tuple(
        path
        for path in found
        if not any(path.startswith(other + "/") for other in found if other != path)
    )


def _candidates(
    *, old_path: str, old: SourceTree, new: SourceTree, skill: bool
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split identical-content paths into same-name candidates and others.

    Args:
        old_path: Path at the previous revision.
        old: Previous tree.
        new: Current tree.
        skill: Require a ``SKILL.md`` in candidate directories.

    Returns:
        Same-name candidates and identical content under other names.
    """
    digest = old.digest(old_path)
    if digest is None:
        return (), ()
    name = PurePosixPath(old_path).name
    same = [path for path in new.matching(digest) if path != old_path]
    candidates = tuple(
        path
        for path in same
        if PurePosixPath(path).name == name
        and (not skill or new.exists(path + "/SKILL.md"))
    )
    return candidates, tuple(path for path in same if path not in candidates)


def _reconcile(
    *,
    outcome: _Outcome,
    location: str,
    selector: str,
    old_path: str | None,
    old: SourceTree | None,
    new: SourceTree,
    skill: bool = False,
    record: bool = True,
) -> str | None:
    """Reconcile one vanished path or record why it cannot be reconciled.

    Args:
        outcome: Accumulator.
        location: Manifest location of the selector.
        selector: Selector value.
        old_path: Path at the previous revision, if known.
        old: Previous tree, None for a new vendor.
        new: Current tree.
        skill: Candidates must be skill directories.
        record: Record a failed drift (callers with a fallback pass False).

    Returns:
        The unique new path, or None.
    """
    if old is None or old_path is None or not old.exists(old_path):
        if record:
            outcome.drifts.append(
                Drift(
                    location=location,
                    selector=selector,
                    old_path=old_path or selector,
                    status="missing",
                )
            )
        return None
    candidates, others = _candidates(old_path=old_path, old=old, new=new, skill=skill)
    outcome.moves.update(
        Change(subject=old_path, kind="identical-content", detail=path)
        for path in others
    )
    if len(candidates) == 1:
        outcome.drifts.append(
            Drift(
                location=location,
                selector=selector,
                old_path=old_path,
                status="reconciled",
                candidates=candidates,
            )
        )
        return candidates[0]
    if record:
        outcome.drifts.append(
            Drift(
                location=location,
                selector=selector,
                old_path=old_path,
                status="ambiguous" if candidates else "missing",
                candidates=candidates,
            )
        )
        if candidates:
            outcome.failures.append(
                f"Ambiguous path drift {location}: {old_path} has "
                f"{len(candidates)} identical candidates: {', '.join(candidates)}"
            )
    return None


def _reconcile_root(
    *,
    outcome: _Outcome,
    pattern: str,
    names: tuple[str, ...] | None,
    location: str,
    member_location: str,
    old: SourceTree | None,
    new: SourceTree,
) -> str | None:
    """Move a vanished literal skills root as a whole or by unique members.

    Args:
        outcome: Accumulator.
        pattern: Declared root.
        names: Listed members, or None to use the skills found under the old root.
        location: Manifest location of the root.
        member_location: Manifest location reported for unresolved members.
        old: Previous tree.
        new: Current tree.

    Returns:
        The new root, or None.
    """
    if any(char in GLOB_METACHARS for char in pattern):
        return None
    whole = _reconcile(
        outcome=outcome,
        location=location,
        selector=pattern,
        old_path=pattern.strip("/"),
        old=old,
        new=new,
        record=False,
    )
    if whole is not None or old is None or not old.exists(pattern):
        return whole
    if names is None:
        names = _skills_under(old, pattern)
    parents: set[str] = set()
    unresolved: list[str] = []
    for name in names:
        member = f"{pattern.strip('/')}/{name}"
        candidates, others = _candidates(old_path=member, old=old, new=new, skill=True)
        outcome.moves.update(
            Change(subject=member, kind="identical-content", detail=path)
            for path in others
        )
        if len(candidates) == 1 and candidates[0].endswith("/" + name):
            parents.add(candidates[0][: -len(name) - 1])
        else:
            unresolved.append(name)
            outcome.drifts.append(
                Drift(
                    location=member_location,
                    selector=name,
                    old_path=member,
                    status="ambiguous" if candidates else "missing",
                    candidates=candidates,
                )
            )
    if names and not unresolved and len(parents) == 1:
        target = parents.pop()
        outcome.drifts.append(
            Drift(
                location=location,
                selector=pattern,
                old_path=pattern,
                status="reconciled",
                candidates=(target,),
            )
        )
        return target
    outcome.drifts.append(
        Drift(
            location=location,
            selector=pattern,
            old_path=pattern,
            status="ambiguous" if len(parents) > 1 else "missing",
            candidates=tuple(sorted(parents)),
        )
    )
    return None


def _skill_roots(
    *,
    mapping: dict[str, Any],
    old: SourceTree | None,
    new: SourceTree,
    outcome: _Outcome,
) -> None:
    """Count, and reconcile literal, legacy discovery roots.

    Args:
        mapping: Mutable vendor mapping.
        old: Previous tree.
        new: Current tree.
        outcome: Accumulator.
    """
    roots = list(mapping.get("skillRoots") or ())
    for position, pattern in enumerate(roots):
        location = "mapping.skillRoots"
        matched = _expand(new, pattern)
        state, detail = "ok", ""
        if not matched and not any(char in GLOB_METACHARS for char in pattern):
            target = _reconcile_root(
                outcome=outcome,
                pattern=pattern,
                names=None,
                location=location,
                member_location=location,
                old=old,
                new=new,
            )
            if target is not None:
                roots[position], matched = target, (target,)
                state, detail = "reconciled", f"{pattern} -> {target}"
        count = sum(len(_skills_under(new, root)) for root in matched)
        outcome.status(
            location=location,
            selector=pattern,
            matches=count,
            state=state if count else "dead",
            detail=detail,
        )
    if roots:
        mapping["skillRoots"] = roots


def _listed_skills(
    *,
    package: dict[str, Any],
    roots: tuple[str, ...],
    old_roots: tuple[str, ...],
    location: str,
    old: SourceTree | None,
    new: SourceTree,
    outcome: _Outcome,
) -> tuple[str, ...]:
    """Count listed skills; move a uniquely moved one to ``extraSkills``.

    Args:
        package: Mutable mapped package.
        roots: Expanded current roots.
        old_roots: Expanded previous roots.
        location: Manifest location of the list.
        old: Previous tree.
        new: Current tree.
        outcome: Accumulator.

    Returns:
        Final skill names (last path segment).
    """
    if package["skills"] == "*":
        found = sorted({name for root in roots for name in _skills_under(new, root)})
        outcome.status(
            location=location,
            selector="*",
            matches=len(found),
            state="ok" if found else "dead",
        )
        return tuple(PurePosixPath(name).name for name in found)
    kept: list[str] = []
    names: list[str] = []
    for name in package["skills"]:
        count = sum(new.exists(f"{root}/{name}/SKILL.md") for root in roots)
        if count:
            kept.append(name)
            names.append(PurePosixPath(name).name)
            outcome.status(location=location, selector=name, matches=count, state="ok")
            continue
        old_path = next(
            (
                f"{root}/{name}"
                for root in old_roots
                if old is not None and old.exists(f"{root}/{name}/SKILL.md")
            ),
            None,
        )
        target = _reconcile(
            outcome=outcome,
            location=location,
            selector=name,
            old_path=old_path,
            old=old,
            new=new,
            skill=True,
        )
        if target is None:
            kept.append(name)
            outcome.status(location=location, selector=name, matches=0, state="dead")
            continue
        package.setdefault("extraSkills", []).append(target)
        names.append(PurePosixPath(target).name)
        outcome.status(
            location=location,
            selector=name,
            matches=1,
            state="reconciled",
            detail=f"moved to extraSkills: {target}",
        )
    package["skills"] = kept
    return tuple(names)


def _paths(
    *,
    values: list[Any],
    key: str | None,
    location: str,
    old: SourceTree | None,
    new: SourceTree,
    outcome: _Outcome,
    skill: bool = False,
) -> None:
    """Count path selectors and rewrite a uniquely moved path in place.

    Args:
        values: Mutable list of paths, or of records holding ``key``.
        key: Record field holding the path, None for plain strings.
        location: Manifest location.
        old: Previous tree.
        new: Current tree.
        outcome: Accumulator.
        skill: Paths are skill directories.
    """
    for position, value in enumerate(values):
        path = value if key is None else value[key]
        probe = f"{path}/SKILL.md" if skill else path
        if new.exists(probe):
            outcome.status(location=location, selector=path, matches=1, state="ok")
            continue
        target = _reconcile(
            outcome=outcome,
            location=location,
            selector=path,
            old_path=path,
            old=old,
            new=new,
            skill=skill,
        )
        if target is None:
            outcome.status(location=location, selector=path, matches=0, state="dead")
            continue
        if key is None:
            values[position] = target
        else:
            value[key] = target
        outcome.status(
            location=location,
            selector=target,
            matches=1,
            state="reconciled",
            detail=f"{path} -> {target}",
        )


def _package(
    *,
    package: dict[str, Any],
    old: SourceTree | None,
    new: SourceTree,
    outcome: _Outcome,
) -> None:
    """Analyze and reconcile one mapped package in place.

    Args:
        package: Mutable mapped package.
        old: Previous tree.
        new: Current tree.
        outcome: Accumulator.
    """
    base = f"mapping.packages[{package['id']}]"
    pattern = package["skillsRoot"]
    old_roots = _expand(old, pattern)
    roots = _expand(new, pattern)
    if roots:
        outcome.status(
            location=base + ".skillsRoot",
            selector=pattern,
            matches=len(roots),
            state="ok",
        )
    else:
        target = _reconcile_root(
            outcome=outcome,
            pattern=pattern,
            names=None if package["skills"] == "*" else tuple(package["skills"]),
            location=base + ".skillsRoot",
            member_location=base + ".skills",
            old=old,
            new=new,
        )
        if target is None:
            outcome.status(
                location=base + ".skillsRoot", selector=pattern, matches=0, state="dead"
            )
            return
        package["skillsRoot"], roots = target, (target,)
        outcome.status(
            location=base + ".skillsRoot",
            selector=target,
            matches=1,
            state="reconciled",
            detail=f"{pattern} -> {target}",
        )
    extra = list(package.get("extraSkills") or ())
    if extra:
        _paths(
            values=extra,
            key=None,
            location=base + ".extraSkills",
            old=old,
            new=new,
            outcome=outcome,
            skill=True,
        )
        package["extraSkills"] = extra
    names = set(
        _listed_skills(
            package=package,
            roots=roots,
            old_roots=old_roots,
            location=base + ".skills",
            old=old,
            new=new,
            outcome=outcome,
        )
    )
    names.update(PurePosixPath(path).name for path in package.get("extraSkills") or ())
    for name in package.get("agents") or ():
        path = f"agents/{name}.md"
        if new.exists(path):
            outcome.status(
                location=base + ".agents", selector=name, matches=1, state="ok"
            )
            names.add(name)
            continue
        # Agent paths are fixed by the mapping format; a move is never rewritable.
        _reconcile(
            outcome=outcome,
            location=base + ".agents",
            selector=name,
            old_path=path,
            old=old,
            new=new,
        )
        outcome.status(
            location=base + ".agents", selector=name, matches=0, state="dead"
        )
    if package.get("extraFiles"):
        files = list(package["extraFiles"])
        _paths(
            values=files,
            key=None,
            location=base + ".extraFiles",
            old=old,
            new=new,
            outcome=outcome,
        )
        package["extraFiles"] = files
    declared = package.get("artifactResources") or {}
    if declared.get("resources"):
        _paths(
            values=declared["resources"],
            key="path",
            location=base + ".artifactResources.resources",
            old=old,
            new=new,
            outcome=outcome,
        )
    for field in ("renameSkills", "capabilities"):
        for name in sorted(package.get(field) or {}):
            outcome.status(
                location=f"{base}.{field}",
                selector=name,
                matches=int(name in names),
                state="ok" if name in names else "dead",
            )


def analyze_mapping(
    *, entry: dict[str, Any], old: SourceTree | None, new: SourceTree
) -> SelectorPlan:
    """Count every mapping selector and reconcile uniquely moved paths.

    Args:
        entry: Consumer vendor declaration (not modified).
        old: Previous revision tree, None for a newly added vendor.
        new: New revision tree.

    Returns:
        Rewritten declaration with outcomes; any failure fails the re-pin.
    """
    result = deepcopy(entry)
    mapping = result.get("mapping")
    outcome = _Outcome()
    if isinstance(mapping, dict):
        _skill_roots(mapping=mapping, old=old, new=new, outcome=outcome)
        for package in mapping.get("packages") or ():
            _package(package=package, old=old, new=new, outcome=outcome)
    failures = list(outcome.failures)
    failures.extend(
        f"Path drift {item.location}: {item.old_path} vanished and no identical "
        "directory with the same name exists at the new revision"
        for item in outcome.drifts
        if item.status == "missing"
    )
    return SelectorPlan(
        entry=result,
        statuses=tuple(sorted(outcome.statuses)),
        drifts=tuple(sorted(set(outcome.drifts))),
        moves=tuple(sorted(outcome.moves)),
        failures=tuple(dict.fromkeys(failures)),
    )
