"""Content digests of one extracted vendor source tree, for drift candidates.

The tree is only read and hashed, never executed. Digests use the inventory's
path/hash/mode tree identity, so a directory's digest is independent of where it
lives and two revisions can be compared.
"""

import hashlib
import stat
from functools import cached_property
from pathlib import Path, PurePosixPath

from ai_skills_engine.inventory.payload import tree_digest
from ai_skills_engine.inventory.payload_file import PayloadFile
from ai_skills_engine.registry.safe_tree import walk_files


class SourceTree:
    """Lazily hashed files and directories of an extracted vendor snapshot.

    Args:
        root: Extracted vendor tree; nothing is read until a digest is needed.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @cached_property
    def files(self) -> dict[str, PayloadFile]:
        """Hash every regular file once.

        Returns:
            Relative POSIX path to its payload observation.
        """
        result = {}
        for path in walk_files(root=self.root):
            relative = path.relative_to(self.root).as_posix()
            result[relative] = PayloadFile(
                path=PurePosixPath(relative),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                mode=0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644,
            )
        return result

    @cached_property
    def directories(self) -> dict[str, str]:
        """Digest every non-root directory from its contained files.

        Returns:
            Relative directory path to qualified tree digest.
        """
        members: dict[str, list[PayloadFile]] = {}
        for relative, item in self.files.items():
            parts = relative.split("/")
            for depth in range(1, len(parts)):
                directory = "/".join(parts[:depth])
                members.setdefault(directory, []).append(
                    PayloadFile(
                        path=PurePosixPath("/".join(parts[depth:])),
                        sha256=item.sha256,
                        mode=item.mode,
                    )
                )
        return {
            directory: "sha256:"
            + tree_digest(tuple(sorted(items, key=lambda item: item.path.as_posix())))
            for directory, items in members.items()
        }

    def digest(self, relative: str) -> str | None:
        """Digest a file or directory by its relative path.

        Args:
            relative: POSIX path inside the tree.

        Returns:
            Qualified digest, or None when the path is absent.
        """
        relative = relative.strip("/")
        if relative in self.directories:
            return self.directories[relative]
        item = self.files.get(relative)
        return None if item is None else f"sha256:{item.sha256}:{item.mode:o}"

    def exists(self, relative: str) -> bool:
        """Whether a file or directory exists.

        Args:
            relative: POSIX path inside the tree.

        Returns:
            True when present.
        """
        return self.digest(relative) is not None

    def skill_directories(self) -> tuple[str, ...]:
        """List every directory directly containing ``SKILL.md``.

        Returns:
            Sorted relative directory paths.
        """
        return tuple(
            sorted(
                relative.rsplit("/", 1)[0]
                for relative in self.files
                if relative.endswith("/SKILL.md")
            )
        )

    def matching(self, digest: str) -> tuple[str, ...]:
        """Find every file or directory with exactly this content digest.

        Args:
            digest: Qualified digest from :meth:`digest`.

        Returns:
            Sorted relative paths.
        """
        found = [path for path, value in self.directories.items() if value == digest]
        found.extend(path for path in self.files if self.digest(path) == digest)
        return tuple(sorted(found))
