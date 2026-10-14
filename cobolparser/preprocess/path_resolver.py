"""
Path resolution and validation for copybook files.

This module handles locating copybook files in search directories,
normalizing paths for cross-platform compatibility, validating
paths to prevent security vulnerabilities like path traversal attacks,
and providing fuzzy matching suggestions for misspelled copybook names.
"""

import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from difflib import get_close_matches
from pathlib import Path

from . import CopybookNotFoundError, CopybookSizeExceededError, PathTraversalError
from .models import CopybookSearchPath


def normalize_path(path: str) -> str:
    """
    Normalize file path to OS-native separator format.

    Converts forward slashes to backslashes on Windows,
    and ensures consistent path representation across platforms.

    Args:
        path: Input path with any separator style

    Returns:
        Normalized path with OS-native separators

    Example:
        >>> normalize_path("copybooks/employee.cpy")  # On Windows
        'copybooks\\employee.cpy'
    """
    # Convert to Path object and back to string for normalization
    return str(Path(path).as_posix() if sys.platform != "win32" else Path(path))


def validate_path_within_directory(file_path: str, base_directory: str) -> bool:
    """
    Validate that a resolved path remains within the base directory.

    Prevents path traversal attacks by rejecting paths containing ".."
    or those that resolve outside the configured search directories.

    Args:
        file_path: The file path to validate
        base_directory: The base directory that must contain the file

    Returns:
        True if path is valid and within base directory

    Raises:
        PathTraversalError: If path attempts to escape base directory

    Example:
        >>> validate_path_within_directory("../etc/passwd", "/home/user/copybooks")
        PathTraversalError: Path traversal attempt detected
    """
    # Check for obvious traversal patterns: a literal ".." *path segment*,
    # not merely the substring "..' anywhere in the path (a filename like
    # "weird..name.cpy" contains the substring but is not a traversal
    # attempt -- reports/open-findings.md H6).
    normalized_for_segments = file_path.replace("\\", "/")
    if any(segment == ".." for segment in normalized_for_segments.split("/")):
        raise PathTraversalError(file_path)

    # Resolve both paths to absolute form
    try:
        resolved_file = Path(file_path).resolve()
        resolved_base = Path(base_directory).resolve()

        # Check if file path is within base directory
        try:
            resolved_file.relative_to(resolved_base)
            return True
        except ValueError as e:
            # Path is not relative to base directory
            raise PathTraversalError(
                file_path,
                f"Resolved path '{resolved_file}' is outside search directory '{resolved_base}'",
            ) from e
    except Exception as e:
        if isinstance(e, PathTraversalError):
            raise
        raise PathTraversalError(file_path, f"Path validation failed: {str(e)}") from e


def get_available_copybooks(search_config: CopybookSearchPath) -> list[str]:
    """
    Get list of all available copybook names in search directories.

    Args:
        search_config: Search configuration with directories and extensions

    Returns:
        List of copybook member names (without extensions)

    Example:
        >>> config = CopybookSearchPath(directories=["/copybooks"])
        >>> get_available_copybooks(config)
        ['EMPLOYEE', 'CUSTOMER', 'ADDRESS']
    """
    available = set()

    for search_dir in search_config.directories:
        if not os.path.isdir(search_dir):
            continue

        for ext in search_config.extensions:
            if ext:
                pattern = f"*{ext}"
                for path in Path(search_dir).glob(pattern):
                    if path.is_file():
                        available.add(path.stem.upper())
            else:
                # "" means "the member name as-is, no extension appended" --
                # that is exactly what resolution tries for it (see
                # `resolve_copybook_path`), so list only the files that
                # resolution could actually hit through it: those with no
                # extension at all (a PDS member downloaded verbatim). It
                # used to add *every* file's stem, which made "ACCTMNT.cbl"
                # look like an available copybook named ACCTMNT even
                # though `COPY ACCTMNT` could never resolve to it via "".
                for path in Path(search_dir).iterdir():
                    if path.is_file() and not path.suffix:
                        available.add(path.name.upper())

    return sorted(available)


# Extensions considered for a did-you-mean suggestion: unambiguous copybook
# shapes only -- ".cpy"/".CPY", plus "" for extensionless members (the
# shape a PDS download has). Deliberately narrower than CopybookSearchPath's
# own `extensions` default (which also includes ".cbl"/".cob" so that a
# copybook stored under a program-source extension still *resolves*). That
# breadth is right for resolution but wrong for a typo suggestion: a
# missing "ACCTMAST" copybook sitting next to "ACCTMNT.cbl" (the program's
# own source file) must never suggest "ACCTMNT" back to the user. See
# docs/2026-09-15-copybook-discovery-defaults-design.md (mocky-mock).
_SUGGESTION_EXTENSIONS = (".cpy", ".CPY", "")


def suggest_similar_copybooks(
    member_name: str,
    search_config: CopybookSearchPath,
    max_suggestions: int = 3,
    cutoff: float = 0.6,
    suggestion_extensions: Sequence[str] | None = None,
) -> list[str]:
    """
    Find similarly-named copybooks for typo detection.

    Uses fuzzy string matching to suggest alternatives when a
    copybook is not found.

    Args:
        member_name: The copybook name that was not found
        search_config: Search configuration
        max_suggestions: Maximum number of suggestions to return
        cutoff: Minimum similarity ratio (0.0 to 1.0)
        suggestion_extensions: Extensions to consider when building the
            candidate pool (default: `_SUGGESTION_EXTENSIONS`, i.e.
            `.cpy`/`.CPY` only). Pass `search_config.extensions` explicitly
            to restore the old (broader, resolution-shaped) candidate
            pool. This parameter affects only which files are *offered*
            as a suggestion -- actual copybook resolution
            (`PathResolver.resolve`) is unaffected either way.

    Returns:
        List of similar copybook names

    Example:
        >>> suggest_similar_copybooks("EMPLOYE", config)
        ['EMPLOYEE']
    """
    extensions = (
        _SUGGESTION_EXTENSIONS
        if suggestion_extensions is None
        else suggestion_extensions
    )
    suggestion_config = replace(search_config, extensions=list(extensions))
    available = get_available_copybooks(suggestion_config)

    # Normalize to uppercase for comparison
    member_upper = member_name.upper()

    return get_close_matches(member_upper, available, n=max_suggestions, cutoff=cutoff)


def _on_disk_casing(file_path: str) -> str:
    """Return ``file_path`` with its basename replaced by the on-disk casing.

    On case-insensitive filesystems (Windows/macOS) ``os.path.isfile`` matches
    a file whose on-disk casing differs from the probed name (disk: MEM.CPY,
    probe: MEM.cpy). Reported paths must carry the on-disk name so they are
    stable across platforms.
    """
    directory, filename = os.path.split(file_path)
    fallback: str | None = None
    try:
        with os.scandir(directory or os.curdir) as entries:
            for entry in entries:
                if entry.name == filename:
                    return file_path
                if fallback is None and entry.name.casefold() == filename.casefold():
                    fallback = entry.name
    except OSError:
        return file_path
    if fallback is not None:
        return os.path.join(directory, fallback)
    return file_path


def _library_directories(
    search_dir: str, library: str, case_sensitive: bool
) -> list[str]:
    """The subdirectories of *search_dir* that ``COPY member OF library``
    names, in the order to search them.

    Matched the way the member name itself is: when the search is
    case-sensitive, the uppercased name first (Enterprise COBOL folds the
    library-name as it does the text-name, so ``OF mylib`` finds ``MYLIB/``)
    and then the name as written -- both, so an unrelated ``MYLIB/`` never
    hides the member in ``mylib/``. Otherwise in any casing (``OF MYLIB``
    finds ``mylib/``), so a case-insensitive search does not find
    ``MEM.cpy`` but miss the library directory holding it.
    """
    exact = os.path.join(search_dir, library)
    if case_sensitive:
        folded = os.path.join(search_dir, library.upper())
        return [folded, exact] if folded != exact else [exact]
    if os.path.isdir(exact):
        return [exact]
    try:
        with os.scandir(search_dir) as entries:
            matches = sorted(
                entry.name
                for entry in entries
                if entry.is_dir() and entry.name.casefold() == library.casefold()
            )
    except OSError:
        return [exact]
    return [os.path.join(search_dir, matches[0]) if matches else exact]


def _is_path_literal(member_name: str) -> bool:
    """True when *member_name* holds a character no COBOL word can."""
    return any(ch in member_name for ch in "./\\")


def _member_probe_names(member_name: str, extensions: Sequence[str]) -> list[str]:
    """The filenames to probe for *member_name*, in order.

    Enterprise COBOL folds a COPY text-name to uppercase, so ``copy errorcd.``
    names member ``ERRORCD`` (issue #289). The name exactly as written comes
    first (``COPY "sub/mem.cpy"`` names a file), then each configured
    extension in order -- the extension order decides first, so ``COPY Foo``
    still prefers ``Foo.cpy`` to ``FOO.cbl`` -- and within an extension the
    uppercased name before the name as written, so ``ERRORCD.cpy`` wins over
    ``errorcd.cpy`` when a case-sensitive filesystem holds both. The bare
    uppercased name sits where the ``""`` extension does (last by default),
    so an extensionless ``FOO`` never shadows ``foo.cpy``.

    A name holding ``.``, ``/`` or ``\\`` cannot be a COBOL word, so it came
    from a literal (``COPY "sub/mem"``) naming a file path; it is used as
    written and not folded.
    """
    folded = member_name if _is_path_literal(member_name) else member_name.upper()
    slots = list(extensions) if "" in extensions else [*extensions, ""]
    names = [member_name]
    for ext in slots:
        for base in (folded, member_name):
            name = f"{base}{ext}"
            if name not in names:
                names.append(name)
    return names


def find_copybook_file(
    member_name: str,
    search_config: CopybookSearchPath,
    library_qualifier: str | None = None,
) -> str:
    """
    Locate a copybook file in the configured search paths.

    Searches for the member name with various extensions (.cpy, .CPY, .cbl, etc.)
    in the configured search directories. If library_qualifier is provided,
    searches in subdirectories matching the library name.

    Args:
        member_name: Name of the copybook member to find
        search_config: Search configuration with directories and extensions
        library_qualifier: Optional library name for subdirectory search

    Returns:
        Absolute path to the found copybook file

    Raises:
        CopybookNotFoundError: If copybook cannot be found in any search path
        PathTraversalError: If path validation fails
        CopybookSizeExceededError: If file exceeds size limit

    Example:
        >>> config = CopybookSearchPath(directories=["/copybooks"])
        >>> find_copybook_file("EMPLOYEE", config)
        '/copybooks/EMPLOYEE.cpy'
    """
    search_dirs = search_config.directories
    extensions = search_config.extensions

    possible_names = _member_probe_names(member_name, extensions)

    # If not case-sensitive, also try case variations
    if not search_config.case_sensitive:
        case_variants = [
            member_name.upper(),
            member_name.lower(),
            member_name.capitalize(),
        ]
        for variant in case_variants:
            if variant not in possible_names:
                possible_names.append(variant)
            for ext in extensions:
                if ext:
                    name_with_ext = f"{variant}{ext}"
                    if name_with_ext not in possible_names:
                        possible_names.append(name_with_ext)

    # Search in each directory
    for configured_dir in search_dirs:
        # Joined and validated in absolute form: a *configured* directory
        # may legitimately be spelled with ".." (`--copybook-path
        # ../copybooks`, or a cobol.yml entry resolved against the config
        # file's own directory), and the traversal check below must judge
        # only what the COPY statement contributed -- the member and library
        # names -- not the search directory the user chose.
        search_dir = os.path.abspath(configured_dir)
        # A library qualifier (COPY member OF library) maps to a
        # subdirectory named after the library, but falls back to the plain
        # search directory when no such subdirectory layout exists — on a
        # filesystem the qualifier often has no directory equivalent.
        candidate_dirs = [search_dir]
        if library_qualifier:
            candidate_dirs[:0] = _library_directories(
                search_dir, library_qualifier, search_config.case_sensitive
            )

        for actual_search_dir in candidate_dirs:
            # Try each possible filename
            for filename in possible_names:
                file_path = os.path.join(actual_search_dir, filename)

                # Normalize path
                file_path = normalize_path(file_path)

                # Check if file exists
                if os.path.isfile(file_path):
                    # Validate path is within search directory
                    validate_path_within_directory(file_path, search_dir)

                    # Check file size
                    file_size = os.path.getsize(file_path)
                    if file_size > search_config.max_file_size:
                        raise CopybookSizeExceededError(
                            file_path, file_size, search_config.max_file_size
                        )

                    return _on_disk_casing(os.path.abspath(file_path))

    # Copybook not found - get suggestions
    suggestions = suggest_similar_copybooks(member_name, search_config)
    raise CopybookNotFoundError(member_name, search_dirs, suggestions)


class PathResolver:
    """
    Wrapper class for path resolution functionality.

    Provides a unified interface for resolving copybook file paths
    with integrated validation, size checking, and fuzzy matching.

    Uses a directory index cache to avoid repeated filesystem traversals.
    The index is built once on first resolution and maps normalized names
    to their absolute paths, reducing 3000+ program × 50+ copybook
    scenarios from O(dirs × extensions × stat) to O(1) dict lookup.

    Attributes:
        search_config: Configuration for copybook search paths and extensions
    """

    def __init__(self, search_config: CopybookSearchPath):
        """
        Initialize path resolver with search configuration.

        Args:
            search_config: Search path configuration
        """
        self.search_config = search_config
        # Resolution cache: member_name -> absolute path (avoids re-scanning)
        self._resolution_cache: dict[str, str] = {}
        # Directory index: normalized_name -> absolute_path (built lazily)
        self._dir_index: dict[str, str] | None = None

    def _build_directory_index(self) -> dict[str, str]:
        """Build an index of all copybook files across search directories.

        Returns a dict mapping each file's full filename (uppercased when
        the search is case-insensitive) to its absolute path. This turns
        per-lookup filesystem traversal into a one-time scan + O(1) dict
        lookups.

        Only the *full* filename is a key. The index used to carry a
        bare-stem key as well (``MEM`` for ``MEM.bak``), which let
        ``COPY MEM`` resolve to a file of ANY extension -- ``MEM.bak``,
        ``MEM.txt``, the program's own ``MEM.cbl`` -- picked by whichever
        one ``os.scandir()`` happened to list first, instead of walking
        ``CopybookSearchPath.extensions`` in order the way Tier 3 does.
        The member name plus each configured extension is looked up
        explicitly in :meth:`resolve` instead.
        """
        index: dict[str, str] = {}
        for search_dir in self.search_config.directories:
            if not os.path.isdir(search_dir):
                continue
            try:
                entries = os.scandir(search_dir)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    abs_path = os.path.abspath(entry.path)
                    # First-configured-directory wins, matching Tier-3's
                    # ``find_copybook_file`` directory-order semantics.
                    key = (
                        entry.name
                        if self.search_config.case_sensitive
                        else entry.name.upper()
                    )
                    index.setdefault(key, abs_path)
        return index

    def _directory_rank(self, path: str) -> int:
        """Position of *path*'s directory in the configured search order
        (``len(directories)`` when it is in none of them)."""
        parent = os.path.dirname(path)
        for rank, search_dir in enumerate(self.search_config.directories):
            if os.path.abspath(search_dir) == parent:
                return rank
        return len(self.search_config.directories)

    def _validate_indexed_result(self, result: str) -> None:
        """Containment check for a Tier-2 (directory-index) resolution.

        The directory index is built via ``os.scandir()`` + ``entry.is_file()``,
        which follows symlinks: a symlink inside a search directory that
        points outside it would otherwise be served with no containment
        check at all -- only the Tier-3 full-filesystem-search path
        (:func:`find_copybook_file`) called ``validate_path_within_directory``.
        See reports/open-findings.md H6.

        The index is flattened across every configured search directory, so
        containment is checked against the whole set: the resolved path must
        land within *some* configured directory, not necessarily the one it
        happened to be enumerated from.
        """
        last_error: PathTraversalError | None = None
        for search_dir in self.search_config.directories:
            try:
                validate_path_within_directory(result, search_dir)
                return
            except PathTraversalError as exc:
                last_error = exc
        raise last_error or PathTraversalError(
            result, "not within any configured search directory"
        )

    def resolve(self, member_name: str, library_qualifier: str | None = None) -> str:
        """
        Resolve a copybook member name to an absolute file path.

        Uses a multi-tier caching strategy:
        1. Exact resolution cache (member already resolved before)
        2. Directory index (O(1) lookup by normalized name)
        3. Fallback to full filesystem search

        Args:
            member_name: Copybook member name
            library_qualifier: Optional library name

        Returns:
            Absolute path to copybook file

        Raises:
            CopybookNotFoundError: If copybook not found (with suggestions)
            PathTraversalError: If path validation fails
            CopybookSizeExceededError: If file exceeds size limit
        """
        # Tier 1: Resolution cache (exact match from prior call)
        cache_key = f"{member_name}::{library_qualifier or ''}"
        if cache_key in self._resolution_cache:
            return self._resolution_cache[cache_key]

        # Tier 2: Directory index lookup (no library qualifier, fast path)
        if library_qualifier is None:
            if self._dir_index is None:
                self._dir_index = self._build_directory_index()

            # Candidates in Tier-3 probe order (`_member_probe_names`). The
            # winner is the first *directory* that holds any candidate
            # (directory order is the SYSLIB concatenation order), and within
            # that directory the first candidate in probe order.
            candidates: list[str] = []
            for name in _member_probe_names(member_name, self.search_config.extensions):
                key = name if self.search_config.case_sensitive else name.upper()
                if key not in candidates:
                    candidates.append(key)
            best: tuple[int, int, str] | None = None
            for order, key in enumerate(candidates):
                hit = self._dir_index.get(key)
                if hit is None:
                    continue
                ranked = (self._directory_rank(hit), order, hit)
                if best is None or ranked < best:
                    best = ranked
            if best is not None:
                result = best[2]
                self._validate_indexed_result(result)
                file_size = os.path.getsize(result)
                if file_size > self.search_config.max_file_size:
                    raise CopybookSizeExceededError(
                        result, file_size, self.search_config.max_file_size
                    )
                self._resolution_cache[cache_key] = result
                return result

        # Tier 3: Full filesystem search (handles library qualifiers and edge cases)
        result = find_copybook_file(member_name, self.search_config, library_qualifier)
        self._resolution_cache[cache_key] = result
        return result

    def normalize(self, path: str) -> str:
        """
        Normalize a file path to OS-native format.

        Args:
            path: Input path

        Returns:
            Normalized path
        """
        return normalize_path(path)

    def validate(self, file_path: str, base_directory: str) -> bool:
        """
        Validate that a file path is within a base directory.

        Args:
            file_path: Path to validate
            base_directory: Base directory

        Returns:
            True if valid

        Raises:
            PathTraversalError: If validation fails
        """
        return validate_path_within_directory(file_path, base_directory)

    def get_suggestions(self, member_name: str) -> list[str]:
        """
        Get suggestions for a possibly misspelled copybook name.

        Args:
            member_name: The copybook name to find suggestions for

        Returns:
            List of similar copybook names
        """
        return suggest_similar_copybooks(member_name, self.search_config)

    def list_available(self) -> list[str]:
        """
        List all available copybook names.

        Returns:
            List of copybook member names
        """
        return get_available_copybooks(self.search_config)


__all__ = [
    "normalize_path",
    "validate_path_within_directory",
    "find_copybook_file",
    "get_available_copybooks",
    "suggest_similar_copybooks",
    "PathResolver",
]
