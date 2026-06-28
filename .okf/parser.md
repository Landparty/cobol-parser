---
type: Module
title: Parser
description: CobolParser, DivisionParserFactory, StatementParserRegistry — converts Token stream to ParseResult.
tags: [parser, ast, division, statement, registry]
timestamp: 2026-06-28T00:00:00Z
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
