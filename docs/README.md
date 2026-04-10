# COBOL Parser Documentation

This directory contains comprehensive documentation for the COBOL parser, including examples, guides, and analysis reports.

## 📚 Quick Navigation

### 🎯 Getting Started
- **[Cookbook / Usage Examples](cookbook.md)** - 🍳 **Start Here!** Real-world recipes for SQL extraction, dependency mapping, and more.
- **[Parser Invocation Guide](PARSER_INVOCATION_GUIDE.md)** - Full API reference and usage patterns
- **[Configuration](configuration.md)** - Memory, error recovery, serialization, batch parsing
- **[Architecture](architecture.md)** - Pipeline, packages, adding new statement parsers
- **[Performance](performance.md)** - Benchmarks, monitoring, optimization tips
- **[Troubleshooting](troubleshooting.md)** - Common issues and solutions
- **[Contributing](contributing.md)** - Development setup and PR checklist
- **[Packaging with mypyc](packaging-mypyc.md)** - Build a compiled binary wheel with no readable source

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

## 🚀 Getting Started

### CLI Quick Reference

The `cobol-parser` CLI provides seven subcommands for working with COBOL source files:

```bash
# Parse a COBOL file to AST JSON
cobol-parser parse program.cbl

# Navigate into the AST with dot-separated paths
cobol-parser parse program.cbl procedure
cobol-parser parse program.cbl procedure.MAIN-LOGIC
cobol-parser parse program.cbl procedure.MAIN-LOGIC.display

# Find all nodes of a specific type
cobol-parser parse program.cbl --find-type MoveStatement
cobol-parser parse program.cbl --find-type CallStatement

# Include errors, warnings, and statistics in the output
cobol-parser parse program.cbl --errors --stats

# Compact (single-line) JSON output
cobol-parser parse program.cbl --compact

# Tokenize a file (outputs all tokens as JSON)
cobol-parser tokenize program.cbl

# Preprocess fixed-format COBOL to free-form text
cobol-parser preprocess program.cbl
cobol-parser preprocess program.cbl --strip-directives

# Expand COPY statements (inline copybooks)
cobol-parser expand program.cbl --copybook-path ./copybooks
cobol-parser expand program.cbl --copybook-path ./copybooks --max-depth 50

# Analyze dynamic CALL targets
cobol-parser analyze program.cbl
cobol-parser analyze program.cbl --copybook-path ./copybooks

# Detect dead code (unreferenced paragraphs/sections)
cobol-parser dead-code program.cbl

# Batch parse multiple files in parallel
cobol-parser batch prog1.cbl prog2.cbl prog3.cbl
cobol-parser batch *.cbl --workers 4 --stats --errors
```

#### Shared CLI Options

| Option | Applies to | Description |
|--------|-----------|-------------|
| `--compact` | parse, batch, tokenize, expand, analyze, dead-code | Single-line JSON output |
| `--free-form` | parse, tokenize, preprocess | Treat source as free-form COBOL |
| `--dialect ibm-enterprise` | parse, batch, tokenize, analyze, dead-code | COBOL dialect (default: ibm-enterprise) |
| `--error-recovery fail-fast\|collect-all` | parse, batch, analyze, dead-code | Error handling strategy (default: collect-all) |
| `--copybook-path DIR` | parse, expand, analyze, dead-code | Copybook search directory (repeatable) |
| `--define SYMBOL[=VALUE]` | parse, preprocess, expand, analyze, dead-code | Define conditional compilation symbol (repeatable) |

### Current Coverage Status (2026-03-30)

- **2,975 tests** with 81%+ coverage enforced

### IO Coverage Status

The parser now includes comprehensive IO statement coverage tracking:

- **64 IO variations** cataloged in the IO variation catalog
- **35+ tests** covering OPEN, CLOSE, READ, WRITE, ACCEPT, DISPLAY statements
- **Machine-readable artifacts** generated for each test run
- **CLI tools** available: `python -m cobolparser.cli.coverage`

#### Quick IO Coverage Commands

```bash
# Show coverage status
python -m cobolparser.cli.coverage status

# Filter by verb (OPEN, READ, WRITE, etc.)
python -m cobolparser.cli.coverage status --verb READ

# Generate coverage artifact
python -m cobolparser.cli.coverage generate --pytest-results results.json

# Validate artifact against schema
python -m cobolparser.cli.coverage validate --artifact io-coverage.json
```

See CLI help for detailed usage: `python -m cobolparser.cli.coverage --help`

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

All examples use the default parser configuration with IBM Enterprise COBOL dialect support enabled. For custom configurations, see [configuration.md](configuration.md).

## 📦 Archived Documentation

Historical documentation has been archived for compliance and reference. See:
- **[Archive Index](../archived_docs/ARCHIVE_INDEX.md)** - Complete archive inventory with cross-references
- **[Archive Manifest](../archived_docs/archive_manifest.json)** - Machine-readable metadata for all archived files

Archived categories:
- Coverage reports (EVALUATE, Statement Coverage matrices)
- Metrics and baseline tracking documents
- Completed feature documentation

## 🔗 Related Resources

- **Main README**: [../README.md](../README.md) - Installation, quick start, API reference
- **Test Suite**: `../tests/` - 2,975+ comprehensive tests (unit, integration, contract)
- **Archived Docs**: `../archived_docs/` - Historical documentation and compliance records