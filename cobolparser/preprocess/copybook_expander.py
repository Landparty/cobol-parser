"""
Core copybook expansion engine.

This module implements the main copybook expansion logic, including
recursive resolution of nested copybooks, encoding detection,
source location tracking, content validation, and caching.

Performance features for large batch scenarios (3000+ programs, 50+ copybooks):
- Module-level file content cache to avoid re-reading the same copybook from disk
- O(1) LRU expansion cache using OrderedDict
- O(1) circular reference detection using a set
- Directory index in PathResolver for instant file lookups
"""

import time
from collections import OrderedDict
from typing import Any

from . import (
    CircularReferenceError,
    EncodingError,
    NestingDepthError,
    TotalExpansionSizeExceededError,
    preprocess_conditional_compilation,
    validate_copybook_content,
    validate_level_numbers,
)
from .copy_statement_parser import (
    CopyStatementLexer,
    apply_replacing_clauses,
    normalize_continuation_lines,
    remove_comment_lines,
    strip_sequence_area,
)
from .models import (
    MAX_COPYBOOK_SIZE_BYTES,
    MAX_TOTAL_EXPANSION_BYTES,
    CopybookExpansion,
    CopybookSearchPath,
    ExpansionContext,
    ExpansionStatistics,
)
from .path_resolver import PathResolver

# Module-level file content cache for batch scenarios.
# When parsing 3000+ programs that reference the same 50+ copybooks,
# this avoids re-reading and re-decoding the same file from disk.
# Uses OrderedDict for O(1) LRU eviction.
#
# Each entry stores ``(content, decode_warnings)`` so cache hits replay any
# lossy-decode diagnostics — without this, only the first reader of a copybook
# would see U+FFFD-replacement warnings; subsequent readers from the same
# process would silently use the replaced text.
_FILE_CONTENT_CACHE: OrderedDict[str, tuple[str, tuple[str, ...]]] = OrderedDict()
_FILE_CONTENT_CACHE_MAX = 2048  # Max cached file contents

# Cache observability — track hits / misses / evictions across the process so
# operators can spot thrashing on large batches and tune ``set_file_cache_size``.
_FILE_CONTENT_CACHE_HITS = 0
_FILE_CONTENT_CACHE_MISSES = 0
_FILE_CONTENT_CACHE_EVICTIONS = 0


def _cached_read_file(
    file_path: str,
    encoding_override: str | None = None,
    warnings: list[str] | None = None,
    encoding_errors: str = "replace",
) -> str:
    """Read a file with caching to avoid redundant disk I/O.

    The cache key includes the encoding override and the errors policy to
    handle cases where the same file might be read with different settings
    (rare but possible).
    Optional *warnings* receives encoding-loss diagnostics emitted by
    :func:`read_file_with_encoding`; on cache hit, any diagnostics recorded
    on the original read are replayed into *warnings* so downstream
    expansions don't lose visibility into prior lossy decodes.
    """
    global _FILE_CONTENT_CACHE_HITS, _FILE_CONTENT_CACHE_MISSES
    global _FILE_CONTENT_CACHE_EVICTIONS

    cache_key = f"{file_path}::{encoding_override or 'auto'}::{encoding_errors}"
    if cache_key in _FILE_CONTENT_CACHE:
        _FILE_CONTENT_CACHE.move_to_end(cache_key)
        _FILE_CONTENT_CACHE_HITS += 1
        content, cached_warnings = _FILE_CONTENT_CACHE[cache_key]
        if warnings is not None and cached_warnings:
            warnings.extend(cached_warnings)
        return content

    _FILE_CONTENT_CACHE_MISSES += 1
    fresh_warnings: list[str] = []
    content = read_file_with_encoding(
        file_path,
        encoding_override,
        warnings=fresh_warnings,
        encoding_errors=encoding_errors,
    )
    if warnings is not None and fresh_warnings:
        warnings.extend(fresh_warnings)

    # LRU eviction
    if len(_FILE_CONTENT_CACHE) >= _FILE_CONTENT_CACHE_MAX:
        _FILE_CONTENT_CACHE.popitem(last=False)
        _FILE_CONTENT_CACHE_EVICTIONS += 1
    _FILE_CONTENT_CACHE[cache_key] = (content, tuple(fresh_warnings))
    return content


def clear_file_cache() -> None:
    """Clear the module-level file content cache and reset its counters.

    Call between independent batch runs if memory reclamation is needed.
    """
    global _FILE_CONTENT_CACHE_HITS, _FILE_CONTENT_CACHE_MISSES
    global _FILE_CONTENT_CACHE_EVICTIONS
    _FILE_CONTENT_CACHE.clear()
    _FILE_CONTENT_CACHE_HITS = 0
    _FILE_CONTENT_CACHE_MISSES = 0
    _FILE_CONTENT_CACHE_EVICTIONS = 0


def set_file_cache_size(max_entries: int) -> None:
    """Configure the maximum entry count of the copybook content cache.

    The default of 2048 fits most batches; raise it when parsing many
    thousands of programs that share copybooks, or lower it to constrain
    memory. Excess entries are evicted in LRU order until the limit is met.

    Args:
        max_entries: Positive integer. Values below 1 raise ``ValueError``.
    """
    global _FILE_CONTENT_CACHE_MAX, _FILE_CONTENT_CACHE_EVICTIONS
    if max_entries < 1:
        raise ValueError(f"File cache size must be at least 1, got {max_entries}")
    _FILE_CONTENT_CACHE_MAX = max_entries
    while len(_FILE_CONTENT_CACHE) > _FILE_CONTENT_CACHE_MAX:
        _FILE_CONTENT_CACHE.popitem(last=False)
        _FILE_CONTENT_CACHE_EVICTIONS += 1


def get_file_cache_stats() -> dict[str, int]:
    """Return a snapshot of file-cache observability counters.

    Keys: ``size``, ``max_size``, ``hits``, ``misses``, ``evictions``.

    A high eviction count relative to ``size`` indicates the cache is too
    small for the working set and should be enlarged via
    :func:`set_file_cache_size`.
    """
    return {
        "size": len(_FILE_CONTENT_CACHE),
        "max_size": _FILE_CONTENT_CACHE_MAX,
        "hits": _FILE_CONTENT_CACHE_HITS,
        "misses": _FILE_CONTENT_CACHE_MISSES,
        "evictions": _FILE_CONTENT_CACHE_EVICTIONS,
    }


#: Number of bytes examined when detecting encoding. Bounding the sample keeps
#: detection O(1) for very large copybooks while sampling far more context
#: than any realistic copybook needs to be classified.
_DETECT_PREFIX_BYTES = 64 * 1024

#: Characters plausible in COBOL source text. Candidate decodings are scored
#: by the proportion of their characters drawn from this set. Includes tab,
#: LF, CR and NEL (U+0085 — what cp037 decodes the EBCDIC NL byte 0x15 to).
_COBOL_TEXT_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    " .,;:'\"()<>=+-*/$"
    "\t\n\r\x85"
)

#: Byte values of the ASCII subset of _COBOL_TEXT_CHARS, so the ASCII-side
#: plausibility score can be computed directly from bytes (no trial decode).
_COBOL_TEXT_BYTES = frozenset(ord(ch) for ch in _COBOL_TEXT_CHARS if ord(ch) < 0x80)

#: High-signal COBOL keywords used as a scoring tiebreaker between candidate
#: decodings (searched case-insensitively).
_COBOL_KEYWORDS = ("DIVISION", "SECTION", "PIC", "COPY", "VALUE", "FILLER")


def _score_cobol_plausibility(text: str, *, newline_bonus: bool) -> float:
    """Score how plausibly *text* is COBOL source (higher is more plausible).

    Base score is the proportion of characters in the COBOL charset (0..1);
    keyword hits add up to +0.3 and a matching newline convention adds +0.05.
    """
    if not text:
        return 0.0
    in_charset = sum(1 for ch in text if ch in _COBOL_TEXT_CHARS)
    score = in_charset / len(text)
    upper = text.upper()
    keyword_hits = sum(1 for kw in _COBOL_KEYWORDS if kw in upper)
    score += 0.1 * min(keyword_hits, 3)
    if newline_bonus:
        score += 0.05
    return score


def _try_strict_utf8(prefix: bytes, truncated: bool) -> str | None:
    """Strict-decode *prefix* as UTF-8, tolerating a truncation-split tail.

    When *truncated* is True the prefix may end mid multi-byte sequence; a
    decode error within the final 4 bytes is retried on the shortened prefix
    so a valid UTF-8 file is not misclassified because of the sample cut.
    Returns the decoded text, or None if the bytes are not valid UTF-8.
    """
    try:
        return prefix.decode("utf-8")
    except UnicodeDecodeError as exc:
        if truncated and exc.start >= len(prefix) - 4:
            try:
                return prefix[: exc.start].decode("utf-8")
            except UnicodeDecodeError:
                return None
        return None


def detect_encoding(file_path: str) -> str:
    """
    Detect character encoding of a file using pure-Python heuristics.

    Detection algorithm (no external dependencies per constitution), applied
    to a bounded prefix (first 64KB) with a single byte pass plus at most two
    trial decodes:

    1. Byte-order marks are decisive: UTF-8 BOM -> 'utf-8-sig'; a UTF-16 BOM
       whose decoded text is plausible COBOL -> 'utf-16'.
    2. ASCII/UTF-8 line endings (0x0A/0x0D) with >=95% ASCII printables are
       decisive for ASCII/UTF-8.
    3. Strict UTF-8 trial decode: success with multi-byte characters present
       is decisive for UTF-8.
    4. Otherwise, compare COBOL-plausibility scores of the bytes read as
       ASCII versus decoded as EBCDIC (proportion of characters in the COBOL
       charset, EBCDIC newline bytes 0x15 NL / 0x25 LF vs ASCII 0x0A/0x0D,
       and COBOL keyword hits as a tiebreaker). This replaces the old single
       0x40-vs-0x20 byte-count ratio, which misclassified '@'-heavy ASCII
       files as EBCDIC.

    Single-byte EBCDIC codecs (cp037, cp500, ...) decode every byte sequence
    without error and agree on the entire COBOL character set (letters,
    digits, space, common punctuation), so variants cannot be distinguished
    by content. cp037 (US/Canada, the most common IBM mainframe encoding) is
    returned as the canonical EBCDIC label; callers needing a specific
    variant (e.g. cp1047, cp500, cp273) should set the
    CopybookSearchPath.encoding field to override auto-detection.

    Args:
        file_path: Path to file to detect encoding

    Returns:
        Encoding name string ('utf-8-sig', 'utf-8', 'utf-16', 'cp037' for
        EBCDIC, or 'ascii')

    Raises:
        EncodingError: If file cannot be read

    Example:
        >>> detect_encoding("employee.cpy")
        'utf-8'
    """
    try:
        with open(file_path, "rb") as f:
            raw_bytes = f.read(_DETECT_PREFIX_BYTES + 1)
    except (OSError, ValueError) as e:
        raise EncodingError(file_path, f"Failed to detect encoding: {str(e)}") from e

    truncated = len(raw_bytes) > _DETECT_PREFIX_BYTES
    prefix = raw_bytes[:_DETECT_PREFIX_BYTES]

    if not prefix:
        return "utf-8"

    # --- Decisive check 1: byte-order marks -------------------------------
    if prefix.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if prefix.startswith((b"\xff\xfe", b"\xfe\xff")):
        # Verify the BOM is real UTF-16 (not binary junk): decode an
        # even-length slice and require plausible COBOL text.
        probe = prefix[: len(prefix) - (len(prefix) % 2)]
        try:
            decoded_utf16 = probe.decode("utf-16")
        except UnicodeDecodeError:
            decoded_utf16 = ""
        if decoded_utf16 and (
            _score_cobol_plausibility(decoded_utf16, newline_bonus=False) >= 0.6
        ):
            return "utf-16"
        # Implausible text behind the "BOM": fall through to byte heuristics.

    # --- Single byte pass: printability, charset and newline conventions ---
    ascii_printable = 0
    ascii_cobol_chars = 0
    has_ascii_newline = False
    has_ebcdic_newline = False
    for byte in prefix:
        if 0x20 <= byte <= 0x7E or byte in (0x09, 0x0A, 0x0D):
            ascii_printable += 1
            if byte in (0x0A, 0x0D):
                has_ascii_newline = True
        if byte in (0x15, 0x25):
            has_ebcdic_newline = True
        if byte in _COBOL_TEXT_BYTES:
            ascii_cobol_chars += 1
    printable_ratio = ascii_printable / len(prefix)

    # Trial decode 1: strict UTF-8 on the bounded prefix.
    utf8_text = _try_strict_utf8(prefix, truncated)

    # --- Decisive check 2: ASCII line endings + overwhelmingly printable ---
    if has_ascii_newline and printable_ratio >= 0.95:
        return "utf-8" if utf8_text is not None else "ascii"

    # --- Decisive check 3: valid UTF-8 with real multi-byte characters -----
    if utf8_text is not None and any(ord(ch) > 0x7F for ch in utf8_text):
        return "utf-8"

    # --- Comparative scoring: ASCII vs EBCDIC plausibility -----------------
    # ASCII side is scored straight from the byte pass (keywords searched on
    # the raw bytes); EBCDIC side uses trial decode 2 (cp037 — cp500 scores
    # identically on the COBOL charset, see docstring).
    ascii_score = ascii_cobol_chars / len(prefix)
    upper_bytes = prefix.upper()
    ascii_keyword_hits = sum(
        1 for kw in _COBOL_KEYWORDS if kw.encode("ascii") in upper_bytes
    )
    ascii_score += 0.1 * min(ascii_keyword_hits, 3)
    if has_ascii_newline:
        ascii_score += 0.05

    ebcdic_text = prefix.decode("cp037")
    ebcdic_score = _score_cobol_plausibility(
        ebcdic_text, newline_bonus=has_ebcdic_newline
    )

    if ebcdic_score > ascii_score:
        return "cp037"

    return "utf-8" if utf8_text is not None else "ascii"


#: U+FFFD REPLACEMENT CHARACTER — emitted by Python's ``errors="replace"``
#: decoding when a byte cannot be mapped to the target codec. We scan for it
#: post-decode to detect lossy conversions and surface them as warnings.
_REPLACEMENT_CHARACTER = "�"


def convert_to_utf8(
    content: bytes,
    detected_encoding: str,
    *,
    source_label: str = "<content>",
    warnings: list[str] | None = None,
    errors: str = "replace",
) -> str:
    """
    Convert file content to UTF-8 string with configurable strictness.

    With ``errors="replace"`` (default, backward compatible), decodes
    ``content`` using ``detected_encoding`` with unmappable bytes replaced by
    U+FFFD.  If the codec name is unknown a second attempt with ASCII
    replacement is made.  No multi-codec probe sequence is performed because
    single-byte EBCDIC codecs (cp037, cp500, cp1047, …) all decode every
    byte sequence without raising errors, making error-based probing useless.
    Use ``CopybookSearchPath.encoding`` to supply a specific EBCDIC variant
    rather than relying on auto-detection.

    With ``errors="strict"``, any undecodable byte raises ``EncodingError``
    with the source label and byte offset instead of silently mangling data.

    When a replace-mode decode substitutes unmappable bytes, a diagnostic
    (including the replacement count) is appended to *warnings* (when
    provided) naming the source so callers can surface it via
    ``ExpansionStatistics.warnings``.

    Args:
        content: Raw bytes from file
        detected_encoding: Encoding name from detect_encoding() or caller override
        source_label: Identifier used in warning messages (file path or
            ``"<content>"`` for in-memory data).
        warnings: Optional list that lossy-decode diagnostics are appended to.
        errors: Decode strictness — ``"replace"`` (default) or ``"strict"``.

    Returns:
        UTF-8 string content

    Raises:
        EncodingError: If conversion fails, or if ``errors="strict"`` and the
            content contains undecodable bytes.
        ValueError: If *errors* is not ``"replace"`` or ``"strict"``.
    """
    if errors not in ("replace", "strict"):
        raise ValueError(
            f"encoding errors policy must be 'replace' or 'strict', got {errors!r}"
        )

    if errors == "strict":
        try:
            return content.decode(detected_encoding, errors="strict")
        except UnicodeDecodeError as e:
            raise EncodingError(
                source_label,
                f"Cannot decode byte 0x{content[e.start]:02x} at offset "
                f"{e.start} as {detected_encoding}: {e.reason} "
                f"(encoding_errors='strict'). Set CopybookSearchPath.encoding "
                f"to the correct codec, or use encoding_errors='replace' to "
                f"substitute U+FFFD.",
            ) from e
        except LookupError as e:
            raise EncodingError(
                source_label,
                f"Unknown encoding {detected_encoding!r} "
                f"(encoding_errors='strict'): {str(e)}",
            ) from e

    try:
        # Decode using detected encoding
        text = content.decode(detected_encoding, errors="replace")
    except (UnicodeDecodeError, LookupError):
        # Fallback to ASCII with replacement
        try:
            text = content.decode("ascii", errors="replace")
            detected_encoding = "ascii"
        except (UnicodeDecodeError, LookupError) as e2:
            raise EncodingError(
                source_label,
                f"Failed to convert from {detected_encoding}: {str(e2)}",
            ) from e2

    if warnings is not None and _REPLACEMENT_CHARACTER in text:
        replacement_count = text.count(_REPLACEMENT_CHARACTER)
        warnings.append(
            f"Lossy decode of '{source_label}' as {detected_encoding}: "
            f"{replacement_count} byte(s) could not be mapped and were "
            f"replaced with U+FFFD. Set CopybookSearchPath.encoding "
            f"explicitly to silence this warning."
        )

    return text


def read_file_with_encoding(
    file_path: str,
    encoding_override: str | None = None,
    *,
    warnings: list[str] | None = None,
    encoding_errors: str = "replace",
) -> str:
    """
    Read a file with automatic encoding detection and UTF-8 conversion.

    Args:
        file_path: Path to file to read
        encoding_override: When provided, skip auto-detection and use this
            encoding directly.  Pass via ``CopybookSearchPath.encoding`` to
            force a specific EBCDIC variant for all copybooks in an expansion.
        warnings: Optional list that lossy-decode diagnostics are appended to.
        encoding_errors: Decode strictness — ``"replace"`` (default)
            substitutes undecodable bytes with U+FFFD and warns; ``"strict"``
            raises ``EncodingError`` with file/offset context.

    Returns:
        File content as UTF-8 string

    Raises:
        EncodingError: If file cannot be read or converted, or if
            ``encoding_errors="strict"`` and undecodable bytes are present

    Example:
        >>> content = read_file_with_encoding("employee.cpy")
        >>> print(content)
        01 EMPLOYEE-RECORD.
           05 EMPLOYEE-ID PIC 9(6).
    """
    encoding = (
        encoding_override
        if encoding_override is not None
        else detect_encoding(file_path)
    )

    try:
        with open(file_path, "rb") as f:
            raw_content = f.read()

        return convert_to_utf8(
            raw_content,
            encoding,
            source_label=file_path,
            warnings=warnings,
            errors=encoding_errors,
        )

    except EncodingError:
        raise
    except Exception as e:
        raise EncodingError(file_path, f"Failed to read file: {str(e)}") from e


def expand_copybooks(
    source_code: str,
    copybook_paths: list[str],
    max_nesting_depth: int = 100,
    preserve_source_locations: bool = False,
    validate_content: bool = True,
    validate_levels: bool = False,
    process_conditionals: bool = False,
    defined_symbols: dict[str, str] | None = None,
    max_file_size: int = MAX_COPYBOOK_SIZE_BYTES,
    max_total_size: int = MAX_TOTAL_EXPANSION_BYTES,
    path_resolver: "PathResolver | None" = None,
    encoding: str | None = None,
    encoding_errors: str = "replace",
) -> CopybookExpansion:
    """
    Expand all COPY statements in COBOL source code by inlining copybook content.

    This is the main entry point for copybook expansion. It recursively resolves
    nested COPY statements, detects circular references, validates content,
    and optionally preserves source location metadata for error tracing.

    Args:
        source_code: COBOL source code containing COPY statements
        copybook_paths: List of directory paths to search for copybooks
        max_nesting_depth: Maximum allowed nesting depth (default: 100)
        preserve_source_locations: Whether to track source locations (default: False)
        validate_content: Whether to validate copybook content (default: True)
        validate_levels: Whether to validate level number alignment (default: False)
        process_conditionals: Whether to process >>IF/>>DEFINE directives (default: False)
        defined_symbols: Pre-defined symbols for conditional compilation
        max_file_size: Maximum size per copybook file in bytes
        max_total_size: Maximum total expanded content size in bytes
        encoding: Optional explicit encoding for all copybook files (skips
            auto-detection; e.g. 'cp1047' or 'cp500' for a specific EBCDIC
            variant). When None (default), encoding is auto-detected per file.
        encoding_errors: Decode strictness for copybook files — "replace"
            (default, backward compatible) substitutes undecodable bytes with
            U+FFFD and records a lossy-decode warning in
            ``statistics.warnings``; "strict" raises ``EncodingError`` with
            file/offset context instead.

    Returns:
        CopybookExpansion object containing expanded source and metadata

    Raises:
        CircularReferenceError: If circular copybook dependency detected
        CopybookNotFoundError: If referenced copybook file not found
        PathTraversalError: If path validation fails
        NestingDepthError: If nesting depth exceeds maximum
        EncodingError: If file encoding cannot be detected or converted, or
            if ``encoding_errors="strict"`` and a copybook contains
            undecodable bytes
        ValueError: If ``encoding_errors`` is not "replace" or "strict"
        CopybookSizeExceededError: If a copybook exceeds the size limit
        TotalExpansionSizeExceededError: If total expanded size exceeds limit
        CopybookSyntaxError: If copybook content validation fails

    Example:
        >>> result = expand_copybooks(
        ...     source_code="COPY EMPLOYEE.",
        ...     copybook_paths=["/copybooks"]
        ... )
        >>> print(result.expanded_source)
        01 EMPLOYEE-RECORD.
           05 EMPLOYEE-ID PIC 9(6).
    """
    start_time = time.time()

    # Pre-process conditional compilation if requested
    conditional_warnings: list[str] = []
    if process_conditionals:
        source_code = preprocess_conditional_compilation(
            source_code, defined_symbols or {}, warnings=conditional_warnings
        )

    # Create search configuration
    search_config = CopybookSearchPath(
        directories=copybook_paths,
        max_nesting_depth=max_nesting_depth,
        max_file_size=max_file_size,
        max_total_size=max_total_size,
        encoding=encoding,
        encoding_errors=encoding_errors,
    )

    # Create path resolver -- but honor a caller-supplied one (its warm
    # resolution/directory-index caches are the whole point of passing it).
    if path_resolver is None:
        path_resolver = PathResolver(search_config)

    # Create expansion context
    context = ExpansionContext(
        current_file="<main>",
        expansion_stack=[],
        current_depth=0,
        defined_symbols=dict(defined_symbols) if defined_symbols else {},
    )

    # Initialize LRU size from search config
    context.max_cache_size = search_config.max_cache_entries

    # Initialize statistics
    stats = ExpansionStatistics()
    stats.file_count = 1  # Count main program
    stats.total_bytes_processed = len(source_code.encode("utf-8"))
    if conditional_warnings:
        stats.warnings.extend(conditional_warnings)

    # Track included copybooks
    included_copybooks: list[str] = []

    # Perform recursive expansion
    expanded_source, max_depth, is_normalized = _expand_source_recursive(
        source_code,
        "<main>",
        path_resolver,
        context,
        preserve_source_locations,
        included_copybooks,
        validate_content,
        validate_levels,
        process_conditionals,
        stats,
    )

    # Calculate statistics
    elapsed_ms = (time.time() - start_time) * 1000
    stats.parse_time_ms = elapsed_ms

    # Scan expanded lines to count them
    expanded_lines = expanded_source.splitlines()
    stats.total_lines = len(expanded_lines)
    stats.file_count = 1 + len(included_copybooks)  # Main + copybooks

    # If the result is normalized (stripped of sequence numbers), we must re-pad it
    # to ensure it is valid fixed-format COBOL for the parser/compiler.
    # If is_normalized is False, it means no changes were made (passthrough), so we return as-is.
    final_source = expanded_source
    if is_normalized:
        final_lines: list[str] = []
        for line in expanded_lines:
            if not line:
                final_lines.append(line)
            else:
                # Prepend 6 spaces for sequence area
                final_lines.append(" " * 6 + line)
        final_source = "\n".join(final_lines)
        if expanded_source.endswith("\n"):
            final_source += "\n"

    return CopybookExpansion(
        expanded_source=final_source,
        included_copybooks=included_copybooks,
        max_depth_reached=max_depth,
        source_location_map=context.source_maps if preserve_source_locations else None,
        statistics=stats,
    )


def _expand_source_recursive(
    source_code: str,
    source_file: str,
    path_resolver: PathResolver,
    context: ExpansionContext,
    preserve_locations: bool,
    included_copybooks: list[str],
    validate_content: bool = True,
    validate_levels: bool = False,
    process_conditionals: bool = False,
    stats: ExpansionStatistics | None = None,
    already_stripped: bool = False,
) -> tuple[str, int, bool]:
    """
    Recursively expand COPY statements in source code.

    Args:
        source_code: Source code to expand
        source_file: Name of current file (for location tracking)
        path_resolver: Path resolver for finding copybooks
        context: Expansion context for tracking state
        preserve_locations: Whether to preserve source locations
        included_copybooks: Accumulated list of included copybook paths
        validate_content: Whether to validate copybook content
        validate_levels: Whether to validate level number alignment
        process_conditionals: Whether to process conditional directives
        stats: Statistics object to update
        already_stripped: True when the caller has already run
            ``remove_comment_lines``/``strip_sequence_area`` on
            *source_code* (e.g. copybook content, normalized up front so
            REPLACING/conditional-compilation/validation never see the raw
            sequence-number or identification columns). Skips the redundant
            internal strip, which would otherwise double-strip and corrupt
            already-normalized text.

    Returns:
        Tuple of (expanded_source, max_depth_reached, is_normalized)
        is_normalized indicates if the returned source has had sequence numbers stripped.


    Raises:
        CircularReferenceError: If circular dependency detected
        NestingDepthError: If max nesting depth exceeded
        TotalExpansionSizeExceededError: If total size exceeds limit
    """
    # Check nesting depth
    if context.current_depth > path_resolver.search_config.max_nesting_depth:
        raise NestingDepthError(
            context.current_depth, path_resolver.search_config.max_nesting_depth
        )

    # Check for circular reference
    if context.stack_contains(source_file):
        # Build dependency chain for error message
        chain = context.expansion_stack + [source_file]
        raise CircularReferenceError(chain)

    # Normalize source for robust matching and expansion. We strip sequence
    # areas and comments to ensure the lexer works consistently. Skipped when
    # the caller (the copybook-content branch below) already did this, since
    # re-running strip_sequence_area on already-stripped text would eat 6
    # more real characters off the front of every line.
    if already_stripped:
        normalized_source = normalize_continuation_lines(
            source_code, indicator_position=0
        )
    else:
        source_no_comments = remove_comment_lines(source_code)
        source_stripped = strip_sequence_area(source_no_comments)
        # We must merge continuation lines to find statements split across lines
        normalized_source = normalize_continuation_lines(
            source_stripped, indicator_position=0
        )

    # Extract COPY statements using the robust lexer on normalized source
    lexer = CopyStatementLexer(normalized_source, source_file)
    copy_statements = lexer.tokenize_copy_statements()
    # Surface COPY statements the lexer recognized but had to drop (missing
    # terminating period, unterminated pseudo-text) — they are never expanded
    # and used to vanish silently (audit 2026-07-07 H6a/H6c).
    if stats is not None and lexer.warnings:
        stats.warnings.extend(lexer.warnings)

    # If no COPY statements, return source unchanged to preserve full fidelity.
    # is_normalized mirrors already_stripped here: if the caller already
    # stripped this content, it stays normalized even on this passthrough.
    if not copy_statements:
        return source_code, context.current_depth, already_stripped

    # Push current file onto stack

    context.stack_push(source_file)
    max_depth = context.current_depth

    # Process COPY statements in reverse order to maintain positions
    # We use the NORMALIZED source as the base for expansion because we need valid indices
    expanded_source = normalized_source
    for statement in reversed(copy_statements):
        # Find copybook file
        copybook_path = path_resolver.resolve(
            statement.member_name, statement.library_qualifier
        )

        # Check if we have a cached expansion (without nested COPY processing)
        # Note: We can only use cache for the same file + same replacements
        full_cache_key = context.get_cache_key(
            copybook_path, statement.replacing_clauses
        )

        expanded_copybook = context.cache_get(full_cache_key)
        if expanded_copybook is not None:
            nested_depth = context.current_depth + 1
            # A cache hit still inserts real content into the expansion
            # (diamond dependency: same member COPYd multiple times) -- it
            # must count toward total_bytes the same as a miss does, or
            # max_total_size silently under-enforces (M14).
            content_size = len(expanded_copybook.encode("utf-8"))
            context.total_bytes += content_size
            if stats:
                stats.total_bytes_processed = context.total_bytes
            if context.total_bytes > path_resolver.search_config.max_total_size:
                raise TotalExpansionSizeExceededError(
                    context.total_bytes, path_resolver.search_config.max_total_size
                )
        else:
            # Read copybook content with encoding detection (or forced override).
            # Lossy decodes are recorded in ExpansionStatistics.warnings so
            # callers see when bytes were silently replaced with U+FFFD.
            encoding_warnings: list[str] = stats.warnings if stats else []
            copybook_content = _cached_read_file(
                copybook_path,
                encoding_override=path_resolver.search_config.encoding,
                warnings=encoding_warnings,
                encoding_errors=path_resolver.search_config.encoding_errors,
            )

            # Update total bytes and check limit. Measured on the raw file
            # content (matching the on-disk size) before the strip below.
            content_size = len(copybook_content.encode("utf-8"))
            context.total_bytes += content_size
            if stats:
                stats.total_bytes_processed = context.total_bytes

            if context.total_bytes > path_resolver.search_config.max_total_size:
                raise TotalExpansionSizeExceededError(
                    context.total_bytes, path_resolver.search_config.max_total_size
                )

            # Strip the sequence-number (columns 1-6) and identification
            # (columns 73-80) areas, and blank comment lines, before anything
            # below inspects or rewrites this content. REPLACING/>>IF/
            # validation all operate on the program-text stream, which by
            # definition excludes those administrative columns. Doing this
            # *after* REPLACING (the previous order) let a length-changing
            # REPLACING move the column-72 boundary relative to the
            # original line: a shrinking replacement pulled identification
            # text into the kept window, and a growing one silently
            # truncated real code (including its terminating period).
            raw_copybook_content = copybook_content
            copybook_content = strip_sequence_area(
                remove_comment_lines(copybook_content)
            )

            # Validate copybook content if requested
            if validate_content:
                warnings = validate_copybook_content(
                    copybook_content,
                    copybook_path,
                    raw_content=raw_copybook_content,
                )
                if stats and warnings:
                    stats.warnings.extend(warnings)

            # Validate level number alignment if requested
            if validate_levels:
                # Get context before the COPY statement
                statement_start = expanded_source.find(statement.original_text)
                if statement_start != -1:
                    pre_context = expanded_source[:statement_start]
                    level_warnings = validate_level_numbers(
                        pre_context, copybook_content, copybook_path
                    )
                    if stats and level_warnings:
                        stats.warnings.extend(level_warnings)

            # Process conditional compilation directives if requested
            if process_conditionals:
                copybook_content = preprocess_conditional_compilation(
                    copybook_content,
                    context.defined_symbols,
                    warnings=stats.warnings if stats is not None else None,
                )

            # Track this copybook
            if copybook_path not in included_copybooks:
                included_copybooks.append(copybook_path)

            # Apply REPLACING clause if present (using enhanced function).
            # copybook_content is already stripped (indicator at index 0).
            if statement.replacing_clauses:
                copybook_content = apply_replacing_clauses(
                    copybook_content,
                    statement.replacing_clauses,
                    indicator_position=0,
                )

            # Handle SUPPRESS clause (for listing control - we still include the content)
            # SUPPRESS is mainly for compiler listing output, not actual code inclusion
            # We note it in metadata but don't change the expansion behavior

            # Recursively expand nested COPY statements
            context.current_depth += 1
            context.current_file = copybook_path

            expanded_copybook, nested_depth, nested_normalized = (
                _expand_source_recursive(
                    copybook_content,
                    copybook_path,
                    path_resolver,
                    context,
                    preserve_locations,
                    included_copybooks,
                    validate_content,
                    validate_levels,
                    process_conditionals,
                    stats,
                    already_stripped=True,
                )
            )

            # copybook_content was already stripped above, so nested_normalized
            # is always True here; this fixup is kept as a defensive no-op in
            # case that invariant ever changes.
            if not nested_normalized:
                nested_no_comments = remove_comment_lines(expanded_copybook)
                nested_stripped = strip_sequence_area(nested_no_comments)
                expanded_copybook = normalize_continuation_lines(
                    nested_stripped, indicator_position=0
                )

            context.current_depth -= 1
            context.current_file = source_file

            # Cache the fully expanded result using LRU-aware method
            context.cache_put(full_cache_key, expanded_copybook)

        max_depth = max(max_depth, nested_depth)

        # Replace COPY statement with expanded content
        # Find statement in source
        # Replace COPY statement with expanded content
        # We use strict index-based replacement from the lexer tokens
        # Since we iterate in reverse, indices remain valid
        statement_start = statement.start_index
        statement_end = statement.end_index

        # Track source locations if requested
        if preserve_locations and statement.source_location:
            _, line_num, _ = statement.source_location
            # Note: With normalized source, line mapping is approximate or requires new logic
            # For now we skip or approximate logic if needed (disabled by default in expander)
            pass

        expanded_source = (
            expanded_source[:statement_start]
            + expanded_copybook
            + expanded_source[statement_end:]
        )

    # Pop current file from stack
    # Pop current file from stack
    context.stack_pop()

    # Return normalized source (we don't pad here to avoid double-padding during recursion)
    return expanded_source, max_depth, True


__all__ = [
    "detect_encoding",
    "convert_to_utf8",
    "read_file_with_encoding",
    "expand_copybooks",
    "parse_cobol_with_expansion",
    "clear_file_cache",
    "set_file_cache_size",
    "get_file_cache_stats",
]


def parse_cobol_with_expansion(
    source_code: str,
    filename: str,
    copybook_paths: list[str],
    max_nesting_depth: int = 100,
    process_conditionals: bool = False,
    defined_symbols: dict[str, str] | None = None,
    **parser_kwargs: Any,
) -> Any:
    """
    Convenience function that expands copybooks and parses in one step.

    This function combines copybook expansion with COBOL parsing, providing
    a seamless workflow for parsing COBOL programs with copybook dependencies.

    Args:
        source_code: COBOL source code containing COPY statements
        filename: Source filename for error reporting
        copybook_paths: List of directory paths to search for copybooks
        max_nesting_depth: Maximum allowed nesting depth (default: 100)
        process_conditionals: Whether to process >>DEFINE/>>IF/>>EVALUATE
            conditional compilation directives before parsing (default: False)
        defined_symbols: Pre-defined symbols for conditional compilation
        **parser_kwargs: Additional arguments passed to parse_cobol()

    Returns:
        ParseResult from the COBOL parser with expanded source

    Raises:
        CircularReferenceError: If circular copybook dependency detected
        CopybookNotFoundError: If referenced copybook file not found
        ParseError: If parsing fails after expansion

    Example:
        >>> from cobolparser.preprocess import parse_cobol_with_expansion
        >>> result = parse_cobol_with_expansion(
        ...     source_code="COPY EMPLOYEE.",
        ...     filename="payroll.cbl",
        ...     copybook_paths=["/copybooks"]
        ... )
        >>> print(result.ast.program_name)
    """
    # Import here to avoid circular dependency
    from ..parser import parse_cobol

    # Expand copybooks first
    expansion = expand_copybooks(
        source_code=source_code,
        copybook_paths=copybook_paths,
        max_nesting_depth=max_nesting_depth,
        preserve_source_locations=False,  # Parser will track its own locations
        process_conditionals=process_conditionals,
        defined_symbols=defined_symbols,
    )

    # Parse the expanded source
    parse_result = parse_cobol(
        source=expansion.expanded_source, filename=filename, **parser_kwargs
    )

    # With enable_profiling=True, parse_cobol returns
    # (ParseResult, ProfilingResult) — the warnings live on the first element.
    result_obj = parse_result[0] if isinstance(parse_result, tuple) else parse_result

    # Propagate expansion warnings (lossy encoding decodes, copybook content
    # validation, level-number mismatches). They lived only on the discarded
    # CopybookExpansion object before, so callers of this convenience entry
    # point never saw them.
    expansion_warnings = list(getattr(expansion.statistics, "warnings", []) or [])
    for warning in expansion_warnings:
        if warning not in result_obj.warnings:
            result_obj.warnings.append(warning)

    return parse_result
