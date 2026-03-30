# Changelog

All notable changes to the COBOL parser project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-03-30

### Breaking Changes

- **BC-1**: Removed 9 IO statement backward-compatibility class aliases (use classes in `cobolparser.models.statements.io` directly)
- **BC-2**: Removed legacy `file_name`/`record_name` field pairs from `IOReadStatement` and `IOWriteStatement` (use `file_identifier` and `record_identifier`)
- **BC-3**: Removed `ParseState` export, `CobolAST` alias, `IOErrorCode`/`IODiagnosticHelper` re-exports, and `get_division_by_name()` compat alias (use `get_division()`)
- **BC-4 – BC-6**: Same commit as BC-3 (see above)
- **BC-7**: Removed `ProcedureParagraph` and `ProcedureSection` compatibility aliases (use `CobolParagraph` and `CobolSection`)
- **BC-8**: Removed legacy `TokenStream.advance()` and `TokenStream.is_at_end`; fixed `skip_whitespace_and_comments`

### Removed

- `StatementRegistry` dead code; benchmark migrated to `StatementParserRegistry` (DUP-6)
- Root-level statement parsers replaced by `parsers/statements/` subpackage

### Refactored

- Deduplicated `_skip_whitespace`, `_collect_clause_stmts`, `_get_context`, `_report_error`, `_try_parse_nested_statement` into shared `parsers/statements/_utils` (DUP-1–4)
- Deduplicated `STATEMENT_TOKEN_TYPES`/`KEYWORDS` into `_utils` (DUP-5)
- Extracted `_collect_until_condition_tokens`; merged `_parse_until_clause`/`_parse_until_conditional` (DUP-7)
- Updated metadata handling to use lazy initialization

### Fixed

- Resolved 6 critical parser edge cases causing silent data loss or crashes
- Fixed fixed-format comment lines being incorrectly parsed as code

### Changed

- License changed to MIT (copyright Samuel Dion)

## [1.3.0] - 2026-03-20

### Added

- **Batch parsing**: `parse_files(paths)` for parallel multi-file parsing using multiprocessing; returns `List[BatchResult]`
- `BatchResult` and `parse_files` exported from top-level `cobolparser` package
- IO statement parsers: `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `START`
- Advanced configuration options for ignored memory patterns and language server settings
- Performance benchmark suite

### Fixed

- `parse_cobol` exceptions now caught in worker to prevent batch abort
- Level number matching uses pre-compiled regex pattern

## [1.1.0] - 2026-01-29

### Added

- **Auto-detection of fixed-format COBOL**: The `parse_cobol` function now automatically detects if a file is in fixed-format based on sequence numbers and indicator area.
- **Enhanced Multi-line String Support**: Robust handling of COBOL string literals spanning multiple lines, including support for continuation indicators and doubled quotes as escape sequences.
- **Comprehensive Lexer Tests**: New suite of 14 unit tests specifically for multi-line string literal edge cases and real-world scenarios.

### Improvements

- Improved lexer robustness for malformed continuation patterns.
- Added COBOL fixed-format column constants for better code maintainability.
- Refactored `_continue_multiline_string` to use character-by-character scanning for accurate quote escaping.


## [1.0.0] - 2026-01-11

### Added

- Initial COBOL parser implementation
- Support for IBM Enterprise COBOL dialect
- Core statement parsing (CALL, PERFORM, MOVE, DISPLAY, etc.)
- File I/O statement parsing (OPEN, CLOSE, READ, WRITE, etc.)
- SQL/CICS/IMS embedded statement parsing
- COPY statement processing with copybook expansion
- FD/SD file description parsing
- JSON serialization of AST nodes
- Error recovery modes (FAIL_FAST, COLLECT_ALL)
- Plugin architecture for extensibility

### Features

- Fixed-format and free-form COBOL support
- Multi-line string continuation
- Comprehensive error reporting with SourceLocation
- Performance monitoring with configurable memory limits
- Type hints for all public APIs

### Tests

- 618+ unit, integration, and contract tests
- 90%+ code coverage on core modules
- Performance test suite for parsing speed
