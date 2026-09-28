"""Tests for the LE / intrinsic call-signature catalogue.

The catalogue is hand-written knowledge, so the tests here are mostly
*consistency* tests -- the kind that catch a typo in a new entry rather than
re-asserting the entry's own content:

- every catalogued service is a service the dialect recognises, in the same
  category (otherwise `language-env` and a tooltip would disagree about what
  a name even is)
- every parameter names a real data type, so no consumer can be handed a
  dangling ``type_id``
- optional parameters sort last, since a USING list is positional and an
  optional operand in the middle would make "required_count" meaningless
- the coverage gap is reported, not hidden
"""

from __future__ import annotations

import pytest

from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol
from cobolparser.dialects.le_signatures import (
    CATALOG_VERSION,
    INTRINSIC_FUNCTION_SIGNATURES,
    LE_DATA_TYPES,
    LE_SERVICE_SIGNATURES,
    catalog_to_dict,
    intrinsic_signature,
    le_service_signature,
    services_without_signature,
)

_SERVICES = sorted(LE_SERVICE_SIGNATURES)
_FUNCTIONS = sorted(INTRINSIC_FUNCTION_SIGNATURES)


class TestServiceCatalogueConsistency:
    @pytest.mark.parametrize("name", _SERVICES)
    def test_service_is_known_to_the_dialect(self, name: str) -> None:
        assert name in IBMEnterpriseCobol.IBM_LE_CALLABLE_SERVICES

    @pytest.mark.parametrize("name", _SERVICES)
    def test_category_matches_the_dialect(self, name: str) -> None:
        assert (
            IBMEnterpriseCobol.IBM_LE_SERVICE_CATEGORIES[name]
            == LE_SERVICE_SIGNATURES[name].category
        )

    @pytest.mark.parametrize("name", _SERVICES)
    def test_keyed_by_its_own_name(self, name: str) -> None:
        assert LE_SERVICE_SIGNATURES[name].name == name

    @pytest.mark.parametrize("name", _SERVICES)
    def test_every_parameter_names_a_real_type(self, name: str) -> None:
        for param in LE_SERVICE_SIGNATURES[name].parameters:
            assert param.type_id in LE_DATA_TYPES
            assert param.direction in ("input", "output", "input/output")
            assert param.description

    @pytest.mark.parametrize("name", _SERVICES)
    def test_optional_parameters_come_last(self, name: str) -> None:
        optional = [p.optional for p in LE_SERVICE_SIGNATURES[name].parameters]
        assert optional == sorted(optional), (
            f"{name}: a USING list is positional, so an optional operand "
            f"cannot precede a required one"
        )

    @pytest.mark.parametrize("name", _SERVICES)
    def test_has_at_least_one_parameter(self, name: str) -> None:
        assert LE_SERVICE_SIGNATURES[name].parameters

    def test_feedback_code_is_optional_wherever_it_appears(self) -> None:
        # LE lets the caller omit fc, and the catalogue's whole point is to
        # say which operands may be left out.
        for sig in LE_SERVICE_SIGNATURES.values():
            for param in sig.parameters:
                if param.name == "fc":
                    assert param.optional

    def test_omitted_fc_is_explained_where_fc_is_optional(self) -> None:
        for sig in LE_SERVICE_SIGNATURES.values():
            if any(p.name == "fc" and p.optional for p in sig.parameters):
                assert any("omitted" in note for note in sig.notes)


class TestServiceSignatureAPI:
    def test_lookup_is_case_insensitive(self) -> None:
        assert le_service_signature("ceedays") is le_service_signature("CEEDAYS")

    def test_lookup_tolerates_surrounding_space(self) -> None:
        assert le_service_signature("  CEEGMT  ") is not None

    def test_unknown_name_is_none(self) -> None:
        assert le_service_signature("NOTASERVICE") is None

    def test_required_parameters_exclude_the_optional_ones(self) -> None:
        sig = le_service_signature("CEEDAYS")
        assert sig is not None
        assert [p.name for p in sig.required_parameters] == [
            "input_char_date",
            "picture_string",
            "output_Lilian",
        ]

    def test_call_example_names_every_operand(self) -> None:
        sig = le_service_signature("CEEGTST")
        assert sig is not None
        assert sig.call_example() == (
            'CALL "CEEGTST" USING heap_id, size, address, [fc]'
        )

    def test_call_example_leaves_a_wholly_required_service_unbracketed(self) -> None:
        sig = le_service_signature("CEE3ABD")
        assert sig is not None
        assert "[" not in sig.call_example()

    def test_repeating_operand_is_marked_in_the_example(self) -> None:
        sig = le_service_signature("CEETDLI")
        assert sig is not None
        assert sig.call_example().endswith("[ssa...]")

    def test_vstring_parameters_carry_a_declaration_snippet(self) -> None:
        sig = le_service_signature("CEEDAYS")
        assert sig is not None
        picture = next(p for p in sig.parameters if p.name == "picture_string")
        assert "PIC S9(4) COMP" in (picture.data_type.snippet or "")

    def test_to_dict_inlines_the_resolved_type(self) -> None:
        sig = le_service_signature("CEEDYWK")
        assert sig is not None
        first = sig.to_dict()["parameters"][0]
        assert first["type"]["declaration"] == "PIC S9(9) COMP"
        assert first["type"]["byte_length"] == 4


class TestCallExampleConventions:
    """An omissible operand is bracketed the same way in both halves.

    The extension renders `call_example` verbatim, so a service that showed
    `fc` unbracketed would be telling the reader it has to be there --
    contradicting the very column of the table that says it may be omitted.
    """

    @pytest.mark.parametrize("name", _SERVICES)
    def test_service_brackets_exactly_its_optional_operands(self, name: str) -> None:
        sig = LE_SERVICE_SIGNATURES[name]
        expected = sum(1 for p in sig.parameters if p.optional)
        assert sig.call_example().count("[") == expected

    @pytest.mark.parametrize("name", _FUNCTIONS)
    def test_function_brackets_exactly_its_optional_arguments(self, name: str) -> None:
        sig = INTRINSIC_FUNCTION_SIGNATURES[name]
        expected = sum(1 for a in sig.arguments if a.optional)
        assert sig.call_example().count("[") == expected


class TestIntrinsicSignatures:
    @pytest.mark.parametrize("name", _FUNCTIONS)
    def test_function_is_known_to_the_dialect(self, name: str) -> None:
        assert name in IBMEnterpriseCobol.IBM_INTRINSIC_FUNCTIONS

    def test_every_ibm_intrinsic_has_a_signature(self) -> None:
        # Unlike the services, this catalogue is complete -- a new intrinsic
        # added to the dialect without a signature would silently lose its
        # tooltip.
        missing = sorted(
            IBMEnterpriseCobol.IBM_INTRINSIC_FUNCTIONS
            - set(INTRINSIC_FUNCTION_SIGNATURES)
        )
        assert missing == []

    @pytest.mark.parametrize("name", _FUNCTIONS)
    def test_optional_arguments_come_last(self, name: str) -> None:
        optional = [a.optional for a in INTRINSIC_FUNCTION_SIGNATURES[name].arguments]
        assert optional == sorted(optional)

    @pytest.mark.parametrize("name", _FUNCTIONS)
    def test_has_a_return_category(self, name: str) -> None:
        assert INTRINSIC_FUNCTION_SIGNATURES[name].returns

    def test_lookup_is_case_insensitive(self) -> None:
        assert intrinsic_signature("upper-case") is intrinsic_signature("UPPER-CASE")

    def test_no_argument_function_has_no_parentheses(self) -> None:
        sig = intrinsic_signature("CURRENT-DATE")
        assert sig is not None
        assert sig.call_example() == "FUNCTION CURRENT-DATE"

    def test_optional_argument_is_bracketed(self) -> None:
        sig = intrinsic_signature("YEAR-TO-YYYY")
        assert sig is not None
        assert sig.call_example() == "FUNCTION YEAR-TO-YYYY(argument-1, [argument-2])"

    def test_repeating_argument_is_marked(self) -> None:
        sig = intrinsic_signature("MAX")
        assert sig is not None
        assert sig.call_example() == "FUNCTION MAX(argument-1...)"

    def test_required_arguments_exclude_the_optional_ones(self) -> None:
        sig = intrinsic_signature("NUMVAL-C")
        assert sig is not None
        assert len(sig.required_arguments) == 1


class TestCoverageIsReported:
    def test_uncatalogued_services_are_listed(self) -> None:
        names = {entry["name"] for entry in services_without_signature()}
        # A service the dialect recognises but this module cannot describe.
        assert "CEETERM" in names
        # ... and one it can, which must NOT appear here.
        assert "CEEDAYS" not in names

    def test_every_uncatalogued_service_carries_a_category(self) -> None:
        for entry in services_without_signature():
            assert entry["category"]

    def test_catalogued_and_uncatalogued_partition_the_dialect(self) -> None:
        covered = set(LE_SERVICE_SIGNATURES)
        uncovered = {entry["name"] for entry in services_without_signature()}
        assert covered | uncovered == set(IBMEnterpriseCobol.IBM_LE_CALLABLE_SERVICES)
        assert covered & uncovered == set()


class TestCatalogDict:
    def test_shape(self) -> None:
        catalog = catalog_to_dict()
        assert catalog["catalog_version"] == CATALOG_VERSION
        assert catalog["reference"]
        assert {"services", "functions", "services_without_signature"} <= set(catalog)

    def test_sorted_by_name(self) -> None:
        catalog = catalog_to_dict()
        for key in ("services", "functions"):
            names = [entry["name"] for entry in catalog[key]]
            assert names == sorted(names)

    def test_entries_are_tagged_with_their_kind(self) -> None:
        catalog = catalog_to_dict()
        assert {e["kind"] for e in catalog["services"]} == {"service"}
        assert {e["kind"] for e in catalog["functions"]} == {"function"}

    def test_json_serialisable(self) -> None:
        import json

        json.dumps(catalog_to_dict())


class TestDialectServiceInfoStaysInSync:
    """`get_le_service_info` is derived from the catalogue -- prove it."""

    def test_derived_entry_matches_the_signature(self) -> None:
        dialect = IBMEnterpriseCobol()
        info = dialect.get_le_service_info("CEEDAYS")
        sig = le_service_signature("CEEDAYS")
        assert info is not None and sig is not None
        assert info["description"] == sig.summary
        assert info["parameters"] == [p.name for p in sig.parameters]

    def test_uncatalogued_service_still_has_info(self) -> None:
        assert IBMEnterpriseCobol().get_le_service_info("CEETERM") is not None


class TestEnterpriseSixIntrinsicSignatures:
    """The post-COBOL-85 intrinsics carry signatures with IBM's arity."""

    @pytest.mark.parametrize(
        "name, required, total",
        [
            ("TRIM", 1, 2),
            ("FORMATTED-DATETIME", 3, 4),
            ("FORMATTED-TIME", 2, 3),
            ("FORMATTED-DATE", 2, 2),
            ("NUMVAL-F", 1, 1),
            ("TEST-NUMVAL-C", 1, 2),
            ("DISPLAY-OF", 1, 2),
            ("USUBSTR", 3, 3),
            ("PI", 0, 0),
            ("UUID4", 0, 0),
        ],
    )
    def test_arity(self, name: str, required: int, total: int) -> None:
        sig = intrinsic_signature(name)
        assert sig is not None
        assert len(sig.required_arguments) == required
        assert len(sig.arguments) == total
        assert IBMEnterpriseCobol().is_intrinsic_function(name)
