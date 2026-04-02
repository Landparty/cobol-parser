"""IO statement error codes and diagnostic helpers.

These types were originally in cobolparser.plugins.core and were moved here
so that IO-specific domain logic lives alongside other IO analysis modules.
"""

from enum import Enum
from typing import ClassVar

from cobolparser._errors import ParseError


class IOErrorCode(Enum):
    """IO statement error codes per contract io-statement-ast.md"""

    # READ statement errors
    IO_READ_INVALID_KEY_ORDER = "IO_READ_INVALID_KEY_ORDER"  # INVALID KEY clause appears before KEY clause
    IO_READ_LOCK_ON_SEQUENTIAL = "IO_READ_LOCK_ON_SEQUENTIAL"  # WITH LOCK on sequential file
    IO_READ_AT_END_WITHOUT_FILE = "IO_READ_AT_END_WITHOUT_FILE"  # AT END without file reference

    # WRITE statement errors
    IO_WRITE_ADVANCING_INVALID_UNIT = "IO_WRITE_ADVANCING_INVALID_UNIT"  # Invalid unit in ADVANCING clause
    IO_WRITE_DELETE_INVALID_ORG = "IO_WRITE_DELETE_INVALID_ORG"  # DELETE clause on non-VSAM file

    # OPEN statement errors
    IO_OPEN_INVALID_MODE = "IO_OPEN_INVALID_MODE"  # Invalid OPEN mode
    IO_OPEN_REEL_ON_DISK = "IO_OPEN_REEL_ON_DISK"  # REEL clause on disk file

    # CLOSE statement errors
    IO_CLOSE_NO_REWIND_INVALID = "IO_CLOSE_NO_REWIND_INVALID"  # NO REWIND on non-tape file
    IO_CLOSE_WITH_LOCK_INVALID = "IO_CLOSE_WITH_LOCK_INVALID"  # WITH LOCK on sequential file

    # REWRITE statement errors
    IO_REWRITE_INVALID_ORG = "IO_REWRITE_INVALID_ORG"  # REWRITE on sequential file
    IO_REWRITE_INVALID_KEY_ORDER = "IO_REWRITE_INVALID_KEY_ORDER"  # Invalid INVALID KEY clause

    # DELETE statement errors
    IO_DELETE_INVALID_ORG = "IO_DELETE_INVALID_ORG"  # DELETE on sequential file
    IO_DELETE_INVALID_KEY_ORDER = "IO_DELETE_INVALID_KEY_ORDER"  # Invalid INVALID KEY clause

    # START statement errors
    IO_START_INVALID_ORG = "IO_START_INVALID_ORG"  # START on sequential file
    IO_START_MISSING_KEY = "IO_START_MISSING_KEY"  # START without KEY condition
    IO_START_INVALID_KEY_CONDITION = "IO_START_INVALID_KEY_CONDITION"  # Invalid key condition

    # ACCEPT/DISPLAY statement errors
    IO_ACCEPT_INVALID_FROM = "IO_ACCEPT_INVALID_FROM"  # Invalid FROM device
    IO_DISPLAY_INVALID_UPON = "IO_DISPLAY_INVALID_UPON"  # Invalid UPON device

    # UNLOCK statement errors
    IO_UNLOCK_INVALID_ORG = "IO_UNLOCK_INVALID_ORG"  # UNLOCK on sequential file

    # Generic IO errors
    IO_INVALID_LOCK = "IO_INVALID_LOCK"  # WITH LOCK invalid for this statement
    IO_INVALID_FILE_ORG = "IO_INVALID_FILE_ORG"  # File organization not supported for this statement
    IO_MISSING_REQUIRED_CLAUSE = "IO_MISSING_REQUIRED_CLAUSE"  # Required IO clause missing


class IODiagnosticHelper:
    """Helper class for generating IO-related diagnostics and error messages."""

    # Mapping of error codes to user-friendly messages
    ERROR_MESSAGES: ClassVar[dict[IOErrorCode, str]] = {
        IOErrorCode.IO_READ_INVALID_KEY_ORDER:
            "INVALID KEY clause must appear after KEY clause in READ statement",
        IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL:
            "WITH LOCK is not valid on sequential files; use indexed or relative file",
        IOErrorCode.IO_READ_AT_END_WITHOUT_FILE:
            "AT END clause requires READ to be operating on a file",

        IOErrorCode.IO_WRITE_ADVANCING_INVALID_UNIT:
            "ADVANCING clause requires valid unit (LINES or CHANNEL)",
        IOErrorCode.IO_WRITE_DELETE_INVALID_ORG:
            "DELETE clause in WRITE is only valid for VSAM (indexed) files",

        IOErrorCode.IO_OPEN_INVALID_MODE:
            "OPEN statement requires valid mode: INPUT, OUTPUT, I-O, or EXTEND",
        IOErrorCode.IO_OPEN_REEL_ON_DISK:
            "REEL clause is only valid for tape files (ORGANIZATION IS SEQUENTIAL)",

        IOErrorCode.IO_CLOSE_NO_REWIND_INVALID:
            "NO REWIND clause is only valid for tape files",
        IOErrorCode.IO_CLOSE_WITH_LOCK_INVALID:
            "WITH LOCK on CLOSE is not valid for sequential files",

        IOErrorCode.IO_REWRITE_INVALID_ORG:
            "REWRITE is only valid for indexed or relative files, not sequential",
        IOErrorCode.IO_REWRITE_INVALID_KEY_ORDER:
            "INVALID KEY clause in REWRITE must follow proper syntax",

        IOErrorCode.IO_DELETE_INVALID_ORG:
            "DELETE is only valid for indexed or relative files, not sequential",
        IOErrorCode.IO_DELETE_INVALID_KEY_ORDER:
            "INVALID KEY clause in DELETE must follow proper syntax",

        IOErrorCode.IO_START_INVALID_ORG:
            "START is only valid for indexed or relative files, not sequential",
        IOErrorCode.IO_START_MISSING_KEY:
            "START statement requires KEY clause with condition",
        IOErrorCode.IO_START_INVALID_KEY_CONDITION:
            "START KEY requires valid condition: EQUAL, GREATER, LESS, GREATER THAN, LESS THAN, etc.",

        IOErrorCode.IO_ACCEPT_INVALID_FROM:
            "ACCEPT FROM specifies invalid source device or environment variable",
        IOErrorCode.IO_DISPLAY_INVALID_UPON:
            "DISPLAY UPON specifies invalid device (use CONSOLE, DISPLAY, STANDARD-OUTPUT, etc.)",

        IOErrorCode.IO_UNLOCK_INVALID_ORG:
            "UNLOCK is only valid for indexed files with record locking",

        IOErrorCode.IO_INVALID_LOCK:
            "WITH LOCK clause is not valid for this statement or file organization",
        IOErrorCode.IO_INVALID_FILE_ORG:
            "File organization does not support this IO statement",
        IOErrorCode.IO_MISSING_REQUIRED_CLAUSE:
            "Required clause is missing from this IO statement",
    }

    @staticmethod
    def get_error_message(code: IOErrorCode) -> str:
        """Get user-friendly error message for IO error code."""
        return IODiagnosticHelper.ERROR_MESSAGES.get(code, f"IO Error: {code.value}")

    @staticmethod
    def create_io_error(
        code: IOErrorCode,
        line: int = 0,
        column: int = 0,
        context: str | None = None
    ) -> ParseError:
        """Create a ParseError for IO statement issues."""
        message = IODiagnosticHelper.get_error_message(code)
        if context:
            message = f"{message} ({context})"

        error = ParseError(message, line_number=line, column=column)
        error.code = code.value  # Add error code attribute
        return error

    @staticmethod
    def validate_io_statement_type(
        statement_type: str,
        file_organization: str | None = None
    ) -> IOErrorCode | None:
        """Validate IO statement against file organization.

        Returns error code if validation fails, None if valid.
        """
        if not file_organization:
            return None  # No organization info, skip validation

        org_upper = file_organization.upper()
        stmt_upper = statement_type.upper()

        # START, REWRITE, DELETE only valid on indexed/relative
        if stmt_upper in ("START", "REWRITE", "DELETE"):
            if org_upper not in ("INDEXED", "RELATIVE"):
                if stmt_upper == "START":
                    return IOErrorCode.IO_START_INVALID_ORG
                elif stmt_upper == "REWRITE":
                    return IOErrorCode.IO_REWRITE_INVALID_ORG
                elif stmt_upper == "DELETE":
                    return IOErrorCode.IO_DELETE_INVALID_ORG

        # UNLOCK only valid on indexed
        if stmt_upper == "UNLOCK":
            if org_upper != "INDEXED":
                return IOErrorCode.IO_UNLOCK_INVALID_ORG

        return None
