# COBOL Parser Examples

This folder contains simple COBOL examples used for testing and demonstration of the parser.

## Files

- `employee_copybook.cpy` - A small copybook that defines an `EMPLOYEE-RECORD` with fields:
  - `EMP-ID` (numeric)
  - `EMP-NAME` (string)
  - `EMP-DEPT` (string)
  - `EMP-SALARY` (numeric with implied decimals)
  - `EMP-STATUS` (single character)

- `program_with_copybook.cob` - A COBOL program that uses `COPY "examples/employee_copybook.cpy"` to include the copybook into the `WORKING-STORAGE SECTION`, moves sample values into the record fields, and displays them.

## CLI Examples

Try these commands from the repository root to see the parser in action:

```bash
# Parse the example program
cobol-parser parse examples/program_with_copybook.cob

# View just the DATA division
cobol-parser parse examples/program_with_copybook.cob data

# View just the PROCEDURE division
cobol-parser parse examples/program_with_copybook.cob procedure

# Tokenize the example program
cobol-parser tokenize examples/program_with_copybook.cob

# Preprocess the example (convert fixed-format to free-form)
cobol-parser preprocess examples/program_with_copybook.cob

# Expand COPY statements using the examples directory as a copybook path
cobol-parser expand examples/program_with_copybook.cob --copybook-path examples/

# Parse with copybook expansion
cobol-parser parse examples/program_with_copybook.cob --copybook-path examples/

# Analyze dynamic CALL targets
cobol-parser analyze examples/program_with_copybook.cob

# Detect unreferenced paragraphs
cobol-parser dead-code examples/program_with_copybook.cob

# Find all DISPLAY statements
cobol-parser parse examples/program_with_copybook.cob --find-type DisplayStatement

# Parse with compact JSON output (for piping to jq, etc.)
cobol-parser parse examples/program_with_copybook.cob --compact
```

You can also parse the NIST COBOL-85 test suite files:

```bash
# Parse a NIST test file
cobol-parser parse examples/cobol/NC101A.CBL

# Batch parse all NIST files
cobol-parser batch examples/cobol/*.CBL --stats --compact
```

## Notes

- The `COPY` statement path is relative to the repository root when run from the project root; adjust the path if you run the program from a different working directory.
- These examples are intentionally simple to make them easy to parse and understand. Use them as fixtures for parser unit tests or as minimal demonstrations when experimenting with the COBOL parser.
