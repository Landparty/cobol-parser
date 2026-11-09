"""
IO statement AST nodes (READ, WRITE, OPEN, CLOSE, ACCEPT, REWRITE, DELETE, START, UNLOCK).
"""

from typing import Any

from ..ast_base import SourceLocation
from .base import CobolStatement


class InvalidKeyClauseMixin:
    """Shared INVALID KEY / NOT INVALID KEY clause setters for IO statements.

    Consolidates the identical setter bodies used by READ, WRITE, REWRITE,
    DELETE, and START statement nodes.
    """

    invalid_key_clause: list["CobolStatement"] | None
    not_invalid_key_clause: list["CobolStatement"] | None

    def set_invalid_key_clause(self, statements: list["CobolStatement"] | None) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        for stmt in statements or []:
            self.add_child(stmt)  # type: ignore[attr-defined]
        if statements:
            self.metadata["has_invalid_key"] = True  # type: ignore[attr-defined]

    def set_not_invalid_key_clause(
        self, statements: list["CobolStatement"] | None
    ) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements
        for stmt in statements or []:
            self.add_child(stmt)  # type: ignore[attr-defined]


class IOReadStatement(InvalidKeyClauseMixin, CobolStatement):
    """AST node for READ statements with comprehensive IBM Enterprise COBOL variation support.

    Contract: contracts/io-statement-ast.md

    Supports:
    - Sequential, indexed, and relative READ operations
    - Multiple access modes (NEXT, PREVIOUS, RANDOM, FIRST, LAST, CURRENT)
    - INTO clause for data transfer
    - KEY clause for indexed and relative files
    - AT END and NOT AT END clauses
    - INVALID KEY handling
    - Lock modes and file access controls
    - RETRY clause for automatic retries
    """

    def __init__(self, location: SourceLocation):
        super().__init__("READ", location)
        self.file_name: str | None = None
        self.record_name: str | None = None
        self.into_target: str | None = None
        self.key_name: str | None = None  # KEY IS value
        self.access_mode: str | None = None  # NEXT, FIRST, LAST, PREVIOUS, CURRENT
        self.lock_scope: str | None = None  # record, file (contract field)
        self.with_lock: bool = False
        self.with_nowait: bool = False
        self.at_end_clause: list[CobolStatement] | None = None
        self.not_at_end_clause: list[CobolStatement] | None = None
        self.invalid_key_clause: list[CobolStatement] | None = None
        self.not_invalid_key_clause: list[CobolStatement] | None = None
        self.retry_count: int | None = None
        # Metadata tracking
        self.set_metadata("has_invalid_key", False)
        self.set_metadata("has_at_end", False)
        self.set_metadata("uses_lock", False)

    def set_file_name(self, name: str) -> None:
        """Set the file name to read from."""
        self.file_name = name
        self._add_unique_operand(name)

    def set_record_name(self, name: str) -> None:
        """Set the record being read."""
        self.record_name = name
        self._add_unique_operand(name)

    def set_into(self, target: str) -> None:
        """Set the INTO clause target."""
        self.into_target = target
        self._add_unique_operand(target)

    def set_key(self, value: str) -> None:
        """Set the KEY IS clause value."""
        self.key_name = value

    def set_access_mode(self, mode: str) -> None:
        """Set the access mode (NEXT, FIRST, LAST, PREVIOUS, CURRENT)."""
        self.access_mode = mode.upper()

    def set_lock_mode(self, with_lock: bool = False, with_nowait: bool = False) -> None:
        """Set the lock mode for the read."""
        self.with_lock = with_lock
        self.with_nowait = with_nowait
        if with_lock:
            self.metadata["uses_lock"] = True
            self.lock_scope = "record"

    def set_at_end_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the AT END clause."""
        self.at_end_clause = statements
        for stmt in statements or []:
            self.add_child(stmt)
        if statements:
            self.metadata["has_at_end"] = True

    def set_not_at_end_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT AT END clause."""
        self.not_at_end_clause = statements
        for stmt in statements or []:
            self.add_child(stmt)

    def to_dict(self) -> dict[str, Any]:
        """Convert READ statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_name": self.record_name,
                "into_target": self.into_target,
                "key_name": self.key_name,
                "access_mode": self.access_mode,
                "lock_scope": self.lock_scope,
                # Status flags
                "with_lock": self.with_lock,
                "with_nowait": self.with_nowait,
            }
        )
        # Clauses
        result.update(
            self._serialize_clauses(
                "at_end_clause",
                "not_at_end_clause",
                "invalid_key_clause",
                "not_invalid_key_clause",
            )
        )
        result["retry_count"] = self.retry_count
        return result


class IOWriteStatement(InvalidKeyClauseMixin, CobolStatement):
    """AST node for WRITE statements with comprehensive IBM Enterprise COBOL variation support.

    Contract: contracts/io-statement-ast.md

    Supports:
    - FROM clause for data source
    - BEFORE/AFTER ADVANCING for print files
    - AT END-OF-PAGE clause
    - INVALID KEY handling for indexed files
    - Record deletion for VSAM files
    - Multiple LINES specification
    - Lock modes and file access controls
    - RETRY clause for automatic retries
    """

    def __init__(self, location: SourceLocation):
        super().__init__("WRITE", location)
        self.file_name: str | None = None  # Contract field (added)
        self.record_name: str | None = None
        self.from_clause: str | None = None
        self.advancing_clause: dict[str, Any] | None = (
            None  # {"type": "BEFORE"|"AFTER", "value": ..., "unit": "LINES"|"CHANNEL"|"MNEMONIC"}
        )
        self.delete_record: bool = False  # For VSAM DELETE
        self.at_eop_clause: list[CobolStatement] | None = None  # AT END-OF-PAGE
        self.not_at_eop_clause: list[CobolStatement] | None = None  # NOT AT END-OF-PAGE
        self.invalid_key_clause: list[CobolStatement] | None = None
        self.not_invalid_key_clause: list[CobolStatement] | None = None
        self.retry_count: int | None = None
        self.with_lock: bool = False
        self.lock_scope: str | None = None  # Contract field
        self.advancing_mode: str | None = None  # Simple advancing mode string
        # Metadata tracking
        self.set_metadata("has_invalid_key", False)
        self.set_metadata("uses_advancing", False)
        self.set_metadata("uses_lock", False)

    def set_record_name(self, name: str) -> None:
        """Set the record being written."""
        self.record_name = name
        self._add_unique_operand(name)

    def set_from(self, source: str) -> None:
        """Set the FROM clause source."""
        self.from_clause = source
        self._add_unique_operand(source)

    def set_advancing(
        self,
        mode: str,
        lines: int | None = None,
        page: bool = False,
        identifier: str | None = None,
        mnemonic: str | None = None,
    ) -> None:
        """Set the ADVANCING clause.

        ``identifier`` is a data-name holding a line count (e.g.
        ``ADVANCING WS-LINE-COUNT LINES``); ``mnemonic`` is a SPECIAL-NAMES
        mnemonic-name for a printer channel (e.g. ``ADVANCING TOP-OF-PAGE``,
        defined via ``SPECIAL-NAMES. C01 IS TOP-OF-PAGE``) and takes no
        LINE/LINES suffix.
        """
        mode_upper = mode.upper()
        if mnemonic is not None:
            value: Any = mnemonic
            unit: str | None = "MNEMONIC"
        elif identifier is not None:
            value = identifier
            unit = "LINES"
        else:
            value = lines if lines else ("PAGE" if page else None)
            unit = "CHANNEL" if page else ("LINES" if lines else None)
        self.advancing_clause = {
            "type": mode_upper,  # BEFORE or AFTER
            "value": value,
            "unit": unit,
        }
        if self.advancing_clause:
            self.metadata["uses_advancing"] = True

    def set_at_eop_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the AT END-OF-PAGE clause."""
        self.at_eop_clause = statements
        for stmt in statements or []:
            self.add_child(stmt)

    def set_not_at_eop_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT AT END-OF-PAGE clause."""
        self.not_at_eop_clause = statements
        for stmt in statements or []:
            self.add_child(stmt)

    def to_dict(self) -> dict[str, Any]:
        """Convert WRITE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_name": self.record_name,
                "from_clause": self.from_clause,
                "advancing_clause": self.advancing_clause,
                "advancing_mode": self.advancing_mode,
                "lock_scope": self.lock_scope,
                # Status flags
                "delete_record": self.delete_record,
                "with_lock": self.with_lock,
            }
        )
        # Clauses
        result.update(
            self._serialize_clauses(
                "at_eop_clause",
                "not_at_eop_clause",
                "invalid_key_clause",
                "not_invalid_key_clause",
            )
        )
        result["retry_count"] = self.retry_count
        return result


class IOOpenStatement(CobolStatement):
    """AST node for OPEN statements with comprehensive IO variation support.

    Supports:
    - Multiple file opens in single statement
    - OPEN INPUT, OUTPUT, I-O, EXTEND modes
    - Error handling for file status issues
    - REPOSITION for VSAM files
    """

    def __init__(self, location: SourceLocation):
        super().__init__("OPEN", location)
        self.open_mode: str | None = None  # INPUT, OUTPUT, I-O, EXTEND
        self.file_names: list[str] = []
        # Per-file mode, keyed by file name (e.g. {"FILE-A": "INPUT",
        # "FILE-B": "OUTPUT"} for `OPEN INPUT FILE-A OUTPUT FILE-B`).
        # `open_mode` above only ever reflects the *first* mode group, which
        # is indistinguishable from every other file's mode to a downstream
        # consumer (CRUD matrix, IO sequence analyzer) keyed off it alone --
        # this dict is the authoritative per-file source of truth.
        self.file_modes: dict[str, str] = {}
        self.with_reposition: bool = False
        self.no_rewind: bool = False  # [WITH] NO REWIND
        self.with_lock: bool = False  # [WITH] LOCK
        self.reversed_mode: bool = False  # OPEN INPUT f REVERSED
        self.reel_unit_control: str | None = None  # Contract field
        self._metadata = {
            "has_reel_unit": False,
        }

    def set_open_mode(self, mode: str) -> None:
        """Set the OPEN mode."""
        self.open_mode = mode.upper()  # INPUT, OUTPUT, I-O, EXTEND

    def add_file(self, file_name: str, mode: str | None = None) -> None:
        """Add a file to open, optionally recording its own mode group.

        *mode* is the mode keyword (INPUT/OUTPUT/I-O/EXTEND) of the mode
        group *file_name* was parsed under -- distinct from ``open_mode``,
        which only ever tracks the statement's first mode group. Omitted
        (``None``) when the caller has no per-file mode to record.
        """
        if file_name not in self.file_names:
            self.file_names.append(file_name)
            self.operands.append(file_name)
        if mode:
            self.file_modes[file_name] = mode.upper()

    def set_reposition(self, reposition: bool = True) -> None:
        """Set the REPOSITION flag for VSAM files."""
        self.with_reposition = reposition

    def set_no_rewind(self, no_rewind: bool = True) -> None:
        """Record a ``[WITH] NO REWIND`` option."""
        self.no_rewind = no_rewind

    def set_with_lock(self, with_lock: bool = True) -> None:
        """Record a ``[WITH] LOCK`` option."""
        self.with_lock = with_lock

    def set_reversed(self, reversed_mode: bool = True) -> None:
        """Record the ``REVERSED`` option (sequential input read backwards)."""
        self.reversed_mode = reversed_mode

    def to_dict(self) -> dict[str, Any]:
        """Convert OPEN statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "open_mode": self.open_mode,
                "file_names": self.file_names,
                "file_modes": self.file_modes,
                "with_reposition": self.with_reposition,
                "no_rewind": self.no_rewind,
                "with_lock": self.with_lock,
                "reversed": self.reversed_mode,
                "reel_unit_control": self.reel_unit_control,  # Contract field
            }
        )
        return result


class IOCloseStatement(CobolStatement):
    """AST node for CLOSE statements with comprehensive IO variation support.

    Supports:
    - Multiple file closes in single statement
    - REEL/UNIT for tape files
    - WITH NO REWIND for tape operations
    - WITH LOCK for exclusive close
    """

    def __init__(self, location: SourceLocation):
        super().__init__("CLOSE", location)
        self.file_names: list[str] = []
        self.close_options: dict[str, Any] = {}  # reel, unit, no_rewind, with_lock
        self._metadata = {
            "has_lock": False,
            "has_reel_unit": False,
        }

    def add_file(
        self,
        file_name: str,
        reel: bool = False,
        unit: bool = False,
        no_rewind: bool = False,
        with_lock: bool = False,
        for_removal: bool = False,
    ) -> None:
        """Add a file to close with options."""
        if file_name not in self.file_names:
            self.file_names.append(file_name)
            self.operands.append(file_name)
            self.close_options[file_name] = {
                "reel": reel,
                "unit": unit,
                "no_rewind": no_rewind,
                "with_lock": with_lock,
                "for_removal": for_removal,
            }
            if with_lock:
                self.metadata["has_lock"] = True
            if reel or unit:
                self.metadata["has_reel_unit"] = True

    def to_dict(self) -> dict[str, Any]:
        """Convert CLOSE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_names": self.file_names,
                "close_options": self.close_options,
            }
        )
        return result


class IOAcceptStatement(CobolStatement):
    """AST node for ACCEPT statements with comprehensive IO variation support.

    Supports:
    - FROM keyword variations (CONSOLE, DISPLAY, COMMAND-LINE, etc.)
    - AT LINE/COLUMN positioning
    - WITH CURSOR positioning
    - COLOR specification
    - BEEP for audible alert
    - NO ECHO for password input
    - RETURN-CODE and ENVIRONMENT-NAME
    - DATE/TIME intrinsics
    """

    def __init__(self, location: SourceLocation):
        super().__init__("ACCEPT", location)
        self.target: str | None = None
        self.from_source: str | None = (
            None  # CONSOLE, DISPLAY, COMMAND-LINE, DATE, TIME, etc.
        )
        self.environment_name: str | None = None  # Contract field
        self.at_line: int | None = None
        self.at_column: int | None = None
        self.with_cursor: bool = False
        self.color_attribute: str | None = None
        self.with_beep: bool = False
        self.with_no_echo: bool = False
        self.secure: bool = False
        self.timeout_value: int | None = None
        self.auto_skip: bool = False
        self.upper: bool = False
        self.on_exception: list[CobolStatement] | None = None
        self.not_on_exception: list[CobolStatement] | None = None
        self._metadata = {
            "has_environment_name": False,
            "has_position": False,
        }

    def set_on_exception_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the [ON] EXCEPTION handler body."""
        self._set_clause("on_exception", statements)

    def set_not_on_exception_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT [ON] EXCEPTION handler body."""
        self._set_clause("not_on_exception", statements)

    def set_target(self, name: str) -> None:
        """Set the accept target variable."""
        self.target = name
        self._add_unique_operand(name)

    def set_from(self, source: str) -> None:
        """Set the FROM source."""
        self.from_source = source.upper()

    def set_environment_name(self, name: str) -> None:
        """Set the ENVIRONMENT-NAME for FROM ENVIRONMENT clause (contract field)."""
        self.environment_name = name
        self.metadata["has_environment_name"] = True

    def set_position(self, line: int | None = None, column: int | None = None) -> None:
        """Set the position (AT LINE/COLUMN)."""
        self.at_line = line
        self.at_column = column
        if line is not None or column is not None:
            self.metadata["has_position"] = True

    def set_no_echo(self, with_no_echo: bool = True) -> None:
        """Set the NO ECHO flag."""
        self.with_no_echo = with_no_echo

    def set_secure(self, secure: bool = True) -> None:
        """Set the SECURE flag (asterisk-masked input; distinct from
        NO-ECHO, which shows nothing -- see reports/open-findings.md M3)."""
        self.secure = secure

    def set_timeout(self, seconds: int) -> None:
        """Set the TIMEOUT clause value, in seconds."""
        self.timeout_value = seconds

    def set_auto_skip(self, auto_skip: bool = True) -> None:
        """Set the AUTO-SKIP flag."""
        self.auto_skip = auto_skip

    def set_upper(self, upper: bool = True) -> None:
        """Set the UPPER flag (force uppercase input)."""
        self.upper = upper

    def to_dict(self) -> dict[str, Any]:
        """Convert ACCEPT statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "target": self.target,
                "from_source": self.from_source,
                "environment_name": self.environment_name,  # Contract field
                "at_line": self.at_line,
                "at_column": self.at_column,
                "with_cursor": self.with_cursor,
                "color_attribute": self.color_attribute,
                "with_beep": self.with_beep,
                "with_no_echo": self.with_no_echo,
                "secure": self.secure,
                "timeout_value": self.timeout_value,
                "auto_skip": self.auto_skip,
                "upper": self.upper,
            }
        )
        result.update(
            self._serialize_clauses("on_exception", "not_on_exception", omit_empty=True)
        )
        return result


class IORewriteStatement(InvalidKeyClauseMixin, CobolStatement):
    """IBM Enterprise COBOL REWRITE statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("REWRITE_STATEMENT", location)
        self.file_name: str | None = None
        self.record_name: str | None = None
        self.from_clause: str | None = None
        self.invalid_key_clause: list[CobolStatement] = []
        self.not_invalid_key_clause: list[CobolStatement] = []
        self.with_lock: bool = False
        self._metadata = {
            "has_invalid_key": False,
            "uses_lock": False,
        }

    def set_file_name(self, file_name: str) -> None:
        """Set the file name."""
        self.file_name = file_name

    def set_record_name(self, record_name: str) -> None:
        """Set the record name to rewrite."""
        self.record_name = record_name
        self._add_unique_operand(record_name)

    def set_from(self, source: str) -> None:
        """Set the FROM source (``REWRITE rec FROM data``)."""
        self.from_clause = source
        self._add_unique_operand(source)

    def to_dict(self) -> dict[str, Any]:
        """Convert REWRITE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_name": self.record_name,
                "from_clause": self.from_clause,
                **self._serialize_clauses(
                    "invalid_key_clause", "not_invalid_key_clause"
                ),
                "with_lock": self.with_lock,
            }
        )
        return result


class IODeleteStatement(InvalidKeyClauseMixin, CobolStatement):
    """IBM Enterprise COBOL DELETE statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("DELETE_STATEMENT", location)
        self.file_name: str | None = None
        self.invalid_key_clause: list[CobolStatement] = []
        self.not_invalid_key_clause: list[CobolStatement] = []
        self.with_lock: bool = False
        self._metadata = {
            "has_invalid_key": False,
            "uses_lock": False,
        }

    def set_file_name(self, file_name: str) -> None:
        """Set the file name."""
        self.file_name = file_name

    def to_dict(self) -> dict[str, Any]:
        """Convert DELETE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                **self._serialize_clauses(
                    "invalid_key_clause", "not_invalid_key_clause"
                ),
                "with_lock": self.with_lock,
            }
        )
        return result


class IOStartStatement(InvalidKeyClauseMixin, CobolStatement):
    """IBM Enterprise COBOL START statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("START_STATEMENT", location)
        self.file_name: str | None = None
        self.key_condition: str | None = (
            None  # EQUAL, GREATER, LESS, GREATER THAN, etc.
        )
        self.key_name: str | None = None  # the data-name named by KEY IS ...
        self.invalid_key_clause: list[CobolStatement] = []
        self.not_invalid_key_clause: list[CobolStatement] = []
        self._metadata = {
            "has_invalid_key": False,
        }

    def set_file_name(self, file_name: str) -> None:
        """Set the file name."""
        self.file_name = file_name

    def set_key_condition(self, condition: str) -> None:
        """Set the key condition (EQUAL, GREATER, LESS, etc.)."""
        self.key_condition = condition.upper()

    def set_key_name(self, key_name: str) -> None:
        """Set the KEY data-name the browse is positioned on."""
        self.key_name = key_name
        self._add_unique_operand(key_name)

    def to_dict(self) -> dict[str, Any]:
        """Convert START statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "key_condition": self.key_condition,
                "key_name": self.key_name,
                **self._serialize_clauses(
                    "invalid_key_clause", "not_invalid_key_clause"
                ),
            }
        )
        return result


class IOUnlockStatement(CobolStatement):
    """IBM Enterprise COBOL UNLOCK statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("UNLOCK_STATEMENT", location)
        self.file_name: str | None = None
        self.record_scope: str | None = None  # 'record' or 'file'
        self._metadata = {
            "has_record_scope": False,
        }

    def set_file_name(self, file_name: str) -> None:
        """Set the file name."""
        self.file_name = file_name

    def set_record_scope(self, scope: str) -> None:
        """Set the record scope (RECORD or FILE)."""
        self.record_scope = scope.upper()
        self.metadata["has_record_scope"] = True

    def to_dict(self) -> dict[str, Any]:
        """Convert UNLOCK statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_scope": self.record_scope,
            }
        )
        return result
