# Changelog

All notable changes to the COBOL parser project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
