"""
Analysis utilities for COBOL AST.

This module provides tools for analyzing COBOL AST structures including
data flow analysis, call graph analysis, and value tracking.
"""

# Lazy import to avoid circular dependency with cobolparser.plugins
def __getattr__(name: str) -> object:
    if name == "DynamicCallAnalyzer":
        from .value_tracker import DynamicCallAnalyzer
        return DynamicCallAnalyzer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["DynamicCallAnalyzer"]
