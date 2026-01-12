# Changelog

All notable changes to the COBOL parser project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### IO Coverage Support

- **IO Coverage Reporter** (`cobolparser/analysis/io_coverage_reporter.py`):
  - Ingests pytest results and maps tests to IO variations
  - Generates machine-readable `io-coverage.json` artifacts
  - Validates artifacts against coverage schema

- **CLI Tools** (`cobolparser/cli/coverage.py`):
  - `status` command: Show coverage status filtered by verb/qualifier
  - `generate` command: Generate coverage artifact from pytest results
  - `validate` command: Validate artifact against schema
  - `render` command: Render artifact as Markdown/CSV/Summary

- **Standalone Tools**:
  - `tools/io_coverage/generate_artifact.py`: Generate coverage artifacts
  - `tools/io_coverage/render_markdown.py`: Render artifacts in various formats
  - `scripts/validate_io_coverage.py`: Validate artifacts against schema

- **Test Coverage Tracking**:
  - 64 IO variations cataloged in `specs/001-io-variation-coverage/io-variation-catalog.csv`
  - 40+ unit/integration tests for IO statements (OPEN, CLOSE, READ, WRITE, etc.)
  - Coverage artifact schema in `contracts/io-coverage-schema.json`

- **New Token Types** (`cobolparser/lexer.py`):
  - `INVALID`, `KEY_IS`, `END_OF_PAGE`, `WITH_LOCK`, `NO_REWIND`
  - `REEL`, `UNIT`, `ADVANCING`, `NO_ADVANCING`, `END_OF_FILE`, `POSITION`

- **Parser Enhancements**:
  - Enhanced `parse_read_statement()` with INVALID KEY support
  - Enhanced `parse_write_statement()` with ADVANCING/NO ADVANCING support

### Changed

- Updated `docs/README.md` with IO coverage documentation links
- Updated `specs/001-io-variation-coverage/quickstart.md` with CLI usage
- Updated `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` with test links

### Fixed

- IO clause parsing now correctly handles continuation lines
- Token type matching improved for IO statement keywords

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

[Unreleased]: https://github.com/anomalyco/cobol-parser/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/anomalyco/cobol-parser/releases/tag/v1.0.0
