# COBOL Parser Quickstart Guide - Updated with Enhanced Features

**Version**: 1.0.0  
**Date**: 2025-09-27  
**Focus**: IBM Enterprise COBOL with configurable memory and JSON export

## Installation

```bash
pip install cobolparser
```

**Requirements**: Python 3.13+

## Basic Usage

### Parse a Simple COBOL Program

```python
from cobolparser import CobolParser, DialectType

# Create parser with IBM Enterprise COBOL focus (default)
parser = CobolParser(dialect=DialectType.IBM_ENTERPRISE_COBOL)

# Sample IBM Enterprise COBOL program
cobol_source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. HELLO-WORLD.

ENVIRONMENT DIVISION.
CONFIGURATION SECTION.
SOURCE-COMPUTER. IBM-390.
OBJECT-COMPUTER. IBM-390.

DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-MESSAGE PIC X(20) VALUE 'Hello, COBOL World!'.
01 WS-COUNTER PIC 9(3) COMP-3 VALUE 0.

PROCEDURE DIVISION.
MAIN-PARA.
    DISPLAY WS-MESSAGE
    ADD 1 TO WS-COUNTER
    STOP RUN.
"""

# Parse the COBOL source with enhanced features
program = parser.parse_string(cobol_source)

# Access program information
print(f"Program name: {program.name}")  # Output: HELLO-WORLD
print(f"Dialect used: {program.parse_metadata.dialect_used}")  # IBM Enterprise COBOL
print(f"Memory used: {program.parse_metadata.memory_used_mb:.2f}MB")

# Access divisions with new structure
divisions_present = []
if program.identification_division: divisions_present.append("IDENTIFICATION")
if program.environment_division: divisions_present.append("ENVIRONMENT") 
if program.data_division: divisions_present.append("DATA")
if program.procedure_division: divisions_present.append("PROCEDURE")
print(f"Divisions found: {divisions_present}")
```

### Explore Program Structure

```python
# Get specific division
data_division = program.get_division(cobolparser.DivisionType.DATA)
if data_division:
    # Find WORKING-STORAGE section
    ws_section = next((s for s in data_division.sections 
                      if s.name == "WORKING-STORAGE"), None)
    
    if ws_section:
        # Examine variable declarations
        for declaration in ws_section.declarations:
            print(f"Variable: {declaration.name}")
            print(f"  Level: {declaration.level_number}")
            print(f"  Picture: {declaration.picture_clause}")
            print(f"  Value: {declaration.value_clause}")

# Get PROCEDURE division
proc_division = program.get_division(cobolparser.DivisionType.PROCEDURE)
if proc_division:
    # Examine paragraphs and statements
    for section in proc_division.sections:
        for paragraph in section.paragraphs:
            print(f"Paragraph: {paragraph.name}")
            for statement in paragraph.statements:
                print(f"  Statement: {statement.type.name} - {statement.raw_text}")
```

### Handle Parse Errors

```python
# COBOL with syntax errors
invalid_cobol = """
IDENTIFICATION DIVISION.
PROGRAM-ID. BAD-PROGRAM.
DATA DIVISION.
01 INVALID-PIC PIC 999V99V99.  # Invalid - multiple V's
PROCEDURE DIVISION.
INVALID-VERB "HELLO".          # Unknown verb
STOP RUN.
"""

try:
    program = cobolparser.parse(invalid_cobol)
    
    # Check for warnings and non-fatal errors
    if program.parse_metadata.warnings:
        print("Warnings encountered:")
        for warning in program.parse_metadata.warnings:
            print(f"  Line {warning.line_number}: {warning.message}")
            
except cobolparser.COBOLParseError as e:
    print(f"Parse error at line {e.line_number}: {e.message}")
    print(f"Error code: {e.error_code}")
```

## Advanced Usage

### Memory-Constrained Environment (NEW)

```python
from cobolparser import CobolParser, MemoryConfiguration

# Configure for low-memory environment (64MB limit)
memory_config = MemoryConfiguration.conservative()
parser = CobolParser(memory_config=memory_config)

# Parse with progress reporting for large files
def progress_callback(processed, total, phase):
    print(f"{phase}: {processed}/{total} lines ({100*processed//total}%)")

parser.set_progress_callback(progress_callback)

try:
    program = parser.parse_file("large_mainframe_program.cbl")
    print(f"Memory used: {program.parse_metadata.memory_used_mb:.1f}MB")
    print(f"Parse time: {program.parse_metadata.parse_duration:.2f}s")
except MemoryLimitExceeded as e:
    print(f"File too large: {e.actual_mb}MB exceeds limit of {e.limit_mb}MB")
```

### Error Collection Mode (NEW)

```python
from cobolparser import CobolParser, ErrorRecoveryMode

# Configure parser to collect all errors instead of failing fast
parser = CobolParser(error_mode=ErrorRecoveryMode.COLLECT_ALL)

# Parse legacy COBOL with potential syntax issues
program = parser.parse_file("legacy_program.cbl")

# Review collected errors and warnings
metadata = program.parse_metadata
print(f"Parsing completed with {len(metadata.syntax_errors)} errors")
print(f"Error recovery mode: {metadata.error_recovery_mode}")

for error in metadata.syntax_errors:
    print(f"Line {error.line_number}: {error.message} ({error.severity})")

# Program structure is still available despite errors
if program.data_division and program.data_division.working_storage_section:
    variables = program.data_division.working_storage_section.variables
    print(f"Found {len(variables)} variables despite parsing errors")
```

### JSON Export for Interoperability (NEW)

```python
from cobolparser import CobolParser, SerializationConfig
import json

parser = CobolParser()
program = parser.parse_file("business_logic.cbl")

# Export full program structure to JSON
full_json = parser.export_json(program, SerializationConfig.full())
with open("program_structure.json", "w") as f:
    f.write(full_json)

# Export only DATA division for analysis tools
data_only_json = parser.export_json(program, SerializationConfig.data_only())
data_structure = json.loads(data_only_json)
print(f"DATA division variables: {len(data_structure.get('variables', []))}")

# Custom serialization configuration
custom_config = SerializationConfig(
    max_depth=3,
    include_divisions={"DATA", "PROCEDURE"},
    include_source_lines=False,
    pretty_print=True
)
custom_json = parser.export_json(program, custom_config)
print("Custom JSON export completed")
```

### Search for Variables

```python
# Find all variables matching a pattern
message_vars = program.find_variables(".*MESSAGE.*")
for var in message_vars:
    print(f"Found variable: {var.name} at line {var.line_number}")

# Find variables by level
group_items = [d for d in program.get_all_declarations() 
               if d.level_number == 1]
for item in group_items:
    print(f"Group item: {item.name}")
```

### Work with Different COBOL Dialects

```python
# Parse IBM COBOL with specific features
ibm_cobol = """
IDENTIFICATION DIVISION.
PROGRAM-ID. IBM-SAMPLE.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-COMP-3-VAR PIC 9(7)V99 COMP-3.  # IBM packed decimal
PROCEDURE DIVISION.
    COMPUTE WS-COMP-3-VAR = 123.45.
    STOP RUN.
"""

program = cobolparser.parse(ibm_cobol, dialect="ibm")

# Parse GnuCOBOL with extensions
gnu_cobol = """
IDENTIFICATION DIVISION.
PROGRAM-ID. GNU-SAMPLE.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-BINARY PIC 9(9) USAGE BINARY-LONG.  # GnuCOBOL extension
PROCEDURE DIVISION.
    STOP RUN.
"""

program = cobolparser.parse(gnu_cobol, dialect="gnucobol")
```

## Plugin Usage

### Use Built-in Analysis Plugins

```python
# Enable static analysis plugin
cobolparser.register_plugin(cobolparser.plugins.StaticAnalyzer())

# Parse with analysis
program = cobolparser.parse(cobol_source)

# Access analysis results
if hasattr(program, 'analysis_results'):
    unused_vars = program.analysis_results.unused_variables
    unreachable_code = program.analysis_results.unreachable_paragraphs
    
    print(f"Unused variables: {len(unused_vars)}")
    print(f"Unreachable code sections: {len(unreachable_code)}")
```

### Create Custom Plugin

```python
class COBOLStyleChecker(cobolparser.ParserPlugin):
    name = "style-checker"
    version = "1.0.0"
    description = "Checks COBOL coding style conventions"
    
    def post_parse_hook(self, program, context):
        # Check for style violations
        violations = []
        
        # Check variable naming conventions
        for declaration in program.get_all_declarations():
            if not declaration.name.startswith(('WS-', 'LS-', 'FS-')):
                violations.append(f"Variable {declaration.name} doesn't follow naming convention")
        
        # Add violations as warnings
        for violation in violations:
            context.add_warning(violation)
            
        return program

# Register and use custom plugin
cobolparser.register_plugin(COBOLStyleChecker())
program = cobolparser.parse(cobol_source)
```

## Error Handling Examples

### Handle Different Error Types

```python
try:
    program = cobolparser.parse(cobol_source)
    
except cobolparser.LexicalError as e:
    print(f"Invalid token at line {e.line_number}: {e.message}")
    
except cobolparser.SyntaxError as e:
    print(f"Syntax error at line {e.line_number}: {e.message}")
    
except cobolparser.StructuralError as e:
    print(f"Structure error: {e.message}")
    
except cobolparser.SemanticError as e:
    print(f"Semantic error at line {e.line_number}: {e.message}")
    
except cobolparser.COBOLParseError as e:
    print(f"General parse error: {e.message}")
```

### Collect Multiple Errors

```python
# Parse with error collection
try:
    program = cobolparser.parse(cobol_source, max_errors=100)
    
    # Check collected errors and warnings
    metadata = program.parse_metadata
    
    if metadata.syntax_errors:
        print("Syntax errors found:")
        for error in metadata.syntax_errors:
            print(f"  Line {error.line_number}: {error.message}")
    
    if metadata.warnings:
        print("Warnings:")
        for warning in metadata.warnings:
            print(f"  Line {warning.line_number}: {warning.message}")
            
except cobolparser.COBOLParseError as e:
    print(f"Fatal error prevented parsing: {e.message}")
```

## Performance Tips

### Optimize for Large Files

```python
# For very large COBOL files
program = cobolparser.parse(
    large_cobol_source,
    include_metadata=False,     # Skip detailed parsing statistics
    strict_mode=False,          # Allow minor syntax variations
    max_errors=5               # Fail fast on major issues
)

# Use streaming for batch processing
def process_cobol_files(filenames):
    for filename in filenames:
        try:
            with open(filename, 'r') as f:
                source = f.read()
            
            program = cobolparser.parse(source, filename=filename)
            
            # Process program...
            yield program
            
        except cobolparser.COBOLParseError as e:
            print(f"Skipping {filename}: {e.message}")
            continue
```

### Memory Management

```python
# For processing many files, clear parser caches periodically
cobolparser.clear_caches()  # Clear internal parser caches

# Use context managers for plugin management
with cobolparser.PluginManager() as pm:
    pm.register(MyPlugin())
    
    # Process files with plugin active
    for filename in large_file_list:
        program = cobolparser.parse(read_file(filename))
        # Plugin automatically unregistered when context exits
```

## Testing Your COBOL Parser Usage

```python
import unittest

class TestCOBOLParsing(unittest.TestCase):
    
    def test_basic_parsing(self):
        program = cobolparser.parse(self.sample_cobol)
        self.assertEqual(program.name, "TEST-PROGRAM")
        self.assertEqual(len(program.divisions), 3)
    
    def test_error_handling(self):
        with self.assertRaises(cobolparser.SyntaxError):
            cobolparser.parse("INVALID COBOL SOURCE")
    
    def test_variable_extraction(self):
        program = cobolparser.parse(self.cobol_with_variables)
        variables = program.find_variables("WS-.*")
        self.assertGreater(len(variables), 0)

if __name__ == "__main__":
    unittest.main()
```

## Next Steps

1. **Read the API Documentation**: Detailed reference for all classes and methods
2. **Explore Plugin Development**: Create custom parsing and analysis plugins  
3. **Check COBOL Dialect Support**: Understand supported COBOL variations
4. **Performance Tuning**: Optimize for your specific use cases
5. **Integration Examples**: See how to integrate with migration and analysis tools