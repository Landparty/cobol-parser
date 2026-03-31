# Troubleshooting

## MemoryError on large files

Enable streaming and increase the memory limit:

```python
from cobolparser.plugins.core import MemoryConfiguration

config = MemoryConfiguration(max_memory_mb=8192, enable_streaming=True)
result = parse_cobol(source, memory_config=config)
```

## "Unknown verb" errors for valid COBOL

Make sure you're using the IBM Enterprise dialect:

```python
from cobolparser.plugins.core import DialectType

result = parse_cobol(source, dialect=DialectType.IBM_ENTERPRISE)
```

## Slow parsing

Use `FAIL_FAST` mode and, for many files, `parse_files()`. See [performance.md](performance.md).

## Missing data in the AST

Switch to `COLLECT_ALL` to see all parse errors rather than stopping at the first:

```python
from cobolparser.plugins.core import ErrorRecoveryMode

result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
for err in result.errors:
    print(f"Line {err.line}: {err.message}")
```

If `result.ast` is not `None`, a partial AST was produced and can still be inspected.

## Import errors / wrong Python version

```bash
python --version          # must be 3.13+
pip install -e ".[dev]"   # reinstall with dev dependencies
python -c "from cobolparser import parse_cobol; print('ok')"
```

## Debug logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

result = parse_cobol(source, debug=True)
```

## Getting help

- [GitHub Issues](https://github.com/Landparty/cobol-parser/issues) — bugs and feature requests
- [GitHub Discussions](https://github.com/Landparty/cobol-parser/discussions) — questions
- [`docs/`](.) — full documentation index
