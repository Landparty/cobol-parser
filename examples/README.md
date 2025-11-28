# COBOL Parser Examples

This folder contains simple COBOL examples used for testing and demonstration of the parser.

Files:

- `employee_copybook.cpy` - A small copybook that defines an `EMPLOYEE-RECORD` with fields:
  - `EMP-ID` (numeric)
  - `EMP-NAME` (string)
  - `EMP-DEPT` (string)
  - `EMP-SALARY` (numeric with implied decimals)
  - `EMP-STATUS` (single character)

- `program_with_copybook.cob` - A COBOL program that uses `COPY "examples/employee_copybook.cpy"` to include the copybook into the `WORKING-STORAGE SECTION`, moves sample values into the record fields, and displays them.

Notes:

- The `COPY` statement path is relative to the repository root when run from the project root; adjust the path if you run the program from a different working directory.
- These examples are intentionally simple to make them easy to parse and understand. Use them as fixtures for parser unit tests or as minimal demonstrations when experimenting with the COBOL parser.
