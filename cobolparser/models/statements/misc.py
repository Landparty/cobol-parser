"""
Miscellaneous statement AST nodes (SELECT, COPY).
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
        self.record_key_source: str | None = (
            None  # SOURCE IS data-name (IBM extension)
        )

        # ALTERNATE RECORD KEY clause(s)
        self.alternate_keys: list[
            dict[str, Any]
        ] = []  # [{key, duplicates_allowed, password}]

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
        if name not in self.operands:
            self.operands.insert(0, name)

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
        if assign_value not in self.operands:
            self.operands.append(assign_value)

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
        if name not in self.operands:
            self.operands.insert(0, name)

    def set_library_name(self, library: str) -> None:
        """Set the IN/OF library name."""
        self.library_name = library
        if library not in self.operands:
            self.operands.append(library)

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
