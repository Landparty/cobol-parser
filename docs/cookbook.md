# COBOL Parser Cookbook

This cookbook contains practical, "real-world" recipes for using the COBOL parser in various automation and analysis scenarios. Each recipe includes both CLI and Python API examples where applicable.

## Recipe 1: The "SQL Extractor"

**Problem**: You have a legacy COBOL application littered with embedded SQL, and you need to map out every table and column being accessed to plan a database migration.

**CLI Quick Check**: Before writing code, use `--find-type` to see all SQL statements in a file:

```bash
# Find all EXEC SQL statements in a single file
cobol-parser parse program.cbl --find-type ExecSQLStatement --compact

# Batch parse a directory to get all ASTs
cobol-parser batch legacy_source/*.cbl --compact
```

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

## Recipe 2: The "File Descriptor Validator"

**Problem**: You need to ensure that all `FD` (File Description) entries in your COBOL programs match the specifications of your new data lake ingestion process (e.g., specific block sizes or recording modes).

**CLI Quick Check**: Inspect the DATA division to see file definitions:

```bash
# Navigate directly to the DATA division
cobol-parser parse program.cbl data
```

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

## Recipe 3: The "Call Graph Generator"

**Problem**: You need to visualize how your COBOL programs call each other to understand dependencies (`CALL` 'subprogram').

**CLI Quick Check**: Use the `analyze` subcommand to list all CALL targets (including dynamic calls with possible values):

```bash
# Analyze dynamic CALL targets
cobol-parser analyze program.cbl

# With copybook expansion (so CALL targets in copybooks are included)
cobol-parser analyze program.cbl --copybook-path ./copybooks

# Find all CALL statements directly
cobol-parser parse program.cbl --find-type CallStatement
```

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

## Recipe 4: Handling Massive Files (Streaming)

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

## Recipe 5: Dead Code Detection

**Problem**: You want to find unreferenced paragraphs and sections in your COBOL programs to clean up legacy code.

**CLI Quick Check**: Use the `dead-code` subcommand:

```bash
# Detect unreferenced paragraphs/sections
cobol-parser dead-code program.cbl

# With copybook expansion
cobol-parser dead-code program.cbl --copybook-path ./copybooks

# Compact output for scripting
cobol-parser dead-code program.cbl --compact
```

## Recipe 6: CRUD Matrix for Mainframe Modernization

**Problem**: You're leading a mainframe modernization project and need to document which COBOL programs touch which files and DB2 tables, and how (Create / Read / Update / Delete). The output goes into a spreadsheet for the migration team.

**Solution**: Use `CRUDMatrixGenerator`. It handles both VSAM/sequential files (via `OPEN`/`READ`/`WRITE`/`REWRITE`/`DELETE`) and DB2 tables (via `EXEC SQL INSERT`/`SELECT`/`UPDATE`/`DELETE` and cursor `FETCH`) in a single pass.

```python
from pathlib import Path
from cobolparser import parse_cobol
from cobolparser.analysis import CRUDMatrixGenerator

def emit_portfolio_crud(folder: Path, csv_out: Path) -> None:
    rows = []
    for cbl in folder.glob("*.cbl"):
        result = parse_cobol(cbl.read_text(), filename=str(cbl))
        if not result.ast:
            continue
        matrix = CRUDMatrixGenerator().analyze(result.ast)
        rows.append(matrix.to_csv())

    # Merge per-program CSVs; keep the header only once
    header, *body_chunks = [r for r in rows if r]
    merged = header.splitlines()[0] + "\n"
    for chunk in body_chunks:
        merged += "\n".join(chunk.splitlines()[1:]) + "\n"

    csv_out.write_text(merged)

# emit_portfolio_crud(Path("./legacy"), Path("./crud.csv"))
```

The per-entry `to_dict()` also captures file `organization` (SEQUENTIAL / INDEXED / RELATIVE), `access_mode`, `open_modes`, and cursor names — enough to reconstruct DB2 access patterns.

## Recipe 7: IMS Segment Inventory

**Problem**: You need to list every IMS database segment that a set of COBOL programs reads or writes, so the IMS administrator can size the replacement database.

**Solution**: `IMSSegmentAnalyzer` resolves segment names from the first 8 bytes of SSA data items, tracking values through `MOVE` propagation.

```python
from cobolparser import parse_cobol
from cobolparser.analysis import IMSSegmentAnalyzer

def inventory_ims_segments(source: str) -> dict[str, list[str]]:
    result = parse_cobol(source)
    analyzer = IMSSegmentAnalyzer()
    calls = analyzer.analyze(result.ast)

    inventory: dict[str, list[str]] = {}
    for call in calls:
        for seg in call.segment_names:
            if seg is None:
                continue
            inventory.setdefault(seg, []).append(
                f"{call.interface} {call.function_code or '?'} @ line {call.location.line}"
            )
    return inventory
```

## Recipe 8: EXEC SQL Host Variable Typing

**Problem**: Your DB2-to-Postgres migration tool needs to know the COBOL type of every host variable that appears in `EXEC SQL`, including ones declared via DCLGEN.

**Solution**: `HostVariableResolver` walks the DATA DIVISION, indexes DCLGEN `DECLARE TABLE` blocks, and resolves every `:host-var` reference it finds in SQL.

```python
from cobolparser import parse_cobol
from cobolparser.analysis import HostVariableResolver

result = parse_cobol(source)
report = HostVariableResolver().resolve(result.ast)

for name, info in sorted(report.resolved.items()):
    pic = info.picture or "(group)"
    db2 = info.db2_column.sql_type if info.db2_column else "n/a"
    print(f":{name:<20} PIC {pic:<15} USAGE {info.usage:<10} DB2={db2}")

if report.unresolved:
    print("UNRESOLVED host variables (no DATA DIVISION entry):")
    for name in sorted(report.unresolved):
        print(f"  :{name}")

if report.column_name_collisions:
    print("AMBIGUOUS column names (defined in multiple DECLARE TABLE blocks):")
    for col, tables in report.column_name_collisions.items():
        print(f"  {col}: {', '.join(tables)}")
```

## Recipe 9: Dead Code + Program Flow Report

**Problem**: You want a single JSON report that a downstream tool can ingest, combining dead code detection and a control-flow graph.

**Solution**:

```python
import json
from cobolparser import parse_cobol, DeadCodeAnalyzer, ProgramFlowAnalyzer

result = parse_cobol(source)

dead_code = DeadCodeAnalyzer().analyze(result.ast)
flow      = ProgramFlowAnalyzer().analyze(result.ast)

report = {
    "program": result.ast.program_name,
    "dead_code": dead_code.to_dict(),
    "flow": flow.to_dict(),
}
print(json.dumps(report, indent=2))
```

## Recipe 10: Custom Dialect "Hotfix"

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
