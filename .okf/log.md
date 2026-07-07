# OKF Update Log

## 2026-07-06 (INSPECT/STRING/UNSTRING swallow + EXEC missing-END-EXEC — audit H2)

* **Updated** [parser.md](parser.md): closed the last four rows of audit
  2026-07-06 H2's "swallow the following statement" class.
  - Added a shared `is_statement_boundary(token)` predicate in
    `parsers/statements/_utils.py` (unions `STATEMENT_TOKEN_TYPES` /
    `STATEMENT_KEYWORDS` / `SCOPE_TERMINATORS` / `CONTROL_FLOW_BOUNDARIES`)
    so INSPECT/STRING/UNSTRING share one boundary check instead of the
    per-parser inline copies MOVE/arithmetic use.
  - `InspectStatementParser`'s trailing "consume to period" loop and the
    `StringStatementParser`/`UnstringStatementParser` main-loop
    `else: consume()` fall-throughs now `break` on that predicate, so an
    un-punctuated INSPECT/STRING/UNSTRING immediately followed by another
    statement (or an enclosing `END-IF`/`ELSE`) no longer devours it up to
    the next period. Behavior stays `errors=0` (a legal COBOL sentence may
    hold several statements without separating periods).
  - EXEC SQL/CICS/IMS is intentionally left off that predicate: embedded
    SQL/CICS text legitimately contains COBOL keywords (SET/DELETE/UPDATE/
    CALL/OPEN/CLOSE), so a content boundary would truncate valid SQL. The
    mandatory `END-EXEC` is the only safe delimiter, so
    `collect_exec_sql_text` now detects a missing `END-EXEC` (stream
    exhausted first) and records a non-fatal "Unterminated EXEC block"
    parse error via the stream's parse context — turning the previous
    silent "consume the rest of the program with `errors=0`" into a
    reported error (`result.success == False`). Well-formed blocks and the
    NIST/shamrice/sample corpora (all `END-EXEC`-terminated) are unaffected.
  - Pinned by four new classes in
    `tests/regression/test_tier2_silent_drop_regressions.py`
    (`TestInspectDoesNotSwallowFollowingStatement`,
    `TestStringDoesNotSwallowFollowingStatement`,
    `TestUnstringDoesNotSwallowFollowingStatement`,
    `TestExecMissingEndExecReportsError`). Full suite: 6579 passed.
  - Still-open H2 row: MOVE *source* path (`MOVE A` with no `TO`) — not part
    of this change.

## 2026-07-06 (MOVE silently accepted malformed input — audit H3)

* **Updated** [parser.md](parser.md): the MOVE parser accepted incomplete
  input and produced a plausible-but-wrong node with `errors == 0` — `MOVE A
  TO.` gave a `MoveStatement` with `targets: []`; `MOVE A` (no `TO`) and a
  stream truncated at `MOVE A TO` were also accepted (audit finding H3).
  `MoveStatementParser.parse` now pulls the active `ParseContext` via
  `_utils.get_parse_context` and calls `report_parse_error` (the same
  record-and-continue path GO/CALL use) when `TO` is missing or when zero
  receiving fields follow `TO` (`target_count == 0`). Well-formed MOVEs stay
  clean, including multi-target, subscripted targets, literals, figurative
  constants, and `MOVE CORRESPONDING`. A missing **source** (`MOVE TO X`) is
  intentionally not flagged — indistinguishable from stray `*>`-comment /
  `REPLACE` pseudo-text the preprocessor does not strip; an earlier
  missing-source check faulted a valid shamrice program. Pinned by
  `tests/unit/test_move_malformed_diagnostics.py`. The stricter check exposed
  three NIST programs previously passing the error-free guarantee *only* via
  this silent acceptance, now strict-xfail `KNOWN_ISSUES`: `SM206A` /`SM208A`
  (`COPY REPLACING` / `REPLACE` pseudo-text substitution not implemented) and
  `NC205A` (continuation-line handling shatters the split literal `-999.777`
  — a preprocessing defect, filed separately).

## 2026-07-06 (COMPUTE swallowing a following statement)

* **Updated** [parser.md](parser.md): the prior same-day fix (below)
  explicitly covered MOVE/SUBTRACT/MULTIPLY/DIVIDE but not COMPUTE.
  `ComputeStatementParser.parse()`'s expression-token-collection loop is a
  standalone inline loop (not `parse_arithmetic_operands()`), so it never
  inherited the boundary check: at `paren_depth == 0` it only stopped at a
  `PERIOD` or a value in `("ON", "NOT", "END-COMPUTE")`, with no check
  against `STATEMENT_KEYWORDS`/`CONTROL_FLOW_BOUNDARIES`. A `COMPUTE` with
  no trailing period, immediately followed by another statement (e.g. a
  multi-line `CALL ... USING`), had that statement's tokens silently
  appended to the COMPUTE expression string — the following statement
  vanished from the AST with `result.success == True` and no error
  reported. Found via a real DEPTMQP program (mockymock e2e work):
  `COMPUTE MQ-OPEN-OPTIONS = ...` directly followed by `CALL 'MQOPEN'
  USING ...`, which blocked all DEPTMQP/DEPTMQC testcases since mockymock
  rejects a whole compiled test file if any one testcase's MOCK doesn't
  match a boundary. Fixed by adding a `STATEMENT_KEYWORDS`/
  `CONTROL_FLOW_BOUNDARIES`/`SCOPE_TERMINATORS` check to the expression
  loop. The `SCOPE_TERMINATORS` half of that check fixes a second,
  distinct trigger of the same gap: a COMPUTE nested inside a clause body
  (e.g. `READ ... AT END COMPUTE X = Y + 1 END-READ`) with no trailing
  period before the *enclosing* scope terminator had that terminator
  folded into the expression string instead of ending the clause —
  `STATEMENT_KEYWORDS`/`CONTROL_FLOW_BOUNDARIES` alone don't cover
  `END-READ`/`END-CALL`/etc. Pinned by
  `tests/regression/test_tier2_silent_drop_regressions.py::TestComputeDoesNotSwallowFollowingCall`
  and `::TestComputeDoesNotSwallowEnclosingScopeTerminator`.

## 2026-07-06 (MOVE/SUBTRACT/MULTIPLY/DIVIDE swallowing a following statement)

* **Updated** [parser.md](parser.md): `MoveStatementParser`'s target loop
  now stops on the shared `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS`
  (`_utils.py`) instead of a hand-rolled list missing `EXEC`/`EXECUTE`;
  `SubtractStatementParser` and the shared MULTIPLY/DIVIDE helper now call
  `parse_size_error_clauses` instead of the deleted `skip_to_period()`.
  Also fixed two more bugs this exposed in `_parse_size_error_stmts`: its
  DISPLAY mini-parser didn't stop at `NOT ON SIZE ERROR` or other
  boundaries (also fixed a latent `DISPLAY 'ADD'`-style truncation), and its
  outer dispatch loop's fallback branch unconditionally consumed tokens
  instead of stopping at `NOT`/scope-terminators, so a `NOT ON SIZE ERROR`
  clause was merged into the preceding `ON SIZE ERROR` clause instead of
  populating `not_on_size_error`. Also added `TokenType.FIGURATIVE_CONSTANT`
  to
  `ARITHMETIC_OPERAND_TOKEN_TYPES` (a pre-existing, previously-unreached gap
  the fix surfaced via `tests/samples/arithmetic_operations.cbl`'s
  `DIVIDE ... BY ZERO`). Previously, a MOVE/SUBTRACT/MULTIPLY/DIVIDE
  statement with no trailing period, immediately followed by another
  statement (most notably `EXEC SQL`), silently swallowed that statement's
  leading tokens — `result.success` stayed `True` with zero errors reported.
  Found via a real ACCTMNT.cbl banking program (mockymock e2e work): two
  EXEC SQL blocks vanished from the AST. The same class also hit a `CALL
  'CBLTDLI' USING DLI-REPL` in an IMS sample's `ELSE` branch, previously
  misattributed to "ELSE branches aren't traversed" —
  `tests/unit/test_ims_segment_analyzer.py::TestRealWorldBankingAccounts`
  updated (4 → 5 expected calls, new `test_repl_detected_in_else_branch`).
  Pinned by `tests/regression/test_tier2_silent_drop_regressions.py`
  (Group 6).

## 2026-07-05 (IO clause bodies parsed into the AST)

* **Updated** [parser.md](parser.md): documented the new "IO clause bodies"
  behaviour — `collect_clause_stmts` in
  `cobolparser/parsers/statements/_utils.py` now parses the statements
  inside `AT END` / `NOT AT END` / `INVALID KEY` / `NOT INVALID KEY` clause
  bodies via the statement registry instead of discarding the tokens and
  returning `[]`. Clause statements land on the IO node's clause lists and
  as AST children (traversal + serialization). WRITE gained INVALID KEY
  parsing; START now matches comparison keywords by value and consumes the
  KEY data-name; MOVE/DISPLAY/CALL-USING operand loops stop at scope
  terminators. Pinned by `tests/unit/io_statements/test_clause_bodies.py`.

## 2026-07-05 (CALL handler-body termination)

* **Updated** [parser.md](parser.md): documented how
  `CallStatementParser._parse_nested_stmts` terminates ON EXCEPTION /
  NOT ON EXCEPTION / ON OVERFLOW bodies — boundary values (`NOT`,
  `END-CALL`), an inter-statement period, and a post-nested-parse
  `previous_meaningful_token` PERIOD check (a nested statement may consume
  the sentence period itself). `_parse_using_clause` stops at
  `SCOPE_TERMINATORS` so `END-CALL` is not captured as a USING parameter.
  Previously the handler body swallowed following top-level statements
  (`STOP RUN` after `END-CALL.` ended up inside `on_exception`) —
  mockymock then refused to mock them as nested-in-boundary. Pinned by
  `tests/regression/test_call_handler_body_termination.py`.

## 2026-07-05 (program_flow typing fix)

* No concept change needed: `ProgramFlowAnalyzer`'s inner `scan()` helper
  in `analysis/program_flow.py` swapped its mypy-invalid
  `source_id: str = proc_name` default for `str | None = None` with an
  in-body `proc_name` fallback — behaviorally identical, `mypy
  cobolparser/` now clean. [analysis.md](analysis.md) documents behavior,
  not this internal signature, so only this log entry records it.

## 2026-07-05 (multi-mode OPEN file capture)

* **Updated** [parser.md](parser.md): `open_parser.py` now consumes
  subsequent mode keywords (`OPEN INPUT A OUTPUT B EXTEND C`) instead of
  breaking at them, so `IOOpenStatement.file_names` captures the files of
  every mode group; `open_mode` still reports only the first group's mode.
  Previously every file after the second mode keyword was silently dropped
  — mockymock's OPEN-site mock matching (which keys on `file_names`) was
  the motivating consumer. Pinned by
  `tests/unit/io_statements/test_open_read_parsers.py` (multi-mode-group
  tests).

## 2026-07-04 (copybook path on-disk casing)

* **Updated** [preprocessing.md](preprocessing.md): `find_copybook_file()`
  now canonicalises the found file's basename to the on-disk casing via
  `os.scandir` (helper `_on_disk_casing` in `preprocess/path_resolver.py`).
  Previously, on case-insensitive filesystems (Windows/macOS), the
  extension probe order (`.cpy` before `.CPY`) leaked probe-cased paths
  (`MEM.cpy` for an on-disk `MEM.CPY`) into
  `CopybookExpansion.included_copybooks` and warnings. The tier-2
  `PathResolver` directory index already used scandir entry names and was
  unaffected. Pinned by
  `tests/unit/test_path_resolver_gaps.py::TestOnDiskCasing`; the SM207A
  regression tests dropped their `os.path.normcase` tolerance and compare
  paths exactly.

## 2026-07-04 (numeric VALUE clause fix)

* **Updated** [parser.md](parser.md): documented the LEVEL_NUMBER-as-literal
  gotcha in `parsers/divisions/data.py`. `_parse_value_clause` and the
  level-88 value collector now accept `LEVEL_NUMBER` tokens as numeric
  literals, consume an optional `IS`, and handle `MINUS`/`PLUS` sign tokens
  — previously `VALUE 5`, `VALUE 42`, `VALUE IS <n>`, `VALUE -5`, and
  `88 ... VALUE 1` all silently lost the literal and could spawn bogus
  anonymous data items. Motivated by mockymock's working-storage reset,
  which restores items to their declared VALUE clause. Regression suite:
  `tests/regression/test_numeric_value_clause.py`.

## 2026-07-04 (later)

* **NIST known-issues burn-down** (parser/lexer/preprocess fixes; corpus
  now 457/459 error-free, and both SM101A and SM207A parse clean with
  copybook expansion):
  - `parsers/divisions/base.py`: new shared `at_division_boundary()` —
    composite header tokens always match; bare keywords only when the next
    significant token is `DIVISION`. `BaseDivisionParser.parse` now skips
    newlines inside split headers.
  - `parsers/divisions/identification.py`: comment-entries containing bare
    division keywords (OBNC1M's `AUTOMATIC DATA AND ...`) no longer end the
    division; uses `at_division_boundary()`.
  - `parsers/divisions/data.py`: section scanner stops at split division
    headers (NC113M's three-line `PROCEDURE / DIVISION / .`) instead of
    consuming them as noise.
  - `parsers/statements/arithmetic_parsers.py`: COMPUTE accepts
    `{identifier [ROUNDED]}...` receiver lists incl. subscripts (NC252A).
  - `lexer.py` + `_lexer_fast.pyx` (`.c` regenerated, Cython 3.2.4):
    trailing period after a numeric literal is a sentence terminator, not a
    decimal point, unless followed by a digit.
  - `preprocess/__init__.py` `validate_copybook_content`: continued string
    literals (column-7 `-` re-opening quote) no longer flagged unbalanced.
  - `preprocess/path_resolver.py`: `COPY member OF library` falls back to
    the plain search path when no `<dir>/<library>/` subdirectory exists.
  - Tests: `tests/regression/test_nist_edge_case_fixes.py` (minimal repros);
    `KNOWN_ISSUES` in `test_nist_cobol85_support.py` shrunk to OBNC1M
    (Area A/B phony-program, architectural) + SM101A (expansion by design);
    `KNOWN_COPYBOOK_ISSUES` now empty; new SM207A expansion test.

## 2026-07-04

* **Updated** [tests.md](tests.md): added
  `tests/integration/test_nist_cobol85_support.py` to the layout and the
  Example Corpora table. The NIST COBOL-85 corpus (459 `.CBL` + 51 `.CPY`)
  is now strictly pinned: every program must parse error-free under
  COLLECT_ALL; the 4 programs the parser cannot yet handle (`NC113M`,
  `OBNC1M`, `NC252A`, `SM101A`) are strict-xfail `KNOWN_ISSUES` entries so
  the list only ever shrinks. `SM101A` additionally must parse clean with
  copybook expansion, and all `.CPY` files must pass
  `validate_copybook_content` (2 strict-xfail validator limitations).

## 2026-07-03

* **Updated** [ast-models.md](ast-models.md): `find_all_by_type()` /
  `find_first_by_type()` now also match a node's concrete class name
  (`"MoveStatement"`, `"CallStatement"`, `"ExecSQLStatement"`, ...), not just
  the `node_type` attribute. All statement subclasses share the generic
  `node_type` `"Statement"`, so class-name matching is what lets the CLI
  `analyze` subcommand list CALL statements and `--find-type` select specific
  statement kinds (previously both silently returned nothing for statement
  class names). Source: `cobolparser/models/ast_base.py` (`_matches_type`).
* **Updated** [cli.md](cli.md) for the output-identification change: every
  CLI output is now self-describing. Added an "Output Identification" section
  (JSON documents lead with `source_file` + `program_id`; `tokenize` output
  wrapped as `{"source_file", "tokens"}`; `parse` path/`--find-type`
  extraction wrapped as `{"source_file", "program_id", "path"/"node_type",
  "result"/"matches"}`; batch entries carry `program_id`; Mermaid flowcharts
  gained a `%% Program: <name>` header) and corrected the Tokenize
  subcommand's documented output shape. Source: `cobolparser/cli/parse.py`
  (`_identification`, `_emit_report`), `cobolparser/generators/flowchart.py`;
  contract pinned by `tests/unit/cli/test_output_identification.py`.

## 2026-06-30

* **Logged untracked drift from commit `cad4db6` (2026-06-29, "Add integration
  contract documentation for backend API")**: that commit added
  [integration.md](integration.md) and updated [lexer.md](lexer.md) and
  [index.md](index.md), but never got a log.md entry. Backfilling it now:
  - **Produced** [integration.md](integration.md): documents the backend
    adapter contract (`backend/src/parsers/cobol/parser.py`) — entry points
    (`CobolParser(...).parse()`, optional `DynamicCallAnalyzer`/
    `ProgramFlowAnalyzer` analyzers, `CobolParseError`), `ParseResult`/
    `CobolProgram` attribute contract, the `program_structure` output dict
    shape, the `dependencies.*` → Neo4j relationship mapping
    (`CALLS`/`COPYBOOK`/`USES_DB2`/`USES_CICS`/`USES_MQ`), the backend's
    `ParserResult` dataclass, and handled file extensions. Defers to the
    canonical `interface-contract.md` (repo root) via the `resource:`
    frontmatter field for full detail (e.g. copybook-specific
    `is_copybook`/`source_kind`/`copybook_name` fields and the
    `VALIDATION_FAILED`/`PERMISSION_ERROR` error-message prefixes are in the
    canonical doc but intentionally summarized out of the OKF concept).
  - **Updated** [lexer.md](lexer.md) Cython Acceleration section: replaced the
    bare 3-module table with one that lists the actual pure-Python file each
    `.pyx` overrides and the specific accelerated symbols (confirmed against
    `cobolparser/_lexer_fast.pyx`: `check_division_header`,
    `read_word_from_text`, `tokenize_program_text`, `_try_single_line_string`,
    `read_number_from_text`, `tokenize`; `_preprocess_fast.pyx`:
    `normalize_fixed_format`; `_data_fast.pyx`:
    `parse_picture_clause_fast`, `parse_data_item_clauses_fast`). Added the
    guarded `try/except ImportError` activation pattern, the `~3x` throughput
    figure (from `setup.py`), and the `pip install -e ".[fast]"` extra
    (`pyproject.toml`).
  - **Updated** [index.md](index.md): added the "Integration" section linking
    to integration.md.
  - Corrected `timestamp` on lexer.md and integration.md from `2026-06-28` to
    `2026-06-29` to match the commit that actually authored their current
    content.
* **Fixed pre-existing gaps in [cli.md](cli.md)** found while verifying
  concept files against current source (none of these came from a dated
  commit since the last log entry — they predate the OKF bundle itself,
  ranging from 2026-04-17 to 2026-05-06):
  - `analyze` subcommand was documented as running "all static analyzers"
    (dead code, IO, MOVE-type, linkage, LE); it actually only runs
    `DynamicCallAnalyzer` and reports dynamic `CALL` target info
    (`called_program`/`is_dynamic`/`possible_values`) — corrected.
  - `program-flow` was missing its `--format json|mermaid|dot` flag (added in
    commit `842f246`, wired to `generators/flowchart.py`'s
    `MermaidFlowchartGenerator`/`DotFlowchartGenerator`).
  - `parse`, `batch`, `program-flow`, `analyze`, and `dead-code` were missing
    the shared `--profile`/`--profile-top-n`/`--profile-output` flags (added
    in commit `5f2468c`/`13a3f1f`).
  - `batch` was missing `--glob` (repeatable), `--workers`, and `--encoding`.
  - `tokenize` output shape was missing the `column` field.
  Bumped cli.md `timestamp` to 2026-06-30.

## 2026-06-28

* **Initialization**: Created OKF bundle for cobolparser v1.1.0.
  Concepts produced: [lexer](lexer.md), [parser](parser.md),
  [preprocessing](preprocessing.md), [ast-models](ast-models.md),
  [analysis](analysis.md), [cli](cli.md), [tests](tests.md).
