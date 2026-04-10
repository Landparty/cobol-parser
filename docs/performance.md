# Performance

## Benchmarks

| File size | Typical parse time |
|-----------|-------------------|
| < 1 MB | < 100ms |
| 1-10 MB | 100ms - 1s |
| 10 MB+ | 1-10s (streaming required) |

Memory usage during parsing is typically 2-5x the source file size.

## Monitoring

### CLI

Use `--stats` to include parse statistics in the JSON output:

```bash
# Show parse statistics alongside the AST
cobol-parser parse program.cbl --stats

# Example output includes:
# {
#   "ast": { ... },
#   "statistics": {
#     "lines_processed": 1500,
#     "tokens_processed": 8200,
#     "parse_time_seconds": 0.045,
#     "memory_peak_mb": 12.3
#   }
# }

# Batch parse with per-file statistics
cobol-parser batch *.cbl --stats --compact
```

### Python API

```python
result = parse_cobol(source)
stats = result.statistics

print(f"Parse time:    {stats.total_time_ms}ms")
print(f"Peak memory:   {stats.memory_peak_mb}MB")
print(f"Lines/second:  {stats.lines_parsed / (stats.total_time_ms / 1000):.0f}")
print(f"Tokens/second: {stats.tokens_processed / (stats.total_time_ms / 1000):.0f}")
```

## Optimization Tips

### Large files -- enable streaming

```python
from cobolparser.plugins.core import MemoryConfiguration

config = MemoryConfiguration(
    max_memory_mb=4096,
    chunk_size_kb=2048,
    enable_streaming=True
)
result = parse_cobol(source, memory_config=config)
```

### Production -- use FAIL_FAST

```bash
# CLI — fail-fast mode stops at the first error (faster)
cobol-parser parse program.cbl --error-recovery fail-fast
```

```python
from cobolparser.plugins.core import ErrorRecoveryMode

result = parse_cobol(source, error_recovery=ErrorRecoveryMode.FAIL_FAST)
```

`COLLECT_ALL` is slower because the parser continues past every error. Reserve it for debugging.

### Multiple files -- use batch parsing

`parse_files()` and `cobol-parser batch` use multiprocessing to parse files in parallel, which is faster than a sequential loop for large batches.

```bash
# CLI — batch parse with parallel workers
cobol-parser batch prog1.cbl prog2.cbl prog3.cbl
cobol-parser batch *.cbl --workers 8
```

```python
from cobolparser import parse_files

results = parse_files(["a.cbl", "b.cbl", "c.cbl"])
```

### Tokenization only

If you only need to analyze tokens (not the full AST), tokenization alone is significantly faster than a full parse:

```bash
cobol-parser tokenize program.cbl --compact
```
