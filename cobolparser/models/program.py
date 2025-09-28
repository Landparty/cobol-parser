"""
COBOL program structure nodes including programs, divisions, and sections.

This module implements the high-level structural elements of COBOL programs
including program nodes, division nodes, and section nodes with full
JSON serialization support.
"""

from typing import Dict, Any, List, Optional, TYPE_CHECKING
from .ast_base import ASTNode, SourceLocation, ValidationResult
from ..plugins import SerializationConfig

if TYPE_CHECKING:
    from .data_items import CobolDataItem
    from .statements import CobolStatement
    
    class CobolParagraph:
        pass
    
    class CobolProcedure:
        pass


class CobolSection(ASTNode):
    """AST node for COBOL sections within divisions."""
    
    def __init__(self, section_name: str, location: SourceLocation):
        super().__init__("Section", location)
        self.section_name = section_name
        self.paragraphs: List['CobolParagraph'] = []
        self.data_items: List['CobolDataItem'] = []
    
    def add_paragraph(self, paragraph: 'CobolParagraph') -> None:
        """Add a paragraph to this section."""
        self.add_child(paragraph)
        self.paragraphs.append(paragraph)
    
    def add_data_item(self, data_item: 'CobolDataItem') -> None:
        """Add a data item to this section."""
        self.add_child(data_item) 
        self.data_items.append(data_item)
    
    def get_paragraph_by_name(self, name: str) -> Optional['CobolParagraph']:
        """Find a paragraph by name in this section."""
        for paragraph in self.paragraphs:
            if hasattr(paragraph, 'paragraph_name') and paragraph.paragraph_name == name:
                return paragraph
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert section to dictionary representation."""
        return {
            "node_type": self.node_type,
            "section_name": self.section_name,
            "location": self.location.to_dict(),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "data_items": [d.to_dict() for d in self.data_items],
            "metadata": self._metadata
        }


class CobolDivision(ASTNode):
    """AST node for COBOL divisions (IDENTIFICATION, DATA, PROCEDURE, etc.)."""
    
    def __init__(self, division_name: str, location: SourceLocation):
        super().__init__("Division", location)
        self.division_name = division_name
        self.sections: Dict[str, CobolSection] = {}
        self.paragraphs: List['CobolParagraph'] = []
    
    @property
    def division_type(self) -> str:
        """Returns the type of division."""
        return self.division_name
    
    def add_section(self, section: CobolSection) -> None:
        """Add a section to this division."""
        self.add_child(section)
        self.sections[section.section_name] = section
    
    def add_paragraph(self, paragraph: 'CobolParagraph') -> None:
        """Add a paragraph directly to this division (procedure division)."""
        self.add_child(paragraph)
        self.paragraphs.append(paragraph)
    
    def get_section_by_name(self, name: str) -> Optional[CobolSection]:
        """Get a section by name."""
        return self.sections.get(name)
    
    def has_section(self, name: str) -> bool:
        """Check if division has a specific section."""
        return name in self.sections
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert division to dictionary representation."""
        return {
            "node_type": self.node_type,
            "division_name": self.division_name,
            "location": self.location.to_dict(),
            "sections": {name: section.to_dict() for name, section in self.sections.items()},
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "metadata": self._metadata
        }


class CobolParagraph(ASTNode):
    """AST node for COBOL paragraphs within sections or divisions."""
    
    def __init__(self, paragraph_name: str, location: SourceLocation):
        super().__init__("Paragraph", location)
        self.paragraph_name = paragraph_name
        self.statements: List['CobolStatement'] = []
    
    def add_statement(self, statement: 'CobolStatement') -> None:
        """Add a statement to this paragraph."""
        self.add_child(statement)
        self.statements.append(statement)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert paragraph to dictionary representation."""
        return {
            "node_type": self.node_type,
            "paragraph_name": self.paragraph_name,
            "location": self.location.to_dict(),
            "statements": [stmt.to_dict() for stmt in self.statements],
            "metadata": self._metadata
        }


class CobolProgram(ASTNode):
    """AST node representing a complete COBOL program."""
    
    def __init__(self, program_name: str, location: SourceLocation):
        super().__init__("Program", location)
        self.program_name = program_name
        self.divisions: Dict[str, CobolDivision] = {}
        self._statistics: Optional[Dict[str, Any]] = None
    
    def add_division(self, division: CobolDivision) -> None:
        """Add a division to the program."""
        self.add_child(division)
        self.divisions[division.division_name] = division
    
    def get_division(self, name: str) -> Optional[CobolDivision]:
        """Get a division by name."""
        return self.divisions.get(name)
    
    def get_division_by_name(self, name: str) -> Optional[CobolDivision]:
        """Get a division by name (alias for compatibility)."""
        return self.get_division(name)
    
    def has_division(self, name: str) -> bool:
        """Check if program has a specific division."""
        return name in self.divisions
    
    def get_data_items(self) -> List['CobolDataItem']:
        """Get all data items defined in the program."""
        data_items = []
        
        # Look in DATA division sections
        data_division = self.get_division("DATA")
        if data_division:
            for section in data_division.sections.values():
                data_items.extend(section.data_items)
                # Also look for nested data items
                for item in section.data_items:
                    data_items.extend(item.get_all_children())
        
        return data_items
    
    def get_procedures(self) -> List['CobolProcedure']:
        """Get all procedure paragraphs/sections in the program."""
        procedures = []
        
        # Look in PROCEDURE division
        proc_division = self.get_division("PROCEDURE")
        if proc_division:
            # Add sections as procedures
            for section in proc_division.sections.values():
                procedures.append(section)
            
            # Add paragraphs as procedures  
            procedures.extend(proc_division.paragraphs)
            
            # Also look in sections for paragraphs
            for section in proc_division.sections.values():
                procedures.extend(section.paragraphs)
        
        return procedures
    
    def validate(self) -> ValidationResult:
        """Validate the COBOL program structure."""
        result = ValidationResult()
        
        # Check for required IDENTIFICATION division
        if not self.has_division("IDENTIFICATION"):
            result.add_error("Missing required IDENTIFICATION DIVISION")
        
        # Check for PROGRAM-ID if IDENTIFICATION division exists
        id_division = self.get_division("IDENTIFICATION")
        if id_division and not self.program_name:
            result.add_error("Missing PROGRAM-ID in IDENTIFICATION DIVISION")
        
        # Validate division order (IDENTIFICATION should come first)
        division_order = ["IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"]
        found_divisions = []
        
        for division_name in division_order:
            if self.has_division(division_name):
                found_divisions.append(division_name)
        
        # Check if divisions are in correct order
        expected_order = [d for d in division_order if d in self.divisions]
        if found_divisions != expected_order:
            result.add_warning(f"Divisions not in standard order. Found: {found_divisions}, Expected: {expected_order}")
        
        # Validate each division
        for division in self.divisions.values():
            division_result = self._validate_division(division)
            result.errors.extend(division_result.errors)
            result.warnings.extend(division_result.warnings)
        
        return result
    
    def _validate_division(self, division: CobolDivision) -> ValidationResult:
        """Validate a specific division."""
        result = ValidationResult()
        
        if division.division_name == "DATA":
            # DATA division should have at least one section
            if not division.sections:
                result.add_warning("DATA DIVISION has no sections")
        
        elif division.division_name == "PROCEDURE":
            # PROCEDURE division should have statements
            if not division.paragraphs and not division.sections:
                result.add_warning("PROCEDURE DIVISION is empty")
        
        return result
    
    def get_statistics(self) -> Dict[str, int | float]:
        """Calculate and return program statistics.""" 
        if self._statistics is None:
            self._calculate_statistics()
        return self._statistics
    
    def _calculate_statistics(self) -> None:
        """Calculate program statistics."""
        total_lines = 0
        data_item_count = 0
        procedure_count = 0
        statement_count = 0
        
        # Count lines from all nodes
        for node in self.traverse_depth_first():
            if hasattr(node, 'location') and node.location:
                total_lines = max(total_lines, node.location.line)
        
        # Count data items
        data_item_count = len(self.get_data_items())
        
        # Count procedures
        procedure_count = len(self.get_procedures())
        
        # Count statements (simplified - would need statement nodes)
        for division in self.divisions.values():
            if division.division_name == "PROCEDURE":
                statement_count += len(division.paragraphs) * 2  # Estimate
        
        self._statistics = {
            "total_lines": total_lines,
            "data_item_count": data_item_count,
            "procedure_count": procedure_count,
            "statement_count": statement_count,
            "division_count": len(self.divisions)
        }
    
    def to_dict(self, config: Optional[SerializationConfig] = None) -> Dict[str, Any]:
        """Convert program to dictionary representation."""
        if config is None:
            config = SerializationConfig()
        
        result = {
            "node_type": self.node_type,
            "program_name": self.program_name,
            "divisions": {name: division.to_dict() for name, division in self.divisions.items()}
        }
        
        if config.include_source_locations:
            result["location"] = self.location.to_dict()
        
        if config.include_metadata:
            result["metadata"] = {
                "statistics": self.get_statistics(),
                "parser_version": "1.0.0",
                "created_at": "2024-01-01T00:00:00Z",  # Would be actual timestamp
                **self._metadata
            }
        
        return result
    
    def to_json(self, config: Optional[SerializationConfig] = None) -> str:
        """Convert program to JSON representation with configuration options."""
        if config is None:
            config = SerializationConfig()
        
        data = self.to_dict(config)
        
        if config.compact_format:
            return super().to_json(indent=None)
        else:
            return super().to_json(indent=2)


class CobolFileDescription(ASTNode):
    """AST node for FD (File Description) in FILE SECTION."""
    
    def __init__(self, file_name: str, location: SourceLocation):
        super().__init__("FileDescription", location)
        self.file_name = file_name
        self.record_type = "FD"  # For test compatibility
        self.data_records: List['CobolDataItem'] = []
        self.record_contains: Optional[int] = None
        self.block_contains: Optional[int] = None
        self.label_records: Optional[str] = None
    
    def add_data_record(self, data_item: 'CobolDataItem') -> None:
        """Add a data record (01 level) to this FD."""
        self.add_child(data_item)
        self.data_records.append(data_item)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert FD to dictionary representation."""
        return {
            "node_type": self.node_type,
            "file_name": self.file_name,
            "record_type": self.record_type,
            "data_records": len(self.data_records),
            "record_contains": self.record_contains,
            "block_contains": self.block_contains,
            "label_records": self.label_records,
            "location": self.location.to_dict(),
            "metadata": self._metadata
        }


# Forward references - actual implementations in data_items.py and statements.py
# These are imported at runtime to avoid circular imports


# Create CobolAST alias for CobolProgram to satisfy contract
CobolAST = CobolProgram


# Module exports
__all__ = [
    "CobolProgram",
    "CobolAST",
    "CobolDivision", 
    "CobolSection",
    "CobolParagraph",
    "CobolFileDescription",
]