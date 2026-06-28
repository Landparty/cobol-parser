# Dialects & Configuration

> Dialect and plugin configuration that controls parser behavior.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/dialects/ibm_enterprise.py` | `IBMEnterpriseCobol` class; `IBMDataType` enum |
| `cobolparser/dialects/__init__.py` | Exports `IBMEnterpriseCobol` |
| `cobolparser/plugins/core.py` | `ErrorRecoveryMode`, `DialectType`, `MemoryConfiguration`, `SerializationConfig`, `ParseStatistics`, `PluginManager`, exception types |
| `cobolparser/plugins/__init__.py` | Exports all plugin configuration classes |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `IBMEnterpriseCobol` | `dialects/ibm_enterprise.py` | Dialect handler enabling IBM extensions |
| `IBMDataType` | `dialects/ibm_enterprise.py` | Enum of IBM-specific data types |
| `DialectType` | `plugins/core.py` | Enum: `IBM_ENTERPRISE`, `ANSI_COBOL`, `MICRO_FOCUS` |
| `ErrorRecoveryMode` | `plugins/core.py` | Enum: `FAIL_FAST` (stop at first error), `COLLECT_ALL` (accumulate all errors) |
| `MemoryConfiguration` | `plugins/core.py` | Dataclass: `max_memory_mb`, `enable_streaming`, `chunk_size_kb`, `max_error_count` |
| `SerializationConfig` | `plugins/core.py` | Dataclass: `include_metadata`, `include_source_locations`, `compact_format` |
| `ParseStatistics` | `plugins/core.py` | Dataclass: `lines_processed`, `tokens_processed`, `memory_peak_mb`, `parse_time_seconds` |
| `PluginManager` | `plugins/core.py` | Plugin registration and lifecycle management |
| `LexerError` | `plugins/core.py` | Lexer-level error (extends `ParseError`) |
| `UnterminatedStringError` | `plugins/core.py` | Unterminated string literal |
| `MemoryLimitExceededError` | `plugins/core.py` | Memory limit from `MemoryConfiguration.max_memory_mb` exceeded |

## IBM Enterprise COBOL Extensions

Enabled by passing `dialect=DialectType.IBM_ENTERPRISE` to `CobolParser` or by using `--dialect ibm-enterprise` on the CLI.

| Extension | Description |
|-----------|-------------|
| `COMP-3` / `PACKED-DECIMAL` | Binary-coded decimal storage |
| `COMP-1` | Single-precision floating point (4 bytes) |
| `COMP-2` | Double-precision floating point (8 bytes) |
| `COMP-4` / `BINARY` | Binary integer |
| `COMP-5` | Native binary (machine-dependent) |
| `POINTER` | Memory address type |
| `EXEC SQL … END-EXEC` | Embedded SQL blocks (parsed via `ExecSqlStatementParser`) |
| `EXEC CICS … END-EXEC` | CICS command blocks (parsed via `ExecCicsStatementParser`) |
| `EXEC IMS … END-EXEC` | IMS DLI call blocks (parsed via `ExecImsStatementParser`) |
| IBM intrinsic functions | `FUNCTION CURRENT-DATE`, `FUNCTION INTEGER-OF-DATE`, etc. |

## Configuring the Parser

```python
from cobolparser import CobolParser, ErrorRecoveryMode, MemoryConfiguration
from cobolparser.plugins import DialectType, SerializationConfig

# IBM dialect with error collection and memory limit
config = MemoryConfiguration(max_memory_mb=256)
parser = CobolParser(
    memory_config=config,
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    dialect=DialectType.IBM_ENTERPRISE,
)
result = parser.parse(source)
```

## Public API (exported symbols)

```python
from cobolparser import ErrorRecoveryMode, MemoryConfiguration, DialectType, SerializationConfig
from cobolparser import IBMEnterpriseCobol
from cobolparser.plugins import PluginManager, ParseStatistics, LexerError, MemoryLimitExceededError
```

## Gotchas / Invariants

- `ErrorRecoveryMode.FAIL_FAST` raises immediately on the first error; `COLLECT_ALL` continues parsing and returns all errors in `ParseResult.errors`.
- Without `DialectType.IBM_ENTERPRISE`, `EXEC SQL` / `EXEC CICS` / `EXEC IMS` blocks will cause `UnknownStatementError`.
- `MemoryConfiguration.max_memory_mb` is checked during parsing; exceeding it raises `MemoryLimitExceededError`.
- `PluginManager` is for advanced extension; standard users only need `ErrorRecoveryMode` and `DialectType`.

## Refresh Checklist

- [x] Verify `DialectType` enum values in `plugins/core.py`
- [x] Check `IBMDataType` enum values in `dialects/ibm_enterprise.py`
- [x] Verify `MemoryConfiguration` and `SerializationConfig` field names
- [x] Check for new exception types in `plugins/core.py`
