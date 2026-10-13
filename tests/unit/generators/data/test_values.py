"""Unit tests for ValueFactory (cobolparser.generators.data.values).

test_copybook_data_generator.py already covers value generation end-to-end
through a real copybook; this file targets ValueFactory's semantic-text
heuristics and numeric-formatting edge cases directly, several of which
(email/phone/state/zip/city/date/time-of-day, COMP-1/2 floats, the
sign/ceiling clamping in _format_number) had no dedicated coverage.
"""

from __future__ import annotations

import random
import re
from decimal import Decimal

from cobolparser.generators.data.layout import FieldCategory, FieldSpec
from cobolparser.generators.data.options import DataGeneratorOptions
from cobolparser.generators.data.values import ValueFactory


def _spec(
    name: str,
    *,
    category: FieldCategory = FieldCategory.ALPHANUMERIC,
    size: int = 10,
    integer_digits: int = 0,
    decimal_digits: int = 0,
    is_signed: bool = False,
    value_clause: str | None = None,
) -> FieldSpec:
    return FieldSpec(
        name=name,
        path=(name,),
        column=name,
        level=5,
        picture=None,
        usage="DISPLAY",
        category=category,
        size=size,
        integer_digits=integer_digits,
        decimal_digits=decimal_digits,
        is_signed=is_signed,
        value_clause=value_clause,
    )


def _factory(seed: int = 1, **opts) -> ValueFactory:
    return ValueFactory(random.Random(seed), DataGeneratorOptions(**opts))


class TestSemanticTextEmailPhone:
    def test_email_field_generates_addr_shaped_value(self):
        factory = _factory()
        spec = _spec("WS-EMAIL-ADDRESS", size=40)
        value = factory.value_for(spec, 0)
        assert re.match(r"^[a-z]+\.[a-z]+@[a-z]+\.[a-z]+$", value), value

    def test_phone_field_generates_ten_digit_number(self):
        factory = _factory()
        spec = _spec("WS-PHONE-NUMBER", size=10)
        value = factory.value_for(spec, 0)
        assert re.match(r"^\d{10}$", value), value


class TestSemanticTextGeography:
    def test_state_field_generates_a_two_letter_state(self):
        factory = _factory()
        spec = _spec("WS-STATE", size=2)
        value = factory.value_for(spec, 0)
        assert re.match(r"^[A-Z]{2}$", value), value

    def test_zip_field_generates_five_digit_zip(self):
        factory = _factory()
        spec = _spec("WS-ZIP-CODE", size=5)
        value = factory.value_for(spec, 0)
        assert re.match(r"^\d{5}$", value), value

    def test_city_field_generates_a_known_city_name(self):
        factory = _factory()
        spec = _spec("WS-CITY", size=20)
        value = factory.value_for(spec, 0)
        assert value.isalpha() or " " in value

    def test_street_field_generates_a_house_number_and_street_name(self):
        factory = _factory()
        spec = _spec("WS-STREET-ADDRESS", size=30)
        value = factory.value_for(spec, 0)
        assert re.match(r"^\d+ .+$", value), value


class TestSemanticTextNames:
    def test_first_name_field(self):
        factory = _factory()
        spec = _spec("WS-FIRST-NAME", size=15)
        value = factory.value_for(spec, 0)
        assert value.isalpha()

    def test_last_name_field(self):
        factory = _factory()
        spec = _spec("WS-LAST-NAME", size=15)
        value = factory.value_for(spec, 0)
        assert value.isalpha()

    def test_bare_name_field_generates_first_and_last(self):
        factory = _factory()
        spec = _spec("WS-CUSTOMER-NAME", size=30)
        value = factory.value_for(spec, 0)
        parts = value.split(" ")
        assert len(parts) == 2
        assert all(p.isalpha() for p in parts)


class TestSemanticTextMisc:
    def test_date_token_text_field_generates_iso_shaped_date(self):
        factory = _factory()
        spec = _spec("WS-BIRTH-DATE", size=10)
        value = factory.value_for(spec, 0)
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", value), value

    def test_description_field_generates_three_words(self):
        factory = _factory()
        spec = _spec("WS-DESCRIPTION", size=60)
        value = factory.value_for(spec, 0)
        assert len(value.split(" ")) == 3

    def test_code_field_generates_uppercase_letters_bounded_by_size(self):
        factory = _factory()
        spec = _spec("WS-STATUS-CODE", size=3)
        value = factory.value_for(spec, 0)
        assert re.match(r"^[A-Z]{1,3}$", value), value
        assert len(value) <= 3

    def test_flag_field_generates_y_or_n(self):
        factory = _factory()
        spec = _spec("WS-ACTIVE-FLAG", size=1)
        value = factory.value_for(spec, 0)
        assert value in ("Y", "N")

    def test_semantic_hints_disabled_falls_back_to_random_text(self):
        factory = _factory(semantic_hints=False)
        spec = _spec("WS-EMAIL-ADDRESS", size=40)
        value = factory.value_for(spec, 0)
        assert "@" not in value


class TestNumericSemanticHints:
    def test_id_token_field_generates_a_number_fitting_the_declared_width(self):
        factory = _factory()
        spec = _spec(
            "WS-CUSTOMER-ID", category=FieldCategory.NUMERIC, size=5, integer_digits=5
        )
        value = factory.value_for(spec, 0)
        assert value.isdigit() and len(value) <= 5

    def test_money_token_field_generates_within_ceiling(self):
        factory = _factory()
        spec = _spec(
            "WS-TOTAL-AMOUNT",
            category=FieldCategory.NUMERIC,
            size=8,
            integer_digits=6,
            decimal_digits=2,
        )
        value = factory.value_for(spec, 0)
        assert Decimal(value) >= 0

    def test_count_token_field_generates_within_bounded_ceiling(self):
        factory = _factory()
        spec = _spec(
            "WS-ITEM-COUNT", category=FieldCategory.NUMERIC, size=3, integer_digits=3
        )
        value = factory.value_for(spec, 0)
        assert 0 <= int(value) <= 999

    def test_rate_token_field_generates_a_percentage_like_value(self):
        factory = _factory()
        spec = _spec(
            "WS-INTEREST-RATE",
            category=FieldCategory.NUMERIC,
            size=5,
            integer_digits=3,
            decimal_digits=2,
        )
        value = factory.value_for(spec, 0)
        assert 0 <= Decimal(value) <= 100

    def test_date_token_numeric_field_generates_8_digit_date(self):
        factory = _factory()
        spec = _spec(
            "WS-ORDER-DATE", category=FieldCategory.NUMERIC, size=8, integer_digits=8
        )
        value = factory.value_for(spec, 0)
        assert re.match(r"^\d{8}$", value), value

    def test_date_token_numeric_field_too_narrow_falls_back_to_random(self):
        # _date_digits returns None below 6 digits -- confirms the numeric
        # path falls through to a plain random number instead of crashing.
        factory = _factory()
        spec = _spec(
            "WS-DATE-CD", category=FieldCategory.NUMERIC, size=3, integer_digits=3
        )
        value = factory.value_for(spec, 0)
        assert value.lstrip("-").isdigit()

    def test_time_token_numeric_field_generates_6_digit_time(self):
        factory = _factory()
        spec = _spec(
            "WS-EVENT-TIME", category=FieldCategory.NUMERIC, size=6, integer_digits=6
        )
        value = factory.value_for(spec, 0)
        # Rendered like every other number (no leading zeros), so the
        # decoder reads the same cell back; the stored digits are HHMMSS.
        assert re.match(r"^\d{1,6}$", value), value
        value = value.zfill(6)
        hh, mm, ss = int(value[:2]), int(value[2:4]), int(value[4:6])
        assert 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59

    def test_time_token_numeric_field_four_digits(self):
        factory = _factory()
        spec = _spec(
            "WS-EVENT-TIME", category=FieldCategory.NUMERIC, size=4, integer_digits=4
        )
        value = factory.value_for(spec, 0)
        assert re.match(r"^\d{1,4}$", value), value
        hh, mm = int(value.zfill(4)[:2]), int(value.zfill(4)[2:])
        assert 0 <= hh <= 23 and 0 <= mm <= 59

    def test_time_token_numeric_field_too_narrow_falls_back_to_random(self):
        factory = _factory()
        spec = _spec(
            "WS-EVENT-TIME", category=FieldCategory.NUMERIC, size=2, integer_digits=2
        )
        value = factory.value_for(spec, 0)
        assert value.lstrip("-").isdigit()


class TestFloatValues:
    def test_comp_1_field_generates_a_decimal_string(self):
        factory = _factory()
        spec = _spec("WS-FLOAT-VAL", category=FieldCategory.FLOAT, size=0)
        value = factory.value_for(spec, 0)
        parsed = float(value)
        assert -10_000 <= parsed <= 10_000


class TestFormatNumberSignAndClamping:
    def test_unsigned_field_never_produces_a_negative(self):
        factory = _factory(seed=42)
        spec = _spec(
            "WS-UNSIGNED", category=FieldCategory.NUMERIC, size=3, integer_digits=3
        )
        for row in range(20):
            value = factory.value_for(spec, row)
            assert not value.startswith("-")

    def test_signed_field_with_declared_negative_value_clause_stays_negative(self):
        factory = _factory()
        spec = _spec(
            "WS-BALANCE",
            category=FieldCategory.NUMERIC,
            size=5,
            integer_digits=5,
            is_signed=True,
            value_clause="-42",
        )
        value = factory.value_for(spec, 0)
        assert value == "-42"

    def test_magnitude_is_clamped_to_the_declared_digit_ceiling(self):
        factory = _factory()
        spec = _spec(
            "WS-SMALL",
            category=FieldCategory.NUMERIC,
            size=2,
            integer_digits=2,
            value_clause="99999",
        )
        value = factory.value_for(spec, 0)
        assert value == "99"

    def test_decimal_only_field_clamps_below_one(self):
        factory = _factory()
        spec = _spec(
            "WS-FRACTION",
            category=FieldCategory.NUMERIC,
            size=2,
            integer_digits=0,
            decimal_digits=2,
            value_clause="5",
        )
        value = factory.value_for(spec, 0)
        assert Decimal(value) < 1

    def test_zero_digit_zero_decimal_field_clamps_to_zero(self):
        factory = _factory()
        spec = _spec(
            "WS-ZERO-WIDTH",
            category=FieldCategory.NUMERIC,
            size=0,
            integer_digits=0,
            decimal_digits=0,
            value_clause="7",
        )
        value = factory.value_for(spec, 0)
        assert value == "0"


class TestBlankRateAndUniqueFields:
    def test_blank_rate_one_always_returns_empty_string(self):
        factory = _factory(blank_rate=1.0)
        spec = _spec("WS-ANY", size=5)
        assert factory.value_for(spec, 0) == ""

    def test_unique_field_retries_produce_distinct_values(self):
        factory = _factory(unique_fields=("WS-CODE",))
        spec = _spec(
            "WS-CODE", category=FieldCategory.NUMERIC, size=1, integer_digits=1
        )
        values = [factory.value_for(spec, row) for row in range(5)]
        assert len(set(values)) == len(values)

    def test_unique_field_falls_back_to_sequential_when_domain_exhausted(self):
        # PIC 9 has only ten possible values -- after they're exhausted the
        # sequential fallback still returns *something* rather than hanging.
        factory = _factory(unique_fields=("WS-DIGIT",))
        spec = _spec(
            "WS-DIGIT", category=FieldCategory.NUMERIC, size=1, integer_digits=1
        )
        values = [factory.value_for(spec, row) for row in range(15)]
        assert len(values) == 15


class TestRender:
    def test_render_fits_a_solved_witness_through_the_picture(self):
        factory = _factory()
        spec = _spec("WS-QTY", category=FieldCategory.NUMERIC, size=3, integer_digits=3)
        assert factory.render(spec, "42") == "042" or factory.render(spec, "42") == "42"

    def test_render_never_randomly_negates(self):
        factory = _factory(seed=7)
        spec = _spec(
            "WS-QTY",
            category=FieldCategory.NUMERIC,
            size=3,
            integer_digits=3,
            is_signed=True,
        )
        for _ in range(20):
            assert not factory.render(spec, "5").startswith("-")


class TestWideNumericPrecision:
    """Issue #285: wide numeric fields keep every low-order digit.

    ``whole + random()`` used to turn the value into a float64, so a
    ``PIC 9(18)`` value lost everything past ~15 significant digits and
    most rows ended in ``00``.
    """

    def _values(self, spec: FieldSpec, rows: int = 200) -> list[str]:
        factory = _factory(seed=1)
        return [factory.value_for(spec, row) for row in range(rows)]

    def test_pic_9_18_low_digits_are_exercised(self):
        spec = _spec("A", category=FieldCategory.NUMERIC, size=18, integer_digits=18)
        values = self._values(spec)
        trailing_00 = sum(v.endswith("00") for v in values)
        # Uniform low digits end in "00" about 1% of the time.
        assert trailing_00 < 10, trailing_00
        assert len({v[-1] for v in values}) == 10
        for v in values:
            assert int(v) <= 10**18 - 1

    def test_signed_comp_style_18_digits_round_trip_exactly(self):
        spec = _spec(
            "B",
            category=FieldCategory.NUMERIC,
            size=18,
            integer_digits=18,
            is_signed=True,
        )
        for v in self._values(spec):
            assert str(int(v)) == v
            assert len(v.lstrip("-")) <= 18

    def test_wide_integer_part_keeps_its_decimals(self):
        # S9(13)V9(5): 18 digits in all, past what a float64 holds.
        spec = _spec(
            "C",
            category=FieldCategory.NUMERIC,
            size=18,
            integer_digits=13,
            decimal_digits=5,
            is_signed=True,
        )
        values = self._values(spec)
        for v in values:
            assert re.fullmatch(r"-?\d{1,13}\.\d{5}", v), v
        assert len({v[-1] for v in values}) == 10
        assert sum(v.endswith("0") for v in values) < 50

    def test_fraction_wider_than_a_float_is_fully_random(self):
        # V9(18): a single random() draw cannot fill 18 decimal places.
        spec = _spec(
            "D",
            category=FieldCategory.NUMERIC,
            size=19,
            integer_digits=1,
            decimal_digits=18,
        )
        values = self._values(spec)
        for v in values:
            assert re.fullmatch(r"\d\.\d{18}", v), v
        assert sum(v.endswith("00") for v in values) < 10

    def test_widest_31_digit_field_keeps_every_digit(self):
        spec = _spec(
            "E",
            category=FieldCategory.NUMERIC,
            size=31,
            integer_digits=18,
            decimal_digits=13,
        )
        values = self._values(spec, rows=50)
        for v in values:
            assert re.fullmatch(r"\d{1,18}\.\d{13}", v), v
        assert len({v[-1] for v in values}) > 5

    def test_same_seed_same_output(self):
        spec = _spec("F", category=FieldCategory.NUMERIC, size=18, integer_digits=18)
        assert self._values(spec, 20) == self._values(spec, 20)

    def test_narrow_fields_are_unchanged(self):
        # Pinned from the float path's output before the fix: a field a
        # float64 already held exactly keeps its seeded values.
        cases = {
            (7, 2, True): [
                "2254257.57",
                "1058756.26",
                "7541208.47",
                "-3522457.09",
                "6539906.43",
                "35333.70",
            ],
            (12, 0, False): [
                "623347347957",
                "884107995871",
                "71999863748",
                "129944532028",
                "835351532923",
                "517326624931",
            ],
            (5, 4, False): [
                "17611.5692",
                "8271.2551",
                "64937.7610",
                "61898.6516",
                "27519.0939",
                "3715.8933",
            ],
        }
        for (whole, decimals, signed), expected in cases.items():
            spec = _spec(
                "G",
                category=FieldCategory.NUMERIC,
                size=whole + decimals,
                integer_digits=whole,
                decimal_digits=decimals,
                is_signed=signed,
            )
            assert self._values(spec, rows=6) == expected
