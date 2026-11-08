"""Validation of lint scopes: ``lint --scope`` values and ``lint.scope``.

The CLI (``cli/_new_code.py``) and the project config reader both validate
scopes. It lives here, under ``config``, so the config layer never imports
from ``cli``, which sits above it.
"""

from __future__ import annotations

from typing import Any

#: Scope values. ``new``: only findings on new code count; ``all``: every one.
SCOPES: tuple[str, ...] = ("new", "all")


def parse_scopes(items: Any) -> tuple[str, dict[str, str]]:
    """``(default, {selector: scope})`` from ``--scope`` values (``new``,
    ``all``, ``RULE=new``, ``RULE/KIND=all``) or the ``lint.scope``
    mapping (``{default: new, call-check: all}``) or string.

    Raises:
        ValueError: a value that is none of those, or names no rule.
    """
    from ..analysis.lint import ALL_RULES, PARSE_RULE

    default = "new"
    per_rule: dict[str, str] = {}
    if items is None:
        return default, per_rule
    if isinstance(items, str):
        items = [items]
    pairs: list[tuple[str | None, str]] = []
    if isinstance(items, dict):
        pairs = [
            (None if str(k) == "default" else str(k), str(v)) for k, v in items.items()
        ]
    else:
        for item in items:
            name, sep, value = str(item).partition("=")
            pairs.append((name, value) if sep else (None, name))
    for selector, value in pairs:
        if value not in SCOPES:
            raise ValueError(
                f"scope {value!r} for {selector or 'every rule'}: expected "
                f"{' or '.join(SCOPES)}"
            )
        if selector is None:
            default = value
            continue
        rule = selector.split("/", 1)[0].lower()
        if rule not in (*ALL_RULES, PARSE_RULE):
            raise ValueError(
                f"scope {selector}={value}: unknown rule {rule!r} "
                f"(recognized: {', '.join((*ALL_RULES, PARSE_RULE))})"
            )
        per_rule[selector] = value
    return default, per_rule
