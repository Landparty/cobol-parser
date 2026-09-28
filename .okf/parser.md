---
type: Module
title: Parser
description: CobolParser, DivisionParserFactory, StatementParserRegistry — converts Token stream to ParseResult.
tags: [parser, ast, division, statement, registry]
timestamp: 2026-09-28T00:00:00Z
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

`statistics` is an independent **snapshot** (2026-08-12, audit P-B3):
`_create_result` hands each `ParseResult` `self.statistics.copy()`
(`ParseStatistics.copy()`, `plugins/core.py`) rather than the parser's live
object, which the next `parse()` call `reset()`s in place — previously
reusing one `CobolParser` clobbered earlier results' statistics.

Every return path fills the statistics (2026-09-28): `lines_parsed` /
`lines_processed` are set before lexing, `tokens_processed` right after it,
and `_create_result` stops the clock -- a FAIL_FAST lexer error, a
propagated `ParseError` or the safety net used to return `0` lines and
`parse_time_seconds == 0`. `_begin_parse()` holds the per-parse reset, and
`parse_file()` runs it before recording a `File error`, which previously
came back alongside the errors, warnings and statistics of whatever the
instance had parsed last.

`CobolParser(..., initial_warnings=[...])` (2026-08-14, consumption fixed
2026-08-15 per Copilot review on PR #153) seeds `self.warnings` with
caller-supplied diagnostics at the top of the *first* `parse()` call, after
`self.warnings.clear()` — for warnings a caller already collected before
constructing the parser (`parse_cobol()`'s own pre-normalization of
fixed-format source runs before its `CobolParser` instance exists; see
[preprocessing.md](preprocessing.md)'s "Column 73+ overflow warning").
Consumed (cleared) immediately after being applied, so reusing one
`CobolParser` instance across multiple `parse()` calls only attributes
those initial warnings to the first call, not every later, unrelated one —
the same reuse hazard `statistics.copy()` above was fixed for.

`warnings` is the "recognized but degraded" channel (2026-07-07): the parser
populates it when it skips an unsupported verb (no registered statement
parser; since the 2026-09-02 statement-coverage audit that is only
`EXECUTE`/`GOTO`/`RECOVER`, see
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
  ├─ TokenStream(tokens - COMMENT)     # lookahead abstraction; `*>` comments dropped
  └─ DivisionParserFactory
       ├─ IdentificationDivisionParser
       ├─ EnvironmentDivisionParser
       ├─ DataDivisionParser
       └─ ProcedureDivisionParser
            └─ StatementParserRegistry  (first-match dispatch)
                 └─ 72 statement parsers (every COBOL verb)
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
| `data.py` | DATA DIVISION — section scan, level-number hierarchy, AST node; entry parsing delegated to the three `data_*.py` collaborators below. `_build_data_hierarchy` ends with `propagate_group_usage_and_sign()` (2026-09-28): a group's USAGE / SIGN is pushed onto subordinates with none of their own (IBM rule). Explicitness is `CobolDataItem.usage_explicit`, set by `set_usage()` — which both the pure-Python and `_data_fast` clause loops call, so the `.pyx` needed no change |
| `data_clauses.py` | `DataItemClauseParser` — data-item entries + PICTURE/VALUE/USAGE/OCCURS/... clauses; owns the optional `_data_fast` Cython fast-path invocation |
| `data_file_description.py` | `FileDescriptionClauseParser` — FD/SD file-description clause capture (BLOCK/RECORD/LABEL/...) |
| `data_report_description.py` | `ReportDescriptionClauseParser` — REPORT SECTION `RD` clause capture (CODE/CONTROLS/PAGE LIMIT/HEADING/FIRST-LAST DETAIL/FOOTING/GLOBAL), 2026-09-02 |
| `data_special_entries.py` | `SpecialEntryParser` — level-88 condition names, level-66 RENAMES, data-division EXEC SQL blocks |
| `procedure.py` | PROCEDURE DIVISION — paragraph/section dispatch loop, ParseContext attachment, AST node; hosts the shared `StatementParserRegistry` cache; supporting logic delegated to the three `procedure_*.py` collaborators below |
| `procedure_registry.py` | `create_statement_registry()` — registers all 72 statement parsers in first-match priority order (new statement parsers register here); order invariant pinned by `tests/unit/test_procedure_registry_dispatch_order.py`; every registered parser also needs a fixture in `tests/regression/test_swallow_sweep.py` |
| `procedure_boundaries.py` | `is_paragraph_or_section_start` / `is_section_marker` / `is_statement_keyword` lookahead predicates |
| `procedure_recovery.py` | `StatementRecoveryHandler` — unsupported-statement warnings, FAIL_FAST/COLLECT_ALL error recording, stream resynchronization; owns `STRAY_MARKERS` / `UNSUPPORTED_VERBS` (aliased as `ProcedureDivisionParser._STRAY_MARKERS` / `._UNSUPPORTED_VERBS`) |

**Cython callback surface (2026-07-15 refactor):** `DataDivisionParser` keeps
`_parse_picture_clause` / `_parse_value_clause` / `_parse_usage_clause` (and
`_parse_data_item`) as delegating wrappers with their historical names and
signatures — the compiled `_data_fast` extension receives the division parser
as `parser_self` and calls those three back by name. New clause logic goes in
`DataItemClauseParser`; the wrappers must stay.

**`_data_fast` signature-drift guard (`data_clauses.py`, 2026-09-05):** the
callback surface above is only half the contract; the other half is the
19-argument positional call `parse_data_item` makes into
`parse_data_item_clauses_fast`. Because the extension is compiled separately
from its caller, a stale *build* (in-place `.so` older than the tree, cached
`build/`, an installed wheel shadowing the source) leaves a binary whose arity
no longer matches. `try/except ImportError` does not catch that: the import
succeeds and the call raises `TypeError` from the middle of every
data-description entry, which `parser.py`'s broad `except Exception` recorded
as a generic line-1 error and recovered from by abandoning the division --
losing the DATA *and* PROCEDURE divisions. Reported on Python 3.14 against an
18-parameter build.

`_data_fast_usable()` now probes the compiled helper once at import (empty
token list -> the clause loop never runs -> it returns `pos` untouched) and, on
mismatch, sets `_HAS_DATA_FAST = False` and names the rebuild via
`logger.warning` (never `warnings.warn` — at import time that would break
`import cobolparser` under `-W error`). **Adding a parameter to `parse_data_item_clauses_fast` means updating
`_DATA_FAST_ARG_COUNT` alongside the call site.** Full mechanics in
[lexer.md](lexer.md) ("Signature-drift guard");
`tests/regression/test_data_fast_signature_drift.py`.

**SCREEN/COMMUNICATION SECTION recognition (`data.py`, 2026-08-13) and REPORT SECTION parsing (2026-09-02):**
`DataDivisionParser` recognizes FILE, WORKING-STORAGE, LOCAL-STORAGE,
LINKAGE and -- since 2026-09-02 -- REPORT as real sections. SCREEN SECTION
and COMMUNICATION SECTION have their own grammars (screen-field clauses, CD
entries) that are not modeled. Their headers are still recognized as
section *boundaries* (`_SECTION_BREAK_HEADERS` / `_UNSUPPORTED_SECTION_HEADERS`
in `parse_division`'s dispatch and `_parse_section`'s break check) so an
in-progress section scan -- almost always WORKING-STORAGE -- stops there
instead of silently absorbing the header token-by-token and then
misparsing the following section's own level-numbered content as bogus
nested data items (a SCREEN SECTION `COLUMN 5` clause previously produced a
spurious `CobolDataItem` literally named `COLUMN`). `DataDivisionParser._skip_section()`
consumes the header (`NAME [SECTION] [.]`) and discards the body up to the
next section/division boundary -- the same boundary logic `_parse_section`
uses -- then registers an empty, distinctly-named `CobolSection`
(`SCREEN`/`COMMUNICATION`) plus a `has_screen`/`has_communication`
division-metadata flag, so downstream consumers can tell the section was
present without seeing corrupted WORKING-STORAGE data. Known tradeoff: a
data item declared inside or directly after one of these sections with no
section header of its own (e.g. a COMMUNICATION SECTION CD's record, or a
bare `01` placed right after it) is discarded along with the rest of the
unmodeled body -- it does not survive into WORKING-STORAGE (the old,
corrupting behavior) or anywhere else. Because that loss would otherwise be
silent (`errors=0`), `_skip_section` records a `ParseResult.warnings` entry
naming the section -- this repo's established "recognized but degraded"
convention (see the Silent-Drop Audit entries below) -- rather than letting
`errors=0, warnings=0` imply a complete AST.

**REPORT SECTION (2026-09-02, `data.py` + `data_report_description.py` +
`data_clauses.py`):** parsed for real, warning-free, so a Report Writer
program is no longer refused by consumers that treat any warning as
dropped content (mocky-mock's `PARSE_WARNING` gate was the driver). Inside
`_parse_section("REPORT")`, an `RD report-name` entry is consumed and its
clauses captured by `ReportDescriptionClauseParser.parse_rd_clauses` --
`CODE`, `CONTROL(S) [ARE] {FINAL | name ...}`, `PAGE [LIMIT] n [LINES]`,
`HEADING n`, `FIRST DETAIL n`, `LAST DETAIL n`, `FOOTING n`, `GLOBAL` -- into
a JSON-serializable mapping (`{"code", "controls", "page_limit", "heading",
"first_detail", "last_detail", "footing", "is_global", "raw"}`; unclaimed
tokens go to `raw`). Every following 01-level report group carries that
mapping as `metadata["rd_clauses"]` and the report name as
`metadata["rd_report_name"]`. Report groups themselves are ordinary
`CobolDataItem` trees parsed by `DataItemClauseParser.parse_data_item(...,
report_group=True)`: an entry whose level is followed by a clause word
(`01 TYPE IS PAGE HEADING.`, `05 LINE NUMBER IS 1.`, `10 COLUMN 1 PIC X(20)`)
is anonymous (`ANONYMOUS-<level>-<line>`, the existing convention), and the
report-group clauses -- `TYPE [IS] ...`, `LINE [NUMBER] [IS] {n | PLUS n |
NEXT PAGE}...`, `NEXT GROUP [IS] ...`, `COLUMN|COL [NUMBER] [IS] n...`,
`SOURCE [IS] id`, `SUM id... [UPON id...] [RESET [ON] {id | FINAL}]`, `GROUP
[INDICATE]`, `PRESENT WHEN cond` -- land in `metadata["report_clauses"]`
(`type`, `line` (list), `next_group`, `column` (list), `source`, `sum` (list
of `{operands, upon?, reset_on?}`), `group_indicate`, `present_when`).
PICTURE / VALUE / JUSTIFIED / BLANK WHEN ZERO / USAGE use the ordinary
clause branches. The report clause words were added to
`_PICTURE_TERMINATOR_KEYWORDS` so `PIC ZZ9 SOURCE WS-X` stops the picture
scan at `SOURCE` (none of them is a valid picture string, so the addition is
safe everywhere, and the Cython fast path receives the same frozenset). The
fast path bails back to the pure-Python loop on every report clause word, so
`_parse_report_clause` is the single implementation. `NEXT` is
position-shaped only when followed by `PAGE` (`_report_position`) -- `LINE
PLUS 1 NEXT GROUP NEXT PAGE` must not fold `NEXT GROUP` into the LINE list.
`parse_rd_clauses` stops at a LEVEL_NUMBER that begins a group
(`_level_starts_group`) so a missing RD period cannot swallow the first
group. **2026-09-28:** `_report_operands` stops at a LEVEL_NUMBER token only
outside parentheses and not after an operator word
(`_REPORT_OPERATOR_WORDS`) -- a one-/two-digit integer lexes as LEVEL_NUMBER
whatever it means, so `SUM WS-AMT (1)` and `PRESENT WHEN WS-I > 1` used to
end the clause there and the clause loop opened a phantom data item at the
integer. String literals in these operands are re-quoted (`PRESENT WHEN
WS-FLAG = 'Y'`), and SUM operands are grouped per operand
(`_group_report_operands`: `WS-AMT OF WS-GRP ( 3 )` is one entry).
`_report_position` also reads COBOL-85 `LINE integer ON NEXT PAGE` (recorded
as `"5 ON NEXT PAGE"`); the `ON` used to be dropped with a warning and
`NEXT PAGE` misread as an empty NEXT GROUP. Pinned by
`tests/regression/test_oo_report_xml_operand_drops.py`. Pinned by `tests/unit/test_report_section.py`; the 2026-08-13
regression file's REPORT tests now pin the parsed shape and the absence of
any warning, and `tests/samples/report_writer.cbl` is back in
`test_sample_programs.py`'s parametrized list.

`REPORT` (and, less commonly, `COMMUNICATION`/`SCREEN`) doubles as an
ordinary clause word outside a section header — an FD's `REPORT IS
report-name.` clause is exactly this
(`examples/cobol/shamrice/report_test.cbl` line 32). `parse_division`'s
dispatch only routes to `_parse_section("REPORT")` / `_skip_section` when the *next* token is literally
`SECTION` (`DataDivisionParser._next_is_section_keyword`, the same
lookahead `_parse_section`'s own break check already used for these three
headers) — otherwise the bare word falls through to the existing
unknown-token skip, so it can't wrongly discard whatever source follows it
(the same "swallow" bug class this parser has been repeatedly audited for
elsewhere — see the Silent-Drop Audit sections below). Pinned by
`tests/regression/test_screen_report_communication_sections.py` (23 cases),
including end-to-end assertions against `tests/samples/screen_section_io.cbl`,
`report_writer.cbl`, and `communication_module.cbl` (the fixtures that
originally exposed the bug) and the `report_test.cbl` FD-clause collision.

**FD/SD metadata tags on FILE SECTION 01-items (`data.py`, `_parse_section`):**
while scanning under an `FD`/`SD` header, every level-01 item is tagged with
`fd_file_name` (the file name) and, when present, `fd_clauses` (the
`FileDescriptionClauseParser`-structured dict — `record`, `recording_mode`,
`label_records`, `data_records`, ...). A third tag, `fd_record_type` (`"FD"`
or `"SD"`, 2026-08-04), records which keyword declared the file — previously
untracked, since nothing downstream needed the distinction before
`ProgramLayoutIndex` (generators.md) started using it to flag SORT/MERGE work
files as non-mockable rather than treating every FILE SECTION entry as a real
file a program can `OPEN`. Purely additive metadata; no existing behavior
changed. Pinned by
`tests/unit/test_program_layout_index.py::TestFdRecordTypeMetadata`.

**LEVEL_NUMBER-as-literal gotcha (`data.py`):** the lexer types every 1-2
digit integer as `TokenType.LEVEL_NUMBER` regardless of context (even inside
`PIC 9(4)` or after `VALUE`). Any data-division clause that consumes a numeric
must therefore accept `LEVEL_NUMBER` alongside `NUMERIC_LITERAL` —
`_parse_value_clause`, the level-88 value collector, and the OCCURS handlers
all do. `_parse_value_clause` also consumes an optional `IS` and a
`MINUS`/`PLUS` sign token before the literal (`VALUE IS -5`). Regression
suite: `tests/regression/test_numeric_value_clause.py`.

**VALUE ALL (`data_clauses.py`):** `ALL` lexes as a `FIGURATIVE_CONSTANT`, so
`parse_value_clause` special-cases it before the plain-literal branch:
`VALUE ALL '='` → `value_clause='ALL "="'`, `VALUE ALL ZEROS` →
`'ALL ZEROS'` (a bare trailing `ALL` still returns `"ALL"`). The returned
string round-trips as legal COBOL — downstream consumers (mockymock's
working-storage reset) splice it into `MOVE <value> TO <item>`. Regression
suite: `tests/regression/test_value_all_clause.py`.

A level-88 `VALUE ALL 'X'` (`data_special_entries.py`, 2026-09-28) is one
value in the same spelling: `values == ['ALL "X"']` (`ALL SPACES` for a
figurative operand), not `['ALL', 'X']`. Consumers that know the field's
width fill it -- see `expand_condition_values(raw, width)` in
[generators.md](generators.md). Pinned by
`tests/regression/test_level88_value_all.py`.

**Multi-line clauses (`data_clauses.py` + `_data_fast.pyx`):** the lexer
emits NEWLINE tokens, so any clause reader that peeks for an operand after
consuming a keyword must skip NEWLINEs first or a line break between keyword
and operand silently drops the operand. REDEFINES does this via
`_skip_newlines` (pure Python) and an inline newline-skip loop (Cython) —
the same pattern the OCCURS sub-clauses (TIMES/DEPENDING/KEY/INDEXED) use.
Remember both implementations must change together, and the checked-in
`_data_fast.c` must be regenerated (Cython 3.2.4). Regression cases:
`tests/unit/test_data_division_branches.py::TestRedefinesClause`
(multi-line + forced pure-Python-loop variants).

**PICTURE clause with no terminating period drops the next data item
(`data_clauses.py::parse_picture_clause`, 2026-07-21):** the flip side of
the multi-line tolerance above — `parse_picture_clause`'s token loop treats
a NEWLINE as "more pattern may follow" *unconditionally*, which is correct
for a legitimate multi-line PICTURE clause but wrong when the terminating
period was simply lost. `LEVEL_NUMBER` is one of the token types the
picture-pattern loop collects (the lexer types every 1-2 digit integer as
`LEVEL_NUMBER` regardless of context — see the gotcha in `data.py` above),
so a bare level number belonging to the *next* data item (`05  BARIABLE`)
was appended to the previous item's pattern (e.g. `"9(08)05bariable"`), and
the following IDENTIFIER (the next item's name) went with it — the next
item, and all of its children, vanished from the AST with
`result.success == True` and `result.warnings == []`. The most common
real-world trigger is fixed-format column-72 truncation:
`normalize_fixed_format` (see [preprocessing.md](preprocessing.md)) extracts
only columns 8-72, so a terminating period placed at column 73+ never
reaches the lexer. Verified empirically against real GnuCOBOL 3.2 (via
mockymock's Docker toolchain, plain fixed-format `cobc`, no `-free`): the
same truncation shape is a **hard compile error** there (`group item cannot
have PICTURE clause` / `syntax error, unexpected Literal`), confirming
cobolparser's column-8-72 extraction already matches GnuCOBOL's own
semantics — the bug was purely the *silence*, not a truncation-boundary
mismatch. Not fixed-format-specific: a plain missing period in free-form
source hits the identical loop defect. Fixed by having the NEWLINE branch
look ahead past the newline for a LEVEL_NUMBER that cannot legally be more
PICTURE content: either (a) its value contains a digit other than `0`/`9`
— the only two digit-shaped PICTURE symbols (digit position /
zero-insertion) — so e.g. the `5` in `05` can only be a real level number
regardless of what follows it, or (b) it's immediately followed by an
`IDENTIFIER` (a named or `FILLER` item — both lex as `IDENTIFIER`). Signal
(a) alone was added after an initial "IDENTIFIER-follows" version shipped
without it: that version missed an **anonymous** next item with no
data-name at all (`05  REDEFINES ...`, no IDENTIFIER token at all — code
review caught it), which still corrupted the previous item's pattern and
misattached the anonymous item's children to it with `warnings == []`. (a)
does not misfire on the legitimate multi-line case this method already
tolerates — a PICTURE pattern built only from `9`/`0` symbols split across
lines, e.g. `PIC 9\n99.` — because every character of the LEVEL_NUMBER
value is itself `0` or `9`. When either signal fires, the clause stops
there instead of consuming the newline, and a `ParseResult.warnings` entry
is recorded via the same `host.add_warning` channel `_warn_dropped_data_token`
already uses. The `_data_fast` Cython path calls back into this same Python
method for PICTURE parsing (see "Cython callback surface" above), so both
paths are fixed together with no `.pyx`/`.c` change. Pinned by
`tests/regression/test_picture_clause_missing_terminator.py`, including
explicit parent/child re-attachment assertions (the original defect didn't
just drop the next item — its children were misattached to the preceding
sibling) and a dedicated anonymous-item case.

# Statement Parsers (`cobolparser/parsers/statements/`)

| File | COBOL Verbs |
|------|------------|
| `accept_parser.py` | ACCEPT |
| `arithmetic_parsers.py` | ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE |
| `call_parser.py` | CALL |
| `close_parser.py` | CLOSE |
| `communication_parsers.py` | SEND, RECEIVE, ENABLE, DISABLE, PURGE (COBOL-85 Communication Module; 2026-09-02) |
| `delete_parser.py` | DELETE |
| `display_parser.py` | DISPLAY |
| `entry_parser.py` | ENTRY |
| `evaluate_parser.py` | EVALUATE |
| `exception_parsers.py` | RAISE, RESUME, VALIDATE (COBOL 2002; 2026-09-02) |
| `go_parser.py` | GO TO |
| `ibm_exec_statements.py` | EXEC SQL, EXEC CICS, EXEC IMS DLI |
| `if_parser.py` | IF |
| `initialize_inspect_parsers.py` | INITIALIZE, INSPECT |
| `legacy_verb_parsers.py` | EXHIBIT, EXAMINE, TRANSFORM (OS/VS), ENTER, NOTE (COBOL-74), CHAIN (Micro Focus), READY TRACE / RESET TRACE, SERVICE LABEL / SERVICE RELOAD, TITLE (IBM compiler-directing; 2026-09-02) |
| `move_parser.py` | MOVE |
| `open_parser.py` | OPEN |
| `perform_parser.py` | PERFORM |
| `read_parser.py` | READ |
| `report_writer_parsers.py` | INITIATE, TERMINATE, SUPPRESS (Report Writer; GENERATE is in `simple_statement_parsers.py`; 2026-09-02) |
| `rewrite_parser.py` | REWRITE |
| `search_parser.py` | SEARCH |
| `set_parser.py` | SET |
| `simple_statement_parsers.py` | ALTER, CANCEL, COMMIT, CONTINUE, EJECT, EXIT, GENERATE, GOBACK, RELEASE, RETURN, ROLLBACK, USE (RELEASE `FROM` / RETURN `INTO` operands go through `consume_optional_qualifiers`, as MOVE's do: `WS-REC OF GRP`, `TBL ( I )`; before 2026-09-28 only the first word was kept) |
| `sort_merge_parsers.py` | SORT, MERGE |
| `start_parser.py` | START |
| `stop_parser.py` | STOP |
| `string_unstring_parsers.py` | STRING, UNSTRING |
| `unlock_parser.py` | UNLOCK |
| `xml_json_parser.py` | XML GENERATE, XML PARSE, JSON GENERATE, JSON PARSE (clause data names structured into `count_in` / `into_item` / `clause_items` by `_record_clause_items`, 2026-09-28) |
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

**ADD/SUBTRACT record `source_operands`** (2026-09-27,
`arithmetic_parsers.py`): the operand list parsed before TO/FROM/GIVING,
duplicates kept, stored on the node so a consumer can tell an addend from a
target/GIVING of the same name (`.operands` dedups them). See
`ast-models.md`.

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

**ADD `... TO` subscripted target dropped (`arithmetic_parsers.py`,
2026-07-21):** `AddStatementParser`'s `TO` branch consumed its target via a
private `_consume_identifier` helper that accepted only a bare `IDENTIFIER`
token, unlike `COMPUTE`'s `_consume_arithmetic_target` (already shared),
which folds a trailing `(subscript[, subscript]...)` group into the target
string. `ADD 1 TO TABLE-ITEM (I, J, K)` therefore captured only
`TABLE-ITEM` as the target and left `( I , J , K )` unconsumed — an
"Unparsed tokens" content-drop warning — and in a two-statement paragraph
the resulting recovery was bad enough to drop a *following* subscripted
`ADD` statement from the AST entirely, not just mis-parse its target. Fixed
by having `AddStatementParser` call the same `_consume_arithmetic_target`
helper COMPUTE already uses instead of its own bare-identifier method (now
removed); `AddStatement.target` is the same `"NAME ( SUB1 , SUB2 )"` shape
COMPUTE already produces for subscripted targets. Pinned by
`tests/unit/test_arithmetic_migration.py::test_add_statement_with_subscripted_target`
and `::test_add_statement_with_subscripted_target_and_giving`.

**SUBTRACT `... FROM` and arithmetic `GIVING` subscripted targets dropped
(`arithmetic_parsers.py` / `_utils.py`, 2026-07-21):** two sibling gaps in
the same bug class as the ADD fix above. (1) `SubtractStatementParser`'s
`FROM` branch consumed an identifier target with a bare
`stmt.set_target(tok.value); token_stream.consume()` instead of
`_consume_arithmetic_target`, so `SUBTRACT 1 FROM VARIABLE (H, I, 1)`
captured only `VARIABLE` and left `( H , I , 1 )` unconsumed. Fixed by
routing the `IDENTIFIER` case through `_consume_arithmetic_target`
(numeric-literal/level-number/figurative-constant targets, which can never
carry a subscript, keep the original bare-consume branch). (2)
`_utils.consume_keyword_and_operand` — shared by every arithmetic
statement's `GIVING` clause (ADD, SUBTRACT, MULTIPLY, DIVIDE) — only
accepted a single bare `IDENTIFIER` token, so `ADD 1 TO A GIVING RESULT
(H, I, 1)` dropped `(H, I, 1)` from the `GIVING` target too. Fixed by
folding an optional trailing `(subscript[, subscript]...)` group into the
returned value, mirroring `_consume_arithmetic_target`'s paren-depth
loop (duplicated rather than shared to avoid a `_utils.py` ->
`arithmetic_parsers.py` import cycle). Pinned by
`tests/unit/test_arithmetic_migration.py::test_subtract_statement_with_subscripted_target`,
`::test_add_statement_with_subscripted_giving_target`, and
`tests/unit/test_utils_clause_collection.py::TestConsumeKeywordAndOperand::test_consumes_subscripted_target`.

**WRITE `BEFORE`/`AFTER` phrase — `ADVANCING` optional (`write_parser.py`,
2026-07-20):** the standard grammar is `BEFORE|AFTER [ADVANCING] [n]
[LINES|LINE|PAGE]`, but the parser previously consumed `BEFORE`/`AFTER`
and then *required* the `ADVANCING` keyword before parsing the rest —
`WRITE rec AFTER 1` / `AFTER 1 LINE` / `BEFORE PAGE` silently dropped the
clause (`advancing_clause=None`), and a trailing `LINE`/`LINES` token was
left unconsumed to trigger the procedure division's "Unparsed tokens"
content-drop warning. `ADVANCING` is now consumed if present via
`try_consume_keyword` and the count/unit parsing runs either way, so both
forms produce the same `advancing_clause` dict
(`{"type": "AFTER", "value": 1, "unit": "LINES"}`; `PAGE` → `"value":
"PAGE", "unit": "CHANNEL"`). Pinned by
`tests/unit/test_write_advancing.py`.

**WRITE `ADVANCING` mnemonic-name / identifier support (`write_parser.py`,
`environment_sections.py`, 2026-07-20):** the count position of `BEFORE|AFTER
[ADVANCING] {integer-1 | identifier-1 | mnemonic-name-1}` accepted only a
numeric literal — an `IDENTIFIER` token there (a data-name holding a line
count, or a SPECIAL-NAMES mnemonic-name for a printer channel) was left
unconsumed, and the PROCEDURE DIVISION scanner then mis-parsed the dangling
identifier as a bogus paragraph header (`WRITE rec AFTER ADVANCING
TOP-OF-PAGE.` produced `advancing_clause={"type": "AFTER", "value": None,
"unit": None}` plus a phantom `TOP-OF-PAGE` paragraph). The parser now
branches on whether a trailing `LINE`/`LINES` follows the identifier: if so
it's `identifier-1` (`{"unit": "LINES", "value": <name>}`, same unit as a
literal count); if not it's `mnemonic-name-1`
(`{"unit": "MNEMONIC", "value": <name>}`). `PAGE` is excluded from this
branch so `ADVANCING PAGE` still hits the existing CHANNEL path.
`IOWriteStatement.set_advancing()` gained `identifier=`/`mnemonic=` kwargs
(mutually exclusive with `lines=`/`page=`, default `None` so existing call
sites are unaffected). Companion fix: `ConfigurationSectionParser`'s
SPECIAL-NAMES paragraph previously only recognized `CURRENCY`,
`DECIMAL-POINT`, `CLASS`, and `ALPHABET` — a mnemonic-name clause
(`implementor-name IS mnemonic-name [ON STATUS IS cond] [OFF STATUS IS
cond]`) fell into the generic "unknown clause, consume to next period"
branch and vanished with no metadata trace. It's now detected by
lookahead (`peek(1).value.upper() == "IS"`) and collected into
`special_names["mnemonic_definitions"]` as `{"environment_name":
"C01", "mnemonic_name": "TOP-OF-PAGE"}` (plus `on_status`/`off_status`
keys when the UPSI switch form is used). Pinned by
`tests/unit/test_special_names.py` and `tests/unit/test_write_advancing.py`.

**EVALUATE blank string-literal WHEN selectors (`evaluate_parser.py`):**
the lexer strips quotes off string literals, so `WHEN '  '` (the IMS DL/I
status-code idiom) arrives as a whitespace-only token that `_build_selector`
would filter out as an empty artifact, collapsing the clause to zero
selectors and reporting "WHEN clause must have at least one selector" on
valid programs. `_parse_selectors` re-quotes whitespace-only
`STRING_LITERAL` tokens (selector value `"'  '"`); non-blank literals keep
their unquoted representation. Pinned by
`tests/regression/test_evaluate_space_literal_when.py`. Commit `17fa400`
(2026-08-11) briefly regressed this by routing every selector token through
`condition_token_text()` (which quotes *all* string literals); restored
2026-08-12 (audit T-H1). EVALUATE *subjects* (`_parse_subjects`) do keep the
`condition_token_text()` quoting — `EVALUATE 'X'` renders its subject as
`'X'` — since no contract pins the unquoted form there; the flow scanner's
`WHEN <value>` edge labels follow the selector (unquoted) shape.

**EVALUATE subjects reach `.operands` (`evaluate_parser.py`, 2026-08-17
review follow-up):** `_parse_subjects` routes each parsed subject through
`EvaluateStatement.add_subject()` instead of appending straight to
`stmt.subjects` — for string subjects (the only kind this parser produces)
`add_subject()` also calls `add_operand()`, so subjects now land in the
generic `.operands` bag that `find_statements_using_variable`,
intrinsic-function detection, `LanguageEnvironmentAnalyzer`, and
`BoundaryInventoryAnalyzer`'s caller-dataflow rung all scan; previously
`stmt.operands == []` for every EVALUATE and each of those saw a
subject-only variable as unreferenced. `stmt.subjects` itself is unchanged
(same strings, same order), so `constraints.py`/`program_flow/scanner.py`'s
direct `.subjects` reads are unaffected; `to_dict()["operands"]` gains the
subject strings (additive — no contract pinned it empty, verified against
`tests/contracts/test_evaluate_serialization.py` and
`interface-contract.md`). Pinned by `TestEvaluateSubjects.
test_subjects_reach_operands_and_public_lookup` in
`tests/unit/analysis/test_unused_variables.py`.

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
A figurative constant (`BY CONTENT ZERO`) or a signed numeric literal
(`BY VALUE -7`) is one USING argument, named by its text (`"ZERO"`, `"-7"`);
before 2026-09-28 either ended the USING list, dropping it and every later
argument (mocky-mock's `CAPTURE ARG n` counts depend on this list). Pinned
by `test_call_using_comma_omitted.py::TestCallUsingFigurativeAndSignedLiterals`.

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

**ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE never consumed their own explicit
scope terminator, causing a phantom paragraph (`arithmetic_parsers.py`,
`_utils.py`):** `END-ADD`/`END-SUBTRACT`/`END-MULTIPLY`/`END-DIVIDE`/
`END-COMPUTE` have no dedicated `TokenType` (unlike `END-IF`/`END-PERFORM`/
`END-EVALUATE`) — they lex as plain `IDENTIFIER`, recognized only by value
via `SCOPE_TERMINATORS`. Every arithmetic parser's operand/expression
collection loop correctly *stopped* at these terminators (so they were never
folded into the statement), but `parse_size_error_clauses()` — the shared
helper all five call last — only handled `ON`/`NOT ON SIZE ERROR` and a bare
`PERIOD`; any other token, including the statement's own terminator, hit an
unconditional `else: break` and was left unconsumed in the stream. Since the
terminator is an `IDENTIFIER` immediately followed by a period, the
procedure division's paragraph-boundary lookahead then misread it as the
start of a new paragraph — e.g. `ADD 1 TO WS-X END-ADD. DISPLAY WS-X.` inside
`MAIN-PARA` produced a bogus `END-ADD` paragraph and silently reparented
`DISPLAY WS-X` (and everything after it) under it instead of `MAIN-PARA`.
Fixed by giving `parse_size_error_clauses()` an optional `end_keyword`
parameter: when the next token's value matches it, the terminator is
consumed along with an optional trailing period before returning. Each of
the four call sites now passes its own verb's terminator (`"END-ADD"`,
`"END-SUBTRACT"`, `f"END-{verb}"` for the shared MULTIPLY/DIVIDE helper,
`"END-COMPUTE"`); this composes with the pre-existing `ON`/`NOT ON SIZE
ERROR` handling since both an ON SIZE ERROR clause *and* an explicit
terminator can appear on the same statement. Pinned by
`tests/regression/test_tier8_arithmetic_scope_terminator.py`.

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

**Update (2026-08-07):** the `*>`-comment half of this rationale is now
stale — the lexer strips `*>` inline comments before the parser ever sees
them (see [lexer.md](lexer.md)'s "Free-form `*>` inline comments now
stripped" entry), so `read_specific_cmd_line_args.cbl`'s line-25 comment no
longer reaches the MOVE parser at all. The missing-source check remains
intentionally lenient regardless, since `REPLACE`/`COPY ... REPLACING`
pseudo-text can still leak a bare `MOVE` token with no source (`SM206A`,
`SM208A` above); the code comment in `move_parser.py` was updated to drop
the now-inaccurate `*>` justification and cite only the pseudo-text case.

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

**All-digit procedure names / PERFORM THRU numbering (2026-07-20, extended
2026-08-21):** COBOL permits procedure names made entirely of digits, and
`PERFORM 1000 THRU 1999` numbering is idiomatic in THRU-style code. Those
names lex as `NUMERIC_LITERAL` (or `LEVEL_NUMBER` for 1–2 digit values),
never `IDENTIFIER`, so support is explicit wherever a statement can target
a paragraph by name:

* `statements/_utils.py` — `is_procedure_name_token` is the single shared
  predicate (an identifier, or an all-digit `NUMERIC_LITERAL`/
  `LEVEL_NUMBER`), used by `perform_parser.py`, `go_parser.py`, and
  `simple_statement_parsers.py`'s `AlterStatementParser`. It was
  originally a `perform_parser.py`-local `_is_procedure_name_token`;
  promoted to `_utils.py` once GO TO and ALTER needed the identical check,
  to avoid a third copy drifting out of sync with the other two.
* `divisions/procedure_boundaries.py` — a separate, division-level
  `_is_procedure_name_token` (same shape, different module: it works off
  `token.type.name` strings rather than `TokenType` enum identity) accepts
  an identifier or an all-digit numeric token; `is_paragraph_or_section_start`
  uses it in both its after-period and at-name cases, so numeric paragraph
  headers (`1000.`) are recognized instead of being skipped as unsupported
  statements.
* `perform_parser.py` — the inline `PERFORM n TIMES` branch checks for a
  following `TIMES`/`TIME` via `_peek_next_meaningful` *before* consuming
  the numeric. Previously the numeric was consumed speculatively and, when
  TIMES did not follow, simply lost — `PERFORM 1000 THRU 1999` set
  `target_paragraph` to the literal word `THRU`. A numeric token not
  followed by TIMES now falls through to the procedure-name-target branch,
  and both the target and the THRU end accept all-digit names.
* `go_parser.py` — the first `GO TO` target always accepted any token
  value regardless of type, so a single-target `GO TO 1999` already
  worked. The computed-GOTO scan-ahead that collects *additional* targets
  before a `DEPENDING ON` required `TokenType.IDENTIFIER` specifically,
  though, so once the first target was numeric the loop never found
  `DEPENDING` and left the rest of the statement — remaining targets and
  the `DEPENDING ON` variable — unconsumed. Fixed by routing that
  scan-ahead through the shared predicate.
* `simple_statement_parsers.py`'s `AlterStatementParser` — the
  from-paragraph read required `TokenType.IDENTIFIER` outright, dropping
  `ALTER 1000 TO PROCEED TO 2000` entirely as an unrecognized statement.
  The to-paragraph read was already unrestricted (any non-`PERIOD` token),
  so only the from-paragraph needed the fix. SORT/MERGE `THRU` procedure
  names remain IDENTIFIER-only.

Pinned by `tests/unit/test_perform_thru_numeric.py` and
`tests/regression/test_real_corpus_parse_failures.py`
(`TestAlterNumericProcedureNames`, `TestGoToDependingOnNumericTargets`).

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
following clauses into `assign_to`). The FILE of `FILE STATUS`
is optional (IBM): a bare `STATUS [IS] x [y]` starts the same clause
(`STATUS` is in `_SELECT_CLAUSE_KEYWORDS`); before 2026-09-28 it was glued
onto `assign_to` and `file_status` stayed empty
(`test_environment_division_parser.py::test_status_clause_without_the_word_file`). `DECIMAL-POINT IS COMMA` in
SPECIAL-NAMES used to warn that the lexer ignored it (H4); since 2026-09-28
it is honoured (comma-decimal literals, `,`/`.` exchanged in PICTURE -- see
[lexer.md](lexer.md)) and the warning is gone. `RECORD KEY IS K6 OF R6` and
`ALTERNATE RECORD KEY IS A6 IN R6` (2026-09-28): `_consume_qualifiers`
reads the `OF`/`IN` chain after the key name into `record_key_qualifiers`
/ the alternate key's `qualifiers` (innermost first; the key stays the bare
name); the qualifier used to be warned "Unparsed token" and knocked out a
following `WITH DUPLICATES`. All division parsers can reach the host warning channel:
`BaseDivisionParser.host` is set by the division loop (`parser.py`).

**Comment-entries verbatim (`identification.py`, 2026-09-28):**
`_parse_clause_value` first takes the consecutive `COMMENT_ENTRY` tokens
the lexer emits (see [lexer.md](lexer.md)), joins the lines with one space
and drops only the entry's own closing period (`AUTHOR. J. SMITH, O'NEIL.`
-> `"J. SMITH, O'NEIL"`). An unterminated entry from a paragraph name that
is not in Area A falls through to the old token-collection loop, so the
loosely indented `AUTHOR. SOMEONE` / `DATA DIVISION.` shape still ends at
the division header. Hand-built token lists (no `COMMENT_ENTRY`) parse
exactly as before.

**SPECIAL-NAMES clause boundaries (`environment_sections.py`, 2026-09-28):**
IBM writes SPECIAL-NAMES as *one sentence* with a single closing period, so
a clause ends where the next one starts. `CLASS` / `ALPHABET` operands used
to run until the next CURRENCY/DECIMAL-POINT/CLASS/ALPHABET word or a
period, swallowing a following `SYMBOLIC CHARACTERS` or mnemonic clause
(`C01 IS TOP-OF-PAGE` vanished from `mnemonic_definitions`) plus the `"\n"`
NEWLINE tokens; `SYMBOLIC CHARACTERS NUL IS 1` was read as a mnemonic
clause; and a following `REPOSITORY.` paragraph's `CLASS X IS 'java.X'`
entries became SPECIAL-NAMES class conditions. Now every operand collection
stops at `_at_clause_start()` (a clause word in `_SPECIAL_NAMES_CLAUSES`, a
`name IS` / `name ON|OFF STATUS` mnemonic start, a period) and the
paragraph ends at any CONFIGURATION SECTION paragraph header
(`_CONFIGURATION_PARAGRAPHS`). New metadata: `symbolic_characters`
(`[{name, ordinal, alphabet}]`, a group is only taken when an integer
follows its IS/ARE) and `currency_signs` (`[{sign, picture_symbol}]`, every
CURRENCY clause; `currency_sign` keeps its last-wins value). `CLASS`/
`ALPHABET ... FOR ALPHANUMERIC|NATIONAL` and the name-less `UPSI-0 ON STATUS
IS x` form are accepted. `tests/regression/test_special_names_clause_boundaries.py`.

**SELECT short forms (`environment_select.py`, 2026-09-28):** `ORGANIZATION
IS` is optional in IBM's grammar. A bare `INDEXED` / `SEQUENTIAL` / `LINE
SEQUENTIAL` used to be glued onto `assign_to` (`"F1DD INDEXED"`) with
`organization` None, and a bare `RELATIVE` went to the RELATIVE KEY parser
(which took the next word as the key). `SEQUENTIAL`/`INDEXED` are now in
`_SELECT_CLAUSE_KEYWORDS`, `LINE SEQUENTIAL` ends ASSIGN by lookahead, and
`RELATIVE` is the key clause only when `KEY` follows (`_next_word`).
`ASSIGN USING data-name` (dynamic file name) stores the data-name in
`assign_to` *and* the new `SelectStatement.assign_using`, which
`UnusedVariableAnalyzer._file_control_references` counts as a use (it was
`assign_to == "USING WS-DSN"` and the item read as unused). The ORGANIZATION
/ ACCESS / RECORD KEY / RELATIVE KEY / FILE STATUS sub-parsers skip line
breaks between their own words (`_try_consume_word`); only one break,
directly before the value, was tolerated. Still open: a qualified `RECORD
KEY IS K OF R` keeps only `K` (the rest is warned as unparsed).
`tests/regression/test_select_optional_organization_word.py`.

# Statement-coverage audit (2026-09-02)

Question asked of the parser: *can a PROCEDURE DIVISION statement leave the
AST with neither an error nor a warning, and is every COBOL verb
supported?* Method: a per-verb probe program for every statement form of
COBOL-85 / COBOL 2002 / IBM Enterprise COBOL plus the OS/VS and Micro
Focus verbs, and a sweep of all 540 COBOL files in the repo (NIST suite,
shamrice, `tests/samples/`) aggregating "Unsupported statement" /
"Unparsed tokens" warnings (~370 before, 30 after -- the remainder is
malformed samples, unexpanded `COPY`, and screen-section extensions).
Pinned by `tests/unit/test_extended_verb_parsers.py` and
`tests/regression/test_statement_coverage_audit_2026_09_02.py`.

**Silent (no error, no warning) gaps found and fixed:**

* `ExecCicsStatement` / `ExecImsStatement` extended `ASTNode`, not
  `CobolStatement`, so `CobolProgram.get_all_statements()` -- the walk
  every analyzer starts from -- never returned a single EXEC CICS / EXEC
  DLI statement. Now `CobolStatement` subclasses (`statement_type` `"EXEC
  CICS"` / `"EXEC IMS"`); `node_type` stays `"EXEC_CICS"` / `"EXEC_IMS"`,
  the `cics_command` / `ims_command` attributes became read-write
  properties overriding the base class's read-only ones, `to_dict()` is
  byte-identical. `unused_variables.py`'s separate `traverse_depth_first`
  sweep is now redundant but harmless.
* `GO TO` with the target on the next line (`GO TO` / `SEP-WRITE-1.`, NIST
  NC107A): the NEWLINE token became the target and the real target was
  re-parsed as a phantom paragraph. `go_parser.py` now skips layout after
  `GO` and after `TO`.
* Optional `ON` / `AT` in handler phrases: `ADD ... SIZE ERROR`, `NOT SIZE
  ERROR`, `CALL ... EXCEPTION` / `OVERFLOW` / `NOT EXCEPTION`, `READ ...
  END` / `NOT END` (NIST RL110A), `WRITE ... END-OF-PAGE`, `RETURN` /
  `SEARCH ... END`. The keyword was swallowed as an operand and the handler
  body escaped to the enclosing paragraph as free-standing statements.
  `parse_size_error_clauses`, `call_parser.py` (main loop and
  `_parse_using_clause` stop set), `read_parser.py`, `write_parser.py`,
  `simple_statement_parsers.py` (RETURN) and `search_parser.py` accept the
  bare forms; the arithmetic target/GIVING stop sets gained `SIZE`. A bare
  `END` is only an `AT END` when it does not start `END PROGRAM` /
  `END DIVISION` (`_utils.bare_end_starts_at_end_clause`).
  `parse_size_error_clauses` also no longer consumes a `NOT` that does not
  open `NOT [ON] SIZE ERROR` (an ADD inside a CALL handler used to eat the
  CALL's own `NOT ON EXCEPTION`, NIST IC222A).
* `MOVE`'s target loop consumed *any* non-identifier token silently
  (`RECEIVE ... NO DATA MOVE A TO B WITH DATA ...` lost `WITH DATA` and
  folded the second handler into the first). It now skips only `,`/`;`
  and stops on anything else.
* `ACCEPT ... [ON] EXCEPTION` / `NOT [ON] EXCEPTION` bodies escaped the
  same way; `IOAcceptStatement.on_exception` / `.not_on_exception` hold
  them now and `END-ACCEPT` is consumed.

**Warned-but-structural drops fixed:**

* A string literal spelled like a verb (`IF TB-25 EQUAL TO "IF"`, NIST
  NC126A; `STRING "IF" ...`; `COMPUTE X = FUNCTION LENGTH("IF")`; `WHEN
  "ELSE"`) was mistaken for the next statement's verb by the value-based
  keyword checks. `is_statement_boundary`, `_looks_like_statement_boundary`,
  `parse_arithmetic_operands` and the IF / EVALUATE / SEARCH / RETURN / USE
  condition-and-operand loops now exempt `LITERAL_TOKEN_TYPES`.
* A CALL handler body swallowed the enclosing IF's `ELSE` / `END-IF` or
  PERFORM's `END-PERFORM` (`call_parser._parse_nested_stmts` now stops at
  `CONTROL_FLOW_BOUNDARIES` / `SCOPE_TERMINATORS`).
* `,` / `;` statement separators (`PERFORM A, GO TO B.`, `... GO TO X;
  ELSE ...`, `CALL ... USING A, B; ON OVERFLOW`, `READ F ; AT END`,
  `START F ; INVALID KEY`, `CLOSE F1, F2`, `SET A; B TO 3`) were "unparsed
  tokens" and broke IF/ELSE structure. `_utils.skip_statement_separators`
  (whitespace + `SEPARATOR_TOKEN_TYPES`) now runs at the top of every
  statement-list loop (paragraph bodies, IF/ELSE, inline PERFORM, EVALUATE
  WHEN, SEARCH WHEN, `collect_clause_stmts`, size-error / invalid-key /
  CALL-handler bodies, RETURN clauses) and before the handler clauses of
  CALL, READ, WRITE and `parse_invalid_key_clauses`; operand lists skip them
  where COBOL allows.
* `XML GENERATE ... SUPPRESS WHEN SPACES` ended the statement at
  `SUPPRESS` (a verb elsewhere) -- `xml_json_parser.py` keeps its own clause
  words (`SUPPRESS`, `NOT`, `ON`, and `WHEN` once a SUPPRESS was seen).
* `IF A EQUAL TO B` recorded `right_operand` `"TO B"`; `GREATER [THAN] OR
  EQUAL [TO]` split into an OR of two conditions. `_conditions.py`'s
  cleaning pass drops the `TO`/`THAN` connective after a relational word and
  folds `OR EQUAL` into `GREATER_OR_EQUAL` / `LESS_OR_EQUAL`.

**Clause-level gaps from the NIST sweep (all previously "unparsed
tokens"):** multi-group `SET SW-1 TO ON SW-2 TO OFF` (`SetStatement.groups`,
NC174A); `OPEN ... [WITH] NO REWIND` / `REVERSED` / `[WITH] LOCK` and
`CLOSE ... LOCK` / `NO REWIND` without `WITH` (OBSQ3A, IX216A); `PERFORM
id TIMES` and `PERFORM P id (sub) TIMES` (NC102A, NC121M); `PERFORM WITH
TEST AFTER VARYING ...` inline (SM208A) and bare `TEST BEFORE` (NC201A);
subscripted `VARYING` variable (NC201A); `START ... KEY IS = / > / >= k`
(IX208A) and `KEY GREATER OR EQUAL TO k` (RL205A); `DISPLAY ELEM OF GRP,
21` (NC204M); `GO TO ... DEPENDING ON X (7)` (NC102A); `PERFORM P OF
SECTION` / `GO TO P IN SECTION` / `ALTER P IN S TO ...` (NC208A, OBNC2M --
qualifier kept in `metadata["target_qualifier"]`, target stays the bare
name); `READ F WITH LOCK KEY IS k`; `ACCEPT X OF Y` / `ACCEPT T (2)` /
`ACCEPT cd MESSAGE COUNT` (NC204M, NC109M, CM101M); `CALL ... USING BY
VALUE 100` / `ADDRESS OF x` / `SUBSCRIPTED-DATA (4)` (IC235A); `STOP ZERO`
/ `STOP QUOTE` (OBNC1M); `WRITE ... ADVANCING ZERO` (SQ101M); `ALTER a TO
..., b TO ...` (NC303M); `OPEN INPUT A, B` (SQ206A); `REWRITE r FROM X (2)`
(SQ116A); a subscripted dynamic `CALL WS-PGM (IDX)` (bare name stays
`called_program`, full reference in `metadata["called_program_reference"]`).
CALL handler bodies also stop at the *next* `ON` / `NOT` clause, so `ON
OVERFLOW ... ON EXCEPTION ...` yields both handlers.

**New statement parsers (22 verbs) and where they live:** see the
statement-parser table above (`report_writer_parsers.py`,
`communication_parsers.py`, `legacy_verb_parsers.py`,
`exception_parsers.py`) and [ast-models.md](ast-models.md). Matching
notes: `TITLE` (not reserved outside IBM) is only claimed when a string
literal follows; `VALIDATE` (not reserved by IBM) only when a data-name
follows, so a paragraph named `VALIDATE.` still parses as a paragraph;
`READY` / `RESET` only before `TRACE` (RESET also appears in Report Writer
`SUM ... RESET ON`); `SERVICE` only before `LABEL` / `RELOAD`; `NOTE`
(COBOL-74 comment statement) runs to the sentence period but stops early at
a following line that starts with a verb, so a period-less NOTE cannot eat
the rest of the program. `PURGE` / `RAISE` / `RESUME` / `VALIDATE` / `TITLE`
have no lexer `TokenType` and are matched by value via `_utils.matches_word`
(never `matches_keyword(stream, TokenType.IDENTIFIER, ...)`, which would
claim every identifier). `_utils.collect_operands` is the shared operand
collector these parsers use (subscripts/qualifiers folded, literals
re-quoted, separators skipped, statement-boundary and H9 paragraph-boundary
aware). `END-RECEIVE` joined `SCOPE_TERMINATORS` / `STRAY_MARKERS`.

**Left as-is (documented, not silent):** an unexpanded `COPY` in the
PROCEDURE DIVISION (use copybook expansion); screen-section DISPLAY/ACCEPT
extensions (`LINE`/`COLUMN`/`BLANK SCREEN`/`WITH BELL`/`FROM ESCAPE KEY`);
the deliberately malformed `tests/samples/` files (a second `PROCEDURE
DIVISION` after a `REPORT SECTION`, an `01` level inside a paragraph, `OPEN
INVALID`, a `CALCULATE` pseudo-verb).

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

*Follow-up (2026-09-28):* neither loop stopped at a **scope terminator** of
the *enclosing* statement. `IF c PERFORM p UNTIL d END-IF STOP RUN.` read
`END-IF` into the condition (`"d END-IF"`), so the IF ran on to the period
and swallowed the top-level `STOP RUN` into its THEN arm; `PERFORM UNTIL x
... PERFORM p UNTIL y END-PERFORM` likewise stole the inline PERFORM's
`END-PERFORM`. The flow analyzers then saw a paragraph that only
*conditionally* stops and invented a fall-through out of it (hiding the
dead paragraph after it). Both `_parse_until_condition_only` (out-of-line
`UNTIL` / `WITH TEST ... UNTIL`) and `_collect_until_condition_tokens`
(`VARYING ... UNTIL`) now stop -- without consuming -- at any
`SCOPE_TERMINATORS` word: an out-of-line PERFORM owns none. Pinned by
`tests/unit/test_perform_until_scope_terminator.py`.

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

# open-findings.md HIGH-severity fixes (2026-07-09, H1-H10)

Eight HIGH findings from `reports/open-findings.md`'s 2026-07-08
re-verification pass, plus H9 (found in a same-day follow-up) and H10
(reported directly by a user, found independently of this document's own
audit passes), all fixed and pinned by
`tests/regression/test_open_findings_high_regressions.py` (H1-H9, one test
class per finding ID) and
`tests/regression/test_perform_backward_compat.py::TestPerformVaryingOutOfLine`
(H10). Full per-finding writeup in `CHANGELOG.md`'s Unreleased → Fixed
section; only the parser-relevant ones are summarized here (H5
MoveTypeChecker → [analysis.md](analysis.md), H6 PathResolver →
[preprocessing.md](preprocessing.md), H7 lexer warning →
[lexer.md](lexer.md) above).

* **H1 — `set_parser.py`:** the `SET ADDRESS OF x TO y` target-collection
  loop only accepted `IDENTIFIER`/`STRING_LITERAL` tokens; `OF` lexes as
  its own dedicated `TokenType.OF`, not `IDENTIFIER`, so the loop's
  `else: break` fired immediately on `OF` and never reached the pointer/
  `TO`/target tokens (`targets: [], set_type: null, value: null`). `OF` is
  now explicitly recognized and skipped in that loop.
* **H1b (2026-08-07) — `set_parser.py`, the value-side mirror of H1:**
  `SET pointer-var TO ADDRESS OF identifier` was not covered by the H1 fix.
  The `TO` branch consumed only the single token after `TO` as `value`, so
  for `ADDRESS OF identifier` it captured `value: "ADDRESS"` and left
  `OF identifier` on the stream — silently reinterpreted by the enclosing
  PROCEDURE DIVISION parser as spurious paragraph headers, with
  `result.success` still `True` and no errors/warnings. The `TO` branch now
  special-cases a leading `ADDRESS OF` prefix on the value: it consumes
  both keywords and stores the underlying identifier as `value`, setting a
  new `SetStatement.value_is_address_of` flag. Pinned by
  `tests/regression/test_open_findings_high_regressions.py::TestH1bSetToAddressOf`.
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
* **H10 — `perform_parser.py`, reported by a user (verified independently
  against the real parser before reporting; found separately from this
  document's own audit passes):** the out-of-line PERFORM branch (reached
  after a target paragraph is consumed) checked for `TIMES`, `WITH TEST`,
  and `UNTIL` following the paragraph name, but had **no case for
  `VARYING` at all** — `PERFORM MY-LOOP VARYING I FROM 1 BY 1 UNTIL I >
  10.` left the whole `VARYING`/`FROM`/`BY`/`UNTIL` clause unconsumed for
  the generic "unparsed tokens ... clause or statement not fully
  supported" recovery path to discard, and `PerformStatement.perform_type`
  stayed the default `"SIMPLE"` — indistinguishable from a genuine plain
  `PERFORM MY-LOOP.` to any caller keyed off `perform_type` (e.g.
  `ProgramFlowAnalyzer`'s loop-edge classification, `program_flow.py:833`).
  The reporter's own framing: the only thing preventing this from being a
  live problem was an *unrelated* mechanism — the generic dropped-clause
  warning happening to trip an unrelated downstream refusal gate in a
  consuming service, before any terminator logic there ran. That's a real
  but accidental safety net, not a fix: the *inline* form of the identical
  clause (`PERFORM VARYING I FROM 1 BY 1 DISPLAY I END-PERFORM`, no
  `UNTIL`) already had the same mistagging with **zero** warning to mask
  it (`errors=[], warnings=[]`, `perform_type: "SIMPLE"`), confirming the
  root cause: `perform_type` only ever became `"VARYING"` as a side effect
  of `set_varying_clause()`, which requires a fully-parsed
  `until_condition` — so a malformed clause silently reported `"SIMPLE"`
  regardless of dispatch path.

  Fixed by (1) extracting the inline VARYING clause's `id FROM x BY y
  [WITH TEST ...] UNTIL cond [AFTER ...]` parsing into a shared
  `_parse_varying_header()`, wired into a new out-of-line dispatch
  (`_parse_out_of_line_varying_clause`) hooked in right where the
  paragraph-name branch already checks for `UNTIL`, and (2) a new
  `PerformStatement.mark_varying()` called the instant the `VARYING`
  keyword is consumed — *before* attempting `FROM`/`BY`/`UNTIL` — so
  `perform_type` reflects the keyword's unambiguous presence rather than a
  successful sub-parse, and can no longer regress to `"SIMPLE"` as a side
  effect of a degraded clause. A malformed/incomplete VARYING clause
  (keyword present, sub-clause not fully recognized) now also emits an
  explicit warning via a new `_warn_incomplete_varying_clause()`, instead
  of depending on an unrelated recovery path to (sometimes) surface it.
  Pinned by `TestPerformVaryingOutOfLine` in
  `tests/regression/test_perform_backward_compat.py` (happy path, a
  degraded/no-UNTIL case asserting `perform_type == "VARYING"` with
  `varying_clause is None` — the assertion that actually pins the
  reported concern — and a plain-PERFORM guard case), plus strengthened
  assertions on the pre-existing `test_perform_variable_times_count_not_breaking`
  (same file — its COBOL fixture also had a latent fixed-format
  column-72 overflow that silently truncated the `UNTIL` clause,
  independent of this bug, fixed by wrapping the statement across two
  lines) and on `TestPerformVaryingMissingUntil` in
  `tests/unit/test_perform_edge_cases.py` (inline-form degraded case).

# open-findings.md MEDIUM-severity fixes (2026-07-09)

Ten MEDIUM findings from `reports/open-findings.md`, all fixed and pinned
by `tests/regression/test_open_findings_medium_regressions.py` (one test
class per finding ID). Full per-finding writeup in `CHANGELOG.md`'s
Unreleased → Fixed section; only the parser-relevant ones are summarized
here (M4/M5/M8 normalize_fixed_format → [preprocessing.md](preprocessing.md),
M7 typed-literal hex validation → [lexer.md](lexer.md), M14 copybook
cache-hit accounting → [preprocessing.md](preprocessing.md)).

* **M1 — `display_parser.py`:** the display-item collection loop accepted
  `STRING_LITERAL`/`IDENTIFIER`/`NUMERIC_LITERAL` but not
  `TokenType.FIGURATIVE_CONSTANT` (what `SPACE`/`ZERO`/`HIGH-VALUE`/etc.
  lex to), so `DISPLAY SPACE.` produced `display_items: []` and an
  "Unparsed tokens" warning — the single most common trigger in the
  mockymock corpus sweep (56 hits across 24 shamrice programs).
  `TokenType.FIGURATIVE_CONSTANT` added to the accepted set.
* **M2 — `display_parser.py` / `models/statements/data.py`:** `WITH`/
  `NO`/`ADVANCING` lex as dedicated `TokenType`s (not `IDENTIFIER`), so
  `DISPLAY ... WITH NO ADVANCING` hit the item loop's final "unknown
  token → stop" branch and the whole clause vanished (warn-masked).
  `DisplayStatement` gained a `with_no_advancing` flag; a new branch in
  the parse loop matches `[WITH] NO ADVANCING` (in that fixed order —
  `WITH` optional, `NO ADVANCING` mandatory) and sets it.
* **M3 — `display_parser.py`, `accept_parser.py`,
  `models/statements/data.py`, `models/statements/io.py`:** `AT`
  positioning on `DISPLAY`/`ACCEPT`, and `ACCEPT`'s extended clauses
  (`SECURE`, `NO-ECHO`, `TIMEOUT`, `AUTO-SKIP`, `UPPER`), were dropped
  entirely — `IOAcceptStatement` already had scaffolded fields/setters
  (`at_line`, `at_column`, `with_no_echo`, `set_position()`, ...) that
  `accept_parser.py` never called. A corpus grep of
  `examples/cobol/shamrice/*.cbl` (the corpus the finding's hit-counts
  came from) found `AT` used 34 times, **100% via the bare
  combined-numeric form** (`AT 0330` → line 3, column 30, decoded via
  `divmod(value, 100)`), zero via the `AT LINE n COLUMN m` keyword form —
  `DisplayStatementParser._parse_at_clause` supports both (the keyword
  form is speculative IBM-grammar coverage there, not corpus-driven);
  `AcceptStatementParser` implements only the corpus-confirmed numeric
  form. `SECURE` and `NO-ECHO` are modeled as **distinct** flags on
  `IOAcceptStatement` (`secure` vs. the pre-existing `with_no_echo`) per
  `accept-secure.cbl`'s own comment: `SECURE` masks input with `*` per
  character, `NO-ECHO` shows nothing — collapsing them would have lost
  that distinction. `IOAcceptStatement` also gained `timeout_value`
  (int) and `auto_skip`/`upper` (bool) fields. All six clause shapes
  (`AT nnnn`, `SECURE`, `NO-ECHO`, `TIMEOUT n`, `AUTO-SKIP`, `UPPER`,
  optionally preceded by `WITH`) are taken verbatim from
  `examples/cobol/shamrice/accept.cbl` and `accept-secure.cbl`.
  **Not implemented** (zero-to-one corpus hits; for `COLOR` especially
  the real GnuCOBOL grammar — `FOREGROUND-COLOR`/`BACKGROUND-COLOR`, a
  two-part clause — isn't specified with enough confidence by the
  finding's text to implement correctly): `CURSOR`, `BEEP`/`BELL`,
  `COLOR`, `UPDATE`, `WITH BLANK SCREEN` (a `DISPLAY`-side clause
  noticed during the corpus grep, 6 hits, but never part of this
  finding). See `reports/open-findings.md`'s M3 entry for the residual
  write-up.
* **M9 — `_utils.py`:** `try_parse_nested_statement`'s bare
  `except Exception` logged at DEBUG only, with no entry in
  `ParseResult.errors`/`.warnings` — an exception that bypassed
  `report_or_raise` (e.g. `TokenMismatch`/`UnexpectedEndOfInput` raised
  directly by `token_stream.expect()`) vanished completely untraceable.
  Now records a warning (`"Nested statement parse failed and was
  skipped: {exc}"`) unless the exception is already tagged
  `_already_recorded = True` by `report_or_raise` (avoiding
  double-reporting on the much more common path). Distinct from H4's 5
  bare `except ParseError: pass` sites in `perform_parser.py` (see the
  H1-H8 section above) — same bug class, different call sites, both
  fixed independently.
* **M16 — `parsers/divisions/data.py`:** `_PICTURE_SYMBOL_TOKEN_TYPES`
  used `TokenType.DIVIDE`/`MULTIPLY` — the DIVIDE/MULTIPLY *statement
  keyword* tokens — instead of `TokenType.DIVIDE_OP`/`MULTIPLY_OP` (what
  `/` and `*` actually lex to per `lexer.py`'s single-char token table),
  so `_parse_picture_clause` stopped collecting at the first slash or
  asterisk editing symbol. `PIC 99/99/99` truncated to pattern `"99"`
  with the `/99/99` remainder misparsed as phantom level-99 data items
  (`ANONYMOUS-99-N`, duplicated as both a child of the real item and at
  top level); `PIC $***,**9.99` similarly truncated to `"$"`. Now uses
  the correct operator token types — both patterns extract in full.

# Section/Paragraph Location Tracking (2026-07-09, user-reported)

A user parsing a real program noticed `ENVIRONMENT DIVISION`'s
`CobolDivision` node and its `INPUT-OUTPUT` `CobolSection` reported the
*same* `line`/`column` in `to_dict()` output, even though the two headers
sit on different source lines. Root cause: `BaseDivisionParser.parse()`
(`divisions/base.py`) captures `start_location` once, from the division
keyword token, and threads that single `SourceLocation` through to
`_create_ast_node()` — which every division parser's `_create_ast_node`
was reusing verbatim for **every** `CobolSection`/`CobolParagraph` it built,
instead of capturing each section's own header token location.

`procedure.py` already did this correctly (`section_info.get("location",
start_location)`, populated from the section-header token when parsed) —
only `environment.py` and `data.py` had the bug:

* **`environment.py`:** `_parse_configuration_section`,
  `_parse_input_output_section`, and `_parse_file_control_paragraph` each
  now capture the location of their own leading keyword token (via
  `token_stream.peek(0)`, before consuming it) and return it in their result
  dict under `"location"` (the FILE-CONTROL paragraph's location is returned
  as `"file_control_location"` inside the INPUT-OUTPUT section's dict, since
  `_create_ast_node` needs both the section's and the paragraph's location).
  `_create_ast_node` reads `division_content[...].get("location",
  start_location)` per section instead of hard-coding `start_location`.
* **`data.py`:** `_parse_section` (shared by `FILE`/`WORKING-STORAGE`/
  `LOCAL-STORAGE`/`LINKAGE`) captures its own section-keyword token location
  the same way and returns it under `"location"`; `_create_ast_node` reads it
  per section instead of reusing the division's `start_location`.

Statement-level and data-item-level locations inside sections were already
accurate — this fix is scoped to the `Division` → `Section` → `Paragraph`
container nodes' own location metadata. Pinned by
`tests/regression/test_section_location_tracking.py`.

# Literal Re-Quoting (`cobolparser/_literals.py`, 2026-08-28)

The lexer hands every `STRING_LITERAL` token over **decoded**: delimiters
stripped and any doubled delimiter collapsed to one character, so both
`'IT''S'` and `"IT'S"` arrive as `IT'S`. Anything that re-emits such a value
as COBOL source text therefore has to re-apply COBOL's only escape for the
delimiter inside a literal -- repeating it -- and until 2026-08-28 none of
the re-quoting sites did.

The failure is narrow and loud only much later. CICS's `DFHAID` copybook
legitimately declares `DFHTRIG PIC X VALUE IS '"'` -- a single-quote-
delimited literal whose content is one `"` character. `parse_value_clause`
wrapped that decoded content in `"..."` verbatim, yielding three quote
characters: an unterminated literal. cobolparser itself never notices (it
only stores the string), so the damage lands in whatever re-emits the
clause -- mockymock's generated `UT-RESET-WORKING-STORAGE` paragraph was
the reporter -- where it desynchronizes `cobc`'s tokenizer for the rest of
the program and surfaces as a bogus `invalid symbol '%'` error two lines
further on.

`_literals.quote_literal(value)` is the single fix: `""" + value.replace(one
quote, two quotes) + """`. It lives in its own zero-internal-dependency
module (same rationale as `_errors.py`) because its callers span both
`parsers/divisions/` and `parsers/statements/`:

| Site | Clause |
|---|---|
| `divisions/data_clauses.py::parse_value_clause` | `VALUE <literal>` and `VALUE ALL <literal>` |
| `divisions/environment_select.py` | SELECT's `ASSIGN TO <literal>` |
| `statements/move_parser.py` | MOVE's literal source |
| `statements/display_parser.py` | DISPLAY items and function-call operands |
| `statements/write_parser.py` | WRITE's `FROM <literal>` |

Level-88 condition values are deliberately **not** in that list:
`data_special_entries.py` stores them undelimited (`item.add_value(t.value)`),
a different convention that never claims to be COBOL source text.

The property that matters is round-tripping: re-parsing an emitted clause
must yield the identical clause (the lexer already decodes doubled
delimiters, so it does). Pinned by
`tests/regression/test_embedded_quote_literals.py`, which also verifies the
`VALUE ALL` branch and the MOVE/DISPLAY operands. The emitted four-quote
form was additionally verified to compile and run under real GnuCOBOL 4.0;
the old three-quote form does not compile at all.

**Typed literals in VALUE (2026-09-27, audit 2.1).** `parse_value_clause`
(both the plain and the `VALUE ALL` branch) renders a STRING_LITERAL through
`data_clauses.literal_source()`, which returns `raw_value` when the lexer set
one (only typed literals: `X"..."`, `Z"..."`, `N"..."`, ...) and
`quote_literal(value)` otherwise. `VALUE X"4142"` had serialized as `"4142"`.
The `_data_fast` path delegates VALUE to this helper, so both builds agree.

# Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser` (`parse()` + `matches()`)
2. Register it in `create_statement_registry()` (`parsers/divisions/procedure_registry.py` — the builder `ProcedureDivisionParser` uses), in the right first-match priority slot (more specific before general)
3. Add a `TokenType` entry in `lexer.py` if the verb is not yet a keyword
4. Add AST node(s) in the appropriate `cobolparser/models/statements/<category>.py` with `to_dict()`; use `ASTNodeFactory` from `core/ast_factory.py`
5. Export from `cobolparser/parsers/statements/__init__.py` and `cobolparser/models/statements/__init__.py`
6. Update `EXPECTED_ORDER` and `DISPATCH_CASES` in `tests/unit/test_procedure_registry_dispatch_order.py` — this pins the registration order and asserts the new parser dispatches for its own keyword(s); the suite fails loudly if the new registration is missing or misplaced
7. Add a fixture to `FIXTURES` in `tests/regression/test_swallow_sweep.py` (see "Generic swallow-sweep regression" below) — both this and step 6 fail the suite automatically if skipped, so neither strictly requires remembering to do it, but a real fixture snippet still needs a human to write it

# Configuration Classes

| Class | Purpose |
|-------|---------|
| `ErrorRecoveryMode` | `FAIL_FAST` (default) or `COLLECT_ALL` |
| `MemoryConfiguration` | `max_memory_mb` (64–8192), `enable_streaming`, `chunk_size_kb` |
| `SerializationConfig` | `include_metadata: bool` |
| `DialectType` | Enum — `IBM_ENTERPRISE`, others planned |
| `ParseStatistics` | Wall-clock timings, token counts, node counts |

# Structured EXEC blocks + expression trees (2026-07-20, M11/M12)

**EXEC CICS / IMS / SQL (M11):** `ibm_exec_statements.py`'s
`_parse_cics_options` parses the CICS option list into
`ExecCicsStatement.options: dict[str, str | None]` (keyword → argument
text inside parentheses, `None` for flag options like `ERASE`/`NOHANDLE`;
nested parentheses and quoted literals handled). `ExecImsStatement`
captures the DLI function code plus top-level positional arguments (PCB,
I/O area, SSAs). `parse_exec_sql` (`models/sql_statements.py`) is a
literal/comment-aware tokenizer: statement kind, tables (FROM / INTO /
UPDATE / JOIN), host variables including `:VAR:IND`, and for SELECTs
`select_columns` + `where_present`. All pre-existing fields and
`to_dict()` keys are unchanged — everything new is additive. Pinned by
`tests/regression/test_open_findings_m11_regression.py`.

**Expression trees (M12):** COMPUTE's collected token sequence is now
also precedence-parsed (unary sign, `**`, `*`/`/`, binary `+`/`-`,
parentheses, subscripted identifiers, FUNCTION calls) into
`ComputeStatement.expression_tree`; the raw `.expression` string is
byte-identical to before, and a failed tree build degrades to `None`
(never a new error/warning). The IF parser's condition machinery was
factored into `parsers/statements/_conditions.py`
(`build_condition_expression`) and is reused by the PERFORM parser:
`PERFORM ... UNTIL` raw-string conditions gain a structural
`condition_tree` (see [ast-models.md](ast-models.md)); the IF fallback
path (class/sign/condition-name conditions like `A IS NUMERIC`) now
produces a structured node while `metadata.raw_condition` stays
populated. Pinned by
`tests/regression/test_open_findings_m12_regression.py`.

**`>=`/`<=`/`<>` mis-parsed as `>`/`<`/`<` with a garbled operand
(2026-08-04, found writing Phase 4 of `gen-fixtures`):** the lexer emits
these as two separate single-character tokens (`>` then `=`, never a
combined `>=`) -- confirmed empirically, not assumed. `_conditions.py`'s
token-cleaning pass only recombined `NOT`-prefixed pairs (`NOT EQUAL`, `NOT
<`, ...), so the comparison scan matched the bare `>`/`<` first and left the
trailing `=`/`>` dangling in the right-hand operand text: `IF WS-X >= 5`
parsed as `operator="GREATER", right_operand="= 5"` instead of
`operator="GREATER_OR_EQUAL", right_operand="5"`. This affected every
consumer of `build_condition_expression` (IF and PERFORM UNTIL both), for
as long as M12 has existed -- not a regression from this fix, a
pre-existing gap this fix closes. `_COMPOUND_SYMBOL_OPS` (`{">=", "<=",
"<>"}`) now recombines the pair during the same cleaning pass, before the
`NOT`-prefix check's sibling logic runs. See
[analysis.md](analysis.md)'s `ConstraintExtractor` section for how this was
found; covered by the existing IF/PERFORM/shamrice/NIST suites (783 tests,
zero regressions) plus `tests/unit/analysis/test_constraints.py`'s
`test_greater_less_and_or_equal`.

# Generic swallow-sweep regression (2026-07-21)

Every Silent-Drop Audit section above (2026-07-05 through 2026-07-09) was
found by hand-rolling the same probe per verb: "period-less statement X,
immediately followed by a marker statement — does the marker survive?"
`tests/regression/test_swallow_sweep.py` formalizes that probe as a
permanent, self-maintaining sweep instead of a one-off manual audit:

* One `Fixture(node_type, snippet, needs_file)` entry per class registered
  in `create_statement_registry()` (46 as of this writing), keyed by parser
  class name. Each `snippet` is a minimal, period-less statement (with an
  explicit `END-IF`/`END-EVALUATE`/`END-SEARCH` for scope-taking statements,
  so the boundary being probed is "does the statement stop at its own scope
  terminator without a trailing period," not "does it ever terminate at
  all").
* `test_fixture_table_covers_every_registered_parser` diffs the fixture
  table's keys against `create_statement_registry().get_all_parsers()`, so a
  future statement parser added with no matching fixture fails the suite
  immediately — the whole point being that this sweep covers new verbs
  automatically instead of waiting for the next manual audit.
* `test_marker_survives_after` builds each fixture into a full program,
  parses it, and asserts against **`CobolParagraph.statements`** (the flat,
  source-order list `add_statement()` appends to) — not the tree-wide
  `CobolProgram.get_all_statements()`. This distinction matters: a swallowed
  marker isn't deleted, it's absorbed as a *child* of the statement under
  test (folded into an expression string, or nested into a THEN/WHEN/AT END
  body), and `get_all_statements()` deliberately recurses into exactly those
  bodies (see its docstring above), so it would still find the marker and
  report a false pass. `CobolParagraph.statements` only reflects what the
  PROCEDURE DIVISION parser itself treated as separate top-level statements,
  so a swallowed marker simply never appears there — confirmed by a
  canary test (`TestHarnessDetectsSwallowing`) that reproduces this exact
  false-pass mode with an intentionally unclosed `IF`, and by manually
  disabling `MoveStatementParser`'s boundary check during development (one
  targeted failure, no collateral damage across the other 45 fixtures).
* **A fixture only guards a real vulnerable path, not just "the parser
  runs."** ADD/SUBTRACT/MULTIPLY/DIVIDE's plain scalar-target form (`ADD 1
  TO WS-A`) turned out to be safe-by-construction — a single bare
  `IDENTIFIER` target is consumed in one shot regardless of how (or whether)
  the trailing-boundary check is wired, so no plausible regression there
  would ever touch the marker. Confirmed by mutating
  `_consume_arithmetic_target`: the fixture stayed green. The four
  arithmetic fixtures were redesigned around a subscripted `GIVING` target
  (`ADD 1 TO WS-A GIVING WS-C (WS-IDX)`) to route through
  `consume_optional_subscript` (`_utils.py`) — the shared paren-depth loop
  every arithmetic verb's `GIVING` clause uses, and the one with real
  historical swallow bugs (see the ADD/SUBTRACT subscripted-target entries
  above). Disabling that loop's `depth == 0` stop condition made all four
  fixtures fail together with zero collateral damage elsewhere, confirmed
  and reverted. General lesson for adding future fixtures: prefer a snippet
  shape that exercises a loop/boundary-check, not just a single
  unconditionally-consumed token — a mutation test against the real parser
  is the way to check.

# Statement-Support Verification Sweep (2026-07-22/23)

A fresh verification pass (PR #99, #100, #101 — distinct from, and later
than, the Silent-Drop Audit series above) found nine more real gaps by the
same "does something vanish from the AST with `success==True`?" standard,
this time concentrated on **comma-separated operand lists** and a handful
of unrelated clause-parsing gaps. All pinned by dedicated new test files
(`test_arithmetic_gaps.py`, `test_call_using_comma_omitted.py`,
`test_data_pic_usage_gaps.py`, `test_display_goto_cancel_gaps.py`,
`test_entry_accept_stop_gaps.py`, `test_exec_cics_sql_gaps.py`,
`test_inspect_before_after.py`, `test_io_control_flow_gaps.py`,
`test_set_comma_targets.py`, `test_unstring_gaps.py`).

**Comma-separated lists silently truncated at the first comma.** Seven
independent list-collecting loops accepted a bare `IDENTIFIER`/
`STRING_LITERAL` sequence but treated `TokenType.COMMA` as an unrecognized
token — ending the list (and, where no trailing period followed, leaking
the abandoned names into the procedure scanner as phantom paragraphs).
Fixed by consuming and skipping the comma in each loop, mirroring the
`MOVE` parser's pre-existing target-list handling:
- `call_parser.py` — `CALL ... USING a, b, c` (USING parameters).
  `TokenType.OMITTED` was also missing from both the boundary-check and
  parameter-acceptance type sets, so every parameter *from the first
  `OMITTED` onward* was dropped, not just the placeholder itself
  (`OMITTED` is a legal USING parameter value per the grammar, not merely a
  passing-mode modifier).
- `set_parser.py` — `SET ix1, ix2 UP BY 1` (index/pointer targets).
- `string_unstring_parsers.py::UnstringStatementParser._parse_into_targets`
  — `UNSTRING ... INTO a, b, c` (normal COBOL style with commas).
- `display_parser.py` — `DISPLAY a, b, c` (display items).
- `go_parser.py` — `GO TO a, b, c DEPENDING ON x` (computed GO TO targets);
  previously collapsed to a single unconditional target, silently
  discarding the DEPENDING-selected alternatives.
- `simple_statement_parsers.py::CancelStatementParser` —
  `CANCEL prog-a, prog-b` (program-name list).
- `entry_parser.py` — `ENTRY 'X' USING a, b` (USING parameters); worse than
  the others, the loop's `else` fallback captured the literal `","` token
  itself as a parameter name, corrupting arity rather than merely dropping
  later parameters.

**UNSTRING gained two previously-unimplemented clauses**
(`string_unstring_parsers.py`, `models/statements/data.py`):
`DELIMITED BY d1 OR d2 OR ...` now loops to collect every `OR`-joined
delimiter (`UnstringStatement.delimiters`) instead of keeping only the
first; `TALLYING IN counter` — documented in the parser's own docstring
but never implemented — now populates a new
`UnstringStatement.tallying_variable` field.
`DELIMITED BY ALL x` (2026-09-28): the `ALL` flag used to be consumed and
dropped. `UnstringStatement.delimiter_all` is a bool list parallel to
`delimiters`; `to_dict()` emits it only when some delimiter is `ALL`, so
every other UNSTRING serializes as before.

**Bug hunt round 8 (2026-09-28), five silent drops in statement parsers:**
- `search_parser.py`: the AT END / WHEN loop's fallback consumed any other
  token, so a SEARCH without END-SEARCH nested in an IF ate `ELSE ...
  END-IF` and every statement up to the period. Any token other than
  AT/END/WHEN/END-SEARCH/separator now ends the SEARCH. SEARCH has no
  `NOT AT END`; it is no longer eaten (it used to overwrite the real AT END
  body) but left for the procedure parser's unparsed-token warning.
- `initialize_inspect_parsers.py`: INITIALIZE targets and the REPLACING
  `BY` value fold subscripts / OF-IN qualifiers via
  `consume_optional_qualifiers` (`"TBL ( 1 )"`, `"B OF C"`, the same text
  shape MOVE targets use).
- `_conditions.py`: after `NOT`, the whole relational operator is resolved
  (`_match_relational_operator`) before negating, so `NOT GREATER THAN OR
  EQUAL TO` / `NOT >=` / `NOT > =` is LESS and the `<=` family is GREATER.
  `_NEGATED_OPS` is gone; `_NEGATED_RELATIONAL` does the negation.
- `string_unstring_parsers.py`: `BY` after `DELIMITED` is optional
  (`DELIMITED SIZE`, `DELIMITED "," OR ALL SPACE`). A delimiter is only
  consumed when the next token is operand-shaped (`_next_is_delimiter`), so
  `DELIMITED INTO X` still leaves INTO for its own clause.
- `display_parser.py`: `FUNCTION name[(args)][(refmod)]` is one DISPLAY item
  rendered as MOVE renders it (`"FUNCTION TRIM(A)"`), not a bare
  `"FUNCTION"` item followed by the call.
Pinned in `tests/unit/test_start_search_set_coverage.py`,
`test_initialize_inspect_parsers.py`, `test_if_parser_gaps.py`,
`test_string_simple_deeper_coverage.py`, `test_unstring_gaps.py`,
`test_display_parser.py`.

**EXEC CICS lost its command verb when written on the line after `EXEC
CICS`** (`ibm_exec_statements.py`) — the idiomatic, most common layout
(and the parser's own docstring example). The command-token lookup ran
before skipping intervening `NEWLINE`/`WHITESPACE` tokens, so the verb was
misfiled as a bogus options key. Fixed by skipping layout tokens first.
Separately, EXEC SQL/DLI raw-text reconstruction inserted a spurious space
when rejoining a lexer-split `>=`/`<=`/`<>` relational operator (each lexes
as two adjacent tokens), corrupting WHERE-clause text fidelity.
The same column-adjacency rule (`_follows_qualifier_period`, 2026-09-23) keeps
a qualified name together: `BANK.ACCOUNT` used to come back as
`BANK. ACCOUNT`, while a period written with a space (`T. X`) keeps it.
2026-09-28: `collect_exec_sql_text(stream, sql=True)` (the EXEC SQL callers
only) re-quotes string literals and drops `--` line comments -- see
[dialects.md](dialects.md) "EXEC SQL text: literals and `--` comments".

**`INSPECT` `TALLYING`/`REPLACING` `BEFORE`/`AFTER INITIAL` qualifiers**
(`initialize_inspect_parsers.py`): the original 2026-07-07 implementation
accepted only one qualifier per FOR-phrase, in a fixed BEFORE-then-AFTER
order. COBOL allows **both** qualifiers on the same phrase, in **either**
order (IBM Enterprise COBOL). Refactored into a shared `_parse_before_after`
helper that loops until neither qualifier matches (each captured at most
once), used by both `_parse_tallying` and `_parse_replacing`.

2026-09-27 follow-up: `_parse_before_after` now reads its delimiter through
`_consume_inspect_value`, so `BEFORE INITIAL SPACE` (a figurative constant)
and `AFTER INITIAL ENT(2)` are taken whole -- previously SPACE was left in
the stream and every later TALLYING counter clause was silently dropped. A
subscripted TALLYING counter (`CNT(2) FOR ...`) is folded in too, and
`CONVERTING` takes subscripted/figurative operands and keeps its
BEFORE/AFTER phrase as `converting_before` / `converting_after` (emitted in
`to_dict()` only when present; read by unused-variables and xref).

**`PIC N(n)` (national/DBCS fields) sized as 1 regardless of `n`**
(`models/data_items.py::PictureClause`): the size-inference cascade had a
branch for `X`/`A` (alphanumeric/alphabetic) patterns but none for `N`
(national), so `PIC N(n)` fell through every numeric/alphanumeric branch to
the final "no match" default of size 1. Added an `N`/`N(n)` branch
mirroring the `X`/`A` one — one character position per `N`, no
double-byte/DBCS byte-doubling (this codebase has no existing DBCS/code-page
convention to build on, so single-width counting was the more defensible
choice absent one).

**`USAGE IS <keyword>` silently downgraded to plain `DISPLAY`**
(`divisions/data_clauses.py`): the USAGE clause parser never consumed the
optional `IS` token before the usage keyword, so `USAGE IS NATIONAL` /
`USAGE IS INDEX` / `USAGE IS DISPLAY-1` left `IS` unconsumed and fell
through without recognizing the keyword after it. `USAGE DISPLAY-1` (no
`IS` at all) had the same failure for a different reason: `DISPLAY-1`
lexes as its own dedicated `TokenType` that the clause parser's keyword set
never checked.

**`START ... KEY IS GREATER THAN OR EQUAL TO key-name`** (`start_parser.py`):
the trailing `TO` after `OR EQUAL` was never consumed — it arrives as a
dedicated `TokenType.TO` token, not an `IDENTIFIER`, so the existing
value-based keyword matching skipped over it, leaving it to block the
key-name `IDENTIFIER` check (which only matches `TokenType.IDENTIFIER`)
and everything that should follow: the key-name itself, `INVALID KEY`,
`NOT INVALID KEY`. All silently failed to parse — not just truncated.

**`WRITE ... AT END-OF-PAGE` / `NOT AT END-OF-PAGE`** (`write_parser.py`,
`models/statements/io.py`): format-1 (sequential/line-sequential file)
clause was entirely unimplemented — only format-2's `INVALID KEY`/
`NOT INVALID KEY` (indexed/relative files) was handled. Added
`IOWriteStatement.set_at_eop_clause`/`set_not_at_eop_clause` (the former
already existed as a field but nothing populated it) parsed the same way
READ's `AT END`/`NOT AT END` is, via `collect_clause_stmts`. Both branches
are attempted regardless of file organization — nothing upstream of the
parser knows which SELECT clause governs the record being written, and the
two clause families are mutually exclusive in real programs by the
standard's own grammar, so attempting both is safe.

**`OPEN` with multiple mode groups collapsed every file onto the first
group's mode** (`models/statements/io.py::IOOpenStatement`): `open_mode`
only ever reflects the *first* `INPUT`/`OUTPUT`/`I-O`/`EXTEND` group (see
"Multi-mode OPEN" above, 2026-07-05) — for `OPEN INPUT FILE-A OUTPUT
FILE-B`, a caller reading `open_mode` alone cannot tell `FILE-B` is really
`OUTPUT`. Added `IOOpenStatement.file_modes: dict[str, str]` (file name →
its own mode group's keyword), populated by a new optional `mode` parameter
on `add_file()`. **Known follow-up, out of scope for this fix:**
`analysis/crud_matrix.py` and `analysis/io_logger.py` still read
`.open_mode` alone for every file in a statement; they have not yet been
updated to consult `file_modes`.

**Arithmetic: `ROUNDED`, multi-target lists, `CORRESPONDING`, `DIVIDE
REMAINDER`** (`arithmetic_parsers.py`, `models/statements/arithmetic.py`):
- `ADD`/`SUBTRACT` never checked for `ROUNDED` at all (only `COMPUTE`
  consumed it — and only to discard it, never storing it).
  `ArithmeticStatement.rounded` and `ComputeStatement.rounded` are now
  populated by `set_rounded()`; `ArithmeticStatement.to_dict()` grew a
  matching `is_corresponding` flag (see below).
- `ADD`/`SUBTRACT` only captured a **single** target even though COBOL
  allows a comma/space-separated list (`ADD 1 TO a, b, c`) — extra targets,
  their per-target `ROUNDED` flags, and downstream `SIZE ERROR` handling
  were all lost for anything past the first. `ArithmeticStatement.target`
  (first target, back-compat) is now joined by `ArithmeticStatement.targets`
  (the full ordered list); `set_target()` appends to both.
- `DIVIDE ... REMAINDER r` was entirely unimplemented — the `REMAINDER`
  keyword and its target were left unconsumed. Added
  `DivideStatement.remainder`, set via `set_remainder()`.
- `ADD`/`SUBTRACT CORRESPONDING` (`ADD CORRESPONDING a TO b`) was misparsed
  as a literal operand *named* `"CORRESPONDING"` instead of being
  recognized as the `CORRESPONDING`/`CORR` keyword. Added
  `ArithmeticStatement.is_corresponding`, set via `set_corresponding()`.
- **Self-review fix, same PR:** the new multi-target loop could itself
  swallow a following paragraph header as a bogus extra target when the
  ADD/SUBTRACT statement's period was missing — the header vanished from
  the AST with no warning. Now stops at `looks_like_paragraph_boundary`
  and records the H9-pattern warning, same as `MoveStatementParser` (see
  H9 above).

**`DISPLAY ... UPON device-name` dropped everything after the device name**
(`display_parser.py`): the UPON branch unconditionally `break`s after
consuming the device token, so a legal trailing clause
(`DISPLAY x UPON CONSOLE WITH NO ADVANCING`) was dropped, and — because the
loop exited without consuming the sentence period — the period was left in
the stream for the procedure-division scanner to misread as an empty
paragraph named `"."`. Now continues the clause loop (`skip_whitespace` +
`continue`) instead of breaking, matching the non-UPON path's period
handling.

**`ACCEPT ... FROM ENVIRONMENT "name"` dropped the environment-variable
name** (`accept_parser.py`): the pre-existing `IOAcceptStatement.
environment_name` contract field (scaffolded but never wired, per the M3
notes above) is now populated when the FROM source is literally
`ENVIRONMENT`, capturing the following literal/identifier via
`set_environment_name()` instead of letting it fall through to the generic
`from_source` capture (string literal case) or being dropped in the
identifier case.

**`STOP` never consumed its sentence period** (`stop_parser.py`): every
`STOP RUN.` (and every other STOP form) left the trailing period
unconsumed, which the procedure-division scanner then misread as a phantom
empty paragraph named `"."` — the same symptom class as the DISPLAY UPON
and EOF-sentinel bugs in this section. Fixed with a `consume_period()` call
at the end of the parser, matching the pattern already used elsewhere in
the statement parsers.

**EOF sentinel manufactured a phantom trailing paragraph on every program**
(`divisions/procedure.py`): the PROCEDURE DIVISION dispatch loop's
"unknown token → treat as a new paragraph name" fallback checks the
token's value against a keyword-exclusion tuple, but the EOF sentinel
token's value is the empty string, which isn't in that tuple — so once
every real paragraph/section was consumed, the loop fell through and
manufactured a spurious empty-named, zero-statement paragraph at end of
file, on **every** program lacking a final named paragraph header (i.e.
almost all of them). This inflated `get_statistics()["total_lines"]`
(computed as the max AST node line) and `procedure_count` by one. Not
found by this repo's own test suite — surfaced by a backend integration
test (outside this repo) asserting `total_lines` stays within 20% of the
source's real line count. Fixed with an explicit `token.type ==
TokenType.EOF: break` check ahead of the fallback branch. This is the
**third** distinct root cause found to produce a phantom "."-or-empty
trailing paragraph (the other two: DISPLAY UPON above, and STOP's missing
period consumption above) — all three share the same symptom
(`procedure_count` one higher than the real paragraph count, a bogus
zero-statement `CobolParagraph` at the end of the AST) but are unrelated
bugs in different parsers, worth remembering as a recognizable fingerprint
if a fourth instance ever turns up.

**Documentation debt this section closes:** all nine fixes above (commits
`5492c40`, `824f654`, `64ff7b9`, `316f0ce`, `82a82ec`, `68f68c0`,
`ddbc688`, `50b6028`, `4a8daa3`, merged via PR #99, #100, #101) landed on
`main` on 2026-07-22/23 without a matching OKF/`CHANGELOG.md`/
`open-findings.md` update — this section, the corresponding
[ast-models.md](ast-models.md) field notes, [log.md](log.md) entries, and
`CHANGELOG.md` (Unreleased → Fixed) reconcile that gap retroactively.

# Follow-up comma-list sweep: INITIALIZE, SORT/MERGE KEY/USING/GIVING, arithmetic GIVING + format-1 targets (2026-07-24)

While auditing the repo for outstanding gaps (user request: "make sure
there is no gaps in the cobolparser"), re-verified the comma-truncation
bug class the 2026-07-22/23 sweep above fixed in CALL/SET/UNSTRING/
DISPLAY/GO TO/CANCEL/ENTRY against the parsers that sweep didn't touch,
using the same repro method (`parse_cobol()` against a minimal program,
inspect `ParseResult.errors`/`.warnings` and the resulting AST). Found and
fixed five more real instances (four from the repro sweep, a fifth from a
second-opinion review of this same pass — see below) — all pinned by
`tests/unit/test_initialize_sort_arithmetic_comma_gaps.py`:

* **`INITIALIZE id-1, id-2, ...`** (`initialize_inspect_parsers.py`): the
  target-collection loop broke on `TokenType.COMMA` (a warned drop — every
  target after the first comma was lost). Fixed by skipping the comma and
  continuing, same pattern as the other comma fixes.
* **`SORT`/`MERGE` `{ASCENDING|DESCENDING} KEY field-1, field-2 ...`**
  (`sort_merge_parsers.py::_parse_keys`, shared by both statements): the
  field-collection loop's `else: break` fired on `TokenType.COMMA` —
  **and unlike every other instance of this bug class, with no warning at
  all** (`errors=[], warnings=[]`): the field simply vanished from
  `SortStatement.keys`/`MergeStatement.keys`. Worse in a second way too:
  because the comma-truncated inner loop returned control to the outer
  clause loop with the comma token still unconsumed, and that outer loop's
  `else: token_stream.consume()` fallback silently eats one token at a
  time with no boundary check, a `USING`/`GIVING` clause immediately
  following the truncated KEY list could itself be partially consumed as
  noise before the outer loop's keyword checks ever saw it intact,
  depending on exact spacing — not separately confirmed as a live
  secondary symptom, but a real risk the comma fix also closes by
  construction (the inner loop never returns with an unconsumed comma
  anymore).
* **`SORT`/`MERGE` `USING file-1, file-2 ...` / `GIVING file-1, file-2
  ...`** (`sort_merge_parsers.py::_parse_file_list`, shared by both
  statements and by both the USING and GIVING clauses): same `else:
  break`-on-COMMA defect, same fully-silent symptom.
* **`ADD`/`SUBTRACT`/`MULTIPLY`/`DIVIDE ... GIVING id-3 [ROUNDED] [id-4
  [ROUNDED]] ...`** (`arithmetic_parsers.py`,
  `models/statements/arithmetic.py`): the standard grammar allows GIVING
  to carry a comma/space-separated list of result targets (each value
  computed once, stored to every target) — symmetric with the TO/FROM
  target list already fixed for ADD/SUBTRACT in the 2026-07-22/23 sweep,
  but that fix only extended the TO/FROM side; GIVING still used
  `consume_keyword_and_operand`, which returns a single string and had no
  list-continuation logic (a warned drop: extra GIVING targets triggered
  the generic "Unparsed tokens" warning). Fixed by adding
  `ArithmeticStatement.givings: list[str]` (mirrors the existing `target`/
  `targets` split — `.giving` keeps the first for back-compat) and a new
  `_consume_additional_giving_targets` helper, mirroring
  `_consume_additional_arithmetic_targets`'s comma/space/ROUNDED/
  paragraph-boundary-guard logic exactly, called after the first GIVING
  target is captured in all five call sites (ADD's TO and GIVING branches,
  SUBTRACT's FROM and GIVING branches, and the shared MULTIPLY/DIVIDE
  `_parse_binary_arithmetic`). DIVIDE's `REMAINDER` clause (which follows
  GIVING) is in the new helper's stop-keyword set so it isn't swallowed as
  a bogus extra GIVING target.

**Fifth instance, found by a second-opinion review of this pass rather
than by the corpus/repro sweep above:** MULTIPLY/DIVIDE format 1 (no
GIVING) has the identical multi-target gap on its *own* side, not just
GIVING's. Format 1 (`MULTIPLY x BY id-2 [ROUNDED] [id-3 [ROUNDED]] ...` /
`DIVIDE x INTO id-2 [ROUNDED] [id-3 [ROUNDED]] ...`) overwrites its second
operand(s) in place — unlike format 2 (GIVING), where the second operand
is just a multiplicand/divisor left untouched — so it is itself a
comma/space-separated target list, and `_parse_binary_arithmetic` only
ever consumed a single second operand via `_consume_arithmetic_operand`
(warned drop for anything after a comma). Fixed by having
`_parse_binary_arithmetic`, when no GIVING clause follows, additionally
call `stmt.set_target(second_operand)` (seeding `.target`/`.targets` —
new for MULTIPLY/DIVIDE, previously these only ever appeared in
`.operands` as untyped strings) and then reuse the *same*
`_consume_additional_arithmetic_targets` helper ADD/SUBTRACT's TO/FROM
list already uses, rather than writing a parallel implementation.
Deliberately scoped to the no-GIVING branch only: format 2 (GIVING) must
**not** gain a spurious `.target` — the second operand there is not a
result — verified by an explicit regression case
(`test_divide_format2_giving_unaffected_by_format1_fix`).
`_ADDITIONAL_TARGET_STOP_KEYWORDS` (shared with ADD/SUBTRACT's TO/FROM
list) gained `"REMAINDER"` so DIVIDE's tolerated no-GIVING
`DIVIDE x INTO y REMAINDER r` form (see the REMAINDER note above) doesn't
have its REMAINDER clause swallowed as a bogus extra target — safe to add
to the shared set since REMAINDER is a COBOL reserved word and can never
be a legal ADD/SUBTRACT target data-name either. The `_BinaryArithmeticNode`
structural `Protocol` (used to type-check the shared MULTIPLY/DIVIDE
helper against both node classes without a common base class) gained
`set_target` alongside its existing `add_operand`/`set_giving`/
`set_rounded` methods.

**Targeted follow-up round (still 2026-07-24), scoped by user decision:**
after presenting the five fixes above, checked the remaining known
list-collecting loops in the parser (per the enumeration in the
2026-07-08 "unsupported-verb boundary gap" audit above) for the same
comma-truncation property. Two more real, live bugs found and fixed,
pinned in the same test file; two candidates checked and confirmed to
need no fix:

* **`CALL ... USING BY REFERENCE|CONTENT|VALUE` mode does not persist
  across a comma-separated parameter list within one BY-phrase group**
  (`call_parser.py::_parse_using_clause`): `passing_mode = "REFERENCE"`
  was reset at the top of *every* loop iteration (i.e. every parameter),
  not just when a fresh `BY` keyword was actually seen. `CALL 'P' USING
  BY CONTENT a, b` — comma-separated within the same BY CONTENT group —
  correctly tagged `a` as CONTENT but silently mode-tagged `b` back to
  the REFERENCE default. Not a data-drop (both parameter *names* survived
  intact), but a silent semantic corruption: `b` would need to be passed
  by content (a copy) but was recorded as passed by reference (the actual
  variable), a distinction that matters for whether the called program
  can mutate the caller's data. Fixed by initializing `passing_mode` once
  before the loop instead of inside it, so it only changes when a `BY`
  keyword is actually encountered.
* **`COMPUTE id-1, id-2 = expr` (comma-separated multi-target) was a hard
  parse failure**, not a silent/warned drop (`arithmetic_parsers.py`,
  `ComputeStatementParser.parse`'s additional-target loop): unlike every
  other instance in this bug class, the target-collection loop had *no*
  comma handling at all — a comma was left unconsumed, the loop broke
  immediately (comma is neither ROUNDED nor an IDENTIFIER target), and
  the subsequent `if token.value == "=": ...` check saw the comma instead
  and reported `ParseError("COMPUTE statement missing '=' operator")`
  with **no** `ComputeStatement` node produced at all — a full parse
  failure (`result.success == False`), worse than every other fix in
  this file's bug class. Fixed with the same comma-skip pattern as the
  other loops.
* **Checked and found NOT to need a fix:** SEARCH's WHEN-condition
  collector (each `WHEN` clause takes exactly one condition — no list in
  the grammar) and READ/WRITE's `INTO`/`FROM` clauses (each takes exactly
  one identifier — also no list). Verified by direct `parse_cobol()` repro
  before concluding, not by grammar inspection alone.

**Methodology note:** the first draft of the SORT/MERGE regression test
used a single long fixture line that itself exceeded fixed-format column
72 (`normalize_fixed_format` truncates columns 73+, per this repo's own
documented, GnuCOBOL-verified semantics — see the PICTURE-clause
column-72 entry above) — this produced a `giving_files: ['WS']`-shaped
truncation that looked like a fifth parser bug but was purely a test-
fixture artifact (line too long), confirmed via direct lexer/column
inspection before concluding so. Fixed by wrapping the fixture across two
lines rather than changing any parser code — a reminder that this
column-72 gotcha applies to test fixtures using this repo's usual
7-space/Area-B indentation, not just to real-world source.

## COMPUTE expression precedence: `_parse_unary` merged with `_parse_signed_primary` (2026-09-10)

`arithmetic_parsers.py`'s expression grammar, tightest-binding first:
`_parse_primary` (literal/identifier/parenthesized/FUNCTION) →
`_parse_power` (`**`, left-associative — `2 ** 3 ** 2` is `(2 ** 3) ** 2 ==
64`, not `2 ** 9`) → `_parse_unary` (leading `+`/`-`) → `_parse_term`
(`*`/`/`) → `_parse_additive` (`+`/`-`). The exponent on the right of `**`
may itself carry a sign (`2 ** -3`), but must not itself absorb a further
`**` — that would make `2 ** -3 ** 2` group as `2 ** (-(3 ** 2))` instead of
the correct `2 ** (-3)`, since a repeated `**` is `_parse_power`'s own loop,
not `_parse_unary`'s concern. This used to be a second, hand-copied method
(`_parse_signed_primary`, identical to `_parse_unary` except its
non-sign fallback called `_parse_primary` directly instead of descending
through `_parse_power`) — now one method, `_parse_unary(fallback=None)`:
`fallback` is `_parse_power` by default and `_parse_primary` for the `**`
right-hand-side call, threaded through the sign-recursion so a chain of
signs (`- - -3`) keeps the same fallback throughout. Behavior unchanged —
`tests/regression/test_review_2026_09_09_generators.py::TestFinding9PowerAssociativity`
(`2 ** 3 ** 2 == 64`, `2 ** (3 ** 2) == 512`, `100 * 2 ** -1 == 50`) still
passes unmodified. (2026-09-28: that last case now folds to nothing -- IBM
truncates `2 ** -1` to 0 decimal places into an integral target; see
analysis.md's ConstantFolder section.)

## `PROCEDURE DIVISION USING` now captures each parameter's passing mode (2026-09-10)

`BaseDivisionParser.parse()` (`divisions/base.py`) already walked the header
clause tokens up to the terminating period to collect bare parameter names
into the `using_parameters` metadata list (`ast_node.set_metadata
("using_parameters", [...])`) — this is what makes the implicit entry
interface visible to `LinkageChecker` at all. It skipped over `BY`/`VALUE`/
`REFERENCE` tokens as non-data-names but never recorded *which* mode a
parameter was declared under. A second metadata key,
`using_parameter_modes: dict[str, str]` (name upper → `"VALUE"`/
`"REFERENCE"`), now tracks a `current_mode` that starts at COBOL's own
`"REFERENCE"` default and flips on each `VALUE`/`REFERENCE` keyword seen
(`BY` itself is a pure connector, no state change) — so `PROCEDURE DIVISION
USING BY REFERENCE LK-A BY VALUE LK-B LK-C` yields `{"LK-A": "REFERENCE",
"LK-B": "VALUE", "LK-C": "VALUE"}` (mode carries forward until it switches
again). Backs `LinkageChecker`'s new `PASSING_MODE_MISMATCH` check — see
[analysis.md](analysis.md)'s LinkageChecker section.

## `SET`'s multi-group ENTRY-form flag was not reset per group (2026-09-10)

`SetStatementParser._entry_form` (set by `_parse_action` when a value is
introduced by `ENTRY`, read right after to call `stmt.set_metadata
("value_is_entry", True)` for the *first* `targets TO/UP/DOWN value` group)
was reset to `False` once, before that first group's `_parse_action` call,
but never again before parsing a later group in the same multi-group SET
(`SET SW-1 TO ON SW-2 TO OFF`-shaped statements, 2026-07-24). A first
group's `SET p TO ENTRY 'X'` would leave the flag set for every later
group's own `_parse_action` call, and there was nowhere to even put a
later group's own answer: `SetStatement.add_group()` had no `is_entry`
parameter at all. Fixed on both ends — the flag is now reset before each
group's `_parse_action` call, and `add_group(..., is_entry=self._entry_form)`
records it per group as the additive `"value_is_entry"` group-dict key (see
[ast-models.md](ast-models.md)).

# EJECT compiler-directing statement was unrecognized (2026-08-05)

`EJECT` (the source-listing page-eject directive — not the column-7 `/`
page-eject comment convention, which was already handled; see
[lexer.md](lexer.md)'s "Unified tokenize pipeline" section) had no
`TokenType`, no `KEYWORDS` entry, and no registered statement parser, so it
lexed as a bare `TokenType.IDENTIFIER`. Two failure modes, both found by
direct repro against `parse_cobol()`:

* **`EJECT.` (trailing period, the common real-world style) was misread as
  a new paragraph header.** `is_paragraph_or_section_start`
  (`procedure_boundaries.py`) treats an `IDENTIFIER` token followed by a
  period as a paragraph name — indistinguishable from a real one at the
  token-type level. `MAIN-PARA. ... EJECT. SECOND-PARA. ...` silently
  became three paragraphs (`MAIN-PARA`, an empty bogus `EJECT`, and
  `SECOND-PARA`) instead of two, splitting `MAIN-PARA`'s own statements
  across the phantom boundary.
* **`EJECT` with no trailing period fell through to the "unsupported
  statement" recovery path** (`procedure_recovery.py`), which does not
  recognize it as a real, known-but-unimplemented verb (it isn't in
  `UNSUPPORTED_VERBS`) and so emits the more alarming generic warning:
  `"Unparsed tokens starting at 'EJECT' ... clause or statement not fully
  supported; content dropped from the AST up to the next statement
  boundary"` — misleading, since EJECT is a well-defined no-op, not
  malformed input. (The following statement itself was not actually
  swallowed in this case — `skip_to_next_statement` stops as soon as it
  reaches the next registered statement keyword — but the spurious warning
  made an otherwise-clean parse look broken.)

Both failure modes reproduce identically when EJECT arrives via
COPY-expanded copybook text (common: copybooks holding shared/common
paragraphs, or multiple record layouts, often use EJECT between sections
for print-listing formatting) — expansion flattens the copybook into the
surrounding source before the lexer ever sees it, so there is nothing
copybook-specific to fix separately.

Fixed the same way `CONTINUE` (a genuine no-op statement) is handled:
`TokenType.EJECT` + a `"EJECT"` `KEYWORDS` entry (`lexer.py`) so it can
never be mistaken for an `IDENTIFIER`-typed paragraph name; added to
`STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` (`_utils.py`) so the
boundary-detection guards across every other statement parser's
trailing-token loop recognize it as a known verb (same bug class the
2026-07-08 "unsupported-verb boundary gap" audit above fixed for
DISABLE/ENABLE/COMMIT/ROLLBACK/etc.); a new `EjectStatementParser` ->
`EjectStatement` no-op AST node (`simple_statement_parsers.py` /
`models/statements/misc.py`), registered in `create_statement_registry()`
right after `ContinueStatementParser`. Pinned by
`tests/regression/test_eject_statement.py` (bogus-paragraph-splitting via
both a plain trailing period and copybook expansion; the swallow-sweep
period-less boundary check; consecutive EJECTs; AST node shape) and by two
completeness guards that would otherwise fail on an unfixtured new parser:
`tests/unit/test_procedure_registry_dispatch_order.py` (`EXPECTED_ORDER`,
`DISPATCH_CASES`) and `tests/regression/test_swallow_sweep.py` (`FIXTURES`).

# INVOKE / ALLOCATE / FREE now have registered parsers (2026-08-05)

All three were real, valid IBM Enterprise COBOL verbs previously listed in
`UNSUPPORTED_VERBS` (`procedure_recovery.py`): `INVOKE` for Object-Oriented
COBOL method calls, `ALLOCATE`/`FREE` for dynamic storage. A program using
any of them parsed "successfully" with an incomplete AST — the statement's
tokens were discarded up to the next boundary with only a warning as a
trace, so `find_all_by_type`/`get_all_statements` never saw it.

* **`invoke_parser.py` -> `InvokeStatement`
  (`models/statements/misc.py`).** Syntax: `INVOKE object-identifier-1
  {identifier-2 | literal-1} [USING [BY REFERENCE|CONTENT|VALUE]
  {identifier-3 | literal-2} ...] [RETURNING identifier-4] [END-INVOKE]`.
  `object_name` (the object reference, typically `SELF`/`SUPER`/an `OBJECT
  REFERENCE` data item), `method_name` + `method_is_literal` (a literal
  method name or an identifier holding one), `using_parameters` (reuses
  `CallParameter` from `models/statements/call.py` — same
  name/passing-mode shape as CALL's USING clause, including `BY
  REFERENCE|CONTENT|VALUE` mode persistence across a comma-separated
  parameter group), and `returning_target`. No `ON EXCEPTION`/`ON OVERFLOW`
  handler clauses — unlike CALL, INVOKE's grammar doesn't have them.
  Registered right after `EntryStatementParser` (both are CALL-adjacent).
* **`allocate_free_parsers.py` -> `AllocateStatement`/`FreeStatement`
  (`models/statements/misc.py`).** `ALLOCATE {identifier-1 CHARACTERS |
  identifier-2} [INITIALIZED] [RETURNING identifier-3]` —
  `is_characters`/`size_expr` for the byte-count form (identifier or numeric
  literal), `data_item` for the `BASED` data-item form, `initialized`,
  `returning_target`. `FREE identifier-1 [identifier-2] ...` — one or more
  `pointer_names`. Both registered in the "Minimal/rare verbs" group, right
  after `UseStatementParser`.

  **Deliberately no lexer `TokenType` for ALLOCATE/FREE.** Unlike INVOKE
  (which already had `TokenType.INVOKE` from before this fix), ALLOCATE and
  FREE are recognized purely by value — `matches()` checks `token.type ==
  IDENTIFIER and token.value.upper() == "ALLOCATE"` directly (a bespoke
  helper, `_matches_bare_verb`, mirroring how `XmlJsonStatementParser`
  recognizes bare `"XML"`/`"JSON"` — see `xml_json_parser.py`) rather than
  reserving the word globally via `KEYWORDS`. This keeps a data item
  legitimately named `ALLOCATE`/`FREE` usable as an ordinary `IDENTIFIER`
  everywhere except a genuine statement-start position, the same tradeoff
  the dead-`KEYWORDS`-entry removal above is about.

  **Known limitation, not introduced by this fix:** a paragraph named
  exactly `FREE.`/`ALLOCATE.` (nothing else on that line) is ambiguous with
  a zero-operand FREE/ALLOCATE statement; `ProcedureDivisionParser`'s
  `is_statement_keyword` check (`procedure_boundaries.py`) — which already
  treated both words as known statement keywords via `STATEMENT_KEYWORDS`,
  independent of whether a parser existed — resolves this in favor of the
  statement reading, folding what should be two named paragraphs into one
  implicit unnamed paragraph. This ambiguity already existed for every other
  bare-word verb with no dedicated `TokenType` and no registered parser
  before this fix (`PURGE`, `RESUME`, ...); what changed is that ALLOCATE/
  FREE no longer hit the severe pre-existing failure mode documented below
  when used this way — no statement content is lost and (critically) the
  parse **terminates**, where it previously did not. The parse is correctly
  flagged `result.success is False` in this shape (see the required-operand
  validation below), rather than silently succeeding.

  **Required-operand validation (2026-08-05, Copilot review on PR #113):**
  all three parsers initially followed the lightweight "Minimal/rare verbs"
  style of tolerating a missing operand by leaving the corresponding field
  `None`/empty with no diagnostic — indistinguishable from `result.success ==
  True` on genuinely malformed input, which undercuts the whole point of
  fixing these verbs. Brought in line with `MoveStatementParser`'s established
  precedent (`move_parser.py`, audit finding H3 — "MOVE silently accepted
  malformed/incomplete input") via the same `report_parse_error` +
  `get_parse_context` mechanism: `INVOKE` now requires both an object
  identifier and a method name (either check failing reports a specific error
  and returns immediately, mirroring MOVE's missing-`TO` bail-out);
  `ALLOCATE` requires its first operand (a size expression or a `BASED` data
  item); `FREE` requires at least one pointer identifier (checked *after* the
  collection loop, so `FREE.` reports the error while `FREE WS-PTR.` does
  not — mirrors MOVE's post-loop `target_count == 0` check). A second review
  comment on the same PR caught that `InvokeStatement.set_method_name()`
  only added the method name to `operands` when it was identifier-held,
  inconsistent with `CallStatement.set_called_program()` (`call.py`), which
  records its program name regardless of whether the CALL is static
  (literal) or dynamic — fixed to always record the operand. Pinned by
  `test_invoke_missing_object_identifier_reports_error`,
  `test_invoke_missing_method_name_reports_error`,
  `test_invoke_literal_method_name_recorded_as_operand`,
  `test_allocate_requires_an_operand`, and
  `test_free_requires_at_least_one_pointer` in
  `tests/regression/test_invoke_allocate_free_statements.py`.

  **Related, separate discovery — not fixed here:** a paragraph (or a
  trailing operand of another statement, e.g. `DISPLAY PURGE`) named after a
  `STATEMENT_KEYWORDS` word with **no** registered parser and **no**
  dedicated `TokenType` (`PURGE`, `RAISE`, `RESUME`, `DISABLE`, `ENABLE`,
  `RECEIVE`, `SEND`, `SERVICE`, `SUPPRESS`, `TERMINATE`, `ENTER`,
  `INITIATE`, `NOTE`, `RECOVER`, `RESET`, `READY`) hangs `parse_cobol()`
  indefinitely (confirmed against the unmodified parser: `PROCEDURE
  DIVISION. PURGE. DISPLAY '...'.` never returns — killed after 2m17s of
  100% CPU and multi-GB memory growth). This predates and is unrelated to
  this fix; it is not yet tracked by a regression test or filed issue.

Pinned by `tests/regression/test_invoke_allocate_free_statements.py`,
extended cases in `tests/regression/test_tier5_silent_drip_audit.py`
(`TestInvokeAllocateFreeNoLongerSwallowed`... covers the CALL-handler-body
position too) and `tests/regression/test_tier7_unsupported_verb_boundary.py`
(`TestInvokeAllocateFreeNoLongerSwallowed`), and the two completeness guards
every new parser must satisfy: `tests/unit/test_procedure_registry_dispatch_order.py`
(`EXPECTED_ORDER`, `DISPATCH_CASES`) and `tests/regression/test_swallow_sweep.py`
(`FIXTURES`).

**Leading `IS` of `[IS] EXTERNAL`/`[IS] GLOBAL`, and missing `IS` on
`SYNCHRONIZED`/`JUSTIFIED` (`divisions/data_clauses.py`, 2026-08-07):**
`EXTERNAL`/`GLOBAL` are written `[IS] EXTERNAL`/`[IS] GLOBAL` — `IS` comes
*before* the clause keyword, unlike `PICTURE`/`VALUE`/`USAGE`/`SIGN`, where
an optional `IS` follows the keyword and is consumed inside that clause's own
parse method. The main dispatch loop had no branch for a bare `IS` token, so
it fell into the generic drop-with-warning case even on fully standard
syntax — `EXTERNAL`/`GLOBAL` still parsed correctly on the next loop
iteration (so `is_external`/`is_global` were set right and
`result.success` stayed `True`), but every such data item picked up a
spurious "Unparsed token 'IS' ... clause not fully supported" warning.
`SYNCHRONIZED IS LEFT`/`JUSTIFIED IS RIGHT` had the mirror-image gap: the
clause keyword consumed itself but never checked for a following `IS`,
which then also stranded `LEFT`/`RIGHT` as a second dropped token (neither
matches any dispatch branch on its own). Fixed by adding a peek-ahead
branch on `TokenType.IS` that consumes it when the next token is
`EXTERNAL`/`GLOBAL`, and `IS` consumption to the `SYNCHRONIZED`/`JUSTIFIED`
branches, mirroring the existing `SIGN` clause's `[IS]` handling. Pinned by
`TestExternalGlobalClauses.test_leading_is_does_not_warn` and
`TestSynchronizedJustifiedIsClause` in
`tests/regression/test_parser_completeness.py`.

# Core audit fixes (2026-08-12)

All pinned by `tests/regression/test_audit_2026_08_12_core.py`.

* **MOVE source join (P-B1, `move_parser.py`):** `_parse_source` collected
  its tokens correctly but rendered them with `"".join`, corrupting every
  multi-token source: `MOVE WS-A OF WS-GRP ...` produced
  `source == "WS-AOFWS-GRP"`, `MOVE FUNCTION UPPER-CASE(WS-X) ...` produced
  `"FUNCTIONUPPER-CASE(WS-X)"`. Now rendered via `_join_source_parts`:
  words space-separated, no space around parens/before commas
  (`TBL(1, 2)` — the same convention `_consume_arithmetic_target`'s
  callers rely on), a leading unary `-`/`+` stays attached to its
  digits (`MOVE -5` → `"-5"`, relied on by `analysis/const_fold.py`),
  and a reference-modification colon joins tight on both sides
  (`WS-X(2:3)`, never `WS-X(2 : 3)` — 2026-08-12 bug review).
  Single-token sources are byte-identical to before. Same review, two
  more text-fidelity fixes: MOVE source and DISPLAY item collection
  prefer `Token.raw_value` for STRING_LITERALs, so a typed literal keeps
  its prefix (`X"41"` stays the one byte `X"41"`, no longer collapsed to
  the two-character `"41"`); and COMPUTE's serialized `expression` string
  re-merges `**`'s two lexed `*` tokens (the `expression_tree` already
  did), so `2 ** 3` no longer reads `2 * * 3`. `DivideStatement` also
  gained `division_mode` (`"BY"`/`"INTO"`), set where
  `_parse_binary_arithmetic` consumes the separator and emitted by
  `to_dict()` — see [ast-models.md](ast-models.md) and
  [analysis.md](analysis.md)'s const-fold notes. All pinned by
  `tests/regression/test_bug_review_2026_08_12.py`.
* **`TokenStream.expect()` matched anything at EOF (P-B2,
  `core/token_stream.py`):** the guard was `if token.value and
  token.value.upper() != value.upper()`, so an empty-valued token (EOF's
  value is `""`) short-circuited the comparison and *matched any expected
  value* — `expect(".")` at end of stream silently consumed the EOF token
  instead of raising `TokenMismatch`. An empty-valued token now mismatches
  every non-empty expected value.
* **`_ID_DIV_RE` vs sequence numbers (P-B4, `parser.py`):**
  `_skip_to_identification_division`'s regex (`^\s*(IDENTIFICATION|ID)\s+
  (DIVISION|DIV)`) never matched a sequence-numbered fixed-format header
  (`000100 IDENTIFICATION DIVISION.`), so junk lines before such a program
  were never skipped. The regex now allows an optional exactly-6-character
  digits/spaces prefix (`^(?:[0-9 ]{6})?\s*...`) — exactly-6 (not "up to 6")
  so arbitrary text that merely starts with digits still doesn't match.

# SKIP1/SKIP2/SKIP3 hardened to match EJECT's boundary-detection coverage (2026-08-21)

`SKIP1`/`SKIP2`/`SKIP3` (compiler-directing listing no-ops, the same class of
statement as `EJECT` above — blank-line hints for the source listing, no
runtime effect) already had their own `TokenType`s, `KEYWORDS` entries, and a
registered `SkipStatementParser` -> `SkipStatement` no-op node
(`simple_statement_parsers.py` / `models/statements/misc.py`) by the time
this entry was written, so direct repro found no misparse: `SKIP1.` between
two paragraphs did not split them, and a period-less `SKIP2`/`SKIP3` did not
swallow the following statement or warn, both inline and via COPY-expanded
copybook text.

What was actually missing: unlike `EJECT`, `SKIP1`/`SKIP2`/`SKIP3` were never
added to `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` (`_utils.py`) — the
sets every operand/parameter-collection loop (`CALL ... USING`, `MOVE`,
`PERFORM`, `SET`, etc.) and the paragraph-boundary scanner consult to
recognize "this token starts a new statement, stop consuming operands here."
Having a dedicated `TokenType` already keeps a token out of the `IDENTIFIER`
checks these sets exist to backstop for *unreserved* verb words (see the
`EJECT` entry above and the 2026-07-08 "unsupported-verb boundary gap" audit
for the general pattern), so nothing was live-broken — but the gap left
`SKIP1`/`SKIP2`/`SKIP3` one refactor away from being swallowed as an operand
by a preceding statement's own collection loop, exactly the failure class
`EJECT` needed fixing for. Added `TokenType.SKIP1`/`SKIP2`/`SKIP3` and
`"SKIP1"`/`"SKIP2"`/`"SKIP3"` to both sets for parity. Pinned by the new
`tests/regression/test_skip_statement.py`, mirroring every scenario in
`test_eject_statement.py` (trailing-period paragraph-split guard, no-period
marker survival, back-to-back directives across all three variants, AST
node shape including each variant's own `lines` count, COPY expansion).

# H9 dedent disambiguation extended to every operand, not just the first (2026-08-21)

The H9 paragraph-boundary check (see above) gained an indentation-based
disambiguation (`_looks_dedented_relative_to`) so a genuine dedented
paragraph header (Area A) isn't confused with an operand that merely wraps
onto its own continuation line (Area B, same or deeper column than the
statement's verb) — but that disambiguation was gated on `target_count ==
0` in `move_parser.py` alone: a *second-or-later* operand still tripped
the boundary check unconditionally, regardless of indentation, dropping it
exactly like the pre-dedent-fix behavior. A real-corpus re-probe found live
repros (`MOVE SPACES TO a\n    b.` and `OPEN OUTPUT a\n    b.`, both
dropping `b`).

Fixed by hoisting the helper into a shared `looks_dedented_relative_to` in
`_utils.py` and ANDing it into every multi-operand call site of
`looks_like_paragraph_boundary`, unconditionally rather than only for the
first operand: `move_parser.py` (targets — the `target_count > 0`
short-circuit removed entirely, since dedentation alone now decides it
uniformly), `open_parser.py`/`close_parser.py` (file-name lists, previously
with no dedent guard at all), `set_parser.py` (targets),
`display_parser.py` (item list), `simple_statement_parsers.py`
(`CancelStatementParser`'s program-name list), `sort_merge_parsers.py`
(SORT/MERGE's own clause-dispatch loop plus the module-level
`_parse_keys`/`_parse_file_list` helpers, both now threading an optional
`reference_column` parameter from their caller's verb-token column),
`string_unstring_parsers.py` (STRING's operand list, UNSTRING's
clause-dispatch loop, and `UnstringStatementParser._parse_into_targets`,
likewise threaded), `initialize_inspect_parsers.py`
(`InspectStatementParser`'s "consume to period" trailer and
`_parse_tallying`, likewise threaded), and `arithmetic_parsers.py`
(`_consume_additional_arithmetic_targets`/`_consume_additional_giving_
targets`, likewise threaded from every ADD/SUBTRACT/MULTIPLY/DIVIDE call
site, plus `ComputeStatementParser`'s expression-token collection loop).
Each site's reference column is the statement's own verb token's column
(`start_token.location.column`), matching the convention MOVE already
established. Regression coverage: `tests/regression/
test_real_corpus_parse_failures.py::TestSecondOperandOnContinuationLine`
(plus a guard test confirming a genuinely dedented next paragraph is still
caught as a boundary).

**SET's subscript fix (2026-08-20, above) only covered the target side.**
`SET target(subscript) TO ...` folds the target's `(subscript)` via
`consume_optional_subscript`, but every value-reading branch (`TO` plain
value, `TO ADDRESS OF` value, `UP BY` value, `DOWN BY` value) still read a
single token, silently truncating e.g. `SET IDX TO TABLE-ITEM(5)` to a
value of `TABLE-ITEM` (the `(5)` left unconsumed and swallowed as generic
trailing tokens). Fixed by applying the same `consume_optional_subscript`
fold to all four value-reading branches in `set_parser.py`. Pinned by
`TestSetSubscriptedValue` in the same regression file.

**Embedded SQL `¬=` (2026-08-20's `!=`/`||` fix, above, missed one
spelling):** `¬` (U+00AC NOT SIGN — how some EBCDIC-derived mainframe
source spells logical NOT) had no lexer token and hit the same hard
`LexerError` `!`/`|` used to before that fix. Added a `NOT_SIGN` token
(`lexer.py`) and a `(NOT_SIGN, ASSIGN)` entry in
`_EXEC_SQL_SPLIT_RELOP_PAIRS` (`_utils.py`) so `¬=` rejoins in
reconstructed SQL text without a spurious space, exactly like `!=`. Pinned
by `TestEmbeddedSqlNotSignOperator` in the same regression file.

**Known limitation, not new (found and traced by a `/code-review` pass on
this fix):** `looks_dedented_relative_to`'s strict `col < reference_column`
test cannot distinguish a real paragraph header from a wrapped operand when
both sit at *exactly* the same column — e.g. a missing-period MOVE whose
second target and the following paragraph name are both written flush left.
This ambiguity is not new: it already existed for a statement's *first*
operand from the original 2026-08-20 MOVE fix onward (verified directly
against that commit) — this pass's change only extends the *same*
pre-existing trade-off uniformly to every operand position instead of just
the first, rather than introducing a new failure mode. A stricter
disambiguation (e.g. also requiring the enclosing paragraph/section to
already be known) was considered and not pursued: the same-column case
requires source that is simultaneously missing its terminating period *and*
using non-conventional indentation (paragraph headers are virtually always
in Area A, well left of any statement body), an even narrower double
coincidence than the "no repro" items already deferred elsewhere in this
log.

# ADD/SUBTRACT/MULTIPLY/DIVIDE targets and operands dropped their OF/IN qualifier chain (2026-08-22)

`_consume_arithmetic_target` (ADD's `TO`/SUBTRACT's `FROM` target) never
consumed a trailing `OF`/`IN` qualifier chain at all — only an optional
`(subscript)` group via `consume_optional_subscript`. A statement like `ADD
X TO Y OF Z` (or `ADD X TO Y\n    OF Z` — a qualifier chain wrapped onto a
continuation line, which is ordinary free-form COBOL layout) left `OF Z`
sitting unconsumed in the token stream after the target was read, orphaned
for whatever ran next to misinterpret. `_consume_arithmetic_operand`
(MULTIPLY/DIVIDE's `BY`/`INTO` operands) had a related but different bug:
its own OF/IN-consuming loop *did* advance the token stream past the
qualifier chain (so parsing didn't outright fail), but never folded the
consumed `OF`/`IN` keyword or qualifier name into the returned string —
silently discarding the qualification from the AST (`ADD 1 TO QUAL OF
GROUP-A` reported a target of just `"QUAL"`, losing which `QUAL` it was).
Both symptoms trace to the same root cause: subscript groups were folded
into the result string via `consume_optional_subscript`/manual
paren-tracking, but qualifier chains were only ever *consumed*, never
*composed* into the value.

Fixed by extracting a new shared helper,
`consume_optional_qualifiers` (`_utils.py`), that loops consuming an
optional `(subscript)` group and/or `OF`/`IN` qualifier hops — any number of
them, each optionally followed by another subscript, and skipping NEWLINEs
between hops so a chain split across a continuation line still resolves —
appending each piece to the caller's `parts` list in source order. Wired
into both `_consume_arithmetic_target` and `_consume_arithmetic_operand`
(replacing each function's own ad hoc subscript-only/consume-without-append
logic), so `ADD X TO Y OF Z` now reports a target of `"Y OF Z"` and
`MULTIPLY A BY QUAL OF GROUP-A` reports an operand of `"QUAL OF GROUP-A"`,
matching the qualifier syntax COBOL itself uses. Pinned by
`tests/regression/test_arithmetic_qualifier_chain.py`.

**Two more call sites caught by a `/code-review` pass on the fix above,
same day:** `consume_keyword_and_operand` (backs the `GIVING` clause
shared by all four verbs, and DIVIDE's `REMAINDER` clause) still called
only `consume_optional_subscript`, so a qualified `GIVING`/`REMAINDER`
target exhibited the exact same drop (`ADD X TO Y GIVING QUAL OF GROUP-A`
reported a giving of just `"QUAL"`) even after the fix above landed —
this call site shares the identical target-consuming responsibility but
was never rewired. `parse_arithmetic_operands` (ADD's/SUBTRACT's leading
addend list before `TO`/`FROM`) had a worse variant: it didn't just drop
the qualifier, it silently skipped the `OF`/`IN` token and appended the
qualifier name as a *separate, spurious* addend (`ADD QUAL OF GROUP-A TO
Y` produced addends `"QUAL"`, `"GROUP-A"`, `"Y"` instead of `"QUAL OF
GROUP-A"`, `"Y"`) — confirmed to poison `analysis.const_fold.ConstantFolder`
downstream (the phantom `"GROUP-A"` addend fails to resolve to a numeric
value, poisoning the whole accumulation instead of folding correctly).
Both now route through `consume_optional_qualifiers` too. Pinned by the
same regression file's `TestGivingAndRemainderQualifierChain` and
`TestAddendListQualifierChain` classes.

**A second `/code-review` pass, same day, caught one more gap:**
`consume_optional_qualifiers` skipped only `NEWLINE` tokens
(`_skip_newlines`) between an operand/qualifier and the next hop, but a
genuine fixed-format continuation line carries a leading `CONTINUATION`
token (column-7 `-`), not `NEWLINE` -- `consume_keyword_and_operand`'s own
docstring already documents this distinction and uses the broader
`skip_whitespace` (which also covers `WHITESPACE`/`COMMENT`) for exactly
this reason. Fixed by switching `consume_optional_qualifiers` to
`skip_whitespace` too -- a strict superset of `_skip_newlines`, so no
narrowing of previously-accepted input. The same pass also fixed a test
correctness bug (not a source bug) in the DIVIDE-operand-with-subscript
regression test: per COBOL's qualified-reference grammar (`data-name
[(subscript)] [OF/IN data-name-2]...`), a subscript binds to the
identifier it immediately trails, so subscripting a table that appears
*before* the `OF` requires the subscript before the qualifier too
(`QUAL-TBL (IDX) OF GROUP-A`, not `QUAL-TBL OF GROUP-A (IDX)`, which
subscripts the non-table `GROUP-A` instead) -- the parser's lenient
token-concatenation made the old (backwards) form "pass" regardless of
binding order, so it wasn't actually validating a realistic construct.

**Four more findings from continued review passes, same day, all fixed:**

1. **MOVE's target left the identical bug live one file over.** MOVE's
   target-collection loop (`move_parser.py`) only folded a trailing
   `(subscript)` via `consume_optional_subscript` -- no `OF`/`IN` handling
   at all. A qualified target (`MOVE X TO QUAL OF GROUP-A`) fell into the
   loop's generic "skip anything unrecognized" branch for the `OF` token,
   and the qualifier name then looped back around and was collected as a
   spurious *separate* target instead of completing the qualified one --
   the exact bug class `consume_optional_qualifiers` was built to fix.
   Fixed by wiring MOVE's target loop to the same shared helper. (MOVE's
   *source* side was already unaffected: `_parse_source` accumulates every
   token generically, not just IDENTIFIERs, so a qualified source like
   `MOVE WS-A OF WS-GRP TO ...` already round-tripped correctly -- only the
   target side had the narrower IDENTIFIER-only collection loop.) Pinned
   by the new `tests/regression/test_move_qualifier_chain.py`.
2. **Dangling `OF`/`IN` was consumed and discarded even when malformed.**
   `consume_optional_qualifiers` consumed an `OF`/`IN` token unconditionally
   before checking whether an identifier actually followed it, so a
   malformed qualifier (`ADD A OF 5 TO B.` -- `OF` must be followed by a
   data-name, not a numeric literal) vanished from the token stream with no
   trace and no diagnostic. Fixed by confirming a real identifier is
   present via non-destructive lookahead (scanning past
   `WHITESPACE`/`COMMENT`/`NEWLINE`/`CONTINUATION` tokens with
   `stream.peek(offset)`, which never consumes) *before* consuming the
   `OF`/`IN` keyword -- a malformed qualifier now leaves it untouched in
   the stream for the caller, the same as an unqualified reference would.
3. **An unbalanced `(` could devour every following statement.**
   `consume_optional_subscript`'s paren-depth loop had no bound other than
   end-of-stream, so a subscript missing its closing `)` (e.g. `ADD TBL
   (IDX TO C.\n STOP RUN.`) ran past the malformed statement's own period
   and swallowed every statement after it while hunting for a `)` that was
   never there -- `STOP RUN` silently vanished from the AST with only a
   generic "missing TO or GIVING clause" error to show for it. Fixed by
   stopping the loop (without consuming the boundary token) at the first
   token that can never legally appear inside a subscript expression: a
   period, an arithmetic scope terminator, or a real statement/control-flow
   keyword (`_looks_like_statement_boundary`, gated on paren depth > 0 so a
   legitimate closing `)` at depth 0 is unaffected).
4. **Duplicated three-line glue at every call site.** The pattern `parts =
   [value]; consume_optional_qualifiers(stream, parts); value = " ".join(p
   for p in parts if p)` was copy-pasted at all four call sites. Collapsed
   by changing `consume_optional_qualifiers`'s signature from
   `(stream, parts: list[str]) -> None` to `(stream, value: str) -> str`
   (it builds and joins its own `parts` list internally now), so every
   call site is just `value = consume_optional_qualifiers(stream, value)`.
   `consume_optional_subscript` keeps the original `(stream, parts) -> None`
   shape since it is still called with an in-progress `parts` list from
   inside `consume_optional_qualifiers` itself.

All four pinned by `tests/regression/test_arithmetic_qualifier_chain.py`
(the `TestMalformedQualifierChainInput` class for findings 2-3) and the new
`tests/regression/test_move_qualifier_chain.py` (finding 1); finding 4 is a
pure refactor covered by the full existing test suite passing unchanged.

# OCCURS clause line splits, comma-separated INDEXED BY, bare INDEX usage (2026-08-23)

A mainframe corpus retry surfaced "Unparsed token 'TIMES'/'INDEX' ...
clause not fully supported" warnings from four independent gaps in the
OCCURS clause walk (`data_clauses._parse_occurs_clause`, mirrored
identically in the `_data_fast.pyx` fast path — `.c` regenerated):

1. **Count on the line after OCCURS.** The count read did not skip
   NEWLINEs, so with `OCCURS` at end-of-line (long data names push it
   there routinely in 72-column decks) and `40 TIMES INDEXED BY ...` on
   the next line, the two-digit count — a LEVEL_NUMBER token — was misread
   by the caller's clause loop as a *new data item's level number*,
   fabricating a phantom `ANONYMOUS-...` item while the real item silently
   recorded `max_times == 0`. Worse than the warning: layout corruption.
   Fixed with newline-skips before the count, before `TO`, and before the
   max count (the variable-OCCURS form splits the same way).
2. **`INDEXED BY I1, I2`** — the index-name loop broke on the COMMA token,
   dropping every name after the first (same for ASCENDING/DESCENDING KEY
   name lists). Commas are pure separators; both loops now consume them
   and continue.
3. **`INDEXED` / `BY` straddling a line break** — the BY check did not
   skip NEWLINEs; the whole INDEXED BY clause was dropped. Fixed.
4. **Bare `INDEX` usage** (`05 X INDEX.`) — USAGE and IS are both optional
   in the grammar and INDEX is a reserved word (a data item can never be
   *named* INDEX), but only `USAGE [IS] INDEX` was recognized; the bare
   form fell through to the unknown-clause branch. New dispatch branch
   (plus `INDEX` added to the `IS`-lookahead set); the Cython fast loop
   needs no change for this one — it already hands unknown clauses back to
   the pure-Python loop, which is the single source of truth for them.

Pinned by `tests/regression/test_occurs_clause_line_splits.py`.

# PERFORM VARYING dropped its whole clause on a signed FROM/BY value (2026-08-23)

The same corpus retry: `PERFORM SUB-PARA VARYING WS-I FROM 5 BY -1 UNTIL
WS-I < 1` — every countdown loop — surfaced as "PERFORM VARYING clause:
FROM/BY/UNTIL not fully recognized" plus an "Unparsed tokens" warning. A
signed numeric literal lexes as two tokens (MINUS/PLUS then the number);
the FROM/BY value reads in `perform_parser` each consumed a single token,
so `BY -1` captured only `"-"`, the leftover `1` made the UNTIL lookahead
fail, and the whole VARYING clause was dropped. Fixed by
`_consume_from_by_value`, composing MINUS/PLUS + NUMERIC_LITERAL/
LEVEL_NUMBER into one value (mirroring `_consume_arithmetic_operand`'s
handling of the same lexing split), wired into all four FROM/BY reads (the
VARYING header and every AFTER dimension). Pinned by
`tests/regression/test_perform_varying_signed_values.py`.

# Review-pass hardening of the 2026-08-23 corpus fixes (same day)

A `/code-review` pass over the corpus-retry fixes above confirmed four
correctness gaps (each reproduced before fixing) and drove one
consolidation:

1. **OCCURS missing-count error-recovery regression.** The unconditional
   newline-skip before the count read meant a malformed `OCCURS` with *no*
   count consumed the next data item's own level number as the count --
   fabricating a table size from the neighbor's level, overwriting the
   OCCURS item's PIC with the neighbor's, and deleting the neighbor from
   the AST. Now guarded by `_peek_count_token` (pure) / `_peek_count_pos`
   (`_data_fast.pyx`): a NUMERIC_LITERAL is always the count; a
   LEVEL_NUMBER on the same line keeps the historical unconditional read;
   a LEVEL_NUMBER reached only by crossing a line break counts only when
   the token after it reads like the OCCURS clause continuing
   (TIMES/TO/DEPENDING/INDEXED/ASCENDING/DESCENDING/PIC). Applies to both
   the first count and the `TO` max.
2. **`DEPENDING ON` had the same line-split gap** one clause further down
   in the very function being fixed: `DEPENDING ON` at end of line with
   the variable on the next silently degraded to a *fixed* OCCURS and
   dropped the variable as an unparsed token. Newline skips added before
   `ON` and the variable (which requires an IDENTIFIER, so the crossing
   can never swallow a level number). Both paths.
3. **`SIGN IS` at end of line recorded a raw `"\n"` as the sign clause**
   -- the direction read accepted any truthy token value. Restricted to
   LEADING/TRAILING with newline skips between all the clause's keywords
   (pure path only; the fast loop already hands SIGN back).
4. **Signed values consolidated into `_utils.consume_signed_numeric`.**
   The MINUS/PLUS + digits lexing split had grown per-file copies, and the
   sibling consumers were still broken: `SET IDX DOWN BY -1` recorded a
   value of `"-"`, and PERFORM's fix missed a sign and digits straddling a
   72-column line break (`BY -` / newline / `1`). The shared helper does a
   non-destructive lookahead past WHITESPACE/COMMENT/NEWLINE/CONTINUATION
   before composing, and now backs PERFORM VARYING/AFTER FROM/BY, SET's
   value reads (via `_consume_subscripted_value`), and
   `_consume_arithmetic_operand`. PERFORM's FROM/BY values also fold
   subscripts/qualifiers via `consume_optional_qualifiers` (a subscripted
   `FROM WS-TBL (2)` used to strand `( 2 )` and kill the UNTIL lookahead).
   The `.pyx` comma checks were also aligned to compare the COMMA token
   *type* (new `comma_type` parameter) instead of the value `","`, which a
   `','` STRING_LITERAL would have matched.

Pinned by new classes in the three 2026-08-23 regression files
(`TestOccursMissingCountRecovery`, `TestDependingOnLineSplit`,
`TestSignClauseLineSplit`, `TestSignSplitAcrossLines`,
`TestSubscriptedFromByValues`, `TestSetSignedValues`).

# See Also

* [lexer.md](lexer.md) — upstream tokenisation
* [ast-models.md](ast-models.md) — what `ParseResult.ast` contains
* [preprocessing.md](preprocessing.md) — input normalisation

# Shared operand helpers + SET qualifier folding (2026-08-24, /code-review pass)

`parsers/statements/_utils.py` is now the single home for four
previously-duplicated pieces:

* `_NOISE_TOKEN_TYPES` + `peek_past_noise(stream, offset)` — the
  non-destructive skip-past-WHITESPACE/COMMENT/NEWLINE/CONTINUATION
  lookahead. `consume_signed_numeric`, `consume_optional_qualifiers`,
  `previous_meaningful_token`, and perform_parser (which deleted its local
  `_NOISE_TOKEN_TYPES`/`_peek_next_meaningful`) all use it.
* `token_column(token)` — the H9 dedent guard's
  `getattr(getattr(token, "location", None), "column", None)` accessor,
  replacing 16 hand-rolled copies across 10 statement-parser files. Pass
  its result to `looks_dedented_relative_to`.
* `consume_value_operand(stream)` — one value operand: signed numeric
  (via `consume_signed_numeric`), then IDENTIFIERs get
  `consume_optional_qualifiers` folding. Shared by PERFORM VARYING/AFTER
  FROM/BY (moved from perform_parser's `_consume_from_by_value`) and
  SET's TO / UP BY / DOWN BY values (`_consume_set_value` wraps it with
  period-stripping).

**SET was the last qualifier-folding straggler** (fixed same pass): its
targets now route through `consume_optional_qualifiers` (previously
`SET FLAG-ON OF WS-REC TO TRUE` recorded two spurious targets with the OF
silently discarded — no warning) and its values through
`consume_value_operand` (previously `SET WS-IDX TO WS-VAL OF WS-CTL`
stranded `OF WS-CTL` as "Unparsed tokens"). Pinned by
`tests/regression/test_set_qualifier_chain.py`.

**Folded references and analyzers:** operand strings now carry the full
qualified/subscripted reference (`"WS-NUM OF GRP-1"`, `"WS-TAB ( 3 )"`).
Any analyzer keying data items by bare name must normalize via
`analysis._names.base_data_name` — `MoveTypeChecker._resolve_category`
and `DynamicCallAnalyzer`'s MOVE tracking already do (pinned by
`tests/regression/test_folded_reference_analyzers.py`); a new analyzer
that does a raw `name in catalog` lookup will silently miss qualified
references.

**H9 dedent guard equality rule (same pass):** `looks_dedented_relative_to`
compares `col <= reference_column` -- a boundary-shaped token at the SAME
column as the verb is a boundary (base behavior, warning attached), because
at equal columns the indentation signal cannot distinguish the readings and
the operand reading silently swallows the next paragraph. Only strictly
deeper tokens are operands. `parse_arithmetic_operands` also routes
sign-prefixed numerics through `consume_signed_numeric` (previously ADD/
SUBTRACT recorded `-1` as `1`). Pinned by
`tests/regression/test_diff_scan_findings.py`.

# Residual corpus findings (2026-08-24)

A follow-up sweep against a 105-program real-world corpus (88 OK / 17
refused, all refusals `PARSE_WARNING`) found four more gaps, three of them
residual to the earlier "Defect 4" (subscript/reference-mod/paren
qualifier folding) and "Defect 5" (`PERFORM ... WITH TEST BEFORE/AFTER`)
fixes. Pinned by `tests/regression/test_corpus_residual_findings.py`.

* **`NEXT SENTENCE` had no statement parser at all.** IF/EVALUATE/SEARCH's
  condition-collection loops stop at a known statement-starting keyword
  (`STATEMENT_KEYWORDS`/`STATEMENT_TOKEN_TYPES`), but `NEXT` (lexed as its
  own `TokenType.NEXT`, distinct from `IDENTIFIER`) was never in either
  set -- so the words "NEXT SENTENCE" were silently swallowed into the
  *condition* text (`IF WS-A = "Y" NEXT SENTENCE` parsed as a comparison
  against `"'Y' NEXT SENTENCE"`) instead of becoming a statement in the
  THEN/ELSE branch. Fixed by adding `TokenType.NEXT`/`"NEXT"` to both sets
  (`_utils.py`) and a new `NextSentenceStatementParser`
  (`simple_statement_parsers.py`, registered in `procedure_registry.py`
  right after `ContinueStatementParser`) whose `matches()` requires a
  `SENTENCE` lookahead (via `peek_past_noise`) so it can never mis-fire.
  New AST node `NextSentenceStatement` (`models/statements/misc.py`) --
  deliberately its own class, not reusing `ContinueStatement`: NEXT
  SENTENCE transfers control past the rest of the current sentence, a true
  no-op only in the shallow sense this parser models statements at all.

* **`PERFORM ... WITH TEST BEFORE/AFTER` split across continuation lines.**
  All three call sites in `perform_parser.py` (the inline/no-target-
  paragraph form at the top of `parse()`, the out-of-line form after a
  target paragraph name, and inside `_parse_varying_header` for `PERFORM
  VARYING ... WITH TEST ...`) peeked the token immediately after consuming
  `WITH` or `TEST` with no `skip_whitespace` first. Whenever WITH, TEST, or
  BEFORE/AFTER landed on separate continuation lines (`PERFORM WITH\n
  TEST AFTER\n UNTIL ...`), the peek hit a NEWLINE/CONTINUATION token
  instead of the keyword it expected, leaving TEST (or BEFORE/AFTER)
  unconsumed and reported as "Unparsed tokens starting at 'TEST'" --
  `perform_type` also silently fell back to `SIMPLE` instead of `UNTIL`/
  `VARYING`. Fixed by adding `skip_whitespace` before every peek in all
  three call sites (mirrors the newline-tolerance pattern already used by
  `consume_optional_qualifiers`/`consume_signed_numeric`).

* **DISPLAY's subscript fold didn't tolerate a continuation-line
  subscript.** `DisplayStatementParser._consume_subscript` peeked for a
  `LEFT_PAREN` immediately after the preceding item token with no
  whitespace-skip, so `DISPLAY WS-ITEM\n    (WS-IDX).` left the `(` for
  the next loop iteration, which has no handling for a bare LEFT_PAREN and
  aborts the item list ("Unparsed tokens starting at '('"). Fixed via a
  non-destructive `peek_past_noise(stream, 0)` lookahead before deciding
  whether to fold a subscript, so an unrelated next display item on its
  own continuation line (no subscript at all) is unaffected.

* **`consume_optional_qualifiers` was only wired into MOVE/arithmetic/
  SET.** WRITE's record-name and FROM source, READ's INTO target and KEY
  name, and START's KEY name still consumed a single IDENTIFIER token with
  no subscript/OF-IN-qualifier fold, dropping a qualified or subscripted
  operand's trailing tokens as unparsed (e.g. `WRITE OUT-REC FROM WS-LINE
  OF WS-GROUP` stranded `OF WS-GROUP`). Fixed by routing all five through
  `consume_optional_qualifiers` (`write_parser.py`, `read_parser.py`,
  `start_parser.py`).

(see log 2026-09-02 for the XML/JSON structured-clause follow-up)


# Enterprise program-type coverage (2026-09-15)

`tests/samples/enterprise/` (one program per IBM Enterprise COBOL program
type; matrix in `docs/enterprise-program-types.md`) is parsed FAIL_FAST with
no errors and no warnings by
`tests/integration/test_enterprise_program_types.py`. The parser changes it
took, all in this release:

## Object-oriented units (`CLASS-ID` / `FACTORY` / `OBJECT` / `METHOD-ID`)

`IdentificationDivisionParser` accepts `CLASS-ID[.] name [INHERITS [FROM]
name]` and `METHOD-ID[.] name` in the PROGRAM-ID position (metadata
`unit_kind` = `"CLASS"` / `"METHOD"`, `inherits`; `program_id` carries the
class/method name so the "mandatory" check and the program-name plumbing
are unchanged). `parse_class_id_clause` / `parse_method_id_clause` are
static so `CobolParser._handle_oo_unit_marker` can call them for the
header-less forms: a bare `METHOD-ID` (IBM makes the IDENTIFICATION
DIVISION header optional in front of it), the `FACTORY.` / `OBJECT.`
paragraphs, and `END METHOD|FACTORY|OBJECT|CLASS [name] [.]`. Each opens a
new `CobolProgram` (`unit_kind` `"FACTORY"` / `"OBJECT"` / `"METHOD"`)
attached to the *current* unit when that unit is a class-family container
(`_OO_CONTAINER_KINDS`) -- `_attach_new_unit` pushes the parent on
`_unit_stack` and the `END` marker pops it -- so a class contains its
factory and object units and those contain their methods. Nested
`PROGRAM-ID` units keep their historical flat attachment to the primary
program. Method names are alphanumeric literals in IBM (Java names are
case-sensitive); `_unit_name` strips the quotes and keeps the case.

Every division parser had to learn to stop at those markers: the
identification loop (`_at_oo_unit_start`), the ENVIRONMENT division loop
and `ConfigurationSectionParser._at_stop` (a class's REPOSITORY paragraph
is the last thing before `FACTORY.`), and `ProcedureDivisionParser` (a
factory's or object's PROCEDURE DIVISION is usually empty and followed by
`METHOD-ID`; `END METHOD` etc. are in `_OO_UNIT_END_WORDS`). The "N
program units" warning now counts every unit via `program_units()`.

**INVOKE operand forms (2026-09-28, `invoke_parser.py`).** The USING loop
now takes the same argument forms CALL's does: a subscript / OF-IN
qualifier chain folds into the argument (`consume_optional_qualifiers`),
`LENGTH OF x` / `ADDRESS OF x` are one argument, `OMITTED` and figurative
constants are arguments. The RETURNING target and the object reference fold
qualifiers/subscripts too. Before, the loop stopped at the `(` / `OF` /
`OMITTED` and everything after it -- RETURNING included -- was warned about
and dropped.

## PROGRAM-ID attributes and RETURNING

`_parse_program_id` consumes `[IS] INITIAL | COMMON | RECURSIVE`
(repeatable) and the optional trailing word `PROGRAM`; the period after
the `PROGRAM-ID` keyword is optional (IBM). Attributes land in
identification metadata `program_attributes` and on
`CobolProgram.program_attributes` / `is_recursive`.
`BaseDivisionParser.parse` records `PROCEDURE DIVISION ... RETURNING x` as
metadata `returning_parameter` instead of a USING parameter.

## DECLARATIVES

`ProcedureDivisionParser.parse_division` consumes `DECLARATIVES.` and `END
DECLARATIVES.` as markers (no pseudo-paragraphs any more) and flags every
section opened in between: section dict key `declarative`, becoming
`CobolSection` metadata `declarative` / property `is_declarative`.
`UseStatementParser` understands `USE [GLOBAL] BEFORE REPORTING group...`
(`use_type "REPORTING"`, `report_groups`) and skips the word `FOR`.

## Data clauses (6.x)

`data_clauses.py`: `VOLATILE`, `BYTE-LENGTH n`, `DYNAMIC LENGTH [LIMIT [IS]
n]` and `[USAGE] [IS] OBJECT REFERENCE [[FACTORY OF] class]` branches
(`_consume_integer`, `_at_object_reference`, `_parse_object_reference`);
the four words joined `_PICTURE_TERMINATOR_KEYWORDS` so a PICTURE scan
stops at them. `_parse_occurs_clause` handles `OCCURS UNBOUNDED DEPENDING
ON` (peeked with `_peek_next_meaningful(offset=0)` so the count read's
line-crossing guard keeps working; `min_times` 1, `max_times` None,
`OccursClause.is_unbounded`). The Cython walker in `_data_fast.pyx` bails
out to the Python path when the word after `OCCURS` is `UNBOUNDED` and when
`USAGE [IS]` is followed by `OBJECT` (it used to delegate to
`parse_usage_clause`, which took `OBJECT` as the usage and left `REFERENCE
class` as dropped tokens -- the extension-built CI matrix would have caught
what the pure-Python coverage job could not); the `.c` was regenerated. `PictureClause` accepts `U` (`_PIC_UTF8_RE`, one
byte per symbol).

## Statements

`XmlJsonStatement`'s clause loop keeps `JSON` after `TO` (`CONVERTING x
TO JSON DECIMAL`). `SetStatement.targets_are_address_of` is set by
`SetStatementParser._collect_targets` for `SET ADDRESS OF x TO p` (it
returns a third value now). `DeclareTableStatement` accepts a qualified
`DECLARE SCHEMA.TABLE TABLE` (spaces around the period tolerated, name
normalized).

## Pre-header lines

`CobolParser._skip_to_identification_division` keeps `>>` directive lines
(and `CBL`/`PROCESS`) that precede the header instead of blanking them --
`>>DEFINE` is legal anywhere and the conditional pass runs after this
step.

# Line splitting (2026-09-17)

`parse_cobol`, `_parse_core`, `_detect_fixed_format` and the
`lines_parsed` statistic split source with
`cobolparser._lines.split_source_lines`, never `str.splitlines()`: the
latter also breaks on form feed / NEL / U+2028, which put every later
`location.line` off by one against the editor and the listing. See
`preprocessing.md` ("Audit 2026-09-17").

# Level-88 `WHEN SET TO FALSE`, INITIALIZE `TO VALUE` / `TO DEFAULT` (2026-09-28)

* **`88 name VALUE ... WHEN SET TO FALSE [IS] literal`** (IBM): the value
  loop in `SpecialEntryParser.parse_condition_name_item` stopped at `WHEN`
  and the rest of the entry was skipped to the period with no warning.
  `_parse_when_set_to_false` accepts `WHEN [SET] [TO] FALSE [IS]` + a
  (signed) literal or figurative constant and records it as
  `ConditionNameItem.false_value`; anything else after `WHEN` is left for
  the old skip.
* **`INITIALIZE id ... [WITH FILLER] [{ALL | category} TO VALUE] [THEN
  REPLACING ...] [THEN TO DEFAULT]`** (Enterprise COBOL 6): the
  `TO VALUE` / `TO DEFAULT` phrases warned "Unparsed tokens" and were
  dropped. The target loop now also stops at `ALL` / `THEN` / `TO` / a
  category word (`_INITIALIZE_PHRASE_STARTS`); the phrases are recorded as
  `InitializeStatement.to_value_category` / `.to_default`. `THEN` is
  optional before `REPLACING` / `TO DEFAULT` (`_match_then`).

Pinned by `tests/regression/test_level88_false_and_initialize_phrases.py`.
# `*>` floating comments never reach the division parsers (2026-09-28)

`CobolParser._parse_core` builds its `TokenStream` from the lexer's tokens
*minus* `COMMENT` tokens (`self.tokens` itself, and the `tokens_processed`
statistic, keep them). A `*>` floating comment (Enterprise COBOL 6.x) is
layout wherever it sits, and it can end any line -- including one that breaks
a data description entry between a clause keyword and its operand. Every
DATA DIVISION sub-clause reader (`_skip_clause_separators`,
`_peek_count_token`, `_skip_newlines`, the picture/value readers, and their
`_data_fast` mirrors `_skip_layout` / `_peek_count_pos`) skipped NEWLINE but
not COMMENT, so `OCCURS 10 TIMES *> note` / `INDEXED BY IX.` dropped the
INDEXED BY clause as unparsed tokens, `PIC *> note` / `X(10)` lost the
picture, and `OCCURS *> note` / `10 TIMES ...` read `10` as a *new item's
level number* (a phantom `ANONYMOUS-10-n` item). Both clause loops did it,
so no fast/pure differential could see it. Filtering once at the stream
fixes every reader, pure and compiled, without touching `_data_fast`'s
arity. Pinned by `tests/regression/test_audit_2026_09_28_accelerators.py`.

# DATA DIVISION: bare national usages, GROUP-USAGE, qualified ODO counters (2026-09-28)

`data_clauses.py` (+ `_data_fast.pyx` for the OCCURS part):

* **Bare `NATIONAL` / `DISPLAY-1` / `UTF-8`** (`_BARE_USAGE_WORDS`) are the
  item's usage when written without the USAGE keyword, with or without a
  leading `IS`. `NATIONAL` and `UTF-8` lex as IDENTIFIERs, so they joined
  `_PICTURE_TERMINATOR_KEYWORDS`: `PIC N(5) NATIONAL` used to be pattern
  `N(5)NATIONAL` (sized 3 bytes, usage DISPLAY); `DISPLAY-1` / `IS NATIONAL`
  were dropped with "Unparsed token" warnings. The Cython loop hands these
  words back to the Python loop (no fast-path change).
* **`GROUP-USAGE [IS] NATIONAL | UTF-8`** sets `CobolDataItem.group_usage`;
  `data.propagate_group_usage_and_sign` relabels the group and pushes the
  usage onto every subordinate without a USAGE of its own. Previously
  dropped with two warnings (`test_tier6_silent_drop_audit` used it as its
  "unsupported clause" example; it now uses a made-up word).
* **`OCCURS ... DEPENDING ON CNT OF CTL [IN ...]`**: `_consume_qualifiers`
  (Cython: `_consume_qualifiers`) reads the chain into
  `OccursClause.depending_on_qualifiers`; `depending_on` stays the bare name
  (every generator matches counters by bare name). Before, the qualifier
  stopped the OCCURS walk and every KEY / INDEXED BY after it was dropped as
  unparsed tokens. Qualified KEY names (`KEY IS K1 OF T`) keep the bare name.

Pinned by `tests/regression/test_data_division_national_occurs_2026_09_28.py`.
