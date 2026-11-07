"""``impact_of_change`` (copybook member or field mode) and ``where_from``:
what a change to a copybook or a field reaches, and where a field's value
comes from."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..._lines import split_source_lines
from ..envelope import Response, ToolError, clamp_limit
from ..workspace import ParsedProgram, Workspace
from .common import BaseTools, _carry_index_caveats, _coverage, _notes


class ImpactTools(BaseTools):
    """``impact_of_change`` and ``where_from``."""

    # -- impact_of_change / where_from ---------------------------------------

    def impact_of_change(
        self,
        name: str,
        file: str | None = None,
        program: str | None = None,
        depth: int | None = None,
        limit: int | None = None,
        full_paths: bool = False,
    ) -> dict[str, Any]:
        """What a change to copybook member or field *name* reaches.

        A copybook member (or, with no *file*, any name a COPY statement
        names): every program that COPYs it, directly or through another
        member. A field: everything its value flows into, across programs.
        """
        from ...analysis.codebase import _MEMBER_SUFFIXES, _normalize_member
        from ..codebase_index import programs_index

        text = " ".join(name.split())
        if not text:
            raise ToolError("no copybook member or field name given")
        cap = clamp_limit(limit)
        suffix = Path(text).suffix.lower()
        if file is None or suffix in _MEMBER_SUFFIXES or "/" in text:
            member = _normalize_member(text)
            index = programs_index(self.workspace)
            if (
                suffix in _MEMBER_SUFFIXES
                or member in index.graph.members
                or member in index.copy_sites
            ):
                return self._copybook_impact(member, cap)
        return self._lineage(text, file, program, depth, cap, "forward", full_paths)

    def where_from(
        self,
        field: str,
        file: str | None = None,
        program: str | None = None,
        depth: int | None = None,
        limit: int | None = None,
        full_paths: bool = False,
    ) -> dict[str, Any]:
        """Where the value of *field* comes from, across programs.

        Paths shared with an earlier hit are given once (``from_hit``)
        unless *full_paths*.
        """
        text = " ".join(field.split())
        if not text:
            raise ToolError("no field name given")
        return self._lineage(
            text, file, program, depth, clamp_limit(limit), "backward", full_paths
        )

    def _copybook_impact(self, member: str, cap: int) -> dict[str, Any]:
        from ...analysis.codebase import CopybookImpactAnalyzer
        from ..codebase_index import programs_index

        index = programs_index(self.workspace)
        response = Response()
        _carry_index_caveats(index, response, "COPY statements")
        graph = index.graph
        # A PL/I %INCLUDE or an assembler COPY of the member: not in the
        # COBOL COPY graph, so listed on its own.
        included = [s for s in index.copy_sites.get(member, []) if s.get("language")]
        if included and member not in graph.members:
            return response.build(
                {
                    "name": member,
                    "kind": "copybook",
                    "found": True,
                    "program_count": len(
                        {self._unit_in(index, s["file"]) for s in included}
                    ),
                    "copied_by": [],
                    "coverage": _coverage(self.workspace, index),
                    "included_by_other_languages": response.cap(
                        self._included_rows(index, included, member),
                        cap,
                        "included_by_other_languages",
                    ),
                }
            )
        report = CopybookImpactAnalyzer(graph).analyze(member)
        if member not in graph.members:
            return response.build(
                {
                    "name": member,
                    "kind": "copybook",
                    "found": False,
                    "suggestions": difflib.get_close_matches(
                        member, graph.members, n=5
                    ),
                }
            )
        # One PROGRAM-ID can be declared in several files: keep every file,
        # so the COPY sites of one are never shown under the other.
        files: dict[str, list[str]] = {}
        for node in graph.programs:
            shown = self.workspace.display(node.path)
            if shown not in files.setdefault(node.program_id, []):
                files[node.program_id].append(shown)

        def declared(program_id: str) -> list[str | None]:
            return [*files.get(program_id, [])] or [None]

        sites_by_file: dict[str, list[dict[str, Any]]] = {}
        for site in index.copy_sites.get(member, []):
            row = {"file": site["file"], "line": site["line"]}
            how = _include_statement(self.workspace, site["file"], site["line"])
            if how is not None:
                row["statement"] = how
            sites_by_file.setdefault(site["file"], []).append(row)
        direct = []
        for program_id in report.direct_programs:
            declared_in = declared(program_id)
            for file in declared_in:
                sites = sites_by_file.get(file or "", [])
                if len(declared_in) > 1 and not sites:
                    continue
                direct.append(
                    {"program": program_id, "file": file, "copy_sites": sites}
                )
        through: dict[str, list[list[str]]] = {}
        for chain in report.chains:
            if chain and chain[0] in report.transitive_programs:
                through.setdefault(chain[0], []).append(chain)
        nested = [
            {"program": p, "file": file, "chains": through.get(p, [])}
            for p in report.transitive_programs
            for file in declared(p)
        ]
        duplicated = sorted(
            p
            for p in {*report.direct_programs, *report.transitive_programs}
            if len(files.get(p, [])) > 1
        )
        for program_id in duplicated:
            response.caveat(
                "duplicate-declaration",
                f"PROGRAM-ID {program_id} is declared in "
                f"{', '.join(files[program_id])}",
                "each file is listed on its own; a program name alone does not "
                "say which one runs",
            )
        _notes(
            response,
            "incomplete-analysis",
            [self._relative(note) for note in report.unresolved],
            "programs or fields reached only through what could not be read "
            "are missing",
        )
        return response.build(
            {
                "name": member,
                "kind": "copybook",
                "found": True,
                "resolved_to": [self.workspace.display(p) for p in report.paths],
                "program_count": report.program_count,
                "copied_by": response.cap(direct, cap, "copied_by"),
                **_statement_counts(direct),
                **self._commented_out(member, direct, response, cap),
                **_unaffected_neighbours(graph, direct, nested, self.workspace),
                "copied_through_other_members": response.cap(
                    nested, cap, "copied_through_other_members"
                ),
                "fields": response.cap(report.fields, cap, "fields"),
                "coverage": _coverage(self.workspace, index),
                **(
                    _other_language_members(
                        [self.workspace.display(p) for p in report.paths],
                        self._included_rows(index, included, member),
                        response,
                        cap,
                    )
                    if included
                    else {}
                ),
                "next": "for where one of these fields' values go, ask "
                "impact_of_change with that field and the file of a program "
                "that copies the member",
            }
        )

    def _commented_out(
        self,
        member: str,
        direct: list[dict[str, Any]],
        response: Response,
        cap: int,
    ) -> dict[str, Any]:
        """``commented_out``: programs in the copying programs' folders whose
        only COPY / INCLUDE of *member* is on a comment line. They are not
        affected, and a text search finds them, so the answer says so."""
        copying = {str(row["file"]) for row in direct if row.get("file")}
        folders = {str(Path(f).parent) for f in copying}
        pattern = re.compile(
            rf"\b(?:COPY|INCLUDE|\+\+INCLUDE|-INC)\s+['\"]?{re.escape(member)}\b",
            re.IGNORECASE,
        )
        rows = []
        for path in self.workspace.program_files():
            shown = self.workspace.display(path)
            if shown in copying or str(Path(shown).parent) not in folders:
                continue
            try:
                lines = split_source_lines(Workspace.read_text(path))
            except (ToolError, OSError):
                continue
            for number, line in enumerate(lines, 1):
                found = pattern.search(line)
                if found is None:
                    continue
                inline = line.find("*>")
                if line[6:7] in ("*", "/") or 0 <= inline < found.start():
                    rows.append({"file": shown, "line": number, "text": line.strip()})
        if not rows:
            return {}
        return {
            "commented_out": response.cap(rows, cap, "commented_out"),
            "commented_out_note": "these name the member only on a comment "
            "line: they do not copy it and need no recompile",
        }

    def _lineage(
        self,
        field: str,
        file: str | None,
        program: str | None,
        depth: int | None,
        cap: int,
        direction: str,
        full: bool = False,
    ) -> dict[str, Any]:
        from ..codebase_index import lineage_index

        if depth is not None and depth < 0:
            raise ToolError("depth must be 0 or more")
        response = Response()
        program_info = None
        programs: list[str] | None = None
        parsed: ParsedProgram | None = None
        if file is not None:
            parsed = self.workspace.program(file)
            program_info = parsed.program_info()
            if program:
                unit = parsed.unit(program, response)
                programs = [unit.program_name or ""]
                program_info = parsed.program_info(unit)
            else:
                programs = [u.program_name or "" for u in parsed.ast.program_units()]
        index = lineage_index(self.workspace)
        _carry_index_caveats(index, response, "field flows")
        if file is None and program:
            # No file, one program: the start is limited to that PROGRAM-ID
            # wherever it is declared, never silently widened to every one.
            chosen = " ".join(program.split()).upper()
            known = {str(p).upper() for p in index.graph.reports}
            if chosen not in known:
                raise ToolError(
                    f"no program under the root has PROGRAM-ID {chosen!r}"
                    + _did_you_mean(chosen, sorted(known))
                )
            programs = [chosen]
        wanted = field.upper().replace(" IN ", " OF ")
        result = index.graph.impact(wanted, programs, direction, depth)
        if not result.start_found:
            names: set[str] = set()
            for program_id, data in index.graph.reports.items():
                if programs and program_id not in {p.upper() for p in programs}:
                    continue
                for item in data.get("items") or []:
                    names.add(str(item.get("qualified_name", "")).split(".")[-1])
            missing: dict[str, Any] = {
                "field": wanted,
                "kind": "field",
                "direction": direction,
                "found": False,
                # Never the very name asked for (#546): it reads as "you
                # meant this". A wrongly qualified name still gets its bare
                # one suggested.
                "suggestions": difflib.get_close_matches(
                    wanted.split(" OF ")[0], sorted(names - {wanted}), n=5
                ),
            }
            if direction == "forward" and self._is_member(wanted, parsed):
                missing["hint"] = (
                    f"{wanted} is a copybook member, not a field: ask "
                    "impact_of_change with it and no file for the programs "
                    "that copy it"
                )
            return response.build(missing, program_info)

        hits = [_hit(hit, index, self.workspace, response) for hit in result.hits]
        hits.sort(
            key=lambda h: (
                _CONFIDENCE_RANK.get(h["confidence"], 9),
                "may_be_overwritten" in h,
                len(h["path"]),
            )
        )
        shown = response.cap(hits, cap, "hits")
        ends = _trail_ends(hits)
        if not full:
            _share_paths(shown)
        reached = set(result.programs) | {p.upper() for p in programs or []}
        for caveat in result.caveats:
            if caveat in result.ambiguous:
                response.caveat(
                    "ambiguous-name",
                    caveat,
                    "every matching field is traced; qualify the name (X OF Y) "
                    "to ask about one of them",
                )
                continue
            response.caveat(
                "incomplete-analysis",
                caveat,
                "a flow past this point is assumed or unknown",
            )
        unjoined = [
            u for u in index.graph.unjoined if u.split(":", 1)[0].upper() in reached
        ]
        if unjoined:
            how = index.jcl_note or (
                "no JCL under the root binds them"
                if not index.jcl_files
                else "the JCL under the root does not bind them"
            )
            _notes(
                response,
                "incomplete-analysis",
                [f"{u} ({how})" for u in unjoined],
                "a flow through these files stops at the program boundary",
            )
        elif index.jcl_note:
            response.caveat("incomplete-analysis", index.jcl_note)
        _notes(
            response,
            "incomplete-analysis",
            [self._relative(p) for p in index.problems],
            "flows through these programs or jobs are missing",
        )
        answer: dict[str, Any] = {
            "field": wanted,
            "kind": "field",
            "direction": direction,
            "found": True,
            "depth": depth,
            "programs": result.programs,
            "tables": result.tables,
            "datasets": result.datasets,
            "hit_count": len(hits),
            "by_confidence": _counts(h["confidence"] for h in hits),
            "may_be_overwritten": sum("may_be_overwritten" in h for h in hits),
            "trail_ends": response.cap(ends, cap, "trail_ends"),
            "hits": shown,
            "notes": list(result.notes),
            "legend": (
                "each hit is a field (or a table column, a dataset byte range, "
                "or the port where a trail ends) with its path from the start, "
                "one step per line; exact hits first. location is the "
                "statement that reaches it (null for a join through a dataset, "
                "table or CALL); derived: the value is computed on the way, "
                "not only copied. may_be_overwritten: a statement replaces "
                "the value on the way, in the same paragraph, before the path "
                "reads it again (a SELECT INTO finding no row or a READ INTO "
                "at end of file would not); such hits come after the others "
                "of their confidence. trail_ends: the hits no other trail runs "
                "through (the "
                + ("ultimate sources" if direction == "backward" else "final receivers")
                + ")."
                + (
                    ""
                    if full
                    else " A hit with from_hit continues hit number from_hit "
                    "(0-based): its path starts with that hit's first "
                    "after_step steps, and only the rest is listed."
                )
            ),
        }
        return response.build(answer, program_info)

    @staticmethod
    def _unit_in(index: Any, file: str) -> str:
        """The program declared in *file* (a PL/I or assembler source)."""
        return next((u.program_id for u in index.units if u.file == file), file)

    def _included_rows(
        self, index: Any, sites: list[dict[str, Any]], member: str
    ) -> list[dict[str, Any]]:
        """One row per PL/I or assembler program including a member, with
        the files under the root that member could be for its language (a
        PL/I ``.inc`` is not the COBOL ``.cpy`` of the same name)."""
        from ..languages import member_files

        rows: dict[str, dict[str, Any]] = {}
        found: dict[str, list[str]] = {}
        for site in sites:
            language = site["language"]
            if language not in found:
                found[language] = member_files(self.workspace, language, member)
            row = rows.setdefault(
                site["file"],
                {
                    "program": self._unit_in(index, site["file"]),
                    "file": site["file"],
                    "language": language,
                    "member_files": found[language],
                    "include_sites": [],
                },
            )
            if site.get("line"):
                row["include_sites"].append(
                    {"file": site["file"], "line": site["line"]}
                )
        return list(rows.values())

    def _is_member(self, name: str, parsed: ParsedProgram | None) -> bool:
        """Whether *name* is a copybook member: one *parsed* expanded, or one
        the programs index (only when already built) saw a COPY name."""
        from ...analysis.codebase import _normalize_member

        member = _normalize_member(name)
        if not member or " " in member:
            return False
        if parsed is not None and parsed.source_map:
            expanded = {Path(f).stem.upper() for f, _ in parsed.source_map.values()}
            if member in expanded - {parsed.path.stem.upper()}:
                return True
        built = self.workspace.built_index("programs")
        return built is not None and member in built.graph.members


_INCLUDE_WORD = re.compile(r"(?<![\w-])(COPY|INCLUDE|\+\+INCLUDE|-INC)(?![\w-])", re.I)


def _include_statement(workspace: Workspace, file: str, line: int) -> str | None:
    """How the program at *file*:*line* brings a member in: ``COPY``, or
    ``EXEC SQL INCLUDE`` (which the DB2 precompiler expands, not the
    compiler). None when the line cannot be read."""
    try:
        lines = split_source_lines(Workspace.read_text(workspace.resolve(file)))
    except (ToolError, OSError):
        return None
    if not 0 < line <= len(lines):
        return None
    # The site is the statement's first line: EXEC SQL may stand alone
    # with INCLUDE on the next.
    text = " ".join(lines[line - 1 : line + 2])
    found = _INCLUDE_WORD.search(text)
    if found is None:
        return None
    word = found.group(1).upper()
    if word != "INCLUDE":
        return word
    before = " ".join(lines[max(0, line - 3) : line - 1]) + " " + text[: found.start()]
    return "EXEC SQL INCLUDE" if re.search(r"\bSQL\b", before, re.I) else word


def _statement_counts(direct: list[dict[str, Any]]) -> dict[str, Any]:
    """``brought_in_by``: programs per statement kind, when the member is
    both COPYed and EXEC SQL INCLUDEd (only the INCLUDEs need the DB2
    precompile)."""
    by: dict[str, list[str]] = {}
    for row in direct:
        for site in row["copy_sites"]:
            kind = site.get("statement")
            if kind and row["program"] not in by.setdefault(kind, []):
                by[kind].append(row["program"])
    if len(by) < 2:
        return {}
    return {
        "brought_in_by": {k: {"count": len(v), "programs": v} for k, v in by.items()}
    }


def _other_language_members(
    resolved: list[str],
    rows: list[dict[str, Any]],
    response: Response,
    cap: int,
) -> dict[str, Any]:
    """``included_by_other_languages`` and, when those programs include
    their own file of the member, ``member_files_to_change``: every file
    that spells the layout. A copybook and a PL/I or assembler include
    of the same name are separate files, so a change is made in each."""
    out: dict[str, Any] = {
        "included_by_other_languages": response.cap(
            rows, cap, "included_by_other_languages"
        )
    }
    others = [f for r in rows for f in r.get("member_files", []) if f not in resolved]
    if others:
        out["member_files_to_change"] = {
            "files": list(dict.fromkeys([*resolved, *others])),
            "note": "each language includes its own file of this member: a "
            "layout change has to be made in every one of them",
        }
    return out


_NEIGHBOURS_SHOWN = 25


def _unaffected_neighbours(
    graph: Any,
    direct: list[dict[str, Any]],
    nested: list[dict[str, Any]],
    workspace: Workspace,
) -> dict[str, Any]:
    """``not_affected``: the programs that share a folder with the ones that
    copy the member but do not copy it, directly or through another member.
    "Which must be recompiled" is half an answer without the ones that need
    not be, and the folder is where a reader would look for them."""
    affected = {str(r["file"]) for r in [*direct, *nested] if r.get("file")}
    folders = {str(Path(f).parent) for f in affected}
    names: set[str] = set()
    for node in graph.programs:
        shown = workspace.display(node.path)
        if shown not in affected and str(Path(shown).parent) in folders:
            names.add(node.program_id)
    names -= {str(r["program"]) for r in [*direct, *nested]}
    if not names:
        return {}
    shown_names = sorted(names)[:_NEIGHBOURS_SHOWN]
    return {
        "not_affected": {
            "count": len(names),
            "programs": shown_names,
            "folders": sorted(folders),
            "note": "programs in the same folders that do not copy the member, "
            "directly or through another: no recompile; name them when the "
            "question asks which must be recompiled",
        }
    }


def _did_you_mean(wanted: str, names: list[str]) -> str:
    """`` (did you mean X, Y?)`` for an error message, or ``""``."""
    close = difflib.get_close_matches(wanted, names, n=3)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def _hit(
    hit: Any, index: Any, workspace: Workspace, response: Response
) -> dict[str, Any]:
    """One lineage hit: where the value arrives, and the steps between.

    Each step is one line of text naming the node, the statement and its
    ``file:line``: a path can run to a dozen steps, and fifty hits of
    nested objects would spend a model's context on punctuation.
    """
    steps = []
    arrived: dict[str, Any] | None = None
    for hop in hit.path:
        location = _hop_location(hop, index, response, workspace)
        how = hop.statement or hop.kind
        if location is not None:
            how += f" at {location['file']}:{location['line']}"
        if hop.confidence != "exact":
            how += f", {hop.confidence}"
        steps.append(f"{hop.label} ({how})")
        arrived = location
    entry: dict[str, Any] = {
        "program": hit.program,
        "field": hit.field,
        "node_kind": hit.node_kind,
        "derived": hit.derived,
        "confidence": hit.confidence,
    }
    if hit.program:
        entry["file"] = index.program_files.get(hit.program.upper())
    entry["location"] = arrived
    entry["path"] = steps
    overwritten = []
    for kill in getattr(hit, "overwritten", ()):
        if kill.origin_file:
            file = workspace.display(kill.origin_file)
        else:
            file = index.program_files.get(kill.program.upper())
        where = f" at {file}:{kill.line}" if file else ""
        overwritten.append(f"{kill.field} by {kill.statement}{where}")
    if overwritten:
        entry["may_be_overwritten"] = overwritten
    return entry


#: Hits are listed most certain first.
_CONFIDENCE_RANK = {"exact": 0, "overlap": 1, "candidate": 2, "opaque": 3}


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _step_node(step: str) -> str:
    """The node a ``NODE (STATEMENT at file:line)`` step names."""
    return step.split(" (", 1)[0]


def _trail_ends(hits: list[dict[str, Any]]) -> list[str]:
    """The hits no other hit's trail passes through: where each trail
    really ends, rather than every field on the way."""
    passed: set[str] = set()
    for hit in hits:
        passed.update(_step_node(step) for step in hit["path"][:-1])
    ends: list[str] = []
    for hit in hits:
        if not hit["path"]:
            continue
        node = _step_node(hit["path"][-1])
        if node not in passed and node not in ends:
            ends.append(node)
    return ends


def _share_paths(hits: list[dict[str, Any]]) -> None:
    """Shorten each hit's ``path`` to what it adds to an earlier hit's.

    A backward trail through three programs reaches a dozen fields, each
    hit repeating every step before it; the repeats were most of a 40 KB
    answer. A hit whose path begins with at least two steps of an earlier
    one names it (``from_hit``, ``after_step``) and lists only the rest.
    """
    full = [list(h["path"]) for h in hits]
    for i, hit in enumerate(hits):
        best, best_len = None, 1
        for j in range(i):
            common = 0
            for a, b in zip(full[i], full[j], strict=False):
                if a != b:
                    break
                common += 1
            if common > best_len:
                best, best_len = j, common
        if best is not None:
            hit["from_hit"] = best
            hit["after_step"] = best_len
            hit["path"] = full[i][best_len:]


def _hop_location(
    hop: Any, index: Any, response: Response, workspace: Workspace
) -> dict[str, Any] | None:
    """Where one hop's statement is, or None for a join (no line of its own)."""
    if not hop.line or not hop.program:
        return None
    program = hop.program.upper()
    origin = getattr(hop, "origin_file", None)
    if origin:
        # The hop's own edge says which file its line is in (#489): a
        # copybook line and a program line of one number never collide.
        return {"file": workspace.display(origin), "line": hop.line}
    key = (program, hop.line, hop.kind, hop.statement)
    file = index.edge_files.get(key)
    if file is None and key not in index.edge_files and program not in index.expanded:
        file = index.program_files.get(program)
    if file is None:
        response.caveat(
            "unmapped-location",
            "some locations could not be traced back to a file on disk "
            "and are reported as null",
        )
        return None
    return {"file": file, "line": hop.line}
