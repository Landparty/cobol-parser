"""RD report-description clause parsing for the REPORT SECTION.

Collaborator of :class:`~cobolparser.parsers.divisions.data.DataDivisionParser`
(2026-09-02, REPORT SECTION support): captures the clauses of an ``RD``
entry -- ``CODE``, ``CONTROL(S) [ARE] {FINAL | name ...}``, ``PAGE [LIMIT]
n [LINES] [HEADING n] [FIRST DETAIL n] [LAST DETAIL n] [FOOTING n]``,
``GLOBAL`` -- as a structured, JSON-serializable mapping, the same way
:class:`~.data_file_description.FileDescriptionClauseParser` captures an
FD's. Tokens no clause claims are kept under ``"raw"`` so nothing is lost
silently.
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType

from .data_clauses import _DIVISION_TOKEN_TYPES

# Words that begin (or continue) an RD clause.
_RD_CLAUSE_STARTS: frozenset[str] = frozenset(
    {"CODE", "CONTROL", "CONTROLS", "PAGE", "GLOBAL"}
)
# PAGE sub-clauses; each takes one integer.
_PAGE_SUBCLAUSES: dict[str, str] = {
    "HEADING": "heading",
    "FIRST": "first_detail",
    "LAST": "last_detail",
    "FOOTING": "footing",
}
_NOISE_TYPES = frozenset({TokenType.NEWLINE, TokenType.WHITESPACE, TokenType.COMMENT})


def _upper(token: Any) -> str:
    return (token.value or "").upper() if token is not None else ""


class ReportDescriptionClauseParser:
    """Parses the clause list of an ``RD report-name ...`` entry."""

    @staticmethod
    def _skip_noise(token_stream: ITokenStream) -> Any:
        while not token_stream.is_empty():
            token = token_stream.peek()
            if token is None or token.type not in _NOISE_TYPES:
                return token
            token_stream.consume()
        return None

    @staticmethod
    def _level_starts_group(token_stream: ITokenStream) -> bool:
        """True when the LEVEL_NUMBER at the cursor begins a report group
        entry (``01 name`` or an anonymous ``01 TYPE IS ...``) rather than
        being an RD clause operand such as the 60 in ``PAGE LIMIT 60``."""
        offset = 1
        while True:
            nxt = token_stream.peek(offset)
            if nxt is None:
                return False
            if nxt.type in _NOISE_TYPES:
                offset += 1
                continue
            if nxt.type in (TokenType.IDENTIFIER, TokenType.LINE, TokenType.NEXT):
                return (
                    _upper(nxt)
                    not in {"LINES", "LINE", "HEADING", "FIRST", "LAST", "FOOTING"}
                    or nxt.type != TokenType.IDENTIFIER
                )
            return _upper(nxt) == "FILLER"

    def _take_int(self, token_stream: ITokenStream) -> int | None:
        token = self._skip_noise(token_stream)
        if token is None or token.type not in (
            TokenType.LEVEL_NUMBER,
            TokenType.NUMERIC_LITERAL,
        ):
            return None
        token_stream.consume()
        try:
            return int(token.value)
        except (TypeError, ValueError):
            return None

    def parse_rd_clauses(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse the clauses of an RD entry, consuming the terminating period.

        Stops (without consuming) at a level number that starts a report
        group or at a division header, so a missing period cannot swallow
        the first group.
        """
        result: dict[str, Any] = {
            "code": None,
            "controls": [],
            "page_limit": None,
            "heading": None,
            "first_detail": None,
            "last_detail": None,
            "footing": None,
            "is_global": False,
            "raw": [],
        }
        while not token_stream.is_empty():
            token = self._skip_noise(token_stream)
            if token is None:
                break
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if token.type in _DIVISION_TOKEN_TYPES:
                break
            if token.type == TokenType.LEVEL_NUMBER and self._level_starts_group(
                token_stream
            ):
                break
            word = _upper(token)
            if word == "CODE":
                token_stream.consume()
                nxt = self._skip_noise(token_stream)
                if _upper(nxt) == "IS":
                    token_stream.consume()
                    nxt = self._skip_noise(token_stream)
                if nxt is not None and nxt.type != TokenType.PERIOD:
                    result["code"] = nxt.value
                    token_stream.consume()
            elif word in ("CONTROL", "CONTROLS"):
                token_stream.consume()
                nxt = self._skip_noise(token_stream)
                if _upper(nxt) in ("IS", "ARE"):
                    token_stream.consume()
                while True:
                    nxt = self._skip_noise(token_stream)
                    if nxt is None or nxt.type != TokenType.IDENTIFIER:
                        break
                    if _upper(nxt) in _RD_CLAUSE_STARTS:
                        break
                    result["controls"].append(nxt.value)
                    token_stream.consume()
            elif word == "PAGE":
                token_stream.consume()
                nxt = self._skip_noise(token_stream)
                if _upper(nxt) in ("LIMIT", "LIMITS"):
                    token_stream.consume()
                    nxt = self._skip_noise(token_stream)
                if _upper(nxt) in ("IS", "ARE"):
                    token_stream.consume()
                result["page_limit"] = self._take_int(token_stream)
                nxt = self._skip_noise(token_stream)
                if _upper(nxt) in ("LINE", "LINES"):
                    token_stream.consume()
            elif word in _PAGE_SUBCLAUSES:
                token_stream.consume()
                nxt = self._skip_noise(token_stream)
                if word in ("FIRST", "LAST") and _upper(nxt) in ("DETAIL", "DE"):
                    token_stream.consume()
                    nxt = self._skip_noise(token_stream)
                if _upper(nxt) == "IS":
                    token_stream.consume()
                result[_PAGE_SUBCLAUSES[word]] = self._take_int(token_stream)
            elif word == "GLOBAL":
                token_stream.consume()
                result["is_global"] = True
            elif word == "IS" and _upper(token_stream.peek(1)) == "GLOBAL":
                token_stream.consume()
            else:
                result["raw"].append(token.value)
                token_stream.consume()
        return result


__all__ = ["ReportDescriptionClauseParser"]
