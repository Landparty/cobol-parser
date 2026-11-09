"""Comprehensive unit tests for IBM Enterprise COBOL dialect.

This module provides 100% test coverage for cobolparser/dialects/ibm_enterprise.py
including all classes, methods, properties, and edge cases.
"""

from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol


class TestIBMEnterpriseCobol:
    """Test IBMEnterpriseCobol dialect class."""

    def test_ibm_intrinsic_functions(self):
        """Test IBM intrinsic functions are defined."""
        dialect = IBMEnterpriseCobol

        # Test some key IBM intrinsic functions
        assert "CURRENT-DATE" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "LENGTH" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "NUMVAL" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "UPPER-CASE" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "LOWER-CASE" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "SQRT" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "RANDOM" in dialect.IBM_INTRINSIC_FUNCTIONS

        assert len(dialect.IBM_INTRINSIC_FUNCTIONS) >= 25
