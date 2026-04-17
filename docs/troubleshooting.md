# Troubleshooting

## MemoryError on large files

Enable streaming and increase the memory limit:

```python
from cobolparser.plugins.core import MemoryConfiguration

config = MemoryConfiguration(max_memory_mb=8192, enable_streaming=True)
result = parse_cobol(source, memory_config=config)
```

## "Unknown verb" errors for valid COBOL

Make sure you're using the IBM Enterprise dialect (the default):

```bash
# CLI — dialect is ibm-enterprise by default
cobol-parser parse program.cbl --dialect ibm-enterprise
```

```python
from cobolparser.plugins.core import DialectType

result = parse_cobol(source, dialect=DialectType.IBM_ENTERPRISE)
```

## Slow parsing

Use `FAIL_FAST` mode and, for many files, batch parsing. See [performance.md](performance.md).

```bash
# CLI — fail-fast is faster for production
cobol-parser parse program.cbl --error-recovery fail-fast

# Batch parse for multiple files
cobol-parser batch *.cbl --workers 4 --error-recovery fail-fast
```

## Missing data in the AST

Switch to `COLLECT_ALL` to see all parse errors rather than stopping at the first:

```bash
# CLI — show errors alongside the partial AST
cobol-parser parse program.cbl --error-recovery collect-all --errors
```

```python
from cobolparser.plugins.core import ErrorRecoveryMode

result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
for err in result.errors:
    print(f"Line {err.line}: {err.message}")
```

If `result.ast` is not `None`, a partial AST was produced and can still be inspected.

## Fixed-format issues (garbled output)

If your COBOL source uses fixed-format columns (1-72) and the output looks wrong, try preprocessing first:

```bash
# Preview the normalized free-form output
cobol-parser preprocess program.cbl

# Strip PROCESS/CBL directives before normalization
cobol-parser preprocess program.cbl --strip-directives
```

If the source is already free-form, pass `--free-form`:

```bash
cobol-parser parse program.cbl --free-form
```

## Copybook not found

Make sure to specify every directory that contains copybooks:

```bash
# Single copybook directory
cobol-parser parse program.cbl --copybook-path ./copybooks

# Multiple directories
cobol-parser expand program.cbl --copybook-path ./copybooks --copybook-path /shared/cobol/includes
```

## Inspecting tokens

If parsing fails and the error is unclear, inspect the raw token stream to see what the lexer produces:

```bash
cobol-parser tokenize program.cbl
```

This outputs every token with its type, value, line, and column, which can help pinpoint where the lexer misinterprets the source.

## Import errors / wrong Python version

```bash
python --version          # must be 3.11+
pip install -e ".[dev]"   # reinstall with dev dependencies
python -c "from cobolparser import parse_cobol; print('ok')"
```

## Debug logging

Enable Python's standard `logging` module at `DEBUG` level before parsing — the
parser emits structured log records for token consumption and rule dispatch:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from cobolparser import parse_cobol
result = parse_cobol(source)
```

## Getting help

- [GitHub Issues](https://github.com/Landparty/cobol-parser/issues) -- bugs and feature requests
- [GitHub Discussions](https://github.com/Landparty/cobol-parser/discussions) -- questions
- [`docs/`](.) -- full documentation index
