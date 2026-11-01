"""CICS resource definitions: DFHCSDUP commands, and the older DFHPCT/DFHPPT/DFHFCT tables.

The CSD is where a transaction id is tied to the program it starts, a CICS
file to its dataset and a mapset to its load module; none of that is in the
COBOL source. ``parse_csd(source)`` reads the ``DEFINE`` commands of a
DFHCSDUP input deck (or an EXTRACT of one) and the ``DFHPCT`` / ``DFHPPT`` /
``DFHFCT TYPE=ENTRY`` macros of a table-based region.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .._lines import split_source_lines
from ._asm import read_statements

#: DFHCSDUP commands: a word that starts a new command when it has no value.
_COMMANDS = frozenset(
    {
        "DEFINE",
        "DEF",
        "ALTER",
        "ALT",
        "ADD",
        "APPEND",
        "COPY",
        "DELETE",
        "LIST",
        "REMOVE",
        "LOCK",
        "UNLOCK",
        "USERDEFINE",
        "CHECK",
        "SCAN",
        "VERIFY",
        "UPGRADE",
        "INITIALIZE",
        "INIT",
        "EXTRACT",
        "SERVICE",
        "MIGRATE",
        "PROCESS",
    }
)

#: Resource types and the shortest abbreviation DFHCSDUP accepts for each.
_RESOURCE_TYPES: dict[str, int] = {
    "TRANSACTION": 5,
    "PROGRAM": 4,
    "MAPSET": 3,
    "FILE": 4,
    "TDQUEUE": 3,
    "TSMODEL": 3,
    "LIBRARY": 3,
    "DB2ENTRY": 8,
    "DB2TRAN": 7,
    "DB2CONN": 7,
    "URIMAP": 4,
    "WEBSERVICE": 4,
    "PIPELINE": 4,
    "TCPIPSERVICE": 5,
    "PROFILE": 4,
    "PARTITIONSET": 5,
    "PARTNER": 7,
    "PROCESSTYPE": 5,
    "TERMINAL": 4,
    "TYPETERM": 4,
    "CONNECTION": 4,
    "SESSIONS": 4,
    "JOURNALMODEL": 4,
    "LSRPOOL": 3,
    "ENQMODEL": 4,
    "REQUESTMODEL": 4,
    "DOCTEMPLATE": 3,
    "JVMSERVER": 3,
    "BUNDLE": 3,
    "ATOMSERVICE": 3,
    "CORBASERVER": 4,
    "DJAR": 4,
    "MQCONN": 6,
    "MQMONITOR": 6,
    "IPCONN": 6,
    "TRANCLASS": 6,
}

_NON_RESOURCE_KEYWORDS = frozenset({"GROUP", "LIST", "DESCRIPTION", "TO", "AS", "ALL"})

#: Attribute abbreviations worth normalising (DFHCSDUP accepts any unique prefix).
_ATTRIBUTE_NAMES = (
    "PROGRAM",
    "DSNAME",
    "DESCRIPTION",
    "TRANSID",
    "PROFILE",
    "TWASIZE",
    "LANGUAGE",
    "ENTRY",
    "PLAN",
    "PLANEXITNAME",
    "REMOTESYSTEM",
    "REMOTENAME",
    "STATUS",
    "RECORDFORMAT",
    "KEYLENGTH",
    "RECORDSIZE",
    "ADD",
    "BROWSE",
    "DELETE",
    "READ",
    "UPDATE",
    "EXECKEY",
    "CONCURRENCY",
    "DATALOCATION",
    "TASKDATALOC",
    "TASKDATAKEY",
    "PRIORITY",
    "TRANCLASS",
    "DTIMOUT",
    "PATH",
    "SCHEME",
    "HOST",
    "PIPELINE",
    "WEBSERVICE",
    "URIMAP",
    "DSNAME01",
    "TYPE",
    "QUEUE",
    "DESTFAC",
    "TRIGGERLEVEL",
)


@dataclass
class CsdResource:
    """One resource definition (or table entry)."""

    type: str
    name: str
    line: int
    group: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    source: str = "DFHCSDUP"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "group": self.group,
            "attributes": self.attributes,
            "source": self.source,
            "line": self.line,
        }


@dataclass
class CsdDefinitions:
    """Every resource of a CSD deck, plus the group lists it builds."""

    resources: list[CsdResource] = field(default_factory=list)
    lists: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def of_type(self, resource_type: str) -> list[CsdResource]:
        return [r for r in self.resources if r.type == resource_type]

    def transactions(self) -> list[dict[str, Any]]:
        """Transaction id -> program, with the DB2 plan when a DB2ENTRY/DB2TRAN names it."""
        plans = self._db2_plans()
        out = []
        for res in self.of_type("TRANSACTION"):
            attrs = res.attributes
            out.append(
                {
                    "transid": res.name,
                    "program": attrs.get("PROGRAM"),
                    "group": res.group,
                    "description": attrs.get("DESCRIPTION"),
                    "profile": attrs.get("PROFILE"),
                    "remote_system": attrs.get("REMOTESYSTEM"),
                    "status": attrs.get("STATUS"),
                    "db2_entry": plans.get(res.name, {}).get("entry"),
                    "db2_plan": plans.get(res.name, {}).get("plan"),
                    "source": res.source,
                    "line": res.line,
                }
            )
        return out

    def _db2_plans(self) -> dict[str, dict[str, str | None]]:
        entries = {r.name: r for r in self.of_type("DB2ENTRY")}
        plans: dict[str, dict[str, str | None]] = {}
        for entry in entries.values():
            transid = entry.attributes.get("TRANSID")
            if transid:
                plans[transid] = {
                    "entry": entry.name,
                    "plan": entry.attributes.get("PLAN"),
                }
        for tran in self.of_type("DB2TRAN"):
            transid = tran.attributes.get("TRANSID")
            entry_name = tran.attributes.get("ENTRY")
            if transid and entry_name:
                db2_entry = entries.get(entry_name)
                plans[transid] = {
                    "entry": entry_name,
                    "plan": db2_entry.attributes.get("PLAN") if db2_entry else None,
                }
        return plans

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for res in self.resources:
            counts[res.type] = counts.get(res.type, 0) + 1
        return {
            "kind": "CSD",
            "transactions": self.transactions(),
            "programs": [
                {
                    "name": r.name,
                    "group": r.group,
                    "language": r.attributes.get("LANGUAGE"),
                    "remote_system": r.attributes.get("REMOTESYSTEM"),
                    "line": r.line,
                }
                for r in self.of_type("PROGRAM")
            ],
            "mapsets": [
                {"name": r.name, "group": r.group, "line": r.line}
                for r in self.of_type("MAPSET")
            ],
            "files": [
                {
                    "name": r.name,
                    "group": r.group,
                    "dsname": r.attributes.get("DSNAME"),
                    "line": r.line,
                    "source": r.source,
                }
                for r in self.of_type("FILE")
            ],
            "resource_counts": counts,
            "resources": [r.to_dict() for r in self.resources],
            "lists": self.lists,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# DFHCSDUP commands
# ---------------------------------------------------------------------------

_SEQUENCE_FIELD = re.compile(r"^(.{72})\s*\d{1,8}\s*$")


def _strip_sequence(record: str) -> str:
    match = _SEQUENCE_FIELD.match(record)
    return match.group(1) if match else record


@dataclass
class _Token:
    word: str
    value: str | None
    line: int


def _tokens(source: str) -> list[_Token]:
    """Words of a DFHCSDUP deck, each with its parenthesised value (if any)."""
    tokens: list[_Token] = []
    word: list[str] = []
    word_line = 0
    value: list[str] | None = None
    depth = 0
    in_quote = False
    for line_no, raw in enumerate(split_source_lines(source), start=1):
        record = _strip_sequence(raw)
        if value is None and record.lstrip().startswith("*"):
            continue
        for char in record:
            if value is not None:
                if char == "'":
                    in_quote = not in_quote
                elif not in_quote and char == "(":
                    depth += 1
                elif not in_quote and char == ")":
                    depth -= 1
                    if depth == 0:
                        tokens.append(
                            _Token("".join(word).upper(), "".join(value), word_line)
                        )
                        word, value = [], None
                        continue
                value.append(char)
                continue
            if char == "(" and word:
                value, depth, in_quote = [], 1, False
                continue
            if char.isspace() or char == ",":
                if word:
                    tokens.append(_Token("".join(word).upper(), None, word_line))
                    word = []
                continue
            if not word:
                word_line = line_no
            word.append(char)
        if value is not None:
            # The value goes on in the next record; _clean_value collapses the gap.
            value.append(" ")
            continue
        if word:
            tokens.append(_Token("".join(word).upper(), None, word_line))
            word = []
    if word:
        tokens.append(
            _Token("".join(word).upper(), "".join(value) if value else None, word_line)
        )
    return tokens


def _resource_type(keyword: str) -> str | None:
    for name, minimum in _RESOURCE_TYPES.items():
        if len(keyword) >= minimum and name.startswith(keyword):
            return name
    return None


def _attribute_name(keyword: str) -> str:
    if keyword in _ATTRIBUTE_NAMES:
        return keyword
    matches = {
        name
        for name in _ATTRIBUTE_NAMES
        if len(keyword) >= 4 and name.startswith(keyword)
    }
    return matches.pop() if len(matches) == 1 else keyword


def _clean_value(value: str) -> str:
    text = " ".join(value.split())
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        text = text[1:-1].replace("''", "'")
    return text


def _commands(tokens: list[_Token]) -> list[list[_Token]]:
    commands: list[list[_Token]] = []
    for token in tokens:
        if token.value is None and token.word in _COMMANDS:
            commands.append([token])
        elif commands:
            commands[-1].append(token)
    return commands


def _define(command: list[_Token], result: CsdDefinitions) -> None:
    head = command[0]
    resource: CsdResource | None = None
    group: str | None = None
    attributes: dict[str, str] = {}
    for token in command[1:]:
        if token.value is None:
            continue
        value = _clean_value(token.value)
        if token.word == "GROUP":
            group = value.upper()
            continue
        resource_type = (
            _resource_type(token.word)
            if resource is None and token.word not in _NON_RESOURCE_KEYWORDS
            else None
        )
        if resource is None and resource_type is not None:
            resource = CsdResource(
                type=resource_type, name=value.upper(), line=head.line
            )
            continue
        name = _attribute_name(token.word)
        attributes[name] = (
            value if name == "DESCRIPTION" else value.replace(" ", "").upper()
        )
    if resource is None:
        result.warnings.append(
            {"line": head.line, "message": "DEFINE without a resource type"}
        )
        return
    resource.group = group
    resource.attributes = attributes
    if head.word in ("ALTER", "ALT"):
        _apply_alter(resource, result)
        return
    result.resources.append(resource)


def _apply_alter(resource: CsdResource, result: CsdDefinitions) -> None:
    for existing in result.resources:
        if existing.type == resource.type and existing.name == resource.name:
            if resource.group in (None, existing.group):
                existing.attributes.update(resource.attributes)
                return
    result.warnings.append(
        {
            "line": resource.line,
            "message": f"ALTER of {resource.type} {resource.name}, which this deck does not define",
        }
    )


def _add(command: list[_Token], result: CsdDefinitions) -> None:
    values = {
        t.word: _clean_value(t.value).upper()
        for t in command[1:]
        if t.value is not None
    }
    group, list_name = values.get("GROUP"), values.get("LIST")
    if group and list_name:
        result.lists.setdefault(list_name, []).append(group)


# ---------------------------------------------------------------------------
# Macro tables (pre-RDO regions)
# ---------------------------------------------------------------------------

_TABLE_ENTRIES: dict[str, tuple[str, str]] = {
    # macro: (resource type, keyword holding the name)
    "DFHPCT": ("TRANSACTION", "TRANSID"),
    "DFHPPT": ("PROGRAM", "PROGRAM"),
    "DFHFCT": ("FILE", "DATASET"),
}


def _table_entries(source: str, result: CsdDefinitions) -> None:
    for stmt in read_statements(source):
        spec = _TABLE_ENTRIES.get(stmt.operation)
        if spec is None:
            continue
        entry_type = (stmt.text("TYPE") or "").upper()
        if entry_type not in ("ENTRY", "DATASET", "FILE"):
            continue
        resource_type, name_key = spec
        name = stmt.text(name_key) or stmt.text("FILE")
        if stmt.operation == "DFHPPT" and not name and stmt.text("MAPSET"):
            resource_type, name = "MAPSET", stmt.text("MAPSET")
        if not name:
            result.warnings.append(
                {
                    "line": stmt.line,
                    "message": f"{stmt.operation} entry without {name_key}=",
                }
            )
            continue
        attributes = {
            key: value.upper()
            for key in ("PROGRAM", "DSNAME", "PROFILE", "TWASIZE")
            if (value := stmt.text(key))
        }
        result.resources.append(
            CsdResource(
                type=resource_type,
                name=name.upper(),
                line=stmt.line,
                attributes=attributes,
                source=stmt.operation,
            )
        )


_TABLE_MACRO = re.compile(r"^\S*\s+DFH(?:PCT|PPT|FCT)\s", re.MULTILINE)


def parse_csd(source: str) -> CsdDefinitions:
    """The resource definitions of a DFHCSDUP deck or of DFHPCT/DFHPPT/DFHFCT tables."""
    result = CsdDefinitions()
    if _TABLE_MACRO.search(source):
        _table_entries(source, result)
        return result
    for command in _commands(_tokens(source)):
        verb = command[0].word
        if verb in ("DEFINE", "DEF", "ALTER", "ALT"):
            _define(command, result)
        elif verb in ("ADD", "APPEND"):
            _add(command, result)
    return result
