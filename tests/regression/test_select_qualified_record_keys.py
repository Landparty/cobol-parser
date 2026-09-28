"""``SELECT ... RECORD KEY IS K6 OF R6`` keeps its qualifier.

``RECORD KEY IS K6 OF R6`` / ``ALTERNATE RECORD KEY IS A6 IN R6 WITH
DUPLICATES`` kept only the key name and warned "Unparsed token" for the
qualifier -- and for ``WITH DUPLICATES`` after it, which was lost. The bare
name stays in ``record_key`` / ``key``; the qualifiers are kept alongside
(``record_key_qualifiers`` / ``qualifiers``), innermost first.
"""

from __future__ import annotations

from cobolparser import parse_cobol

SELECT_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. QKEY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F6 ASSIGN TO DD6
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS K6 OF R6
               ALTERNATE RECORD KEY IS A6 IN R6 WITH DUPLICATES
               ALTERNATE RECORD KEY IS B6
               FILE STATUS IS FS6.
       DATA DIVISION.
       FILE SECTION.
       FD F6.
       01 R6.
          05 K6 PIC X(5).
          05 A6 PIC X(5).
          05 B6 PIC X(5).
       WORKING-STORAGE SECTION.
       01 FS6 PIC XX.
       PROCEDURE DIVISION.
           STOP RUN.
"""


def test_select_record_keys_keep_their_qualifiers():
    result = parse_cobol(SELECT_PROGRAM)
    assert result.success, result.errors
    assert not result.warnings
    (select,) = result.ast.find_all_by_type("SelectStatement")
    assert select.record_key == "K6"
    assert select.record_key_qualifiers == ["R6"]
    assert select.alternate_keys == [
        {
            "key": "A6",
            "duplicates_allowed": True,
            "password": None,
            "qualifiers": ["R6"],
        },
        {"key": "B6", "duplicates_allowed": False, "password": None, "qualifiers": []},
    ]
    data = select.to_dict()
    assert data["record_key_qualifiers"] == ["R6"]
    assert select.file_status == "FS6"
