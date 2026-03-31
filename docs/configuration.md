# Configuration

## Memory Configuration

```python
from cobolparser.plugins.core import MemoryConfiguration

config = MemoryConfiguration(
    max_memory_mb=1024,    # 64MB–8GB
    chunk_size_kb=512,     # processing chunk size
    enable_streaming=True  # required for files > available RAM
)

result = parse_cobol(source, memory_config=config)
```

## Error Recovery

```python
from cobolparser.plugins.core import ErrorRecoveryMode

# Stop on first error — faster, use in production
result = parse_cobol(source, error_recovery=ErrorRecoveryMode.FAIL_FAST)

# Collect all errors — slower, use for debugging
result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

## JSON Serialization

```python
from cobolparser.plugins.core import SerializationConfig

config = SerializationConfig(
    include_metadata=True,         # parser version, timestamp
    include_source_locations=True, # line/column info per node
    compact_format=False           # pretty-print vs compact JSON
)
```

## Full CobolParser Constructor

```python
from cobolparser import CobolParser
from cobolparser.plugins.core import (
    MemoryConfiguration, ErrorRecoveryMode, SerializationConfig, DialectType
)

parser = CobolParser(
    memory_config=MemoryConfiguration(max_memory_mb=2048),
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    dialect=DialectType.IBM_ENTERPRISE,
    serialization_config=SerializationConfig(include_source_locations=True)
)

result = parser.parse(source, filename="program.cob")
```

## parse_cobol() Convenience Function

```python
from cobolparser import parse_cobol

result = parse_cobol(
    source,
    filename="prog.cob",
    preprocess_fixed=True,         # auto-detect and normalize fixed-format
    error_recovery=ErrorRecoveryMode.FAIL_FAST,
    memory_config=MemoryConfiguration()
)
```

## Batch / Parallel Parsing

```python
from cobolparser import parse_files

results = parse_files(["a.cbl", "b.cbl", "c.cbl"])
for r in results:
    print(r.filename, r.result.success)
```
