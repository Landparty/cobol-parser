#!/usr/bin/env python
"""Script to refactor parser.py by removing obsolete division parsing code."""

import re

def refactor_parser():
    # Read the file
    with open('cobolparser/parser.py', 'r') as f:
        lines = f.readlines()
    
    # Find method boundaries by regex
    # We'll keep everything except lines that match division parsing method patterns
    
    # Methods to remove (by pattern)
    division_methods = [
        r'^\s{4}def parse_program\(self\)',  # Old version (line 474)
        r'^\s{4}def parse_identification_division',
        r'^\s{4}def parse_environment_division',
        r'^\s{4}def parse_environment_sections',
        r'^\s{4}def parse_configuration_section',
        r'^\s{4}def parse_input_output_section',
        r'^\s{4}def parse_file_control_paragraph',
        r'^\s{4}def parse_select_statement',
        r'^\s{4}def _parse_select_',  # All SELECT-related helpers
        r'^\s{4}def parse_data_division',
        r'^\s{4}def parse_data_sections',
        r'^\s{4}def parse_working_storage_section',
        r'^\s{4}def parse_local_storage_section',
        r'^\s{4}def parse_linkage_section',
        r'^\s{4}def parse_file_section',
        r'^\s{4}def parse_fd_record',
        r'^\s{4}def _parse_fd_',  # All FD-related helpers
        r'^\s{4}def parse_data_items',
        r'^\s{4}def parse_data_item',
        r'^\s{4}def _parse_usage_clause',
        r'^\s{4}def _parse_occurs_clause',
        r'^\s{4}def parse_procedure_division',
        r'^\s{4}def parse_statements',
        r'^\s{4}def parse_sentence',
        r'^\s{4}def parse_paragraph_or_statement',
        r'^\s{4}def _parse.*inline',  # All inline parsing helpers
        r'^\s{4}def _skip_to.*verb',
        r'^\s{4}def _skip_whitespace',
        r'^\s{4}def _is_keyword',
        r'^\s{4}def _is_statement_start',
        r'^\s{4}def _parse_nested_statements',
        r'^\s{4}def _parse_size_error',
        r'^\s{4}def _parse_overflow',
        r'^\s{4}def _parse_integer_token',
        r'^\s{4}def _parse_picture_pattern',
        r'^\s{4}def _validate_',  # All validation methods for divisions
        r'^\s{4}def skip_to_next_',  # Division skipping methods
    ]
    
    # Filter lines - keep a line if NO division method pattern matches it
    # BUT we need to discard entire method bodies, not just method definitions
    
    # Better approach: Use line numbers based on our earlier findings
    # Remove lines in these ranges:
    remove_line_ranges = [
        # (start_line, end_line) - line numbers are 1-indexed, convert to 0-indexed
        (473, 579),     #Line 474-580: old parse_program()
        (581, 659),     # 582-660: parse_identification_division
        (659, 1417),    # 660-1418: parse_environment_* methods
        (1417, 2792),   # 1418-2793: parse_data_* methods
        (2792, 5523),   # 2793-5524: parse_procedure_* methods
    ]
    
    # Convert to set of lines to remove (0-indexed)
    lines_to_remove = set()
    for start, end in remove_line_ranges:
        for i in range(start, end):
            lines_to_remove.add(i)
    
    # Filter lines
    filtered_lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]
    
    print(f"Original lines: {len(lines)}")
    print(f"Lines removed: {len(lines_to_remove)}")
    print(f"New total: {len(filtered_lines)}")
    
    # Write back
    with open('cobolparser/parser.py', 'w') as f:
        f.writelines(filtered_lines)
    
    print("File refactored successfully!")

if __name__ == '__main__':
    refactor_parser()
