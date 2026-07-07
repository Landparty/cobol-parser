---
type: Module
title: Parser
description: CobolParser, DivisionParserFactory, StatementParserRegistry — converts Token stream to ParseResult.
tags: [parser, ast, division, statement, registry]
timestamp: 2026-07-06T00:00:00Z
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
| `environment.py` | ENVIRONMENT DIVISION |
| `data.py` | DATA DIVISION |
| `procedure.py` | PROCEDURE DIVISION — hosts `StatementParserRegistry` |

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

# Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser` (`parse()` + `matches()`)
2. Register it in `ProcedureDivisionParser` (or via `StatementParserRegistry`)
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
