# Preprocessing

> Converts fixed-format COBOL to free-form text and optionally inlines COPY statements before lexing.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/preprocess/__init__.py` | Module hub; exports preprocessing functions and exception hierarchy |
| `cobolparser/preprocess/copybook_expander.py` | Core copybook inlining engine with LRU file cache |
| `cobolparser/preprocess/copy_statement_parser.py` | Lexes COPY statements and applies REPLACING clauses |
| `cobolparser/preprocess/path_resolver.py` | Resolves copybook paths securely (prevents directory traversal) |
| `cobolparser/preprocess/models.py` | Data structures for copybook expansion |
| `cobolparser/_preprocess_fast.pyx` | Cython override of `normalize_fixed_format()` hot-path |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `normalize_fixed_format()` | `preprocess/__init__.py` | Converts fixed-format COBOL lines to free-form text string; drops comment lines |
| `preprocess_conditional_compilation()` | `preprocess/__init__.py` | Processes `>>IF` / `>>ELSE` / `>>END-IF` directives |
| `validate_copybook_content()` | `preprocess/__init__.py` | Validates a copybook file's content before expansion |
| `validate_level_numbers()` | `preprocess/__init__.py` | Checks level-number sequencing in data definitions |
| `strip_compiler_directives()` | `preprocess/__init__.py` | Strips IBM compiler directives before parsing |
| `expand_copybooks()` | `copybook_expander.py` | Expands COPY statements in source text; returns `CopybookExpansion` |
| `parse_cobol_with_expansion()` | `copybook_expander.py` | Full pipeline: expand + parse in one call |
| `clear_file_cache()` | `copybook_expander.py` | Clears the LRU file cache |
| `set_file_cache_size()` | `copybook_expander.py` | Sets max entries in the LRU cache |
| `get_file_cache_stats()` | `copybook_expander.py` | Returns hit/miss statistics for the file cache |
| `read_file_with_encoding()` | `copybook_expander.py` | Reads a file detecting encoding (UTF-8, EBCDIC, Latin-1) |
| `detect_encoding()` | `copybook_expander.py` | Detects file encoding using heuristics (UTF-8 BOM, EBCDIC markers) |
| `convert_to_utf8()` | `copybook_expander.py` | Converts raw bytes to UTF-8 string with fallback handling |
| `CopyStatementLexer` | `copy_statement_parser.py` | Tokenizes a COPY statement line |
| `apply_replacing_clauses()` | `copy_statement_parser.py` | Applies REPLACING text substitutions to copybook content |
| `normalize_continuation_lines()` | `copy_statement_parser.py` | Merges fixed-format continuation lines |
| `strip_sequence_area()` | `copy_statement_parser.py` | Removes columns 1–6 from a line |
| `remove_comment_lines()` | `copy_statement_parser.py` | Removes lines where column 7 is `*` or `/` |
| `PathResolver` | `path_resolver.py` | Resolves copybook names to filesystem paths within allowed directories |
| `normalize_path()` | `path_resolver.py` | Normalizes and canonicalizes a path |
| `validate_path_within_directory()` | `path_resolver.py` | Raises `PathTraversalError` if path escapes the allowed root |
| `get_available_copybooks()` | `path_resolver.py` | Lists all `.cpy`/`.CPY` files in the search path |
| `find_copybook_file()` | `path_resolver.py` | Locates a copybook file in the configured search paths |
| `CopybookExpansion` | `models.py` | Result dataclass: `expanded_source`, `included_copybooks`, `statistics` |
| `CopyStatement` | `models.py` | Parsed COPY statement: `member_name`, `library_qualifier`, `replacing_clauses`, `suppress_clause` |
| `CopybookSearchPath` | `models.py` | Configuration for copybook file search: `directories`, `extensions`, `max_nesting_depth` |
| `ExpansionContext` | `models.py` | Tracks nesting depth and visited copybooks during recursive expansion |
| `ExpansionStatistics` | `models.py` | Metrics: `parse_time_ms`, `file_count`, `total_lines`, `total_bytes_processed` |
| `ReplacingClause` | `models.py` | A single `REPLACING old BY new` pair with optional `LEADING`/`TRAILING` mode |
| `SuppressClause` | `models.py` | Models `COPY … SUPPRESS` clause with line-range and single-line suppression |

## Exception Hierarchy

```
PreprocessingError  (base, in preprocess/__init__.py)
  ├── CircularReferenceError    — copybook A copies B copies A
  ├── CopybookNotFoundError     — COPY name not found on any search path
  ├── PathTraversalError        — copybook path escapes allowed directories
  ├── EncodingError             — cannot detect or decode file encoding
  ├── NestingDepthError         — recursive COPY nesting too deep
  ├── CopybookSizeExceededError — file exceeds MAX_COPYBOOK_SIZE_BYTES
  ├── CopybookSyntaxError       — copybook content fails validation
  └── TotalExpansionSizeExceededError — total expansion exceeds MAX_TOTAL_EXPANSION_BYTES
```

Constants in `models.py`:
- `MAX_COPYBOOK_SIZE_BYTES` = 10 MB per copybook
- `MAX_TOTAL_EXPANSION_BYTES` = 100 MB total expansion

## Data Flow / Lifecycle

**Stage 1 — normalize_fixed_format:**

1. Input: raw COBOL source as `List[str]` (one line per element)
2. For each line, extract columns 8–72; skip if column 7 is `*` or `/`
3. Handle continuation lines (column 7 = `-`): strip leading whitespace and append to previous line
4. Track quote state to merge continued string literals without inserting newlines
5. Join all lines and return a single free-form text string
6. Output: `str` ready for `CobolLexer`

Note: `_preprocess_fast.pyx` overrides this function with Cython C-typed quote tracking for performance; falls back to pure Python if not compiled.

**Stage 2 — expand_copybooks (optional):**

1. Input: free-form text + `copybook_paths: list[str]`
2. Pre-process conditional compilation if `process_conditionals=True` via `preprocess_conditional_compilation()`
3. `CopyStatementLexer` scans for `COPY <name>` patterns
4. For each COPY statement found:
   a. `PathResolver.resolve()` locates the copybook file using multi-tier caching (resolution cache → directory index → filesystem search)
   b. File read via `read_file_with_encoding()` with automatic encoding detection (UTF-8 BOM → UTF-8 strict → EBCDIC heuristic → ASCII fallback)
   c. Content cached in LRU file cache (`_cached_read_file`) keyed by absolute path + encoding
   d. Copybook content validated via `validate_copybook_content()` if `validate_content=True`
   e. Level numbers validated via `validate_level_numbers()` if `validate_levels=True`
   f. REPLACING clauses applied via `apply_replacing_clauses()` with LEADING/TRAILING modifier support
   g. Copybook content recursively expanded (circular reference detection via `ExpansionContext.stack_contains()`)
   h. Nesting depth checked against `max_nesting_depth` limit (raises `NestingDepthError` if exceeded)
   i. Total expansion size checked against `max_total_size` limit (raises `TotalExpansionSizeExceededError` if exceeded)
5. Returns `CopybookExpansion` with:
   - `expanded_source`: fully expanded text ready for lexing
   - `included_copybooks`: list of resolved copybook file paths (in order)
   - `max_depth_reached`: deepest nesting level encountered
   - `source_location_map`: optional line-to-origin mapping for error tracing
   - `statistics`: `ExpansionStatistics` with timings, file counts, warnings

## Public API (exported symbols)

```python
from cobolparser import (
    expand_copybooks,
    parse_cobol_with_expansion,
    normalize_fixed_format,
)
from cobolparser.preprocess import (
    PreprocessingError,
    CircularReferenceError,
    CopybookNotFoundError,
    PathTraversalError,
    EncodingError,
    NestingDepthError,
    CopybookSizeExceededError,
    CopybookSyntaxError,
    TotalExpansionSizeExceededError,
    strip_compiler_directives,
    preprocess_conditional_compilation,
    validate_copybook_content,
    validate_level_numbers,
    clear_file_cache,
    set_file_cache_size,
    get_file_cache_stats,
)
from cobolparser.preprocess.models import (
    CopybookExpansion,
    CopyStatement,
    CopybookSearchPath,
    ExpansionContext,
    ExpansionStatistics,
    ReplacingClause,
    SuppressClause,
    MAX_COPYBOOK_SIZE_BYTES,
    MAX_TOTAL_EXPANSION_BYTES,
)
from cobolparser.preprocess.path_resolver import PathResolver
```

## Gotchas / Invariants

- **normalize_fixed_format() must run before CobolLexer** — the lexer has no fixed-format awareness. Call `normalize_fixed_format()` on raw fixed-format input or use `expand_copybooks()` which does this internally.

- **LRU cache is module-level and persistent** — `_cached_read_file()` caches file content by absolute path in `_FILE_CONTENT_CACHE` (default 2048 entries). Call `clear_file_cache()` between independent batch runs or after on-disk file edits to avoid serving stale content.

- **PathResolver multi-tier caching** — Each `PathResolver` instance maintains a resolution cache and builds a directory index on first lookup. Rebuild or clear the index if search directories change mid-session.

- **PathResolver validates copybook paths** — Resolved paths are validated via `validate_path_within_directory()` to prevent path traversal attacks. Symlinks are resolved before checking.

- **Nesting depth is limited to prevent stack overflow** — Default max is 100 levels. Circular references detected via `ExpansionContext.stack_contains()` before recursion. Set `max_nesting_depth` lower for hostile inputs.

- **Encoding detection uses heuristics** — Auto-detection checks for UTF-8 BOM, tries UTF-8 strict decode, then checks EBCDIC space markers (0x40), falling back to ASCII. Set `CopybookSearchPath.encoding` explicitly to force a specific EBCDIC variant (e.g., `cp1047`, `cp500`, `cp273`) rather than relying on auto-detection defaulting to cp037.

- **_preprocess_fast.pyx overrides only normalize_fixed_format()** — All other preprocessing functions remain pure Python. The Cython module is optional; install with `pip install -e ".[fast]"` to compile, or falls back silently to pure Python.

- **Circular reference error includes dependency chain** — `CircularReferenceError.dependency_chain` lists the copybook names in the cycle (e.g., `['A', 'B', 'A']`), useful for debugging.

- **CopybookNotFoundError includes suggestions** — Uses fuzzy matching to suggest similar copybook names when a member is not found. Set `search_config.case_sensitive` based on filesystem (auto-detected as False on Windows/macOS, True on Linux).

## Refresh Checklist

- [ ] Check `preprocess/__init__.py` for new exported functions and exception types
- [ ] Verify `models.py` dataclass fields still match their uses in `copybook_expander.py`
- [ ] Check if new exception types were added to the exception hierarchy
- [ ] Verify `MAX_COPYBOOK_SIZE_BYTES` and `MAX_TOTAL_EXPANSION_BYTES` constants still exist and have expected values in `models.py`
- [ ] Check `copybook_expander.py` for new cache management functions (esp. `_cached_read_file` signature)
- [ ] Verify `PathResolver` class methods (resolve, normalize, validate, get_suggestions, list_available) unchanged
- [ ] Check `copy_statement_parser.py` for new COPY statement parsing functions or `CopyStatementLexer` methods
- [ ] Verify path resolution security functions still exist: `normalize_path()`, `validate_path_within_directory()`, `find_copybook_file()`
- [ ] Check for changes to `ExpansionContext` stack and cache methods
- [ ] Verify `_preprocess_fast.pyx` still provides only `normalize_fixed_format()` override (not other functions)
