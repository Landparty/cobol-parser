"""Reading code by its structure: ``read_procedure`` and ``find_statements``.

``read_source`` shows lines around a citation, so a model asking "what does
2100-VALIDATE do" guesses a window and asks again when the paragraph runs
past it. ``read_procedure`` returns exactly one paragraph or section, its
COPY members' lines shown and cited in their own files.

Models still fall back to grep for "every WRITE of REPORT-REC", which
matches comments and misses copybook text. ``find_statements`` searches the
parsed statements instead: by verb, by an operand (resolved by the
cross-reference, so a qualified name or a copybook field matches), by a
literal on the statement's line, by paragraph, in one file or under the
whole root (through the ``statements`` index).

Like :mod:`.tools`, this module imports no SDK.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..models.program import CobolParagraph, CobolProgram, CobolSection
from .envelope import Response, ToolError, clamp_limit
from .workspace import ParsedProgram, Stamp, Workspace, stdout_to_stderr

#: Most lines one read_procedure answer shows.
MAX_PROCEDURE_LINES = 300

#: Files listed in find_statements' by_file, most matches first.
BY_FILE_SHOWN = 20

#: Characters of a statement's source line kept in a find_statements row.
MAX_TEXT = 160


# ---------------------------------------------------------------------------
# Statements as rows
# ---------------------------------------------------------------------------


def statement_verb(statement: Any) -> str:
    """What a reader calls *statement*: ``MOVE``, ``EXEC CICS LINK``,
    ``EXEC SQL SELECT``, ``EXEC DLI GU``."""
    cics = getattr(statement, "_cics_command", None)
    if cics:
        return f"EXEC CICS {str(cics).upper()}"
    ims = getattr(statement, "_ims_command", None)
    if ims:
        return f"EXEC DLI {str(ims).upper()}"
    kind = str(getattr(statement, "statement_type", "") or type(statement).__name__)
    if type(statement).__module__.endswith("sql_statements"):
        sql = getattr(statement, "sql_type", None) or kind
        return f"EXEC SQL {str(sql).upper()}".replace("EXEC SQL EXEC-SQL", "EXEC SQL")
    return kind.upper()


def _procedure_of(statement: Any) -> tuple[str | None, str | None]:
    """(paragraph, section) *statement* is written in."""
    paragraph = section = None
    node = getattr(statement, "parent", None)
    while node is not None:
        if isinstance(node, CobolParagraph) and paragraph is None:
            paragraph = node.paragraph_name
        if isinstance(node, CobolSection):
            section = node.section_name
            break
        if isinstance(node, CobolProgram):
            break
        node = getattr(node, "parent", None)
    return paragraph, section


def _verb_matches(verb: str, wanted: str) -> bool:
    """*wanted* names *verb* or a word-prefix of it (``EXEC CICS`` matches
    ``EXEC CICS LINK``; ``WRITE`` does not match ``WRITE-X``)."""
    words, asked = verb.split(), wanted.split()
    return words[: len(asked)] == asked


@dataclass
class StatementRow:
    """One PROCEDURE DIVISION statement, as find_statements searches it."""

    program: str
    file: str
    line: int
    verb: str
    paragraph: str | None
    section: str | None
    text: str
    #: Operand name (bare and qualified, uppercased) -> roles in it.
    operands: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self, matched: list[str] | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {
            "location": {"file": self.file, "line": self.line},
            "program": self.program,
            "verb": self.verb,
            "paragraph": self.paragraph,
            "text": self.text,
        }
        if self.section:
            row["section"] = self.section
        if matched:
            row["operand_roles"] = matched
        return row


class _Lines:
    """On-disk lines of the files one answer cites, each read once."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._held: dict[str, list[str]] = {}

    def of(self, file: str) -> list[str]:
        if file not in self._held:
            from .tools import _source_lines

            try:
                path = self.workspace.resolve(file)
                self._held[file] = list(_source_lines(path))
            except (ToolError, OSError):
                self._held[file] = []
        return self._held[file]

    def line(self, file: str, number: int) -> str:
        lines = self.of(file)
        return lines[number - 1] if 0 < number <= len(lines) else ""


def _statement_text(text: str) -> str:
    """A source line as a row shows it: sequence and indicator areas off
    (when the line looks fixed-format), blanks collapsed, at most
    :data:`MAX_TEXT` characters."""
    if len(text) > 7 and (text[:6].strip().isdigit() or not text[:6].strip()):
        text = text[7:72]
    text = " ".join(text.split())
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def statement_rows(
    parsed: ParsedProgram, lines: _Lines, response: Response
) -> Iterator[StatementRow]:
    """Every statement of every unit of *parsed*, with its operands."""
    from ..analysis.xref import XrefAnalyzer
    from .tools import _own_statements

    for unit in parsed.ast.program_units():
        name = unit.program_name or "<unnamed>"
        with stdout_to_stderr():
            report = XrefAnalyzer().analyze(unit)
        operands: dict[tuple[int, str], dict[str, set[str]]] = {}
        for entry in report.entries:
            if entry.kind not in ("data-item", "condition-name", "file", "index"):
                continue
            names = {entry.name.upper()}
            if entry.qualified_name:
                names.add(entry.qualified_name.upper())
            for ref in entry.references:
                key = (ref.location.line, ref.statement)
                held = operands.setdefault(key, {})
                for n in names:
                    held.setdefault(n, set()).add(ref.role)
        for statement in _own_statements(unit):
            location = getattr(statement, "location", None)
            if location is None or not location.line:
                continue
            located = parsed.locate(location.line, None, response)
            if located is None:
                continue
            paragraph, section = _procedure_of(statement)
            ops = operands.get((location.line, type(statement).__name__), {})
            yield StatementRow(
                program=name,
                file=located["file"],
                line=located["line"],
                verb=statement_verb(statement),
                paragraph=paragraph,
                section=section,
                text=_statement_text(lines.line(located["file"], located["line"])),
                operands={k: sorted(v) for k, v in ops.items()},
            )


# ---------------------------------------------------------------------------
# The statements index
# ---------------------------------------------------------------------------


@dataclass
class StatementsIndex:
    rows: list[StatementRow] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    file_caveats: dict[str, list[Any]] = field(default_factory=dict)
    seconds: float = 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "program_files": len(self.files),
            "failed_files": len(self.failed),
            "built_in_seconds": round(self.seconds, 2),
        }


def statements_index(workspace: Workspace) -> StatementsIndex:
    def build() -> tuple[StatementsIndex, dict[str, Stamp]]:
        import time

        from .codebase_index import _Survey
        from .facts import surveyed

        started = time.monotonic()
        survey = _Survey()
        stamps = workspace.tree_stamps()
        index = StatementsIndex()
        for facts in surveyed(workspace, survey, stamps):
            index.rows.extend(facts.statements)
        index.files = survey.files
        index.failed = survey.failed
        index.file_caveats = survey.file_caveats
        index.seconds = time.monotonic() - started
        return index, stamps

    held: StatementsIndex = workspace.index("statements", build)
    return held


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------


def find_statements(
    workspace: Workspace,
    verb: str | None = None,
    operand: str | None = None,
    role: str | None = None,
    literal: str | None = None,
    paragraph: str | None = None,
    file: str | None = None,
    program: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Statements matching every filter given, in one file or the root."""
    if not any((verb, operand, literal, paragraph)):
        raise ToolError("give at least one of verb, operand, literal or paragraph")
    cap = clamp_limit(limit)
    response = Response()
    program_info = None
    if file is not None:
        parsed = workspace.program(file)
        from .tools import _carry_parse_caveats

        _carry_parse_caveats(parsed, response)
        program_info = parsed.program_info()
        rows: list[StatementRow] = list(
            statement_rows(parsed, _Lines(workspace), response)
        )
        scope = "file"
    else:
        index = statements_index(workspace)
        from .tools import _carry_index_caveats

        _carry_index_caveats(index, response, "statements")
        rows = index.rows
        scope = "workspace"

    wanted_verb = " ".join(verb.upper().split()) if verb else None
    wanted_operand = (
        " ".join(operand.upper().replace(" IN ", " OF ").split()) if operand else None
    )
    wanted_role = role.lower() if role else None
    wanted_program = program.upper() if program else None
    wanted_paragraph = paragraph.upper() if paragraph else None
    matches: list[dict[str, Any]] = []
    known_verbs: set[str] = set()
    known_operands: set[str] = set()
    for row in rows:
        known_verbs.add(row.verb)
        if wanted_program and row.program.upper() != wanted_program:
            continue
        if wanted_verb and not _verb_matches(row.verb, wanted_verb):
            continue
        if wanted_paragraph and (row.paragraph or "").upper() != wanted_paragraph:
            continue
        if literal and literal.upper() not in row.text.upper():
            continue
        matched: list[str] | None = None
        if wanted_operand:
            known_operands.update(row.operands)
            roles = _operand_roles(row.operands, wanted_operand)
            if roles is None or (wanted_role and wanted_role not in roles):
                continue
            matched = roles
        matches.append(row.to_dict(matched))
    by_verb: dict[str, int] = {}
    by_file: dict[str, int] = {}
    for match in matches:
        by_verb[match["verb"]] = by_verb.get(match["verb"], 0) + 1
        file_of = match["location"]["file"]
        by_file[file_of] = by_file.get(file_of, 0) + 1
    answer: dict[str, Any] = {
        "scope": scope,
        "filters": {
            k: v
            for k, v in {
                "verb": wanted_verb,
                "operand": wanted_operand,
                "role": wanted_role,
                "literal": literal,
                "paragraph": wanted_paragraph,
                "program": wanted_program,
            }.items()
            if v
        },
        "match_count": len(matches),
        "by_verb": dict(sorted(by_verb.items())),
        "file_count": len(by_file),
        "by_file": dict(
            response.cap(
                sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0])),
                BY_FILE_SHOWN,
                "by_file",
            )
        ),
        "statements": response.cap(matches, cap, "statements"),
    }
    if not matches:
        suggestions: list[str] = []
        if wanted_verb and not any(_verb_matches(v, wanted_verb) for v in known_verbs):
            suggestions = difflib.get_close_matches(
                wanted_verb, sorted(known_verbs), n=5
            )
        elif wanted_operand and known_operands:
            suggestions = difflib.get_close_matches(
                wanted_operand, sorted(known_operands), n=5
            )
        if suggestions:
            answer["suggestions"] = suggestions
    if literal:
        response.caveat(
            "incomplete-analysis",
            "literal is matched on the first source line of each statement",
            "a literal on a statement's continuation line is not found",
        )
    return response.build(answer, program_info)


def _operand_roles(operands: dict[str, list[str]], wanted: str) -> list[str] | None:
    """The roles of operand *wanted* (bare, qualified ``X OF Y``, or a
    partial chain) in a row's operands, or None when it is not one."""
    if wanted in operands:
        return operands[wanted]
    # Qualified names are kept as xref spells them: dotted, outermost first
    # (``REC.FIELD``); ``FIELD OF REC`` is the same name.
    parts = [p.strip() for p in wanted.split(" OF ")]
    if len(parts) > 1:
        dotted = ".".join(reversed(parts))
        for name, roles in operands.items():
            if name == dotted or name.endswith("." + dotted):
                return roles
        for name, roles in operands.items():
            chain = name.split(".")
            if chain[-1] == parts[0] and all(q in chain for q in parts[1:]):
                return roles
    return None


def read_procedure(
    workspace: Workspace,
    file: str,
    name: str,
    program: str | None = None,
) -> dict[str, Any]:
    """The whole of one paragraph or section, numbered, copybook lines in
    their own files."""
    from ..analysis._procedures import ProcedureIndex
    from .tools import _carry_parse_caveats, _declared_elsewhere

    wanted = " ".join(name.upper().replace(" IN ", " OF ").split())
    if not wanted:
        raise ToolError("no paragraph or section name given")
    parsed = workspace.program(file)
    response = Response()
    _carry_parse_caveats(parsed, response)
    unit = parsed.unit(program, response)
    program_info = parsed.program_info(unit)
    division = unit.procedure_division
    if division is None:
        raise ToolError(f"{parsed.display_path} has no PROCEDURE DIVISION")
    index = ProcedureIndex.build(division)
    entries = index.entries
    matches = [
        e for e in entries if e.key.upper() == wanted or e.name.upper() == wanted
    ]
    if not matches:
        missing: dict[str, Any] = {
            "name": wanted,
            "found": False,
            "suggestions": difflib.get_close_matches(
                wanted, sorted({e.key.upper() for e in entries}), n=5
            ),
        }
        _declared_elsewhere(
            missing,
            parsed,
            unit,
            lambda other: other.procedure_division is not None
            and any(
                e.name.upper() == wanted
                for e in ProcedureIndex.build(other.procedure_division).entries
            ),
        )
        return response.build(missing, program_info)
    if len(matches) > 1:
        response.caveat(
            "ambiguous-name",
            f"{len(matches)} procedures are named {wanted}",
            "the first is shown; qualify the name (PARA OF SECTION) for another",
        )
    entry = matches[0]
    start = entry.node.location.line
    lines = _Lines(workspace)
    end = _procedure_end(entry, entries, parsed, lines)
    segments: list[dict[str, Any]] = []
    shown = 0
    total = end - start + 1
    for expanded in range(start, end + 1):
        located = parsed.locate(expanded, None, response)
        if located is None:
            continue
        if shown >= MAX_PROCEDURE_LINES:
            continue
        text = lines.line(located["file"], located["line"])
        last = segments[-1] if segments else None
        if (
            last is not None
            and last["file"] == located["file"]
            and last["start_line"] + len(last["lines"]) == located["line"]
        ):
            last["lines"].append(text)
        else:
            segments.append(
                {
                    "file": located["file"],
                    "start_line": located["line"],
                    "lines": [text],
                }
            )
        shown += 1
    if shown < total and total > MAX_PROCEDURE_LINES:
        response.truncated.append(
            {"field": "segments", "shown": MAX_PROCEDURE_LINES, "total": total}
        )
    answer: dict[str, Any] = {
        "name": entry.name,
        "kind": entry.procedure_type.lower(),
        "found": True,
        "line_count": total,
        "segments": segments,
        "legend": "each segment is a run of consecutive lines of one file, "
        "the first numbered start_line; a COPY member's lines are a segment "
        "of their own, in the member",
    }
    if entry.section and entry.procedure_type == "PARAGRAPH":
        answer["section"] = entry.section
    if entry.procedure_type == "SECTION":
        answer["paragraphs"] = [
            p.paragraph_name
            for p in getattr(entry.node, "paragraphs", [])
            if p.paragraph_name
        ]
    return response.build(answer, program_info)


#: Lines past a last procedure's last statement read for its continuation.
_TAIL_LINES = 50


def _procedure_end(
    entry: Any,
    entries: list[Any],
    parsed: ParsedProgram,
    lines: _Lines,
) -> int:
    """The last expanded line of *entry*: the line before the next procedure
    header at its level (for a section, the next section). The last
    procedure of a unit has no next header: it runs from its last
    statement to the next line starting in Area A (``END PROGRAM``, a
    following unit) or the end of the text."""
    start = entry.node.location.line
    if entry.procedure_type == "SECTION":
        later = [
            e.node.location.line
            for e in entries
            if e.procedure_type == "SECTION" and e.node.location.line > start
        ]
    else:
        later = [e.node.location.line for e in entries if e.node.location.line > start]
    if later:
        return int(max(min(later) - 1, start))
    statements = _statements_under(entry.node)
    last: int = max(
        [start] + [s.location.line for s in statements if getattr(s, "location", None)]
    )
    end = last
    for expanded in range(last + 1, last + 1 + _TAIL_LINES):
        located = parsed.locate(expanded, None, Response())
        if located is None:
            break
        text = lines.line(located["file"], located["line"])
        if not text and located["line"] > len(lines.of(located["file"])):
            break
        if _starts_in_area_a(text):
            break
        end = expanded
    return end


def _starts_in_area_a(text: str) -> bool:
    """A fixed-format line with code in columns 8-11, or END PROGRAM."""
    if "END PROGRAM" in text.upper():
        return True
    return len(text) > 7 and text[6:7] not in ("*", "/") and bool(text[7:11].strip())


def _statements_under(node: Any) -> list[Any]:
    found: list[Any] = []

    def walk(current: Any) -> None:
        for child in getattr(current, "children", []) or []:
            if getattr(child, "location", None) is not None and hasattr(
                child, "statement_type"
            ):
                found.append(child)
            walk(child)

    walk(node)
    return found
