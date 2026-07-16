# Changelog

All notable changes to the COBOL parser project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Bug Fixes

* **parser:** IDENTIFICATION DIVISION boundary checks are now comment-entry
  aware. COBOL-74 comment-entries (AUTHOR, SECURITY, REMARKS, ...) end only
  at the next Area A entry, and `normalize_fixed_format` preserves Area A/B
  as indentation — so a phony program embedded in Area B inside a
  comment-entry (NIST `OBNC1M`) no longer terminates the division early or
  spawns a bogus second program unit. The relative-column check
  self-calibrates for free-form sources. Per COBOL-74, *any* line-starting
  Area A token — not just recognized clause keywords — ends an active
  comment-entry, in both the clause-value loop and the main clause loop.
  Pinned by `tests/regression/test_comment_entry_area_b.py`. With this and the
  pseudo-text fixes below, **all 459 NIST COBOL-85 programs now parse
  error-free** (`KNOWN_ISSUES` is empty; `SM101A` is parsed through the
  copybook-expansion pipeline it requires by design, via
  `REQUIRES_COPYBOOK_EXPANSION`).

* **preprocess:** implement COBOL source-text pseudo-text substitution before
  lexing (`cobolparser/preprocess/replace_statement.py`), wired into
  `CobolParser._parse_core`. Two NIST COBOL-85 programs now parse error-free
  and were removed from `KNOWN_ISSUES`:
  * `apply_replace_statements` applies the `REPLACE ==a== BY ==b== [==c== BY
    ==d== ...] .` compiler-directing statement (one or more operand pairs) and
    cancels the active set at `REPLACE OFF.`. Matching is on the COBOL
    *text-word* stream — whitespace-, comma-, and semicolon-insensitive between
    words, with a separator period treated as its own text word and literals
    compared exactly — so multi-word / multi-line pseudo-text (including a
    pseudo-text operand that itself contains a period or a statement keyword)
    matches regardless of layout. Fixes `SM208A.CBL` (30x `REPLACE`), where the
    raw pseudo-text (`MOVE "*" AO WRK-XN-00001`, `==MOVE "FAIL" TO==`) had been
    leaking into the statement stream as malformed MOVEs.
  * `strip_unexpanded_copy_statements` blanks `COPY` statements the standalone
    pipeline is not going to expand — reusing the pseudo-text-aware
    `CopyStatementLexer` — so a `COPY ... REPLACING ==pseudo-text==` operand
    that legally contains a bare `MOVE` token (`SM206A.CBL`'s `BY MOVE
    ==DELETE==`) no longer leaks as a `MOVE` with no `TO`. In the
    copybook-expansion pipeline COPY is already inlined before this point, so
    the strip is a no-op there.
  Both passes preserve the physical line count of their input. Pinned by
  `tests/regression/test_replace_and_copy_pseudo_text.py`.
* **parser:** exclude clause-continuation keywords (`DELIMITED`, `TALLYING`,
  `POINTER`, ...) and SQL special registers (`SQLCODE`/`SQLSTATE`) from
  `looks_like_paragraph_boundary`. Fixes real-world layouts — a multi-source
  `STRING` with each `DELIMITED BY SIZE` clause on its own continuation
  line, and a period-less `DISPLAY` before a bare `SQLCODE` — that were
  silently truncating the AST. The period/`SECTION` lookahead is kept:
  dropping it misreads continuation-line operands named by *unexpanded*
  COPY members as boundaries (caught by mocky-mock's copybook fixtures).
  Pinned by `tests/regression/test_clause_continuation_boundary.py`.

## [1.2.0](https://github.com/Landparty/cobol-parser/compare/v1.1.0...v1.2.0) (2026-07-09)


### Features

* Add integration contract documentation for backend API ([cad4db6](https://github.com/Landparty/cobol-parser/commit/cad4db6b83e891496885b4dc6edc676dcab9c81c))
* **cli:** identify every CLI output with source_file and program_id ([94b1e98](https://github.com/Landparty/cobol-parser/commit/94b1e9844c5e3164a910200a4cca09674651bf3c))
* Create OKF knowledge bundle with lexer, parser, preprocessing, AST models, analysis, CLI, and tests documentation ([b2f8eeb](https://github.com/Landparty/cobol-parser/commit/b2f8eeb3b387bbaae3e1d1d186931c146e0c66e1))
* enhance copybook path resolution and numeric VALUE clause handling ([5111096](https://github.com/Landparty/cobol-parser/commit/511109675d9f48911f81c4c401a6e6ff9cb5aa4c))
* Initialize OKF v0.1 bundle with comprehensive documentation ([741a3f0](https://github.com/Landparty/cobol-parser/commit/741a3f0ceb335cd1ba5294d70b307cbf4e7c5bc2))
* **logging:** add detailed logging for parsing and error handling in COBOL parser ([6343f18](https://github.com/Landparty/cobol-parser/commit/6343f18fed1dc76097a2aa0db70557bacc688ae3))


### Bug Fixes

* address review — quote-parity tracking in copybook validator, CHANGELOG consistency ([b8267b1](https://github.com/Landparty/cobol-parser/commit/b8267b1b32b4f645735c6f666fcdb8f04b686040))
* address review feedback on H5 unterminated-literal recovery ([4c67876](https://github.com/Landparty/cobol-parser/commit/4c67876f50d58085b772047f2bfd66712717de28))
* **docs:** update test count and examples in CLAUDE.md ([150f2c3](https://github.com/Landparty/cobol-parser/commit/150f2c3497e9ee8b99ebd75055661a654d505051))
* honour COBOL AND/OR precedence in IF condition trees ([031b492](https://github.com/Landparty/cobol-parser/commit/031b492170d004427712c4d2c48d37c08d079a47))
* honour COBOL AND/OR precedence in IF condition trees (H4) ([5ebc346](https://github.com/Landparty/cobol-parser/commit/5ebc346a90fdc7b325b59c3ca2781e8e156066c6))
* join fixed-format numeric-literal continuation lines without a space ([f4dc2b3](https://github.com/Landparty/cobol-parser/commit/f4dc2b35e2eaf48546aab1d95c9afbd0e777c128))
* join fixed-format numeric-literal continuation lines without a space ([0bcf0cf](https://github.com/Landparty/cobol-parser/commit/0bcf0cf4fc00e3119017ebd7233d58d15cea16e5))
* **models:** match statement class names in find_all_by_type so CALL/SQL/IO statements are identifiable ([92e50c8](https://github.com/Landparty/cobol-parser/commit/92e50c80631855187801dbf5048bf20dc35b1f96))
* OPEN parser captures file names from every mode group ([f7b39b6](https://github.com/Landparty/cobol-parser/commit/f7b39b662da5b33017c2610590d14da7a0e2d23e))
* OPEN parser captures file names from every mode group ([b9f7595](https://github.com/Landparty/cobol-parser/commit/b9f7595fa704c4fa0d8cf7809f106493555bc87a))
* parse blank string-literal WHEN selectors (EVALUATE ... WHEN '  ') ([d8ad880](https://github.com/Landparty/cobol-parser/commit/d8ad880f4c7106d215ed65dd89f1ceadad3ea4a4))
* parse IO-statement clause bodies into the AST ([4a04b4e](https://github.com/Landparty/cobol-parser/commit/4a04b4ec8f83dc5330ae28b8f64452bfbca08eab))
* parse IO-statement clause bodies into the AST ([28f1de8](https://github.com/Landparty/cobol-parser/commit/28f1de8b7ab0a726228e079a44aa30580f65cd56))
* **parser:** resolve H9 issue where missing period absorbs following paragraph header ([7405700](https://github.com/Landparty/cobol-parser/commit/7405700748e54d23d03536d726298c11717639bd))
* prevent COMPUTE from swallowing following statements and improve expression boundary checks ([3e0493f](https://github.com/Landparty/cobol-parser/commit/3e0493f22862daa2c3e129ca2622059bf127a9cc))
* prevent MOVE/SUBTRACT/MULTIPLY/DIVIDE from swallowing following statements and improve size error clause handling ([c68a8ff](https://github.com/Landparty/cobol-parser/commit/c68a8ff9f45e2304d2dfb5aed49bed4437814622))
* recover from unterminated literal instead of aborting whole parse (H5) ([bf057e5](https://github.com/Landparty/cobol-parser/commit/bf057e526339ecd2085ff74bd05ccbac8c935754))
* register EVALUATE WHEN clauses as AST children ([f8f7877](https://github.com/Landparty/cobol-parser/commit/f8f787706dcbcf07d3f9fd9dd08ebb4f98d9768a))
* register EVALUATE WHEN clauses as AST children ([d37cec5](https://github.com/Landparty/cobol-parser/commit/d37cec57d47ce06dcdb06fee2c5b2f07ee0b33bc))
* report errors for malformed MOVE statements (audit H3) ([1b9886c](https://github.com/Landparty/cobol-parser/commit/1b9886c9fdfa3938498df9962120099a1359ac1a))
* report errors for malformed MOVE statements (audit H3) ([38ea9c6](https://github.com/Landparty/cobol-parser/commit/38ea9c6e538f123df3c9b8dfa22d3b78c152670b))
* resolve NIST corpus known issues — split headers, comment-entries, COMPUTE receivers, literal periods, COPY OF libraries ([6e2e33c](https://github.com/Landparty/cobol-parser/commit/6e2e33c478237fadd8933c9373de3be10ec360ba))
* reuse default clause on duplicate WHEN OTHER in EVALUATE ([2f597c2](https://github.com/Landparty/cobol-parser/commit/2f597c222a00c8bc344c154c1061bf40c403cf77))
* stop INSPECT/STRING/UNSTRING/EXEC-* from swallowing the next statement ([c6e030e](https://github.com/Landparty/cobol-parser/commit/c6e030e5bad4960b5cefed15b76dc1e2955d4368))
* stop INSPECT/STRING/UNSTRING/EXEC-* from swallowing the next statement ([066230a](https://github.com/Landparty/cobol-parser/commit/066230a9c1f2c3866a52bdd36ca464b189f777c8))
* strip layout tokens from IF condition before building the tree ([56e52c6](https://github.com/Landparty/cobol-parser/commit/56e52c6de8155083f231ecf71dc02388abf4aed8))
* type-safe source_id default in ProgramFlowAnalyzer.scan ([e676066](https://github.com/Landparty/cobol-parser/commit/e6760668dfdc51ee5b9a10c53f759ca1a3eae3da))
* unterminated literal no longer aborts whole parse, defeating COLLECT_ALL (H5) ([b87a654](https://github.com/Landparty/cobol-parser/commit/b87a6547bccac8ca450c23dab090b99b5f884320))
* Update timestamps in cli.md, integration.md, and lexer.md to reflect accurate commit dates ([177ac45](https://github.com/Landparty/cobol-parser/commit/177ac4511fe086f7996af0bf0a266f56f8424fca))


### Documentation

* add cobolparser gap-analysis audit report ([abbb3d1](https://github.com/Landparty/cobol-parser/commit/abbb3d18ecdf45801a2108133761e54f1f1602c4))
* add OKF docs, drift-prevention hooks, and homogenize README ([d178448](https://github.com/Landparty/cobol-parser/commit/d178448388246e60faf50d8467715a5ff85ca3c1))
* cobolparser gap-analysis audit ([2d88c83](https://github.com/Landparty/cobol-parser/commit/2d88c83d9f5cc1c08f1f33dff94a9a943101e1e6))
* **okf:** add analysis subsystem file ([3275545](https://github.com/Landparty/cobol-parser/commit/32755451ce7ce9e035781a5e1874dc6f05ccef62))
* **okf:** add ast-models subsystem file ([9222125](https://github.com/Landparty/cobol-parser/commit/922212538f8f5b3f638f1f454b8b0bd236acbde3))
* **okf:** add batch and profiling subsystem file ([7e23d7e](https://github.com/Landparty/cobol-parser/commit/7e23d7e80968255783c3e2eebbd9672a3c3c9807))
* **okf:** add CLI subsystem file ([c518d12](https://github.com/Landparty/cobol-parser/commit/c518d122a56a5aa078b2996bb2ba827622587dd8))
* **okf:** add conventions subsystem file ([f7c0921](https://github.com/Landparty/cobol-parser/commit/f7c0921b14f5681e14fb0f6b1ebe6c97f41fe845))
* **okf:** add dialects and configuration subsystem file ([6d3bec2](https://github.com/Landparty/cobol-parser/commit/6d3bec22605100c51b19f726bfd8307dc19daa1b))
* **okf:** add lexer subsystem file ([20482f7](https://github.com/Landparty/cobol-parser/commit/20482f796c1d6a91705c5ac8ee460d7262e56d5c))
* **okf:** add OKF design spec ([dab92e8](https://github.com/Landparty/cobol-parser/commit/dab92e8e721be6f7dea96a1b127193469e3bde97))
* **okf:** add OKF implementation plan ([6d7599d](https://github.com/Landparty/cobol-parser/commit/6d7599ddaef3e56a95583842a01b9f9e31169883))
* **okf:** add OKF master index ([a9d364f](https://github.com/Landparty/cobol-parser/commit/a9d364f0329a84e4387b51a082459668697a2cf3))
* **okf:** add parser subsystem file ([fcacac2](https://github.com/Landparty/cobol-parser/commit/fcacac2e44b810d9e20685d396770e5294f65d9c))
* **okf:** add preprocessing subsystem file ([c5bb598](https://github.com/Landparty/cobol-parser/commit/c5bb598dbf89dfba9d9a20a2fdc41baf7cdf2263))
* **okf:** add tests subsystem file ([531b112](https://github.com/Landparty/cobol-parser/commit/531b1123717c7d480310a37f842f2a3718cdb2c2))
* **okf:** apply final review fixes — export bucket, counts, dual LexerError, minor ([9eba638](https://github.com/Landparty/cobol-parser/commit/9eba6389f50f968b1ad0bdf09e0e829464b6d9e3))
* **okf:** fix analysis.md — correct FlowEdgeType enum and HostVariableResolver API ([e95fdb3](https://github.com/Landparty/cobol-parser/commit/e95fdb3a38185e4fafd8b7e66dfc0ef5611f6975))
* **okf:** fix Files section, Ruff ignores, dev deps in conventions.md ([8a9d1c7](https://github.com/Landparty/cobol-parser/commit/8a9d1c752c963291dd68d4674e1281c4cdc446d1))
* **okf:** fix minor field-name inaccuracies in lexer.md ([e7277ed](https://github.com/Landparty/cobol-parser/commit/e7277ed81f3d600d85b000c46dfac8f2f54c8a98))
* **okf:** fix ParseStatistics fields in dialects.md ([815d1e4](https://github.com/Landparty/cobol-parser/commit/815d1e4a627dc432d04f16d21e35b6c63d7232e2))
* **okf:** remove outdated OKF design spec — no longer needed ([b091747](https://github.com/Landparty/cobol-parser/commit/b09174736c1af244cccaeb6c3fd0b36807d6224b))

### Added

* **OCCURS `ASCENDING/DESCENDING KEY` and multi-index `INDEXED BY` capture**
  (audit 2026-07-09). `OccursClause` gained `key_clauses` (a list of
  `{"direction", "keys"}`, serialized when present) and `index_names` (all
  `INDEXED BY` names; `indexed_by` still holds the first for backward
  compatibility). Previously the `ASCENDING/DESCENDING KEY` clause was dropped
  entirely — and, because it sits before `INDEXED BY` in standard COBOL, its
  presence also caused the following `INDEXED BY` to be silently consumed and
  lost. `INDEXED BY a b` also kept only the last index. Mirrored in the Cython
  `_data_fast` fast-path.

* **`REWRITE ... FROM`, `START ... KEY IS <data-name>`, `STOP RUN RETURNING
  <x>` operands, and the `ACCEPT ... FROM DATE/TIME <format>` phrase are now
  captured** (audit 2026-07-09). New fields: `IORewriteStatement.from_clause`,
  `IOStartStatement.key_name`, `StopStatement.returning`; the ACCEPT format
  phrase folds into `from_source`. All were previously consumed and discarded
  with `errors=[]`/`warnings=[]`; the ACCEPT format word was additionally
  re-parsed as a phantom paragraph.

* **DATA division drop warnings** (audit 2026-07-09). Unrecognized data-item
  clause tokens (GROUP-USAGE, VOLATILE, DYNAMIC LENGTH, ...) now emit an
  "Unparsed token ... in data item" warning instead of being consumed
  silently — symmetric with the ENVIRONMENT division's SELECT handling.

* **`PERFORM VARYING ... AFTER ...` multi-dimension support** (audit
  2026-07-07 H2). The `AFTER var FROM x BY y [UNTIL cond]` dimensions of a
  2-D/3-D table loop are parsed into `PerformStatement.after_clauses`
  (serialized as `after_clauses` when present). Previously the whole AFTER
  phrase was absorbed into the first UNTIL condition string (with token-type
  names leaking into it) and the second dimension was lost.

* **SELECT clause capture: `ALTERNATE RECORD KEY` (with `WITH DUPLICATES`),
  `PADDING CHARACTER`, `RESERVE n AREAS`, `SHARING WITH`, `LOCK MODE`
  (with `LOCK ON` / `WITH ROLLBACK`), `PASSWORD`, `RECORD DELIMITER`, and
  the second (VSAM) `FILE STATUS` variable** (audit 2026-07-07 H5). The
  `SelectStatement` model already had the fields; the parser now populates
  them. `assign_device_type` is populated for recognizable device words
  (`DISK`, `PRINTER`, ...) and IBM `UT-S-`/`UR-`/`DA-` prefixed assignment
  names. Unknown SELECT clause tokens now produce an "Unparsed token ... in
  SELECT" warning instead of being silently consumed.

* **Conditional-compilation diagnostics** (audit 2026-07-07 H7).
  `preprocess_conditional_compilation()` accepts a `warnings` list and
  reports: unsupported `>>IF` conditions (which delete the guarded block),
  malformed `>>DEFINE`, stray `>>ELSE`/`>>END-IF`, unknown `>>` directives
  passed through, and unclosed `>>IF` at end of input. The copybook
  expansion path routes these into `ExpansionStatistics.warnings` (and from
  there into `ParseResult.warnings` via `parse_cobol_with_expansion`); the
  CLI prints them to stderr. Previously all of these were completely silent.

* **Dropped-COPY diagnostics** (audit 2026-07-07 H6a/H6c). A `COPY` whose
  clause scan never reaches a terminating period (e.g. `COPY FOO` with no
  `.`, or `COPY FOO BAR.`) is never expanded — this now produces a "COPY
  ... was NOT expanded" warning on `ExpansionStatistics.warnings` instead
  of the copybook's content silently not existing. An unterminated
  `==pseudo-text==` REPLACING operand likewise warns instead of silently
  abandoning the clause. `extract_copy_statements()` accepts an optional
  `warnings` list. The COPY scanner also gained a left-side word-boundary
  check so `GOODCOPY.` is no longer probed as a COPY statement.

### Changed

* **`ON SIZE ERROR` / `NOT ON SIZE ERROR` bodies now parse every verb**
  (audit 2026-07-07 H1). The handler-body parser dispatches through the
  statement registry (same mechanism as IF/EVALUATE/IO clause bodies), so
  `ON SIZE ERROR PERFORM ERR-PARA` (or CALL, IF, ADD, ...) is captured,
  serialized, and visible to `find_all_by_type`. Previously only DISPLAY
  and MOVE were mini-parsed and every other verb was skipped token-by-token
  — the handler vanished with `errors=0`. Affects
  ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE.

* **`DECIMAL-POINT IS COMMA` now warns** (audit 2026-07-07 H4). The clause
  is recorded in division metadata but the lexer does not honor it (comma
  decimal literals misparse), so parsing a program that declares it now
  produces an explicit `ParseResult.warnings` entry instead of silent
  misparsing. (Actually honoring the clause remains open.)

* **`CobolExpression.to_dict()` now includes `operands`** — condition/
  expression text (e.g. PERFORM UNTIL conditions) previously vanished at
  the JSON boundary.

* **`MemoryConfiguration` documents its no-op fields** (audit 2026-07-07
  M5): `max_memory_mb`, `enable_streaming` and `chunk_size_kb` are
  validated but not enforced; `max_error_count` is enforced.
  `interface-contract.md` now states the real `success`/`ast` semantics
  (audit 2026-07-07 M8): `ast` can be non-None while `success` is False.

* **`cobol-parser coverage status` handles malformed artifacts** (audit
  2026-07-07 M10): invalid JSON or a non-object artifact reports a clean
  error and exit code 1 instead of an uncaught traceback.

### Added (2026-07-07 C1-C8 remediation)

* **Multi-program compilation units are now parsed** (audit 2026-07-07 C1).
  Stacked or nested programs delimited by `END PROGRAM` are each parsed into
  their own `CobolProgram`; the first is `ParseResult.ast` and the rest are
  attached to `ast.contained_programs` (serialized as `contained_programs`,
  included in `get_all_statements()`), with a summary warning. Previously
  everything after the first program was silently dropped with `errors=0`
  (NIST `IC228A` retained ~3% of its statements).

* **XML/JSON GENERATE/PARSE statement support** (audit 2026-07-07 C3). New
  `XmlJsonStatementParser` + `XmlJsonStatement` AST node capture verb,
  action, primary operands, and raw trailing-clause text. Previously the
  `XML`/`JSON` keyword was silently skipped and the remainder mis-parsed as
  a Report Writer `GENERATE`.

* **Unsupported-statement and unparsed-token warnings** (audit 2026-07-07
  C2). When no statement parser matches, the skip is now recorded on
  `ParseResult.warnings` with the token and line instead of only
  `logger.debug`: known unsupported verbs (`INVOKE`, `EXHIBIT`, `SEND`,
  `ENABLE`, ...) get an "Unsupported statement" warning; leftover clause
  tokens from partially-supported statements get an "Unparsed tokens"
  warning. `ALLOCATE`, `FREE`, `EXHIBIT`, `INVOKE`, `XML`, and `JSON` were
  added to `STATEMENT_KEYWORDS` so they are treated as statement starts
  rather than becoming phantom paragraph names. Note: programs that
  previously parsed with `warnings == []` may now carry warnings — that is
  the fix working, not a regression; each warning marks content that was
  already being dropped silently.

### Fixed

* **Eight HIGH-severity findings from `reports/open-findings.md` (2026-07-08
  re-verification pass), all pinned by
  `tests/regression/test_open_findings_high_regressions.py`:**
  - **H1** — `SET ADDRESS OF x TO y` produced an empty `SetStatement`
    (`targets: []`, `set_type: null`, `value: null`) because the
    target-collection loop only accepted `IDENTIFIER`/`STRING_LITERAL`
    tokens; `OF` lexes as its own dedicated `TokenType.OF`, not
    `IDENTIFIER`, so the loop broke immediately on it. `OF` is now
    recognized and skipped so the pointer/`TO`/target tokens are reached.
  - **H2** — `COMPUTE` with unbalanced parentheses was silently accepted,
    and once `paren_depth` was left non-zero by a stray `(` the
    statement-boundary check (gated on `paren_depth == 0`) never re-armed,
    silently folding a well-formed following statement into the
    expression string. A boundary check now fires regardless of
    `paren_depth`, and a final `paren_depth != 0` check now reports
    "COMPUTE statement has unbalanced parentheses in expression" instead
    of accepting silently.
  - **H3** — `PERFORM para-name JUNK-TOKEN.` speculatively consumed a
    trailing `IDENTIFIER` as a candidate TIMES value and discarded it with
    **no warning at all** when `TIMES`/`TIME` didn't follow
    (`errors=[], warnings=[]`, `times_count: null`). The TIMES-clause
    lookahead now peeks past the candidate token before committing to
    consuming it, and emits a warning identifying the discarded token when
    it isn't a valid TIMES clause.
  - **H4** — `perform_parser.py` had 5 bare `except ParseError: pass`
    sites (VARYING/UNTIL/inline-body parsing) with no logging at all, not
    even DEBUG — a nested-parse failure could vanish completely
    untraceable. All 5 sites now log the suppressed exception at DEBUG.
  - **H5** — `MoveTypeChecker` silently skipped every MOVE whose source or
    target category couldn't be resolved (`UNKNOWN`/`FIGURATIVE`), with no
    counter anywhere on `MoveTypeReport` — 3 MOVEs on undeclared
    identifiers (e.g. an unexpanded copybook) produced
    `violations: [], error_count: 0, warning_count: 0`, a false all-clear.
    `MoveTypeReport` gained an `unresolved_count` field (serialized in
    `to_dict()`) that counts every operand the checker couldn't resolve.
  - **H6** — the Tier-2 (directory-index) copybook resolver fast path in
    `PathResolver.resolve()` returned an indexed path after only an
    `os.path.getsize()` check, never calling `validate_path_within_directory()`
    (which the Tier-3 path does call). Since the index is built via
    `os.scandir()` + `entry.is_file()` (which follows symlinks), a symlink
    inside a search directory pointing outside it would be served with no
    containment check. Both Tier-2 fast-path hits (exact and
    extension-suffixed) now validate containment before returning.
    Separately, the `".." in file_path` guard was naive substring
    matching, false-flagging filenames like `weird..name.cpy`; it's now a
    path-segment check (`.. ` as a whole segment only).
  - **H7** — an unterminated string literal in the default parse path was
    fully silent: the lexer's error was gated on `if not self.free_form`,
    and `parse_cobol()` always lexes with `free_form=True` after
    normalization, so `DISPLAY "UNCLOSED` followed by a well-formed
    statement parsed clean with the literal silently closed at the line
    boundary. The lexer (both the pure-Python path and the `_lexer_fast`
    Cython path) now records a warning — surfaced via
    `ParseResult.warnings` — instead of staying silent, without promoting
    it to a hard error (a lone quote can legitimately appear in a
    free-form comment). Separately investigated the report's "unclosed
    `IF`s with no bodies" sub-claim: confirmed this is legal, correctly
    scope-nested COBOL (period-terminated or nesting-closed IFs need no
    `END-IF`), not a bug — no change made for that sub-case.
  - **H8** — `CLOSE` used an if/elif chain across `REEL`/`UNIT`/`WITH`
    (one branch per file, applied only once), and the outer per-file loop
    required the next token to be a plain `IDENTIFIER` to continue, so
    `CLOSE F REEL WITH NO REWIND.` kept only `reel: true` and dropped
    `no_rewind` (only warn-masked via the generic "unparsed tokens"
    fallback). The per-file option parse is now a loop that keeps applying
    options until none match, so combined options on one file (and across
    multiple files in one CLOSE) all survive.

  Also fixed while verifying H2: `tests/samples/arithmetic_operations.cbl`
  had a `FUNCTION MAX(WS-NUM-1, WS-NUM-2, WS-NUM-3)` line that overflowed
  fixed-format column 72 (the closing `)` landed in column 73 and was
  silently truncated by `normalize_fixed_format`) — previously masked by
  the very H2 bug (the truncated, unbalanced expression silently absorbed
  the next statement); now correctly surfaced by the H2 fix and corrected
  in the sample by removing the space after each comma.

  Noted but intentionally not fixed in that pass (out of scope of the 8
  listed findings, and higher blast-radius core-parser surgery): a
  statement with no terminating period, immediately followed by what
  should be a new paragraph header, caused the paragraph-name identifier
  to be absorbed as a trailing operand of the preceding statement instead
  of starting a new paragraph. Flagged as H9 and fixed in a follow-up
  pass — see below.

* **H9 — a statement missing its terminating period could absorb the
  following paragraph/section header as a trailing operand** (follow-up to
  the H1-H8 pass above; pinned by
  `tests/regression/test_open_findings_high_regressions.py::TestH9MissingPeriodParagraphBoundary`).
  Operand-collection loops with no boundary awareness (`DISPLAY`'s item
  list, `MOVE`'s target list, `COMPUTE`'s expression capture, `STRING`'s
  operand list) had no way to tell a legitimate trailing operand from a
  following paragraph name once the statement's own period was missing —
  both are just "`IDENTIFIER` then `PERIOD`" to the grammar, and
  `is_statement_boundary()` only catches *known* verbs lexed as plain
  identifiers, not ordinary user-defined paragraph names. Fixed via a new
  `looks_like_paragraph_boundary()` helper (`parsers/statements/_utils.py`)
  that mirrors COBOL's own disambiguator instead of guessing from grammar
  shape alone: the candidate identifier only counts as a paragraph boundary
  when it starts its own source line, is immediately followed by a period
  or `SECTION`, and is not a name declared in the DATA DIVISION (excluded
  so a genuinely wrapped continuation-line operand, e.g. `DISPLAY\n
  WS-X.`, is not misread just because it opens its line). The DATA DIVISION
  cross-check is threaded through `ParseContext.known_data_names`, computed
  once per PROCEDURE DIVISION parse. Recovery now warns instead of silently
  re-interpreting, per the H7/H8 precedent. Applied to the six statement
  parsers confirmed (by direct repro) to swallow the following paragraph:
  `DISPLAY`, `MOVE`, `COMPUTE`, `STRING`, `UNSTRING` (its `INTO` target
  list), and `INSPECT` (both its `TALLYING` counter-name loop and its
  outer "consume to period" trailer, which is what actually swallowed the
  paragraph name for `INSPECT ... REPLACING`, since the `REPLACING`
  clause loop itself already stopped safely). Not probed / not fixed:
  other statement parsers with a similarly open-ended list/text-collection
  loop may share this gap; only the six demonstrated cases were fixed here,
  per the report's own "needs its own scoped investigation" framing for
  this finding.

* **A period-less statement could silently swallow an unsupported (or even a
  fully-supported) following verb** (residual of audit 2026-07-07 C2). C2
  taught the top-level PROCEDURE DIVISION dispatch loop to warn when it
  directly encounters a verb with no registered parser — but that loop only
  sees the verb directly when a period separates it from the previous
  statement. Without a period, the previous statement's own trailing-token
  loop (MOVE's target list, the arithmetic operand collector, ...) decides
  for itself whether to stop, via `STATEMENT_TOKEN_TYPES`/
  `STATEMENT_KEYWORDS` (`_utils.py`). Those sets were missing several verbs
  `_UNSUPPORTED_VERBS` already labeled (`DISABLE`, `ENABLE`, `PURGE`,
  `RAISE`, `READY`, `RECEIVE`, `RESET`, `RESUME`, `SEND`, `SERVICE`,
  `TRANSFORM`), missing the `TokenType` (though not the string) for
  `EXECUTE`/`EXHIBIT`/`INVOKE`, and were completely missing two verbs with
  **registered parsers** (`COMMIT`, `ROLLBACK` — the worse case: a fully
  supported statement vanished) plus several more real, previously
  unlabeled verbs (`CHAIN`, `ENTER`, `EXAMINE`, `GOTO` fused spelling,
  `INITIATE`, `NOTE`, `RECOVER`, `SUPPRESS`, `TERMINATE`). All are now in
  `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS`, and the newly-recognized
  unsupported verbs were added to `_UNSUPPORTED_VERBS` for a specific
  warning message. Separately, `PURGE`/`RAISE`/`RESUME` have no dedicated
  lexer `TokenType` at all (they lex as plain `IDENTIFIER`), so the
  `STATEMENT_KEYWORDS` fix alone didn't reach ten *other* list-collecting
  loops that never consulted `STATEMENT_KEYWORDS`/`is_statement_boundary`
  at all: `DISPLAY`'s item list, `CANCEL`'s program-name list, `SET`'s
  target list, `OPEN`/`CLOSE`'s file-name lists, `INITIALIZE`'s target
  list, `UNSTRING`'s `INTO` target list, `SORT`/`MERGE`'s shared
  `_parse_keys`/`_parse_file_list` helpers, and `INSPECT`'s
  `_parse_tallying` counter-name loop (separate nested loops with their own
  hand-rolled boundary keyword list — or, for `_parse_tallying`, no
  boundary check at all — bypassing the `is_statement_boundary()` check
  their statement's outer loop already had). Each of those ten loops now
  also breaks on `is_statement_boundary()` before accepting a bare
  `IDENTIFIER` as a list item. A related, more severe pre-existing bug in
  `PerformStatementParser._parse_until_condition_only` (the out-of-line
  `PERFORM paragraph-name UNTIL condition` form) had **no boundary check at
  all** — a period-less `PERFORM ... UNTIL cond` swallowed every remaining
  token in the program into the condition string, including entire
  well-formed statements, not just unsupported verbs; it now stops at the
  same `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` boundary the sibling
  `_collect_until_condition_tokens` helper already used. A fourth finding,
  in `EvaluateStatementParser`: `_parse_subjects` (the subject list before
  the first `WHEN`) had no boundary check, same shape as the ten
  list-collecting loops above. Worse, the outer clause-scan loop treated
  any non-`WHEN`/`END-EVALUATE` token as noise to skip past, so a malformed
  (missing-`WHEN`) `EVALUATE` could consume forward past an entire
  intervening statement — verified with a trailing `MOVE` immediately
  followed by a second, well-formed `EVALUATE`: the first EVALUATE annexed
  the *second* EVALUATE's `WHEN` clause as its own, silently erasing the
  MOVE and merging two EVALUATEs into one, with zero errors and zero
  warnings. Both loops now stop at the same boundary check. `IfStatement
  Parser`'s condition collector was probed and confirmed already safe.
  Pinned by `tests/regression/test_tier7_unsupported_verb_boundary.py`.

* **`ProgramFlowAnalyzer` missed control-flow edges nested in clause bodies**
  (audit 2026-07-09). PERFORM/GO TO/CALL statements inside a `READ ... AT END`,
  `WRITE ... INVALID KEY`, `... ON SIZE ERROR`, or `STRING ... ON OVERFLOW`
  clause produced no edge, cascading into false `unreachable_nodes` reports and
  missing arrows in generated flowcharts. `scan()` now recurses into those
  clause bodies (matching `coverage_analyzer`). `ACCEPT`/`UNLOCK` with a
  missing operand no longer swallow the following statement's verb.

* **`EVALUATE ... WHEN '  '` (blank string-literal selector) parses again.**
  The lexer strips quotes off string literals, so a blank literal's token
  value is whitespace-only; the WHEN selector builder filtered it out as an
  empty artifact and reported "WHEN clause must have at least one selector"
  on valid programs. Blank literals are now re-quoted (`selector value
  "'  '"`) so they survive; non-blank literals are unchanged. This is the
  standard IMS DL/I status-code idiom and blocked 5/17 programs in the
  legacy-application corpus. Pinned by
  `tests/regression/test_evaluate_space_literal_when.py`.

* **Three real-world parse-content-drop bugs found by mockymock's refreshed
  corpus sweep against `legacy-application`** (all 26 corpus programs now
  parse and generate clean, zero refusals — up from 3 `PARSE_WARNING`s):
  - `SUBTRACT a FROM b GIVING c` silently dropped the `GIVING c` clause
    whenever it appeared (the 3-operand form's target was always `b`,
    never `c`) — the `FROM` branch never checked for a trailing `GIVING`
    the way the `ADD ... TO` branch already did. Fixed by mirroring that
    check. Also fixed the more general root cause in
    `consume_keyword_and_operand`: it only skipped `NEWLINE` tokens
    *between* a keyword and its operand, not *before* checking whether the
    keyword was even present, so `GIVING` (or any such optional clause) on
    its own continuation line — ordinary free-form COBOL layout — was
    missed entirely. This also fixes the same class of bug for `ADD ... TO
    ... GIVING` when `GIVING` is on a continuation line.
  - `DISPLAY` stopped at a subscripted operand like `SQLERRD(3)`: the item
    loop only accepted `STRING_LITERAL`/`IDENTIFIER`/`NUMERIC_LITERAL`
    tokens, so the bare `(` token after the identifier fell through to the
    "unknown token, stop parsing" branch, dropping the subscript and
    everything after it. Subscripted identifiers are now folded into a
    single display item (`SQLERRD(3)`).
  - `WRITE record FROM 'literal'` (an IBM/GnuCOBOL extension for writing a
    fixed message record) wasn't recognized — the `FROM` source only
    accepted `IDENTIFIER`; a string literal was left unconsumed. Now
    accepted and stored quoted, matching how other operand literals are
    serialized.
  Pinned by `tests/unit/test_arithmetic_size_error_branches.py`,
  `tests/unit/test_display_parser.py`, and
  `tests/unit/io_statements/test_write_close_parsers.py`.

* **`GO TO a b c DEPENDING ON x` no longer collapses to `GO TO a`** (audit
  2026-07-07 C4). All targets are kept (`GoStatement.target_paragraphs`)
  and the `DEPENDING ON` variable is captured. The extra targets are only
  consumed when a `DEPENDING` clause actually follows (peek-ahead), so an
  identifier after a missing sentence period is still treated as the next
  paragraph rather than swallowed. Previously the extra targets and the
  variable were silently skipped — and the variable could become a phantom
  paragraph.

* **Level-88 condition names and level-66 RENAMES survive `to_dict()`**
  (audit 2026-07-07 C5). `CobolDataItem.to_dict()` emits `condition_names`;
  `CobolSection.to_dict()` emits `renames_items`. Both node types were
  parsed in-memory but dropped from every JSON export.

* **`CALL ... NOT ON EXCEPTION` handler serialization and traversal** (audit
  2026-07-07 C6). `CallStatement.to_dict()` now includes
  `not_on_exception`, and all CALL handler statements are registered as AST
  children so `find_all_by_type()` agrees with `get_all_statements()`.

* **CLI exit codes are honest** (audit 2026-07-07 C7). `cobol-parser parse`
  exits `2` (with a stderr summary) when the parse completed with collected
  errors; `batch` exits `2` when any file has a `read_error` or
  `success=false`; analyzer subcommands print a stderr warning when
  analyzing a partial AST. Previously every command exited `0` as long as
  an AST existed.

* **A poisoned file no longer aborts an entire batch** (audit 2026-07-07
  C8). Batch workers catch parse-time exceptions (and `UnicodeDecodeError`
  under `errors="strict"`) and record them as per-file
  `BatchResult.read_error` instead of propagating out of the pool and
  losing every other file's result.

* **`WRITE ... ADVANCING n LINES/PAGE` keeps the count and unit** (audit
  2026-07-07 H3). The WRITE parser now populates
  `IOWriteStatement.advancing_clause`; previously the count/unit tokens
  were consumed and dropped.

* **Copybook expansion warnings propagate** (audit 2026-07-07 H6).
  `parse_cobol_with_expansion` copies `expansion.statistics.warnings`
  (lossy encoding decodes, content validation, level-number mismatches)
  onto `ParseResult.warnings`; they were previously discarded with the
  `CopybookExpansion` object.

### Added (pre-2026-07-07)

* Strict support tests for the real-life NIST COBOL-85 corpus
  (`tests/integration/test_nist_cobol85_support.py`). All 459 `.CBL`
  programs in `examples/cobol/` must now parse **error-free** (the
  pre-existing corpus test only checked that parsing does not crash).
  455/459 currently pass. The 4 remaining are pinned
  as strict-xfail `KNOWN_ISSUES` with documented causes, so any parser
  improvement must remove the entry and the list only ever shrinks:
  `OBNC1M` (a COBOL-74 obsolete-feature test that embeds a phony program in
  a comment-entry, requiring Area A/B-aware parsing), `SM101A` (requires
  copybook expansion by design), and `SM206A`/`SM208A` (need `COPY REPLACING` /
  `REPLACE` pseudo-text substitution — uncovered by the H3 MOVE fix, see
  *Fixed* below). (`NC205A`, also uncovered by the H3 fix, was a
  continuation-line bug that shattered a split numeric literal and is now
  fixed — see *Fixed* below.) `SM101A` and `SM207A` must additionally
  parse clean with copybook expansion against the suite's own copybooks,
  and all 51 `.CPY` copybooks must pass `validate_copybook_content`.

* All CLI outputs are now properly identified. Every JSON document emitted by
  the `cobol-parser` CLI starts with a `source_file` key (the input path as
  given on the command line) and, for subcommands that parse the source, a
  `program_id` key (the PROGRAM-ID from the IDENTIFICATION DIVISION, or
  `null` when the program has none). This covers `analyze`, `dead-code`,
  `program-flow` (JSON format), `io-sequence`, `move-type-check`,
  `linkage-check`, `language-env`, `ims-dli`, `expand`, and `parse`
  (`--errors`/`--stats` wrapper). `batch` entries additionally carry
  `program_id` next to the existing `path`. Mermaid flowcharts from
  `program-flow --format mermaid` now start with a `%% Program: <name>`
  comment header (DOT output already named the digraph after the program).
  The contract is pinned by `tests/unit/cli/test_output_identification.py`.

### Changed

* **CLI output shapes for list-style results** (part of the output
  identification change above; library APIs are unchanged). `tokenize` now
  emits `{"source_file": ..., "tokens": [...]}` instead of a bare token
  list. `parse --find-type` emits `{"source_file", "program_id",
  "node_type", "matches"}` instead of a bare node list, and dotted-path
  extraction (`parse <file> <path>`) emits `{"source_file", "program_id",
  "path", "result"}` instead of the bare subtree; with `--errors`/`--stats`
  a path extraction now carries those keys directly instead of being wrapped
  under an `"ast"` key.

* `PictureClause` now validates the PICTURE pattern and exposes `is_valid` and
  `validation_errors` (also surfaced in `to_dict()`). Validation is
  conservative -- it flags only unambiguously illegal pictures (empty pattern,
  illegal characters, malformed/empty/zero repeat factors, unbalanced
  parentheses, more than one `V`, both `V` and a decimal point, multiple
  decimal points, and a misplaced or duplicated `S`) so valid pictures are
  never rejected. Pattern parsing remains lenient: an invalid picture is
  flagged but never aborts the surrounding parse.

### Changed

* Internal code-review cleanup removing dead code and consolidating
  duplication (no public-API or behaviour changes; full test suite unchanged).
  Removed unreferenced symbols (`ParserHost` protocol, `TokenStream.match_value`,
  four unused `CobolFileDescription` builder methods, the orphaned
  `TestReference` dataclass, a stray `TypeVar`, and ten dead fixed-format column
  constants in the lexer that duplicated the preprocessor's). Consolidated
  copy-pasted logic behind shared helpers: per-subcommand parse/emit/parser
  boilerplate in the CLI (`_parse_or_fail`, `_emit_report`,
  `_build_analyzer_parser`, `_stats_dict`); clause-list serialization and
  clause/operand setters in the statement AST models
  (`CobolStatement._serialize_clauses` / `_add_unique_operand` and IO clause
  mixins); IO statement-parser preamble and INVALID KEY / KEY-IS handling
  (`create_statement`, `consume_key_is`, `try_consume_keyword`, and reuse of
  `parse_invalid_key_clauses`); and the duplicated unescaped-quote scan in the
  copybook preprocessor.
* Silent `except Exception` handlers that swallowed failures without a trace
  now emit diagnostics instead. `batch.parse_files_with_copybooks()` logs a
  `WARNING` (logger `cobolparser.batch`) when copybook expansion fails and it
  falls back to parsing raw source, and the statement-parser probe helpers
  `peek_token()` / `try_parse_nested()` log at `DEBUG` when their "never raise"
  contract suppresses an exception. The fall-back behaviour itself is
  unchanged. The dead broad-`except` around `CobolProgram.get_division()` in
  the CRUD matrix generator (a plain dict lookup that cannot raise) was
  removed.

### Fixed

* **`INSPECT`, `STRING`, and `UNSTRING` no longer swallow the following
  statement**, and a **missing `END-EXEC` on `EXEC SQL`/`CICS`/`IMS` blocks is
  now reported instead of silently consuming the rest of the program** (audit
  2026-07-06 H2 — the last four verbs in the "swallow the next statement"
  class after MOVE/arithmetic/COMPUTE). A COBOL sentence may legally contain
  several statements with no separating period; previously an un-punctuated
  `INSPECT`/`STRING`/`UNSTRING` immediately followed by another statement (e.g.
  `INSPECT WS-X TALLYING WS-C FOR ALL 'A'  DISPLAY 'X'`) consumed that
  statement — INSPECT's trailing "consume to period" loop and the
  STRING/UNSTRING main-loop `else: consume()` fall-throughs never checked a
  statement boundary. A new shared `is_statement_boundary()` predicate
  (`parsers/statements/_utils.py`, unioning `STATEMENT_TOKEN_TYPES` /
  `STATEMENT_KEYWORDS` / `SCOPE_TERMINATORS` / `CONTROL_FLOW_BOUNDARIES`) now
  stops all three at the boundary; behavior stays `errors=0`. `EXEC` blocks
  can't use a content boundary (embedded SQL legitimately contains
  SET/DELETE/UPDATE/CALL/OPEN/CLOSE), so `collect_exec_sql_text` instead
  detects a missing `END-EXEC` and records an "Unterminated EXEC block" parse
  error, changing that malformed case from a silent `errors=0`,
  `success=True` swallow to a reported error (`success=False`); well-formed
  blocks are unchanged. Pinned by `TestInspectDoesNotSwallowFollowingStatement`,
  `TestStringDoesNotSwallowFollowingStatement`,
  `TestUnstringDoesNotSwallowFollowingStatement`, and
  `TestExecMissingEndExecReportsError` in
  `tests/regression/test_tier2_silent_drop_regressions.py`.

* `IF` condition trees now honour COBOL AND/OR precedence (audit finding H4).
  `IfStatementParser._build_condition_expression` split on the first of
  `("AND", "OR")` it found, making `AND` the tree root — so
  `IF A = 1 OR B = 2 AND C = 3` parsed as `(A OR B) AND C` instead of the
  correct `A OR (B AND C)`, silently inverting the logic for any analyzer that
  reads the condition tree. The split now runs `OR` before `AND` (OR binds
  loosest, so it becomes the root and `AND` nests beneath it) and is
  parenthesis-aware: it strips a fully-enclosing `( ... )` wrapper and only
  splits on operators at the top paren level, so explicit grouping such as
  `IF (A = 1 OR B = 2) AND C = 3` correctly keeps `AND` as the root. As a
  side effect, parenthesised operands no longer leak stray `(`/`)` tokens into
  the comparison strings. The split now picks the rightmost top-level operator,
  making repeated same-precedence chains (`A OR B OR C`) left-associative to
  match COBOL's left-to-right evaluation. Layout tokens (whitespace, end-of-line,
  continuation, comments) are now stripped from the condition token list before
  the tree is built, so a fully-parenthesised condition such as
  `IF (A = 1 OR B = 2)` is no longer defeated by the trailing end-of-line token
  (which previously left `tokens[-1] != ")"`, blocking the enclosing-paren strip
  and collapsing the whole condition into a bogus comparison); multi-line
  conditions are handled more robustly for the same reason. Pinned by
  `tests/unit/test_if_parser_comprehensive.py::TestIfConditionPrecedence`.

* An unterminated string literal at end of input no longer aborts the whole
  parse under `ErrorRecoveryMode.COLLECT_ALL` (audit finding H5). Fixed-format
  normalization (`normalize_fixed_format`) raises `ValueError` on a literal
  still open at EOF; that raise was reached before error recovery was active,
  so a single bad literal collapsed the entire program to `ast=None` — in
  `CobolParser._parse_core` (via the generic exception safety net) and in the
  `parse_cobol` convenience function (which caught it but returned `ast=None`
  regardless of mode). `_parse_core` now records the unterminated-literal error
  and, unless in `FAIL_FAST`, re-normalizes with `merge_continued_literals=False`
  (a non-raising best-effort path the lexer already tokenizes permissively) so a
  partial AST survives; `parse_cobol` defers to the parser for this recovery.
  `FAIL_FAST` still aborts with the error, and calling `normalize_fixed_format`
  directly still raises by default. Pinned by
  `tests/unit/test_critical_fixes.py::TestUnterminatedLiteralDoesNotAbortParse`.
* **Malformed `MOVE` statements no longer parse silently (audit finding H3).**
  The MOVE parser accepted incomplete input and produced a plausible-but-wrong
  node with `errors == 0`: `MOVE A TO.` yielded a `MoveStatement` with
  `targets: []`, `MOVE A` (no `TO`) and a stream truncated at `MOVE A TO` were
  likewise accepted. The parser now reports a diagnostic (via the parse
  context, the same path GO/CALL use) when `TO` is missing or when no receiving
  field follows `TO`; well-formed MOVEs — including multi-target
  (`MOVE A TO B C`), subscripted targets (`MOVE A TO B(I)`), literals, figurative
  constants, and `MOVE CORRESPONDING` — stay error-free. A missing *source*
  (`MOVE TO X`) is intentionally not flagged, because it is indistinguishable
  from stray `*>`-comment / pseudo-text the preprocessor does not yet strip and
  flagging it faulted otherwise-valid programs. Pinned by
  `tests/unit/test_move_malformed_diagnostics.py`. This surfaced that three NIST
  programs were previously passing the error-free guarantee *only* by way of
  this silent acceptance — `SM206A`/`SM208A` (need `COPY REPLACING` /`REPLACE`
  pseudo-text substitution) and `NC205A` (the continuation-line bug fixed
  below); `SM206A`/`SM208A` are now pinned as strict-xfail `KNOWN_ISSUES`,
  while `NC205A` is fixed in this same release.

* `normalize_fixed_format` now joins **non-literal fixed-format continuation
  lines** (indicator `-` in column 7) with no intervening space, matching the
  COBOL rule that the first non-blank character of a continuation line is the
  successor of the last non-blank character of the continued line. Previously a
  space was injected before every such chunk, so a numeric literal split across
  continuation lines (one character per line, as in NIST `NC205A.CBL`'s
  `-999.777`) normalised to `- 9  9  9  .  7  7  7` — spaced-out digits plus a
  free-standing `.` that the lexer treated as a statement terminator, silently
  truncating the enclosing `MOVE` (the AST lost the `MOVE -999.777 TO CONT-B`
  entirely, yet `result.success` stayed `True`). Words split mid-token rejoin
  correctly for the same reason; alphanumeric literals split with `-` were
  already handled via the open-quote continuation path. The fix is applied to
  both the pure-Python implementation and the Cython `_preprocess_fast`
  fast-path (the checked-in `.c` is regenerated). Because the H3 MOVE fix
  (above) had just pinned `NC205A` as strict-xfail for exactly this defect,
  that `KNOWN_ISSUES` entry is removed here — NC205A parses error-free again.
  Pinned by `tests/regression/test_continued_literal_normalization.py`, which
  exercises both code paths and the real `NC205A.CBL`.

* `EVALUATE` WHEN-branch statements are now reachable via the public tree-walk
  API. `EvaluateStatementParser` attached WHEN clauses by mutating the model
  directly (`stmt.when_clauses.append(...)` and `stmt.default_when = ...`),
  bypassing `add_when_clause` / `set_default_when` and so never registering the
  `WhenClause` nodes as AST children. Because `find_all_by_type`,
  `find_first_by_type`, and `traverse_depth_first` only descend `node.children`,
  every statement nested in a `WHEN` or `WHEN OTHER` branch was invisible to
  them (e.g. `ast.find_all_by_type("MoveStatement")` returned `0` for a MOVE
  that lived only inside an EVALUATE), even though the data was present in the
  `when_clauses` attribute and reachable via the separate `get_all_statements`
  traversal. The parser now routes both paths through the model methods so the
  clauses are real children; `get_all_statements` dedupes by `id` (visited set)
  so the now-registered children are not double-counted, and `to_dict()` output
  is unchanged (it serializes attributes, not `children`). Pinned by
  `tests/regression/test_evaluate_traversal_regression.py`.

* IO-statement conditional clause bodies are now parsed into the AST instead
  of being silently discarded. `collect_clause_stmts` (shared by READ,
  WRITE, REWRITE, DELETE, and START) previously consumed the tokens of
  `AT END` / `NOT AT END` / `INVALID KEY` / `NOT INVALID KEY` bodies and
  always returned `[]`, so an inner statement such as
  `READ F AT END CALL "EOFH" USING WS-AMT END-READ.` vanished from the AST
  entirely — `at_end_clause` was `[]` and the CALL appeared nowhere
  (breaking downstream boundary-statement detection, e.g. mockymock's
  mock-surface analysis). Clause bodies are now dispatched through the
  statement registry (the same nesting mechanism IF/PERFORM/EVALUATE use),
  attached to the owning IO node's clause lists with correct
  `SourceLocation`s, added as AST children (visible to `find_all_by_type`
  and `to_dict()`), and terminated correctly at periods, the next clause
  keyword, and `END-xxx` scope terminators. Supporting fixes:
  `WriteStatementParser` now parses `INVALID KEY` / `NOT INVALID KEY`
  (previously unsupported); `StartStatementParser` matches `KEY IS`
  comparison keywords by value (they lex as dedicated token types, not
  IDENTIFIERs) and consumes the trailing key data-name; the MOVE-target,
  DISPLAY-item, and CALL-USING collection loops stop at scope terminators
  (`END-READ` etc.) instead of capturing them as operands. Pinned by
  `tests/unit/io_statements/test_clause_bodies.py`.

* `find_copybook_file()` now reports copybook paths with their **on-disk
  basename casing**. On case-insensitive filesystems (Windows/macOS) the
  extension probe order (`.cpy` before `.CPY`) could match a file whose
  on-disk casing differs (disk: `MEM.CPY`, probe: `MEM.cpy`), and the
  probe-cased path leaked into `CopybookExpansion.included_copybooks` and
  warning messages, making reported paths platform-dependent. The found
  path's basename is now canonicalised against `os.scandir` entry names.
  The `PathResolver` directory index (tier 2) already used scandir names
  and was unaffected. Pinned by
  `tests/unit/test_path_resolver_gaps.py::TestOnDiskCasing`; the
  library-qualified COPY regression tests now compare paths exactly
  instead of via `os.path.normcase`.

* Numeric `VALUE` clause literals that lex as `LEVEL_NUMBER` are no longer
  silently dropped. The lexer types every 1-2 digit integer as
  `TokenType.LEVEL_NUMBER` regardless of context, and
  `DataDivisionParser._parse_value_clause` only accepted `NUMERIC_LITERAL` —
  so `VALUE 5` / `VALUE 42` produced `value_clause=None` and the orphaned
  token then spawned a bogus anonymous data item at that level. `VALUE IS
  <literal>` (the `IS` was never consumed) and signed literals (`VALUE -5`,
  `VALUE +2.5` — sign lexed as a separate `MINUS`/`PLUS` token) were dropped
  the same way. Level-88 condition names had the parallel bug: their value
  collector broke on `LEVEL_NUMBER`, so `88 FLAG-ON VALUE 1.` yielded
  `values == []` plus a spurious top-level item. All forms now parse
  correctly; pinned by `tests/regression/test_numeric_value_clause.py`.

* `PerformStatementParser` now recognises `THROUGH` as a synonym for `THRU` in
  `PERFORM paragraph THRU/THROUGH paragraph` ranges. Previously only the
  literal `THRU` token set `PerformStatement.thru_paragraph`; `THROUGH` fell
  through unmatched, leaving `thru_paragraph` unset and the ending paragraph
  name misparsed as a spurious extra paragraph in the AST.

* Division headers split across source lines (`DATA` at the end of one
  line, `DIVISION.` on the next — legal COBOL word separation) are now
  recognised, both at the header parser (`BaseDivisionParser.parse`) and in
  the DATA DIVISION section scanner, which previously consumed a split
  `PROCEDURE DIVISION` header as noise and silently dropped the entire
  procedure division. Found via NIST `NC113M.CBL`, which now parses
  error-free with all four divisions and 111 statements.

* IDENTIFICATION DIVISION comment-entries (AUTHOR, INSTALLATION, ...)
  containing a bare division keyword (e.g. `AUTOMATIC DATA AND
  TELECOMMUNICATION SERVICE`) are no longer mistaken for a division
  boundary: a bare keyword only ends the division when the next significant
  token is `DIVISION`. Shared helper `at_division_boundary()` in
  `parsers/divisions/base.py`. Found via NIST `OBNC1M.CBL`.

* COMPUTE now accepts the full receiver list syntax
  `COMPUTE {identifier [ROUNDED]}... = expression`, including subscripted
  receivers (`T (2, 2, 2)`). Previously only a single receiver with one
  optional ROUNDED was parsed and anything more reported "missing '='
  operator". Found via NIST `NC252A.CBL`, which now parses error-free.

* A period after a numeric literal is now treated as a decimal point only
  when followed by a digit (a COBOL numeric literal cannot end with a
  decimal point). Previously `COMPUTE A = 174 / 16.` lexed `16.` as one
  literal, so the sentence never terminated and the following statement was
  silently swallowed into the COMPUTE expression. Fixed in both the pure-
  Python lexer and the Cython fast path (`_lexer_fast.pyx`, regenerated
  `.c` checked in).

* `validate_copybook_content()` no longer flags copybooks that continue a
  string literal across lines (fixed-format `-` in column 7 re-opens the
  literal with an extra quote) as having unbalanced quotes. Found via NIST
  `K1WKA.CPY` / `K1WKY.CPY`; genuinely unbalanced quotes are still flagged.

* Library-qualified `COPY member OF library` now falls back to the plain
  copybook search path when the library has no matching subdirectory
  (previously an unhandled `CopybookNotFoundError` — NIST `SM207A.CBL`
  crashed expansion even though `ALTLB.CPY` sat in the search path). A
  `<search-dir>/<library>/` subdirectory still takes precedence when it
  exists.

* `ASTNode.find_all_by_type()` / `find_first_by_type()` now also match a
  node's concrete class name (e.g. `"MoveStatement"`, `"CallStatement"`,
  `"ExecSQLStatement"`, `"IOReadStatement"`) in addition to the `node_type`
  attribute. All statement subclasses share the generic `node_type`
  `"Statement"`, so lookups by statement class name silently returned nothing
  — which meant the `analyze` CLI subcommand always printed an empty
  `"calls"` list and `parse --find-type` could never select a specific
  statement kind (both are documented to work this way). Lookups by
  `node_type` (`"Statement"`, `"DataItem"`, `"ConditionNameItem"`, ...) are
  unchanged, and serialized output is unaffected.

* Lexer now recognises typed-literal prefixes (`X"1F"` hexadecimal, `N"..."`
  national, `NX"..."` national-hex, `G"..."` DBCS/graphic, `Z"..."`
  null-terminated, `U"..."` UTF-8, `B"..."` boolean). Previously a prefixed
  literal was split into a separate identifier token plus a string literal
  (e.g. `MOVE X"1F" TO WS` parsed `X` as its own operand), corrupting
  statement operands. Such literals now produce a single `STRING_LITERAL`
  token whose `raw_value` preserves the original prefixed source text. The
  Cython-accelerated lexer (`_lexer_fast`) was updated to match.

## [1.1.0](https://github.com/Landparty/cobol-parser/compare/v1.0.0...v1.1.0) (2026-06-19)


### Features

* add shamrice/COBOL-Examples corpus with parse verification tests ([cd0b7c4](https://github.com/Landparty/cobol-parser/commit/cd0b7c40e1e5881b2f3e634bb36fff0333d5362e))
* **ims:** add IMSEntryPoint class and integrate ENTRY 'DLITCBL' detection ([b41104c](https://github.com/Landparty/cobol-parser/commit/b41104c54b7ddddeec348f7467c483adc20b0d50))
* **lexer:** support typed-literal prefixes (X/N/NX/G/Z/U/B) ([b3d428a](https://github.com/Landparty/cobol-parser/commit/b3d428ae7844b4441357dc0c20733946bbc1a81b))
* **models:** validate PICTURE clause patterns ([6c9a414](https://github.com/Landparty/cobol-parser/commit/6c9a414aaa43c292d7e6181747fac7f49117ed53))


### Bug Fixes

* **docs:** update test count and success metrics in README and CLAUDE.md ([bfad610](https://github.com/Landparty/cobol-parser/commit/bfad61032d1d6d320cb24f7f11bb8e8bed295cdf))
* **lexer:** keep unterminated typed literals lenient in free-form ([401aa4f](https://github.com/Landparty/cobol-parser/commit/401aa4f60c2616978a3af71739a91bcd1fa4e63c))
* **logging:** include tracebacks in suppressed-exception logs; correct test docstring ([f4959c5](https://github.com/Landparty/cobol-parser/commit/f4959c569df1ed5d07df15fe8c452b8db91ef366))
* **parser:** improve real-world COBOL parse success to 99.1% on NIST-85 corpus ([7a1a387](https://github.com/Landparty/cobol-parser/commit/7a1a3876e2e2fb87648f59a2b8aa8b3710b93e2a))


### Documentation

* add design spec for shamrice COBOL examples corpus ([98bb00b](https://github.com/Landparty/cobol-parser/commit/98bb00bbbd4659f914e866905290ef542c785489))

## 1.0.0 (2026-06-16)


### Features

* add --profile, --profile-top-n, --profile-output CLI flags ([13a3f1f](https://github.com/Landparty/cobol-parser/commit/13a3f1f1b9b0690105eaed738601d9730abd76fa))
* add --profile/--profile-top-n/--profile-output CLI flags to cobol-parser ([5f2468c](https://github.com/Landparty/cobol-parser/commit/5f2468c61fc1fd61f2099fe550aff4646c02181c))
* add advanced configuration options for ignored memory patterns and language server settings ([4808304](https://github.com/Landparty/cobol-parser/commit/4808304ddf6262dc7797c45410d4ca194492891b))
* add batch.py with BatchResult, _parse_one worker, and parse_files() ([6680e5d](https://github.com/Landparty/cobol-parser/commit/6680e5d829c6344f418a28feb044a470d4231467))
* Add comprehensive COBOL CALL statement parsing, samples, and validation utilities. ([9c4d75f](https://github.com/Landparty/cobol-parser/commit/9c4d75f6b6b5f5689de5aa501ff7558640eb5006))
* Add comprehensive COBOL examples demonstrating CALL statements and exception handling ([52e5f14](https://github.com/Landparty/cobol-parser/commit/52e5f1447077d3facce33e9c9848c8f04fda5220))
* Add comprehensive test cases and samples for COBOL CALL and ENTRY statement parsing. ([c07e94b](https://github.com/Landparty/cobol-parser/commit/c07e94bb22bd6314ccdb573f724b05682bcd2a74))
* add convergence node tracking for branch decisions in program flow analysis ([b7e0787](https://github.com/Landparty/cobol-parser/commit/b7e07871882ff2ee3b68cfcdba3228958c99e191))
* add CRUDMatrixGenerator for mainframe modernization analysis ([79f2a28](https://github.com/Landparty/cobol-parser/commit/79f2a282cc7794eb7f9589fd037c92ac8f997707))
* Add examples for COBOL parser testing and demonstration ([8df3f9f](https://github.com/Landparty/cobol-parser/commit/8df3f9ffeb8a36657b531964508e628e6ce23a12))
* add IO statement parsers for OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START ([63ae8c2](https://github.com/Landparty/cobol-parser/commit/63ae8c2d44963f154362bb81642040606368364c))
* Add macOS compatibility verification script and update README ([18e724c](https://github.com/Landparty/cobol-parser/commit/18e724c3dfea79327bc6ef83c948c2fd06f828f6))
* add profiling module with ProfilerContext, ProfilingResult, FunctionProfile ([01ab5d2](https://github.com/Landparty/cobol-parser/commit/01ab5d299046c7ba1d6d1c60d230721936912279))
* add profiling overloads to CobolParser.parse() ([27a0dd8](https://github.com/Landparty/cobol-parser/commit/27a0dd8e02a6180328308932cafe07c39e2f7044))
* add profiling overloads to parse_cobol() ([1e17ef0](https://github.com/Landparty/cobol-parser/commit/1e17ef0e029fc9cafbbb6bf9abf68cbf9a5fa6ce))
* add profiling support to batch parsing functions ([1ac0f4f](https://github.com/Landparty/cobol-parser/commit/1ac0f4f08fe78382fcae884cb9c3f338ad35f055))
* add profiling support to BatchResult and parse_files() ([b3332e0](https://github.com/Landparty/cobol-parser/commit/b3332e0902f9fda206bedf5f41e968b19034ab07))
* add psutil optional dependency for profiling extra ([33774c2](https://github.com/Landparty/cobol-parser/commit/33774c20342200403eeea1ea8fedf513ebace362))
* complete ProgramFlowAnalyzer with cycle detection, unreachable nodes, and missing statement coverage ([5ac379e](https://github.com/Landparty/cobol-parser/commit/5ac379ea97766255e4a743b1f7b1b0480c4874d0))
* **docs:** Revise documentation structure and add cookbook for practical usage examples ([f0b6e1c](https://github.com/Landparty/cobol-parser/commit/f0b6e1c2db0f9fb3c3e31a3accb03a050666b9f3))
* Enhance COBOL parser to support nested PERFORM and IF statements with inline handling ([b7cf7ef](https://github.com/Landparty/cobol-parser/commit/b7cf7ef20badf742816403248f204856df0dc1c1))
* enhance COBOL parser with batch processing optimizations and reusable components ([851b348](https://github.com/Landparty/cobol-parser/commit/851b348e44e414f7d772ca9c4dfec668d3ec10f0))
* Enhance COBOL parser with fixed-format auto-detection and multi-line string support ([48375e6](https://github.com/Landparty/cobol-parser/commit/48375e6f093e21eb1bb6c0b1436e37cd13854888))
* Enhance COPY statement parser with comment and string literal handling ([6c5a97b](https://github.com/Landparty/cobol-parser/commit/6c5a97b46cc1032112bd3b29ea8c5cfc839c8900))
* Enhance dynamic CALL statement support in COBOL parser ([744d0ca](https://github.com/Landparty/cobol-parser/commit/744d0ca0ba049ca8f63c00cf8515869599164f4d))
* **evaluate-coverage:** Add specification and quality checklist for COBOL Fixed-Format EVALUATE coverage ([74f480f](https://github.com/Landparty/cobol-parser/commit/74f480f29325d44e90ca07045290f83ed3f3aeac))
* export parse_files and BatchResult from cobolparser package ([1a3a9e6](https://github.com/Landparty/cobol-parser/commit/1a3a9e61cc4d0c6d15d804c72ab04209f04fab1a))
* export ProfilingResult and FunctionProfile from cobolparser public API ([b0803c3](https://github.com/Landparty/cobol-parser/commit/b0803c3ce9739367c7c10babdd767dac010e1080))
* Implement copybook preprocessing, expand documentation with new guides, and archive historical reports and metrics. ([3790f39](https://github.com/Landparty/cobol-parser/commit/3790f3991e5b89b17375a8b2e9502a6bae319597))
* implemented parser to return IMS, CICS and DB2 instructions ([11771af](https://github.com/Landparty/cobol-parser/commit/11771af1e8cfefb3b4573b5aa0bc6d077bc33223))
* **io-statements:** Implement comprehensive support for IO statements ([39b1881](https://github.com/Landparty/cobol-parser/commit/39b1881c0d77d185c21352328c2fb3510f2edab2))
* **lexer:** Add support for figurative constants in VALUE clause parsing ([d7526e5](https://github.com/Landparty/cobol-parser/commit/d7526e592d382daeb18d872b3574b7345f57f1da))
* optimize statement retrieval in CobolProgram with caching mechanism ([6257308](https://github.com/Landparty/cobol-parser/commit/625730870b49f817d1ce79ffd69ee0e37d9d4b23))
* **parser:** Implement inline parsing for EVALUATE statement with diagnostics ([aef8eda](https://github.com/Landparty/cobol-parser/commit/aef8edabdb5254519154cc6ab3ccca285f598c63))
* **parser:** surface statement errors and honor ErrorRecoveryMode ([aa87b88](https://github.com/Landparty/cobol-parser/commit/aa87b8827590b97179534926a36d71b81a9c1c09))
* **program-flow:** model THRU ranges and classify circular dependencies ([da89832](https://github.com/Landparty/cobol-parser/commit/da8983225c237e9c8173662f774bf5c2787ce8e2))
* **program-flow:** model THRU ranges and classify cycles ([e166594](https://github.com/Landparty/cobol-parser/commit/e1665947b4e9dd12c62b4c0e4ee34320f62fdffc))
* **T015-T021:** Complete Phase 2 test suites and contracts ([c1aea81](https://github.com/Landparty/cobol-parser/commit/c1aea81c06bf06100a51d05a38d3ebbe76afa409))
* update project dependencies and enhance CLAUDE.md documentation ([2a5d200](https://github.com/Landparty/cobol-parser/commit/2a5d20019213c0784e1adb748450371bd04d56ba))


### Bug Fixes

* address review feedback on parser/lexer optimizations ([fc781c2](https://github.com/Landparty/cobol-parser/commit/fc781c2614705138cfc8f91093950bb2857ee0ef))
* apply review feedback on T3 profiling overloads ([911834d](https://github.com/Landparty/cobol-parser/commit/911834da87b848194d7498f89230384d90068884))
* catch parse_cobol exceptions in worker to prevent batch abort ([f7d8fde](https://github.com/Landparty/cobol-parser/commit/f7d8fde28afe0d59ee62acd3cd4a5bbba7d9572e))
* clean up profiling module per code review ([9eec0ce](https://github.com/Landparty/cobol-parser/commit/9eec0ce5b428fd32472890ab33d13a5353893d72))
* **copy_statement_parser:** handle \r and \r\n line endings in source_location ([b6f4822](https://github.com/Landparty/cobol-parser/commit/b6f48225c40ff087e909efaf3ca5a5c500f7280d))
* **data:** drop dead branches in _parse_data_item fallback ([e641b7c](https://github.com/Landparty/cobol-parser/commit/e641b7cd686af285604ffe2e2a1ac59aa7dd51e6))
* **data:** mirror SIGN/SYNC/JUSTIFIED/BLANK/POINTER clauses in Cython fast path ([4acb0b1](https://github.com/Landparty/cobol-parser/commit/4acb0b1433a837a40e179a69b5271522cce061e4))
* **lexer,preprocess:** scientific notation crash, configurable cache, encoding warnings ([740d725](https://github.com/Landparty/cobol-parser/commit/740d72510a109dc87cd70936219d896cd6337dbb))
* **parser,preprocess:** address Copilot review on PR [#49](https://github.com/Landparty/cobol-parser/issues/49) ([a69033e](https://github.com/Landparty/cobol-parser/commit/a69033e0ce994d94b326a365093a1820990c1dec))
* remove over-broad parse exception catch; parity test uses workers=2 for pickle coverage ([a54b31d](https://github.com/Landparty/cobol-parser/commit/a54b31d89a0531ae28214be06825420759186919))
* remove unused pytest imports flagged by ruff ([9d9c0ac](https://github.com/Landparty/cobol-parser/commit/9d9c0acf5d4c1e5f2c1b40f2f0eb3026bb0b8cd4))
* resolve 6 critical parser edge cases causing silent data loss or crashes ([88f97c6](https://github.com/Landparty/cobol-parser/commit/88f97c6113bf088e472335ca7c611dd84de55a0f))
* **setup:** drop unused zip(), satisfy ruff B905 ([2964649](https://github.com/Landparty/cobol-parser/commit/2964649fae357ce3138dfeeb4bfa5b7a6aee62dd))


### Performance Improvements

* always build Cython extensions; tighten TokenStream ([0b33ae9](https://github.com/Landparty/cobol-parser/commit/0b33ae91026807d2cd4b35b74b33fda93e6d7ae3))
* **build,parser:** always build Cython extensions; tighten TokenStream ([1739e40](https://github.com/Landparty/cobol-parser/commit/1739e409f318f1aa7f4db8fc33ce37bd58d3f04c))
* **copy_statement_parser:** pre-build newline index for O(log n) line lookups ([26c1dd3](https://github.com/Landparty/cobol-parser/commit/26c1dd33f306c199ca61f023976fec2252293b85))
* **data:** Cythonize _parse_picture_clause and _parse_data_item loops ([430e1bb](https://github.com/Landparty/cobol-parser/commit/430e1bb2e08001b1d0162fc9a654c5aeb27d479e))
* **data:** hoist _parse_section literals; cache token attrs per iteration ([c263a8c](https://github.com/Landparty/cobol-parser/commit/c263a8c15465d48782e519960645e03db6a97233))
* **data:** use shared _DIVISION_TOKEN_TYPES set; drop hasattr/list-literal cruft ([21125fa](https://github.com/Landparty/cobol-parser/commit/21125fa788652b0cd233c8020a6f1d1aa2e4c497))
* **lexer,data:** Token __slots__; hoist allocations out of data-item loop ([a933512](https://github.com/Landparty/cobol-parser/commit/a933512593d556578c413d4a7500931d971b0135))
* **lexer,models,arith:** IntEnum TokenType; PIC first-char dispatch; COMPUTE inner loop ([773cd02](https://github.com/Landparty/cobol-parser/commit/773cd02d9c952af54edc872c0d26ca51b78bb220))
* **lexer,registry:** cythonize read_number_from_text; share registry across parses ([f0400d3](https://github.com/Landparty/cobol-parser/commit/f0400d3a402dfbe16e86774b646693833999ce32))
* **lexer:** Cythonize _try_single_line_string ([a99f2e2](https://github.com/Landparty/cobol-parser/commit/a99f2e2cb32524192c22a991dc0eb6eeef184ff9))
* **lexer:** Cythonize the outer tokenize() per-line loop ([6cc4128](https://github.com/Landparty/cobol-parser/commit/6cc41282ecbd467b385deb9670de90006e8f9191))
* **move_parser:** hoist stop_token_types and keywords to module-level frozensets ([616eced](https://github.com/Landparty/cobol-parser/commit/616ecedd9e8ea295d78d04dbeb67415cb1b2da47))


### Documentation

* Add comprehensive project completion summary ([ad3471b](https://github.com/Landparty/cobol-parser/commit/ad3471b2e32b1234b81e5ab98c8f4681cc0c1ede))
* add documentation audit design spec (2026-03-30) ([2e3d39a](https://github.com/Landparty/cobol-parser/commit/2e3d39a41ec071f1119e912dcd1debc84677d77a))
* add documentation audit implementation plan (2026-03-30) ([22ce72f](https://github.com/Landparty/cobol-parser/commit/22ce72f22336bd7517ede3248880eae654f8be98))
* Add final status report - project complete and production-ready ([6e028e6](https://github.com/Landparty/cobol-parser/commit/6e028e6a52628d663a1f642506175d37dff7d0ba))
* add framework baseline analysis and fill in plan.md with technical context ([65d576d](https://github.com/Landparty/cobol-parser/commit/65d576d2a7565941258a13ea0b8a95bedc2261e9))
* add full project audit report (2026-03-29) ([69f8d0d](https://github.com/Landparty/cobol-parser/commit/69f8d0d8507b9220f1a86a8ac959898691aadd7c))
* add performance profiling design spec ([b4ba714](https://github.com/Landparty/cobol-parser/commit/b4ba714c654a01953febf69d22abd14941c78a5d))
* add performance profiling implementation plan ([f084773](https://github.com/Landparty/cobol-parser/commit/f0847735f7542e66ae84d5d00a9a0c2634db7176))
* **changelog:** note Cython data-clause drop fix ([8021401](https://github.com/Landparty/cobol-parser/commit/8021401a23188b20a07acc71493f0f64360d0987))
* **claude:** refresh CLAUDE.md to match current code state ([b7c6036](https://github.com/Landparty/cobol-parser/commit/b7c6036278d7925c819a3ce789120db253984649))
* **claude:** refresh CLAUDE.md to match current code state ([931e692](https://github.com/Landparty/cobol-parser/commit/931e69234448db1bb5ce4bbdba5b7a0a634072fe))
* correct license references from MIT to proprietary EULA ([ea2254f](https://github.com/Landparty/cobol-parser/commit/ea2254fe0ab081786d6cf6e7bcada093588a32c0))
* document all analysis features and update CLI reference ([62e3475](https://github.com/Landparty/cobol-parser/commit/62e3475ff55355c34056a1ba00a705a606797569))
* fix BatchResult example — use r.path and guard r.result nullable ([4ee44ae](https://github.com/Landparty/cobol-parser/commit/4ee44ae63297fec76a153b6a4aa43c23cc86b356))
* fix duplicate section, stale file path, and vague BC-4-6 entries ([5f36c09](https://github.com/Landparty/cobol-parser/commit/5f36c09ed761a8f4075e416134965878a4a356a4))
* fix SQL example metadata fields and DECLARE CURSOR sql_type value ([a4520ee](https://github.com/Landparty/cobol-parser/commit/a4520ee2d17bd4b56309cc9a3eb7893982df9559))
* fix stale API reference in data-items.md ([cc4ae82](https://github.com/Landparty/cobol-parser/commit/cc4ae825a645ac223e7bcca8dd5b5b584645c822))
* refresh CLAUDE.md counts (tests, files, TokenTypes, analyzers) ([44af908](https://github.com/Landparty/cobol-parser/commit/44af9083e02e3589d54b0ae25b515f46d811a828))
* **T026-T027:** Add success criteria validation and mark Phase 3 complete ([1a53991](https://github.com/Landparty/cobol-parser/commit/1a53991d01b2349ed5c2218db3c2d033b10e935a))
* update CLAUDE.md to reflect current codebase ([de6c392](https://github.com/Landparty/cobol-parser/commit/de6c39290d8d5d0fb00844cd87fc4411d49afef2))
* update CLAUDE.md to reflect current codebase state ([d2873cf](https://github.com/Landparty/cobol-parser/commit/d2873cf34dc2f451fe9ab056e436bc6848cf6e9c))
* update docs hub — fix metrics, remove dead links, add batch parsing ([363c36a](https://github.com/Landparty/cobol-parser/commit/363c36a9bb11714f83e23440ebb9f6bf153df1c8))
* update documentation and examples for COBOL parser features and fixes ([344ce35](https://github.com/Landparty/cobol-parser/commit/344ce3578d12fbcfe3fc6d62652fc8063809da6e))
* update README badges/counts and add CHANGELOG entries for v1.3.0 and v2.0.0 ([1b403e3](https://github.com/Landparty/cobol-parser/commit/1b403e35cbdecdb526a010c68b8e40a05a60049c))
* update README with correct Python version, test count, and all features ([aad07d4](https://github.com/Landparty/cobol-parser/commit/aad07d42837212480b479665bdc2258259fe7cb0))
* update statement guides — fix AST field names and removed API references ([4994a4e](https://github.com/Landparty/cobol-parser/commit/4994a4eaac7ec15ee27a673f403d93fcedb22a25))
* Update tasks.md - mark all 27 tasks complete + add implementation status report ([bc8a7b3](https://github.com/Landparty/cobol-parser/commit/bc8a7b398779cb8e21fa1e16ff2e190c02831a02))

## [Unreleased]

### Added

- **DATA DIVISION completeness**:
  - `EXTERNAL` and `GLOBAL` data-item clauses are now recorded on
    `CobolDataItem` (`is_external` / `is_global`, serialized in `to_dict()`)
    instead of being silently consumed
  - FD/SD file-description clauses are captured rather than discarded: the
    file's `01` record carries an `fd_clauses` metadata mapping with
    `block_contains`, `record` (fixed and `RECORD VARYING ... DEPENDING ON`),
    `recording_mode`, `label_records`, `code_set`, `data_records`, `linage`,
    and `value_of`
  - Edited `PICTURE` clauses are extracted and classified correctly, including
    embedded decimal points and currency / sign / check-protect / stroke
    insertion symbols (`$$$,$$9.99`, `ZZ,ZZ9.99-`, `**,**9.99`, `XXX/XXX`);
    `PictureClause` now exposes `is_numeric_edited` / `is_alphanumeric_edited`
    and computes the displayed character size

### Fixed

- The Cython-accelerated data-item clause loop (`_data_fast`) had drifted out
  of sync with the pure-Python parser and silently dropped the `SIGN`,
  `SYNCHRONIZED`, `JUSTIFIED`, `BLANK WHEN ZERO`, and bare-`POINTER` clauses in
  compiled builds. The fast loop now hands those clauses back to the
  pure-Python path, which is the single source of truth, so the two
  implementations can no longer diverge. Picture extraction is likewise
  centralized in the Python `_parse_picture_clause`.

- **Analysis toolkit**: comprehensive static and dynamic analyzers exposed via `cobolparser.analysis` and the top-level package:
  - `DeadCodeAnalyzer` — unreferenced paragraphs and sections
  - `ProgramFlowAnalyzer` — control-flow graph with typed PERFORM / GO TO / CALL / fall-through edges (also wired to the `cobol-parser program-flow` CLI). PERFORM/SORT/MERGE `... THRU ...` edges now carry `thru_target` and the ordered `range_members` of every paragraph the range spans, and detected cycles are classified in `cycle_details` by kind (`PERFORM_RECURSION` / `GOTO_LOOP` / `FALL_THROUGH` / `MIXED`) so genuine recursive dependencies are distinguishable from sequential-fall-through artifacts
  - `IOLogger` — structured report of every CALL / SQL / FILE-IO / CONSOLE-IO / ENTRY operation with direction (INPUT / OUTPUT / BIDIRECTIONAL)
  - `IOSequenceAnalyzer` — detects READ/WRITE/REWRITE/DELETE/START before OPEN, double open/close, files left open at program exit
  - `MoveTypeChecker` — flags category-incompatible MOVE statements (numeric ↔ alphabetic, etc.)
  - `LinkageChecker` — cross-references CALL arguments with ENTRY declarations and LINKAGE SECTION 01-items
  - `LanguageEnvironmentAnalyzer` — IBM LE intrinsic functions and service calls
  - `CRUDMatrixGenerator` — program × file/table Create/Read/Update/Delete matrix with CSV and JSON export
  - `IMSSegmentAnalyzer` — resolves IMS DLI segment names for CBLTDLI / AIBTDLI / CEETDLI calls (all 16 DLI function codes)
  - `HostVariableResolver` — resolves `:host-var` references in EXEC SQL to DATA DIVISION data items and DCLGEN DECLARE TABLE columns
- **CobolCheck test generation**: `cobol-parser generate-tests` CLI and `generate_cobolcheck_tests()` Python API, powered by `CoverageAnalyzer` + `TestPlanGenerator` + `CobolCheckGenerator`; supports `paragraph`, `branch`, and `boundary` strategies across 18 branch types
- CLI subcommands grew from 7 to 9 (`program-flow`, `generate-tests`)
- `docs/analysis.md` — comprehensive reference for every analyzer
- Test suite expanded to 3,456 tests across `unit/`, `integration/`, `contract/`, `regression/`, `performance/`

### Fixed

- **DATA DIVISION clause drop in the Cython fast path**: the compiled
  `_data_fast.parse_data_item_clauses_fast` hot path did not handle the
  `SIGN`, `SYNCHRONIZED`/`SYNC`, `JUSTIFIED`/`JUST`, `BLANK WHEN ZERO`, and
  `POINTER` clauses (added to the pure-Python parser later), so when the
  extension was compiled those clauses were silently dropped (e.g.
  `blank_when_zero` stayed `False`). The fast path now mirrors the
  pure-Python branches exactly.

## [1.0.0] - 2026-03-31

### Added

- COBOL parser for Python 3.13+ with full two-stage pipeline: preprocessing → lexing → parsing → AST
- IBM Enterprise COBOL dialect support: COMP-3, EXEC SQL, EXEC CICS, 75+ verbs, IBM intrinsic functions
- Fixed-format and free-form COBOL support with auto-detection; automatic column normalization and comment stripping
- Multi-line string continuation handling with doubled-quote escape sequences
- Statement parsers: CALL, PERFORM, MOVE, DISPLAY, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE, IF, EVALUATE, OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, COPY, and more
- Embedded SQL/CICS/IMS statement parsing (EXEC blocks)
- FD/SD file description and FILE-CONTROL SELECT parsing (including multi-line ASSIGN, ORGANIZATION, ACCESS clauses)
- Copybook expansion via `expand_copybooks()`
- JSON serialization of all AST nodes with optional source location and metadata
- Error recovery modes: `FAIL_FAST` (default) and `COLLECT_ALL`
- Configurable memory management: 64MB–8GB limits, chunk-based streaming for large files
- `parse_files(paths)` for parallel multi-file batch parsing using multiprocessing
- `ParseResult` with AST, errors, warnings, and `ParseStatistics` (timings, counts, peak memory)
- Plugin architecture (`cobolparser/plugins/core.py`) for memory config, dialect, and serialization config
- `ASTNodeFactory` for validated, consistent AST node construction
- `StatementParserRegistry` for dynamic statement parser dispatch
- `DynamicCallAnalyzer` — tracks possible values of variables used in dynamic `CALL` statements
- IO coverage reporter and CLI (`python -m cobolparser.cli.coverage`)
- 2,975 unit, integration, and contract tests; 81%+ line coverage enforced

### Design

- All AST nodes extend `ASTNode` with mandatory `to_dict()` for JSON serialization
- `TokenStream` wraps `List[Token]` with `peek()`, `consume()`, `expect()`
- Division parsers (`IdentificationDivisionParser`, `DataDivisionParser`, `ProcedureDivisionParser`, etc.) are each independently testable
- Statement parsers live in `cobolparser/parsers/statements/`, one file per verb or verb group
- Proprietary license — copyright © 2026 Samuel Dion, all rights reserved
