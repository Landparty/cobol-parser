"""COBOL word lists shared across the package: one home, so they agree.

Before this module the figurative constants were spelled out again in about
two dozen modules (lexer, parsers, layout, a dozen analyzers, generators),
and the copies drifted: some forgot ``NULL`` / ``NULLS``, which the lexer
added later, and a reader could not tell a deliberate subset from a stale
copy. A module that needs a deliberate subset or an extra word builds it
from these sets, so the difference is visible where it is made.

Layer 1 (a leaf): imports nothing from the package.
"""

from __future__ import annotations

from types import MappingProxyType

#: Every spelling of each figurative constant, mapped to its singular form.
#: ``ALL`` is not in it: ``ALL literal`` is a prefix, not a constant on its
#: own (see :data:`FIGURATIVE_CONSTANTS_WITH_ALL`).
FIGURATIVE_CANONICAL = MappingProxyType(
    {
        "ZERO": "ZERO",
        "ZEROS": "ZERO",
        "ZEROES": "ZERO",
        "SPACE": "SPACE",
        "SPACES": "SPACE",
        "HIGH-VALUE": "HIGH-VALUE",
        "HIGH-VALUES": "HIGH-VALUE",
        "LOW-VALUE": "LOW-VALUE",
        "LOW-VALUES": "LOW-VALUE",
        "QUOTE": "QUOTE",
        "QUOTES": "QUOTE",
        # NULL / NULLS: the VALUE of a USAGE POINTER item and the operand of
        # SET ptr TO NULL.
        "NULL": "NULL",
        "NULLS": "NULL",
    }
)

#: Every figurative-constant word, singular and plural.
FIGURATIVE_CONSTANTS: frozenset[str] = frozenset(FIGURATIVE_CANONICAL)

#: The figurative constants plus ``ALL``, for code that classifies a token
#: before it knows whether ``ALL`` starts an ``ALL literal``.
FIGURATIVE_CONSTANTS_WITH_ALL: frozenset[str] = FIGURATIVE_CONSTANTS | {"ALL"}

ZERO_WORDS: frozenset[str] = frozenset({"ZERO", "ZEROS", "ZEROES"})
SPACE_WORDS: frozenset[str] = frozenset({"SPACE", "SPACES"})
HIGH_VALUE_WORDS: frozenset[str] = frozenset({"HIGH-VALUE", "HIGH-VALUES"})
LOW_VALUE_WORDS: frozenset[str] = frozenset({"LOW-VALUE", "LOW-VALUES"})
QUOTE_WORDS: frozenset[str] = frozenset({"QUOTE", "QUOTES"})
NULL_WORDS: frozenset[str] = frozenset({"NULL", "NULLS"})

#: Sign-condition words (``IF X IS [NOT] POSITIVE``); ``ZERO`` in all three
#: spellings.
SIGN_CONDITION_WORDS: frozenset[str] = frozenset({"POSITIVE", "NEGATIVE"}) | ZERO_WORDS

__all__ = [
    "FIGURATIVE_CANONICAL",
    "FIGURATIVE_CONSTANTS",
    "FIGURATIVE_CONSTANTS_WITH_ALL",
    "HIGH_VALUE_WORDS",
    "LOW_VALUE_WORDS",
    "NULL_WORDS",
    "QUOTE_WORDS",
    "SIGN_CONDITION_WORDS",
    "SPACE_WORDS",
    "ZERO_WORDS",
]
