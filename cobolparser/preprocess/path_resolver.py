"""
Path resolution and validation for copybook files.

This module handles locating copybook files in search directories,
normalizing paths for cross-platform compatibility, validating
paths to prevent security vulnerabilities like path traversal attacks,
and providing fuzzy matching suggestions for misspelled copybook names.
"""

import os
import sys
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
    # Check for obvious traversal patterns
    if ".." in file_path:
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
                # No extension - add all files
                for path in Path(search_dir).iterdir():
                    if path.is_file():
                        available.add(path.stem.upper())

    return sorted(available)


def suggest_similar_copybooks(
    member_name: str,
    search_config: CopybookSearchPath,
    max_suggestions: int = 3,
    cutoff: float = 0.6,
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

    Returns:
        List of similar copybook names

    Example:
        >>> suggest_similar_copybooks("EMPLOYE", config)
        ['EMPLOYEE']
    """
    available = get_available_copybooks(search_config)

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

    # Build list of possible filenames
    possible_names = [member_name]  # Try exact name first
    for ext in extensions:
        if ext:  # Skip empty extension (already added as exact name)
            possible_names.append(f"{member_name}{ext}")

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
    for search_dir in search_dirs:
        # A library qualifier (COPY member OF library) maps to a
        # subdirectory named after the library, but falls back to the plain
        # search directory when no such subdirectory layout exists — on a
        # filesystem the qualifier often has no directory equivalent.
        candidate_dirs = [search_dir]
        if library_qualifier:
            candidate_dirs.insert(0, os.path.join(search_dir, library_qualifier))

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

        Returns a dict mapping normalized (uppercased, no-extension) names
        AND full filenames to their absolute paths. This turns per-lookup
        filesystem traversal into a one-time scan + O(1) dict lookups.
        """
        index: dict[str, str] = {}
        for search_dir in self.search_config.directories:
            if not os.path.isdir(search_dir):
                continue
            try:
                entries = os.scandir(search_dir)
            except OSError:
                continue
            for entry in entries:
                if not entry.is_file():
                    continue
                abs_path = os.path.abspath(entry.path)
                name = entry.name
                # Index by exact filename
                if self.search_config.case_sensitive:
                    index[name] = abs_path
                    # Also index by stem (without extension)
                    stem = Path(name).stem
                    if stem not in index:
                        index[stem] = abs_path
                else:
                    name_upper = name.upper()
                    index[name_upper] = abs_path
                    stem_upper = Path(name).stem.upper()
                    if stem_upper not in index:
                        index[stem_upper] = abs_path
        return index

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

            lookup_key = (
                member_name
                if self.search_config.case_sensitive
                else member_name.upper()
            )
            if lookup_key in self._dir_index:
                result = self._dir_index[lookup_key]
                # Validate size
                file_size = os.path.getsize(result)
                if file_size > self.search_config.max_file_size:
                    raise CopybookSizeExceededError(
                        result, file_size, self.search_config.max_file_size
                    )
                self._resolution_cache[cache_key] = result
                return result

            # Try with common extensions
            for ext in self.search_config.extensions:
                if ext:
                    ext_key = f"{lookup_key}{ext.upper() if not self.search_config.case_sensitive else ext}"
                    if ext_key in self._dir_index:
                        result = self._dir_index[ext_key]
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
