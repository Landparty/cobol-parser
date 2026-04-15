"""
IO statement AST nodes (READ, WRITE, OPEN, CLOSE, ACCEPT, REWRITE, DELETE, START, UNLOCK).
"""

from typing import Any

from ..ast_base import SourceLocation
from .base import CobolStatement


class IOReadStatement(CobolStatement):
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
        if name not in self.operands:
            self.operands.append(name)

    def set_record_name(self, name: str) -> None:
        """Set the record being read."""
        self.record_name = name
        if name not in self.operands:
            self.operands.append(name)

    def set_into(self, target: str) -> None:
        """Set the INTO clause target."""
        self.into_target = target
        if target not in self.operands:
            self.operands.append(target)

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
        if statements:
            self.metadata["has_at_end"] = True

    def set_not_at_end_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT AT END clause."""
        self.not_at_end_clause = statements

    def set_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self.metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def set_retry(self, count: int) -> None:
        """Set the RETRY clause count."""
        self.retry_count = count

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
                # Clauses
                "at_end_clause": [s.to_dict() for s in (self.at_end_clause or [])],
                "not_at_end_clause": [
                    s.to_dict() for s in (self.not_at_end_clause or [])
                ],
                "invalid_key_clause": [
                    s.to_dict() for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() for s in (self.not_invalid_key_clause or [])
                ],
                "retry_count": self.retry_count,
            }
        )
        return result


class IOWriteStatement(CobolStatement):
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
            None  # {"type": "BEFORE"|"AFTER", "value": ..., "unit": "LINES"|"CHANNEL"}
        )
        self.delete_record: bool = False  # For VSAM DELETE
        self.at_eop_clause: list[CobolStatement] | None = None  # AT END-OF-PAGE
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
        if name not in self.operands:
            self.operands.append(name)

    def set_from(self, source: str) -> None:
        """Set the FROM clause source."""
        self.from_clause = source
        if source not in self.operands:
            self.operands.append(source)

    def set_advancing(
        self, mode: str, lines: int | None = None, page: bool = False
    ) -> None:
        """Set the ADVANCING clause."""
        mode_upper = mode.upper()
        self.advancing_clause = {
            "type": mode_upper,  # BEFORE or AFTER
            "value": lines if lines else ("PAGE" if page else None),
            "unit": "CHANNEL" if page else ("LINES" if lines else None),
        }
        if self.advancing_clause:
            self.metadata["uses_advancing"] = True

    def set_delete(self, delete: bool = True) -> None:
        """Set the VSAM DELETE flag."""
        self.delete_record = delete

    def set_at_eop_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the AT END-OF-PAGE clause."""
        self.at_eop_clause = statements

    def set_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self.metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def set_retry(self, count: int) -> None:
        """Set the RETRY clause count."""
        self.retry_count = count

    def set_lock(self, with_lock: bool = True) -> None:
        """Set the LOCK flag."""
        self.with_lock = with_lock
        if with_lock:
            self.metadata["uses_lock"] = True
            self.lock_scope = "record"

    def to_dict(self) -> dict[str, Any]:
        """Convert WRITE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_name": self.record_name,
                "from_clause": self.from_clause,
                "advancing_clause": self.advancing_clause,
                "lock_scope": self.lock_scope,
                # Status flags
                "delete_record": self.delete_record,
                "with_lock": self.with_lock,
                # Clauses
                "at_eop_clause": [s.to_dict() for s in (self.at_eop_clause or [])],
                "invalid_key_clause": [
                    s.to_dict() for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() for s in (self.not_invalid_key_clause or [])
                ],
                "retry_count": self.retry_count,
            }
        )
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
        self.with_reposition: bool = False
        self.reel_unit_control: str | None = None  # Contract field
        self._metadata = {
            "has_reel_unit": False,
        }

    def set_open_mode(self, mode: str) -> None:
        """Set the OPEN mode."""
        self.open_mode = mode.upper()  # INPUT, OUTPUT, I-O, EXTEND

    def add_file(self, file_name: str) -> None:
        """Add a file to open."""
        if file_name not in self.file_names:
            self.file_names.append(file_name)
            self.operands.append(file_name)

    def set_reposition(self, reposition: bool = True) -> None:
        """Set the REPOSITION flag for VSAM files."""
        self.with_reposition = reposition

    def set_reel_unit_control(self, control: str) -> None:
        """Set the REEL/UNIT control (contract field)."""
        self.reel_unit_control = control.upper()
        self.metadata["has_reel_unit"] = True

    def to_dict(self) -> dict[str, Any]:
        """Convert OPEN statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "open_mode": self.open_mode,
                "file_names": self.file_names,
                "with_reposition": self.with_reposition,
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
        self._metadata = {
            "has_environment_name": False,
            "has_position": False,
        }

    def set_target(self, name: str) -> None:
        """Set the accept target variable."""
        self.target = name
        if name not in self.operands:
            self.operands.append(name)

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

    def set_cursor(self, with_cursor: bool = True) -> None:
        """Set the WITH CURSOR flag."""
        self.with_cursor = with_cursor

    def set_color(self, attribute: str) -> None:
        """Set the COLOR attribute."""
        self.color_attribute = attribute

    def set_beep(self, with_beep: bool = True) -> None:
        """Set the BEEP flag."""
        self.with_beep = with_beep

    def set_no_echo(self, with_no_echo: bool = True) -> None:
        """Set the NO ECHO flag."""
        self.with_no_echo = with_no_echo

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
            }
        )
        return result


class IORewriteStatement(CobolStatement):
    """IBM Enterprise COBOL REWRITE statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("REWRITE_STATEMENT", location)
        self.file_name: str | None = None
        self.record_name: str | None = None
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
        if record_name not in self.operands:
            self.operands.append(record_name)

    def set_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self.metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def set_lock(self, with_lock: bool = True) -> None:
        """Set the LOCK flag."""
        self.with_lock = with_lock
        if with_lock:
            self.metadata["uses_lock"] = True

    def to_dict(self) -> dict[str, Any]:
        """Convert REWRITE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_name": self.record_name,
                "invalid_key_clause": [
                    s.to_dict() for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() for s in (self.not_invalid_key_clause or [])
                ],
                "with_lock": self.with_lock,
            }
        )
        return result


class IODeleteStatement(CobolStatement):
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

    def set_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self.metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def set_lock(self, with_lock: bool = True) -> None:
        """Set the LOCK flag."""
        self.with_lock = with_lock
        if with_lock:
            self.metadata["uses_lock"] = True

    def to_dict(self) -> dict[str, Any]:
        """Convert DELETE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "invalid_key_clause": [
                    s.to_dict() for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() for s in (self.not_invalid_key_clause or [])
                ],
                "with_lock": self.with_lock,
            }
        )
        return result


class IOStartStatement(CobolStatement):
    """IBM Enterprise COBOL START statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("START_STATEMENT", location)
        self.file_name: str | None = None
        self.key_condition: str | None = (
            None  # EQUAL, GREATER, LESS, GREATER THAN, etc.
        )
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

    def set_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self.metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: list["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def to_dict(self) -> dict[str, Any]:
        """Convert START statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "key_condition": self.key_condition,
                "invalid_key_clause": [
                    s.to_dict() for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() for s in (self.not_invalid_key_clause or [])
                ],
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
