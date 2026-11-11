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

import codecs
import os
import re
import time
from collections import OrderedDict
from typing import Any

from .._lines import split_source_lines
from .._source_directive import free_format_flags
from .._source_text.normalize import (
    CircularReferenceError,
    CopybookNotFoundError,
    EncodingError,
    NestingDepthError,
    TotalExpansionSizeExceededError,
    preprocess_conditional_compilation,
    validate_copybook_content,
    validate_level_numbers,
)
from .copy_statement_parser import (
    CopyStatementLexer,
    _open_literal_quote,
    apply_replacing_clauses,
    is_comment_line,
    normalize_continuation_lines,
    remove_comment_lines,
    strip_sequence_area,
)
from .models import (
    MAX_COPYBOOK_SIZE_BYTES,
    MAX_TOTAL_EXPANSION_BYTES,
    PRECOMPILER_MEMBERS,
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
#: key -> (content, encoding warnings, (mtime_ns, size) stamp at read time)
_FILE_CONTENT_CACHE: OrderedDict[
    str, tuple[str, tuple[str, ...], tuple[int, int] | None]
] = OrderedDict()
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

    # The file's (mtime_ns, size) is stored beside the content and compared
    # on every hit, so an edit on disk invalidates the entry: the cache is
    # process-wide and never cleared between calls, and a stale hit fed a
    # long-lived process (an editor extension, a batch run) the old member
    # for as long as it lived.
    stamp = _file_stamp(file_path)
    cache_key = f"{file_path}::{encoding_override or 'auto'}::{encoding_errors}"
    cached = _FILE_CONTENT_CACHE.get(cache_key)
    if cached is not None and cached[2] == stamp:
        _FILE_CONTENT_CACHE.move_to_end(cache_key)
        _FILE_CONTENT_CACHE_HITS += 1
        content, cached_warnings, _ = cached
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

    # LRU eviction (a stale entry being replaced does not count as one)
    if cached is not None:
        del _FILE_CONTENT_CACHE[cache_key]
    elif len(_FILE_CONTENT_CACHE) >= _FILE_CONTENT_CACHE_MAX:
        _FILE_CONTENT_CACHE.popitem(last=False)
        _FILE_CONTENT_CACHE_EVICTIONS += 1
    _FILE_CONTENT_CACHE[cache_key] = (content, tuple(fresh_warnings), stamp)
    return content


def _file_stamp(file_path: str) -> tuple[int, int] | None:
    """``(st_mtime_ns, st_size)`` of *file_path*, or None when it cannot be
    stat-ed (the read below reports the real error; an unstat-able file is
    simply never served from cache)."""
    try:
        st = os.stat(file_path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


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


def _single_byte_codec(prefix: bytes) -> str:
    """The codec for ASCII-shaped text that is *not* valid UTF-8.

    Such a file carries bytes >= 0x80 that are not UTF-8 sequences -- in
    practice a Windows / Micro Focus shop's cp1252 (or ISO-8859-1) copybook,
    with an accented ``VALUE 'CAFÉ'`` or a ``€`` in a comment. It used to be
    labelled ``'ascii'``, which cannot represent a single one of those bytes:
    every accented character was silently turned into U+FFFD (and, under
    ``encoding_errors="strict"``, the whole expansion failed). cp1252 is a
    superset of ISO-8859-1's printable range; the five bytes it leaves
    undefined fall back to latin-1, which maps every byte.
    """
    if prefix.isascii():
        return "ascii"
    try:
        prefix.decode("cp1252")
    except UnicodeDecodeError:
        return "latin-1"
    return "cp1252"


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
        EBCDIC, 'cp1252' / 'latin-1' for 8-bit ASCII-shaped text that is not
        valid UTF-8, or 'ascii')

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
        return "utf-8" if utf8_text is not None else _single_byte_codec(prefix)

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

    return "utf-8" if utf8_text is not None else _single_byte_codec(prefix)


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
            return _normalize_record_separators(
                content.decode(detected_encoding, errors="strict"), detected_encoding
            )
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

    return _normalize_record_separators(text, detected_encoding)


def read_program_source(
    file_path: str,
    encoding: str | None = None,
    *,
    warnings: list[str] | None = None,
    encoding_errors: str = "replace",
) -> str:
    """Read a *program* source the way a copybook is read (#522).

    *encoding* None (or ``"auto"``) detects it (:func:`detect_encoding`), so a
    cp1252 / Latin-1 program decodes like a cp1252 copybook instead of being
    refused as "not valid UTF-8" by one entry point and silently mangled to
    U+FFFD by another. A named *encoding* is used as given. A lossy decode
    appends a warning to *warnings*; ``encoding_errors="strict"`` raises
    ``EncodingError`` instead. Every entry point that reads a main program
    (the CLI, ``batch``, ``scan``, ``codebase-graph``, the MCP server) goes
    through here, so they cannot disagree about a file's text or lines.
    """
    override = None if encoding in (None, "", "auto") else encoding
    if override is not None:
        try:
            codecs.lookup(override)
        except LookupError as exc:
            # convert_to_utf8 would quietly fall back to ASCII on a typo.
            raise EncodingError(file_path, f"unknown encoding {override!r}") from exc
    collected: list[str] = []
    text = read_file_with_encoding(
        file_path,
        override,
        warnings=collected,
        encoding_errors=encoding_errors,
    )
    if warnings is not None:
        warnings.extend(
            warning.replace(
                "Set CopybookSearchPath.encoding explicitly",
                "Name the source encoding explicitly (--encoding)",
            )
            for warning in collected
        )
    # Every reader this replaced opened the file in text mode, which turns
    # CR LF and a lone CR into LF; keep that, so a Windows-edited program's
    # text (``expand``'s ``expanded_source``, the MCP parse, a COPY scan) does
    # not start carrying CRs. Line numbers are unchanged: split_source_lines
    # breaks on all three the same way.
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _is_ebcdic_codec(encoding: str) -> bool:
    """True when *encoding* names an EBCDIC code page (cp037, cp500,
    cp1047, cp273, cp1140, ...). Decided by what the codec does to the
    bytes of ``ABC`` rather than by a list of names, so a variant this
    module never heard of is classified correctly too."""
    try:
        return b"\xc1\xc2\xc3".decode(encoding) == "ABC"
    except (LookupError, UnicodeDecodeError):
        return False


def _normalize_record_separators(text: str, encoding: str) -> str:
    """Turn the EBCDIC NL record separator into ``\\n``.

    On z/OS a text member's records end in NL (0x15), which every EBCDIC
    codec decodes to U+0085 -- a character no line splitter downstream
    (``split("\\n")`` in the sequence-area / comment / continuation
    passes) treats as a line break, so the whole member read as ONE
    72-column line and everything past the first record was silently
    cut. ``detect_encoding`` already scores 0x15 as the EBCDIC newline;
    this makes the decoded text agree with it. LF (0x25 -> ``\\n``) and
    CR LF (0x0D 0x25) records were already fine and are untouched; a CR NL
    pair collapses to one break. ASCII/UTF-8 text is never rewritten:
    U+0085 there is ordinary (if odd) text, not a record boundary.
    """
    if "\x85" not in text or not _is_ebcdic_codec(encoding):
        return text
    return text.replace("\r\x85", "\n").replace("\x85", "\n")


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
        debug_lines: Keep debugging lines (``D`` in column 7) as code
            (default False), for a parse with ``debug_lines=True``: expansion
            otherwise blanks them with the comments, and the parser never
            sees them. While False, the ones blanked are listed in
            ``CopybookExpansion.dropped_debug_lines`` so the parse can still
            warn about them under ``WITH DEBUGGING MODE``.
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


#: Last column of the fixed-format code area (inclusive, 1-based). Re-padded
#: expansion output must fit within it -- the final parse's fixed-format
#: slice (``normalize_fixed_format``) silently drops anything past it.
_CODE_AREA_WIDTH = 72

#: First 0-based index the squeeze/wrap passes may touch: the re-added
#: 6-character sequence area plus the indicator column (7 chars total) stay
#: untouched so the emitted line keeps valid fixed-format column semantics.
_CONTENT_START_IDX = 7


def _blank_runs_outside_literals(line: str, start: int) -> list[tuple[int, int]]:
    """Scan *line* from *start*, tracking alphanumeric-literal quote state.

    Returns every maximal run of two or more blanks that sits outside any
    quoted literal (as ``(index, length)`` pairs, in order). A doubled quote
    inside a literal toggles the state twice, leaving it open -- exactly
    COBOL's escape convention.
    """
    runs: list[tuple[int, int]] = []
    quote: str | None = None
    i = start
    n = len(line)
    while i < n:
        ch = line[i]
        if quote is not None:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == " ":
            j = i
            while j < n and line[j] == " ":
                j += 1
            if j - i >= 2:
                runs.append((i, j - i))
            i = j
            continue
        i += 1
    return runs


def _rightmost_safe_blank(line: str, start: int, after: int, limit: int) -> int | None:
    """Rightmost blank index in ``(after, limit]`` outside any quoted literal.

    Same quote-state tracking as :func:`_blank_runs_outside_literals`, but
    scanning stops at *limit*: quote state at an index depends only on the
    characters before it, so nothing past *limit* can change which of the
    candidate blanks are safe. That bound is what keeps the wrap loop in
    :func:`_fit_fixed_format_width` linear -- each iteration scans at most
    ``limit`` characters of the (possibly much longer) remaining tail
    instead of all of it.
    """
    best: int | None = None
    quote: str | None = None
    i = start
    n = min(len(line), limit + 1)
    while i < n:
        ch = line[i]
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == " " and i > after:
            best = i
        i += 1
    return best


def _fit_fixed_format_width(line: str) -> list[str]:
    """Fit a re-padded expansion line back inside the 72-column code area.

    A ``COPY ... REPLACING`` whose replacement text is longer than what it
    replaces (e.g. ``==:LKPCB:== BY ==LKPCB-PCB1==``, +3 characters per
    occurrence) lengthens the line it lands on; once this module re-pads the
    normalized text with a 6-character sequence area, that overflow sits
    past column 72 -- where ``normalize_fixed_format`` in the final parse
    silently drops it. The classic casualty is a data item's terminating
    period, whose loss merges the item into its neighbor.

    Two passes, both quote-aware (never touching the inside of an
    alphanumeric literal) and both leaving the 7-column sequence/indicator
    prefix intact:

    1. **Squeeze** -- shrink interior multi-blank runs, rightmost first,
       each down to no less than a single blank, until the line fits.
       Blanks are only separators in COBOL, and the alignment padding
       between a data name and its PIC clause almost always has enough
       slack, so this usually suffices -- and it keeps the line count (and
       with it every following line's number) unchanged.
    2. **Wrap** -- if squeezing alone cannot fit the line, break it at the
       rightmost safe blank within the width and continue on a fresh
       Area-B line (a new physical line, so later line numbers shift by
       one -- the cost of not corrupting the statement).

    3. **Continue a literal** -- when the only way to fit is inside an
       alphanumeric literal still open at column 72 (a long ``VALUE`` that
       arrived as one logical line, since the expander merges continuation
       records before splicing), the literal is split the way it would be
       written by hand: the head runs to column 72 with the literal left
       open, and the rest resumes on a continuation line (``-`` in column 7)
       whose Area-B text starts with the literal's quote. The wrap in pass 2
       is skipped in favour of this when its tail would not fit anyway.

    A line with no break point at all (a single 65+-character token outside
    any literal) is returned unchanged; the final parse's existing column-72
    overflow warning then reports the drop.
    """
    stripped = line.rstrip()
    if len(stripped) <= _CODE_AREA_WIDTH:
        return [line]

    runs = _blank_runs_outside_literals(stripped, _CONTENT_START_IDX)
    excess = len(stripped) - _CODE_AREA_WIDTH
    # Shrink rightmost runs first: trailing alignment padding (before a
    # PIC clause, a VALUE literal, ...) is the least meaningful layout.
    # Editing right-to-left keeps every earlier run's indices valid, so
    # the string can be cut in place per run.
    for idx, length in reversed(runs):
        if excess <= 0:
            break
        take = min(length - 1, excess)
        stripped = stripped[: idx + length - take] + stripped[idx + length :]
        excess -= take

    if len(stripped) <= _CODE_AREA_WIDTH:
        return [stripped]

    # Wrap: break at the rightmost safe blank that keeps the head within
    # the code area, and continue on a fresh Area-B line. Loop for the
    # (pathological) case of a tail that is itself still too long.
    out: list[str] = []
    while len(stripped) > _CODE_AREA_WIDTH:
        # The break point must fall *after* the line's first non-blank
        # character, so the head always carries real content -- a break
        # inside the leading pad (which a wrapped tail's own fresh 11-space
        # prefix re-creates every iteration) would emit an empty head and
        # loop forever on the same tail.
        content_start = len(stripped) - len(stripped.lstrip())
        # ``head = stripped[:break_at]`` has length ``break_at``, so a break
        # at index ``_CODE_AREA_WIDTH`` (72) yields a head of exactly 72
        # characters -- still fully inside the code area. Capping one lower
        # left a token ending exactly at column 72 unsplittable, silently
        # dropping its tail past the slice -- the very defect this helper
        # exists to prevent.
        break_at = _rightmost_safe_blank(
            stripped, _CONTENT_START_IDX, content_start, _CODE_AREA_WIDTH
        )
        literal_split = _split_open_literal(stripped, content_start)
        if break_at is None:
            if literal_split is not None:
                out.append(literal_split[0])
                stripped = literal_split[1]
                continue
            # No safe break point: emit as-is and let the final parse's
            # column-overflow warning report the drop.
            out.append(stripped)
            return out
        head = stripped[:break_at].rstrip()
        tail = stripped[break_at:].lstrip()
        # 6-char sequence area + blank indicator + 4-space indent: the
        # continuation content starts at column 12, safely inside Area B.
        # (head is never empty: the content_start filter above guarantees
        # the break lands after the first non-blank character.)
        next_line = " " * 11 + tail
        if literal_split is not None and len(next_line) > _CODE_AREA_WIDTH:
            # The wrapped tail would still need its literal continued, so
            # continue it here instead and spend one line fewer.
            out.append(literal_split[0])
            stripped = literal_split[1]
            continue
        if len(next_line) >= len(stripped):
            # No forward progress possible (e.g. the tail is a single
            # unbreakable 62+-character token): emit as-is rather than
            # loop, same escape hatch as the no-break-point case above.
            out.append(stripped)
            return out
        out.append(head)
        stripped = next_line
    out.append(stripped)
    return out


#: Sequence area, ``-`` continuation indicator and a 4-blank indent: the
#: continued literal resumes at column 12, inside Area B.
_LITERAL_CONTINUATION_PREFIX = " " * 6 + "-" + " " * 4


def _split_open_literal(line: str, content_start: int) -> tuple[str, str] | None:
    """Split *line* inside the alphanumeric literal open at column 72.

    Returns ``(head, continuation)``: *head* is the line through column 72
    with the literal left open (its trailing blanks are literal content and
    are kept), *continuation* a ``-`` continuation record resuming the
    literal with its opening quote. ``None`` when no literal is open at
    column 72.

    The split point moves one column left when column 72 holds the first
    quote of a doubled-quote escape: cutting there would read as the
    literal's close. Splitting *between* the two quotes is fine -- the
    continuation's leading quote is dropped when the lines are merged, so
    the second quote of the pair survives.
    """
    for cut in (_CODE_AREA_WIDTH, _CODE_AREA_WIDTH - 1):
        if cut <= content_start:
            return None
        quote = _open_literal_quote(line[_CONTENT_START_IDX:cut])
        if quote is not None:
            return line[:cut], _LITERAL_CONTINUATION_PREFIX + quote + line[cut:]
    return None


# --- Source map -------------------------------------------------------------
#
# Every step between the program on disk and the expanded text either
# preserves line numbers (comment blanking, sequence-area strip), merges lines
# (continuation joining), inserts them (the COPY splice) or splits one into
# several (the re-pad's width wrap). A ``LineOrigin`` per expanded line rides
# through all four, so a consumer handed the expansion can move a line number
# reported against it back onto the file a human actually edits -- previously
# impossible, which is why every downstream tool re-anchored findings by
# searching for the name they were about.
#
# It is computed unconditionally (one tuple per line, negligible beside the
# expansion itself) and surfaced only when the caller passes
# ``preserve_source_locations=True``.

LineOrigin = tuple[str, int]


def _looks_fixed_format(text: str, default: bool = True) -> bool:
    """Whether *text* uses the fixed-format column layout.

    The single member detector,
    :func:`~.._source_text.source_format.detect_member_fixed_format`: every
    non-blank line votes, a valid column-7 indicator counts as fixed whatever
    columns 1-6 hold, and a tie goes to *default* (the including program's
    format; fixed when there is none). Tabs are expanded first, as every
    column-sensitive step here does.
    """
    from .._source_text.source_format import detect_member_fixed_format

    return detect_member_fixed_format(text.expandtabs(8), default=default)


def _looks_program_fixed(text: str) -> bool:
    """Whether a *program* uses the fixed-format column layout.

    The verdict the final parse reaches (:func:`detect_fixed_format`), so
    expansion and parse agree; that sampler declines to judge fewer than
    three non-blank lines, which are left to the member detector instead.
    """
    from .._source_text.source_format import detect_fixed_format

    text = text.expandtabs(8)
    if sum(1 for line in split_source_lines(text) if line.strip()) >= 3:
        return detect_fixed_format(text)
    return _looks_fixed_format(text)


def _identity_origins(source_file: str, text: str) -> list[LineOrigin]:
    """One origin per line of *text*, each naming its own line in *source_file*."""
    return [(source_file, n) for n in range(1, text.count("\n") + 2)]


def _fit_origins(
    origins: list[LineOrigin], line_count: int, fallback: LineOrigin
) -> list[LineOrigin]:
    """Force *origins* to exactly *line_count* entries.

    Defensive: every producer below keeps the two in step, but a map that has
    drifted must not be able to mis-attribute a line (or raise). Extra entries
    are dropped; missing ones repeat the last known origin, or *fallback* when
    there is none.
    """
    if len(origins) == line_count:
        return origins
    if len(origins) > line_count:
        return origins[:line_count]
    tail = origins[-1] if origins else fallback
    return origins + [tail] * (line_count - len(origins))


def _wrapped_origins(
    origin: LineOrigin, next_origin: LineOrigin | None, count: int
) -> list[LineOrigin]:
    """Origins for the *count* pieces one expanded line was wrapped into.

    A logical line merged from continuation records starts at *origin* and
    absorbed every physical line before the next line's origin (comment and
    blank lines are blanked in place, never removed, so they keep origins of
    their own). Piece k is attributed to record ``origin + k``, capped at the
    last absorbed one; with nothing absorbed every piece shares *origin*.
    """
    file_name, first = origin
    last = first
    if next_origin is not None and next_origin[0] == file_name:
        last = max(first, next_origin[1] - 1)
    return [(file_name, min(first + k, last)) for k in range(count)]


def _restore_comment_lines(
    lines: list[str],
    origins: list[LineOrigin],
    sources: dict[str, list[str]],
) -> list[str]:
    """Put each blanked comment line's original text back, in place.

    Expansion blanks every comment line before it starts, and it has to: the
    COPY scanner works on the program-text stream, and a ``COPY`` written
    inside a comment must not be expanded. The line survives as spaces, so
    numbering holds -- but the text is gone, which for a *listing* (as opposed
    to input for the lexer) throws away exactly what a reader most wants to
    keep.

    The source map is what makes putting it back possible: each output line
    names the file and line it came from, so the original text can be read
    back out of that file. Only a line that is now blank AND whose origin
    really is a comment line is restored, so nothing this pass does can
    change a line of code.
    """
    restored: list[str] = []
    # strict=False deliberately: _fit_origins keeps the two in step, and a
    # map that somehow drifted must lose a comment, not raise mid-expansion.
    for line, origin in zip(lines, origins, strict=False):
        if line.strip():
            restored.append(line)
            continue
        origin_lines = sources.get(origin[0])
        if origin_lines is None or not 0 < origin[1] <= len(origin_lines):
            restored.append(line)
            continue
        original = origin_lines[origin[1] - 1]
        restored.append(original if is_comment_line(original) else line)
    return restored


def _origin_sources(
    source_file: str,
    source_code: str,
    included_copybooks: list[str],
    search_config: CopybookSearchPath,
    warnings: list[str],
) -> dict[str, list[str]]:
    """Every file the source map can name, as its own lines.

    The copybooks come back through the same content cache the expansion just
    read them from, so this costs no disk I/O in the normal case, and reads
    them exactly as the expansion did (same encoding detection, same errors
    policy) -- a comment restored from a differently-decoded read would be a
    different string. A file that has become unreadable since is skipped: a
    listing missing one member's comments beats an expansion that fails.
    """
    # split_source_lines, not split("\n"): the source map numbers lines the
    # same way, so a CR-only file must not read back as one line, and a CRLF
    # file must not hand back each comment with a stray "\r" (#581).
    sources: dict[str, list[str]] = {source_file: split_source_lines(source_code)}
    for path in included_copybooks:
        try:
            content = _cached_read_file(
                path,
                encoding_override=search_config.encoding,
                warnings=warnings,
                encoding_errors=search_config.encoding_errors,
            )
        except (OSError, EncodingError):
            continue
        sources[path] = split_source_lines(content)
    return sources


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
    source_file: str = "<main>",
    preserve_comments: bool = False,
    debug_lines: bool = False,
    skip_missing_copybooks: bool = False,
    source_format: str = "auto",
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
        source_file: Name recorded for the main program's own lines in the
            source map (default "<main>"). Pass the real path when the caller
            has one, so a mapped line names a file a reader can open.
        preserve_comments: Put each comment line's original text back into the
            expanded output (default False). Expansion always blanks comments
            first -- a ``COPY`` written inside one must not be expanded -- and
            without this the listing keeps their line numbers but not their
            text. Restoration happens after every substitution, so it changes
            no line of code; it is for output meant to be *read*, and the
            parse pipeline (which drops comments again) is unaffected.
        debug_lines: Keep debugging lines (``D`` in column 7) as code
            (default False), for a parse with ``debug_lines=True``: expansion
            otherwise blanks them with the comments, and the parser never
            sees them. While False, the ones blanked are listed in
            ``CopybookExpansion.dropped_debug_lines`` so the parse can still
            warn about them under ``WITH DEBUGGING MODE``.
        skip_missing_copybooks: Leave a COPY whose member cannot be found as
            written, with a warning in ``statistics.warnings``, instead of
            raising ``CopybookNotFoundError`` (default False). Every member
            that *can* be found is still expanded; the parser then reports
            the one left behind as not expanded.
        source_format: ``"auto"`` (default) detects the format of the
            program and of each member on its own; ``"fixed"`` reads them
            all as fixed format, whatever their columns 1-6 hold -- the
            ``--source-format fixed`` / cobol.yml ``source_format: fixed``
            setting, which used to reach the main program only.
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
    # The symbol table after each >>DEFINE in the program, so every COPY is
    # expanded with the symbols defined above it (see _symbols_at_line).
    define_log: list[tuple[int, dict[str, str]]] | None = None
    if process_conditionals:
        define_log = []
        source_code = preprocess_conditional_compilation(
            source_code,
            defined_symbols or {},
            warnings=conditional_warnings,
            keep_source_format_directives=True,
            define_log=define_log,
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
        current_file=source_file,
        expansion_stack=[],
        current_depth=0,
        defined_symbols=dict(defined_symbols) if defined_symbols else {},
        debug_lines=debug_lines,
        skip_missing=skip_missing_copybooks,
        source_format=source_format,
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
    expanded_source, max_depth, is_normalized, origins = _expand_source_recursive(
        source_code,
        source_file,
        path_resolver,
        context,
        preserve_source_locations,
        included_copybooks,
        validate_content,
        validate_levels,
        process_conditionals,
        stats,
        define_log=define_log,
    )

    # Calculate statistics
    elapsed_ms = (time.time() - start_time) * 1000
    stats.parse_time_ms = elapsed_ms

    # Scan expanded lines to count them
    expanded_lines = split_source_lines(expanded_source)
    stats.total_lines = len(expanded_lines)
    stats.file_count = 1 + len(included_copybooks)  # Main + copybooks

    # If the result is normalized (stripped of sequence numbers), we must re-pad it
    # to ensure it is valid fixed-format COBOL for the parser/compiler.
    # If is_normalized is False, it means no changes were made (passthrough), so we return as-is.
    final_source = expanded_source
    dropped_debug_lines: list[LineOrigin] = []
    line_origins = _fit_origins(origins, len(expanded_lines), (source_file, 1))
    if is_normalized:
        final_lines: list[str] = []
        final_origins: list[LineOrigin] = []
        # A line after ``>>SOURCE FORMAT IS FREE`` is free format: it was
        # never cut to the code area (strip_sequence_area), so it is not
        # re-padded or wrapped either -- the final parse reads it whole.
        free_flags = (
            free_format_flags(expanded_lines, indicator_position=0)
            if ">>" in expanded_source
            else None
        )
        # Length-matched by _fit_origins just above; see _restore_comment_lines
        # for why this stays non-strict.
        for index, (line, origin) in enumerate(
            zip(expanded_lines, line_origins, strict=False)
        ):
            if not line or (free_flags is not None and free_flags[index]):
                final_lines.append(line)
                final_origins.append(origin)
                continue
            # Prepend 6 spaces for sequence area. A REPLACING clause
            # that lengthens its replaced text (e.g. ==:LKPCB:== BY
            # ==LKPCB-PCB1==, +3 chars) can push a line's tail -- often
            # a data item's terminating period -- past column 72, where
            # the final parse's fixed-format slice silently drops it.
            # _fit_fixed_format_width squeezes/wraps such a line back
            # within the 72-column code area (see its docstring). The
            # length guard keeps the overwhelmingly common in-width case
            # a plain append -- no helper call, no rstrip copy, no
            # throwaway single-element list per line.
            padded = " " * 6 + line
            if len(padded) <= _CODE_AREA_WIDTH:
                final_lines.append(padded)
                final_origins.append(origin)
            else:
                # A wrap turns one line into several; every piece came from the
                # same place, so they share its origin -- unless the line was
                # merged from continuation records, in which case piece k
                # maps to the k-th of those records (never past the last).
                wrapped = _fit_fixed_format_width(padded)
                final_lines.extend(wrapped)
                final_origins.extend(
                    _wrapped_origins(
                        origin,
                        (
                            line_origins[index + 1]
                            if index + 1 < len(line_origins)
                            else None
                        ),
                        len(wrapped),
                    )
                )
        line_origins = final_origins
        if not debug_lines:
            dropped_debug_lines = _blanked_debug_lines(
                final_lines,
                line_origins,
                source_file,
                source_code,
                included_copybooks,
                search_config,
                stats.warnings,
            )
        if preserve_comments:
            final_lines = _restore_comment_lines(
                final_lines,
                line_origins,
                _origin_sources(
                    source_file,
                    source_code,
                    included_copybooks,
                    search_config,
                    stats.warnings,
                ),
            )
        final_source = "\n".join(final_lines)
        if expanded_source.endswith("\n"):
            final_source += "\n"
        # The wrap fallback can add lines after the count above was taken;
        # keep the documented "total lines in the expanded output" invariant
        # true against the source actually returned.
        stats.total_lines = len(final_lines)

    # `source_maps` is the context's own accumulator; filling it from the
    # per-line origins is what finally makes `preserve_source_locations` mean
    # something -- until now the flag returned an always-empty dict.
    if preserve_source_locations:
        context.source_maps = {
            index + 1: origin for index, origin in enumerate(line_origins)
        }

    return CopybookExpansion(
        expanded_source=final_source,
        included_copybooks=included_copybooks,
        max_depth_reached=max_depth,
        source_location_map=context.source_maps if preserve_source_locations else None,
        statistics=stats,
        dropped_debug_lines=dropped_debug_lines,
    )


def _blanked_debug_lines(
    lines: list[str],
    origins: list[LineOrigin],
    source_file: str,
    source_code: str,
    included_copybooks: list[str],
    search_config: CopybookSearchPath,
    warnings: list[str],
) -> list[LineOrigin]:
    """Origins of the debugging lines expansion blanked as comments.

    Read off the output rather than counted while expanding, so a member
    included twice (a content-cache hit) counts twice, as it compiles. A
    line counts when it is blank now and its origin is a ``D`` line. Only
    looked for when a ``DEBUGGING`` clause is anywhere in the expanded
    text: without one, the parse has nothing to warn about.
    """
    if not _DEBUGGING_RE.search("\n".join(lines)):
        return []
    from .._source_text.source_format import debug_line_numbers

    debug_lines: dict[str, set[int]] = {}
    sources = _origin_sources(
        source_file, source_code, included_copybooks, search_config, warnings
    )
    for name, text in sources.items():
        numbers = debug_line_numbers(text)
        if numbers:
            debug_lines[name] = set(numbers)
    if not debug_lines:
        return []
    return [
        origin
        for line, origin in zip(lines, origins, strict=False)
        if not line.strip() and origin[1] in debug_lines.get(origin[0], ())
    ]


#: Whether a text can hold ``WITH DEBUGGING MODE`` at all.
_DEBUGGING_RE = re.compile(r"\bDEBUGGING\b", re.IGNORECASE)


def _symbols_at_line(
    define_log: list[tuple[int, dict[str, str]]], line: int
) -> dict[str, str]:
    """The conditional-compilation symbols in effect on *line*: the last
    ``define_log`` snapshot taken on an earlier line (see
    ``preprocess_conditional_compilation(define_log=...)``)."""
    current = define_log[0][1]
    for logged_line, symbols in define_log:
        if logged_line >= line:
            break
        current = symbols
    return current


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
    free_form: bool | None = None,
    define_log: list[tuple[int, dict[str, str]]] | None = None,
    initial_origins: list[LineOrigin] | None = None,
) -> tuple[str, int, bool, list[LineOrigin]]:
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
        free_form: True when *source_code* is free-form (no sequence,
            indicator or identification columns): nothing is stripped or
            merged, and the result is never re-padded. None (the default)
            detects it from the text; the copybook branch passes each
            member's own verdict down.
        define_log: The ``define_log`` that conditional-compilation
            processing of *source_code* produced (``process_conditionals``
            only): each COPY's member is processed with the symbols in effect
            on the COPY's own line, not the ones the caller started with.
        initial_origins: Where each line of *source_code* really came from,
            when that is not simply its own line of *source_file* -- a
            copybook rewritten by a REPLACING whose BY text added or removed
            lines (#561). None means identity origins.

    Returns:
        Tuple of (expanded_source, max_depth_reached, is_normalized, origins)
        is_normalized indicates if the returned source has had sequence numbers stripped.
        origins holds one ``(file, original line)`` pair per line of
        expanded_source -- see the ``LineOrigin`` note above.


    Raises:
        CircularReferenceError: If circular dependency detected
        NestingDepthError: If max nesting depth exceeded
        TotalExpansionSizeExceededError: If total size exceeds limit
    """
    source_origins: list[LineOrigin] = _fit_origins(
        (
            list(initial_origins)
            if initial_origins is not None
            else _identity_origins(source_file, source_code)
        ),
        source_code.count("\n") + 1,
        (source_file, 1),
    )

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
    #
    # `merged_from` collects, per normalized line, the physical line of
    # *source_code* it started on -- the one step here that changes the line
    # count, and so the one the source map cannot infer afterwards. The
    # comment-blanking and sequence-area strips above it are line-preserving
    # by construction (both blank in place), so nothing else has to be tracked.
    merged_from: list[int] = []
    if free_form is None:
        free_form = context.source_format != "fixed" and not _looks_program_fixed(
            source_code
        )
    if free_form:
        # Free-form source has no sequence/indicator/identification columns
        # to strip and no column-7 continuation records to merge; slicing
        # it at column 7 (the previous unconditional path) cut the first
        # six characters off every line. Its `*>` comments are skipped by
        # the COPY scanner itself.
        normalized_source = source_code
        merged_from = list(range(1, source_code.count("\n") + 2))
    elif already_stripped:
        normalized_source = normalize_continuation_lines(
            source_code, indicator_position=0, line_origins=merged_from
        )
    else:
        source_no_comments = remove_comment_lines(
            source_code, keep_debug_lines=context.debug_lines
        )
        source_stripped = strip_sequence_area(source_no_comments)
        # We must merge continuation lines to find statements split across lines
        normalized_source = normalize_continuation_lines(
            source_stripped, indicator_position=0, line_origins=merged_from
        )

    # Extract COPY statements using the robust lexer on normalized source
    lexer = CopyStatementLexer(
        normalized_source, source_file, sql_include=True, line_origins=merged_from
    )
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
        return (
            source_code,
            context.current_depth,
            already_stripped and not free_form,
            source_origins,
        )

    # Push current file onto stack

    context.stack_push(source_file)
    max_depth = context.current_depth

    # Process COPY statements in reverse order to maintain positions
    # We use the NORMALIZED source as the base for expansion because we need valid indices
    expanded_source = normalized_source
    origins: list[LineOrigin] = _fit_origins(
        [
            source_origins[n - 1] if 0 < n <= len(source_origins) else (source_file, n)
            for n in merged_from
        ],
        normalized_source.count("\n") + 1,
        (source_file, 1),
    )
    for statement in reversed(copy_statements):
        # Find copybook file
        try:
            copybook_path = path_resolver.resolve(
                statement.member_name, statement.library_qualifier
            )
        except CopybookNotFoundError as exc:
            if statement.sql_include:
                # EXEC SQL INCLUDE of a member the precompiler supplies
                # (SQLCA, SQLDA) or one the shop keeps elsewhere: leave the
                # statement as written -- the parser handles it as the EXEC
                # SQL statement it is -- rather than failing the expansion.
                # Only the precompiler's own members are expected to be
                # missing; any other name (a DCLGEN, a shared COMMAREA) was
                # left out silently before, and every analyzer then read a
                # program without its declarations with nothing to say so.
                if (
                    stats is not None
                    and statement.member_name.upper() not in PRECOMPILER_MEMBERS
                ):
                    stats.warnings.append(
                        f"EXEC SQL INCLUDE {statement.member_name} was not "
                        f"expanded: {exc}; the statement was left as written"
                    )
                continue
            if context.skip_missing:
                # One missing member must not cost every other one its
                # expansion. The COPY stays as written; the parser then
                # reports it as not expanded, like any unexpanded COPY.
                if stats is not None:
                    stats.warnings.append(f"{exc}; the COPY was left as written")
                continue
            raise

        # A >>DEFINE above this COPY is in effect inside the member (IBM
        # processes compiler directives and COPY in one sequential pass).
        # The member's conditional compilation therefore depends on where
        # the COPY sits, so those symbols are part of the cache key.
        member_symbols: dict[str, str] | None = None
        if process_conditionals:
            member_symbols = context.defined_symbols
            if define_log:
                copy_line = expanded_source.count("\n", 0, statement.start_index)
                if copy_line < len(origins):
                    member_symbols = _symbols_at_line(define_log, origins[copy_line][1])

        # Check if we have a cached expansion (without nested COPY processing)
        # Note: We can only use cache for the same file + same replacements
        # (and, under conditional compilation, the same symbols).
        full_cache_key = context.get_cache_key(
            copybook_path, statement.replacing_clauses
        )
        if member_symbols is not None:
            full_cache_key += "::" + repr(sorted(member_symbols.items()))

        expanded_copybook = context.cache_get(full_cache_key)
        if expanded_copybook is not None:
            nested_depth = context.current_depth + 1
            copybook_origins = context.cache_get_origins(
                full_cache_key
            ) or _identity_origins(copybook_path, expanded_copybook)
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
            member_free_form = context.source_format != "fixed" and not (
                _looks_fixed_format(copybook_content, default=not free_form)
            )
            if member_free_form and not free_form and stats is not None:
                stats.warnings.append(
                    f"Copybook {statement.member_name} was read as free-form although "
                    f"the program that copies it is fixed-format: most of its "
                    f"lines have no valid column-7 indicator. If it is fixed "
                    f"format, pass --source-format fixed (cobol.yml: "
                    f"source_format: fixed)"
                )
            if not member_free_form:
                copybook_content = strip_sequence_area(
                    remove_comment_lines(
                        copybook_content, keep_debug_lines=context.debug_lines
                    )
                )
            elif not free_form:
                # A free-form member spliced into a fixed-format parent: the
                # stripped shape (and the final 6-column re-pad) expect each
                # line to begin with its indicator column, so give the
                # member one -- otherwise its first character would land in
                # column 7 and be read as the indicator.
                copybook_content = "\n".join(
                    (" " + line) if line.strip() else line
                    for line in copybook_content.split("\n")
                )

            # Validate copybook content if requested
            if validate_content:
                warnings = validate_copybook_content(
                    copybook_content,
                    copybook_path,
                    raw_content=raw_copybook_content,
                    # The content validated here is the STRIPPED one: its
                    # indicator sits at index 0, not 6. Validating with the
                    # raw-source default made the continued-literal quote
                    # discount never fire, so every copybook with a
                    # continued literal drew a false "unbalanced quotes".
                    indicator_position=None if member_free_form else 0,
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
            member_define_log: list[tuple[int, dict[str, str]]] | None = None
            if process_conditionals:
                member_define_log = []
                copybook_content = preprocess_conditional_compilation(
                    copybook_content,
                    (
                        member_symbols
                        if member_symbols is not None
                        else context.defined_symbols
                    ),
                    warnings=stats.warnings if stats is not None else None,
                    keep_source_format_directives=True,
                    define_log=member_define_log,
                )

            # Track this copybook
            if copybook_path not in included_copybooks:
                included_copybooks.append(copybook_path)

            # Apply REPLACING clause if present (using enhanced function).
            # copybook_content is already stripped (indicator at index 0).
            replaced_origins: list[LineOrigin] | None = None
            if statement.replacing_clauses:
                pre_replacing_size = len(copybook_content.encode("utf-8"))
                replaced_from: list[int] = []
                copybook_content = apply_replacing_clauses(
                    copybook_content,
                    statement.replacing_clauses,
                    indicator_position=0,
                    line_origins=replaced_from,
                )
                # The recursion below numbers its input from line 1; after a
                # BY text that added or removed lines that numbering is not
                # the copybook's, so hand it the real one (#561).
                replaced_origins = [(copybook_path, n) for n in replaced_from]
                # The raw-content charge above is taken before REPLACING, and
                # a REPLACING BY text longer than its operand multiplies the
                # member: a 48 KB copybook grew to 5.5 MB under a 1 MB
                # max_total_size. Charge the growth too, so the limit bounds
                # what the expansion actually produces.
                growth = len(copybook_content.encode("utf-8")) - pre_replacing_size
                if growth > 0:
                    context.total_bytes += growth
                    if stats:
                        stats.total_bytes_processed = context.total_bytes
                    if context.total_bytes > path_resolver.search_config.max_total_size:
                        raise TotalExpansionSizeExceededError(
                            context.total_bytes,
                            path_resolver.search_config.max_total_size,
                        )

            # Handle SUPPRESS clause (for listing control - we still include the content)
            # SUPPRESS is mainly for compiler listing output, not actual code inclusion
            # We note it in metadata but don't change the expansion behavior

            # Recursively expand nested COPY statements
            context.current_depth += 1
            context.current_file = copybook_path

            expanded_copybook, nested_depth, nested_normalized, copybook_origins = (
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
                    # A free-form member under a fixed-format parent was
                    # just given the stripped fixed shape above.
                    free_form=member_free_form and free_form,
                    define_log=member_define_log,
                    initial_origins=replaced_origins,
                )
            )

            # copybook_content was already stripped above, so nested_normalized
            # is always True here; this fixup is kept as a defensive no-op in
            # case that invariant ever changes.
            if not nested_normalized and not (member_free_form and free_form):
                nested_no_comments = remove_comment_lines(
                    expanded_copybook, keep_debug_lines=context.debug_lines
                )
                nested_stripped = strip_sequence_area(nested_no_comments)
                nested_merged_from: list[int] = []
                expanded_copybook = normalize_continuation_lines(
                    nested_stripped,
                    indicator_position=0,
                    line_origins=nested_merged_from,
                )
                # This branch merges lines, so the origins from the recursion
                # no longer line up one-to-one; re-index them through the merge.
                copybook_origins = [
                    (
                        copybook_origins[n - 1]
                        if 0 < n <= len(copybook_origins)
                        else (copybook_path, n)
                    )
                    for n in nested_merged_from
                ]

            context.current_depth -= 1
            context.current_file = source_file

            # Cache the fully expanded result using LRU-aware method
            context.cache_put(full_cache_key, expanded_copybook, copybook_origins)

        max_depth = max(max_depth, nested_depth)

        # `expanded_copybook` (fresh or cached) still carries the copybook's
        # own trailing "\n" -- the terminator of its last real line, not a
        # blank line of content. The splice below inserts it into a span
        # that already ends in the COPY statement's own line terminator
        # (`expanded_source[statement_end:]` starts right after the
        # statement, keeping the newline that closed its line), so leaving
        # both in doubles that boundary: one phantom blank physical line per
        # COPY statement, compounding with nesting. It also over-counts
        # `copybook_line_count` below by one, which pads the spliced-in
        # origins to match -- so the fix has to happen before that count is
        # taken, not just in the text splice. Stripping exactly one trailing
        # newline here (never more, so a copybook with a genuine blank final
        # line keeps it) lets `expanded_source[statement_end:]` supply the
        # single boundary the un-expanded source already had.
        if expanded_copybook.endswith("\n"):
            expanded_copybook = expanded_copybook[:-1]

        # Replace COPY statement with expanded content
        # Find statement in source
        # Replace COPY statement with expanded content
        # We use strict index-based replacement from the lexer tokens
        # Since we iterate in reverse, indices remain valid
        statement_start = statement.start_index
        statement_end = statement.end_index

        # Splice the source map exactly as the text is spliced. The COPY
        # statement occupies the lines [start_line, end_line] of the text as it
        # stands now (a COPY with a REPLACING clause legally spans several);
        # the copybook's own lines replace them. The first spliced line is
        # credited to the *parent* only when the parent had real text before
        # the COPY on that line (`COPY X.` on a line of its own, the normal
        # case, credits it to the copybook). Text AFTER the COPY's period on
        # its last line is moved onto a physical line of its own, in its own
        # columns, credited to that parent line: appended to the copybook's
        # last line it inherited the copybook's origin, so lint blamed the
        # member for a parent item (#355, option (b)).
        start_line = expanded_source.count("\n", 0, statement_start)
        end_line = expanded_source.count("\n", 0, statement_end)
        head_start = expanded_source.rfind("\n", 0, statement_start) + 1
        head_has_text = bool(expanded_source[head_start:statement_start].strip())
        tail_end = expanded_source.find("\n", statement_end)
        if tail_end == -1:
            tail_end = len(expanded_source)
        tail_has_text = bool(expanded_source[statement_end:tail_end].strip())

        copybook_line_count = expanded_copybook.count("\n") + 1
        spliced = _fit_origins(
            list(copybook_origins), copybook_line_count, (copybook_path, 1)
        )
        if head_has_text and start_line < len(origins):
            spliced[0] = origins[start_line]
        if tail_has_text and end_line < len(origins):
            spliced.append(origins[end_line])
            tail_column = statement_end - (
                expanded_source.rfind("\n", 0, statement_end) + 1
            )
            expanded_copybook += "\n" + " " * tail_column
        origins = origins[:start_line] + spliced + origins[end_line + 1 :]

        # `COPY X.` on a line of its own: the blanks before it are the COPY
        # statement's OWN indentation, not the copied text's. Splicing at
        # `statement_start` would prepend them to the member's first line,
        # which is that line's columns as its author wrote them -- so a `01`
        # copied from a member that puts it in Area A lands in Area B, and a
        # far-right `COPY` pushes the line past column 72, where
        # `_fit_fixed_format_width` then squeezes its blanks out or wraps it
        # onto an extra physical line (shifting every following line number).
        # A member's lines are inserted as whole source records, in their own
        # columns, so the splice starts at the beginning of the record. When
        # the parent DOES have text before the COPY on that line, those
        # characters are program text and must survive -- hence the guard.
        text_start = statement_start if head_has_text else head_start

        expanded_source = (
            expanded_source[:text_start]
            + expanded_copybook
            + expanded_source[statement_end:]
        )

    # Pop current file from stack
    # Pop current file from stack
    context.stack_pop()

    # Return normalized source (we don't pad here to avoid double-padding
    # during recursion). Free-form output was never stripped, so it must not
    # be re-padded either.
    return (
        expanded_source,
        max_depth,
        not free_form,
        _fit_origins(origins, expanded_source.count("\n") + 1, (source_file, 1)),
    )


__all__ = [
    "detect_encoding",
    "convert_to_utf8",
    "read_file_with_encoding",
    "expand_copybooks",
    "clear_file_cache",
    "set_file_cache_size",
    "get_file_cache_stats",
]


#: A COPY diagnostic from the parser's own un-expanded-COPY strip pass
#: (``CopyStatementLexer(source, "<main>")`` over the EXPANDED text).
_STRIP_PASS_COPY_WARNING_RE = re.compile(
    r"<main>: ((?:COPY|EXEC SQL INCLUDE)\b.*?\bline )(\d+)\b"
)


def _locate_strip_pass_warning(
    warning: str, source_map: dict[int, tuple[str, int]] | None
) -> str:
    """*warning* re-stated in the coordinates of the file a human edits.

    The parser's strip pass runs over the expanded text, so its COPY
    diagnostics count expanded lines and are labelled ``<main>``; the
    expander reports the same COPY in the original file's lines (#256).
    Translating through the expansion source map makes the two agree, so
    the caller sees one diagnostic, at the right line.
    """
    match = _STRIP_PASS_COPY_WARNING_RE.match(warning) if source_map else None
    if match is None or source_map is None:
        return warning
    origin = source_map.get(int(match.group(2)))
    if origin is None:
        return warning
    origin_file, origin_line = origin
    return f"{origin_file}: {match.group(1)}{origin_line}{warning[match.end():]}"


#: Moved to :mod:`cobolparser.parser` (an expand-then-parse orchestrator
#: belongs above both). Reading them here still works, with a warning.
_MOVED_TO_PARSER = ("parse_cobol_with_expansion", "warn_dropped_debug_lines")


def __getattr__(name: str) -> Any:
    if name in _MOVED_TO_PARSER:
        import warnings

        warnings.warn(
            f"cobolparser.preprocess.copybook_expander.{name} moved to "
            f"cobolparser.parser.{name}; this path goes away in the next "
            "major release",
            DeprecationWarning,
            stacklevel=2,
        )
        from .. import parser

        return getattr(parser, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
