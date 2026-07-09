# cobolparser — Open Findings (as of 2026-07-08)

**Status update (2026-07-09):** all 9 HIGH findings (H1-H9) and 10 of the
17 MEDIUM findings (M1, M2, M3 partial, M4, M5, M7 partial, M8, M9, M14,
M16) are now fixed and pinned by regression tests — see the per-severity
banners below (`## HIGH`, `## MEDIUM`) and `CHANGELOG.md` (Unreleased →
Fixed) for the full writeup. Still open: M6, M10, M11, M12, M13, M15
(each close to its own subsystem rewrite, deferred to separate plans),
M17 (test-coverage debt, not a bug), and all LOW findings.

This file supersedes `audit-2026-07-06.md`, `-07.md`, `-08.md`, `-09.md`, and
`cobol-parser-example-parse-gaps.md`. Those four audits (plus the mockymock
corpus-sweep report) produced ~70 findings; the large majority — every
CRITICAL and most HIGH items (multi-program units, unknown-verb warnings,
EVALUATE/CALL-handler traversal, GO TO DEPENDING, SELECT clause drops, WRITE
ADVANCING, OCCURS KEY clauses, REWRITE/START/STOP operands, line-number
drift, CLI/batch exit codes and fault isolation, and the whole 2026-07-08/09
statement-boundary "swallow" class) — are now fixed and pinned by regression
tests. See `CHANGELOG.md` (Unreleased section) for the full fix history.

Every item below was re-verified empirically against current `main`
(commit `b54348e`) by five independent read-only passes on 2026-07-08 —
each with a runtime repro or an exact file:line citation, not carried
forward from the old reports on faith. Two old findings did **not**
survive re-verification and are dropped entirely: **EVALUATE `ALSO`
pairing** (subjects/selectors are positionally aligned; the old finding
was simply wrong) and **`ACCEPT ... FROM STATUS/NAME`** (now captured,
incidentally, by the generic FROM-phrase fix that landed for `FROM DATE
YYYYMMDD`).

A recurring pattern below: several items were "silent" in the original
audits and have since been converted to an explicit `ParseResult.warnings`
entry *without the underlying functionality gap being closed*. These are
marked **(now warns, not fixed)** — they're real, they're just no longer
undetectable by a caller that checks `warnings`, only by one that checks
`errors`/`success` alone.

---

## HIGH

**H1-H9 are all fixed** (H1-H8 on 2026-07-09; H9, discovered during H7
verification, in a 2026-07-09 follow-up pass) and are pinned by
`tests/regression/test_open_findings_high_regressions.py` — see
`CHANGELOG.md` (Unreleased → Fixed) for the full per-finding writeup.
Left in place (rather than deleted) for traceability, per this file's own
convention for prior audits.

### H1 — `SET ADDRESS OF x TO y` produces an empty `SetStatement`
`cobolparser/parsers/statements/set_parser.py:60-68`. The target-collection
loop only accepts `TokenType.IDENTIFIER`/`STRING_LITERAL`; `OF` lexes as its
own dedicated `TokenType.OF` (not `IDENTIFIER`), so the loop's `else: break`
fires immediately on `OF` and never reaches `WS-PTR`/`TO`/`WS-TARGET`.
`SET ADDRESS OF WS-PTR TO WS-TARGET.` → `targets: [], set_type: null,
value: null`, warning `"Unparsed tokens starting at 'OF' ..."`.
(Correction to `reports/audit-2026-07-09.md`: that report blamed the
*lexer* greedily matching `ADD` inside `ADDRESS` — that specific token
truncation does not reproduce through the real `parse_cobol()` pipeline;
it only appears if `CobolLexer` is instantiated directly with
`free_form=False`, bypassing preprocessing. The real, current bug is the
`set_parser.py` `OF` type check.)

### H2 — `COMPUTE` with unbalanced parentheses is silently accepted, and can swallow the next statement
`cobolparser/parsers/statements/arithmetic_parsers.py:479-514`. `paren_depth`
is tracked only to gate the statement-boundary check (which only fires at
`paren_depth == 0`); there is no final `if paren_depth != 0: report_or_raise(...)`.
`COMPUTE X = ((A + B)` → `errors=0, warnings=0`, and because `paren_depth`
never returns to 0, the boundary guard never re-arms: a following
`DISPLAY 'DONE'.` gets folded into the expression string
(`expression: '( ( A + B ) \n DISPLAY DONE .'`) — this is worse than the
original audit described (silent acceptance *plus* a boundary-guard bypass
that swallows a real, well-formed following statement).

### H3 — `PERFORM para-name JUNK-TOKEN.` silently drops the trailing identifier
`cobolparser/parsers/statements/perform_parser.py:181-204`. After the target
paragraph, a following `IDENTIFIER` is speculatively consumed as a candidate
TIMES value; if `TIMES`/`TIME` doesn't follow, it's discarded with no
`set_times_clause()` call and — unlike almost every other finding in this
document — **no warning at all**: `errors=[], warnings=[]`,
`PerformStatement.times_count: null`. The trailing period is then consumed
normally, so the top-level "unparsed tokens" recovery path never triggers
either. Fully silent, `errors==0 && warnings==0`.

### H4 — `perform_parser.py` bare `except ParseError: pass` at 5 sites discards diagnostics with zero trace
Lines **253, 355, 475, 496, 594**. Unlike the `_utils.py` nested-parse helper
(see M9), these catch blocks have **no logging at all**, not even DEBUG.
Confirmed via targeted repro (monkeypatched nested-parse to raise inside
`_parse_inline_statements`): the exception is swallowed at line 594-595,
the method returns normally, `inline_statements == []`, and there is no
record anywhere — no `ParseResult.errors`, no `.warnings`, no log line.
VARYING/UNTIL body parse failures can vanish completely untraceable.

### H5 — `MoveTypeChecker` silently skips every unresolvable MOVE, with no count
`cobolparser/analysis/move_type_checker.py:293-305`: `UNKNOWN`/`FIGURATIVE`
source category → `return`; `UNKNOWN` target category → `continue`. No
counter, no field on `MoveTypeReport` for "skipped/unresolved" (only
`violations`/`errors`/`warnings`). Repro: 3 MOVEs on undeclared identifiers
(simulating an unexpanded copybook) → `violations: [], error_count: 0,
warning_count: 0` — a false all-clear.

### H6 — Path-traversal validation gap in the Tier-2 copybook resolver fast path (security)
`cobolparser/preprocess/path_resolver.py:361-394`. `PathResolver.resolve()`'s
directory-index fast path returns `self._dir_index[lookup_key]` after only
an `os.path.getsize()` check — it never calls `validate_path_within_directory()`
(which the Tier-3 resolver does call, at line 255, and which itself resolves
symlinks via `Path.resolve()`). The directory index is built via
`os.scandir()` + `entry.is_file()`, which follows symlinks, so a symlink
inside a copybook search directory pointing outside the search root would be
served with no containment check. Could not construct a live Windows symlink
in this environment (requires elevated privilege), so this is code-confirmed
rather than exploit-confirmed; the code path literally never references
`validate_path_within_directory`. Separately, the `".." in file_path` guard
(`path_resolver.py:62`) is still naive substring matching (a filename like
`weird..name.cpy` triggers `PathTraversalError` despite not being a
traversal attempt — confirmed false positive). **No test exercises the
Tier-2 containment gap** (`tests/unit/test_path_resolver_gaps.py` only
covers size limits/casing; rejection-path tests in
`tests/unit/test_path_resolver_coverage.py` only exercise the Tier-3/
`validate()` path).

### H7 — Silent acceptance of malformed input: unbalanced/unterminated constructs
`reports/audit-2026-07-06.md` H3, residual after the MOVE-specific sub-cases
were fixed. Still `errors=0, warnings=0`:
- Unclosed `IF`s with no bodies (any count) — accepted.
- Unterminated string literal in the default parse path: `lexer.py:1121`'s
  error is gated on `if not self.free_form`, and `parse_cobol()` always
  lexes with `free_form=True` after normalization (`parser.py:204`) — so
  `DISPLAY "UNCLOSED` followed by a well-formed statement on the next line
  parses clean, the literal silently closed at the line boundary.
  (A *different*, unconditional check at `preprocess/__init__.py:546-550`
  does fire if the unterminated literal runs to true EOF — that specific
  sub-case is not silent.)

### H8 — `CLOSE` keeps only one per-file option
`cobolparser/parsers/statements/close_parser.py:61-122` uses an if/elif
chain across `REEL`/`UNIT`/`WITH` (one branch per file, not a loop), and the
outer per-file loop requires the next token to be a plain `IDENTIFIER` to
continue — so once one option is consumed, a following non-`IDENTIFIER`
clause token (e.g. `WITH`) ends the whole loop. `CLOSE F REEL WITH NO
REWIND.` → `close_options: {"F": {"reel": true, "no_rewind": false, ...}}`,
`no_rewind` lost, only warn-masked (`"Unparsed tokens starting at 'WITH'..."`).

### H9 — A statement with no terminating period absorbs the following paragraph header instead of starting a new paragraph — FIXED 2026-07-09
Discovered 2026-07-09 while verifying H7's "unclosed IF" sub-claim (which
itself turned out **not** to be a bug — period-terminated or
nesting-closed IFs with no body are legal COBOL and were re-verified as
parsing correctly). This was a distinct, more general root cause: any
statement lacking a terminating period, immediately followed by what
should be a new paragraph header, caused the parser to read the paragraph
name as a trailing operand of the preceding statement instead of
recognizing a paragraph boundary. Reproduced with a bare `DISPLAY "X"`
(no period) immediately followed by `NEXT-PARA.` and its own statement —
not IF-specific; also confirmed (by direct repro) in `MOVE`'s target
list, `COMPUTE`'s expression capture, `STRING`'s operand list,
`UNSTRING`'s `INTO` target list, and `INSPECT`'s `TALLYING`
counter-name loop and outer "consume to period" trailer (the latter is
what actually ate the paragraph name for `INSPECT ... REPLACING`, since
the `REPLACING` clause loop itself already stopped safely on an
unrecognized token — it just left it for the trailer to mishandle).

Fixed via a new `looks_like_paragraph_boundary()` helper
(`cobolparser/parsers/statements/_utils.py`) that mirrors COBOL's own
disambiguator instead of guessing from grammar shape alone (the raw
grammar can't tell "last operand of an unterminated statement" from "next
paragraph name" — both are just `IDENTIFIER` then `PERIOD`): the
candidate identifier only counts as a paragraph boundary when it (a)
starts its own source line, (b) is immediately followed by a period or
`SECTION`, and (c) is not a name declared in the DATA DIVISION — condition
(c) is what keeps a genuinely wrapped continuation-line operand (e.g.
`DISPLAY\n    WS-X.`) from being misread just because it opens its line.
The DATA DIVISION cross-check is threaded through
`ParseContext.known_data_names`, computed once per PROCEDURE DIVISION
parse. Recovery now warns instead of silently re-interpreting, matching
the H7/H8 precedent. Applied to the six statement parsers confirmed by
direct repro: `DISPLAY`, `MOVE`, `COMPUTE`, `STRING`, `UNSTRING` (its
`INTO` target list), and `INSPECT` (its `TALLYING` counter-name loop and
its outer "consume to period" trailer). Pinned by
`tests/regression/test_open_findings_high_regressions.py::TestH9MissingPeriodParagraphBoundary`
(9 tests: one repro per fixed statement/clause shape, plus two guard
cases for the DATA DIVISION cross-check).

**Known residual gap, by design:** an undeclared identifier (e.g. from an
unexpanded COPY member) that is *also* alone on its own continuation line
is inherently ambiguous — no purely syntactic check can tell "wrapped
operand referencing a name this parser can't see" from "a real paragraph
name" — and is treated as a paragraph boundary (with a warning), which
may be wrong for that case. This is the same class of ambiguity `parse_cobol()`
already carries whenever copybooks aren't expanded; callers needing full
resolution should use `parse_cobol_with_expansion()`.

**Not covered by this fix:** every operand-collection loop with a
directly-reproduced instance of this bug (probed: DISPLAY, MOVE, COMPUTE,
SET, ADD/SUBTRACT/MULTIPLY/DIVIDE, IF, STRING, UNSTRING, INSPECT
TALLYING/REPLACING) was fixed or found already safe. `SET`, the
arithmetic parsers' fixed-arity target/GIVING slots, and `IF` do not have
this bug in the shapes tested (bounded grammar, not an open list). Not
probed at all: parsers not touched by this pass (e.g. `SORT`/`MERGE`'s
key lists, `CALL`'s `USING` parameter list, `INITIALIZE`'s target list) —
any of those could still share the underlying gap; fixing them needs its
own repro-first pass rather than a blanket rewrite of every
operand-collection loop in the parser.

---

## MEDIUM

**M1, M2, M3, M4, M5, M7, M8, M9, M14, and M16 are fixed** (2026-07-09
batch) and are pinned by
`tests/regression/test_open_findings_medium_regressions.py` — see
`CHANGELOG.md` (Unreleased → Fixed) for the full per-finding writeup.
Left in place (rather than deleted) for traceability, per this file's own
convention for prior audits. M3's fix covers `AT` positioning (both the
corpus-dominant bare combined-numeric form and the `AT LINE`/`COLUMN`
keyword form) plus `SECURE`/`NO-ECHO`/`TIMEOUT`/`AUTO-SKIP`/`UPPER` on
`ACCEPT`; `CURSOR`, `BEEP`/`BELL`, `COLOR`, `UPDATE`, and `WITH BLANK
SCREEN` were not implemented (zero-to-one corpus hits in
`examples/cobol/shamrice/`, and — for `COLOR` especially — the real
grammar is a two-part clause this finding's text didn't specify with
enough confidence to implement correctly) and remain open, tracked below
under "M3 residual — extended DISPLAY/ACCEPT clauses not covered".

**M6, M10, M11, M12, M13, and M15 remain open**, each close to its own
subsystem rewrite rather than a contained bug fix; deferred to separate
plans. **M17** is test-coverage debt, not a bug, and was not attempted in
this pass.

### M1 — DISPLAY/ACCEPT don't accept figurative constants as operands — FIXED 2026-07-09
`cobolparser/parsers/statements/display_parser.py:106-129` only accepts
`STRING_LITERAL`/`IDENTIFIER`/`NUMERIC_LITERAL`; `TokenType.FIGURATIVE_CONSTANT`
(what `SPACE`/`SPACES`/`ZERO`/`QUOTE`/`HIGH-VALUE`/`LOW-VALUE` lex to) isn't
in that set. `DISPLAY SPACE.` / `DISPLAY SPACES.` **(now warns, not fixed)** —
`display_items: []`, warning `"Unparsed tokens starting at 'SPACE'..."`.
Per the mockymock corpus sweep this is the single most common trigger
(56 hits across 24 real-world shamrice programs).

### M2 — `DISPLAY ... WITH NO ADVANCING` still dropped — FIXED 2026-07-09
No `WITH`/`NO`/`ADVANCING` handling in `display_parser.py`.
**(now warns, not fixed)** — the display item before `WITH` survives, the
clause itself is dropped. Second-most-common mockymock trigger (13 hits).

### M3 — Screen positioning and extended ACCEPT clauses still dropped — FIXED 2026-07-09 (partial, see residual below)
`AT LINE n COLUMN m` on DISPLAY/ACCEPT, and `SECURE`/`TIMEOUT`/`AUTO-SKIP`/
`NO-ECHO`/`UPPER`/`UPDATE` on ACCEPT. **(now warns, not fixed)**. Notably,
`IOAcceptStatement` (`models/statements/io.py:398-443`) already has
scaffolded fields/setters (`at_line`, `at_column`, `with_no_echo`,
`set_position()`, `set_cursor()`, `set_color()`, ...) that
`accept_parser.py` never calls — the model is ready, the parser isn't
wired to it. 32 `AT` + 4 `LINE` + several single-digit extended-clause hits
in the mockymock sweep.

**Fixed 2026-07-09, partially — "M3 residual — extended DISPLAY/ACCEPT
clauses not covered":** a corpus grep of `examples/cobol/shamrice/*.cbl`
found `AT` positioning used 34 times, 100% via the bare combined-numeric
form (`AT 0330`), zero via the `AT LINE n COLUMN m` keyword form — both
are now implemented on `DISPLAY`; `ACCEPT` implements the corpus-confirmed
numeric form. `SECURE`, `NO-ECHO`, `TIMEOUT`, and `AUTO-SKIP` are now
wired on `ACCEPT` (all corpus-confirmed exact shapes); `UPPER` likewise.
`SECURE` and `NO-ECHO` are modeled as distinct flags per
`accept-secure.cbl`'s own comment (`SECURE` masks with `*`, `NO-ECHO`
shows nothing). **Not fixed:** `CURSOR`, `BEEP`/`BELL`, `COLOR`
(`FOREGROUND-COLOR`/`BACKGROUND-COLOR`, a GnuCOBOL-flavored two-part
clause not confidently specified by this finding's original text),
`UPDATE`, and `WITH BLANK SCREEN` (a `DISPLAY`-side clause noticed during
the corpus grep — 6 hits — but never part of this finding to begin with).
None of these had more than one corpus hit except `BLANK SCREEN`, which
was out of scope. See
`tests/regression/test_open_findings_medium_regressions.py::TestM3aDisplayAtPositioning`
and `::TestM3bAcceptExtendedClauses`.

### M4 — `D`-column-7 debug lines: two inconsistent behaviors — FIXED 2026-07-09
`normalize_fixed_format` (`preprocess/__init__.py:494-537`, and its Cython
mirror) only treats `*`/`/` as comment indicators — a `D`/`d` line falls
through and is kept as **live code**. `copy_statement_parser.py`'s
`is_comment_line()` (~line 257-270) treats `D`/`d` as a comment. Same input,
two different pipelines, two different answers, neither configurable, no
signal either way.

### M5 — Continued alphanumeric literal loses trailing blanks — FIXED 2026-07-09
`preprocess/__init__.py:534` (`rstrip()` on the opening line of a new
logical line) and its Cython mirror `_preprocess_fast.pyx:140` strip
trailing blanks that are part of the literal per fixed-format continuation
rules. Repro: opening line `VALUE "ABC   ` (3 trailing blanks) +
continuation `-    "DEF".` → `VALUE "ABCDEF"` (blanks gone; should be
`"ABC   DEF"`).

### M6 — `parse_cobol()` and `tokenize_cobol()`/CLI `tokenize` run different fixed-format logic
`parse_cobol()` normalizes via `normalize_fixed_format` then lexes with
`free_form=True` (comment lines dropped upstream). `tokenize_cobol()`
(`lexer.py:1694-1719`) and CLI `tokenize` (`cli/parse.py:570`) construct
`CobolLexer` directly with `free_form=False` by default, running the
lexer's own ~200-line fixed-format handler (emits `COMMENT` tokens).
Confirmed empirically to disagree on token count/content for the same
source (comment-line handling differs).

### M7 — Typed literals (`X'..'`, `N'..'`, `G'..'`) not decoded — PARTIALLY FIXED 2026-07-09 (hex validation only, see below)
`lexer.py:1245-1307`. `.value` still holds raw inner text; no hex-validity
or even-length check (`X'ABC'`, odd-length/invalid hex, accepted with no
error). A `raw_value` attribute was added since the original audit
(preserves e.g. `"X'1F'"`), which helps a downstream consumer recover the
prefix/kind, but decoding/validation is still absent.

**Fixed 2026-07-09, partially:** `X'..'`/`NX'..'` hex literals now get a
validity check — invalid hex digits or an odd digit count emit a lexer
warning (surfaced via `ParseResult.warnings`). **Not fixed:** the value is
still not decoded to actual bytes/characters (that requires a codepage
decision this fix doesn't make), and `G'..'`/`N'..'` literals are
untouched (different, codepage-dependent validity rules). See
`tests/regression/test_open_findings_medium_regressions.py::TestM7TypedLiteralHexValidation`.

### M8 — Tab handling in fixed-format normalization — FIXED 2026-07-09
No tab-expansion logic anywhere in `normalize_fixed_format` — columns are
still raw character-index slices. **(now warns, not fixed)**: a leading
tab shifting columns now produces `"Unparsed tokens..."` (caught by the
generic unknown-verb/unparsed-token warning mechanism added 2026-07-07)
rather than being fully silent — but `ParseResult.success` only checks
`errors`, so a caller checking only `success`/`errors` still misses it.

### M9 — `try_parse_nested_statement` still has a bare `except Exception` — FIXED 2026-07-09
`_utils.py:598-636`. CHANGELOG's own text confirms the 2026-07-07 cleanup
only added a DEBUG log call here — "the fall-back behaviour itself is
unchanged." Errors raised via `report_or_raise` are separately
pre-recorded into `ParseResult.errors` before the raise (so some failures
do surface), but exceptions that bypass `report_or_raise` (e.g.
`TokenMismatch`/`UnexpectedEndOfInput` raised directly by
`token_stream.expect()`) are still fully lost with only a DEBUG line.

### M10 — Conditional compilation (`>>IF`/`>>EVALUATE`) still functionally incomplete
`preprocess/__init__.py:628-686`. **(now warns, not fixed)**: only
`symbol IS [NOT] DEFINED` is evaluated; any other `>>IF` condition (e.g.
`>>IF DEBUGLEVEL > 3`) still unconditionally blanks the guarded block
regardless of truth value — confirmed with a numerically-true condition
still being skipped, now with a warning attached. `>>EVALUATE` is
confirmed still fully unimplemented (falls through to the generic
"unknown directive passed through unprocessed" branch). Also still not
wired into the default `parse_cobol()` path — only reachable via
`parse_cobol_with_expansion(process_conditionals=True)` or CLI `--define`.

### M11 — EXEC CICS / EXEC IMS remain raw-text stubs; EXEC SQL improved but still not a real clause tree
`ExecCicsStatement`/`ExecImsStatement` (`ibm_exec_statements.py`) still only
capture a command name + flat joined-token text blob — `EXEC CICS SEND
MAP('MAP1') MAPSET('SET1') END-EXEC.` produces no `MAP`/`MAPSET` fields.
EXEC SQL is better than the original audit claimed: `parse_exec_sql()`
(`models/sql_statements.py`) now regex-extracts `sql_type`, `host_variables`,
and `tables` — but this is regex field-scraping over the flattened SQL
text, not a real SQL grammar (no SELECT-list/WHERE-clause structure).

### M12 — Arithmetic/loop expressions still stored as raw strings, not trees
`ComputeStatement.expression` (`arithmetic_parsers.py:477-523`) is always a
plain joined `str`, never decomposed. `PERFORM ... UNTIL`'s
`CobolExpression.operands` (added since the original audit, referenced in
CHANGELOG) is a **one-element list containing the entire raw condition
string** — the new `operands` key is cosmetic, not structural decomposition.
`IfStatementParser`'s comparison/logical path (`if_parser.py:235-325`) is
genuinely tree-structured (predates these audits) and not affected — but
its fallback for non-comparison conditions (`IF A IS NUMERIC`,
condition-names, sign conditions) still stores a raw joined string in
`metadata.raw_condition`.

### M13 — REPLACING is context-blind text substitution
`apply_replacing_clauses` (`copy_statement_parser.py:774-824`) is pure
regex substitution with only identifier-boundary lookarounds — no
literal/comment awareness. Confirmed: a `REPLACING FOO BY BAR` clause
rewrites `FOO` both inside a `*`-comment and inside a string literal
VALUE. Separately, `:...:` pseudo-text delimiters are silently broken in
the actual code path used by `expand_copybooks()` (`CopyStatementLexer`):
`REPLACING :ABC: BY :XYZ:` is captured **with the colons still attached**
as literal text, so the substitution never matches anything in the
copybook body and silently no-ops (a separate, unused regex-based parser
in the same file does handle `:...:` correctly, but nothing calls it).

### M14 — Copybook cache hits bypass `total_bytes` size accounting — FIXED 2026-07-09
`copybook_expander.py:571-594` (`_expand_source_recursive`): `context.total_bytes`
is only incremented on a cache **miss**; a copybook served from the
intra-expansion cache (e.g. the same member COPYd multiple times — a
routine diamond dependency) contributes zero to the running total. Repro:
3x inclusion of a 76-byte copybook, `max_total_size=96` → no
`TotalExpansionSizeExceededError` raised despite 228 true content bytes,
more than double the configured limit.

### M15 — EBCDIC autodetection heuristic still fragile; lossy decode fallback still silently mangles bytes
`copybook_expander.py:194-210` (`detect_encoding`) is still a raw
`0x40`-vs-`0x20` byte-count heuristic with a 5% threshold.
`convert_to_utf8` still uses `errors="replace"` (U+FFFD) on undecodable
bytes. **(now warns, not fixed)**: since the 2026-07-07 H6b fix, a lossy
decode now appends a diagnostic to `warnings` when the caller threads a
list through — but the byte-level data loss itself is unchanged, and the
detection heuristic wasn't touched.

### M16 — `PIC 99/99/99` (slash-edited pictures) corrupts DATA DIVISION structure — FIXED 2026-07-09
Worse than the original "garbled but harmless" framing:
`PictureClause.pattern` truncates to `"99"` (first segment only), and the
`/99/99` remainder is misinterpreted as **phantom level-99 data items**
(`ANONYMOUS-99-5` etc., duplicated as both a child of the real item and at
top level) plus 2 "unparsed token" warnings. Dot-edited pictures
(`PIC 99.99`) work correctly — only slash/comma/other-operand-character
editing is affected.

### M17 — Divisions `data.py`/`environment.py` branch-coverage debt grew, not shrank
Both files roughly doubled in size since the 2026-07-06 baseline
(48→86 missing branches in `divisions/data.py`; 40→69 in
`divisions/environment.py`, measured against the same ~89% of the suite).
Branch-coverage *percentage* is flat-to-improved (new code is reasonably
tested), but the absolute untested-branch count — the thing that
determines how much of the DATA/ENVIRONMENT-division clause surface is
unverified — is worse than at the original audit.

---

## LOW

- **`*>` inline comments** still lex as `MULTIPLY_OP` + `GREATER`, not
  recognized as a comment marker (confirmed via direct token dump).
- **`TokenType.ALL` is dead** — `"ALL"` always lexes as a
  `FIGURATIVE_CONSTANT`; zero references to `TokenType.ALL` anywhere in the
  codebase. Currently masked for `INSPECT ... REPLACING ALL` (the statement
  parser special-cases the string value `"ALL"` regardless of token type),
  but any future construct that needs to distinguish the `ALL` keyword from
  the figurative constant has no way to.
- **Dead code**: `lexer.py:1398` `_compress_doubled_quotes` — defined, never
  called in production (only referenced directly by a test for coverage).
- **Unknown column-7 indicator characters** (anything other than
  space/`*`/`/`/`-`/`D`) are silently treated as live code by
  `normalize_fixed_format`, confirmed in both the pure-Python and active
  Cython path.
- **A comment line interrupting an open continued literal silently severs
  it**: `normalize_fixed_format`'s comment branch flushes and resets
  `pending_literal`, so the next continuation line is treated as a
  non-literal continuation instead of merging. If quotes stay balanced
  across the interruption this corrupts the literal with no error; if they
  don't, it raises a confusing unrelated "unterminated string literal at
  EOF" error instead of a clear diagnostic.
- **`CallStatement.possible_values` (`DynamicCallAnalyzer`) returns `[]`
  ambiguously** — no way to distinguish "analyzer never tracked this
  variable" from "tracked, resolved to zero possible values" (the latter
  state is structurally unreachable in the current code, which is itself
  part of the ambiguity).
- **`ProfilerContext` over-reports peak memory when tracemalloc is already
  active** — `tracemalloc.reset_peak()` is never called in
  `profiling.py`, so if tracemalloc was started by something else before
  `ProfilerContext.__enter__` runs, the reported peak includes
  pre-existing allocations. (Not reachable via two literal nested
  `ProfilerContext`s in this process — `cProfile.Profile.enable()` raises
  immediately on a second concurrent instance — but reachable via any
  other concurrent tracemalloc consumer, e.g. another profiling harness.)
- **`CobolFileDescription` AST class is fully built (including `to_dict()`)
  but never instantiated** — FD/SD clauses are parsed into a raw
  `metadata["fd_clauses"]` dict on the associated `01`-level item instead.
  Data isn't lost (round-trips via metadata), so this is a dead-code/API
  surface inconsistency, not a silent drop.
- **Newly-recognized-but-unsupported verbs (INITIATE, TERMINATE, CHAIN,
  GOTO, NOTE, RECOVER, SUPPRESS, ...) now warn explicitly** via
  `_UNSUPPORTED_VERBS` (confirmed: distinct "Unsupported statement ...
  no parser is registered for this verb" message, and a preceding
  period-less statement is no longer swallowed) **but still produce no
  AST node** — downgraded from "silent drop" to "warned, unmodeled."
  Tracking here only as a reminder these constructs still aren't captured
  in the AST, not as a live bug.

---

## Test / tooling

- **12 permanently-skipped copybook-expansion tests**, unchanged count and
  locations since 2026-07-06: `tests/unit/test_copybook_expansion.py` (3,
  lines 296/300/308), `tests/contracts/test_copybook_expansion_contracts.py`
  (5, lines 226/230/234/242/246), `tests/integration/test_copybook_expansion_integration.py`
  (4, lines 180/184/650/654) — all `pytest.skip("Implementation pending -
  Phase 6/7")`.
- **The Tier-2 path-resolver symlink/containment gap (H6 above) has zero
  test coverage** — no `symlink` reference anywhere under `tests/`, and
  the existing rejection-path tests
  (`tests/unit/test_path_resolver_coverage.py`) only exercise the
  Tier-3/`validate()` code path, not the Tier-2 fast path.
- **CI's Cython-extension build is implicit, not an explicit step** —
  `.github/workflows/ci.yml`'s `test` job has no `build_ext --inplace`
  step; the compiled `_lexer_fast`/`_preprocess_fast`/`_data_fast` paths
  are only exercised as a side effect of `pip install -e ".[dev]"` (which
  triggers `cythonize()` via `pyproject.toml`'s build-system requirement).
  Verified this **currently works** — `test_fast_lexer_is_active` /
  `test_fast_preprocess_is_active` pass on all 3 Python versions in the
  latest CI run — but it's an undocumented dependency on packaging
  behavior rather than a guaranteed CI step; if the editable-install
  mechanics ever change, the fast path could silently stop being tested
  with no CI signal.
- `branch-coverage holes` are covered under M17 above (moved there since
  it's a substantive, not just tooling, gap).
- **`tests/regression/test_open_findings_medium_regressions.py`** pins the
  2026-07-09 fixes for M1, M2, M3 (partial), M4, M5, M7 (partial), M8, M9,
  M14, and M16 — one `TestM<N>...` class per finding, mirroring
  `test_open_findings_high_regressions.py`'s convention.

Not included here: `batch.py` coverage (was 61%, now empirically 93.55% —
resolved), fast-vs-pure token/output identity (parity tests now exist and
pass), and the NIST `KNOWN_ISSUES` xfail list growing from 2→4 entries
(`SM206A`/`SM208A` added) — that's the H3 MOVE-diagnostics fix surfacing
two previously-masked, now-honestly-documented parser limitations, not a
regression.
