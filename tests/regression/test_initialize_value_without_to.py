"""``INITIALIZE x {ALL | category} VALUE``: TO is optional.

The TO-less form used to drop the VALUE phrase with an "unparsed tokens"
warning, so the AST lost the request to initialize to VALUE clauses
(open-source corpus finding, an IBM sample).
"""

import pytest

from cobolparser import parse_cobol

SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INIT2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-G1.
          05 WS-X PIC X(4) VALUE 'AB'.
          05 WS-N PIC 9(4) VALUE 7.
       PROCEDURE DIVISION.
           INITIALIZE WS-G1 {phrase}
           DISPLAY WS-X
           STOP RUN.
"""


@pytest.mark.parametrize(
    ("phrase", "category", "default"),
    [
        ("ALL VALUE", "ALL", False),
        ("ALL TO VALUE", "ALL", False),
        ("NUMERIC VALUE", "NUMERIC", False),
        ("ALPHANUMERIC VALUE THEN TO DEFAULT", "ALPHANUMERIC", True),
    ],
)
def test_value_phrase_with_or_without_to(phrase, category, default):
    result = parse_cobol(SRC.format(phrase=phrase))
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    (init,) = result.ast.find_all_by_type("InitializeStatement")
    assert init.to_value_category == category
    assert init.to_default is default
    assert len(result.ast.find_all_by_type("DisplayStatement")) == 1
