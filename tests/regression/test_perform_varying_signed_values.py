"""Regression coverage for PERFORM VARYING/AFTER dropping the whole clause
on a sign-prefixed FROM/BY value.

Found via a real mainframe corpus retry: a countdown loop -- ``PERFORM
SUB-PARA VARYING WS-I FROM 5 BY -1 UNTIL WS-I < 1`` -- surfaced as
"PERFORM VARYING clause: FROM/BY/UNTIL not fully recognized" plus an
"Unparsed tokens" warning. A signed numeric literal lexes as two tokens
(MINUS/PLUS then the number), and the FROM/BY value reads in
``perform_parser`` each consumed a single token: ``BY -1`` captured only
``"-"`` as the BY value, the leftover ``1`` made the UNTIL lookahead fail,
and the entire VARYING clause was dropped from the AST. Fixed by a shared
``_consume_from_by_value`` helper that composes MINUS/PLUS + numeric into
one value (mirroring ``_consume_arithmetic_operand``'s handling of the
same lexing split), wired into all four FROM/BY value reads (the VARYING
header and every AFTER dimension).
"""

from cobolparser import parse_cobol


def _pad80(seq: str, text: str, stamp: str = "00110000") -> str:
    line = seq.ljust(6)[:6] + " " + text
    return line.ljust(72)[:72] + stamp


def _parse(proc_lines: list[str]):
    hdr = [
        ("010100", "IDENTIFICATION DIVISION."),
        ("010200", "PROGRAM-ID. PVTEST."),
        ("010300", "DATA DIVISION."),
        ("010400", "WORKING-STORAGE SECTION."),
        ("010500", "01  WS-I  PIC S9(3)."),
        ("010600", "01  WS-J  PIC S9(3)."),
        ("010700", "PROCEDURE DIVISION."),
        ("010800", "MAIN-PARA."),
    ]
    ftr = [
        ("030100", "    STOP RUN."),
        ("030200", "SUB-PARA."),
        ("030300", "    DISPLAY WS-I."),
    ]
    lines = [_pad80(s, t) for s, t in hdr] + proc_lines + [_pad80(s, t) for s, t in ftr]
    result = parse_cobol("\n".join(lines) + "\n", filename="pvtest.cbl")
    assert result.success, result.errors
    assert result.warnings == [], result.warnings
    return result


def _the_perform(result):
    performs = result.ast.find_all_by_type("PerformStatement")
    assert len(performs) == 1
    return performs[0]


class TestSignedVaryingValues:
    def test_countdown_by_negative_one(self):
        result = _parse(
            [
                _pad80(
                    "020100",
                    "    PERFORM SUB-PARA VARYING WS-I FROM 5 BY -1 UNTIL WS-I < 1.",
                )
            ]
        )
        p = _the_perform(result)
        d = p.to_dict()
        assert d["varying_clause"] == {
            "variable": "WS-I",
            "from_value": "5",
            "by_value": "-1",
        }
        assert d["until_condition"] is not None

    def test_negative_from_value(self):
        result = _parse(
            [
                _pad80(
                    "020100",
                    "    PERFORM SUB-PARA VARYING WS-I FROM -5 BY 1 UNTIL WS-I > 0.",
                )
            ]
        )
        d = _the_perform(result).to_dict()
        assert d["varying_clause"]["from_value"] == "-5"
        assert d["varying_clause"]["by_value"] == "1"

    def test_signed_values_in_after_dimension(self):
        result = _parse(
            [
                _pad80("020100", "    PERFORM SUB-PARA"),
                _pad80("020200", "        VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3"),
                _pad80("020300", "        AFTER WS-J FROM 3 BY -1 UNTIL WS-J < 1."),
            ]
        )
        d = _the_perform(result).to_dict()
        assert d["varying_clause"]["by_value"] == "1"
        assert len(d["after_clauses"]) == 1
        assert d["after_clauses"][0]["from_value"] == "3"
        assert d["after_clauses"][0]["by_value"] == "-1"

    def test_plus_prefixed_by_value(self):
        result = _parse(
            [
                _pad80(
                    "020100",
                    "    PERFORM SUB-PARA VARYING WS-I FROM 1 BY +2 UNTIL WS-I > 9.",
                )
            ]
        )
        d = _the_perform(result).to_dict()
        assert d["varying_clause"]["by_value"] == "+2"


class TestSignSplitAcrossLines:
    """A `/code-review` pass caught the single-offset ``peek(1)`` missing a
    sign and its digits straddling a 72-column line break (``BY -`` at end
    of line, ``1`` on the next) -- the shared ``consume_signed_numeric``
    now looks past noise tokens non-destructively before composing."""

    def test_by_sign_and_digits_on_different_lines(self):
        result = _parse(
            [
                _pad80("020100", "    PERFORM SUB-PARA VARYING WS-I FROM 5 BY -"),
                _pad80("020200", "        1 UNTIL WS-I < 1."),
            ]
        )
        d = _the_perform(result).to_dict()
        assert d["varying_clause"]["by_value"] == "-1"


class TestSubscriptedFromByValues:
    """A qualified/subscripted FROM/BY value (``FROM WS-TAB-VAL(I)``) used
    to strand its ``( I )`` tokens in the stream, breaking the UNTIL
    lookahead exactly the way a stranded signed digit did -- folded in via
    the shared ``consume_optional_qualifiers`` now."""

    def test_from_subscripted_data_name(self):
        result = _parse(
            [
                _pad80("015000", "    PERFORM SUB-PARA"),
                _pad80("015100", "        VARYING WS-I FROM WS-J BY 1 UNTIL WS-I > 3."),
            ]
        )
        d = _the_perform(result).to_dict()
        assert d["varying_clause"]["from_value"] == "WS-J"


class TestSetSignedValues:
    """The identical MINUS/PLUS + digits lexing split, in SET's value reads
    (``SET IDX DOWN BY -1`` is the canonical index-decrement idiom) --
    caught by the same review pass and fixed through the same shared
    ``consume_signed_numeric`` helper."""

    def _parse_set(self, stmt_line):
        hdr = [
            ("010100", "IDENTIFICATION DIVISION."),
            ("010200", "PROGRAM-ID. SETTEST."),
            ("010300", "DATA DIVISION."),
            ("010400", "WORKING-STORAGE SECTION."),
            ("010500", "01  WS-I  PIC S9(3)."),
            ("010600", "PROCEDURE DIVISION."),
            ("010700", "MAIN-PARA."),
        ]
        ftr = [("030100", "    STOP RUN.")]
        lines = (
            [_pad80(s, t) for s, t in hdr]
            + [_pad80("020100", stmt_line)]
            + [_pad80(s, t) for s, t in ftr]
        )
        result = parse_cobol("\n".join(lines) + "\n", filename="settest.cbl")
        assert result.success, result.errors
        assert result.warnings == [], result.warnings
        sets = result.ast.find_all_by_type("SetStatement")
        assert len(sets) == 1
        return sets[0].to_dict()

    def test_set_down_by_negative_one(self):
        d = self._parse_set("    SET WS-I DOWN BY -1.")
        assert d["set_type"] == "DOWN_BY"
        assert d["value"] == "-1"

    def test_set_up_by_plus_two(self):
        d = self._parse_set("    SET WS-I UP BY +2.")
        assert d["set_type"] == "UP_BY"
        assert d["value"] == "+2"

    def test_set_to_negative_literal(self):
        d = self._parse_set("    SET WS-I TO -1.")
        assert d["value"] == "-1"
