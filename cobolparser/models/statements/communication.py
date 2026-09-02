"""COBOL-85 Communication Module statement AST nodes.

``SEND``, ``RECEIVE``, ``ENABLE``, ``DISABLE`` and ``PURGE`` operate on the
COMMUNICATION SECTION's CD entries (message control system queues). IBM
Enterprise COBOL does not implement the module, but the NIST COBOL-85 suite
(``CM1xx``/``CM2xx``/``CM4xx``) and older ANSI programs use these verbs, and
every one of them previously vanished from the AST with only an
"unsupported statement" warning.
"""

from typing import Any

from ..ast_base import SourceLocation
from .base import CobolStatement


class SendStatement(CobolStatement):
    """AST node for the SEND statement.

    Syntax::

        SEND cd-name [FROM identifier]
             [WITH {EGI | EMI | ESI | identifier}]
             [{BEFORE | AFTER} [ADVANCING] {identifier | integer [LINE|LINES]
                                            | PAGE | mnemonic-name}]
             [REPLACING LINE]
    """

    def __init__(self, location: SourceLocation):
        super().__init__("SEND", location)
        self.cd_name: str | None = None
        self.from_identifier: str | None = None
        self.indicator: str | None = None  # EGI / EMI / ESI / identifier
        self.advancing_mode: str | None = None  # BEFORE / AFTER
        self.advancing_value: str | None = None  # identifier, integer, PAGE, ...
        self.advancing_unit: str | None = None  # LINE / LINES
        self.replacing_line: bool = False

    def set_cd_name(self, name: str) -> None:
        self.cd_name = name
        self._add_unique_operand(name)

    def set_from_identifier(self, name: str) -> None:
        self.from_identifier = name
        self._add_unique_operand(name)

    def set_indicator(self, value: str) -> None:
        self.indicator = (
            value.upper() if value.upper() in ("EGI", "EMI", "ESI") else value
        )
        if self.indicator not in ("EGI", "EMI", "ESI"):
            self._add_unique_operand(value)

    def set_advancing(
        self, mode: str, value: str | None = None, unit: str | None = None
    ) -> None:
        self.advancing_mode = mode.upper() if mode else None
        self.advancing_value = value
        self.advancing_unit = unit.upper() if unit else None

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "cd_name": self.cd_name,
                "from_identifier": self.from_identifier,
                "indicator": self.indicator,
                "advancing_mode": self.advancing_mode,
                "advancing_value": self.advancing_value,
                "advancing_unit": self.advancing_unit,
                "replacing_line": self.replacing_line,
            }
        )
        return result


class ReceiveStatement(CobolStatement):
    """AST node for the RECEIVE statement.

    Syntax::

        RECEIVE cd-name {MESSAGE | SEGMENT} INTO identifier
                [NO DATA imperative-statement]
                [WITH DATA imperative-statement]
                [END-RECEIVE]
    """

    def __init__(self, location: SourceLocation):
        super().__init__("RECEIVE", location)
        self.cd_name: str | None = None
        self.mode: str | None = None  # MESSAGE / SEGMENT
        self.into_target: str | None = None
        self.no_data_clause: list[CobolStatement] | None = None
        self.with_data_clause: list[CobolStatement] | None = None

    def set_cd_name(self, name: str) -> None:
        self.cd_name = name
        self._add_unique_operand(name)

    def set_mode(self, mode: str) -> None:
        self.mode = mode.upper()

    def set_into(self, target: str) -> None:
        self.into_target = target
        self._add_unique_operand(target)

    def set_no_data_clause(self, statements: list[CobolStatement]) -> None:
        self._set_clause("no_data_clause", statements)

    def set_with_data_clause(self, statements: list[CobolStatement]) -> None:
        self._set_clause("with_data_clause", statements)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "cd_name": self.cd_name,
                "mode": self.mode,
                "into_target": self.into_target,
            }
        )
        result.update(self._serialize_clauses("no_data_clause", "with_data_clause"))
        return result


class _EnableDisableStatement(CobolStatement):
    """Shared shape of ENABLE and DISABLE.

    Syntax::

        {ENABLE | DISABLE} {INPUT [TERMINAL] | I-O TERMINAL | OUTPUT} cd-name
                           [WITH KEY {identifier | literal}]
    """

    def __init__(self, statement_type: str, location: SourceLocation):
        super().__init__(statement_type, location)
        self.mode: str | None = None  # INPUT / INPUT TERMINAL / I-O TERMINAL / OUTPUT
        self.cd_name: str | None = None
        self.key: str | None = None

    def set_mode(self, mode: str) -> None:
        self.mode = mode.upper()

    def set_cd_name(self, name: str) -> None:
        self.cd_name = name
        self._add_unique_operand(name)

    def set_key(self, value: str) -> None:
        self.key = value

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update({"mode": self.mode, "cd_name": self.cd_name, "key": self.key})
        return result


class EnableStatement(_EnableDisableStatement):
    """AST node for the ENABLE statement."""

    def __init__(self, location: SourceLocation):
        super().__init__("ENABLE", location)


class DisableStatement(_EnableDisableStatement):
    """AST node for the DISABLE statement."""

    def __init__(self, location: SourceLocation):
        super().__init__("DISABLE", location)


class PurgeStatement(CobolStatement):
    """AST node for ``PURGE cd-name``."""

    def __init__(self, location: SourceLocation):
        super().__init__("PURGE", location)
        self.cd_name: str | None = None

    def set_cd_name(self, name: str) -> None:
        self.cd_name = name
        self._add_unique_operand(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["cd_name"] = self.cd_name
        return result


__all__ = [
    "SendStatement",
    "ReceiveStatement",
    "EnableStatement",
    "DisableStatement",
    "PurgeStatement",
]
