"""Paragraph/section boundary detection for the PROCEDURE DIVISION.

Collaborator module of
:class:`~cobolparser.parsers.divisions.procedure.ProcedureDivisionParser`:
the lookahead predicates that decide whether the token stream is positioned
at a new paragraph, a section header, or a statement keyword.
"""

from cobolparser.core.interfaces import ITokenStream
from cobolparser.parsers.statements._utils import STATEMENT_KEYWORDS


def is_paragraph_or_section_start(token_stream: ITokenStream) -> bool:
    """Check if current position starts a new paragraph or section.

    A paragraph/section starts when an identifier is followed by either:
    - A period (paragraph end/start)
    - SECTION keyword (section definition)

    Handles the case where current position is at a period (end of previous
    paragraph), and next token is a paragraph name identifier.

    Args:
        token_stream: Token stream to check

    Returns:
        True if at paragraph/section start
    """
    if token_stream.is_empty():
        return False

    token = token_stream.peek(0)
    if not token:
        return False

    # Case 1: If current token is a PERIOD, check if the next token after it
    # is an IDENTIFIER (new paragraph name)
    if token.value == ".":
        # Skip the period and any whitespace/newlines
        next_idx = 1
        while next_idx < 10:  # Reasonable lookahead
            next_token = token_stream.peek(next_idx)
            if not next_token:
                return False
            if next_token.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                next_idx += 1
                continue
            # Found a non-whitespace token
            if next_token.type.name == "IDENTIFIER":
                # Check if it's followed by SECTION or a period (paragraph name pattern)
                next_next_idx = next_idx + 1
                while next_next_idx < 10:
                    next_next_token = token_stream.peek(next_next_idx)
                    if not next_next_token:
                        return True  # Assume it's a paragraph name
                    if next_next_token.type.name in ("NEWLINE", "WHITESPACE"):
                        next_next_idx += 1
                        continue
                    # Check for SECTION or period after identifier
                    if next_next_token.value == "." or (
                        next_next_token.value
                        and next_next_token.value.upper() == "SECTION"
                    ):
                        return True
                    break
                return False
            return False
        return False

    # Case 2: Original logic - current token is an IDENTIFIER
    if token.type.name != "IDENTIFIER":
        return False

    # Look ahead for SECTION or period
    next_token = token_stream.peek(1)
    if not next_token:
        return False

    if next_token.value == ".":
        return True

    if next_token.value and next_token.value.upper() == "SECTION":
        return True

    return False


def is_section_marker(token_stream: ITokenStream) -> bool:
    """Check if current token starts a section definition.

    A section marker is followed by SECTION keyword.

    Args:
        token_stream: Token stream to check

    Returns:
        True if current position marks a section start
    """
    if token_stream.is_empty():
        return False

    token = token_stream.peek(0)
    if not token:
        return False

    # Look ahead for SECTION keyword
    for offset in range(1, 3):
        next_tok = token_stream.peek(offset)
        if next_tok and next_tok.value.upper() == "SECTION":
            return True

    return False


def is_statement_keyword(word: str) -> bool:
    """Check if word is a known statement keyword.

    Args:
        word: Word to check

    Returns:
        True if word is a statement keyword
    """
    return word.upper() in STATEMENT_KEYWORDS
