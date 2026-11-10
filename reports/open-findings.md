# cobolparser — Open Findings (as of 2026-11-06)

This is the one list of what is **currently open**. Every dated audit in this
folder (`audit-2026-08-12.md`, `-08-12-followup.md`, `-09-07.md`, `-09-16.md`,
`-09-27.md`) has been folded in: an item from one of them is either listed
below or was re-checked against the code on 2026-11-06 and is closed. The
audits themselves stay as point-in-time records; do not track status in them.
Fixed-finding history lives in `CHANGELOG.md` and this file's git history.

**When you fix an item, delete it here in the same commit. When an audit
finds something, add it here** (with the audit's ID), not only in the audit.

---

## Open

### Parser bugs pinned as strict xfails (found 2026-11-06)

Each has an `xfail(strict=True)` test in the named file under `tests/unit/`;
fixing one turns its test into an XPASS failure, so remove the mark with the fix.

- `XmlJsonStatementParser.matches` looks only 5 tokens past XML/JSON: a block
  of comment lines before GENERATE/PARSE drops the statement, and GENERATE is
  then parsed as Report Writer GENERATE (`test_xml_json_parser_branches.py`).
- XML/JSON takes the sentence period as a missing operand, FROM item or
  PROCESSING PROCEDURE name, reports nothing, and swallows the next paragraph
  header as clause text (3 cases, same file).
- A paragraph name whose period is on the next line (`P2` / `.`) is not a
  header: P2 is dropped and its statements join the previous paragraph
  (`test_procedure_boundary_branches.py`).
- `SetStatementParser._starts_another_group` looks at most 24 tokens ahead: a
  later group with more targets is dropped as "Unparsed tokens"
  (`test_set_parser_branches.py`).
- Level-88 with a misspelt VALUE (`88 A1 VALU 'Y'.`) drops the value list
  silently; a level-88 value list without its period swallows the next
  entry's level number and loses that entry; `66 R1 B.` (no RENAMES) vanishes
  with no warning (`test_data_special_entry_branches.py`).
- `IF X = THEN` yields a COMPARISON with `right_operand` `None` and no error
  (`test_if_parser_branches.py`).
- Seen on malformed input, not pinned: `88 X VALUE 1 WHEN SET TO TRUE 2.`
  turns `2` into a level-02 item; `IF X = 1 GARBAGE ELSE GARBAGE2.` makes
  GARBAGE2 a paragraph; `XML PARSE X PROCESSING WS-IX` records `PROCESSING`
  as a clause item.

### Performance

- **COPY-strip runs its full scan on files with no COPY statement**
  (09-27 §3.1). `strip_unexpanded_copy_statements`
  (`preprocess/replace_statement.py`) skips the scan only when the substring
  `COPY` is absent, so `COPYRIGHT` or a `" COPY - NOT FOR DISTRIBUTION"`
  literal (every NIST program) sends the file through the character-at-a-time
  `CopyStatementLexer`; measured at 35–50% of parse time on the largest NIST
  files. Fix: a word-boundary prefilter on non-comment text, or jump between
  regex hits. Also `_EXEC_SQL_TAIL_RE.search(self.source[:keyword_start])`
  copies the source prefix once per INCLUDE (O(n²) for many INCLUDEs).

### Correctness / API

- **Under COLLECT_ALL, a division parser that raises without consuming a
  token is retried forever** (found 2026-11-06 while pinning the error-location
  fix; pre-existing). `tests/regression/test_unexpected_error_location.py`
  uses FAIL_FAST to stay clear of it. The division loop needs a
  no-progress guard.
- **The MCP server has no per-file time or size cap** (S-2 residual).
  `batch` / `scan` gained `timeout_seconds` / `max_file_bytes` on 2026-11-06;
  the MCP facts pool does not call them. `cobolparser._file_limits`
  (`oversize_reason`, `run_with_timeouts`) is the piece to reuse.
- **COMPUTE and PERFORM UNTIL drop the expression tree silently on a
  tree-building failure** (09-27 §4.10). By design tree building is
  best-effort and must not add errors or warnings (M12), so
  `expression_tree` is `None` with the raw text kept; downstream analyzers
  lose structure without a caveat. Decide whether a caveat (not a warning)
  belongs here.
- **Unknown column-7 indicator characters** (anything other than
  space/`*`/`/`/`-`/`D`) are treated as live code by `normalize_fixed_format`.
- **`CallStatement.possible_values` returns `[]` ambiguously**: "never
  tracked" and "tracked, zero values" look the same (the latter is
  structurally unreachable today).
- **Recognized-but-unsupported verbs** (INITIATE, TERMINATE, CHAIN, NOTE,
  RECOVER, SUPPRESS, ...) warn via `_UNSUPPORTED_VERBS` but produce no AST
  node. Not a silent drop; a reminder they are unmodeled.
- **P-D4** — statement `column` numbers are normalized-text coordinates
  (columns 1–7 stripped), systematically −7 from fixed-format source columns;
  undocumented.

### Analyzer design (A-design, A-B2, from 2026-08-12)

- `MoveTypeChecker`'s flat name→category catalog collapses duplicate data
  names (no ambiguity accounting).
- `DeadCodeAnalyzer` explicit references are not reachability-gated (dead
  subgraphs shield each other).
- `domains._apply_enum` ignores relational ops on 88-enumerated domains and
  can leak raw `THROUGH:n` markers as witnesses.
- `detect_cycles` dedups by node *set*, merging genuinely distinct cycles.
- `_unique_prefix` uses `startswith` without a word boundary ("SELECT A" also
  prefixes "SELECT AB ..."); `value_tracker._extract_literal_value`'s
  permissive identifier fallback is gated at its caller but still pinned by
  direct-call tests (`tests/unit/test_value_tracker_coverage.py`). Delete
  both together.

### Structure / tests

- **542 function-local imports**, several commented as avoiding a circular
  import (09-27 §4.11): latent cycles between models, analysis, plugins and
  generators.
- **M17 — DATA/ENVIRONMENT-division branch coverage**: see "Coverage" below.
- `XrefAnalyzer._visit_statement_tree` walks `.children` rather than the
  canonical `iter_clause_bodies()`. Correct today (every clause body is a
  child); move it onto the canonical walker when next touched.

### Process (open by choice)

- **CI runs only on manual dispatch** (`ci.yml` `workflow_dispatch`, to save
  cost), and the release job builds and publishes without running the suite.
  Run lint, mypy and the full suite locally before merging to `main`.
- **S-3 (info)** — CLI `-o` overwrites without confirmation (standard; keep
  it a conscious choice).

---

## Coverage

Measured 2026-11-06 (one pure-Python build; the old "measure without the
Cython extensions" caveat is gone with them): **93.42%** combined
line+branch, 89.03% pure branch ratio, against the 90% floor.

- **M17:** `parsers/divisions/data.py` 13 missing lines, 27/198 missing
  branches (92.71%); `parsers/divisions/environment.py` 4 missing lines, 5/36
  missing branches (92.11%). Both well down from the 2026-07-09 counts
  (86 and 69 missing branches); keep it open only as a watch item.
- Weakest parser modules after this pass: `procedure_boundaries` 86.7%,
  `if_parser` 88.9%; nearly all their remaining misses are end-of-stream
  guards unreachable through the public API (the lexer always ends with
  EOF). Next weakest: `search_parser` 85.6%, `open_parser` 85.7%,
  `initialize_inspect_parsers` 87.9%, `identification` 88.3%.

---

## Closed on 2026-11-06 (re-checked against the code)

- Numeric-edited fields written to record images as plain numbers — fixed
  by `ebf69044` (`generators/data/editing.py`); IBM editing examples now
  pinned in `tests/unit/generators/data/test_editing.py`.
- `TokenType.ALL`, `_compress_doubled_quotes`, `CobolFileDescription`,
  `TokenStream.transaction()`, the legacy char-cursor lexer API and the dead
  newline-strip branches (P-C3/P-C4/P-C6) — removed.
- P-D2, P-D3, P-C1 and 09-27 §3.4 (Cython `.c` files, `wraparound=False`,
  dead `parse_picture_clause_fast`, parity/speedup claim) — moot: the
  accelerators are removed.
- Generic exceptions recorded at line 1, column 1 (09-27 §4.8) — fixed.
- io-sequence exponential time / `RecursionError` (09-27 §2.2, §3.3) — fixed
  (range summaries replayed, generator-driven walk).
- recursion-check superlinear (09-27 §3.2) — fixed (per-report edge index).
- `scan` dropping copybook-expansion failures (09-27 §4.5) — fixed
  (`FileScan.copybook_error`).
- Ten hand-rolled statement walkers and three name normalizers (09-27 §3.5)
  — consolidated; this fixed missed RECEIVE NO DATA / WITH DATA bodies.
- `cli/parse.py` size (09-27 §3.6) — split into `cli/commands/`.
- F-rated functions (09-27 §3.7) — the top four and six more are C or better.
- `MemoryConfiguration.max_memory_mb` advertised as enforced (09-27 §4.7) —
  docs now say it is advisory.
- Seven undocumented CLI subcommands, stale README counts, committed
  `coverage.json`, 2,850-line CHANGELOG `Unreleased` (09-27 §4.1–4.4) —
  fixed.
- `datetime.utcnow()`, dead mypy `tests.*` override, Sphinx `docs` extra
  with no `conf.py`, loose dev-tool floors, `ruff-format` + black both in
  pre-commit (09-27 §5.1, §5.4, §5.6, §5.11; T-misc) — fixed.
- Batch workers with no per-file memory/time cap (S-2) — fixed for
  `batch` / `scan` (`--timeout`, `--max-file-bytes`); MCP residual above.
