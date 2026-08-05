"""
Miscellaneous statement AST nodes (SELECT, COPY, CONTINUE, EXIT, GOBACK,
CANCEL, ALTER, GENERATE, RELEASE, RETURN, USE, SORT, MERGE).
"""

from typing import Any

from ..ast_base import SourceLocation
from .base import CobolStatement


class SelectStatement(CobolStatement):
    """AST node for SELECT statements in FILE-CONTROL paragraph.

    Supports comprehensive SELECT clause variations:
    - ASSIGN TO with device types and assignment specifications
    - ORGANIZATION: SEQUENTIAL, INDEXED, RELATIVE, LINE SEQUENTIAL
    - ACCESS MODE: SEQUENTIAL, RANDOM, DYNAMIC
    - RECORD KEY and ALTERNATE RECORD KEY with duplicate handling
    - FILE STATUS variable assignments
    - RESERVE clause area allocations
    - PADDING CHARACTER and RECORD DELIMITER specifications
    - PASSWORD and LOCK MODE clauses for security and concurrency
    - SHARING clauses for multi-user access
    - OPTIONAL clause for file existence handling
    """

    def __init__(self, location: SourceLocation):
        super().__init__("SELECT", location)
        self.file_name: str | None = None
        self.is_optional: bool = False

        # ASSIGN clause
        self.assign_to: str | None = None
        self.assign_device_type: str | None = None  # DISK, TAPE, PRINTER, etc.
        self.assign_external_name: str | None = None

        # ORGANIZATION clause
        self.organization: str | None = (
            None  # SEQUENTIAL, INDEXED, RELATIVE, LINE SEQUENTIAL
        )

        # ACCESS MODE clause
        self.access_mode: str | None = None  # SEQUENTIAL, RANDOM, DYNAMIC

        # RECORD KEY clause
        self.record_key: str | None = None
        self.record_key_source: str | None = None  # SOURCE IS data-name (IBM extension)

        # ALTERNATE RECORD KEY clause(s)
        self.alternate_keys: list[dict[str, Any]] = (
            []
        )  # [{key, duplicates_allowed, password}]

        # FILE STATUS clause
        self.file_status: str | None = None
        self.file_status_vsam: str | None = None  # Second status variable for VSAM

        # RELATIVE KEY clause
        self.relative_key: str | None = None

        # RESERVE clause
        self.reserve_areas: int | None = None

        # PADDING CHARACTER clause
        self.padding_character: str | None = None

        # RECORD DELIMITER clause
        self.record_delimiter: str | None = None  # STANDARD-1 or identifier

        # PASSWORD clause
        self.password: str | None = None

        # LOCK MODE clause
        self.lock_mode: str | None = None  # MANUAL, AUTOMATIC, EXCLUSIVE
        self.lock_on: str | None = None  # RECORD, MULTIPLE RECORDS
        self.lock_with_rollback: bool = False

        # SHARING clause
        self.sharing_mode: str | None = None  # ALL, NO OTHER, READ ONLY

    def set_file_name(self, name: str, is_optional: bool = False) -> None:
        """Set the file name being selected."""
        self.file_name = name
        self.is_optional = is_optional
        self._add_unique_operand(name, front=True)

    def set_assign_to(
        self,
        assign_value: str,
        device_type: str | None = None,
        external_name: str | None = None,
    ) -> None:
        """Set the ASSIGN TO clause value with optional device type."""
        self.assign_to = assign_value
        self.assign_device_type = device_type
        self.assign_external_name = external_name
        self._add_unique_operand(assign_value)

    def set_organization(self, org: str) -> None:
        """Set the ORGANIZATION clause."""
        self.organization = org.upper()

    def set_access_mode(self, mode: str) -> None:
        """Set the ACCESS MODE clause."""
        self.access_mode = mode.upper()

    def set_record_key(self, key: str, source: str | None = None) -> None:
        """Set the RECORD KEY clause."""
        self.record_key = key
        self.record_key_source = source

    def add_alternate_key(
        self, key: str, duplicates_allowed: bool = False, password: str | None = None
    ) -> None:
        """Add an ALTERNATE RECORD KEY clause."""
        self.alternate_keys.append(
            {"key": key, "duplicates_allowed": duplicates_allowed, "password": password}
        )

    def set_file_status(self, status: str, vsam_status: str | None = None) -> None:
        """Set the FILE STATUS clause."""
        self.file_status = status
        self.file_status_vsam = vsam_status

    def set_relative_key(self, key: str) -> None:
        """Set the RELATIVE KEY clause."""
        self.relative_key = key

    def set_reserve_areas(self, areas: int) -> None:
        """Set the RESERVE clause."""
        self.reserve_areas = areas

    def set_padding_character(self, character: str) -> None:
        """Set the PADDING CHARACTER clause."""
        self.padding_character = character

    def set_record_delimiter(self, delimiter: str) -> None:
        """Set the RECORD DELIMITER clause."""
        self.record_delimiter = delimiter

    def set_password(self, password: str) -> None:
        """Set the PASSWORD clause."""
        self.password = password

    def set_lock_mode(
        self, mode: str, lock_on: str | None = None, with_rollback: bool = False
    ) -> None:
        """Set the LOCK MODE clause."""
        self.lock_mode = mode.upper()
        self.lock_on = lock_on
        self.lock_with_rollback = with_rollback

    def set_sharing_mode(self, mode: str) -> None:
        """Set the SHARING clause."""
        self.sharing_mode = mode.upper()

    def to_dict(self) -> dict[str, Any]:
        """Convert SELECT statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "is_optional": self.is_optional,
                "assign_to": self.assign_to,
                "assign_device_type": self.assign_device_type,
                "assign_external_name": self.assign_external_name,
                "organization": self.organization,
                "access_mode": self.access_mode,
                "record_key": self.record_key,
                "record_key_source": self.record_key_source,
                "alternate_keys": self.alternate_keys,
                "file_status": self.file_status,
                "file_status_vsam": self.file_status_vsam,
                "relative_key": self.relative_key,
                "reserve_areas": self.reserve_areas,
                "padding_character": self.padding_character,
                "record_delimiter": self.record_delimiter,
                "password": self.password,
                "lock_mode": self.lock_mode,
                "lock_on": self.lock_on,
                "lock_with_rollback": self.lock_with_rollback,
                "sharing_mode": self.sharing_mode,
            }
        )
        return result


class CopyStatement(CobolStatement):
    """AST node for COPY statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("COPY", location)
        self.copybook_name: str | None = None
        self.library_name: str | None = None
        self.suppressions: list[str] = []
        self.replacements: list[dict[str, str]] = []

    def set_copybook_name(self, name: str) -> None:
        """Set the copybook name."""
        self.copybook_name = name
        self._add_unique_operand(name, front=True)

    def set_library_name(self, library: str) -> None:
        """Set the IN/OF library name."""
        self.library_name = library
        self._add_unique_operand(library)

    def add_suppression(self, suppression: str) -> None:
        """Add a SUPPRESS phrase."""
        self.suppressions.append(suppression)

    def add_replacement(self, old_text: str, new_text: str) -> None:
        """Add a REPLACING phrase."""
        self.replacements.append({"old_text": old_text, "new_text": new_text})

    def to_dict(self) -> dict[str, Any]:
        """Convert COPY statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "copybook_name": self.copybook_name,
                "library_name": self.library_name,
                "suppressions": self.suppressions,
                "replacements": self.replacements,
            }
        )
        return result


class ContinueStatement(CobolStatement):
    """AST node for CONTINUE statements (no-op)."""

    def __init__(self, location: SourceLocation):
        super().__init__("CONTINUE", location)

    def to_dict(self) -> dict[str, Any]:
        return super().to_dict()


class EjectStatement(CobolStatement):
    """AST node for EJECT statements (compiler-directing listing no-op).

    EJECT forces a page break in the compiler source listing; it has no
    effect on program logic. Recognizing it as its own statement (rather
    than leaving it as a bare unrecognized IDENTIFIER) keeps it from being
    misread as a paragraph name when written ``EJECT.`` between two real
    paragraphs -- see tests/regression/test_eject_statement.py.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("EJECT", location)

    def to_dict(self) -> dict[str, Any]:
        return super().to_dict()


class ExitStatement(CobolStatement):
    """AST node for EXIT statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("EXIT", location)
        self.exit_type: str | None = None  # PROGRAM, SECTION, PARAGRAPH, PERFORM

    def set_exit_type(self, exit_type: str) -> None:
        self.exit_type = exit_type.upper()

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["exit_type"] = self.exit_type
        return result


class GobackStatement(CobolStatement):
    """AST node for GOBACK statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("GOBACK", location)
        self.returning_value: str | None = None

    def set_returning_value(self, value: str) -> None:
        self.returning_value = value

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["returning_value"] = self.returning_value
        return result


class CancelStatement(CobolStatement):
    """AST node for CANCEL statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("CANCEL", location)
        self.program_names: list[str] = []

    def add_program_name(self, name: str) -> None:
        self.program_names.append(name)
        self._add_unique_operand(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["program_names"] = self.program_names
        return result


class AlterStatement(CobolStatement):
    """AST node for ALTER statements (obsolete)."""

    def __init__(self, location: SourceLocation):
        super().__init__("ALTER", location)
        self.alterations: list[dict[str, str]] = []

    def add_alteration(self, from_paragraph: str, to_paragraph: str) -> None:
        self.alterations.append(
            {"from_paragraph": from_paragraph, "to_paragraph": to_paragraph}
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["alterations"] = self.alterations
        return result


class GenerateStatement(CobolStatement):
    """AST node for GENERATE statements (Report Writer)."""

    def __init__(self, location: SourceLocation):
        super().__init__("GENERATE", location)
        self.report_name: str | None = None

    def set_report_name(self, name: str) -> None:
        self.report_name = name
        self._add_unique_operand(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["report_name"] = self.report_name
        return result


class XmlJsonStatement(CobolStatement):
    """AST node for XML/JSON GENERATE and PARSE statements (IBM Enterprise).

    Historically the leading XML/JSON keyword was silently skipped and the
    remainder mis-parsed as a Report Writer GENERATE. This node preserves the
    verb (``XML``/``JSON``), the action (``GENERATE``/``PARSE``), the primary
    operands, and the raw text of any trailing clauses (COUNT IN, WITH
    ENCODING, NAMESPACE, PROCESSING PROCEDURE, ON EXCEPTION, ...).
    """

    def __init__(self, verb: str, action: str, location: SourceLocation):
        super().__init__(f"{verb} {action}", location)
        self.verb = verb  # "XML" | "JSON"
        self.action = action  # "GENERATE" | "PARSE"
        # GENERATE: receiving item; PARSE: the item being parsed
        self.primary_operand: str | None = None
        # GENERATE only: the FROM source item
        self.from_item: str | None = None
        # Raw text of trailing clauses, preserved rather than dropped
        self.clause_text: str | None = None

    def set_primary_operand(self, name: str) -> None:
        self.primary_operand = name
        self._add_unique_operand(name)

    def set_from_item(self, name: str) -> None:
        self.from_item = name
        self._add_unique_operand(name)

    def set_clause_text(self, text: str) -> None:
        self.clause_text = text or None

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "verb": self.verb,
                "action": self.action,
                "primary_operand": self.primary_operand,
                "from_item": self.from_item,
                "clause_text": self.clause_text,
            }
        )
        return result


class ReleaseStatement(CobolStatement):
    """AST node for RELEASE statements (sort input)."""

    def __init__(self, location: SourceLocation):
        super().__init__("RELEASE", location)
        self.record_name: str | None = None
        self.from_source: str | None = None

    def set_record_name(self, name: str) -> None:
        self.record_name = name
        self._add_unique_operand(name)

    def set_from_source(self, source: str) -> None:
        self.from_source = source

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {"record_name": self.record_name, "from_source": self.from_source}
        )
        return result


class ReturnStatement(CobolStatement):
    """AST node for RETURN statements (sort output)."""

    def __init__(self, location: SourceLocation):
        super().__init__("RETURN", location)
        self.file_name: str | None = None
        self.into_target: str | None = None
        self.at_end_clause: list[CobolStatement] | None = None
        self.not_at_end_clause: list[CobolStatement] | None = None

    def set_file_name(self, name: str) -> None:
        self.file_name = name
        self._add_unique_operand(name)

    def set_into_target(self, target: str) -> None:
        self.into_target = target

    def set_at_end_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("at_end_clause", statements)

    def set_not_at_end_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("not_at_end_clause", statements)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update({"file_name": self.file_name, "into_target": self.into_target})
        result.update(
            self._serialize_clauses(
                "at_end_clause", "not_at_end_clause", omit_empty=True
            )
        )
        return result


class UseStatement(CobolStatement):
    """AST node for USE statements (declaratives)."""

    def __init__(self, location: SourceLocation):
        super().__init__("USE", location)
        self.use_type: str | None = None  # EXCEPTION, ERROR, DEBUGGING, REPORTING
        self.is_global: bool = False
        self.file_names: list[str] = []

    def set_use_type(self, use_type: str) -> None:
        self.use_type = use_type.upper()

    def set_global(self, is_global: bool = True) -> None:
        self.is_global = is_global

    def add_file_name(self, name: str) -> None:
        self.file_names.append(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "use_type": self.use_type,
                "is_global": self.is_global,
                "file_names": self.file_names,
            }
        )
        return result


class SortStatement(CobolStatement):
    """AST node for SORT statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("SORT", location)
        self.file_name: str | None = None
        self.keys: list[dict[str, str]] = []  # [{"field": str, "order": str}]
        self.duplicates_in_order: bool = False
        self.collating_sequence: str | None = None
        self.input_procedure: str | None = None
        self.input_procedure_thru: str | None = None
        self.output_procedure: str | None = None
        self.output_procedure_thru: str | None = None
        self.using_files: list[str] = []
        self.giving_files: list[str] = []

    def set_file_name(self, name: str) -> None:
        self.file_name = name
        self._add_unique_operand(name)

    def add_key(self, field: str, order: str = "ASCENDING") -> None:
        self.keys.append({"field": field, "order": order.upper()})

    def set_input_procedure(self, name: str, thru: str | None = None) -> None:
        self.input_procedure = name
        self.input_procedure_thru = thru

    def set_output_procedure(self, name: str, thru: str | None = None) -> None:
        self.output_procedure = name
        self.output_procedure_thru = thru

    def add_using_file(self, name: str) -> None:
        self.using_files.append(name)

    def add_giving_file(self, name: str) -> None:
        self.giving_files.append(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "keys": self.keys,
                "duplicates_in_order": self.duplicates_in_order,
                "collating_sequence": self.collating_sequence,
                "input_procedure": self.input_procedure,
                "input_procedure_thru": self.input_procedure_thru,
                "output_procedure": self.output_procedure,
                "output_procedure_thru": self.output_procedure_thru,
                "using_files": self.using_files,
                "giving_files": self.giving_files,
            }
        )
        return result


class MergeStatement(CobolStatement):
    """AST node for MERGE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("MERGE", location)
        self.file_name: str | None = None
        self.keys: list[dict[str, str]] = []
        self.collating_sequence: str | None = None
        self.output_procedure: str | None = None
        self.output_procedure_thru: str | None = None
        self.using_files: list[str] = []
        self.giving_files: list[str] = []

    def set_file_name(self, name: str) -> None:
        self.file_name = name
        self._add_unique_operand(name)

    def add_key(self, field: str, order: str = "ASCENDING") -> None:
        self.keys.append({"field": field, "order": order.upper()})

    def set_output_procedure(self, name: str, thru: str | None = None) -> None:
        self.output_procedure = name
        self.output_procedure_thru = thru

    def add_using_file(self, name: str) -> None:
        self.using_files.append(name)

    def add_giving_file(self, name: str) -> None:
        self.giving_files.append(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "keys": self.keys,
                "collating_sequence": self.collating_sequence,
                "output_procedure": self.output_procedure,
                "output_procedure_thru": self.output_procedure_thru,
                "using_files": self.using_files,
                "giving_files": self.giving_files,
            }
        )
        return result


class CommitStatement(CobolStatement):
    """AST node for COMMIT statements (transaction control).

    Syntax: COMMIT
    Commits the current unit of work in DB2/CICS embedded SQL programs.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("COMMIT", location)

    def to_dict(self) -> dict[str, Any]:
        return super().to_dict()


class RollbackStatement(CobolStatement):
    """AST node for ROLLBACK statements (transaction control).

    Syntax: ROLLBACK [WORK]
    Rolls back the current unit of work in DB2/CICS embedded SQL programs.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("ROLLBACK", location)
        self.rollback_work: bool = False  # ROLLBACK WORK variant

    def set_rollback_work(self, value: bool = True) -> None:
        """Mark that the WORK keyword was present."""
        self.rollback_work = value

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["rollback_work"] = self.rollback_work
        return result
