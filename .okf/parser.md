---
type: Module
title: Parser
description: CobolParser, DivisionParserFactory, StatementParserRegistry — converts Token stream to ParseResult.
tags: [parser, ast, division, statement, registry]
timestamp: 2026-07-05T00:00:00Z
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
