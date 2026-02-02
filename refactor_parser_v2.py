#!/usr/bin/env python
"""Script to refactor parser.py by safely removing obsolete division parsing code."""

import re

def find_method_body(lines, start_idx):
    """Find the end line of a method starting at start_idx."""
    start_line = lines[start_idx]
    # Get the indentation level of the 'def' keyword
    indent_match = re.match(r'^(\s*)', start_line)
    method_indent = len(indent_match.group(1)) if indent_match else 0
    
    # Find the next method/class definition at the same indent level
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        # Skip empty lines and comments
        if not line.strip() or line.strip().startswith('#'):
            continue
        # Check indentation
        current_indent_match = re.match(r'^(\s*)', line)
        current_indent = len(current_indent_match.group(1)) if current_indent_match else 0
        
        # If we find a 'def' at the same indentation level, we've reached the next method
        if re.match(r'\s*def ', line) and current_indent == method_indent:
            return i - 1  # Return the last line before the next method
    
    return len(lines) - 1  # End of file

def refactor_parser():
    """Remove obsolete division parsing methods."""
    with open('cobolparser/parser.py', 'r') as f:
        lines = f.readlines()
    
    # Methods to remove by exact starting point (line number - 1 for 0-indexing)
    methods_to_remove = [
        'def parse_program(self) -> Optional[CobolProgram]:',  # Old version at ~474
        'def parse_identification_division(self) -> bool:',
        'def parse_environment_division(self) -> bool:',
        'def parse_environment_sections(self) -> None:',
        'def parse_configuration_section(self) -> None:',
        'def parse_input_output_section(self) -> None:',
        'def parse_file_control_paragraph(self) -> None:',
        'def parse_select_statement(self) -> None:',
        'def parse_data_division(self) -> bool:',
        'def parse_data_section(self) -> None:',
        'def parse_working_storage_section(self) -> None:',
        'def parse_local_storage_section(self) -> None:',
        'def parse_linkage_section(self) -> None:',
        'def parse_file_section(self) -> None:',
        'def parse_fd_record(self,',
        'def parse_data_items(self) -> None:',
        'def parse_data_item(self) -> Optional[CobolDataItem]:',
        'def parse_procedure_division(self) -> bool:',
        'def parse_statements(self) -> None:',
        'def parse_sentence(self, ',
        'def parse_paragraph_or_statement(self) -> None:',
        # Also remove all _parse_*_inline methods
    ]
    
    # Find line numbers for each method
    lines_to_remove = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if this line starts any method we want to remove
        for method_sig in methods_to_remove:
            if method_sig in line:
                # Found a method to remove
                end_idx = find_method_body(lines, i)
                print(f"Removing lines {i+1}-{end_idx+1}: {method_sig}")
                for j in range(i, end_idx + 1):
                    lines_to_remove.add(j)
                i = end_idx
                break
        i += 1
    
    # Also remove all _parse_*_inline and _skip_* methods
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'\s{4}def _parse.*inline|_skip_to_next_verb|_is_keyword|_is_statement_start', line):
            end_idx = find_method_body(lines, i)
            print(f"Removing lines {i+1}-{end_idx+1}: (inline/skip method)")
            for j in range(i, end_idx + 1):
                lines_to_remove.add(j)
            i = end_idx
        i += 1
    
    # Filter lines
    filtered_lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]
    
    print(f"\nOriginal lines: {len(lines)}")
    print(f"Lines removed: {len(lines_to_remove)}")
    print(f"New total: {len(filtered_lines)}")
    
    # Write back
    with open('cobolparser/parser.py', 'w') as f:
        f.writelines(filtered_lines)
    
    print("File refactored successfully!")

if __name__ == '__main__':
    refactor_parser()
