"""Regression tests for issue #529: the LE callable service list.

``IBM_LE_CALLABLE_SERVICES`` missed frequently used services from the z/OS LE
Programming Reference (CEERAN0, CEEDCOD, CEE3INF, ...), which language-env
reported ``is_known_service: false``, and carried names that are not LE
services at all (CEEDUMP for CEE3DMP, CEEABND for CEE3ABD, CEETIME, ...), which
it reported known. ``_UNCATALOGUED_LE_SERVICE_INFO`` also described CEETREC as
"Remove a condition handler" -- that is CEEHDLU.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis import LanguageEnvironmentAnalyzer
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol

# The checked-in reference list: every service the dialect recognises, by the
# category the analyzer reports. A change to the dialect's list must be made
# here too, deliberately. (The CEESxyyy math services are not listed.)
# fmt: off
_REFERENCE: dict[str, set[str]] = {
    "datetime": {
        "CEECBLDY", "CEEDATE", "CEEDATM", "CEEDAYS", "CEEDYWK", "CEEFMDA",
        "CEEFMDT", "CEEFMTM", "CEEGMT", "CEEGMTO", "CEEISEC", "CEELOCT",
        "CEEQCEN", "CEESCEN", "CEESECI", "CEESECS", "CEEUTC",
    },
    "storage": {"CEECRHP", "CEECZST", "CEEDSHP", "CEEFRST", "CEEGTST", "CEE3RPH"},
    "condition": {
        "CEEHDLR", "CEEHDLU", "CEESGL", "CEEMRCE", "CEEMRCR", "CEE3SRP",
        "CEEITOK", "CEEGQDT", "CEENCOD", "CEEDCOD", "CEE3CIB", "CEE3CNC",
        "CEE3GRN", "CEE3GRO", "CEE3SPM", "CEE3DMP", "CEE3ABD", "CEE3AB2",
        "CEETREC",
    },
    "runtime": {
        "CEEMGET", "CEEMOUT", "CEEMSG", "CEE3PRM", "CEE3PR2", "CEE3GRC",
        "CEE3SRC", "CEE3DLY", "CEEDLYM", "CEETEST", "CEETERM",
    },
    "environment": {"CEE3INF", "CEE3USR", "CEEENV", "CEEGPID", "CEEGTJS"},
    "locale": {
        "CEE3CTY", "CEE3LNG", "CEE3MCS", "CEE3MDS", "CEE3MTS", "CEEFMON",
        "CEEFTDS", "CEELCNV", "CEEQDTC", "CEEQRYL", "CEESCOL", "CEESETL",
        "CEESTXF",
    },
    "math": {"CEERAN0", "CEESICLR", "CEESISET", "CEESISHF", "CEESITST"},
    "ims": {"CEETDLI"},
}

_NOT_LE_SERVICES = [
    "CEEDUMP", "CEEABND", "CEETIME", "CEEFMTDT", "CEEDTTM", "CEEGMTCO",
    "CEEFMTVF", "CEEFRMST", "CEECREH", "CEEZLNG", "CEEHOOK", "CEENDUC",
    "CEERADR", "CEENVST", "CEEGMEM", "CEEGPIL", "CEEGLS", "CEEBINIT",
    "CEEPCMD", "CEEGLOB", "CEEGSS", "CEESST", "CEESG", "CEESQ",
]
# fmt: on


def test_service_set_matches_the_reference_list():
    expected = {name for names in _REFERENCE.values() for name in names}
    assert IBMEnterpriseCobol.IBM_LE_CALLABLE_SERVICES == expected


def test_categories_match_the_reference_list():
    expected = {
        name: category for category, names in _REFERENCE.items() for name in names
    }
    assert IBMEnterpriseCobol.IBM_LE_SERVICE_CATEGORIES == expected


@pytest.mark.parametrize("name", _NOT_LE_SERVICES)
def test_names_not_in_the_reference_are_not_services(name):
    assert IBMEnterpriseCobol().is_le_callable_service(name) is False
    assert IBMEnterpriseCobol().get_le_service_info(name) is None


def test_ceetrec_is_not_described_as_unregistering_a_handler():
    info = IBMEnterpriseCobol().get_le_service_info("CEETREC")
    assert info is not None
    assert "handler" not in info["description"].lower()


def test_issue_repro_language_env():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LE529.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 SEED PIC S9(9) COMP.
       01 RNUM COMP-2.
       01 FC PIC X(12).
       01 TOK PIC X(12).
       PROCEDURE DIVISION.
           CALL 'CEERAN0' USING SEED RNUM FC
           CALL 'CEEDCOD' USING FC
           CALL 'CEE3INF' USING TOK
           CALL 'CEEDUMP' USING FC
           GOBACK.
"""
    result = parse_cobol(source)
    assert result.errors == []
    calls = LanguageEnvironmentAnalyzer().analyze(result.ast).le_service_calls
    assert [(c.service_name, c.is_known_service, c.category) for c in calls] == [
        ("CEERAN0", True, "math"),
        ("CEEDCOD", True, "condition"),
        ("CEE3INF", True, "environment"),
        ("CEEDUMP", False, "unknown"),
    ]
