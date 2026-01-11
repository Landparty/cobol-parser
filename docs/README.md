# COBOL Parser Documentation

This directory contains comprehensive documentation for the COBOL parser, including examples, guides, and analysis reports.

## 📚 Quick Navigation

### 🎯 Project Planning & Coverage
- **[Statement Coverage Summary](STATEMENT_COVERAGE_SUMMARY.md)** - Quick reference: What's implemented, what's missing (START HERE)
- **[Gap Analysis](STATEMENT_COVERAGE_GAP_ANALYSIS.md)** - Comprehensive analysis of missing COBOL statements (42-week roadmap)
- **[Test Coverage Matrix](STATEMENT_TEST_COVERAGE_MATRIX.md)** - Detailed test tracking for TDD workflow

### 📖 Statement Parsing Examples
- **[CALL Statements](call-statements.md)** - Function/procedure calls with parameters
- **[PERFORM Statements](perform-statements.md)** - Loop and subroutine execution constructs
- **[SQL Statements](sql-statements.md)** - Embedded SQL (EXEC SQL) parsing
- **[CICS and IMS Statements](cics-ims-statements.md)** - EXEC CICS and IMS interface calls
- **[COPY Statements](copy-statements.md)** - Copybook inclusion and text replacement

### 📊 Data Constructs
- **[Data Items](data-items.md)** - Variable declarations and data structures
- **[File Control](file-control.md)** - File definitions and SELECT statements

### 🏗️ Program Structure
- **[Complete Program](complete-program.md)** - Full COBOL program parsing example
- **[IBM Enterprise Features](ibm-enterprise.md)** - COMP-3, EXEC CICS, and other IBM-specific constructs
- **[Copybook Expansion](copybook-expansion.md)** - COPY statement processing and text replacement
- **[Parser Invocation Guide](PARSER_INVOCATION_GUIDE.md)** - How to use the parser API

## 🚀 Getting Started

### Current Coverage Status (2026-01-11)

- **27%** of COBOL statements fully implemented (11/41)
- **43%** of HIGH priority statements complete (11/24)
- **618 tests** with 90%+ coverage (target: 1,455 tests)

### Most Critical Gaps

**HIGH Priority Missing**:
1. Arithmetic: ADD, SUBTRACT, MULTIPLY, DIVIDE (75-65% program frequency)
2. File I/O: OPEN, CLOSE, READ, WRITE, REWRITE, DELETE (60-85% frequency)
3. Control Flow: EVALUATE, ACCEPT, INITIALIZE (60-70% frequency)

**Next Steps**: See [Statement Coverage Summary](STATEMENT_COVERAGE_SUMMARY.md) for implementation roadmap.

## 📋 Output Format

All parsing examples show the JSON representation of AST nodes. Each example includes:

1. **COBOL Source Code** - The original COBOL code being parsed
2. **Parsed AST Output** - The JSON representation of the parsed construct
3. **Key Properties** - Explanation of important AST node properties
4. **Usage Notes** - How to access and use the parsed data in your applications

## 🎓 Using the Examples

These examples demonstrate how the COBOL parser converts COBOL source code into structured, machine-readable AST representations. The JSON output can be used for:

- Code analysis and metrics
- Refactoring and modernization
- Documentation generation
- Cross-platform COBOL processing
- Legacy system migration
- Enterprise mainframe modernization projects

## ⚙️ Parser Configuration

All examples use the default parser configuration with IBM Enterprise COBOL dialect support enabled. For custom parsing configurations, see the main [README](../README.md).

### Constitutional Principles

All parser development follows principles defined in [`.specify/memory/constitution.md`](../.specify/memory/constitution.md):

1. **Test-First Development (TDD)** - All features developed using red-green-refactor cycle
2. **Code Quality Standards** - 90%+ test coverage, type hints, comprehensive documentation
3. **Performance Requirements** - 10,000+ lines/sec parsing speed, configurable memory limits
4. **User Experience Consistency** - Predictable APIs, clear error messages
5. **IBM Enterprise COBOL Priority** - Dialect-specific features prioritized

## 🔗 Related Resources

- **Main README**: [../README.md](../README.md) - Installation, quick start, API reference
- **Constitution**: [../.specify/memory/constitution.md](../.specify/memory/constitution.md) - Project governance
- **Test Suite**: `../tests/` - 618 comprehensive tests (unit, integration, contract)