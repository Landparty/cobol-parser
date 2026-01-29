# COBOL Parser Cookbook 🍳

This cookbook contains practical, "real-world" recipes for using the COBOL parser in various automation and analysis scenarios.

## 🥘 Recipe 1: The "SQL Extractor"

**Problem**: You have a legacy COBOL application littered with embedded SQL, and you need to map out every table and column being accessed to plan a database migration.

**Solution**: Use the parser to walk the AST, find `ExecSQLStatement` nodes, and extract the raw SQL texts.

```python
import os
from cobolparser import parse_cobol

def extract_sql_from_folder(folder_path):
    sql_report = {}
    
    for filename in os.listdir(folder_path):
        if not filename.endswith(('.cob', '.cbl')):
            continue
            
        filepath = os.path.join(folder_path, filename)
        with open(filepath, 'r') as f:
            # Tip: Use collect-all mode to get partial results even if the code has syntax errors
            from cobolparser.plugins.core import ErrorRecoveryMode
            result = parse_cobol(f.read(), error_recovery=ErrorRecoveryMode.COLLECT_ALL)
            
        if not result.ast:
            print(f"Skipping {filename} due to critical parse errors.")
            continue
            
        # Helper to recursively find nodes
        sql_stmts = []
        def visitor(node):
            if hasattr(node, 'children'):
                for child in node.children:
                    visitor(child)
            # Check if this is an SQL statement
            # Note: Ensure you check the node type correctly based on your version
            if node.__class__.__name__ == 'ExecSQLStatement':
                sql_stmts.append(node)
                
        visitor(result.ast)
        
        if sql_stmts:
            sql_report[filename] = [stmt.sql_text for stmt in sql_stmts]
            
    return sql_report

# Usage
# report = extract_sql_from_folder('./legacy_source')
# for file, sqls in report.items():
#     print(f"--- {file} ---")
#     for sql in sqls:
#         print(sql)
```

## 🥗 Recipe 2: The "File Descriptor Validator"

**Problem**: You need to ensure that all `FD` (File Description) entries in your COBOL programs match the specifications of your new data lake ingestion process (e.g., specific block sizes or recording modes).

**Solution**: focus your analysis on the `DATA DIVISION` -> `FILE SECTION`.

```python
from cobolparser import parse_cobol

def validate_file_descriptors(cobol_code):
    result = parse_cobol(cobol_code)
    issues = []
    
    if not result.success:
        return ["Parsing failed"]
        
    data_div = result.ast.get_division("DATA")
    if not data_div:
        return ["No Data Division"]
        
    file_section = data_div.get_section_by_name("FILE")
    if not file_section:
            
    if not file_section:
        return ["No File Section"]
        
    # Access FD entries through the section's data_records
    for fd in file_section.data_records:
        # Example Rule: Recording Mode must be 'F' (Fixed)
        if getattr(fd, 'recording_mode', '') != 'F':
            issues.append(f"File {fd.file_name} has invalid recording mode: {getattr(fd, 'recording_mode', 'N/A')}")
            
        # Example Rule: Block contains must be reasonable
        block_count = getattr(fd, 'block_contains', None)
        if block_count and block_count < 10:
            issues.append(f"File {fd.file_name} has small block size: {block_count}")
                 
    return issues

# source = "... your cobol code ..."
# print(validate_file_descriptors(source))
```

## 🍰 Recipe 3: The "Call Graph Generator"

**Problem**: You need to visualize how your COBOL programs call each other to understand dependencies (`CALL` 'subprogram').

**Solution**: Extract `CALL` targets.

```python
from cobolparser import parse_cobol
from cobolparser.models.statements import CallStatement

def get_dependencies(cobol_code):
    result = parse_cobol(cobol_code)
    dependencies = set()
    
    if not result.ast:
        return dependencies
        
    def find_calls(node):
        if isinstance(node, CallStatement):
            # 'called_program' is the attribute for the program name
            if node.called_program:
                dependencies.add(str(node.called_program))
            # Also add any possible values for dynamic calls
            for value in node.possible_values:
                dependencies.add(str(value))
            
        if hasattr(node, 'children'):
            for child in node.children:
                find_calls(child)
                
    # Start the walk from Procedure Division
    proc_div = result.ast.get_division("PROCEDURE")
    if proc_div:
        find_calls(proc_div)
        
    return dependencies
```

## 🍲 Recipe 4: Handling Massive Files (Streaming)

**Problem**: You have a 50MB COBOL source file (yes, they exist) and it's crashing your parser with `MemoryError`.

**Solution**: Use the `CobolParser` class directly with memory configuration.

```python
from cobolparser import CobolParser
from cobolparser.plugins.core import MemoryConfiguration

# 1. Configure for low memory footprint
mem_config = MemoryConfiguration(
    max_memory_mb=512,      # Limit to 512MB
    chunk_size_kb=1024,     # Read in 1MB chunks
    enable_streaming=True   # Turn on streaming tokenizer
)

# 2. Create parser with memory configuration
parser = CobolParser(memory_config=mem_config)

# 3. Parse
# Note: Streaming slightly increases parse time but drastically reduces peak RAM
result = parser.parse(huge_string_content, filename="large_program.cbl")

print(f"Parsed {result.statistics.lines_parsed} lines successfully.")
```

## 🍹 Recipe 5: Custom Dialect "Hotfix"

**Problem**: Your vendor uses a non-standard verb `SUPER-COMPUTE` that isn't valid COBOL, causing the parser to choke.

**Solution**: You can pre-process or "monkey patch" keywords if needed (though officially we recommend filing an issue!). A quick workaround is to replace the token before parsing, or register a custom plugin (advanced).

*Simple Pre-processing Workaround:*

```python
def clean_dialect(source_code):
    # Replace non-standard verb with a COMMENT or a standard verb
    return source_code.replace("SUPER-COMPUTE", "COMPUTE")

source = clean_dialect(raw_source)
result = parse_cobol(source)
```
