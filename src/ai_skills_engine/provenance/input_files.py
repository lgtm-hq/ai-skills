"""Read-only full-pin comparison without treating navigation aliases as payloads."""

from pathlib import Path, PurePosixPath

from ai_skills_engine.inventory.payload import payload_files, source_path
from ai_skills_engine.inventory.payload_file import PayloadFile
from ai_skills_engine.registry.safe_tree import iter_directory_entries


def input_files(
    *, root: Path, protected: tuple[PurePosixPath, ...]
) -> tuple[PayloadFile, ...]:
    """Hash every regular input file while validating unrelated file aliases.

    A relative alias outside every observed payload may name an existing regular
    file in the same pin. Its target is compared at its canonical path; the alias
    adds no bytes. Never follow directory, chained, dangling or escaping links.
    Payload collection and copying retain their unconditional symlink rejection.

    Args:
        root: Structurally bounded pinned input tree.
        protected: Capability and resource source paths observed in this pin.

    Returns:
        Sorted regular-file observations; source links and modes are unchanged.

    Raises:
        ValueError: For a payload symlink, unsafe alias or unsupported node.
    """
    source_path(root=root, relative=".")
    files = []
    stack = [root]
    while stack:
        directory = stack.pop()
        for path in iter_directory_entries(directory=directory):
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if path.is_symlink():
                if any(
                    relative.is_relative_to(payload) or payload.is_relative_to(relative)
                    for payload in protected
                ):
                    raise ValueError(f"symlink rejected in payload: {path}")
                _validate_alias(root=root, path=path)
            elif path.is_dir():
                stack.append(path)
            elif path.is_file():
                file = payload_files(path)[0]
                files.append(
                    PayloadFile(path=relative, sha256=file.sha256, mode=file.mode)
                )
            else:
                raise ValueError(f"unsupported file type rejected: {path}")
    return tuple(sorted(files, key=lambda item: item.path.as_posix()))


def _validate_alias(*, root: Path, path: Path) -> None:
    """Check an alias lexically before inspecting any target components.

    Args:
        root: Pinned input boundary.
        path: Unrelated symlink, which will never be opened or modified.

    Raises:
        ValueError: Unless the target is an internal, non-symlink regular file.
    """
    target = path.readlink().as_posix()
    if PurePosixPath(target).is_absolute() or "\\" in target:
        raise ValueError(f"symlink rejected: {path}: non-relative alias")
    parts = list(path.relative_to(root).parent.parts)
    for part in PurePosixPath(target).parts:
        if part == "..":
            if not parts:
                raise ValueError(f"symlink rejected: {path}: alias escapes pin")
            parts.pop()
        elif part != ".":
            parts.append(part)
    resolved = source_path(root=root, relative=PurePosixPath(*parts).as_posix())
    if not resolved.is_file():
        raise ValueError(f"symlink rejected: {path}: alias target is not a file")
