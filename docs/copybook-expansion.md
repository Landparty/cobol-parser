# Copybook Expansion Guide

This guide shows how to use the copybook expansion feature to process COBOL programs that contain COPY statements.

## Table of Contents

1. [Basic Usage](#basic-usage)
2. [Nested Copybooks](#nested-copybooks)
3. [Extracting Information](#extracting-information)
4. [Error Handling](#error-handling)
5. [Advanced Features](#advanced-features)

---

## Basic Usage

### Simple Copybook Expansion

```python
from cobolparser import expand_copybooks

# COBOL source with COPY statement
source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       01 WS-TOTAL-SALARY PIC 9(10)V99.
       PROCEDURE DIVISION.
           DISPLAY "Processing payroll".
           STOP RUN.
"""

# Expand copybooks from a directory
result = expand_copybooks(
    source_code=source,
    copybook_paths=["path/to/copybooks"]
)

# Access expanded source
print(result.expanded_source)

# Check which copybooks were included
print(f"Included copybooks: {result.included_copybooks}")
print(f"Max nesting depth: {result.max_depth_reached}")
```

---

## Nested Copybooks

### Understanding Nested Copybook Structure

Copybooks can reference other copybooks, creating a nested hierarchy. The parser automatically handles this recursion.

**Example Directory Structure:**
```
copybooks/
├── EMPLOYEE.cpy      (contains COPY ADDRESS)
├── ADDRESS.cpy       (contains COPY COUNTRY)
└── COUNTRY.cpy       (base level, no COPY)
```

**EMPLOYEE.cpy:**
```cobol
       01 EMPLOYEE-RECORD.
           05 EMPLOYEE-ID           PIC 9(6).
           05 EMPLOYEE-NAME         PIC X(30).
           COPY ADDRESS.
```

**ADDRESS.cpy:**
```cobol
           05 EMPLOYEE-ADDRESS.
               10 STREET            PIC X(30).
               10 CITY              PIC X(20).
               COPY COUNTRY.
```

**COUNTRY.cpy:**
```cobol
               10 COUNTRY-CODE      PIC X(3).
               10 POSTAL-CODE       PIC X(10).
```

### Expanding Nested Copybooks

```python
from cobolparser import expand_copybooks

# Program that uses nested copybooks
program = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPAPP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       PROCEDURE DIVISION.
           STOP RUN.
"""

# Expand with nested resolution
result = expand_copybooks(
    source_code=program,
    copybook_paths=["path/to/copybooks"],
    max_nesting_depth=10  # Allow up to 10 levels of nesting
)

# The expanded source contains all nested content
print(result.expanded_source)
# Output will show EMPLOYEE-RECORD with all nested ADDRESS and COUNTRY fields
```

---

## Extracting Information

### Getting Expansion Statistics

```python
from cobolparser import expand_copybooks

result = expand_copybooks(source, ["path/to/copybooks"])

# Access statistics
stats = result.statistics
print(f"Parse time: {stats.parse_time_ms}ms")
print(f"Total files processed: {stats.file_count}")
print(f"Total lines: {stats.total_lines}")
print(f"Peak memory: {stats.peak_memory_bytes} bytes")
```

### Analyzing Copybook Dependencies

```python
from cobolparser import expand_copybooks
from pathlib import Path

result = expand_copybooks(source, ["path/to/copybooks"])

# List all included copybooks (in order of processing)
print("Copybook Dependency Chain:")
for idx, copybook_path in enumerate(result.included_copybooks, 1):
    name = Path(copybook_path).name
    print(f"  {idx}. {name}")

# Check nesting depth
print(f"\nMaximum nesting depth reached: {result.max_depth_reached}")

# Example output:
# Copybook Dependency Chain:
#   1. EMPLOYEE.cpy
#   2. ADDRESS.cpy
#   3. COUNTRY.cpy
# Maximum nesting depth reached: 3
```

### Converting to JSON for Analysis

```python
from cobolparser import expand_copybooks
import json

result = expand_copybooks(source, ["path/to/copybooks"])

# Export expansion result to JSON
expansion_json = result.to_dict()
print(json.dumps(expansion_json, indent=2))

# JSON structure:
# {
#   "expanded_source": "... full expanded COBOL ...",
#   "included_copybooks": ["path/to/EMPLOYEE.cpy", ...],
#   "max_depth_reached": 3,
#   "statistics": {
#     "parse_time_ms": 1.23,
#     "file_count": 4,
#     "total_lines": 120,
#     "peak_memory_bytes": 45000
#   }
# }
```

### Parsing Expanded Code

```python
from cobolparser import parse_cobol_with_expansion

# Combine expansion and parsing in one step
result = parse_cobol_with_expansion(
    source_code=program,
    filename="PAYROLL.cbl",
    copybook_paths=["path/to/copybooks"]
)

# Access the AST
ast = result.ast
print(f"Program ID: {ast.program_id}")

# Access data division items
for section in ast.data_division.sections:
    print(f"Section: {section.name}")
    for item in section.data_items:
        print(f"  Data Item: {item.name} - {item.picture_clause}")
```

### Detailed Nested Copybook Analysis

```python
from cobolparser import expand_copybooks
from pathlib import Path

def analyze_nested_copybooks(source_code, copybook_paths):
    """
    Analyze nested copybook structure and extract detailed information.
    """
    result = expand_copybooks(source_code, copybook_paths)
    
    print("=== Copybook Expansion Analysis ===\n")
    
    # Basic statistics
    print(f"Total copybooks included: {len(result.included_copybooks)}")
    print(f"Maximum nesting depth: {result.max_depth_reached}")
    print(f"Expansion time: {result.statistics.parse_time_ms:.2f}ms")
    print(f"Total lines processed: {result.statistics.total_lines}")
    
    # Copybook hierarchy
    print("\n=== Copybook Hierarchy ===")
    for idx, path in enumerate(result.included_copybooks, 1):
        name = Path(path).stem
        indent = "  " * (idx - 1)  # Simple indentation (actual depth may vary)
        print(f"{indent}{idx}. {name}")
    
    # Source size comparison
    original_lines = len(source_code.splitlines())
    expanded_lines = len(result.expanded_source.splitlines())
    growth = ((expanded_lines - original_lines) / original_lines * 100)
    
    print(f"\n=== Source Code Growth ===")
    print(f"Original lines: {original_lines}")
    print(f"Expanded lines: {expanded_lines}")
    print(f"Growth: +{growth:.1f}%")
    
    return result

# Example usage
program = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPAPP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       PROCEDURE DIVISION.
           STOP RUN.
"""

result = analyze_nested_copybooks(program, ["path/to/copybooks"])

# Example output:
# === Copybook Expansion Analysis ===
#
# Total copybooks included: 3
# Maximum nesting depth: 3
# Expansion time: 1.85ms
# Total lines processed: 45
#
# === Copybook Hierarchy ===
# 1. EMPLOYEE
#   2. ADDRESS
#     3. COUNTRY
#
# === Source Code Growth ===
# Original lines: 8
# Expanded lines: 52
# Growth: +550.0%
```

---

## Error Handling

### Circular Reference Detection

```python
from cobolparser import expand_copybooks, CircularReferenceError

try:
    result = expand_copybooks(source, ["path/to/copybooks"])
except CircularReferenceError as e:
    print(f"Circular dependency detected!")
    print(f"Dependency chain: {' → '.join(e.dependency_chain)}")
    # Example: "<main> → EMPLOYEE.cpy → ADDRESS.cpy → EMPLOYEE.cpy"
```

### Copybook Not Found

```python
from cobolparser import expand_copybooks, CopybookNotFoundError

try:
    result = expand_copybooks(source, ["path/to/copybooks"])
except CopybookNotFoundError as e:
    print(f"Copybook '{e.copybook_name}' not found")
    print(f"Searched in: {', '.join(e.search_paths)}")
```

### Nesting Depth Exceeded

```python
from cobolparser import expand_copybooks, NestingDepthError

try:
    result = expand_copybooks(
        source,
        ["path/to/copybooks"],
        max_nesting_depth=5  # Limit to 5 levels
    )
except NestingDepthError as e:
    print(f"Nesting depth exceeded: {e.current_depth} > {e.max_depth}")
```

---

## Advanced Features

### Multiple Search Paths

```python
from cobolparser import expand_copybooks

# Search in multiple directories
result = expand_copybooks(
    source_code=program,
    copybook_paths=[
        "/app/copybooks/common",
        "/app/copybooks/payroll",
        "/shared/cobol/includes"
    ]
)
```

### Analyzing Copybook Content Before Expansion

```python
from cobolparser import expand_copybooks
from pathlib import Path

def inspect_copybook_hierarchy(main_source, copybook_paths):
    """
    Inspect copybook hierarchy without fully parsing.
    """
    import re
    
    def find_copy_statements(source):
        """Extract COPY statement member names."""
        pattern = r'COPY\s+([A-Z0-9\-_]+)'
        return re.findall(pattern, source, re.IGNORECASE)
    
    def build_tree(member_name, paths, visited=None, depth=0):
        """Recursively build copybook dependency tree."""
        if visited is None:
            visited = set()
        
        if member_name in visited:
            return f"{'  ' * depth}{member_name} (CIRCULAR!)"
        
        visited.add(member_name)
        result = f"{'  ' * depth}{member_name}\n"
        
        # Find and read copybook file
        for search_path in paths:
            for ext in ['.cpy', '.CPY', '.cbl', '.CBL', '']:
                file_path = Path(search_path) / f"{member_name}{ext}"
                if file_path.exists():
                    with open(file_path, 'r') as f:
                        content = f.read()
                    
                    # Find nested COPY statements
                    nested = find_copy_statements(content)
                    for nested_member in nested:
                        result += build_tree(nested_member, paths, visited.copy(), depth + 1)
                    break
        
        return result
    
    # Find COPY statements in main source
    main_copies = find_copy_statements(main_source)
    
    print("=== Copybook Dependency Tree ===")
    for member in main_copies:
        print(build_tree(member, copybook_paths))

# Example usage
program = """
       COPY EMPLOYEE.
       COPY DEPARTMENT.
"""

inspect_copybook_hierarchy(program, ["path/to/copybooks"])

# Example output:
# === Copybook Dependency Tree ===
# EMPLOYEE
#   ADDRESS
#     COUNTRY
# DEPARTMENT
#   LOCATION
```

### Performance Monitoring

```python
from cobolparser import expand_copybooks
import time

def benchmark_expansion(source, copybook_paths, iterations=10):
    """Benchmark copybook expansion performance."""
    times = []
    
    for i in range(iterations):
        start = time.perf_counter()
        result = expand_copybooks(source, copybook_paths)
        end = time.perf_counter()
        times.append((end - start) * 1000)  # Convert to ms
    
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    
    print(f"Performance over {iterations} iterations:")
    print(f"  Average: {avg_time:.2f}ms")
    print(f"  Min: {min_time:.2f}ms")
    print(f"  Max: {max_time:.2f}ms")
    print(f"  Files processed: {result.statistics.file_count}")
    print(f"  Lines processed: {result.statistics.total_lines}")
    
    return result

result = benchmark_expansion(program, ["path/to/copybooks"])
```

---

## Best Practices

1. **Organize Copybooks**: Keep copybooks in dedicated directories
2. **Limit Nesting**: Keep nesting depth under 10 levels for maintainability
3. **Avoid Circular References**: Design copybooks to prevent circular dependencies
4. **Use Meaningful Names**: Name copybooks clearly (e.g., `EMPLOYEE-RECORD` not `ER01`)
5. **Monitor Performance**: Track expansion statistics for large programs
6. **Cache Results**: For frequently-used copybooks, consider caching expanded results
7. **Version Control**: Keep copybooks in version control with the programs that use them

---

## See Also

- [COPY Statement Syntax](./copy-statements.md)
- [Error Handling Guide](../README.md#error-handling)
- [Parser Integration](../README.md#parser-integration)
