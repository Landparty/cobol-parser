# Performance

## Benchmarks

| File size | Typical parse time |
|-----------|-------------------|
| < 1 MB | < 100ms |
| 1–10 MB | 100ms – 1s |
| 10 MB+ | 1–10s (streaming required) |

Memory usage during parsing is typically 2–5x the source file size.

## Monitoring

```python
result = parse_cobol(source)
stats = result.statistics

print(f"Parse time:    {stats.total_time_ms}ms")
print(f"Peak memory:   {stats.memory_peak_mb}MB")
print(f"Lines/second:  {stats.lines_parsed / (stats.total_time_ms / 1000):.0f}")
print(f"Tokens/second: {stats.tokens_processed / (stats.total_time_ms / 1000):.0f}")
```

## Optimization Tips

### Large files — enable streaming

```python
from cobolparser.plugins.core import MemoryConfiguration

config = MemoryConfiguration(
    max_memory_mb=4096,
    chunk_size_kb=2048,
    enable_streaming=True
)
result = parse_cobol(source, memory_config=config)
```

### Production — use FAIL_FAST

```python
from cobolparser.plugins.core import ErrorRecoveryMode

result = parse_cobol(source, error_recovery=ErrorRecoveryMode.FAIL_FAST)
```

`COLLECT_ALL` is slower because the parser continues past every error. Reserve it for debugging.

### Multiple files — use parse_files()

`parse_files()` uses multiprocessing to parse files in parallel, which is faster than a sequential loop for large batches.

```python
from cobolparser import parse_files

results = parse_files(["a.cbl", "b.cbl", "c.cbl"])
```
