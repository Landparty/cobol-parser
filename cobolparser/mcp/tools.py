"""The MCP tools, as plain functions over a :class:`Workspace`.

Nothing here imports the MCP SDK: every tool takes plain arguments and
returns a plain dict (the :mod:`.envelope` shape), so it is unit-testable
without the ``[mcp]`` extra and callable from any other front end -- the
backend, the VS Code extension -- exactly as the server calls it.

Each tool answers one question a person asks about COBOL, joining analyzers
server-side, rather than mirroring a CLI subcommand: a whole ``xref`` report
of a large program would spend a model's context on the first call.
"""

from __future__ import annotations

import difflib
from typing import Any

from .._lines import split_source_lines
from ..models.program import CobolProgram
from .envelope import Response, ToolError, clamp_limit
from .workspace import ParsedProgram, Workspace, stdout_to_stderr

#: Prefixes of the xref caveats that are about undeclared names only.
_UNDECLARED_CAVEATS: tuple[str, ...] = (
    "the kind of an undefined symbol",
    "'undefined' means",
    "special registers",
)

#: Most lines :meth:`CobolTools.read_source` returns in one call.
MAX_SOURCE_LINES = 200


class CobolTools:
    """Every tool the MCP server exposes, bound to one workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    # -- read_source ---------------------------------------------------------

    def read_source(
        self, file: str, line: int = 1, before: int = 10, after: int = 10
    ) -> dict[str, Any]:
        """The lines around ``file:line``, numbered as an editor numbers them."""
        path = self.workspace.resolve(file)
        lines = split_source_lines(self.workspace.read_text(path))
        if lines and lines[-1] == "":
            lines.pop()
        total = len(lines)
        if line < 1 or (total and line > total):
            raise ToolError(f"line {line} is outside {file} (1-{total})")
        before = max(0, before)
        after = max(0, after)
        start = max(1, line - before)
        end = min(total, line + after)
        response = Response()
        if end - start + 1 > MAX_SOURCE_LINES:
            response.truncated.append(
                {
                    "field": "lines",
                    "shown": MAX_SOURCE_LINES,
                    "total": end - start + 1,
                }
            )
            end = start + MAX_SOURCE_LINES - 1
        return response.build(
            {
                "file": self.workspace.display(path),
                "start_line": start,
                "end_line": end,
                "total_lines": total,
                "lines": [
                    {"line": n, "text": lines[n - 1]} for n in range(start, end + 1)
                ],
            }
        )

    # -- lint ----------------------------------------------------------------

    def lint(
        self,
        file: str,
        rules: list[str] | None = None,
        min_severity: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Every lint finding in *file*, worst first, each cited on disk."""
        from ..analysis.lint import (
            SEVERITIES,
            LintAnalyzer,
            add_parse_errors,
            filter_by_severity,
        )

        config = self.workspace.config.lint
        selected = rules or list(config.rules) or None
        severity = min_severity or config.min_severity or "info"
        if severity not in SEVERITIES:
            raise ToolError(
                f"unknown severity {severity!r} (expected one of "
                f"{', '.join(SEVERITIES)})"
            )
        try:
            analyzer = LintAnalyzer(selected)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        with stdout_to_stderr():
            report = analyzer.analyze(
                parsed.ast, copybook_item_names=_copybook_item_names(parsed)
            )
        add_parse_errors(report, list(parsed.result.errors))

        for failure in report.failed_rules:
            response.caveat(
                "analyzer-failed",
                f"lint rule {failure['rule']} did not run: {failure['error']}",
                f"no {failure['rule']} findings are reported",
            )
        for caveat in report.caveats:
            response.caveat("incomplete-analysis", caveat)

        findings = filter_by_severity(report.findings, severity)
        # Worst first, then source order, so a cut list keeps the errors.
        rank = {name: i for i, name in enumerate(SEVERITIES)}
        ordered = sorted(
            enumerate(findings), key=lambda pair: (rank[pair[1].severity], pair[0])
        )
        shown = response.cap([f for _, f in ordered], clamp_limit(limit), "findings")

        summary: dict[str, Any] = {"total": len(findings)}
        for name in SEVERITIES:
            summary[name] = sum(1 for f in findings if f.severity == name)
        answer = {
            "rules_run": list(report.rules_run),
            "min_severity": severity,
            "summary": summary,
            "findings": [
                {
                    "rule": f.rule,
                    "severity": f.severity,
                    "message": f.message,
                    "symbol": f.symbol,
                    "kind": f.kind,
                    "location": parsed.locate(
                        f.location.line if f.location else None,
                        f.location.column if f.location else None,
                        response,
                        column_known=f.column_known,
                    ),
                }
                for f in shown
            ],
        }
        return response.build(answer, parsed.program_info())

    # -- explain_symbol ------------------------------------------------------

    def explain_symbol(
        self,
        file: str,
        name: str,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """What *name* is in *file*: declaration, layout, every reference."""
        from ..analysis.xref import XrefAnalyzer

        wanted = " ".join(name.split()).upper()
        if not wanted:
            raise ToolError("no symbol name given")
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        with stdout_to_stderr():
            report = XrefAnalyzer().analyze(unit)

        qualified = " OF " in wanted or " IN " in wanted
        if qualified:
            entry = report.entry_for(wanted.replace(" IN ", " OF "))
            matches = [entry] if entry is not None else []
        else:
            matches = [e for e in report.entries if e.name.upper() == wanted]

        program_info = parsed.program_info(unit)
        undeclared_asked = not matches or any(e.definition is None for e in matches)
        for caveat in report.caveats:
            # xref's notes about *undeclared* names only bear on an answer
            # about one; on every other answer they are noise a model pays for.
            if undeclared_asked or not caveat.startswith(_UNDECLARED_CAVEATS):
                response.caveat("incomplete-analysis", caveat)
        if not matches:
            undeclared = wanted in {u.upper() for u in report.undefined}
            names = sorted({e.name.upper() for e in report.entries})
            return response.build(
                {
                    "name": wanted,
                    "found": False,
                    "referenced_but_undeclared": undeclared,
                    "suggestions": difflib.get_close_matches(wanted, names, n=5),
                },
                program_info,
            )

        if len(matches) > 1:
            response.caveat(
                "ambiguous-name",
                f"{len(matches)} declarations are named {wanted}",
                "qualify the name (X OF Y) to ask about one of them",
            )
        if any(d.upper() == wanted for d in report.duplicate_declarations):
            response.caveat(
                "duplicate-declaration",
                f"{wanted} is declared more than once in one namespace",
                "every reference is attributed to the first declaration",
            )

        layout = _layout_index(unit, response)
        cap = clamp_limit(limit)
        symbols: list[dict[str, Any]] = []
        for index, entry in enumerate(matches):
            roles: dict[str, int] = {}
            for ref in entry.references:
                roles[ref.role] = roles.get(ref.role, 0) + 1
            refs = response.cap(
                list(entry.references), cap, f"symbols[{index}].references"
            )
            symbol: dict[str, Any] = {
                "name": entry.name,
                "kind": entry.kind,
                "qualified_name": entry.qualified_name,
                "level": entry.level,
                "section": entry.section,
                "declared_at": (
                    parsed.locate(
                        entry.definition.line, entry.definition.column, response
                    )
                    if entry.definition
                    else None
                ),
                "declared": entry.definition is not None,
                "reference_count": entry.reference_count,
                "references_by_role": roles,
                "references": [
                    {
                        # xref's column is the statement's, not the
                        # operand's: the line is exact, a column would mislead.
                        "location": parsed.locate(
                            ref.location.line,
                            None,
                            response,
                            column_known=False,
                        ),
                        "role": ref.role,
                        "statement": ref.statement,
                        "paragraph": ref.context,
                    }
                    for ref in refs
                ],
            }
            item = _layout_for(entry.name, entry.qualified_name, layout)
            if item is not None:
                symbol["layout"] = {
                    key: item.get(key)
                    for key in (
                        "qualified_name",
                        "picture",
                        "usage",
                        "byte_offset",
                        "byte_length",
                        "offset_ambiguous",
                        "redefines_chain",
                        "occurs",
                        "condition_values",
                        "condition_ranges",
                    )
                    if _worth_showing(item.get(key))
                }
            symbols.append(symbol)

        return response.build(
            {"name": wanted, "found": True, "symbols": symbols}, program_info
        )


def _copybook_item_names(parsed: ParsedProgram) -> set[str] | None:
    """Upper-cased names of data items declared only inside a COPY member.

    What lets lint grade an unused copybook field (every SQLCA field a
    program never reads) as info rather than warning, as the ``lint`` CLI
    does. The CLI finds them by diffing an unexpanded parse; the source map
    already says which file each declaration came from, so no second parse
    is needed. A name the program also declares itself is the program's.
    ``None`` -- "not known" -- when nothing was expanded.
    """
    from ..analysis.unused_variables import collect_declared_items

    if parsed.source_map is None:
        return None
    main = str(parsed.path)
    copied: set[str] = set()
    local: set[str] = set()
    for unit in parsed.ast.program_units():
        for item in collect_declared_items(unit):
            location = getattr(item, "location", None)
            origin = parsed.source_map.get(location.line) if location else None
            if origin is None:
                continue
            (local if origin[0] == main else copied).add(item.name.upper())
    return copied - local


def _worth_showing(value: Any) -> bool:
    """A layout value that says something: not absent, empty or ``False``.

    ``byte_offset`` 0 is information; ``0 in (None, [], False)`` is True.
    """
    return value is not None and value is not False and value != []


def _carry_parse_caveats(parsed: ParsedProgram, response: Response) -> None:
    for caveat in parsed.caveats:
        response.caveat(caveat.kind, caveat.detail, caveat.effect)


def _layout_index(
    unit: CobolProgram, response: Response
) -> dict[str, list[dict[str, Any]]]:
    """Every data item's byte layout, by upper-cased name."""
    from ..generators.data.layout_offsets import compute_program_data_items

    try:
        with stdout_to_stderr():
            items = compute_program_data_items(unit)["items"]
    except Exception as exc:  # noqa: BLE001 -- one analyzer must not sink the answer
        response.caveat(
            "analyzer-failed",
            f"byte layout could not be computed: {exc}",
            "no layout is reported for data items",
        )
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        index.setdefault(str(item["name"]).upper(), []).append(item)
    return index


def _layout_for(
    name: str,
    xref_qualified: str | None,
    layout: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """The layout item an xref entry describes, or None when it is unclear.

    xref qualifies a duplicated name as ``AMT OF OUT-REC``; the layout as
    ``OUT-REC.AMT``. Every ``OF`` qualifier must be one of the item's
    ancestors.
    """
    candidates = layout.get(name.upper(), [])
    if xref_qualified:
        qualifiers = [
            q.strip().upper() for q in xref_qualified.upper().split(" OF ")[1:]
        ]
        candidates = [
            c
            for c in candidates
            if set(qualifiers)
            <= set(str(c.get("qualified_name", "")).upper().split(".")[:-1])
        ]
    return candidates[0] if len(candidates) == 1 else None
