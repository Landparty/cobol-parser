"""
COBOL data item AST nodes with PICTURE clauses and usage information.

This module implements AST nodes for COBOL data definitions including
data items, PICTURE clauses, OCCURS clauses, and IBM-specific data types.
"""

import re
from typing import Any

from .ast_base import ASTNode, SourceLocation

# Pre-compiled regex patterns for PictureClause parsing (avoids re-compilation per instance)
_PIC_P_FACTOR_RE = re.compile(r"P(\((\d+)\))?")
_PIC_ALPHA_RE = re.compile(r"([XA])(\((\d+)\))?$")
_PIC_BASIC_NUMERIC_RE = re.compile(r"S?9(\((\d+)\))?$")
_PIC_SIGNED_RE = re.compile(r"S(9+|\((\d+)\)|9\((\d+)\))$")
_PIC_LEFT_V_RE = re.compile(r"S?(9+|9\((\d+)\))$")
_PIC_RIGHT_V_RE = re.compile(r"(9+|9\((\d+)\))$")
_PIC_SCALING_LEFT_RE = re.compile(r"S?P(\((\d+)\))?9+$")
_PIC_SCALING_RIGHT_RE = re.compile(r"S?9+P(\((\d+)\))?$")
_PIC_EDITED_INT_RE = re.compile(r"9(\((\d+)\))?|9+$")
_PIC_COMPLEX_RE = re.compile(r"S?(9+)V(9+)$")
_PIC_DIGIT_X_RE = re.compile(r"[9X]")
_PIC_NINE_RE = re.compile(r"9")


class PictureClause(ASTNode):
    """AST node for COBOL PICTURE clauses."""

    def __init__(self, pattern: str, location: SourceLocation):
        super().__init__("PictureClause", location)
        self.pattern = pattern
        self.size: int | None = None
        self.integer_digits: int | None = None
        self.decimal_digits: int | None = None
        self.total_digits: int | None = None
        self.is_signed: bool = False
        self.has_scaling_factor: bool = False
        self.scaling_factor: int = 0
        self.is_edited: bool = False
        self._parse_pattern()

    def _parse_pattern(self) -> None:
        """Parse the PICTURE pattern to extract size and digit information."""
        pattern = self.pattern

        # Cheap membership tests before regex work -- the regexes below
        # were being invoked even when they could not possibly match.
        if "S" in pattern:
            self.is_signed = True

        if "P" in pattern:
            p_matches = _PIC_P_FACTOR_RE.findall(pattern)
            if p_matches:
                self.has_scaling_factor = True
                if p_matches[0][1]:  # P(n) format
                    self.scaling_factor = int(p_matches[0][1])
                else:  # Single P
                    self.scaling_factor = 1

        # Use the first character as a cheap guard for the simple
        # alphanumeric branch below, so we avoid that regex when the
        # pattern cannot be X/A-based.
        first = pattern[0] if pattern else ""

        # 1. Basic alphanumeric patterns: X, X(n), A, A(n)
        if first == "X" or first == "A":
            alpha_match = _PIC_ALPHA_RE.match(pattern)
            if alpha_match:
                count_str = alpha_match.group(3)
                self.size = int(count_str) if count_str else 1
                return

        # 2. Basic numeric patterns: 9, 9(n)
        basic_numeric = _PIC_BASIC_NUMERIC_RE.match(self.pattern)
        if basic_numeric:
            count_str = basic_numeric.group(2)
            digit_count = int(count_str) if count_str else 1
            self.integer_digits = digit_count
            self.decimal_digits = 0
            self.total_digits = digit_count
            self.size = digit_count
            return

        # 3. Signed patterns: S9(n), S999, etc.
        signed_match = _PIC_SIGNED_RE.match(self.pattern)
        if signed_match:
            if signed_match.group(2):  # S(n) format
                digit_count = int(signed_match.group(2))
            elif signed_match.group(3):  # S9(n) format
                digit_count = int(signed_match.group(3))
            else:  # S999... format
                digit_count = len(signed_match.group(1))

            self.integer_digits = digit_count
            self.decimal_digits = 0
            self.total_digits = digit_count
            self.size = digit_count
            return

        # 4. Decimal patterns: split at V and parse each side
        if "V" in self.pattern:
            parts = self.pattern.split("V")
            if len(parts) == 2:
                left_part = parts[0]
                right_part = parts[1]

                # Parse integer part (before V)
                left_match = _PIC_LEFT_V_RE.match(left_part)
                if left_match:
                    if left_match.group(2):  # 9(n) format
                        integer_part = int(left_match.group(2))
                    else:  # 9999... format
                        integer_part = len(_PIC_NINE_RE.findall(left_part))
                else:
                    integer_part = 0  # SV format

                # Parse decimal part (after V)
                right_match = _PIC_RIGHT_V_RE.match(right_part)
                if right_match:
                    if right_match.group(2):  # 9(n) format
                        decimal_part = int(right_match.group(2))
                    else:  # 9999... format
                        decimal_part = len(_PIC_NINE_RE.findall(right_part))
                else:
                    decimal_part = 0

                self.integer_digits = integer_part
                self.decimal_digits = decimal_part
                self.total_digits = integer_part + decimal_part
                self.size = self.total_digits
                return

        # 5. Leading decimal patterns: SV9(n), V9(n) - already handled above in V parsing
        # This is redundant now since we handle V patterns above

        # 6. Scaling factor patterns: SP(n)9, S9P(n)
        scaling_match = _PIC_SCALING_LEFT_RE.match(
            self.pattern
        ) or _PIC_SCALING_RIGHT_RE.match(self.pattern)
        if scaling_match:
            # Count digits (9s)
            digit_count = len(_PIC_NINE_RE.findall(self.pattern))
            self.integer_digits = digit_count
            self.decimal_digits = 0
            self.total_digits = digit_count
            self.size = digit_count
            return

        # 7. Display numeric edited patterns: -9(n), -9(n).9(n), -.9(n), -99.99
        if self.pattern.startswith("-"):
            self.is_numeric_edited = True
            pattern_without_minus = self.pattern[1:]  # Remove leading minus
            integer_part = 0
            decimal_part = 0

            if "." in pattern_without_minus:
                parts = pattern_without_minus.split(".")
                int_part = parts[0] if parts[0] else ""
                dec_part = parts[1] if len(parts) > 1 else ""

                # Parse integer part
                if int_part:
                    int_match = _PIC_EDITED_INT_RE.match(int_part)
                    if int_match:
                        if int_match.group(2):  # 9(n) format
                            integer_part = int(int_match.group(2))
                        else:  # 9+ format
                            integer_part = len(_PIC_NINE_RE.findall(int_part))

                # Parse decimal part
                if dec_part:
                    dec_match = _PIC_EDITED_INT_RE.match(dec_part)
                    if dec_match:
                        if dec_match.group(2):  # 9(n) format
                            decimal_part = int(dec_match.group(2))
                        else:  # 9+ format
                            decimal_part = len(_PIC_NINE_RE.findall(dec_part))
            else:
                # No decimal point, just integer part
                int_match = _PIC_EDITED_INT_RE.match(pattern_without_minus)
                if int_match:
                    if int_match.group(2):  # 9(n) format
                        integer_part = int(int_match.group(2))
                    else:  # 9+ format
                        integer_part = len(_PIC_NINE_RE.findall(pattern_without_minus))

            self.integer_digits = integer_part
            self.decimal_digits = decimal_part
            self.total_digits = integer_part + decimal_part
            self.size = self.total_digits + 1  # +1 for the sign/decimal point
            return

        # 8. Complex patterns with repetition: S999V999, etc.
        complex_match = _PIC_COMPLEX_RE.match(self.pattern)
        if complex_match:
            integer_part = len(complex_match.group(1))
            decimal_part = len(complex_match.group(2))

            self.integer_digits = integer_part
            self.decimal_digits = decimal_part
            self.total_digits = integer_part + decimal_part
            self.size = self.total_digits
            return

        # 8. Fallback for unrecognized patterns
        # Count all 9s and Xs to estimate size
        digit_count = len(_PIC_DIGIT_X_RE.findall(self.pattern))
        if digit_count > 0:
            self.size = digit_count
            if "9" in self.pattern:
                self.total_digits = digit_count
                # Estimate integer vs decimal based on V
                if "V" in self.pattern:
                    v_pos = self.pattern.find("V")
                    integer_nines = len(_PIC_NINE_RE.findall(self.pattern[:v_pos]))
                    decimal_nines = len(_PIC_NINE_RE.findall(self.pattern[v_pos:]))
                    self.integer_digits = integer_nines
                    self.decimal_digits = decimal_nines
                else:
                    self.integer_digits = digit_count
                    self.decimal_digits = 0
        else:
            # Default size if nothing else matches
            self.size = 1

    def to_dict(self) -> dict[str, Any]:
        """Convert PICTURE clause to dictionary representation."""
        return {
            "node_type": self.node_type,
            "pattern": self.pattern,
            "size": self.size,
            "integer_digits": self.integer_digits,
            "decimal_digits": self.decimal_digits,
            "total_digits": self.total_digits,
            "is_signed": self.is_signed,
            "has_scaling_factor": self.has_scaling_factor,
            "scaling_factor": self.scaling_factor,
            "is_edited": self.is_edited,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


class OccursClause(ASTNode):
    """AST node for COBOL OCCURS clauses (arrays/tables)."""

    def __init__(self, location: SourceLocation):
        super().__init__("OccursClause", location)
        self.min_times: int | None = None
        self.max_times: int | None = None
        self.depending_on: str | None = None
        self.indexed_by: str | None = None

    @property
    def times(self) -> int | None:
        """Get the OCCURS times (for fixed OCCURS)."""
        if self.min_times == self.max_times:
            return self.min_times
        return self.max_times  # Fallback to max_times

    def set_fixed_occurs(self, times: int) -> None:
        """Set fixed OCCURS count (e.g., OCCURS 10 TIMES)."""
        self.min_times = times
        self.max_times = times

    def set_variable_occurs(
        self, min_times: int, max_times: int, depending_on: str
    ) -> None:
        """Set variable OCCURS (e.g., OCCURS 1 TO 100 TIMES DEPENDING ON)."""
        self.min_times = min_times
        self.max_times = max_times
        self.depending_on = depending_on

    def set_indexed_by(self, index_name: str) -> None:
        """Set INDEXED BY clause."""
        self.indexed_by = index_name

    def to_dict(self) -> dict[str, Any]:
        """Convert OCCURS clause to dictionary representation."""
        return {
            "node_type": self.node_type,
            "min_times": self.min_times,
            "max_times": self.max_times,
            "depending_on": self.depending_on,
            "indexed_by": self.indexed_by,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


class CobolDataItem(ASTNode):
    """AST node for COBOL data item definitions."""

    def __init__(self, name: str, level: int, location: SourceLocation):
        super().__init__("DataItem", location)
        self.name = name
        self.level = level
        self.picture_clause: PictureClause | None = None
        self.usage: str = "DISPLAY"  # Default usage
        self.value_clause: str | None = None
        self.occurs_clause: OccursClause | None = None
        self.redefines: str | None = None
        self.is_filler: bool = name.upper() == "FILLER"

    @property
    def initial_value(self) -> str | None:
        """Get the initial value (VALUE clause)."""
        return self.value_clause

    @initial_value.setter
    def initial_value(self, value: str) -> None:
        """Set the initial value (VALUE clause)."""
        self.value_clause = value

    def set_picture_clause(self, picture: PictureClause) -> None:
        """Set the PICTURE clause for this data item."""
        self.picture_clause = picture
        self.add_child(picture)

    def set_usage(self, usage: str) -> None:
        """Set the USAGE clause for this data item."""
        self.usage = usage

    def set_value_clause(self, value: str) -> None:
        """Set the VALUE clause for this data item."""
        self.value_clause = value

    def set_occurs_clause(self, occurs: OccursClause) -> None:
        """Set the OCCURS clause for this data item."""
        self.occurs_clause = occurs
        self.add_child(occurs)

    def set_redefines(self, redefines_item: str) -> None:
        """Set the REDEFINES clause for this data item."""
        self.redefines = redefines_item

    def is_group_item(self) -> bool:
        """Check if this is a group item (has CobolDataItem children, no PICTURE)."""
        cobol_data_children = [
            child for child in self.children if isinstance(child, CobolDataItem)
        ]
        return len(cobol_data_children) > 0 and self.picture_clause is None

    def is_elementary_item(self) -> bool:
        """Check if this is an elementary item (has PICTURE, no CobolDataItem children)."""
        cobol_data_children = [
            child for child in self.children if isinstance(child, CobolDataItem)
        ]
        return self.picture_clause is not None and len(cobol_data_children) == 0

    def get_elementary_items(self) -> list["CobolDataItem"]:
        """Get all elementary items under this data item."""
        elementary_items = []

        if self.is_elementary_item():
            elementary_items.append(self)
        else:
            for child in self.children:
                if isinstance(child, CobolDataItem):
                    elementary_items.extend(child.get_elementary_items())

        return elementary_items

    def get_all_children(self) -> list["CobolDataItem"]:
        """Get all child data items recursively."""
        all_children = []

        for child in self.children:
            if isinstance(child, CobolDataItem):
                all_children.append(child)
                all_children.extend(child.get_all_children())

        return all_children

    def calculate_size(self) -> int:
        """Calculate the size of this data item in bytes."""
        if self.is_elementary_item() and self.picture_clause:
            base_size = self.picture_clause.size or 0

            # Adjust for USAGE clauses
            if self.usage == "COMP-3":
                # COMP-3 (packed decimal): (digits + 1) / 2 rounded up
                if self.picture_clause.total_digits:
                    comp3_size = (self.picture_clause.total_digits + 1) // 2
                    if (self.picture_clause.total_digits + 1) % 2:
                        comp3_size += 1
                    base_size = comp3_size
            elif self.usage in ["COMP", "COMP-4", "COMP-5"]:
                # Binary: depends on digits
                if self.picture_clause.total_digits:
                    if self.picture_clause.total_digits <= 4:
                        base_size = 2
                    elif self.picture_clause.total_digits <= 9:
                        base_size = 4
                    else:
                        base_size = 8
            elif self.usage in ["COMP-1"]:
                base_size = 4  # Single precision float
            elif self.usage in ["COMP-2"]:
                base_size = 8  # Double precision float

            # Apply OCCURS clause
            if self.occurs_clause:
                occurs_count = self.occurs_clause.max_times or 1
                base_size *= occurs_count

            return base_size

        elif self.is_group_item():
            # Group item size is sum of children
            total_size = 0
            for child in self.children:
                if isinstance(child, CobolDataItem):
                    total_size += child.calculate_size()
            return total_size

        return 0

    def to_dict(self) -> dict[str, Any]:
        """Convert data item to dictionary representation."""
        result = {
            "node_type": self.node_type,
            "name": self.name,
            "level": self.level,
            "usage": self.usage,
            "is_filler": self.is_filler,
            "is_group_item": self.is_group_item(),
            "is_elementary_item": self.is_elementary_item(),
            "calculated_size": self.calculate_size(),
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }

        if self.picture_clause:
            result["picture_clause"] = self.picture_clause.to_dict()

        if self.value_clause:
            result["value_clause"] = self.value_clause

        if self.occurs_clause:
            result["occurs_clause"] = self.occurs_clause.to_dict()

        if self.redefines:
            result["redefines"] = self.redefines

        # Include child data items
        child_data_items = [
            child.to_dict()
            for child in self.children
            if isinstance(child, CobolDataItem)
        ]
        if child_data_items:
            result["children"] = child_data_items

        return result


# Update the placeholder in program.py to use the full implementation
def update_cobol_data_item_placeholder() -> None:
    """Update the CobolDataItem placeholder in program.py with full implementation."""
    # This would be handled by importing the real implementation
    pass


class ConditionNameItem(ASTNode):
    """AST node for COBOL level-88 condition name items.

    A condition name binds one or more VALUES to a boolean condition that
    can be tested in the Procedure Division (e.g. ``IF STATUS-OPEN PERFORM ...``).
    It is always stored as a child of the immediately preceding elementary data item.
    """

    def __init__(self, name: str, location: SourceLocation):
        super().__init__("ConditionNameItem", location)
        self.name = name
        self.values: list[str] = []

    def add_value(self, value: str) -> None:
        """Add a VALUE entry for this condition name."""
        self.values.append(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "name": self.name,
            "values": self.values,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


class RenamesItem(ASTNode):
    """AST node for COBOL level-66 RENAMES items.

    Declares a contiguous alias view over one or more existing data items.
    Always appears at the top level of a section (not nested under any 01-item).
    """

    def __init__(
        self,
        name: str,
        renames_from: str,
        location: SourceLocation,
        renames_through: str | None = None,
    ):
        super().__init__("RenamesItem", location)
        self.name = name
        self.renames_from = renames_from
        self.renames_through = renames_through

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "name": self.name,
            "renames_from": self.renames_from,
            "renames_through": self.renames_through,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


# Module exports
__all__ = [
    "PictureClause",
    "OccursClause",
    "CobolDataItem",
    "ConditionNameItem",
    "RenamesItem",
]
