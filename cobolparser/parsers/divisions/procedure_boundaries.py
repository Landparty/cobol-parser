"""Paragraph/section boundary detection for the PROCEDURE DIVISION.

Collaborator module of
:class:`~cobolparser.parsers.divisions.procedure.ProcedureDivisionParser`:
the lookahead predicates that decide whether the token stream is positioned
at a new paragraph, a section header, or a statement keyword.
"""

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import Token
from cobolparser.parsers.statements._utils import STATEMENT_KEYWORDS

# Token types that can carry a procedure (paragraph/section) name. COBOL
# allows all-digit procedure names (``1000 THRU 1999`` style numbering is
# idiomatic in PERFORM THRU code); the lexer emits those as NUMERIC_LITERAL
# (or LEVEL_NUMBER for 1-2 digit values), never IDENTIFIER.
_NAME_TOKEN_TYPES = ("IDENTIFIER", "NUMERIC_LITERAL", "LEVEL_NUMBER")


def _is_procedure_name_token(token: Token | None) -> bool:
    """True if *token* can be a procedure name: an identifier, or an
    all-digit token (numeric paragraph names like ``1000``).

    A reserved statement verb can never legally be a paragraph name, so it
    is excluded even when the lexer has no dedicated ``TokenType`` for it
    and it would otherwise lex as a plain ``IDENTIFIER`` (e.g. ``PURGE``,
    ``RAISE``, ``RESUME``). Without this guard a bare unsupported verb
    immediately followed by its own terminating period -- ``RESUME.`` -- is
    indistinguishable by shape alone from a paragraph header ``RESUME.``,
    which stops the PROCEDURE DIVISION's statement loop from ever consuming
    it and can leave the token stream cursor unable to advance. Mirrors the
    same guard :func:`~cobolparser.parsers.statements._utils.
    looks_like_paragraph_boundary` already applies (H9,
    ``reports/open-findings.md``).
    """
    if token is None or not token.value:
        return False
    if token.value.upper() in STATEMENT_KEYWORDS:
        return False
    if token.type.name == "IDENTIFIER":
        return True
    return token.type.name in _NAME_TOKEN_TYPES and token.value.isdigit()


def is_paragraph_or_section_start(token_stream: ITokenStream) -> bool:
    """Check if current position starts a new paragraph or section.

    A paragraph/section starts when a procedure name (an identifier, or an
    all-digit numeric paragraph name) is followed by either:
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
            if _is_procedure_name_token(next_token):
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

    # Case 2: Original logic - current token is a procedure name (an
    # identifier, or an all-digit numeric paragraph name)
    if not _is_procedure_name_token(token):
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

    # ``EXIT SECTION.`` is the statement, never a section named EXIT (a
    # reserved word): written straight after a section header it became an
    # empty section ``EXIT`` that swallowed the paragraphs after it.
    if (token.value or "").upper() == "EXIT":
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
