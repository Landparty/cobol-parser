---
type: Module
title: Parser
description: CobolParser, DivisionParserFactory, StatementParserRegistry — converts Token stream to ParseResult.
tags: [parser, ast, division, statement, registry]
timestamp: 2026-07-09T00:00:00Z
---

# Overview

`cobolparser/parser.py` — `CobolParser` orchestrates the full parse pipeline.
It normalises input, lexes it via `CobolLexer`, wraps tokens in `TokenStream`,
then delegates to `DivisionParserFactory` for each COBOL division.

# Public API

```python
from cobolparser import CobolParser, ParseResult, parse_cobol
from cobolparser import ErrorRecoveryMode, MemoryConfiguration, SerializationConfig
from cobolparser.dialects import IBMEnterpriseCobol

# Convenience
result: ParseResult = parse_cobol(source, filename="prog.cob")

# Configurable
config = MemoryConfiguration(max_memory_mb=256)
parser = CobolParser(
    memory_config=config,
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
)
result = parser.parse(source)

# With IBM dialect + serialisation options
dialect = IBMEnterpriseCobol()
parser = CobolParser(dialect=dialect, serialization_config=SerializationConfig(include_metadata=True))
```

# ParseResult

```python
@dataclass
class ParseResult:
    ast: CobolProgram | None
    errors: list[ParseError]
    warnings: list[str]
    statistics: ParseStatistics

    @property
    def success(self) -> bool:        # ast is not None AND no errors
    @property
    def has_warnings(self) -> bool:
```

`warnings` is the "recognized but degraded" channel (2026-07-07): the parser
populates it when it skips an unsupported verb (no registered statement
parser — e.g. `INVOKE`, `EXHIBIT`; see
`ProcedureDivisionParser._UNSUPPORTED_VERBS`), when it skips leftover clause
tokens a statement parser did not understand ("Unparsed tokens" warnings),
when a compilation unit contains more than one program (see below), and
(2026-07-09) when the lexer itself recorded a non-fatal diagnostic — see
the "Warnings (non-fatal diagnostics)" section of [lexer.md](lexer.md).
Unknown statements
were previously consumed with only a `logger.debug`, so `errors=0,
warnings=0` did not guarantee a complete AST.

## Multi-program compilation units (2026-07-07)

`parse_program()` no longer stops at the first `END PROGRAM`. Stacked or
nested programs in one source member are each parsed into their own
`CobolProgram`; the first is returned as `ParseResult.ast` and the rest are
attached to `ast.contained_programs` (also reachable via `get_all_statements()`
and `to_dict()["contained_programs"]`), with one summary warning. Helpers:
`_peek_is_end_program()` / `_consume_end_program_marker()` consume
`END PROGRAM [name] [.]` between units. Previously everything after the first
program was silently dropped (NIST `IC228A` retained ~3% of statements with
`errors=0`).

# Architecture

```
CobolParser.parse(source)
  ├─ normalize_fixed_format()          # fixed-format → free-form
  ├─ strip_compiler_directives()       # remove compiler control statements
  ├─ CobolLexer.tokenize()             # → List[Token]
  ├─ TokenStream(tokens)               # lookahead abstraction
  └─ DivisionParserFactory
       ├─ IdentificationDivisionParser
       ├─ EnvironmentDivisionParser
       ├─ DataDivisionParser
       └─ ProcedureDivisionParser
            └─ StatementParserRegistry  (first-match dispatch)
                 └─ 26 statement parsers
```

# Core Infrastructure (`cobolparser/core/`)

| File | Class / Purpose |
|------|----------------|
| `interfaces.py` | `ITokenStream`, `IDivisionParser`, `IStatementParser` ABCs; `ParserHost` protocol; `ParseContext` |
| `token_stream.py` | `TokenStream` — `peek()`, `consume()`, `expect()`, configurable lookahead |
| `registry.py` | `StatementParserRegistry` — first-match dispatch |
| `exceptions.py` | `TokenMismatch`, `UnexpectedEndOfInput`, `DivisionNotFoundError`, `UnknownStatementError`, `ValidationError` |
| `ast_factory.py` | `ASTNodeFactory` — validated node creation; `get_factory()` / `create_node()` |
| `_errors.py` (root) | `ParseError` base class — zero internal deps (avoids circular imports) |

# Division Parsers (`cobolparser/parsers/divisions/`)

| File | Division |
|------|---------|
| `factory.py` | `DivisionParserFactory`, `DivisionType` enum (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE) |
| `base.py` | Base division parser with error recovery |
| `identification.py` | IDENTIFICATION DIVISION |
| `environment.py` | ENVIRONMENT DIVISION — division scan + AST node; section/SELECT parsing delegated to the two `environment_*.py` collaborators below |
| `environment_sections.py` | `ConfigurationSectionParser` (CONFIGURATION SECTION + SPECIAL-NAMES) and `InputOutputSectionParser` (INPUT-OUTPUT SECTION + FILE-CONTROL) |
| `environment_select.py` | `SelectClauseParser` — SELECT statement + all clause parsers (ASSIGN/ORGANIZATION/ACCESS/KEY/STATUS/ALTERNATE/PADDING/RESERVE/SHARING/LOCK/PASSWORD) and `SelectStatement` node construction |
| `data.py` | DATA DIVISION — section scan, level-number hierarchy, AST node; entry parsing delegated to the three `data_*.py` collaborators below |
| `data_clauses.py` | `DataItemClauseParser` — data-item entries + PICTURE/VALUE/USAGE/OCCURS/... clauses; owns the optional `_data_fast` Cython fast-path invocation |
| `data_file_description.py` | `FileDescriptionClauseParser` — FD/SD file-description clause capture (BLOCK/RECORD/LABEL/...) |
| `data_special_entries.py` | `SpecialEntryParser` — level-88 condition names, level-66 RENAMES, data-division EXEC SQL blocks |
| `procedure.py` | PROCEDURE DIVISION — paragraph/section dispatch loop, ParseContext attachment, AST node; hosts the shared `StatementParserRegistry` cache; supporting logic delegated to the three `procedure_*.py` collaborators below |
| `procedure_registry.py` | `create_statement_registry()` — registers all 40+ statement parsers in first-match priority order (new statement parsers register here) |
| `procedure_boundaries.py` | `is_paragraph_or_section_start` / `is_section_marker` / `is_statement_keyword` lookahead predicates |
| `procedure_recovery.py` | `StatementRecoveryHandler` — unsupported-statement warnings, FAIL_FAST/COLLECT_ALL error recording, stream resynchronization; owns `STRAY_MARKERS` / `UNSUPPORTED_VERBS` (aliased as `ProcedureDivisionParser._STRAY_MARKERS` / `._UNSUPPORTED_VERBS`) |

**Cython callback surface (2026-07-15 refactor):** `DataDivisionParser` keeps
`_parse_picture_clause` / `_parse_value_clause` / `_parse_usage_clause` (and
`_parse_data_item`) as delegating wrappers with their historical names and
signatures — the compiled `_data_fast` extension receives the division parser
as `parser_self` and calls those three back by name. New clause logic goes in
`DataItemClauseParser`; the wrappers must stay.

**LEVEL_NUMBER-as-literal gotcha (`data.py`):** the lexer types every 1-2
digit integer as `TokenType.LEVEL_NUMBER` regardless of context (even inside
`PIC 9(4)` or after `VALUE`). Any data-division clause that consumes a numeric
must therefore accept `LEVEL_NUMBER` alongside `NUMERIC_LITERAL` —
`_parse_value_clause`, the level-88 value collector, and the OCCURS handlers
all do. `_parse_value_clause` also consumes an optional `IS` and a
`MINUS`/`PLUS` sign token before the literal (`VALUE IS -5`). Regression
suite: `tests/regression/test_numeric_value_clause.py`.

# Statement Parsers (`cobolparser/parsers/statements/`)

| File | COBOL Verbs |
|------|------------|
| `accept_parser.py` | ACCEPT |
| `arithmetic_parsers.py` | ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE |
| `call_parser.py` | CALL |
| `close_parser.py` | CLOSE |
| `delete_parser.py` | DELETE |
| `display_parser.py` | DISPLAY |
| `entry_parser.py` | ENTRY |
| `evaluate_parser.py` | EVALUATE |
| `go_parser.py` | GO TO |
| `ibm_exec_statements.py` | EXEC SQL, EXEC CICS, EXEC IMS DLI |
| `if_parser.py` | IF |
| `initialize_inspect_parsers.py` | INITIALIZE, INSPECT |
| `move_parser.py` | MOVE |
| `open_parser.py` | OPEN |
| `perform_parser.py` | PERFORM |
| `read_parser.py` | READ |
| `rewrite_parser.py` | REWRITE |
| `search_parser.py` | SEARCH |
| `set_parser.py` | SET |
| `simple_statement_parsers.py` | ALTER, CANCEL, COMMIT, CONTINUE, EXIT, GENERATE, GOBACK, RELEASE, RETURN, ROLLBACK, USE |
| `sort_merge_parsers.py` | SORT, MERGE |
| `start_parser.py` | START |
| `stop_parser.py` | STOP |
| `string_unstring_parsers.py` | STRING, UNSTRING |
| `unlock_parser.py` | UNLOCK |
| `xml_json_parser.py` | XML GENERATE, XML PARSE, JSON GENERATE, JSON PARSE |
| `write_parser.py` | WRITE |
| `_utils.py` | Shared clause-collection utilities |

**IO clause bodies (`_utils.py` / `read_parser.py` / `write_parser.py` /
`rewrite_parser.py` / `delete_parser.py` / `start_parser.py`):** the
statements inside `AT END` / `NOT AT END` / `INVALID KEY` / `NOT INVALID
KEY` clauses are parsed by `collect_clause_stmts` in `_utils.py`, which
dispatches through the statement registry attached to the token stream
(same mechanism as IF/PERFORM/EVALUATE nesting). The parsed statements are
attached to the IO node's clause list (`at_end_clause`, `invalid_key_clause`,
…) **and** added as AST children, so `find_all_by_type` and `to_dict()` see
them. Clause collection stops at a period, `NOT`/`INVALID` (next clause), a
caller-supplied stop value (e.g. `END-READ`), any `SCOPE_TERMINATORS` /
`CONTROL_FLOW_BOUNDARIES` value, or when a nested parser consumed the
sentence period (`previous_meaningful_token` check). The MOVE-target,
DISPLAY-item, and CALL-USING collection loops stop at `SCOPE_TERMINATORS`
(and MOVE additionally at `NOT`/`INVALID`/`AT` token types) so clause
boundaries are never swallowed as operands. `WriteStatementParser` parses
`INVALID KEY` / `NOT INVALID KEY` via the shared `parse_invalid_key_clauses`,
and `StartStatementParser` matches comparison keywords by value (they lex as
dedicated token types, not IDENTIFIERs) and consumes the KEY data-name.
Before 2026-07-05 `collect_clause_stmts` **discarded** clause tokens and
returned `[]` — an inner `CALL` in `AT END` vanished from the AST entirely,
blinding mockymock's boundary detection. Pinned by
`tests/unit/io_statements/test_clause_bodies.py`.

**SUBTRACT/ADD trailing `GIVING` on a continuation line, subscripted DISPLAY
operands, and `WRITE ... FROM` literal (`arithmetic_parsers.py` /
`display_parser.py` / `write_parser.py` / `_utils.py`, 2026-07-07):** three
content-drop bugs found by mockymock's corpus sweep against
`legacy-application`, all now fixed (26/26 corpus programs parse and
generate clean, zero refusals):
- `SubtractStatementParser`'s `FROM` branch never checked for a trailing
  `GIVING` the way `AddStatementParser`'s `TO` branch already did, so
  `SUBTRACT a FROM b GIVING c` silently stored the result back into `b`
  and dropped `c` entirely. Fixed by mirroring the ADD parser's check.
- `_utils.consume_keyword_and_operand` only skipped `NEWLINE` tokens
  *between* a keyword and its operand, not *before* checking whether the
  keyword was present at all — so an optional clause keyword (`GIVING`,
  etc.) on its own continuation line (ordinary free-form COBOL layout) was
  missed. Now calls `skip_whitespace` (not the narrower `_skip_newlines`)
  before *and* after the keyword check, so a leading `WHITESPACE`/
  `COMMENT`/`CONTINUATION` token doesn't hide the keyword either — a
  review comment flagged that fixed-format continuation lines carry a
  `CONTINUATION` token (column-7 `-`), not just `NEWLINE`, though in the
  standard `parse_cobol` pipeline `normalize_fixed_format` already merges
  those textually before the lexer runs, so this is defensive-in-depth
  rather than a reachable gap through today's entry point. Fixes the same
  class of bug for `ADD ... TO ... GIVING` when `GIVING` is on a
  continuation line.
- `DisplayStatementParser`'s item loop only accepted
  `STRING_LITERAL`/`IDENTIFIER`/`NUMERIC_LITERAL` tokens, so a subscripted
  operand like `SQLERRD(3)` hit the bare `LEFT_PAREN` token and aborted
  the whole item list. `_consume_subscript` now folds a following
  `( ... )` into the preceding identifier as one display item, tracking
  paren depth so a nested subscript/function call (`TAB(FUNCTION
  MOD(3 2))`) keeps its inner parens literally instead of flattening them
  into a single space-joined pair (a review comment on the first version
  of this fix caught that flattening bug).
- `WriteStatementParser`'s `FROM` clause only accepted `IDENTIFIER`; a
  literal source (`WRITE rec FROM 'text'`, an IBM/GnuCOBOL extension) was
  left unconsumed. Now accepted and stored quoted.
Pinned by `tests/unit/test_arithmetic_size_error_branches.py`,
`tests/unit/test_utils_clause_collection.py`,
`tests/unit/test_display_parser.py`, and
`tests/unit/io_statements/test_write_close_parsers.py`.

**EVALUATE blank string-literal WHEN selectors (`evaluate_parser.py`):**
the lexer strips quotes off string literals, so `WHEN '  '` (the IMS DL/I
status-code idiom) arrives as a whitespace-only token that `_build_selector`
would filter out as an empty artifact, collapsing the clause to zero
selectors and reporting "WHEN clause must have at least one selector" on
valid programs. `_parse_selectors` re-quotes whitespace-only
`STRING_LITERAL` tokens (selector value `"'  '"`); non-blank literals keep
their unquoted representation. Pinned by
`tests/regression/test_evaluate_space_literal_when.py`.

**EVALUATE WHEN-clause child registration (`evaluate_parser.py`):** the
`WhenClause` nodes (both regular `WHEN` branches and the `WHEN OTHER`
`default_when`) must be attached via the model's `add_when_clause` /
`set_default_when` methods, which call `add_child`. Before 2026-07-07 the
parser mutated the model directly (`stmt.when_clauses.append(...)`,
`stmt.default_when = ...`), so the clauses were **never** AST children and
every statement nested in a WHEN branch was invisible to `find_all_by_type` /
`find_first_by_type` / `traverse_depth_first` (which only walk `node.children`)
— though still reachable via `CobolProgram.get_all_statements` (which also
recurses the `when_clauses` / `default_when` attributes and dedupes by `id`).
Because `get_all_statements` dedupes, registering the clauses as children does
not double-count. `EvaluateStatement.to_dict()` serializes the `when_clauses`
attribute, not `children`, so its output is unchanged. Because
`set_default_when` always calls `add_child`, a malformed program with two
`WHEN OTHER` branches reuses the existing `default_when` clause (still
reporting the error) rather than attaching a second one — otherwise the
orphaned first default clause's statements would be surfaced by the tree-walk
APIs but not by `default_when` / `to_dict()`. Pinned by
`tests/regression/test_evaluate_traversal_regression.py`.

**CALL handler-body termination (`call_parser.py`):** the ON EXCEPTION /
NOT ON EXCEPTION / ON OVERFLOW bodies are parsed by `_parse_nested_stmts`,
which dispatches through the statement registry. Termination is three-fold:
a `NOT` / `END-CALL` boundary value, a period seen between statements, or —
because a nested statement parser may itself consume the sentence period —
a check after every nested parse that the last consumed meaningful token was
a `PERIOD` (`previous_meaningful_token` from `_utils.py`, same pattern as
`if_parser.py`). `_parse_using_clause` additionally stops at any
`SCOPE_TERMINATORS` value so `END-CALL` is never captured as a USING
parameter. Before 2026-07-05 the handler body swallowed following top-level
statements (e.g. `STOP RUN` after `END-CALL.`) — pinned by
`tests/regression/test_call_handler_body_termination.py`.

**Multi-mode OPEN (`open_parser.py`):** one OPEN statement may carry several
mode groups (`OPEN INPUT FILE-A OUTPUT FILE-B EXTEND FILE-C`). The parser
collects the file names of *every* group into `IOOpenStatement.file_names`;
`open_mode` keeps only the **first** group's mode (backward-compatible
single-mode field). Before 2026-07-05 the file-name loop broke at the second
mode keyword and silently dropped all later files — pinned by
`tests/unit/io_statements/test_open_read_parsers.py::TestOpenParserCoverage::test_open_multiple_mode_groups_captures_all_files`.

**MOVE / SUBTRACT / MULTIPLY / DIVIDE swallowing a following statement
(`move_parser.py`, `arithmetic_parsers.py`, `_utils.py`):** a statement with
no trailing period, immediately followed by another statement, must stop at
the boundary rather than consume the next statement's leading tokens.
- `MoveStatementParser`'s target-collection loop now stops on the shared
  `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` (`_utils.py`) unioned with its
  own clause-boundary extras (`GO`, `ELSE`/`WHEN`/`END-*`, and the IO-clause
  `NOT`/`INVALID`/`AT` tokens), instead of a hand-rolled, incomplete local
  list. The local list omitted `EXEC`/`EXECUTE` (among other verbs), so
  `MOVE X TO Y` immediately followed by `EXEC SQL ... END-EXEC` (no period
  after the MOVE) silently swallowed `EXEC SQL <table-qualifier>` as bogus
  MOVE targets and the whole EXEC SQL block vanished from the AST.
- `SubtractStatementParser` and the shared `_parse_binary_arithmetic` helper
  (MULTIPLY/DIVIDE) ended their parse with `skip_to_period()` — a crude "eat
  every token until the next period" helper — instead of `parse_size_error_clauses`
  (already used by ADD/COMPUTE), which properly parses ON SIZE ERROR / NOT ON
  SIZE ERROR and stops without consuming at the first unrecognized token.
  `skip_to_period()` has been deleted (dead code once nothing called it).
  Because a following EXEC SQL block's leading text is not
  period-terminated, `skip_to_period` walked past the entire block, stopping
  only at a coincidental period inside a qualified table name (e.g.
  `BANK.ACCOUNT`) — the remaining SQL `SET` clause was then misparsed as a
  COBOL `SET` statement.
- Fixing that swap exposed two previously-unreachable bugs in
  `_parse_size_error_stmts` (`_utils.py`), both now fixed:
  1. Its inline DISPLAY mini-parser collected display items until a period
     or literal `MOVE`/`DISPLAY`, so `ON SIZE ERROR DISPLAY '...' NOT ON
     SIZE ERROR ...` swallowed `NOT ON SIZE ERROR` as bogus display items
     instead of recognizing it as the next clause. It now also stops (without
     consuming) at `TokenType.NOT` and any non-string-literal token whose
     value is in `STATEMENT_KEYWORDS`/`SCOPE_TERMINATORS`/
     `CONTROL_FLOW_BOUNDARIES` (the `STRING_LITERAL` exclusion also fixes a
     latent truncation bug for `DISPLAY 'ADD'`-style literals that predates
     this change).
  2. Its own outer dispatch loop's `else` branch (for verbs other than
     DISPLAY/MOVE) unconditionally called `stream.consume()` — violating its
     own docstring ("the next clause boundary is NOT consumed"). A `NOT`
     token (or a scope/control-flow boundary like `END-SUBTRACT`) reaching
     this branch — e.g. right after the DISPLAY fix above correctly stopped
     without consuming it — was silently eaten one token at a time instead
     of ending the clause, so `NOT ON SIZE ERROR`'s own DISPLAY got merged
     into the *first* clause's nested-statement list and `not_on_size_error`
     stayed `None`. The `else` branch now breaks (without consuming) on
     `TokenType.NOT` or a `SCOPE_TERMINATORS`/`CONTROL_FLOW_BOUNDARIES`
     value; other verbs are still skipped token-by-token, per the documented
     "DISPLAY and MOVE are the only inline mini-parsers" design.
- `ARITHMETIC_OPERAND_TOKEN_TYPES` (`_utils.py`) gained
  `TokenType.FIGURATIVE_CONSTANT` — figurative constants (`ZERO`, `SPACES`,
  ...) are valid operands anywhere a literal is allowed (e.g. `MULTIPLY A BY
  ZERO GIVING B`); the SUBTRACT `FROM` target already special-cased this
  token type, so the general operand set was inconsistent with it. This
  surfaced only once the swallow-bug fixes above stopped masking
  `tests/samples/arithmetic_operations.cbl`'s `DIVIDE ... BY ZERO ...`
  statement (previously never reached — the *preceding* DIVIDE statement's
  `skip_to_period` had swallowed it as part of a much larger silently
  discarded block).
Originally found via a real ACCTMNT.cbl banking program (mockymock e2e
work): two EXEC SQL `UPDATE`/`INSERT` blocks vanished from the AST with
`result.success == True` and no errors reported. The same bug class also
hit a `CALL 'CBLTDLI' USING DLI-REPL` in an IMS sample's `ELSE` branch (see
`tests/unit/test_ims_segment_analyzer.py::TestRealWorldBankingAccounts`) —
previously misattributed to "ELSE branches aren't traversed" when the real
cause was an un-punctuated `SUBTRACT` swallowing the branch. Pinned by
`tests/regression/test_tier2_silent_drop_regressions.py` (Group 6).

**COMPUTE also swallowed a following statement (`arithmetic_parsers.py`,
2026-07-06):** the 2026-07-05 fix above explicitly covered MOVE/SUBTRACT/
MULTIPLY/DIVIDE but not COMPUTE — `ComputeStatementParser.parse()`'s
expression-token-collection loop is its own inline loop, not
`parse_arithmetic_operands()`, so it didn't inherit that fix. At
`paren_depth == 0` it only stopped at a `PERIOD` or a value in `("ON",
"NOT", "END-COMPUTE")`; it never checked `STATEMENT_KEYWORDS` /
`CONTROL_FLOW_BOUNDARIES`. A `COMPUTE` with no trailing period, immediately
followed by another statement (e.g. a multi-line `CALL 'MQOPEN' USING
...`), had that statement's tokens silently appended to the COMPUTE
expression string — the following statement vanished from the AST with
`result.success == True` and no error reported. Found via a real DEPTMQP
program (mockymock e2e work): `COMPUTE MQ-OPEN-OPTIONS = ... ` directly
followed by `CALL 'MQOPEN' USING ...` with no separating period. Fixed by
adding a `STATEMENT_KEYWORDS`/`CONTROL_FLOW_BOUNDARIES`/`SCOPE_TERMINATORS`
check to the expression loop (mirrors `parse_arithmetic_operands()`'s stop
set, plus `SCOPE_TERMINATORS` for the nested-clause trigger below). The
same gap also swallowed an *enclosing* scope terminator when COMPUTE sits
inside a clause body with no trailing period before it — e.g. `READ ... AT
END COMPUTE X = Y + 1 END-READ` had `END-READ` folded into the expression
string (`"Y + 1 END-READ"`) instead of ending the clause, which the
`STATEMENT_KEYWORDS`/`CONTROL_FLOW_BOUNDARIES` check alone did not catch
(`END-READ` is in neither set — only `SCOPE_TERMINATORS`). Pinned by
`tests/regression/test_tier2_silent_drop_regressions.py::TestComputeDoesNotSwallowFollowingCall`
and `::TestComputeDoesNotSwallowEnclosingScopeTerminator`.

**INSPECT / STRING / UNSTRING also swallowed a following statement, and EXEC
SQL/CICS/IMS silently ate the rest of the program on a missing `END-EXEC`
(`initialize_inspect_parsers.py`, `string_unstring_parsers.py`,
`ibm_exec_statements.py` + `_utils.py`, audit 2026-07-06 H2):** the same
un-punctuated-statement swallow class as MOVE/arithmetic above, in the last
four verbs that never consulted the boundary guards.
- A new shared predicate `is_statement_boundary(token)` (`_utils.py`)
  centralises the four-way check (`STATEMENT_TOKEN_TYPES` /
  `STATEMENT_KEYWORDS` / `SCOPE_TERMINATORS` / `CONTROL_FLOW_BOUNDARIES`) that
  MOVE/arithmetic perform inline. `InspectStatementParser`'s trailing
  "consume to period" loop and the `StringStatementParser` /
  `UnstringStatementParser` main-loop `else: consume()` fall-throughs now
  `break` (without consuming) on it, so a following statement with no period
  (or `END-STRING`/`END-UNSTRING`) before it survives instead of being eaten
  up to the next period. None of the three verbs' own clause keywords
  (DELIMITED/BY/INTO/WITH/POINTER/ON/OVERFLOW/NOT/REPLACING/TALLYING/
  CONVERTING) collide with the boundary sets.
- **EXEC-* is deliberately NOT routed through `is_statement_boundary`.**
  Embedded SQL/CICS/IMS text legitimately contains COBOL statement keywords
  (SET, DELETE, UPDATE, CALL, OPEN, CLOSE), so a content-keyword boundary
  would truncate valid SQL — the highest-traffic embedded construct. The only
  safe end marker is the mandatory `END-EXEC`. `collect_exec_sql_text`
  (`_utils.py`) now tracks whether it actually saw `END-EXEC`; if the stream
  is exhausted first (malformed block), it records a non-fatal
  "Unterminated EXEC block: missing END-EXEC" error via the parse context
  attached to the stream (`get_parse_context` + `report_parse_error`), so the
  block no longer swallows the rest of the program with `errors=0` — it now
  reports the error and `result.success` is `False`. Well-formed blocks (with
  `END-EXEC`) are unaffected; the DATA-division caller
  (`data.py::_parse_exec_sql_in_data`) does not attach a context, so it
  degrades to the prior silent behavior rather than raising. Every EXEC block
  in the NIST + shamrice + `tests/samples` corpora is `END-EXEC`-terminated,
  so no clean-parse test regressed. Pinned by
  `tests/regression/test_tier2_silent_drop_regressions.py`
  `::TestInspectDoesNotSwallowFollowingStatement`,
  `::TestStringDoesNotSwallowFollowingStatement`,
  `::TestUnstringDoesNotSwallowFollowingStatement`, and
  `::TestExecMissingEndExecReportsError`.

**MOVE silently accepted malformed/incomplete input (`move_parser.py`,
2026-07-06, audit finding H3):** the MOVE parser produced a
plausible-but-wrong node with `errors == 0` for incomplete input — `MOVE A
TO.` yielded a `MoveStatement` with `targets: []`; `MOVE A` (no `TO`) and a
stream truncated at `MOVE A TO` were also accepted. `MoveStatementParser.parse`
now pulls the active `ParseContext` (via `_utils.get_parse_context`) and calls
`report_parse_error` — the same record-and-continue path GO/CALL use, so the
error lands in `ParseResult.errors` under both `COLLECT_ALL` and (the default)
`FAIL_FAST` without dropping the node or forcing `_skip_to_next_statement`
recovery — in two spots: when `TO` is absent, and when zero receiving fields
follow `TO` (`target_count == 0`). Well-formed MOVEs stay error-free, including
multi-target (`MOVE A TO B C`), subscripted targets (`MOVE A TO B(I)`),
literals, figurative constants, and `MOVE CORRESPONDING`. A missing **source**
(`MOVE TO X`) is deliberately *not* flagged: it is indistinguishable from stray
`*>`-comment / `REPLACE` pseudo-text the preprocessor does not yet strip
(`normalize_fixed_format` leaves `*>` inline comments in place), and an earlier
missing-source check faulted a valid shamrice program
(`read_specific_cmd_line_args.cbl`, whose line-25 `*>` comment contains the
word "move to"). Pinned by `tests/unit/test_move_malformed_diagnostics.py`.
The stricter check revealed three NIST programs that were passing the
error-free guarantee *only* through this silent acceptance, now strict-xfail
`KNOWN_ISSUES` in `tests/integration/test_nist_cobol85_support.py`: `SM206A`
(`COPY REPLACING` pseudo-text with a bare `MOVE` token leaks in), `SM208A`
(30x `REPLACE` + `==...==` pseudo-text leaks in as `MOVE "*" AO ...` /
`==MOVE "FAIL" TO==`), and `NC205A` (a continuation-line bug that shatters the
split literal `-999.777` into `- 9 9 9 . 7 7 7`, the embedded `.` truncating
the MOVE source — a preprocessing defect, filed separately).

**ON SIZE ERROR / NOT ON SIZE ERROR bodies (`_utils.py::_parse_size_error_stmts`,
audit 2026-07-07 H1):** handler bodies dispatch through the statement
registry (same mechanism as `collect_clause_stmts` for IO clauses), so any
verb — PERFORM, CALL, IF, nested arithmetic — is captured, registered as an
AST child via the model's `_set_clause`, and serialized. Before 2026-07-07
only DISPLAY and MOVE were mini-parsed inline; every other verb was skipped
token-by-token and the handler vanished with `errors=0`. Termination: period
(consumed), `NOT` / scope terminators / control-flow boundaries (not
consumed), or a nested parser consuming the sentence period. Pinned by
`tests/regression/test_tier4_audit_remediations.py::TestH1SizeErrorBodiesKeepAllVerbs`.

**PERFORM VARYING ... AFTER (`perform_parser.py`, audit 2026-07-07 H2):**
`_parse_varying_clause` collects the UNTIL condition via
`_collect_until_expression` (no inline-body parsing), then
`_parse_after_clauses` parses each `AFTER var FROM x BY y [UNTIL cond]`
dimension into `PerformStatement.after_clauses`, then the inline body is
parsed. `_collect_until_condition_tokens` stops (without consuming) at
`AFTER` so the second dimension is never absorbed into the first UNTIL
condition string — but only when `for_varying=True` (the VARYING call
site): a plain, non-VARYING `PERFORM UNTIL` has no AFTER clause of its own,
so gating the stop on `for_varying` avoids truncating a condition that
happens to contain an `AFTER` token (Copilot review on PR #79 caught the
original unconditional stop). Pinned by `::TestH2PerformVaryingAfter`.

**ENVIRONMENT division SELECT clauses (`environment.py`, audit 2026-07-07
H4/H5):** SELECT parsing captures ALTERNATE RECORD KEY (repeatable, WITH
DUPLICATES), PADDING CHARACTER, RESERVE n AREAS, SHARING WITH, LOCK MODE
(LOCK ON / WITH ROLLBACK), PASSWORD, RECORD DELIMITER (disambiguated from
RECORD KEY), and a second FILE STATUS (VSAM) variable — all mapped onto the
`SelectStatement` model fields that already existed. `assign_device_type`
is populated for device words and IBM `UT-`/`UR-`/`DA-` prefixed names.
Unknown SELECT clause tokens produce an "Unparsed token ... in SELECT"
warning instead of a silent `consume()`. The ASSIGN collector stops at the
shared `_SELECT_CLAUSE_KEYWORDS` set (previously it swallowed unknown
following clauses into `assign_to`). `DECIMAL-POINT IS COMMA` in
SPECIAL-NAMES emits a warning that the clause is recorded but not honored
by the lexer (H4). All division parsers can reach the host warning channel:
`BaseDivisionParser.host` is set by the division loop (`parser.py`).

# Silent-Drop Audit (2026-07-08)

Three more instances of the "no boundary check → swallows the following
statement" bug class (same family as the 2026-07-06 INSPECT/STRING/UNSTRING
fixes), found by re-auditing every statement parser's clause-collection loop:

* **`sort_merge_parsers.py`:** SORT's and MERGE's "remaining clauses" loop
  recognized only a fixed keyword list (`WITH`/`COLLATING`/`USING`/`GIVING`/
  `INPUT`/`OUTPUT`); any other token fell to an `else: consume()` fallback
  with no boundary check, so `SORT f ... GIVING g` immediately followed by
  another un-punctuated statement had that statement's tokens silently
  folded into the SORT/MERGE clause loop. Both loops now call the shared
  `is_statement_boundary()` (from `_utils.py`) right after the period check
  and `break` instead of falling through to `else`.
* **`entry_parser.py`:** `_parse_using_clause`'s fallback branch
  (`else: stmt.add_using_parameter(next_token.value)`) accepted *any* token
  as a USING parameter, including a following statement's verb and operand
  tokens when no period terminated the ENTRY statement. Now checks
  `is_statement_boundary()` before falling through to the catch-all.
* **`call_parser.py`:** `_parse_nested_stmts` (used for ON EXCEPTION / NOT ON
  EXCEPTION / ON OVERFLOW handler bodies) silently consumed one token at a
  time when the registry had no parser for a verb — unlike the identical
  situation at the top level of PROCEDURE DIVISION, which has emitted an
  "Unsupported statement" warning since the 2026-07-07 C2 fix. Added
  `_warn_and_skip_handler_statement`, mirroring
  `ProcedureDivisionParser._warn_unsupported_statement` /
  `_skip_to_next_statement`: one warning per dropped statement (reached via
  `get_parse_context(stream).host.add_warning`), then the tokens are skipped
  up to the next statement boundary in one pass (not one warning per token).

Pinned by `tests/regression/test_tier5_silent_drip_audit.py`.

# Silent-Drop Audit (2026-07-09)

Further instances found by re-auditing the DATA division and the
statement parsers prior sweeps had not covered in depth. All pinned by
`tests/regression/test_tier6_silent_drop_audit.py`; full report
`reports/audit-2026-07-09.md`.

* **OCCURS `ASCENDING/DESCENDING KEY` (`data.py` + `_data_fast.pyx`):** the
  OCCURS parser jumped from the DEPENDING check straight to `INDEXED`, so a
  KEY clause in the standard position (between DEPENDING and INDEXED BY) was
  dropped *and* pushed the following `INDEXED BY` into the clause loop's
  `else: consume()`, losing the index too. Now parses one-or-more
  `{ASCENDING|DESCENDING} KEY [IS] k1 [k2 ...]` clauses (repeatable) before
  `INDEXED BY`, and `INDEXED BY` collects **all** index names. See
  `OccursClause.key_clauses` / `index_names` in [ast-models.md](ast-models.md).
* **`REWRITE ... FROM` (`rewrite_parser.py`):** the FROM source was consumed
  and discarded (`IORewriteStatement` had no field). Now stored in
  `from_clause` (identifier or literal), mirroring `IOWriteStatement`.
* **`START ... KEY IS <data-name>` (`start_parser.py`):** the KEY data-name —
  the key the browse is positioned on — was consumed and discarded. Now stored
  in `IOStartStatement.key_name` (the pre-existing `key_condition` kept the
  operator only).
* **`ACCEPT ... FROM DATE/TIME <format>` (`accept_parser.py`):** a trailing
  format phrase (`YYYYMMDD`, `YYYYDDD`) was left in the stream and re-parsed by
  the procedure parser as a **phantom paragraph**. Now folded into
  `from_source`. `ACCEPT`/`UNLOCK` also guard their operand with
  `is_statement_boundary()` so a missing operand no longer eats the next
  statement's verb.
* **`STOP RUN RETURNING <x>` / `STOP <numeric>` (`stop_parser.py`):** the
  return code was dropped; now stored in `StopStatement.returning`, and a bare
  numeric STOP operand is captured as `stop_type`.
* **DATA division drop warning (`data.py`):** the clause loop's
  `else: consume()` now emits an "Unparsed token ... in data item" warning for
  meaningful tokens (skips NEWLINE/WHITESPACE/COMMENT/CONTINUATION), symmetric
  with `environment.py`'s `_warn_dropped_select_token`. Unsupported data-item
  clauses (GROUP-USAGE, VOLATILE, DYNAMIC LENGTH, ...) are no longer fully
  silent.

# Silent-Drop Audit: unsupported-verb boundary gap (2026-07-08 residual fix)

The 2026-07-07 C2 fix (`_warn_unsupported_statement`) only fires when the
PROCEDURE DIVISION's top-level dispatch loop *sees* the offending token
directly — which requires a period to hand control back to that loop at the
right place. A statement with no trailing period, immediately followed by an
unsupported (or simply un-added) verb, never reaches that loop at the right
spot: the *previous* statement's own trailing-token loop (MOVE's target
list, the arithmetic operand collector, etc.) runs first and decides for
itself, via `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` (`_utils.py`,
consulted through `is_statement_boundary()` or an equivalent inline check),
whether the next token starts a new statement. Those two sets were missing
several verbs `ProcedureDivisionParser._UNSUPPORTED_VERBS` already knew how
to *label* — so once the wrongly-shaped following statement reached the
label logic, it was already too late: its tokens had been silently absorbed
as bogus operands of the previous statement, with `result.success is True`
and `warnings == []`.

Confirmed via a `MOVE A TO B` (no period) probe, sweeping every verb whose
lexer `TokenType` or `STATEMENT_KEYWORDS` string was missing from the
boundary sets:

* **DISABLE, ENABLE, PURGE, RAISE, READY, RECEIVE, RESET, RESUME, SEND,
  SERVICE, TRANSFORM** — already in `_UNSUPPORTED_VERBS`'s warning-message
  list, but absent from `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS`.
* **EXECUTE, EXHIBIT, INVOKE** — the *string* was already in
  `STATEMENT_KEYWORDS`, but the lexer's dedicated `TokenType` for each was
  missing from `STATEMENT_TOKEN_TYPES`. This mattered because
  `MoveStatementParser`'s target loop checks `token.type in
  _STOP_TOKEN_TYPES` **before** falling back to a value check that is itself
  gated on `token.type == TokenType.IDENTIFIER` — a keyword-typed token
  (never `IDENTIFIER`) skips both checks and falls into the loop's
  "skip non-identifier noise" branch, discarded with zero trace.
* **COMMIT, ROLLBACK** — *do* have registered parsers
  (`CommitStatementParser`/`RollbackStatementParser`), yet were absent from
  both boundary sets. A period-less statement directly followed by a
  legally-formed `COMMIT.`/`ROLLBACK.` lost the entire statement — worse
  than the unsupported-verb case, since this one was fully supported and
  still vanished.
* **CHAIN, ENTER, EXAMINE, GOTO (the fused one-word spelling only — `GO TO`
  as two words is unaffected and already worked via the `GO` entry),
  INITIATE, NOTE, RECOVER, SUPPRESS, TERMINATE** — real (mostly
  obsolete/Report-Writer) COBOL verbs with dedicated lexer `TokenType`s and
  no registered parser, previously absent from every set that tracks
  "known verb" in this file.

Fix: `STATEMENT_TOKEN_TYPES` gained the `TokenType` member for every verb
above that has one; `STATEMENT_KEYWORDS` gained the string for every verb
above (including `PURGE`/`RAISE`/`RESUME`, which the lexer tokenizes as plain
`IDENTIFIER` with no dedicated `TokenType` at all — see below for why the
`STATEMENT_KEYWORDS` addition alone wasn't sufficient for these three).
`ProcedureDivisionParser._UNSUPPORTED_VERBS` gained `CHAIN`, `ENTER`,
`EXAMINE`, `GOTO`, `INITIATE`, `NOTE`, `RECOVER`, `SUPPRESS`, `TERMINATE` so
these get the specific "Unsupported statement 'X'" message instead of the
generic "Unparsed tokens" one; `COMMIT`/`ROLLBACK` were deliberately **not**
added there since they now dispatch to their real parsers instead of ever
reaching the warn-and-skip path. Pure clause words that are tokenized
distinctly but never start a statement (`ON`, `OTHERWISE`, `NEXT`, `THEN`,
scope-terminator tokens like `END-INVOKE`/`END-SET`, and `DISPLAY-1`'s
USAGE-clause token) were deliberately left out of both sets.

**Second wave — ten list-collecting loops never consulted the boundary sets
at all.** `PURGE`/`RAISE`/`RESUME` have no dedicated `TokenType`, so they are
lexically indistinguishable from a data-name and only a *value* check
(`STATEMENT_KEYWORDS`) can catch them — which is exactly what
`MoveStatementParser`'s target loop and `parse_arithmetic_operands()` already
consult. But two further, independent probes found ten *other* loops that
never made that check, so these three verbs kept vanishing even after the
`STATEMENT_KEYWORDS` fix above:

- Leading with `DISPLAY`/`CANCEL`/`SET`/`OPEN`/`CLOSE`/`INITIALIZE` instead
  of `MOVE` found six statement parsers whose *main* trailing loop collects
  an open-ended list of bare `IDENTIFIER` tokens and never consults
  `STATEMENT_KEYWORDS`/`is_statement_boundary` at all:
  - `display_parser.py` — the DISPLAY item-collection loop accepted any
    `STRING_LITERAL`/`IDENTIFIER`/`NUMERIC_LITERAL` token as an item and
    only checked `SCOPE_TERMINATORS` by value (never `STATEMENT_KEYWORDS`).
  - `simple_statement_parsers.py::CancelStatementParser` — the program-name
    loop accepted any `IDENTIFIER`/`STRING_LITERAL`.
  - `set_parser.py` — the `SET id-1 [id-2 ...] TO value` target loop.
  - `open_parser.py` / `close_parser.py` — the multi-file-name loops (`OPEN
    INPUT A B C`, `CLOSE A B C`).
  - `initialize_inspect_parsers.py::InitializeStatementParser` — the
    `INITIALIZE id-1 [id-2 ...]` target loop.
- Leading with `STRING`/`UNSTRING`/`SORT`/`MERGE`/`CALL`/`ENTRY` instead
  (these statements' own *outer* loop already calls `is_statement_boundary()`
  from the 2026-07-06/2026-07-08 fixes, so `STRING`/`CALL`/`ENTRY` were
  already clean) found three more instances hiding in separate nested
  **helper** loops with their own hand-rolled boundary keyword list that
  predates or bypasses that outer-loop check:
  - `string_unstring_parsers.py::UnstringStatementParser._parse_into_targets`
    — the `INTO target-1 [target-2 ...]` list.
  - `sort_merge_parsers.py::_parse_keys` (shared by SORT/MERGE) — the
    `{ASCENDING|DESCENDING} KEY field-1 [field-2 ...]` list.
  - `sort_merge_parsers.py::_parse_file_list` (shared by SORT/MERGE) — the
    `USING`/`GIVING` file-name lists.
- A follow-up registry walk (every parser in `_create_statement_registry()`,
  checked by eye for an open bare-`IDENTIFIER`-list shape and, where
  plausible, verified behaviorally) found one more:
  `initialize_inspect_parsers.py::InspectStatementParser._parse_tallying`
  — the `counter-1 FOR {CHARACTERS|ALL|LEADING} [value] ...` list treated
  any bare `IDENTIFIER` as the start of a new TALLYING counter clause with
  **no boundary check at all** (unlike its sibling `_parse_replacing`, which
  only accepts a token whose *value* is a REPLACING category keyword —
  never an arbitrary `IDENTIFIER` — so it was never at risk). The rest of
  the registry is type-excluded (`TokenType`-carrying verbs) or reads a
  fixed number of single tokens per clause (`ACCEPT`, `UNLOCK`, `REWRITE`,
  `START`, `DELETE`, `READ`, `WRITE`, `RETURN`'s AT END skip-loop, `USE`,
  `GO`'s computed-target scan, `SEARCH`'s WHEN-condition collector, `ADD`/
  `SUBTRACT`/`MULTIPLY`/`DIVIDE`/`COMPUTE`, `PERFORM`'s target/THRU/AFTER
  fields, `XmlJsonStatementParser`) — none of these are an open list of
  bare identifiers, and each already gates on `STATEMENT_KEYWORDS`/
  `is_statement_boundary` or a required literal keyword before consuming a
  value, so they were not re-verified individually beyond that check.

Each of the ten now breaks on `is_statement_boundary(token)` when the token
is a plain `IDENTIFIER`, immediately before accepting it as a list item —
the same guard `MoveStatementParser`'s value-check branch already applies.
(`TokenType`-carrying verbs were already safe in the type-only loops above,
since their type never matches `STRING_LITERAL`/`IDENTIFIER`/
`NUMERIC_LITERAL`; `display_parser.py` no longer needs its own
`SCOPE_TERMINATORS` check, since `is_statement_boundary()` subsumes it.) This
two-wave shape — fix the shared boundary sets, then discover that several
loops don't consult the shared sets at all — is exactly the same failure
mode `is_statement_boundary()` was introduced to eliminate on 2026-07-06;
each new statement parser (or new helper loop inside one) must call it
rather than re-deriving its own boundary list. Pinned by
`tests/regression/test_tier7_unsupported_verb_boundary.py`.

**Third finding — `PERFORM paragraph-name UNTIL condition` had no boundary
check at all, for *any* verb.** Distinct from the `PURGE`/`RAISE`/`RESUME`
gap above (and not caused by it): `PerformStatementParser
._parse_until_condition_only` — used only by the out-of-line form with an
explicit target paragraph and no inline body (`PERFORM SOME-PARA UNTIL
cond`, as opposed to the inline `PERFORM UNTIL cond ... END-PERFORM` form,
which already went through `_collect_until_condition_tokens` and was safe)
— stopped only at a literal period or `END-PERFORM`. A period-less `PERFORM
... UNTIL cond` therefore swallowed **every remaining token in the
program** into the condition string, including entire well-formed
statements — verified with a trailing `DISPLAY 'HELLO'` / `STOP RUN` pair,
both of which vanished from the AST (`result.success == True`, `warnings ==
[]`, one `PerformStatement` node left holding the whole rest of the program
as `until_condition.operands`). Fixed by adding the same
`STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` check
`_collect_until_condition_tokens` already used. Pinned by
`TestPerformUntilConditionNoLongerSwallowsRest` in
`tests/regression/test_tier7_unsupported_verb_boundary.py`.

**Fourth finding — `EVALUATE` had two independent unguarded loops, one of
which could annex an entire unrelated later statement.**
`EvaluateStatementParser._parse_subjects` (the subject-list loop before the
first `WHEN`) had no boundary check at all, so a malformed/period-less
`EVALUATE` with no `WHEN` clause folded a following verb straight into
`stmt.subjects` as free text — same shape as the `PURGE`/`RAISE`/`RESUME`
list-loop gap above, fixed the same way (`self._is_statement_keyword()`,
already used by the sibling `_parse_selectors`, added to `_parse_subjects`
too). More severe: the *outer* clause-scan loop (between `subject_count =
self._parse_subjects(...)` and the `WHEN`-clause dispatch) treated any token
that wasn't literally `WHEN` or `END-EVALUATE` as noise to skip past. A
malformed `EVALUATE` therefore consumed forward past entire intervening
statements — verified with a trailing `MOVE 1 TO WS-Y` followed by a second,
well-formed `EVALUATE WS-Y ... WHEN 1 ... END-EVALUATE` — until it hit the
literal string `"WHEN"` *inside that second EVALUATE* and annexed it as its
own clause, silently erasing the `MoveStatement` and folding two EVALUATEs
into one, with **zero errors and zero warnings** (the missing-WHEN /
missing-END-EVALUATE errors that normally flag a malformed EVALUATE never
fired, because the loop found *a* WHEN — just the wrong one's). Fixed by
adding the same `self._is_statement_keyword()` break to the outer loop's
`token_val_upper != "WHEN"` branch. Pinned by
`TestEvaluateSubjectsAndClauseScanDoNotSwallowFollowingContent` in
`tests/regression/test_tier7_unsupported_verb_boundary.py`.

Verified adjacent, not vulnerable: `IfStatementParser`'s condition collector
(probed with `IF ... PURGE ...` variants, with and without `THEN`/`END-IF`)
already stops correctly. `EvaluateStatementParser._parse_selectors` (the
per-`WHEN` selector list) already called `self._is_statement_keyword()`
before this fix — only `_parse_subjects` and the outer clause-scan loop were
missing it.

# open-findings.md HIGH-severity fixes (2026-07-09, H1-H8)

Eight HIGH findings from `reports/open-findings.md`'s 2026-07-08
re-verification pass, all fixed and pinned by
`tests/regression/test_open_findings_high_regressions.py` (one test class
per finding ID). Full per-finding writeup in `CHANGELOG.md`'s Unreleased →
Fixed section; only the parser-relevant ones are summarized here (H5
MoveTypeChecker → [analysis.md](analysis.md), H6 PathResolver →
[preprocessing.md](preprocessing.md), H7 lexer warning →
[lexer.md](lexer.md) above).

* **H1 — `set_parser.py`:** the `SET ADDRESS OF x TO y` target-collection
  loop only accepted `IDENTIFIER`/`STRING_LITERAL` tokens; `OF` lexes as
  its own dedicated `TokenType.OF`, not `IDENTIFIER`, so the loop's
  `else: break` fired immediately on `OF` and never reached the pointer/
  `TO`/target tokens (`targets: [], set_type: null, value: null`). `OF` is
  now explicitly recognized and skipped in that loop.
* **H2 — `arithmetic_parsers.py`:** `paren_depth` in the COMPUTE
  expression loop was only used to gate the `paren_depth == 0` boundary
  check; once left non-zero by a stray `(` with no matching `)`, the
  boundary check never re-armed for the rest of the token stream, so a
  well-formed following statement got silently folded into the expression
  string. A new check (`if paren_depth != 0 and is_statement_boundary(token):
  break`) now applies *regardless* of `paren_depth`, and a final
  `if paren_depth != 0` check after the loop reports "COMPUTE statement
  has unbalanced parentheses in expression" instead of accepting silently.
  This is additive to the pre-existing 2026-07-06 COMPUTE-swallow fix
  documented above (that fix covered the `paren_depth == 0` case; this one
  covers the never-returns-to-zero case the `paren_depth == 0` gate
  couldn't reach).
* **H3/H4 — `perform_parser.py`:** the TIMES-clause lookahead after a
  PERFORM target paragraph speculatively consumed a following
  `IDENTIFIER`/`NUMERIC_LITERAL` as a candidate TIMES value and discarded
  it with **zero trace** (no warning, no log) if `TIMES`/`TIME` didn't
  follow — worse than the sibling boundary-swallow bugs elsewhere in this
  file, since even `errors=[]`/`warnings=[]` gave no signal. A new
  `_peek_next_meaningful()` helper looks past whitespace/comment/newline/
  continuation tokens *before* committing to consume the candidate; if it
  isn't a valid TIMES clause, `_warn_stray_trailing_token()` emits a
  warning identifying the discarded token instead of silently dropping
  it. Separately, all 5 bare `except ParseError: pass` sites in this file
  (VARYING/UNTIL/inline-body parsing) had **no logging at all**, unlike
  the shared `try_parse_nested_statement` helper in `_utils.py` (see M9 in
  `reports/open-findings.md`) — all 5 now log the suppressed exception at
  DEBUG.
* **H8 — `close_parser.py`:** `REEL`/`UNIT`/`WITH` per-file options were
  parsed via a single if/elif chain (applied at most once per file), and
  the outer per-file loop required the next token to be a plain
  `IDENTIFIER` to continue — so `CLOSE F REEL WITH NO REWIND.` consumed
  `REEL`, set `reel: true`, then hit `WITH` (not an `IDENTIFIER`) and
  ended the whole per-file loop, leaving `WITH NO REWIND` dangling
  (warn-masked by the generic "unparsed tokens" fallback, `no_rewind`
  silently lost). The option parse is now a `while True` loop that keeps
  applying options until none match, so combined options on one file (and
  across multiple files in one `CLOSE`) all survive together.
* **H9 — fixed in a 2026-07-09 follow-up pass (`_utils.py`,
  `display_parser.py`, `move_parser.py`, `arithmetic_parsers.py`,
  `string_unstring_parsers.py`, `initialize_inspect_parsers.py`,
  `core/interfaces.py`, `parsers/divisions/procedure.py`):** a distinct,
  more general silent-drop found while verifying H7's "unclosed IF"
  sub-claim — a statement with no terminating period, immediately followed
  by what should be a new paragraph header, caused the paragraph name to
  be absorbed as a trailing operand of the preceding statement instead of
  starting a new paragraph (`errors=[], warnings=[]`; confirmed by direct
  repro in `DISPLAY`'s item list, `MOVE`'s target list, `COMPUTE`'s
  expression capture, `STRING`'s operand list, `UNSTRING`'s `INTO` target
  list, and `INSPECT`'s `TALLYING` counter-name loop / outer "consume to
  period" trailer — none of which is `is_statement_boundary()` territory,
  since an ordinary user-defined paragraph name is not a known verb). The
  raw grammar genuinely cannot disambiguate "last operand of an
  unterminated statement" from "next paragraph name" — both are just
  `IDENTIFIER` then `PERIOD` — so a new `looks_like_paragraph_boundary()`
  predicate (`_utils.py`) mirrors COBOL's own disambiguator instead:
  the candidate identifier only counts as a boundary when it (a) starts
  its own source line (checked via `previous_meaningful_token`'s
  `.location.line`, the same mechanism `call_parser.py`'s handler-body
  termination already relies on), (b) is immediately followed by a period
  or `SECTION`, and (c) is not a name declared in the DATA DIVISION.
  Condition (c) exists specifically so a legitimately wrapped
  continuation-line operand (`DISPLAY\n    WS-X.`) isn't misread as a
  paragraph header just because it opens its line; the DATA DIVISION name
  set is computed once per PROCEDURE DIVISION parse
  (`ProcedureDivisionParser._collect_known_data_names`) and threaded to
  statement parsers via a new `ParseContext.known_data_names` field. When
  the predicate fires, `warn_paragraph_boundary_swallowed()` records a
  warning (matching the H7/H8 "warn, don't silently reinterpret"
  precedent) before the loop breaks; the existing top-level
  `_is_paragraph_or_section_start()` check then picks the identifier up as
  a normal new paragraph — no separate paragraph-name pre-scan was needed.
  `INSPECT`'s `TALLYING` loop is a special case: its own inner check
  breaks without warning, because the outer "consume to period" trailer in
  `InspectStatementParser.parse()` re-checks the same un-consumed token and
  is the one that records the warning — that trailer is also the *sole*
  fix point for `INSPECT ... REPLACING`, whose own `REPLACING` clause loop
  already stopped safely on an unrecognized token but left it for the
  trailer's unconditional `token_stream.consume()` fallback to silently
  discard. Same split for `UNSTRING`: the outer clause-dispatch loop owns
  the warning, `_parse_into_targets`'s inner check only breaks.
  **Deliberately scoped, not universal:** only the six statement parsers
  confirmed by direct repro were touched; `is_statement_boundary()` itself
  (used by 16 call sites, including CALL/SORT/OPEN/INITIALIZE) was left
  untouched rather than overloaded with this check, since those sites have
  no demonstrated instance of this bug and a bare trailing identifier
  before a period is normal in several of them — extending coverage there
  needs its own repro-first pass. **Known residual ambiguity:** an
  undeclared identifier (e.g. from an unexpanded `COPY` member) alone on
  its own continuation line is inherently indistinguishable from a real
  paragraph name by syntax alone, and is treated as a boundary (with a
  warning) — the same class of gap `parse_cobol()` already has whenever
  copybooks aren't expanded. Pinned by
  `tests/regression/test_open_findings_high_regressions.py::TestH9MissingPeriodParagraphBoundary`
  (9 tests: one repro per fixed statement/clause shape, plus two guard
  cases for the DATA DIVISION cross-check).

# Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser` (`parse()` + `matches()`)
2. Register it in `create_statement_registry()` (`parsers/divisions/procedure_registry.py` — the builder `ProcedureDivisionParser` uses)
3. Add a `TokenType` entry in `lexer.py` if the verb is not yet a keyword
4. Add AST node(s) in the appropriate `cobolparser/models/statements/<category>.py` with `to_dict()`; use `ASTNodeFactory` from `core/ast_factory.py`
5. Export from `cobolparser/parsers/statements/__init__.py` and `cobolparser/models/statements/__init__.py`

# Configuration Classes

| Class | Purpose |
|-------|---------|
| `ErrorRecoveryMode` | `FAIL_FAST` (default) or `COLLECT_ALL` |
| `MemoryConfiguration` | `max_memory_mb` (64–8192), `enable_streaming`, `chunk_size_kb` |
| `SerializationConfig` | `include_metadata: bool` |
| `DialectType` | Enum — `IBM_ENTERPRISE`, others planned |
| `ParseStatistics` | Wall-clock timings, token counts, node counts |

# See Also

* [lexer.md](lexer.md) — upstream tokenisation
* [ast-models.md](ast-models.md) — what `ParseResult.ast` contains
* [preprocessing.md](preprocessing.md) — input normalisation
