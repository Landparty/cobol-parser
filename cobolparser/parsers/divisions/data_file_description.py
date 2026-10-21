"""FD/SD file-description clause parsing for the DATA DIVISION.

Collaborator of :class:`~cobolparser.parsers.divisions.data.DataDivisionParser`:
captures the clauses of an FD/SD entry in the FILE SECTION (BLOCK CONTAINS,
RECORD/RECORD VARYING, LABEL RECORDS, RECORDING MODE, CODE-SET, DATA RECORDS,
LINAGE, VALUE OF, GLOBAL, EXTERNAL) as a structured, JSON-serializable mapping
so the record layout's physical attributes survive into the AST.
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType

from .data_clauses import _DIVISION_TOKEN_TYPES

# Keywords that begin an FD/SD file-description clause. Used to segment the
# clause tokens captured by ``parse_fd_clauses``.
_FD_CLAUSE_STARTS: frozenset[str] = frozenset(
    {
        "BLOCK",
        "RECORD",
        "LABEL",
        "RECORDING",
        "CODE-SET",
        "DATA",
        "LINAGE",
        "VALUE",
        "GLOBAL",
        "EXTERNAL",
        # Report Writer: ``REPORT IS r`` / ``REPORTS ARE r1 r2`` -- the
        # reports INITIATE / GENERATE / TERMINATE write to this file.
        "REPORT",
        "REPORTS",
    }
)


def _keyword_int(tokens: list[str], upper: list[str], keyword: str) -> int | None:
    """The integer right after *keyword* in a clause's tokens, or None."""
    if keyword not in upper:
        return None
    idx = upper.index(keyword)
    if idx + 1 < len(tokens):
        try:
            return int(tokens[idx + 1])
        except (TypeError, ValueError):
            return None
    return None


class FileDescriptionClauseParser:
    """Parses the clause list of an FD/SD file description entry."""

    @staticmethod
    def _level_starts_record(token_stream: ITokenStream) -> bool:
        """Return True if the LEVEL_NUMBER at the cursor begins a record entry.

        A record description is a level number immediately followed by a
        data-name (an IDENTIFIER, or FILLER), e.g. ``01 IN-REC``. A bare
        integer that is merely a clause operand (``RECORD CONTAINS 77``) is
        followed by a keyword or another number instead, so it must not be
        mistaken for the start of a record. NEWLINE tokens between the level
        and the name are skipped.
        """
        offset = 1
        while True:
            nxt = token_stream.peek(offset)
            if nxt is None:
                return False
            if nxt.type == TokenType.NEWLINE:
                offset += 1
                continue
            if nxt.type == TokenType.IDENTIFIER:
                return True
            return bool(nxt.value and nxt.value.upper() == "FILLER")

    def parse_fd_clauses(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse the clauses of an FD/SD file description entry.

        Walks tokens from just after the file name up to (and consuming) the
        terminating period, or up to the next level number / division header.
        Recognized clauses (BLOCK CONTAINS, RECORD/RECORD VARYING, LABEL
        RECORDS, RECORDING MODE, CODE-SET, DATA RECORDS, LINAGE, VALUE OF,
        GLOBAL, EXTERNAL, REPORT(S)) are returned as a structured, JSON-serializable
        mapping. Unrecognized tokens for a clause are preserved as raw text so
        nothing is silently lost.
        """
        raw: dict[str, list[str]] = {}
        current_key: str | None = None

        while not token_stream.is_empty():
            t = token_stream.peek()
            if t is None:
                break
            if t.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if t.type in _DIVISION_TOKEN_TYPES:
                break
            # The lexer tags every bare integer as LEVEL_NUMBER, so a clause
            # operand such as the 77 in "RECORD CONTAINS 77 CHARACTERS" or the
            # 1 in "BLOCK CONTAINS 1 RECORDS" is indistinguishable from a record
            # level by value alone. A real record description is a level number
            # immediately followed by a data-name (IDENTIFIER/FILLER); operands
            # are followed by a keyword (RECORDS/CHARACTERS/...) or a number.
            # Only the former should stop clause capture.
            if t.type == TokenType.LEVEL_NUMBER:
                if self._level_starts_record(token_stream):
                    break
                if current_key is not None and t.value:
                    raw[current_key].append(t.value)
                token_stream.consume()
                continue
            if t.type == TokenType.NEWLINE:
                token_stream.consume()
                continue

            value_upper = t.value.upper() if t.value else ""
            # "RECORD" is also the second word of the LABEL RECORD / DATA RECORD
            # clauses; don't let it start a fresh RECORD clause in that context.
            # Only the RECORD *immediately* after LABEL/DATA is that second word:
            # a later one ("LABEL RECORDS ARE STANDARD RECORD CONTAINS 30") is
            # a RECORD CONTAINS clause of its own.
            starts_clause = value_upper in _FD_CLAUSE_STARTS and not (
                value_upper == "RECORD"
                and current_key in ("LABEL", "DATA")
                and not raw[current_key]
            )
            if starts_clause:
                current_key = value_upper
                raw.setdefault(current_key, [])
            elif current_key is not None and t.value:
                raw[current_key].append(t.value)
            token_stream.consume()

        return self._structure_fd_clauses(raw)

    @staticmethod
    def _structure_fd_clauses(raw: dict[str, list[str]]) -> dict[str, Any]:
        """Normalize raw FD clause tokens into structured fields."""

        def _ints(tokens: list[str]) -> list[int]:
            out: list[int] = []
            for tok in tokens:
                try:
                    out.append(int(tok))
                except (TypeError, ValueError):
                    continue
            return out

        clauses: dict[str, Any] = {}

        for key, tokens in raw.items():
            upper = [tok.upper() for tok in tokens]

            if key in ("GLOBAL", "EXTERNAL"):
                clauses[key.lower().replace("-", "_")] = True

            elif key == "BLOCK":
                nums = _ints(tokens)
                unit = (
                    "RECORDS"
                    if "RECORDS" in upper
                    else ("CHARACTERS" if "CHARACTERS" in upper else None)
                )
                clauses["block_contains"] = {
                    "min": nums[0] if len(nums) > 1 else None,
                    "max": nums[-1] if nums else None,
                    "unit": unit,
                }

            elif key == "RECORD":
                if "VARYING" in upper:
                    nums = _ints(tokens)
                    low: int | None = nums[0] if nums else None
                    # A lone integer with neither FROM nor TO is integer-6,
                    # the minimum (``[[FROM] integer-6] [TO integer-7]``):
                    # the maximum stays None, the largest record's size.
                    high: int | None = nums[1] if len(nums) > 1 else None
                    if "FROM" in upper or "TO" in upper:
                        # ``FROM integer`` and ``TO integer`` are each
                        # optional (an omitted bound is the smallest /
                        # largest record description's size), so each is
                        # read after its own keyword. Taking the numbers by
                        # position made ``VARYING IN SIZE TO 80`` report a
                        # minimum of 80, and ``FROM 20`` a maximum of 20.
                        low = _keyword_int(tokens, upper, "FROM")
                        high = _keyword_int(tokens, upper, "TO")
                        if low is None and "FROM" not in upper and "TO" in upper:
                            # The FROM word itself is optional too
                            # (``[[FROM] integer-6] [TO integer-7]``), so
                            # ``VARYING IN SIZE 10 TO 30`` has a minimum of
                            # 10: the integer right before TO.
                            to_idx = upper.index("TO")
                            if to_idx > 0:
                                try:
                                    low = int(tokens[to_idx - 1])
                                except (TypeError, ValueError):
                                    low = None
                    depending = None
                    if "DEPENDING" in upper:
                        # data-name follows DEPENDING [ON]
                        idx = upper.index("DEPENDING")
                        rest = [tok for tok in tokens[idx + 1 :] if tok.upper() != "ON"]
                        depending = rest[0] if rest else None
                    clauses["record"] = {
                        "varying": True,
                        "min": low,
                        "max": high,
                        "depending_on": depending,
                    }
                else:
                    nums = _ints(tokens)
                    clauses["record"] = {
                        "varying": False,
                        "min": nums[0] if len(nums) > 1 else None,
                        "max": nums[-1] if nums else None,
                    }

            elif key == "LABEL":
                if "OMITTED" in upper:
                    clauses["label_records"] = "OMITTED"
                elif "STANDARD" in upper:
                    clauses["label_records"] = "STANDARD"
                elif tokens:
                    clauses["label_records"] = " ".join(tokens)

            elif key == "RECORDING":
                mode = [tok for tok in tokens if tok.upper() not in ("MODE", "IS")]
                if mode:
                    clauses["recording_mode"] = mode[0]

            elif key == "CODE-SET":
                names = [tok for tok in tokens if tok.upper() != "IS"]
                if names:
                    clauses["code_set"] = names[0]

            elif key == "DATA":
                names = [
                    tok
                    for tok in tokens
                    if tok.upper() not in ("RECORD", "RECORDS", "IS", "ARE")
                ]
                if names:
                    clauses["data_records"] = names

            elif key in ("REPORT", "REPORTS"):
                names = [tok for tok in tokens if tok.upper() not in ("IS", "ARE", ",")]
                if names:
                    clauses.setdefault("report_names", []).extend(names)

            elif key == "LINAGE":
                clauses["linage"] = " ".join(tokens)

            elif key == "VALUE":
                clauses["value_of"] = " ".join(tokens)

        return clauses
