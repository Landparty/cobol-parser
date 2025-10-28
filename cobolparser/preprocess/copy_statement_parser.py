"""
COPY statement parser for COBOL copybook expansion.

This module handles parsing of COBOL COPY statements from source code,
supporting various syntax variants including library qualifiers and
REPLACING clauses.
"""

import re
from typing import Optional
from .models import CopyStatement


# COPY statement regex patterns supporting IBM Enterprise COBOL syntax
# Matches: COPY member, COPY "member", COPY member IN/OF library
COPY_PATTERN = re.compile(
    r'\bCOPY\s+'  # COPY keyword
    r'(?:'  # Member name (quoted or unquoted)
        r'"([^"]+)"'  # Quoted member name
        r'|'
        r"'([^']+)'"  # Single-quoted member name
        r'|'
        r'(\S+?)'  # Unquoted member name
    r')'
    r'(?:\s+(?:IN|OF)\s+(\S+))?'  # Optional library qualifier (IN/OF library-name)
    r'(?:\s+REPLACING\s+(.+?))?'  # Optional REPLACING clause
    r'\s*\.',  # Terminating period
    re.IGNORECASE | re.DOTALL
)


def extract_copy_statements(source_code: str, source_file: str = "<main>") -> list[CopyStatement]:
    """
    Extract all COPY statements from COBOL source code.
    
    Args:
        source_code: COBOL source code to parse
        source_file: Source file name for location tracking
        
    Returns:
        List of CopyStatement objects representing each COPY statement found
        
    Example:
        >>> statements = extract_copy_statements("COPY EMPLOYEE.")
        >>> print(statements[0].member_name)
        EMPLOYEE
    """
    statements = []
    
    for match in COPY_PATTERN.finditer(source_code):
        # Extract member name (try all three capture groups)
        member_name = match.group(1) or match.group(2) or match.group(3)
        library_qualifier = match.group(4)
        replacing_text = match.group(5)
        
        # Calculate line and column from match position
        line_num = source_code[:match.start()].count('\n') + 1
        col_num = match.start() - source_code.rfind('\n', 0, match.start())
        
        # Parse REPLACING clause if present
        replacing_clauses = None
        if replacing_text:
            replacing_clauses = parse_replacing_clause(replacing_text)
        
        statement = CopyStatement(
            member_name=member_name.strip(),
            library_qualifier=library_qualifier.strip() if library_qualifier else None,
            replacing_clauses=replacing_clauses,
            source_location=(source_file, line_num, col_num),
            original_text=match.group(0)
        )
        statements.append(statement)
    
    return statements


def parse_replacing_clause(replacing_text: str) -> list[tuple[str, str]]:
    """
    Parse COPY REPLACING clause into find/replace pairs.
    
    Supports IBM Enterprise COBOL REPLACING syntax:
    - ==text== BY ==replacement==
    - :text: BY :replacement:
    
    Args:
        replacing_text: The REPLACING clause text (after REPLACING keyword)
        
    Returns:
        List of (find, replace) tuples
        
    Example:
        >>> parse_replacing_clause("==OLD== BY ==NEW==")
        [('OLD', 'NEW')]
    """
    pairs = []
    
    # Pattern for ==delimiter== or :delimiter: style replacements
    pattern = re.compile(
        r'(?:==(.+?)==|:(.+?):)'  # Find text (either == or : delimited)
        r'\s+BY\s+'
        r'(?:==(.+?)==|:(.+?):)',  # Replace text (either == or : delimited)
        re.IGNORECASE | re.DOTALL
    )
    
    for match in pattern.finditer(replacing_text):
        find_text = match.group(1) or match.group(2)
        replace_text = match.group(3) or match.group(4)
        pairs.append((find_text.strip(), replace_text.strip()))
    
    return pairs


def track_source_location(
    line_number: int,
    source_file: str,
    original_line: int
) -> tuple[int, tuple[str, int]]:
    """
    Create a source location mapping entry.
    
    Args:
        line_number: Line number in expanded output
        source_file: Original source file path
        original_line: Line number in original source file
        
    Returns:
        Tuple of (line_number, (source_file, original_line))
    """
    return (line_number, (source_file, original_line))


__all__ = [
    'extract_copy_statements',
    'parse_replacing_clause',
    'track_source_location',
    'COPY_PATTERN',
]
