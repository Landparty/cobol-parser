"""The MCP prompts: ready-made requests that chain the tools.

A client without skills still gets the same working method the
``cobol-analysis`` skill teaches -- run the tool, cite ``file:line``, carry
the caveats -- as a prompt the user picks from a menu. Each prompt is a plain
function returning the request text, so, like :mod:`.tools`, this module
imports no SDK; :mod:`.server` registers every entry of :data:`PROMPTS`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

#: What every prompt asks of the answer, whatever the task.
_METHOD = """
Work from the cobol tools, not from reading the source by eye: COBOL
programs are long, their meaning is spread across copybooks, and byte
layouts are easy to get wrong. Cite every fact as file:line from the tool
results (read_source shows the code behind a citation). Read each result's
caveats: when one says something could not be checked, say so in the
answer rather than presenting it as complete. When a list is truncated,
narrow the question or raise limit instead of assuming you saw everything.
"""


def _program(file: str, program: str | None) -> str:
    return f"{file} (program unit {program})" if program else file


def explain_program(file: str, program: str | None = None) -> str:
    """Explain what a COBOL program does, for someone new to it."""
    target = _program(file, program)
    return f"""Explain what the COBOL program in {target} does, for a developer
who has never seen it.

1. Call program_brief on it: what it is, its calling interface, the files,
   tables and programs it touches, its health.
2. Call business_rules on it for the decisions, validations and
   calculations it implements; the rule ids let you refer to them.
3. For any data name that matters to the explanation, call explain_symbol;
   for a paragraph whose role is unclear, callers_of.

Answer with: its purpose in two or three sentences; its inputs and outputs
(files, tables, CALL parameters); its main processing steps in order, by
paragraph; its key business rules; and anything the caveats say could not
be checked.
{_METHOD}"""


def review_program(file: str, program: str | None = None) -> str:
    """Review a COBOL program for defects and risky code."""
    target = _program(file, program)
    return f"""Review the COBOL program in {target} for defects and risks.

1. Call lint on it (min_severity "warning" first; "info" if that is quiet).
2. Call program_brief for its health grade, unreachable paragraphs and
   PERFORM cycles.
3. For each finding worth raising, call read_source at its location to
   confirm it in context, and explain_symbol on any data item it names.

Report the findings worst first, each with file:line, what is wrong, why it
matters at run time, and a suggested fix. Separate confirmed defects from
style or maintainability notes, and list what the caveats say was not
checked.
{_METHOD}"""


def plan_change(name: str, file: str | None = None) -> str:
    """Find everything a change to a field or copybook would reach."""
    where = f" (declared in {file})" if file else ""
    file_arg = f', file="{file}"' if file else ""
    return f"""I want to change {name}{where}. Find everything the change reaches
before I make it.

1. Call impact_of_change with name="{name}"{file_arg}. For a copybook it
   lists every program that COPYs it; for a field, everything its value
   flows into, across programs, files, CALLs and DB2 columns.
2. Call where_from for the field (if it is one) to see what feeds it.
3. For each affected program, call explain_symbol on the field to see how
   it is used (read, written, tested), and record_layout when its byte
   position or length is what is changing.

Answer with: the programs, files, tables and fields affected, each with
file:line; which of them must change too and which only need retesting;
and the risks (byte offsets that shift, REDEFINES over the field, values
tested by level-88 names). Say plainly where a caveat means the list may be
incomplete -- an unbound dataset, an unresolved copybook, a dynamic CALL.
{_METHOD}"""


def document_business_rules(file: str, program: str | None = None) -> str:
    """Write the business rules a COBOL program implements as plain prose."""
    target = _program(file, program)
    return f"""Write down the business rules the COBOL program in {target}
implements, for a business analyst who does not read COBOL.

1. Call business_rules on it (and again with kind="validation" if the list
   is long). Each rule is a decision table: one branch per condition, with
   the actions it takes.
2. Translate level-88 condition names using the condition_names list, and
   call explain_symbol on any field whose meaning the rule depends on.

Write one entry per rule: its id, a one-line name, the rule in plain
language ("When ... then ..., otherwise ..."), the fields it reads and
writes, and its file:line. Group them by kind (validations, decisions,
calculations). Mark rules in dead code as such.
{_METHOD}"""


def onboard_codebase() -> str:
    """Give an overview of a whole COBOL codebase."""
    return f"""Give me an overview of the COBOL codebase in this workspace.

1. Call codebase_overview: every program with its health grade, the call
   graph's entry programs and most-called programs, missing programs and
   copybooks, and code duplicated between programs.
2. Call program_brief on two or three entry programs, and on the
   most-called ones, to say what they do.

Answer with: what the system appears to do; its entry points (batch jobs,
transactions) and the main call chains; the most important shared
copybooks; and where the risk is (worst health grades, missing members,
duplicated code, call cycles).
{_METHOD}"""


@dataclass(frozen=True)
class PromptSpec:
    """One prompt as the server registers it."""

    name: str
    function: Callable[..., str]

    @property
    def description(self) -> str:
        return (self.function.__doc__ or "").strip()


#: Every prompt the server offers.
PROMPTS: tuple[PromptSpec, ...] = (
    PromptSpec("explain_program", explain_program),
    PromptSpec("review_program", review_program),
    PromptSpec("plan_change", plan_change),
    PromptSpec("document_business_rules", document_business_rules),
    PromptSpec("onboard_codebase", onboard_codebase),
)
