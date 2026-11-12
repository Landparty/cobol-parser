"""What the tool modules share: :class:`BaseTools` (the workspace, path
display, the other-language dispatch) and the envelope, caveat and analyzer
helpers more than one tool calls (:func:`_attempt`, :func:`_notes`,
:func:`_carry_parse_caveats`, :func:`_carry_index_caveats`, ...)."""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from ...models.program import CobolProgram
from ..envelope import Response, ToolError
from ..workspace import ParsedProgram, Workspace, stdout_to_stderr

#: Notes named one by one in a caveat that summarizes many.
NOTES_SHOWN = 5


#: Flow edges that CALL another program rather than run a procedure.
_CALL_EDGES = frozenset({"CALL", "CALL_DYNAMIC"})


#: Flow edges that hand control to a paragraph or section. IF/EVALUATE
#: edges are the graph's own branch scaffolding, never a caller.
_CONTROL_EDGES = frozenset(
    {
        "PERFORM",
        "PERFORM_THRU",
        "GOTO",
        "GOTO_DEPENDING",
        "SORT_INPUT_PROCEDURE",
        "SORT_INPUT_PROCEDURE_THRU",
        "SORT_OUTPUT_PROCEDURE",
        "SORT_OUTPUT_PROCEDURE_THRU",
        "MERGE_OUTPUT_PROCEDURE",
        "MERGE_OUTPUT_PROCEDURE_THRU",
        "XML_PROCESSING_PROCEDURE",
        "XML_PROCESSING_PROCEDURE_THRU",
        "CICS_HANDLE",
        "SQL_WHENEVER",
        "ALTER",
        "FALL_THROUGH",
    }
)


def _with_site_settings(method: Callable[..., Any]) -> Callable[..., Any]:
    """*method* run under its workspace's :meth:`Workspace.site_settings`."""

    @functools.wraps(method)
    def tool(self: BaseTools, *args: Any, **kwargs: Any) -> Any:
        with self.workspace.site_settings():
            return method(self, *args, **kwargs)

    return tool


class BaseTools:
    """The workspace every tool reads, and the helpers several tools share.

    Every public method a subclass defines (a tool) runs under the
    workspace's :meth:`~..workspace.Workspace.site_settings`, so ``cobol.yml``
    settings that are process-wide in the analyzers (``abend_programs``)
    apply to a tool called straight from Python as to one the server calls.
    """

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, value in list(vars(cls).items()):
            if not name.startswith("_") and callable(value):
                setattr(cls, name, _with_site_settings(value))

    # -- PL/I and assembler ---------------------------------------------------

    def _other_language_path(self, file: str) -> Path | None:
        """*file*'s path when it is a PL/I or assembler source, else None."""
        from ..languages import language_of

        if language_of(file) is None:
            return None
        path = self.workspace.resolve(file)
        if path.suffix.lower() in self.workspace._program_suffixes():
            return None
        return path

    def _relative(self, text: str) -> str:
        """*text* (a library note) with the root's absolute path cut, so it
        names files the way every location does."""
        return text.replace(f"{self.workspace.root.as_posix()}/", "")


_T = TypeVar("_T")


def _attempt(response: Response, what: str, build: Callable[[], _T]) -> _T | None:
    """*build()*, or None with an ``analyzer-failed`` caveat when it raises.

    A brief joins several analyzers; one that fails must not sink the rest.
    """
    try:
        with stdout_to_stderr():
            return build()
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
        response.caveat(
            "analyzer-failed",
            f"{what} could not be analyzed: {exc}",
            f"the answer has no {what} section",
        )
        return None


def _flow(parsed: ParsedProgram, unit: CobolProgram) -> Any:
    return parsed.flow(unit)


@dataclass(frozen=True)
class _Reachability:
    """Which procedures of a unit can run, and which fall-throughs happen."""

    #: Procedure keys (``X OF S`` when the name repeats) control never reaches.
    unreachable: list[str]
    #: Upper-cased ``(from, to)`` keys of the fall-throughs that can happen.
    fall_throughs: frozenset[tuple[str, str]]


def _reachability(
    parsed: ParsedProgram, unit: CobolProgram, response: Response
) -> _Reachability | None:
    """DeadCodeAnalyzer's reachability for *unit*, memoized beside the parse.

    The root-based fixpoint the OKF calls authoritative (issue #486), rather
    than ``ProgramFlowAnalyzer.unreachable_nodes``. None, with an
    ``analyzer-failed`` caveat, when the analyzer raises: callers then fall
    back to the flow graph's answer.
    """
    from ...analysis.dead_code import DeadCodeAnalyzer

    def build() -> _Reachability:
        report = DeadCodeAnalyzer().analyze(unit)
        return _Reachability(
            unreachable=[
                item.qualified_name or item.name for item in report.dead_items
            ],
            fall_throughs=frozenset(
                (source.upper(), target.upper())
                for source, target in report.fall_through_edges
            ),
        )

    return _attempt(
        response,
        "reachability",
        lambda: parsed.report("reachability", unit, build),
    )


def _crud(parsed: ParsedProgram, unit: CobolProgram) -> Any:
    from ...analysis.crud_matrix import CRUDMatrixGenerator

    return parsed.report("crud", unit, lambda: CRUDMatrixGenerator().analyze(unit))


def _file_facts(parsed: ParsedProgram, unit: CobolProgram) -> dict[str, Any]:
    """Every FD/SD's facts (organization, keys, records), by upper-cased name."""
    from ...layout.program import ProgramLayoutIndex

    def build() -> dict[str, Any]:
        index = ProgramLayoutIndex.build(unit)
        facts: dict[str, Any] = {}
        for name in index.file_names():
            fact = index.file_facts(name)
            if fact is not None:
                facts[name.upper()] = fact
        return facts

    result: dict[str, Any] = parsed.report("file-facts", unit, build)
    return result


def _label_runs_as(
    workspace: Workspace,
    answer: dict[str, Any],
    rows: list[dict[str, Any]],
    response: Response,
) -> None:
    """Each row's ``runs_as`` (online (CICS), batch, IMS) and, once per
    program, why: so "the batch layer" is not read off a program's name."""
    from ..codebase_index import RunsAs

    labels = _attempt(response, "online or batch", lambda: RunsAs(workspace))
    if labels is None:
        return
    evidence: dict[str, str] = {}
    for row in rows:
        program = str(row.get("program") or "")
        found = labels.of(program) if program else None
        if found is None:
            continue
        row["runs_as"] = found["runs_as"]
        evidence.setdefault(program, found["because"])
    if evidence:
        answer["runs_as_because"] = evidence


def _worth_showing(value: Any) -> bool:
    """A layout value that says something: not absent, empty or ``False``.

    ``byte_offset`` 0 is information; ``0 in (None, [], False)`` is True.
    """
    return value is not None and value is not False and value != []


def _carry_index_caveats(
    index: Any, response: Response, what: str, files: set[str] | None = None
) -> None:
    """A root-wide index's gaps, as a few caveats rather than one per file;
    with *files*, only the gaps in those files."""
    failed = {f: why for f, why in index.failed.items() if files is None or f in files}
    if failed:
        _notes(
            response,
            "incomplete-analysis",
            [f"{file}: {why}" for file, why in sorted(failed.items())],
            f"{what} in the program files that could not be parsed are missing",
            lead=f"{len(failed)} program file(s) could not be parsed",
        )
    by_kind: dict[str, list[str]] = {}
    for file, caveats in sorted(index.file_caveats.items()):
        if files is not None and file not in files:
            continue
        for caveat in caveats:
            by_kind.setdefault(caveat.kind, []).append(file)
    effects = {
        "partial-parse": f"{what} in the statements that did not parse are missing",
        "unresolved-copybook": f"{what} in the members that were not expanded "
        "are missing",
        "analyzer-failed": f"{what} from those files are missing",
    }
    for kind, effect in effects.items():
        named = sorted(set(by_kind.get(kind, [])))
        if named:
            response.caveat(
                kind,
                f"{len(named)} program file(s): {_listed(named)}",
                effect,
            )


def _coverage(workspace: Workspace, index: Any) -> dict[str, Any]:
    """What a root-wide answer looked through: the source files read, by
    language, and the sources under the root no parser here reads. So an
    empty or short list can be taken at its word, or not."""
    read: dict[str, set[str]] = {}
    for unit in index.units:
        if unit.language != "COBOL":
            read.setdefault(unit.language, set()).add(unit.file)
    others = set().union(*read.values()) if read else set()
    read["COBOL"] = set(index.files) - others
    out: dict[str, Any] = {
        "files_read": {lang: len(files) for lang, files in sorted(read.items())}
    }
    skipped: dict[str, set[str]] = {}
    for entries in workspace.other_sources().values():
        for path, language in entries:
            skipped.setdefault(language, set()).add(str(path))
    if skipped:
        out["files_not_analyzed"] = {
            lang: len(paths) for lang, paths in sorted(skipped.items())
        }
    if index.failed:
        out["files_failed"] = len(index.failed)
    return out


def _notes(
    response: Response,
    kind: str,
    notes: list[str],
    effect: str,
    lead: str | None = None,
) -> None:
    """Many notes as one caveat: the first few in full, then a count."""
    if not notes:
        return
    detail = _listed(notes, separator="; ")
    response.caveat(kind, f"{lead}: {detail}" if lead else detail, effect)


def _declared_elsewhere(
    answer: dict[str, Any],
    parsed: ParsedProgram,
    unit: CobolProgram,
    declares: Callable[[CobolProgram], bool],
) -> None:
    """Name the other program units of *parsed* that *declares*, on a
    not-found *answer* about *unit*.

    A tool answers about one unit (the outermost by default), so a name
    declared only in a nested or stacked program reads as missing; the
    answer says where it is rather than leave "not found" to stand.
    """
    others = []
    for other in parsed.ast.program_units():
        if other is unit:
            continue
        try:
            with stdout_to_stderr():
                found = declares(other)
        except Exception:  # noqa: BLE001 -- only a hint; never fail the answer
            continue
        if found:
            others.append(other.program_name or "<unnamed>")
    if others:
        answer["declared_in_program_units"] = others
        answer["hint"] = (
            f"not in {unit.program_name or '<unnamed>'}, but declared in "
            f"{', '.join(others)} of this file: pass program= to ask about it"
        )


def _degraded_declaration(
    answer: dict[str, Any], parsed: ParsedProgram, name: str
) -> None:
    """On a not-found or undeclared *answer*, name the COPY member that
    declares *name* on disk but that the parse read badly, so "not
    declared" is not taken at its word."""
    member = parsed.degraded_names.get(name.split(" OF ")[0].split(" IN ")[0].strip())
    if member is None:
        return
    answer["declared_in_degraded_copybook"] = member
    answer.setdefault(
        "hint",
        f"{member} declares {name}, but the parse read that member badly "
        "(see caveats): this answer does not see the declaration",
    )


def _listed(items: list[str], separator: str = ", ") -> str:
    shown = separator.join(items[:NOTES_SHOWN])
    if len(items) > NOTES_SHOWN:
        shown += f"{separator}and {len(items) - NOTES_SHOWN} more"
    return shown


def _carry_parse_caveats(parsed: ParsedProgram, response: Response) -> None:
    for caveat in parsed.caveats:
        response.caveat(caveat.kind, caveat.detail, caveat.effect)
