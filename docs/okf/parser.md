# Parser

> Orchestrates division parsers and statement parsers to produce a `ParseResult` from a `List[Token]`.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/parser.py` | `CobolParser` orchestrator; `parse_cobol()` convenience function; `ParseResult` dataclass |
| `cobolparser/core/token_stream.py` | `TokenStream` — navigable wrapper over `List[Token]` with lookahead and transaction support |
| `cobolparser/core/registry.py` | `StatementParserRegistry` — first-match dispatch for statement parsers with caching |
| `cobolparser/core/interfaces.py` | ABCs: `ITokenStream`, `IStatementParser`, `IDivisionParser`; `ParseContext` dataclass |
| `cobolparser/core/ast_factory.py` | `ASTNodeFactory` — centralized, validated AST node creation; `NodeTypeError`, `FieldValidationError` |
| `cobolparser/core/exceptions.py` | Structured exception types: `TokenMismatch`, `UnexpectedEndOfInput`, `DivisionNotFoundError`, `UnknownStatementError`, `ValidationError` (imports `ParseError` from `_errors.py`) |
| `cobolparser/parsers/divisions/factory.py` | `DivisionParserFactory`, `DivisionType` enum (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE) |
| `cobolparser/parsers/divisions/base.py` | `BaseDivisionParser` abstract class with error recovery |
| `cobolparser/parsers/divisions/identification.py` | `IdentificationDivisionParser` |
| `cobolparser/parsers/divisions/environment.py` | `EnvironmentDivisionParser` |
| `cobolparser/parsers/divisions/data.py` | `DataDivisionParser` |
| `cobolparser/parsers/divisions/procedure.py` | `ProcedureDivisionParser` with `StatementParserRegistry` integration |
| `cobolparser/parsers/statements/_utils.py` | Shared utilities: `parse_condition_value()`, `parse_expression_operand()`, `matches_keyword()`, etc. |

## Statement Parser Files (26 parsers)

| File | Parser Class(es) |
|------|-----------------|
| `accept_parser.py` | `AcceptStatementParser` |
| `arithmetic_parsers.py` | `AddStatementParser`, `SubtractStatementParser`, `MultiplyStatementParser`, `DivideStatementParser`, `ComputeStatementParser` |
| `call_parser.py` | `CallStatementParser` |
| `close_parser.py` | `CloseStatementParser` |
| `delete_parser.py` | `DeleteStatementParser` |
| `display_parser.py` | `DisplayStatementParser` |
| `entry_parser.py` | `EntryStatementParser` |
| `evaluate_parser.py` | `EvaluateStatementParser` |
| `go_parser.py` | `GoStatementParser` |
| `ibm_exec_statements.py` | `ExecSqlStatementParser`, `ExecCicsStatementParser`, `ExecImsStatementParser` |
| `if_parser.py` | `IfStatementParser` |
| `initialize_inspect_parsers.py` | `InitializeStatementParser`, `InspectStatementParser` |
| `move_parser.py` | `MoveStatementParser` |
| `open_parser.py` | `OpenStatementParser` |
| `perform_parser.py` | `PerformStatementParser` |
| `read_parser.py` | `ReadStatementParser` |
| `rewrite_parser.py` | `RewriteStatementParser` |
| `search_parser.py` | `SearchStatementParser` |
| `set_parser.py` | `SetStatementParser` |
| `simple_statement_parsers.py` | `ContinueStatementParser`, `ExitStatementParser`, `GobackStatementParser`, `CancelStatementParser`, `AlterStatementParser`, `GenerateStatementParser`, `ReleaseStatementParser`, `ReturnStatementParser`, `UseStatementParser`, `CommitStatementParser`, `RollbackStatementParser` |
| `sort_merge_parsers.py` | `SortStatementParser`, `MergeStatementParser` |
| `start_parser.py` | `StartStatementParser` |
| `stop_parser.py` | `StopStatementParser` |
| `string_unstring_parsers.py` | `StringStatementParser`, `UnstringStatementParser` |
| `unlock_parser.py` | `UnlockStatementParser` |
| `write_parser.py` | `WriteStatementParser` |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `CobolParser` | `parser.py` | Top-level parser orchestrator; `.parse(source, filename) -> ParseResult` |
| `ParseResult` | `parser.py` | Dataclass: `ast: CobolProgram \| None`, `errors: list[ParseError]`, `warnings: list[str]`, `statistics: ParseStatistics`; `.success` property |
| `parse_cobol()` | `parser.py` | Convenience wrapper: `parse_cobol(source, filename="") -> ParseResult` (overloaded for profiling support) |
| `TokenStream` | `core/token_stream.py` | Wraps `List[Token]` with position tracking; implements `ITokenStream` |
| `TokenStream.peek(offset=0)` | `core/token_stream.py` | Look ahead without consuming; returns `Token \| None` |
| `TokenStream.consume()` | `core/token_stream.py` | Consume and return next token; raises `UnexpectedEndOfInput` if exhausted |
| `TokenStream.expect(value)` | `core/token_stream.py` | Expect a specific token value; raises `TokenMismatch` if mismatch |
| `TokenStream.is_empty()` | `core/token_stream.py` | Check if stream exhausted; returns `bool` |
| `TokenStream.match(*types)` | `core/token_stream.py` | Check if next token matches any `TokenType`; returns `bool` |
| `TokenStream.skip_whitespace_and_comments()` | `core/token_stream.py` | Skip WHITESPACE, COMMENT, NEWLINE, CONTINUATION tokens |
| `TokenStream.transaction()` | `core/token_stream.py` | Context manager for backtracking on exception |
| `TokenStream.context` | `core/token_stream.py` | Property: get/set optional `ParseContext` attached to stream |
| `TokenStream.position` | `core/token_stream.py` | Property: current position in token list |
| `StatementParserRegistry` | `core/registry.py` | Holds ordered list of `IStatementParser`; `.find_parser(stream) -> IStatementParser \| None` (first-match with 2-token dispatch cache) |
| `StatementParserRegistry.register(parser, position=None)` | `core/registry.py` | Register a statement parser; optional position to insert |
| `StatementParserRegistry.find_parser(stream)` | `core/registry.py` | Find first parser matching current token stream (cached) |
| `StatementParserRegistry.unregister(parser)` | `core/registry.py` | Remove a parser; returns `bool` |
| `StatementParserRegistry.clear()` | `core/registry.py` | Remove all parsers; clears dispatch cache |
| `ITokenStream` | `core/interfaces.py` | ABC defining token stream contract |
| `IStatementParser` | `core/interfaces.py` | ABC; implementors must define `parse(stream, context=None) -> ASTNode` and `matches(stream) -> bool` |
| `IDivisionParser` | `core/interfaces.py` | ABC for division parsers; `parse()` and `can_parse()` methods |
| `ParseContext` | `core/interfaces.py` | Context object: `host`, `registry`, `parser`; properties: `current_section`, `current_division`; method: `parse_nested_statement(stream)` |
| `ASTNodeFactory` | `core/ast_factory.py` | Singleton factory for creating validated AST nodes; `.create(node_class, location, **kwargs)` |
| `ASTNodeFactory.register_validator()` | `core/ast_factory.py` | Register validator config for a node type |
| `ASTNodeFactory.validate_node_type()` | `core/ast_factory.py` | Type check; raises `NodeTypeError` on mismatch |
| `ASTNodeFactory.validate_required_fields()` | `core/ast_factory.py` | Check required fields exist; raises `FieldValidationError` on failure |
| `ASTNodeFactory.validate_field_types()` | `core/ast_factory.py` | Check field types match expectations |
| `ASTNodeFactory.with_metadata()` | `core/ast_factory.py` | Attach metadata dict to node (returns node for chaining) |
| `ASTNodeFactory.with_context()` | `core/ast_factory.py` | Set division/section context on node |
| `NodeTypeError` | `core/ast_factory.py` | Raised for unknown or mismatched AST node types; extends `ValidationError` |
| `FieldValidationError` | `core/ast_factory.py` | Raised for invalid field values; extends `ValidationError` |
| `get_factory()` | `core/ast_factory.py` | Returns singleton `ASTNodeFactory` instance |
| `set_factory(factory)` | `core/ast_factory.py` | Replace singleton (used in tests) |
| `create_node(node_class, location, **kwargs)` | `core/ast_factory.py` | Module-level shortcut using default factory |
| `DivisionParserFactory` | `parsers/divisions/factory.py` | Selects the right division parser based on `DivisionType` |
| `DivisionParserFactory.register_parser()` | `parsers/divisions/factory.py` | Register a division parser for a type |
| `DivisionParserFactory.get_parser()` | `parsers/divisions/factory.py` | Get parser instance for a division type |
| `DivisionParserFactory.find_parser()` | `parsers/divisions/factory.py` | Find first parser that can handle current stream (first-match) |
| `DivisionType` | `parsers/divisions/factory.py` | Enum: `IDENTIFICATION`, `ENVIRONMENT`, `DATA`, `PROCEDURE` |

## Exception Hierarchy

```
ParseError (canonical base — defined in cobolparser/_errors.py, re-exported from core/exceptions.py)
  ├── TokenMismatch          — unexpected token type/value encountered
  ├── UnexpectedEndOfInput   — token stream exhausted before parsing completed
  ├── DivisionNotFoundError  — unknown COBOL division name
  ├── UnknownStatementError  — no registered statement parser matched
  └── ValidationError        — AST validation failed
      ├── NodeTypeError      — node type validation failed
      └── FieldValidationError — required field validation failed
```

`ParseError` is defined in `_errors.py` with zero internal imports to avoid circular dependency between `plugins/core.py` and `core/exceptions.py`. All core exception types extend `ParseError`.

## Data Flow / Lifecycle

### Parse Call Sequence

1. Caller invokes `CobolParser.parse(source, filename)` or convenience wrapper `parse_cobol(source, filename)`.
2. Input validation and preprocessing:
   - If `free_form=False`, call `normalize_fixed_format(source.splitlines())` to convert fixed-format COBOL to free-form text.
   - Strip compiler directives via `strip_compiler_directives(text)`.
3. Lexing:
   - `CobolLexer(text, filename, dialect).tokenize()` returns `List[Token]`.
4. Token stream wrapping:
   - `TokenStream(tokens)` wraps the list with position tracking and lookahead.
5. Division-by-division parsing:
   - `DivisionParserFactory.parse_divisions(stream)` iterates over `DivisionType` values (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE):
     - Skip tokens until a division header keyword is found.
     - Call `DivisionParserFactory.find_parser(stream)` to select the appropriate division parser.
     - Delegate to that parser's `.parse(stream)` method to consume tokens and produce a `CobolDivision` node.
6. Statement parsing within PROCEDURE division:
   - `ProcedureDivisionParser` uses `StatementParserRegistry`:
     - For each statement position, call `registry.find_parser(stream)` using first-match strategy with 2-token dispatch caching.
     - Invoke the matching parser's `.parse(stream, context)` to consume tokens and return a `CobolStatement` node.
     - If no parser matches, raise `UnknownStatementError` or collect error per recovery mode.
7. Error and warning collection:
   - As parsing proceeds, errors and warnings are collected in `CobolParser.errors` and `CobolParser.warnings`.
   - Per `ErrorRecoveryMode` (FAIL_FAST vs COLLECT_ALL), stop on first error or continue.
8. Result assembly:
   - Return `ParseResult(ast=CobolProgram(...), errors=..., warnings=..., statistics=ParseStatistics(...)`.

### StatementParserRegistry Dispatch

- **First-match strategy:** Registry holds an ordered list of `IStatementParser` implementations.
- **Non-destructive matching:** Each parser's `.matches(stream)` is called; must NOT consume tokens, only peek.
- **2-token cache:** Dispatch result cached by `(tok0_type, tok0_val, tok1_type, tok1_val)` to avoid redundant scans and correctly disambiguate parsers that inspect peek(1) (e.g., EXEC SQL vs EXEC CICS).
- **Cache invalidation:** Cleared on every `.register()`, `.unregister()`, or `.clear()` call.

## Public API (exported symbols)

```python
from cobolparser import CobolParser, ParseResult, parse_cobol, ErrorRecoveryMode, MemoryConfiguration

from cobolparser.core import TokenStream, StatementParserRegistry, ASTNodeFactory
from cobolparser.core.interfaces import ITokenStream, IStatementParser, IDivisionParser, ParseContext
from cobolparser.core.exceptions import (
    ParseError,
    TokenMismatch,
    UnexpectedEndOfInput,
    DivisionNotFoundError,
    UnknownStatementError,
    ValidationError,
)
from cobolparser.core.ast_factory import NodeTypeError, FieldValidationError, get_factory, set_factory, create_node
from cobolparser.parsers.divisions.factory import DivisionParserFactory, DivisionType
```

All 26 statement parsers are importable from `cobolparser.parsers.statements` (module docstring lists them).

## Gotchas / Invariants

- **First-match order matters:** `StatementParserRegistry` uses first-match dispatch. More specific parsers must be registered before more general ones. For example, `EXEC SQL` must be checked before `EXEC CICS`.
- **Non-destructive matching:** Every `IStatementParser.matches(stream)` must NOT consume tokens — it may only peek. Violation breaks the registry's first-match strategy.
- **Singleton factory:** `ASTNodeFactory` is a singleton. Tests needing to inject a mock must call `set_factory(mock)` and restore afterward to avoid cross-test pollution.
- **Circular import avoidance:** `ParseError` is defined in `_errors.py` with zero imports. Never import `ParseError` from `core.exceptions` in `plugins/core.py` — import from `_errors.py` directly.
- **Success criterion:** `ParseResult.success` is `True` only when `ast is not None` AND `errors` is empty.
- **TokenStream position:** `TokenStream` tracks position internally; after calling `.consume()`, position advances. Use `.peek()` to look ahead without advancing. The `.transaction()` context manager can undo position changes on exception.
- **ParseContext passing:** Statement parsers receive `context: ParseContext | None` and must check for `None` before accessing `context.host`, `context.registry`, etc.
- **Division parser registration:** `DivisionParserFactory` must have all four division types registered (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE) before calling `.parse_divisions()`. Missing types will not be parsed.

## Refresh Checklist

- [ ] Verify statement parser file count (26 files in `parsers/statements/`, excluding `_utils.py`)
- [ ] Count statement parser classes by reading all files under `parsers/statements/` and cross-check against brief's table
- [ ] Verify all 26 parser classes are importable from `cobolparser.parsers.statements`
- [ ] Verify `DivisionType` enum values in `parsers/divisions/factory.py` (should have IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE)
- [ ] Verify `TokenStream` method list in `core/token_stream.py` against this document (peek, consume, expect, is_empty, match, skip_whitespace_and_comments, transaction, context property, position property)
- [ ] Verify `ParseResult` fields in `parser.py`: ast, errors, warnings, statistics, success, has_warnings
- [ ] Verify exception types in `core/exceptions.py`: TokenMismatch, UnexpectedEndOfInput, DivisionNotFoundError, UnknownStatementError, ValidationError
- [ ] Verify `ASTNodeFactory` methods: create, register_validator, validate_node_type, validate_required_fields, validate_field_types, with_metadata, with_context
- [ ] Verify module-level factory functions: get_factory, set_factory, create_node (in `core/ast_factory.py`)
- [ ] Verify `DivisionParserFactory` methods: register_parser, get_parser, find_parser
- [ ] Verify `ParseContext` properties and methods: host, registry, parser, current_section, current_division, parse_nested_statement
