"""
Path resolution and validation for copybook files.

This module handles locating copybook files in search directories,
normalizing paths for cross-platform compatibility, and validating
paths to prevent security vulnerabilities like path traversal attacks.
"""

import os
import sys
from pathlib import Path
from typing import Optional
from .models import CopybookSearchPath
from . import PathTraversalError, CopybookNotFoundError


def normalize_path(path: str) -> str:
    """
    Normalize file path to OS-native separator format.
    
    Converts forward slashes to backslashes on Windows,
    and ensures consistent path representation across platforms.
    
    Args:
        path: Input path with any separator style
        
    Returns:
        Normalized path with OS-native separators
        
    Example:
        >>> normalize_path("copybooks/employee.cpy")  # On Windows
        'copybooks\\employee.cpy'
    """
    # Convert to Path object and back to string for normalization
    return str(Path(path).as_posix() if sys.platform != "win32" else Path(path))


def validate_path_within_directory(file_path: str, base_directory: str) -> bool:
    """
    Validate that a resolved path remains within the base directory.
    
    Prevents path traversal attacks by rejecting paths containing ".."
    or those that resolve outside the configured search directories.
    
    Args:
        file_path: The file path to validate
        base_directory: The base directory that must contain the file
        
    Returns:
        True if path is valid and within base directory
        
    Raises:
        PathTraversalError: If path attempts to escape base directory
        
    Example:
        >>> validate_path_within_directory("../etc/passwd", "/home/user/copybooks")
        PathTraversalError: Path traversal attempt detected
    """
    # Check for obvious traversal patterns
    if ".." in file_path:
        raise PathTraversalError(file_path)
    
    # Resolve both paths to absolute form
    try:
        resolved_file = Path(file_path).resolve()
        resolved_base = Path(base_directory).resolve()
        
        # Check if file path is within base directory
        try:
            resolved_file.relative_to(resolved_base)
            return True
        except ValueError:
            # Path is not relative to base directory
            raise PathTraversalError(
                file_path,
                f"Resolved path '{resolved_file}' is outside search directory '{resolved_base}'"
            )
    except Exception as e:
        if isinstance(e, PathTraversalError):
            raise
        raise PathTraversalError(file_path, f"Path validation failed: {str(e)}")


def find_copybook_file(
    member_name: str,
    search_config: CopybookSearchPath,
    library_qualifier: Optional[str] = None
) -> str:
    """
    Locate a copybook file in the configured search paths.
    
    Searches for the member name with various extensions (.cpy, .CPY, .cbl, etc.)
    in the configured search directories. If library_qualifier is provided,
    searches in subdirectories matching the library name.
    
    Args:
        member_name: Name of the copybook member to find
        search_config: Search configuration with directories and extensions
        library_qualifier: Optional library name for subdirectory search
        
    Returns:
        Absolute path to the found copybook file
        
    Raises:
        CopybookNotFoundError: If copybook cannot be found in any search path
        PathTraversalError: If path validation fails
        
    Example:
        >>> config = CopybookSearchPath(directories=["/copybooks"])
        >>> find_copybook_file("EMPLOYEE", config)
        '/copybooks/EMPLOYEE.cpy'
    """
    search_dirs = search_config.directories
    extensions = search_config.extensions
    
    # Build list of possible filenames
    possible_names = [member_name]  # Try exact name first
    for ext in extensions:
        possible_names.append(f"{member_name}{ext}")
    
    # Search in each directory
    for search_dir in search_dirs:
        # If library qualifier provided, add it as a subdirectory
        if library_qualifier:
            search_dir = os.path.join(search_dir, library_qualifier)
        
        # Try each possible filename
        for filename in possible_names:
            file_path = os.path.join(search_dir, filename)
            
            # Normalize path
            file_path = normalize_path(file_path)
            
            # Check if file exists
            if os.path.isfile(file_path):
                # Validate path is within search directory
                validate_path_within_directory(file_path, search_dir)
                return os.path.abspath(file_path)
    
    # Copybook not found in any search path
    raise CopybookNotFoundError(member_name, search_dirs)


class PathResolver:
    """
    Wrapper class for path resolution functionality.
    
    Provides a unified interface for resolving copybook file paths
    with integrated validation and search configuration.
    
    Attributes:
        search_config: Configuration for copybook search paths and extensions
    """
    
    def __init__(self, search_config: CopybookSearchPath):
        """
        Initialize path resolver with search configuration.
        
        Args:
            search_config: Search path configuration
        """
        self.search_config = search_config
    
    def resolve(self, member_name: str, library_qualifier: Optional[str] = None) -> str:
        """
        Resolve a copybook member name to an absolute file path.
        
        Args:
            member_name: Copybook member name
            library_qualifier: Optional library name
            
        Returns:
            Absolute path to copybook file
            
        Raises:
            CopybookNotFoundError: If copybook not found
            PathTraversalError: If path validation fails
        """
        return find_copybook_file(member_name, self.search_config, library_qualifier)
    
    def normalize(self, path: str) -> str:
        """
        Normalize a file path to OS-native format.
        
        Args:
            path: Input path
            
        Returns:
            Normalized path
        """
        return normalize_path(path)
    
    def validate(self, file_path: str, base_directory: str) -> bool:
        """
        Validate that a file path is within a base directory.
        
        Args:
            file_path: Path to validate
            base_directory: Base directory
            
        Returns:
            True if valid
            
        Raises:
            PathTraversalError: If validation fails
        """
        return validate_path_within_directory(file_path, base_directory)


__all__ = [
    'normalize_path',
    'validate_path_within_directory',
    'find_copybook_file',
    'PathResolver',
]
