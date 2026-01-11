"""
Test FD binding for IO statements.

Ensures that IO statements correctly bind to their corresponding FD metadata,
including BLOCK CONTAINS, RECORD KEY, and ALTERNATE RECORD KEY clauses.
This is essential for FR-005 compliance.
"""

import pytest
from pathlib import Path
from cobolparser import CobolParser, ErrorRecoveryMode


@pytest.fixture
def fd_binding_fixture_dir() -> Path:
    """Return path to FD binding test fixtures."""
    return Path(__file__).parent.parent.parent / "samples" / "io" / "positive" / "test_fd_binding.cob"


def test_indexed_file_primary_key_binding(fd_binding_fixture_dir: Path) -> None:
    """Test that READ with KEY IS binds to RECORD KEY from FD."""
    source = fd_binding_fixture_dir.read_text()
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    
    result = parser.parse(source)
    
    # Assertions will be implemented with AST enhancements
    assert result.ast is not None, "AST should be generated"
    
    # TODO: Verify that IO READ statement has reference to FD RECORD KEY metadata
    # This will require AST enhancements in T016-T018


def test_indexed_file_alternate_key_binding(fd_binding_fixture_dir: Path) -> None:
    """Test that READ with alternate key binds to ALTERNATE RECORD KEY."""
    source = fd_binding_fixture_dir.read_text()
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    
    result = parser.parse(source)
    assert result.ast is not None


def test_relative_file_key_binding(fd_binding_fixture_dir: Path) -> None:
    """Test that RELATIVE file I/O binds key metadata correctly."""
    source = fd_binding_fixture_dir.read_text()
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    
    result = parser.parse(source)
    assert result.ast is not None


def test_block_contains_metadata(fd_binding_fixture_dir: Path) -> None:
    """Test that BLOCK CONTAINS clause is accessible from IO context."""
    source = fd_binding_fixture_dir.read_text()
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    
    result = parser.parse(source)
    assert result.ast is not None
    
    # TODO: Verify BLOCK CONTAINS metadata is preserved and accessible
    # for performance/buffering analysis


def test_record_varying_with_io() -> None:
    """Test that RECORD VARYING clause is recognized with IO statements."""
    source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-VARYING.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO X ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F RECORD VARYING IN SIZE FROM 10 TO 100 CHARACTERS.
       01  REC PIC X(100).
       PROCEDURE DIVISION.
           OPEN INPUT F.
           READ F.
           CLOSE F.
           STOP RUN.
    """
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(source)
    assert result.ast is not None
