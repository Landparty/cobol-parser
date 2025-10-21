# COBOL Parser Output Examples

This directory contains examples of parsed COBOL constructs showing the Abstract Syntax Tree (AST) output for various statement types and language features.

## Available Examples

### Statement Types
- **[CALL Statements](call-statements.md)** - Function/procedure calls with parameters
- **[PERFORM Statements](perform-statements.md)** - Loop and subroutine execution constructs
- **[SQL Statements](sql-statements.md)** - Embedded SQL (EXEC SQL) parsing
- **[COPY Statements](copy-statements.md)** - Copybook inclusion and text replacement

### Data Constructs
- **[Data Items](data-items.md)** - Variable declarations and data structures
- **[File Control](file-control.md)** - File definitions and SELECT statements

### Program Structure
- **[Complete Program](complete-program.md)** - Full COBOL program parsing example
- **[IBM Enterprise Features](ibm-enterprise.md)** - COMP-3, EXEC CICS, and other IBM-specific constructs

## Output Format

All examples show the JSON representation of the parsed AST nodes. Each example includes:

1. **COBOL Source Code** - The original COBOL code being parsed
2. **Parsed AST Output** - The JSON representation of the parsed construct
3. **Key Properties** - Explanation of important AST node properties
4. **Usage Notes** - How to access and use the parsed data in your applications

## Using the Examples

These examples demonstrate how the COBOL parser converts COBOL source code into structured, machine-readable AST representations. The JSON output can be used for:

- Code analysis and metrics
- Refactoring and modernization
- Documentation generation
- Cross-platform COBOL processing
- Legacy system migration

## Parser Configuration

All examples use the default parser configuration with IBM Enterprise COBOL dialect support enabled. For custom parsing configurations, see the main [README](../README.md).