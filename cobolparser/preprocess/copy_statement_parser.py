"""
COPY statement parser for COBOL copybook expansion.

This module handles parsing of COBOL COPY statements from source code,
supporting various syntax variants including library qualifiers,
REPLACING clauses with LEADING/TRAILING modifiers, and SUPPRESS options.
"""

import re
from typing import Optional
from .models import CopyStatement, ReplacingClause, SuppressClause


# COPY statement regex patterns supporting IBM Enterprise COBOL syntax
# Matches: COPY member, COPY "member", COPY member IN/OF library, COPY member SUPPRESS, COPY member REPLACING
COPY_PATTERN = re.compile(
    r'\bCOPY\s+'  # COPY keyword
    r'(?:'  # Member name (quoted or unquoted)
        r'"([^"]+)"'  # Quoted member name (group 1)
        r'|'
        r"'([^']+)'"  # Single-quoted member name (group 2)
        r'|'
        r'([A-Za-z0-9_-]+)'  # Unquoted member name (group 3)
    r')'
    r'(?:\s+(?:IN|OF)\s+([A-Za-z0-9_-]+))?'  # Optional library qualifier (group 4)
    r'(?:\s+(SUPPRESS)(?:\s+(PRINTING))?)?'  # Optional SUPPRESS [PRINTING] clause (groups 5, 6)
    r'(?:\s+REPLACING\s+(.+?))?'  # Optional REPLACING clause (group 7)
    r'\s*\.',  # Terminating period
    re.IGNORECASE | re.DOTALL
)


def normalize_continuation_lines(source: str) -> str:
    """
    Normalize COBOL fixed-format continuation lines for COPY statement detection.
    
    In fixed-format COBOL:
    - Columns 1-6: Sequence number area
    - Column 7: Indicator area ('-' for continuation)
    - Columns 8-72: Program text area
    
    This function merges continuation lines to enable proper COPY statement parsing.
    
    Args:
        source: COBOL source code (may contain continuation lines)
        
    Returns:
        Source with continuation lines merged
        
    Example:
        >>> source = "       COPY EMPLOYEE REPLACING\\n      -    ==OLD== BY ==NEW==."
        >>> normalize_continuation_lines(source)
        "       COPY EMPLOYEE REPLACING ==OLD== BY ==NEW==."
    """
    lines = source.split('\n')
    result = []
    
    for i, line in enumerate(lines):
        # Check if this is a continuation line (column 7 is '-')
        if len(line) >= 7 and line[6] == '-':
            # This is a continuation line
            if result:
                # Get the continuation text (columns 8 onwards)
                continuation_text = line[7:] if len(line) > 7 else ""
                # Append to previous line (trimming trailing spaces from previous, 
                # but preserving leading spaces of continuation for string literals)
                result[-1] = result[-1].rstrip() + continuation_text
            else:
                # Orphan continuation line - just add the text part
                result.append(line[7:] if len(line) > 7 else "")
        else:
            result.append(line)
    
    return '\n'.join(result)


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
        
        >>> statements = extract_copy_statements("COPY DATA SUPPRESS REPLACING ==X== BY ==Y==.")
        >>> print(statements[0].is_suppressed)
        True
    """
    # Normalize continuation lines before parsing
    normalized_source = normalize_continuation_lines(source_code)
    
    statements = []
    
    for match in COPY_PATTERN.finditer(normalized_source):
        # Extract member name (try all three capture groups)
        member_name = match.group(1) or match.group(2) or match.group(3)
        library_qualifier = match.group(4)
        suppress_keyword = match.group(5)
        suppress_details = match.group(6)
        replacing_text = match.group(7)
        
        # Calculate line and column from match position
        line_num = normalized_source[:match.start()].count('\n') + 1
        col_num = match.start() - normalized_source.rfind('\n', 0, match.start())
        
        # Parse SUPPRESS clause if present
        suppress_clause = None
        if suppress_keyword:
            suppress_clause = parse_suppress_clause(suppress_details)
        
        # Parse REPLACING clause if present
        replacing_clauses = None
        if replacing_text:
            replacing_clauses = parse_replacing_clause(replacing_text)
        
        statement = CopyStatement(
            member_name=member_name.strip(),
            library_qualifier=library_qualifier.strip() if library_qualifier else None,
            replacing_clauses=replacing_clauses,
            suppress_clause=suppress_clause,
            source_location=(source_file, line_num, col_num),
            original_text=match.group(0)
        )
        statements.append(statement)
    
    return statements


def parse_suppress_clause(suppress_text: Optional[str]) -> SuppressClause:
    """
    Parse COPY SUPPRESS clause into a SuppressClause object.
    
    Supports IBM Enterprise COBOL SUPPRESS syntax:
    - SUPPRESS (suppress all)
    - SUPPRESS 1 THRU 5 (suppress lines 1-5)
    - SUPPRESS 1 THRU 5, 10, 15 THRU 20 (multiple ranges and lines)
    
    Args:
        suppress_text: The SUPPRESS clause text (after SUPPRESS keyword), or None
        
    Returns:
        SuppressClause object representing the suppression rules
        
    Example:
        >>> clause = parse_suppress_clause(None)
        >>> clause.suppress_all
        True
        
        >>> clause = parse_suppress_clause("1 THRU 5, 10")
        >>> clause.line_ranges
        [(1, 5)]
        >>> clause.single_lines
        [10]
    """
    if not suppress_text or not suppress_text.strip():
        # SUPPRESS with no details means suppress all
        return SuppressClause(suppress_all=True)
    
    suppress_text = suppress_text.strip()
    line_ranges = []
    single_lines = []
    
    # Pattern for "N THRU M" or "N THROUGH M"
    range_pattern = re.compile(r'(\d+)\s+(?:THRU|THROUGH)\s+(\d+)', re.IGNORECASE)
    
    # Find all ranges
    for match in range_pattern.finditer(suppress_text):
        start = int(match.group(1))
        end = int(match.group(2))
        line_ranges.append((start, end))
    
    # Remove ranges from text to find standalone numbers
    remaining = range_pattern.sub('', suppress_text)
    
    # Find standalone line numbers
    for num_match in re.finditer(r'\b(\d+)\b', remaining):
        single_lines.append(int(num_match.group(1)))
    
    return SuppressClause(
        suppress_all=False,
        line_ranges=line_ranges,
        single_lines=single_lines
    )


def parse_replacing_clause(replacing_text: str) -> list[ReplacingClause]:
    """
    Parse COPY REPLACING clause into ReplacingClause objects.
    
    Supports IBM Enterprise COBOL REPLACING syntax:
    - ==text== BY ==replacement==
    - :text: BY :replacement:
    - LEADING ==prefix== BY ==new-prefix==
    - TRAILING ==suffix== BY ==new-suffix==
    
    Args:
        replacing_text: The REPLACING clause text (after REPLACING keyword)
        
    Returns:
        List of ReplacingClause objects
        
    Example:
        >>> clauses = parse_replacing_clause("==OLD== BY ==NEW==")
        >>> clauses[0].find_text
        'OLD'
        >>> clauses[0].mode
        'ALL'
        
        >>> clauses = parse_replacing_clause("LEADING ==:PREFIX:== BY ==EMP-==")
        >>> clauses[0].mode
        'LEADING'
    """
    clauses = []
    
    # Enhanced pattern with LEADING/TRAILING support
    # Supports both == and : delimiters, and allows empty replacement text
    pattern = re.compile(
        r'(LEADING|TRAILING)?\s*'  # Optional modifier (group 1)
        r'(?:==([^=]+)==|:([^:]+):)'  # Find text (groups 2, 3)
        r'\s+BY\s+'
        r'(?:==([^=]*)==|:([^:]*):)',  # Replace text (groups 4, 5) - allow empty
        re.IGNORECASE | re.DOTALL
    )
    
    for match in pattern.finditer(replacing_text):
        modifier = match.group(1)
        find_text = match.group(2) or match.group(3)
        replace_text = match.group(4) if match.group(4) is not None else match.group(5)
        
        if replace_text is None:
            replace_text = ""
        
        mode = modifier.upper() if modifier else "ALL"
        
        clauses.append(ReplacingClause(
            find_text=find_text.strip(),
            replace_text=replace_text.strip(),
            mode=mode
        ))
    
    return clauses


def apply_replacing_clauses(content: str, clauses: list[ReplacingClause]) -> str:
    """
    Apply REPLACING clauses to copybook content.
    
    Handles different replacement modes:
    - ALL: Replace all occurrences
    - LEADING: Replace only at the start of words/identifiers
    - TRAILING: Replace only at the end of words/identifiers
    
    Args:
        content: Copybook content to modify
        clauses: List of ReplacingClause objects to apply
        
    Returns:
        Modified content with replacements applied
        
    Example:
        >>> content = "01 :PREFIX:-FIELD PIC X(10)."
        >>> clauses = [ReplacingClause(":PREFIX:", "EMP", "ALL")]
        >>> apply_replacing_clauses(content, clauses)
        '01 EMP-FIELD PIC X(10).'
    """
    result = content
    
    for clause in clauses:
        if clause.mode == "ALL":
            # Simple string replacement
            result = result.replace(clause.find_text, clause.replace_text)
        
        elif clause.mode == "LEADING":
            # Replace only at the start of words
            # Word boundary before, but text must be followed by word characters or hyphen
            pattern = re.compile(
                r'\b' + re.escape(clause.find_text) + r'(?=[-\w])',
                re.IGNORECASE
            )
            result = pattern.sub(clause.replace_text, result)
        
        elif clause.mode == "TRAILING":
            # Replace only at the end of words
            # Text must be preceded by word characters or hyphen, word boundary after
            pattern = re.compile(
                r'(?<=[-\w])' + re.escape(clause.find_text) + r'\b',
                re.IGNORECASE
            )
            result = pattern.sub(clause.replace_text, result)
    
    return result


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
    'parse_suppress_clause',
    'apply_replacing_clauses',
    'normalize_continuation_lines',
    'track_source_location',
    'COPY_PATTERN',
]
