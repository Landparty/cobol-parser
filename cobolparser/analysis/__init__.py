"""
Analysis utilities for COBOL AST.

This module provides tools for analyzing COBOL AST structures including
data flow analysis, call graph analysis, and value tracking.
"""

from .value_tracker import DynamicCallAnalyzer

__all__ = ["DynamicCallAnalyzer"]
