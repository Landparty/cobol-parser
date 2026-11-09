---
type: Module
title: Parser orchestration
description: CobolParser / parse_cobol / ParseResult, the source-text passes before lexing, multi-unit compilation units, core/ infrastructure (TokenStream, StatementParserRegistry, ASTNodeFactory, interfaces, exceptions, _errors.py), plugins/core.py configuration and profiling.py.
tags: [parser, parse-result, token-stream, registry, configuration, profiling]
timestamp: 2026-11-08T00:00:00Z
---

# Parser orchestration

How `cobolparser/parser.py` turns source text into a `ParseResult`: the public
entry points (`parse_cobol`, `CobolParser.parse` / `.parse_file`), the
line-count-preserving source passes it runs before lexing, how one source member
with several program units becomes one `CobolProgram` tree, and the shared
infrastructure every division and statement parser sits on (`core/`,
`plugins/core.py`, `_errors.py`, `profiling.py`). Start with
[Public API](#public-api) and [Pipeline](#pipeline); the division and statement
parsers themselves are in [divisions.md](divisions.md) and
[statements.md](statements.md).

## Contents

- [Public API](#public-api)
- [ParseResult](#parseresult)
- [Errors and warnings](#errors-and-warnings)
- [Pipeline](#pipeline)
- [Source passes before lexing](#source-passes-before-lexing)
- [Multi-unit compilation units](#multi-unit-compilation-units)
- [Core infrastructure](#core-infrastructure)
- [Configuration classes](#configuration-classes)
- [Profiling](#profiling)
- [See also](#see-also)

## Public API

```python
from cobolparser import CobolParser, ParseResult, parse_cobol
from cobolparser import ErrorRecoveryMode, MemoryConfiguration, SerializationConfig
from cobolparser.plugins.core import DialectType

# Convenience (source may also be a path); error_recovery defaults to FAIL_FAST
result: ParseResult = parse_cobol(source, filename="prog.cob")
# enable_profiling=True returns (ParseResult, ProfilingResult) -- see Profiling

# Configurable
config = MemoryConfiguration(max_error_count=100)  # only this field is enforced
parser = CobolParser(
    memory_config=config,
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
)
result = parser.parse(source)

# Dialect + serialisation options (`dialect` takes a `DialectType` member,
# not a dialect object; IBM_ENTERPRISE is the default)
parser = CobolParser(
    dialect=DialectType.IBM_ENTERPRISE,
    serialization_config=SerializationConfig(include_metadata=True),
)
```

`CobolParser.__init__(dialect=DialectType.IBM_ENTERPRISE,
error_recovery=ErrorRecoveryMode.FAIL_FAST, memory_config=None,
serialization_config=None, free_form=False,
initial_warnings=None, preprocess_fixed=None, debug_lines=False)`.
`parse_cobol(source, filename="<string>", dialect=..., error_recovery=FAIL_FAST,
free_form=False, preprocess_fixed=None, debug_lines=False,
enable_profiling=False, top_n=50, prof_output=None)`. Both default to
**FAIL_FAST**; the CLI defaults to `--error-recovery collect-all`.

`parse_cobol()` reads a path if given one, then hands the source to a
`CobolParser` (`preprocess_fixed=None` maps to the parser's auto-detect with
`free_form=False`, so detection runs even when the caller set `free_form`). It
does no format detection or normalization of its own: there is one copy of that
logic, in `CobolParser`. Copybook-expanding parses go through
`parse_cobol_with_expansion` (see [preprocessing.md](../preprocessing.md)).

## ParseResult

```python
@dataclass
class ParseResult:
    ast: CobolProgram | None
    errors: list[ParseError]
    warnings: list[str]
    statistics: ParseStatistics
    # Expanded line -> (origin file, origin line); set only by
    # parse_cobol_with_expansion, None otherwise (see preprocessing.md)
    expansion_source_map: dict[int, tuple[str, int]] | None = None
    # Every copybook file parse_cobol_with_expansion opened, in order, incl.
    # a member that adds no line of its own (#763); [] otherwise
    expansion_copybooks: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:        # ast is not None AND no errors
    @property
    def has_warnings(self) -> bool:
```

- **`ast` is `None` only on a lexer/preprocessing/I/O/internal failure** (or a
  `FAIL_FAST` stop). Text with no recognisable division (`"hello world"`, `""`)
  gives an empty `CobolProgram("UNKNOWN")` with no divisions plus a "No
  recognizable COBOL division found" error, under both recovery modes; `lint`
  and `health` report on that shape. "Something usable" is `ast.divisions`, not
  `ast is not None` (#368; documented in `interface-contract.md`).
- **`statistics` is an independent snapshot.** `_create_result` hands each
  `ParseResult` `self.statistics.copy()` (`ParseStatistics.copy()`), never the
  parser's live object: the next `parse()` call `reset()`s that object in place,
  so sharing it would clobber earlier results when one `CobolParser` is reused.
- **Every return path fills the statistics.** `lines_parsed` / `lines_processed`
  are set before lexing, `tokens_processed` right after it, and `_create_result`
  stops the clock -- so a FAIL_FAST lexer error, a propagated `ParseError` or the
  safety net still reports line counts and a non-zero `parse_time_seconds`.
  `_begin_parse()` holds the per-parse reset; `parse_file()` runs it before
  recording a `File error`, so a missing file never comes back with the previous
  parse's errors, warnings and statistics.
- **`initial_warnings=[...]`** seeds `self.warnings` with caller-supplied
  diagnostics at the top of the *first* `parse()` call (after
  `self.warnings.clear()`), then is consumed, so a reused parser attributes them
  to the first call only. Nothing inside the library passes it; it is public API.

## Errors and warnings

`errors` holds `ParseError`s (`_errors.py`, see
[Core infrastructure](#core-infrastructure)); with FAIL_FAST the first one stops
the parse, with COLLECT_ALL parsing resynchronizes and continues. Statement
parsers record a non-fatal error without dropping their node through
`_utils.get_parse_context(stream)` + `report_parse_error` (see
[statements.md](statements.md)).

**Unexpected exceptions.** A non-`ParseError` exception escaping a division
parser (or `parse_program()`'s outer loop) is recorded as `Division parsing
error: <Type>: <message>`, and one escaping `_parse_core` as `Parser error:
<Type>: <message>`, both built by `CobolParser._unexpected_error()`: the
location is the exception's own (`line_number`/`column`, or a `location` with
`line`/`column`) when it carries one, else the token the stream is positioned
at, and line 1 column 1 only when neither exists; the original exception is
chained as `__cause__`. `_parse_core` resets `self.stream` first, so an error
raised before tokenizing never borrows a previous parse's position. Pinned by
`tests/regression/test_unexpected_error_location.py`.

`warnings` is the **"recognized but degraded"** channel, and the parser's central
invariant is that `errors == []` and `warnings == []` together mean a complete
AST: any construct the parser recognizes but cannot represent must leave a
warning rather than vanish. Sources of warnings: an unsupported verb (no
registered parser -- only `EXECUTE` / `GOTO` / `RECOVER`, see
[divisions.md](divisions.md)), leftover clause tokens a statement parser did not
understand ("Unparsed tokens ..."), an unparsed data-item / SELECT token, a
skipped SCREEN / COMMUNICATION section, a paragraph header absorbed by a
period-less statement (H9 warning), a compilation unit holding more than one
program, dropped debugging lines under `WITH DEBUGGING MODE`, and the lexer's own
non-fatal diagnostics (the "Warnings (non-fatal diagnostics)" section of
[lexer.md](../lexer.md)). Downstream consumers (mocky-mock's `PARSE_WARNING`
gate) refuse any program with warnings, so a construct that parses completely
must stay warning-free.

## Pipeline

```
CobolParser.parse(source) -> _parse_core()
  ├─ _preprocess_source()                   # every pass preserves line count
  │    ├─ _skip_to_identification_division()  # blank pre-header junk (keeps REPLACE)
  │    ├─ strip_compiler_directives()       # CBL / PROCESS cards
  │    ├─ detect_fixed_format() → _normalize_fixed_source()
  │    │     (normalize_fixed_format via normalize_with_recovery; fixed → free-form)
  │    ├─ preprocess_conditional_compilation()   # >>DEFINE / >>IF / >>EVALUATE
  │    ├─ strip_unexpanded_copy_statements()
  │    └─ apply_replace_statements()        # REPLACE (incl. ==:TAG:== partial words)
  ├─ _tokenize(): CobolLexer.tokenize()     # → list[Token]
  │    └─ TokenStream(tokens - COMMENT)     # lookahead abstraction; `*>` comments dropped
  └─ parse_program()
  └─ DivisionParserFactory
       ├─ IdentificationDivisionParser
       ├─ EnvironmentDivisionParser
       ├─ DataDivisionParser
       └─ ProcedureDivisionParser
            └─ StatementParserRegistry  (first-match dispatch)
                 └─ 72 statement parsers (every COBOL verb)
```

`_parse_core` is a thin driver over three stages: `_preprocess_source()` ->
`(text, free_form)`, `_tokenize()` (records lexer errors/warnings, builds
`self.stream`) and `parse_program()`. Each stage returns `None` / `False` when
FAIL_FAST stops the parse. Inside `parse_program()`, a token no division parser
matches goes to `_handle_unmatched_token()` (`END PROGRAM` -> continue; EOF ->
clean stop; else the "No recognizable COBOL division" error), and each matched
division runs through `_parse_division()` (sets the division parser's `host`,
adds the node, names the unit from `program_id` / `unit_kind`).

**The `TokenStream` excludes `COMMENT` tokens** (`self.tokens` and the
`tokens_processed` statistic keep them). A `*>` floating comment can end any
line, including one that breaks a data description entry between a clause
keyword and its operand (`OCCURS 10 TIMES *> note` / `INDEXED BY IX.`). Every
DATA DIVISION sub-clause reader skips NEWLINE but not
COMMENT, so filtering once at the stream is what keeps those readers correct;
do not reintroduce COMMENT tokens into the stream.

The stream also carries `omitted_source_lines` -- the lines
`strip_unexpanded_copy_statements` blanked -- which the EVALUATE parser consults
before treating adjacent WHENs as stacked (see
[statements-control.md](statements-control.md)). The same list is copied onto
every program unit as `CobolProgram.omitted_copy_lines` (not serialized), so
an analyzer can tell a program with a missing COPY member (lint's
`undefined-name` stays quiet then).

## Source passes before lexing

Every pass preserves the line count, so token locations stay true to the source.

- **Line splitting.** `parse_cobol`, `_parse_core`, format detection and the
  `lines_parsed` statistic split source with `cobolparser._lines.split_source_lines`,
  never `str.splitlines()`: the latter also breaks on form feed / NEL / U+2028
  and shifts every later `location.line`. See [preprocessing.md](../preprocessing.md).
- **Pre-header lines.** `_skip_to_identification_division` blanks junk before
  the IDENTIFICATION DIVISION header but keeps `>>` directive lines (`>>DEFINE`
  is legal anywhere and the conditional pass runs later), `CBL` / `PROCESS`
  cards, and every line a well-formed leading `REPLACE` statement spans
  (`replace_statement.find_replace_statement_spans` over the pre-header text,
  via `_replace_statement_lines`) -- `REPLACE` is legal as the first statement
  of a compilation unit and `apply_replace_statements` runs after this pass.
  Applies to `parse_cobol`, `CobolParser.parse` and `parse_cobol_with_expansion`.
- **Header regex.** The header is found with
  `preprocess._normalize.ID_DIVISION_HEADER_RE` (shared with
  `strip_compiler_directives`):
  `^(?:[^\r\n]{6}(?=[ \t]))?\s*(IDENTIFICATION|ID)\s+(DIVISION|DIV)`. Any six
  characters are accepted in columns 1-6 as long as column 7 is blank, so a
  change tag (`CHG001 IDENTIFICATION DIVISION.`) is recognized; a digits-only
  prefix rule missed it, blanked everything up to a *nested* program's header
  and returned only the inner program, and left `strip_compiler_directives`'s
  directive section open (so `PROCESS SECTION.` in the PROCEDURE DIVISION was
  blanked as a PROCESS card). The prefix is exactly six characters, so text that
  merely starts with digits does not match, and a comment record (`*` / `/` in
  column 7) never does.
- **Fixed- vs free-format detection** lives in
  `cobolparser/preprocess/source_format.py` (`detect_fixed_format`);
  `cobolparser.parser._detect_fixed_format` and `_sequence_area_is_fixed_like`
  stay importable as aliases. Its tagged-sequence-area rule is corroborated by
  `_has_area_a_division_header` **or** `_has_tagged_line_anchor` (a tagged line
  with a column-7 comment indicator, or a tagged data-description entry); the
  second anchor exists for copybooks, which have no division header. Details in
  [preprocessing.md](../preprocessing.md).
- **Normalization.** `_normalize_fixed_source()` calls
  `source_format.normalize_with_recovery()` -- the unterminated-literal retry
  shared with the lexer's `_tokenize_source`. `CobolParser.source_is_fixed_format`
  records the decision (the H9 paragraph-boundary check reads it, see
  [statements.md](statements.md)).
- **SPECIAL-NAMES state from the lexer.** After lexing, `CobolParser` copies
  `lexer.decimal_point_is_comma` and `lexer.currency_signs` (each declared
  PICTURE currency symbol's string, #491) onto itself; the DATA DIVISION's
  `DataItemClauseParser._picture_clause` reads both off its host. Both reset
  at the start of every `parse()`.
- **Debugging lines.** `debug_lines` (`parse_cobol` and `CobolParser`, default
  False; #334) compiles fixed-format `D` lines as code. With it off,
  `_normalize_fixed_source` records the dropped line numbers and
  `_warn_dropped_debug_lines()` (called after `parse_program()`) warns once when
  any unit's SOURCE-COMPUTER is `WITH DEBUGGING MODE` (`_debugging_mode_on()`
  reads the CONFIGURATION section's `source_computer` metadata). Reset per parse
  in `_begin_parse`. Details in [preprocessing.md](../preprocessing.md).

## Multi-unit compilation units

`parse_program()` does not stop at the first `END PROGRAM`. Stacked or nested
programs in one source member are each parsed into their own `CobolProgram`; the
first is returned as `ParseResult.ast` and the rest are attached to
`ast.contained_programs` (also reachable via `get_all_statements()` and
`to_dict()["contained_programs"]`), with one summary warning that counts every
unit via `program_units()`. `_peek_is_end_program()` /
`_consume_end_program_marker()` consume `END PROGRAM [name] [.]` between units,
and `END FUNCTION [name] [.]` after a `FUNCTION-ID` unit (`unit_kind`
`"FUNCTION"`, a separately compiled unit like a stacked program).
`CobolProgram.program_units()` enumerates every unit (outermost first, in source
order). The tree stays flat (every PROGRAM unit hangs off the first), so the
source nesting is recorded apart (#532): `_open_programs` is a stack of the
PROGRAM units whose `END PROGRAM` has not been seen; `_attach_new_unit` sets
the new unit's `enclosing_program` to its top (None when the stack is empty:
a *stacked* program, a separate compilation unit) and pushes it, and the
`END PROGRAM` branch of `_handle_unmatched_token` pops it. Dropping everything after the first program would silently lose most of
a member (NIST `IC228A`).

**Object-oriented units.** IBM OO `CLASS-ID` / `FACTORY` / `OBJECT` /
`METHOD-ID` units nest the same way, tagged by `CobolProgram.unit_kind`
(`"CLASS"` / `"FACTORY"` / `"OBJECT"` / `"METHOD"`). The IDENTIFICATION parser
reads `CLASS-ID` / `METHOD-ID` in the PROGRAM-ID position (see
[divisions.md](divisions.md)); `CobolParser._handle_oo_unit_marker` handles the
header-less forms -- a bare `METHOD-ID` (IBM makes the IDENTIFICATION DIVISION
header optional in front of it), the `FACTORY.` / `OBJECT.` paragraphs, and
`END METHOD|FACTORY|OBJECT|CLASS [name] [.]` -- calling the static
`parse_class_id_clause` / `parse_method_id_clause`. Each opens a new
`CobolProgram` attached to the *current* unit when that unit is a class-family
container (`_OO_CONTAINER_KINDS`): `_attach_new_unit` pushes the parent on
`_unit_stack` and the `END` marker pops it, so a class contains its factory and
object units and those contain their methods. Nested `PROGRAM-ID` units keep
their flat attachment to the primary program. Method names are alphanumeric
literals in IBM (Java names are case-sensitive); `_unit_name` strips the quotes
and keeps the case. Every division parser stops at these markers (see
[divisions.md](divisions.md)).

## Core infrastructure

| File | Class / Purpose |
|------|----------------|
| `interfaces.py` | `ITokenStream`, `IDivisionParser`, `IStatementParser` ABCs; `ParseContext` (nested statement parsing; carries `host`, the registry, `known_data_names` and `condition_names` -- the level-88 names, #562) |
| `token_stream.py` | `TokenStream` — `peek()`, `consume()`, `expect()`, configurable lookahead; `omitted_source_lines` |
| `registry.py` | `StatementParserRegistry` — `register(parser, position=None)` / `clear` / `find_parser(stream)` / `get_all_parsers()`; first-match dispatch (registration order matters), uncached: every lookup asks the parsers in order, so a result never depends on earlier parses |
| `exceptions.py` | `TokenMismatch`, `UnexpectedEndOfInput`, `DivisionNotFoundError`, `UnknownStatementError`, `ValidationError` (all `ParseError` subclasses) |
| `ast_factory.py` | `ASTNodeFactory` — validated node creation; `get_factory()` / `set_factory()` / `create_node(node_class, location, **kwargs)`; raises `ValidationError` when the node has no location or node type |
| `_errors.py` (root) | `ParseError` base class — zero internal deps (avoids circular imports); re-exported by `plugins/core.py` |

The division layer adds `parsers/divisions/base.py` (`BaseDivisionParser`,
`at_division_boundary()`) and `factory.py` (`DivisionParserFactory`,
`DivisionType`, `get_default_factory()` / `reset_default_factory()`).

- **`TokenStream.expect(value)` never matches an empty-valued token against a
  non-empty expected value.** EOF's value is `""`; a truthiness short-circuit
  would let `expect(".")` silently consume EOF instead of raising
  `TokenMismatch`.
- **`find_parser` has no result cache, on purpose.** A cache keyed on the next
  few tokens returned a stale parser whenever a `matches()` looked further ahead
  than the key, and on the shared `ProcedureDivisionParser._SHARED_REGISTRY` it
  grew with every distinct statement opening (identifiers included) in a
  long-running process: about 19,000 keys after one pass over the samples. It
  saved about 2% of parse time (0.4 s of 18 s on the 571 sample and NIST
  programs) and nothing measurable end to end, so it was deleted. Don't add one
  back without a benchmark that shows a real win. `find_parser` re-raises a
  `RecursionError` from `matches()` rather than trying the next parser (#375),
  the same rule as `try_parse_nested`.

## Configuration classes

All in `cobolparser/plugins/core.py` (re-exported by `cobolparser.plugins`).

| Class | Purpose |
|-------|---------|
| `ErrorRecoveryMode` | `FAIL_FAST` (the `CobolParser` / `parse_cobol` default) or `COLLECT_ALL` (the CLI default) |
| `MemoryConfiguration` | dataclass: `max_memory_mb=256` (validated 64–8192), `enable_streaming=False`, `chunk_size_kb=512`, `max_error_count=1000`. Only `max_error_count` is enforced (`CobolParser.add_error` stops recording at the limit); the other three are validated and stored but no parse path reads them, so `MemoryLimitExceededError` is never raised -- measure memory with `ProfilerContext` |
| `SerializationConfig` | dataclass: `include_metadata=True`, `include_source_locations=True`, `compact_format=False`; stamped onto every program unit after the parse |
| `DialectType` | Enum — `IBM_ENTERPRISE` (default; the only dialect with behaviour behind it), `ANSI_COBOL`, `MICRO_FOCUS` |
| `ParseStatistics` | `lines_processed`, `lines_parsed`, `tokens_processed`, `memory_peak_mb` (always 0.0), `parse_time_seconds`, `total_time_ms`, `error_count`, `warning_count`; `reset()` / `start_timing()` / `end_timing()` / `copy()` / `to_dict()` |

Also defined there: `LexerError` -> `UnterminatedStringError`, and
`MemoryLimitExceededError` (all `ParseError` subclasses).

## Profiling

`cobolparser/profiling.py`. `ProfilerContext(top_n=50, prof_output=None)` wraps
any call with cProfile,
tracemalloc and (optionally) psutil, and leaves a `ProfilingResult` on
`.result`: `wall_clock_s`, `cpu_user_s`/`cpu_system_s` (`None` without
psutil), `peak_memory_mb` + `peak_memory_exact`, `top_functions`
(`FunctionProfile`: `function`, `calls`, `total_time_s`, `cumul_time_s`,
`per_call_total_s`, `per_call_cumul_s`), `prof_file`,
`function_profile_available`, `caveats`. `parse_cobol(...,
enable_profiling=True, top_n=, prof_output=)` uses it and returns
`(ParseResult, ProfilingResult)`.

Nesting is safe (see #274): when another profiler is already
active (`sys.getprofile()` on 3.11, `sys.monitoring` PROFILER_ID on 3.12+)
the context skips cProfile, so `function_profile_available` is `False`,
`top_functions` is empty, no `.prof` file is written, and `caveats` says why.
Wall-clock, CPU and memory are still measured, and the outer profile is left
alone. tracemalloc is stopped only by the context that started it, including
when `__enter__` fails. Tests: `tests/unit/test_profiling.py`.

## See also

- [../parser.md](../parser.md) — routing page for the parser files
- [divisions.md](divisions.md) — the four division parsers and their collaborators
- [statements.md](statements.md) — statement dispatch, shared helpers, boundary invariants
- [../lexer.md](../lexer.md) — tokenisation, `TokenType`, the lexer's warnings channel
- [../preprocessing.md](../preprocessing.md) — normalization, format detection, copybooks, the source map
- [../ast-models.md](../ast-models.md) — what `ParseResult.ast` contains
- [history](../history/parser.md) — archived dated notes behind these rules
