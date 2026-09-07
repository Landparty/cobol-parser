"""Call signatures for IBM Language Environment services and COBOL intrinsics.

``ibm_enterprise.py`` answers *"is this name an LE callable service?"*.  This
module answers the next question, the one a developer standing in front of a
``CALL "CEEDAYS"`` actually has: **what has to be declared, in what order, and
which of those parameters am I allowed to leave out?**

Two catalogues, because LE presents two different things under one banner:

* :data:`LE_SERVICE_SIGNATURES` — the ``CEExxxx`` callable services, invoked
  with ``CALL "CEExxxx" USING ...``.  Every parameter is a data item the
  caller must declare with an exact picture; getting one wrong is a runtime
  problem, not a compile-time one, which is why the declarations are carried
  here verbatim rather than described in prose.
* :data:`INTRINSIC_FUNCTION_SIGNATURES` — the ``FUNCTION xxx(...)``
  intrinsics, whose arguments are positional and whose return category
  decides what you are allowed to MOVE the result into.

**Coverage is deliberately partial and says so.**  A signature is present
only where it is known exactly.  ``IBMEnterpriseCobol.IBM_LE_CALLABLE_SERVICES``
recognises more service names than this module has signatures for, and
:func:`services_without_signature` reports exactly which ones — a consumer
showing this catalogue to a user can then say "known service, signature not
catalogued" instead of quietly showing nothing, or worse, guessing a
parameter list.

Sources: *z/OS Language Environment Programming Reference* (SA38-0683) for
the callable services, and *Enterprise COBOL for z/OS Language Reference* for
the intrinsic functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Bumped when the shape of the dicts below changes, not when an entry is
# added -- a consumer that pins on it (the VS Code extension's hover) is
# pinning on the shape.
CATALOG_VERSION = 1

_REFERENCE = "z/OS Language Environment Programming Reference (SA38-0683)"

IN = "input"
OUT = "output"
INOUT = "input/output"


# ── Parameter data types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class LEDataType:
    """How one LE parameter has to be declared in the caller's storage.

    Attributes:
        id:           Stable identifier used by :class:`LEParameter`.
        declaration:  One-line COBOL declaration, as it would be written on
                      an elementary item (``PIC S9(9) COMP``).
        byte_length:  Size of the item in bytes, or ``None`` when the type is
                      a family rather than one fixed width.
        snippet:      A full WORKING-STORAGE entry, for the parameters that
                      are *structures* rather than elementary items (the
                      feedback code and the halfword-prefixed strings).  A
                      one-line ``declaration`` cannot express those, and they
                      are exactly the two shapes people get wrong.
        description:  What the item means, in one sentence.
    """

    id: str
    declaration: str
    byte_length: int | None
    description: str
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "declaration": self.declaration,
            "byte_length": self.byte_length,
            "description": self.description,
            "snippet": self.snippet,
        }


_FEEDBACK_SNIPPET = """01  FC.
    05  FC-SEVERITY       PIC S9(4) COMP.
    05  FC-MSG-NO         PIC S9(4) COMP.
    05  FC-CASE-SEV-CTL   PIC X.
    05  FC-FACILITY-ID    PIC XXX.
    05  FC-I-S-INFO       PIC S9(9) COMP."""

_VSTRING_SNIPPET = """01  LE-STRING.
    05  LE-STRING-LENGTH  PIC S9(4) COMP.
    05  LE-STRING-TEXT    PIC X(80)."""

LE_DATA_TYPES: dict[str, LEDataType] = {
    t.id: t
    for t in (
        LEDataType(
            id="int32",
            declaration="PIC S9(9) COMP",
            byte_length=4,
            description="Fullword binary integer (COMP / BINARY).",
        ),
        LEDataType(
            id="int16",
            declaration="PIC S9(4) COMP",
            byte_length=2,
            description="Halfword binary integer (COMP / BINARY).",
        ),
        LEDataType(
            id="float64",
            declaration="COMP-2",
            byte_length=8,
            description=(
                "Long (64-bit) floating point -- how LE carries Lilian " "seconds."
            ),
        ),
        LEDataType(
            id="vstring",
            declaration="halfword length + PIC X(n) text",
            byte_length=None,
            description=(
                "A length-prefixed string: a PIC S9(4) COMP character count "
                "followed by the text itself. Passing a plain PIC X(n) here "
                "is the single most common LE calling mistake -- the service "
                "reads the first two bytes as the length."
            ),
            snippet=_VSTRING_SNIPPET,
        ),
        LEDataType(
            id="char17",
            declaration="PIC X(17)",
            byte_length=17,
            description="Gregorian character string, YYYYMMDDHHMMSSTTT.",
        ),
        LEDataType(
            id="char80",
            declaration="PIC X(80)",
            byte_length=80,
            description="Fixed 80-character field, blank padded.",
        ),
        LEDataType(
            id="pointer",
            declaration="USAGE POINTER",
            byte_length=4,
            description="Address of a storage area.",
        ),
        LEDataType(
            id="procedure-pointer",
            declaration="USAGE PROCEDURE-POINTER",
            byte_length=8,
            description="Address of an entry point, SET from a program name.",
        ),
        LEDataType(
            id="feedback",
            declaration="12-byte condition token",
            byte_length=12,
            description=(
                "The feedback code every service reports its outcome in. "
                "Severity 0 means success. Omit the argument entirely (or "
                "pass OMITTED) and LE signals the condition instead of "
                "returning it -- which for a nonzero severity means your "
                "program ends rather than reads a return code."
            ),
            snippet=_FEEDBACK_SNIPPET,
        ),
        LEDataType(
            id="record",
            declaration="a record area (group item)",
            byte_length=None,
            description="A group item whose layout the callee defines.",
        ),
    )
}


# ── Callable-service signatures ───────────────────────────────────────────────


@dataclass(frozen=True)
class LEParameter:
    """One operand of a ``CALL "CEExxxx" USING ...`` statement.

    Attributes:
        name:        The parameter's name in the LE reference.
        direction:   ``input`` (the caller fills it in), ``output`` (the
                     service does), or ``input/output``.
        type_id:     Key into :data:`LE_DATA_TYPES`.
        description: What this operand carries.
        optional:    True when the argument may be omitted. In practice this
                     is the feedback code, and omitting it changes behaviour
                     rather than merely dropping a value -- see the
                     ``feedback`` data type.
        repeats:     True when the argument may appear more than once at the
                     end of the USING list (DL/I SSAs).
    """

    name: str
    direction: str
    type_id: str
    description: str
    optional: bool = False
    repeats: bool = False

    @property
    def data_type(self) -> LEDataType:
        return LE_DATA_TYPES[self.type_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction,
            "optional": self.optional,
            "repeats": self.repeats,
            "description": self.description,
            "type": self.data_type.to_dict(),
        }


@dataclass(frozen=True)
class LEServiceSignature:
    """The full call shape of one IBM LE callable service."""

    name: str
    category: str
    summary: str
    parameters: tuple[LEParameter, ...]
    notes: tuple[str, ...] = ()
    reference: str = _REFERENCE

    @property
    def required_parameters(self) -> tuple[LEParameter, ...]:
        """The operands that must be present, in order."""
        return tuple(p for p in self.parameters if not p.optional)

    def call_example(self) -> str:
        """A ``CALL`` statement in the service's own parameter names."""
        operands = ", ".join(
            f"{p.name}..." if p.repeats else p.name for p in self.parameters
        )
        return f'CALL "{self.name}" USING {operands}'

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "service",
            "category": self.category,
            "summary": self.summary,
            "parameters": [p.to_dict() for p in self.parameters],
            "required_count": len(self.required_parameters),
            "call_example": self.call_example(),
            "notes": list(self.notes),
            "reference": self.reference,
        }


def _fc(optional: bool = True) -> LEParameter:
    return LEParameter(
        name="fc",
        direction=OUT,
        type_id="feedback",
        description="Feedback code reporting the outcome of the call.",
        optional=optional,
    )


_OMITTED_FC_NOTE = (
    "fc may be omitted. If it is, an unsuccessful call is signalled as an "
    "LE condition rather than returned -- the caller never sees it."
)

_LILIAN_NOTE = (
    "A Lilian date is the number of days since 14 October 1582; Lilian "
    "seconds count from midnight 14 October 1582."
)


def _service(
    name: str,
    category: str,
    summary: str,
    parameters: tuple[LEParameter, ...],
    notes: tuple[str, ...] = (),
) -> LEServiceSignature:
    has_optional_fc = any(p.name == "fc" and p.optional for p in parameters)
    all_notes = (*notes, _OMITTED_FC_NOTE) if has_optional_fc else notes
    return LEServiceSignature(
        name=name,
        category=category,
        summary=summary,
        parameters=parameters,
        notes=all_notes,
    )


_SIGNATURES: tuple[LEServiceSignature, ...] = (
    # ── Date and time ────────────────────────────────────────────────────────
    _service(
        "CEEDAYS",
        "datetime",
        "Convert a character date to a Lilian date",
        (
            LEParameter(
                "input_char_date",
                IN,
                "vstring",
                "The date to convert, matching picture_string.",
            ),
            LEParameter(
                "picture_string",
                IN,
                "vstring",
                'How input_char_date is laid out, e.g. "YYYYMMDD" or ' '"MM/DD/YY".',
            ),
            LEParameter(
                "output_Lilian",
                OUT,
                "int32",
                "The converted date, as a Lilian day number.",
            ),
            _fc(),
        ),
        notes=(_LILIAN_NOTE,),
    ),
    _service(
        "CEECBLDY",
        "datetime",
        "Convert a character date to a COBOL integer date",
        (
            LEParameter(
                "input_char_date",
                IN,
                "vstring",
                "The date to convert, matching picture_string.",
            ),
            LEParameter(
                "picture_string",
                IN,
                "vstring",
                "How input_char_date is laid out.",
            ),
            LEParameter(
                "output_COBOL_date",
                OUT,
                "int32",
                "The converted date, on COBOL's INTEGER-OF-DATE scale "
                "(days since 31 December 1600) rather than the Lilian one.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEDATE",
        "datetime",
        "Convert a Lilian date to a character date",
        (
            LEParameter(
                "input_Lilian", IN, "int32", "The Lilian day number to format."
            ),
            LEParameter(
                "picture_string",
                IN,
                "vstring",
                'The layout to produce, e.g. "YYYY-MM-DD".',
            ),
            LEParameter(
                "output_char_date",
                OUT,
                "char80",
                "The formatted date, blank padded.",
            ),
            _fc(),
        ),
        notes=(_LILIAN_NOTE,),
    ),
    _service(
        "CEEDATM",
        "datetime",
        "Convert Lilian seconds to a character timestamp",
        (
            LEParameter(
                "input_seconds",
                IN,
                "float64",
                "The Lilian seconds value to format.",
            ),
            LEParameter(
                "picture_string",
                IN,
                "vstring",
                'The layout to produce, e.g. "YYYY-MM-DD HH:MI:SS".',
            ),
            LEParameter(
                "output_timestamp",
                OUT,
                "char80",
                "The formatted timestamp, blank padded.",
            ),
            _fc(),
        ),
        notes=(_LILIAN_NOTE,),
    ),
    _service(
        "CEESECS",
        "datetime",
        "Convert a character timestamp to Lilian seconds",
        (
            LEParameter(
                "input_timestamp",
                IN,
                "vstring",
                "The timestamp to convert, matching picture_string.",
            ),
            LEParameter(
                "picture_string",
                IN,
                "vstring",
                "How input_timestamp is laid out.",
            ),
            LEParameter(
                "output_seconds",
                OUT,
                "float64",
                "The converted timestamp, in Lilian seconds.",
            ),
            _fc(),
        ),
        notes=(_LILIAN_NOTE,),
    ),
    _service(
        "CEEGMT",
        "datetime",
        "Get the current Greenwich Mean Time",
        (
            LEParameter("output_Lilian", OUT, "int32", "Current GMT as a Lilian date."),
            LEParameter(
                "output_seconds",
                OUT,
                "float64",
                "Current GMT as Lilian seconds.",
            ),
            LEParameter(
                "output_Gregorian",
                OUT,
                "char17",
                "Current GMT as YYYYMMDDHHMMSSTTT.",
            ),
            _fc(),
        ),
        notes=(_LILIAN_NOTE,),
    ),
    _service(
        "CEEUTC",
        "datetime",
        "Get the current Coordinated Universal Time",
        (
            LEParameter("output_Lilian", OUT, "int32", "Current UTC as a Lilian date."),
            LEParameter(
                "output_seconds",
                OUT,
                "float64",
                "Current UTC as Lilian seconds.",
            ),
            LEParameter(
                "output_Gregorian",
                OUT,
                "char17",
                "Current UTC as YYYYMMDDHHMMSSTTT.",
            ),
            _fc(),
        ),
        notes=("CEEUTC is an alias of CEEGMT and takes the same operands.",),
    ),
    _service(
        "CEELOCT",
        "datetime",
        "Get the current local time",
        (
            LEParameter(
                "output_Lilian",
                OUT,
                "int32",
                "Current local time as a Lilian date.",
            ),
            LEParameter(
                "output_seconds",
                OUT,
                "float64",
                "Current local time as Lilian seconds.",
            ),
            LEParameter(
                "output_Gregorian",
                OUT,
                "char17",
                "Current local time as YYYYMMDDHHMMSSTTT.",
            ),
            _fc(),
        ),
        notes=(_LILIAN_NOTE,),
    ),
    _service(
        "CEEGMTO",
        "datetime",
        "Get the offset from Greenwich Mean Time to local time",
        (
            LEParameter(
                "offset_hours", OUT, "int32", "Whole hours of offset from GMT."
            ),
            LEParameter(
                "offset_minutes",
                OUT,
                "int32",
                "Whole minutes of offset from GMT.",
            ),
            LEParameter(
                "offset_seconds", OUT, "float64", "Offset from GMT in seconds."
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEDYWK",
        "datetime",
        "Calculate the day of the week from a Lilian date",
        (
            LEParameter(
                "input_Lilian", IN, "int32", "The Lilian day number to look up."
            ),
            LEParameter(
                "output_day_of_week",
                OUT,
                "int32",
                "1 = Sunday through 7 = Saturday.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEISEC",
        "datetime",
        "Convert integer date and time components to Lilian seconds",
        (
            LEParameter("input_year", IN, "int32", "Four-digit year."),
            LEParameter("input_month", IN, "int32", "Month, 1 to 12."),
            LEParameter("input_day", IN, "int32", "Day of month, 1 to 31."),
            LEParameter("input_hours", IN, "int32", "Hours, 0 to 23."),
            LEParameter("input_minutes", IN, "int32", "Minutes, 0 to 59."),
            LEParameter("input_seconds", IN, "int32", "Seconds, 0 to 59."),
            LEParameter(
                "output_seconds",
                OUT,
                "float64",
                "The components as one Lilian seconds value.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEESECI",
        "datetime",
        "Convert Lilian seconds to integer date and time components",
        (
            LEParameter("input_seconds", IN, "float64", "The Lilian seconds to split."),
            LEParameter("output_year", OUT, "int32", "Four-digit year."),
            LEParameter("output_month", OUT, "int32", "Month, 1 to 12."),
            LEParameter("output_day", OUT, "int32", "Day of month, 1 to 31."),
            LEParameter("output_hours", OUT, "int32", "Hours, 0 to 23."),
            LEParameter("output_minutes", OUT, "int32", "Minutes, 0 to 59."),
            LEParameter("output_seconds", OUT, "int32", "Seconds, 0 to 59."),
            LEParameter("output_millisecs", OUT, "int32", "Milliseconds, 0 to 999."),
            _fc(),
        ),
    ),
    _service(
        "CEEQCEN",
        "datetime",
        "Query the century window",
        (
            LEParameter(
                "century_start",
                OUT,
                "int32",
                "Years before today at which the century window starts " "(0 to 100).",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEESCEN",
        "datetime",
        "Set the century window",
        (
            LEParameter(
                "century_start",
                IN,
                "int32",
                "Years before today at which the century window is to start "
                "(0 to 100).",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEFMDA",
        "datetime",
        "Get the default date picture string",
        (
            LEParameter(
                "picture_string",
                OUT,
                "char80",
                "The date layout for the current national language.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEFMDT",
        "datetime",
        "Get the default date and time picture string",
        (
            LEParameter(
                "picture_string",
                OUT,
                "char80",
                "The timestamp layout for the current national language.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEFMTM",
        "datetime",
        "Get the default time picture string",
        (
            LEParameter(
                "picture_string",
                OUT,
                "char80",
                "The time layout for the current national language.",
            ),
            _fc(),
        ),
    ),
    # ── Heap storage ─────────────────────────────────────────────────────────
    _service(
        "CEEGTST",
        "storage",
        "Get heap storage",
        (
            LEParameter(
                "heap_id",
                IN,
                "int32",
                "Which heap to allocate from; 0 is the initial heap.",
            ),
            LEParameter(
                "size", IN, "int32", "Number of bytes to allocate (must be > 0)."
            ),
            LEParameter(
                "address",
                OUT,
                "pointer",
                "Address of the allocated storage; SET a based item's "
                "ADDRESS OF from it.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEFRST",
        "storage",
        "Free heap storage",
        (
            LEParameter(
                "address",
                IN,
                "pointer",
                "Address returned by the CEEGTST that allocated the storage.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEECZST",
        "storage",
        "Reallocate (change the size of) heap storage",
        (
            LEParameter(
                "address",
                INOUT,
                "pointer",
                "Address of the storage to resize; updated in place, since "
                "the storage may move.",
            ),
            LEParameter("new_size", IN, "int32", "The new size, in bytes."),
            _fc(),
        ),
    ),
    _service(
        "CEEDSHP",
        "storage",
        "Discard a heap",
        (
            LEParameter(
                "heap_id",
                IN,
                "int32",
                "The heap to discard, freeing everything still allocated in " "it.",
            ),
            _fc(),
        ),
    ),
    # ── Condition handling ───────────────────────────────────────────────────
    _service(
        "CEEHDLR",
        "condition",
        "Register a user condition handler",
        (
            LEParameter(
                "routine",
                IN,
                "procedure-pointer",
                "The handler entry point, SET from a program name.",
            ),
            LEParameter(
                "token",
                IN,
                "int32",
                "Value handed back to the handler when it runs.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEHDLU",
        "condition",
        "Unregister a user condition handler",
        (
            LEParameter(
                "routine",
                IN,
                "procedure-pointer",
                "The handler to remove -- the same pointer CEEHDLR was given.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEESGL",
        "condition",
        "Signal a condition",
        (
            LEParameter(
                "condition_token",
                IN,
                "feedback",
                "The condition to raise.",
            ),
            LEParameter(
                "q_data_token",
                IN,
                "int32",
                "Qualifying data token, or omitted when there is none.",
                optional=True,
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEMSG",
        "runtime",
        "Get, format and dispatch a message for a condition",
        (
            LEParameter(
                "condition_token",
                IN,
                "feedback",
                "The condition whose message is wanted.",
            ),
            LEParameter(
                "destination",
                IN,
                "int32",
                "2 writes the message to the LE message file.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEMOUT",
        "runtime",
        "Dispatch a message string",
        (
            LEParameter("message_string", IN, "vstring", "The text to write out."),
            LEParameter(
                "destination",
                IN,
                "int32",
                "2 writes the message to the LE message file.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEEMRCR",
        "condition",
        "Move the resume cursor relative to the handle cursor",
        (
            LEParameter(
                "type_of_move",
                IN,
                "int32",
                "0 resumes at the next instruction, 1 at the call return "
                "point of the routine that incurred the condition.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEE3DMP",
        "condition",
        "Generate a Language Environment dump",
        (
            LEParameter("title", IN, "char80", "Title line for the dump."),
            LEParameter(
                "options",
                IN,
                "vstring",
                'Blank-separated dump options, e.g. "TRACEBACK VARIABLES".',
            ),
            _fc(),
        ),
    ),
    _service(
        "CEE3ABD",
        "condition",
        "Terminate the enclave with an abend",
        (
            LEParameter("abend_code", IN, "int32", "The abend code to issue."),
            LEParameter(
                "timing",
                IN,
                "int32",
                "0 abends after LE cleanup, 1 abends immediately.",
            ),
        ),
        notes=("CEE3ABD does not return, and takes no feedback code.",),
    ),
    # ── Enclave and runtime ──────────────────────────────────────────────────
    _service(
        "CEE3PRM",
        "runtime",
        "Query the runtime parameter string",
        (
            LEParameter(
                "parm_string",
                OUT,
                "char80",
                "The program's parameter string, blank padded.",
            ),
            _fc(),
        ),
    ),
    _service(
        "CEE3GRC",
        "runtime",
        "Get the enclave return code",
        (
            LEParameter(
                "return_code", OUT, "int32", "The current enclave return code."
            ),
            _fc(),
        ),
    ),
    _service(
        "CEE3SRC",
        "runtime",
        "Set the enclave return code",
        (
            LEParameter("return_code", IN, "int32", "The return code to set."),
            _fc(),
        ),
    ),
    # ── IMS ──────────────────────────────────────────────────────────────────
    _service(
        "CEETDLI",
        "ims",
        "Issue an IMS DL/I call through Language Environment",
        (
            LEParameter(
                "function_code",
                IN,
                "record",
                'The DL/I function, e.g. a PIC X(4) holding "GU  " or ' '"ISRT".',
            ),
            LEParameter("pcb", INOUT, "record", "The PCB mask the call works through."),
            LEParameter(
                "io_area",
                INOUT,
                "record",
                "The segment I/O area read into or written from.",
            ),
            LEParameter(
                "ssa",
                IN,
                "record",
                "Segment search argument. Repeat once per level being "
                "qualified; omit entirely for an unqualified call.",
                optional=True,
                repeats=True,
            ),
        ),
        notes=(
            "Unlike CBLTDLI, CEETDLI takes no parameter-count operand -- LE "
            "derives it from the USING list.",
        ),
    ),
)

LE_SERVICE_SIGNATURES: dict[str, LEServiceSignature] = {
    sig.name: sig for sig in _SIGNATURES
}


# ── Intrinsic-function signatures ─────────────────────────────────────────────


@dataclass(frozen=True)
class IntrinsicArgument:
    """One positional argument of a ``FUNCTION`` reference."""

    name: str
    category: str
    description: str
    optional: bool = False
    repeats: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "optional": self.optional,
            "repeats": self.repeats,
            "description": self.description,
        }


@dataclass(frozen=True)
class IntrinsicSignature:
    """The call shape and return category of one COBOL intrinsic function."""

    name: str
    summary: str
    returns: str
    arguments: tuple[IntrinsicArgument, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = ()

    @property
    def required_arguments(self) -> tuple[IntrinsicArgument, ...]:
        return tuple(a for a in self.arguments if not a.optional)

    def call_example(self) -> str:
        if not self.arguments:
            return f"FUNCTION {self.name}"
        parts = []
        for arg in self.arguments:
            text = f"{arg.name}..." if arg.repeats else arg.name
            parts.append(f"[{text}]" if arg.optional else text)
        return f"FUNCTION {self.name}({', '.join(parts)})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "function",
            "summary": self.summary,
            "returns": self.returns,
            "arguments": [a.to_dict() for a in self.arguments],
            "required_count": len(self.required_arguments),
            "call_example": self.call_example(),
            "notes": list(self.notes),
        }


def _num(name: str = "argument-1", description: str = "") -> IntrinsicArgument:
    return IntrinsicArgument(name, "numeric", description)


def _int_arg(name: str = "argument-1", description: str = "") -> IntrinsicArgument:
    return IntrinsicArgument(name, "integer", description)


def _alnum(name: str = "argument-1", description: str = "") -> IntrinsicArgument:
    return IntrinsicArgument(name, "alphanumeric", description)


_SERIES = IntrinsicArgument(
    "argument-1",
    "numeric",
    "One or more numeric operands, or a table reference with ALL.",
    repeats=True,
)

_SERIES_ANY = IntrinsicArgument(
    "argument-1",
    "numeric or alphanumeric",
    "Two or more operands of the same class, or a table reference with ALL.",
    repeats=True,
)

_WINDOW = IntrinsicArgument(
    "argument-2",
    "integer",
    "End of the 100-year sliding window, as years from today. Defaults to "
    "50 when omitted.",
    optional=True,
)


def _fn(
    name: str,
    summary: str,
    returns: str,
    arguments: tuple[IntrinsicArgument, ...] = (),
    notes: tuple[str, ...] = (),
) -> IntrinsicSignature:
    return IntrinsicSignature(name, summary, returns, arguments, notes)


_INTRINSICS: tuple[IntrinsicSignature, ...] = (
    _fn(
        "ACOS",
        "Arccosine of the argument, in radians",
        "numeric",
        (_num(description="A value from -1 to +1."),),
    ),
    _fn(
        "ANNUITY",
        "Ratio of an annuity payment to its present value",
        "numeric",
        (
            _num("argument-1", "Interest rate per period."),
            _int_arg("argument-2", "Number of periods (must be positive)."),
        ),
    ),
    _fn(
        "ASIN",
        "Arcsine of the argument, in radians",
        "numeric",
        (_num(description="A value from -1 to +1."),),
    ),
    _fn(
        "ATAN",
        "Arctangent of the argument, in radians",
        "numeric",
        (_num(description="Any numeric value."),),
    ),
    _fn(
        "CHAR",
        "The character at an ordinal position in the collating sequence",
        "alphanumeric",
        (
            _int_arg(
                description="Ordinal position, 1 through the size of the "
                "collating sequence."
            ),
        ),
    ),
    _fn(
        "COS",
        "Cosine of an angle given in radians",
        "numeric",
        (_num(description="The angle, in radians."),),
    ),
    _fn(
        "CURRENT-DATE",
        "The current date, time and offset from GMT",
        "alphanumeric",
        (),
        notes=(
            "21 characters: YYYYMMDDHHMMSShh followed by the GMT offset as "
            "+hhmm, -hhmm, or 00000 when the offset is unavailable.",
        ),
    ),
    _fn(
        "DATE-OF-INTEGER",
        "Standard date form of an integer date",
        "integer",
        (
            _int_arg(
                description="Days since 31 December 1600, as INTEGER-OF-DATE "
                "returns."
            ),
        ),
        notes=("The result is an integer of the form YYYYMMDD.",),
    ),
    _fn(
        "DATE-TO-YYYYMMDD",
        "Expand a two-digit-year date to a four-digit-year date",
        "integer",
        (_int_arg(description="A date of the form YYMMDD."), _WINDOW),
    ),
    _fn(
        "DAY-OF-INTEGER",
        "Julian date form of an integer date",
        "integer",
        (_int_arg(description="Days since 31 December 1600."),),
        notes=("The result is an integer of the form YYYYDDD.",),
    ),
    _fn(
        "DAY-TO-YYYYDDD",
        "Expand a two-digit-year Julian date to a four-digit-year one",
        "integer",
        (_int_arg(description="A date of the form YYDDD."), _WINDOW),
    ),
    _fn(
        "FACTORIAL",
        "Factorial of the argument",
        "integer",
        (_int_arg(description="A non-negative integer."),),
    ),
    _fn(
        "INTEGER",
        "The greatest integer not greater than the argument",
        "integer",
        (_num(description="Any numeric value."),),
    ),
    _fn(
        "INTEGER-OF-DATE",
        "Integer date form of a standard date",
        "integer",
        (_int_arg(description="A date of the form YYYYMMDD."),),
        notes=("The result counts days since 31 December 1600.",),
    ),
    _fn(
        "INTEGER-OF-DAY",
        "Integer date form of a Julian date",
        "integer",
        (_int_arg(description="A date of the form YYYYDDD."),),
    ),
    _fn(
        "LENGTH",
        "Size of the argument in character positions",
        "integer",
        (
            IntrinsicArgument(
                "argument-1",
                "any",
                "Any data item, literal, or function result.",
            ),
        ),
    ),
    _fn(
        "LOG",
        "Natural logarithm of the argument",
        "numeric",
        (_num(description="A value greater than zero."),),
    ),
    _fn(
        "LOG10",
        "Base 10 logarithm of the argument",
        "numeric",
        (_num(description="A value greater than zero."),),
    ),
    _fn(
        "LOWER-CASE",
        "The argument with every letter folded to lower case",
        "alphanumeric",
        (_alnum(description="The text to fold."),),
    ),
    _fn(
        "MAX",
        "The largest of the arguments",
        "same class as the arguments",
        (_SERIES_ANY,),
    ),
    _fn("MEAN", "Arithmetic mean of the arguments", "numeric", (_SERIES,)),
    _fn("MEDIAN", "Middle value of the arguments", "numeric", (_SERIES,)),
    _fn(
        "MIDRANGE",
        "Mean of the smallest and largest argument",
        "numeric",
        (_SERIES,),
    ),
    _fn(
        "MIN",
        "The smallest of the arguments",
        "same class as the arguments",
        (_SERIES_ANY,),
    ),
    _fn(
        "MOD",
        "Argument-1 modulo argument-2",
        "integer",
        (
            _int_arg("argument-1", "The dividend."),
            _int_arg("argument-2", "The divisor; must not be zero."),
        ),
        notes=(
            "The result takes the sign of argument-2, which is what "
            "separates MOD from REM.",
        ),
    ),
    _fn(
        "NUMVAL",
        "Numeric value of an alphanumeric numeric string",
        "numeric",
        (
            _alnum(
                description="Digits with optional sign, decimal point and "
                'surrounding spaces, e.g. " -12.34 ".'
            ),
        ),
    ),
    _fn(
        "NUMVAL-C",
        "Numeric value of an alphanumeric string with currency and commas",
        "numeric",
        (
            _alnum("argument-1", 'A string such as "$1,234.56".'),
            IntrinsicArgument(
                "argument-2",
                "alphanumeric",
                "The currency sign to expect. Defaults to the CURRENCY SIGN "
                "clause, or $, when omitted.",
                optional=True,
            ),
        ),
    ),
    _fn(
        "ORD",
        "Ordinal position of a character in the collating sequence",
        "integer",
        (_alnum(description="A one-character argument."),),
    ),
    _fn(
        "ORD-MAX",
        "Position, in the argument list, of the largest argument",
        "integer",
        (_SERIES_ANY,),
    ),
    _fn(
        "ORD-MIN",
        "Position, in the argument list, of the smallest argument",
        "integer",
        (_SERIES_ANY,),
    ),
    _fn(
        "PRESENT-VALUE",
        "Present value of a series of future amounts",
        "numeric",
        (
            _num("argument-1", "Discount rate per period."),
            IntrinsicArgument(
                "argument-2",
                "numeric",
                "One amount per future period, in order.",
                repeats=True,
            ),
        ),
    ),
    _fn(
        "RANDOM",
        "A pseudo-random number from 0 up to but not including 1",
        "numeric",
        (
            IntrinsicArgument(
                "argument-1",
                "integer",
                "Seed. Supply it on the first reference to make the sequence "
                "repeatable; omit it to continue the sequence.",
                optional=True,
            ),
        ),
    ),
    _fn(
        "RANGE",
        "Largest argument minus smallest argument",
        "numeric",
        (_SERIES,),
    ),
    _fn(
        "REM",
        "Remainder of argument-1 divided by argument-2",
        "numeric",
        (
            _num("argument-1", "The dividend."),
            _num("argument-2", "The divisor; must not be zero."),
        ),
        notes=("The result takes the sign of argument-1, unlike MOD.",),
    ),
    _fn(
        "REVERSE",
        "The argument with its characters in reverse order",
        "alphanumeric",
        (_alnum(description="The text to reverse."),),
    ),
    _fn(
        "SIN",
        "Sine of an angle given in radians",
        "numeric",
        (_num(description="The angle, in radians."),),
    ),
    _fn(
        "SQRT",
        "Square root of the argument",
        "numeric",
        (_num(description="A non-negative value."),),
    ),
    _fn(
        "STANDARD-DEVIATION",
        "Standard deviation of the arguments",
        "numeric",
        (_SERIES,),
    ),
    _fn("SUM", "Sum of the arguments", "numeric", (_SERIES,)),
    _fn(
        "TAN",
        "Tangent of an angle given in radians",
        "numeric",
        (_num(description="The angle, in radians."),),
    ),
    _fn(
        "UPPER-CASE",
        "The argument with every letter folded to upper case",
        "alphanumeric",
        (_alnum(description="The text to fold."),),
    ),
    _fn("VARIANCE", "Variance of the arguments", "numeric", (_SERIES,)),
    _fn(
        "WHEN-COMPILED",
        "The date and time this program was compiled",
        "alphanumeric",
        (),
        notes=("21 characters, in the same layout CURRENT-DATE returns.",),
    ),
    _fn(
        "YEAR-TO-YYYY",
        "Expand a two-digit year to a four-digit year",
        "integer",
        (_int_arg(description="A year of the form YY."), _WINDOW),
    ),
)

INTRINSIC_FUNCTION_SIGNATURES: dict[str, IntrinsicSignature] = {
    sig.name: sig for sig in _INTRINSICS
}


# ── Lookup API ────────────────────────────────────────────────────────────────


def le_service_signature(name: str) -> LEServiceSignature | None:
    """Return the signature of LE callable service *name*, if catalogued."""
    return LE_SERVICE_SIGNATURES.get(name.strip().upper())


def intrinsic_signature(name: str) -> IntrinsicSignature | None:
    """Return the signature of intrinsic function *name*, if catalogued."""
    return INTRINSIC_FUNCTION_SIGNATURES.get(name.strip().upper())


def services_without_signature() -> list[dict[str, str]]:
    """LE services the dialect recognises but this module cannot describe.

    Reported rather than hidden: a consumer can then say "known service,
    signature not catalogued" instead of showing nothing, which would be
    indistinguishable from "not an LE service at all".
    """
    from .ibm_enterprise import IBMEnterpriseCobol

    return [
        {
            "name": name,
            "category": IBMEnterpriseCobol.IBM_LE_SERVICE_CATEGORIES.get(
                name, "unknown"
            ),
        }
        for name in sorted(IBMEnterpriseCobol.IBM_LE_CALLABLE_SERVICES)
        if name not in LE_SERVICE_SIGNATURES
    ]


def catalog_to_dict() -> dict[str, Any]:
    """The whole catalogue as one JSON-serialisable dict."""
    return {
        "catalog_version": CATALOG_VERSION,
        "reference": _REFERENCE,
        "services": [
            LE_SERVICE_SIGNATURES[name].to_dict()
            for name in sorted(LE_SERVICE_SIGNATURES)
        ],
        "functions": [
            INTRINSIC_FUNCTION_SIGNATURES[name].to_dict()
            for name in sorted(INTRINSIC_FUNCTION_SIGNATURES)
        ],
        "services_without_signature": services_without_signature(),
    }
