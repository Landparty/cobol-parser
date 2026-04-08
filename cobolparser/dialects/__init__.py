"""COBOL dialect support package.

This package provides implementations of various COBOL dialects including:
- IBM Enterprise COBOL (z/OS)
- ANSI COBOL standards
- Micro Focus COBOL
- GnuCOBOL extensions
"""

from .ibm_enterprise import IBMEnterpriseCobol

__all__ = [
    "IBMEnterpriseCobol",
]
