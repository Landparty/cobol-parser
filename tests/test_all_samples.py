"""
Test runner script for all COBOL sample tests.
Run with: python -m pytest tests/test_all_samples.py -v
"""
import pytest
import sys
from pathlib import Path


def run_sample_tests():
    """Run all tests for COBOL samples."""
    
    # Configure pytest arguments
    pytest_args = [
        'tests/integration/test_sample_programs.py',
        'tests/unit/test_sample_features.py',
        'tests/contracts/test_sample_api_contracts.py',
        '-v',                    # Verbose output
        '--tb=short',            # Short traceback format
        '--color=yes',           # Colored output
        '-ra',                   # Show all test summary info
    ]
    
    # Run tests
    print("=" * 70)
    print("Running COBOL Sample Tests")
    print("=" * 70)
    print()
    
    exit_code = pytest.main(pytest_args)
    
    return exit_code


def run_sample_tests_with_coverage():
    """Run all sample tests with code coverage."""
    
    pytest_args = [
        'tests/integration/test_sample_programs.py',
        'tests/unit/test_sample_features.py',
        'tests/contracts/test_sample_api_contracts.py',
        '-v',
        '--cov=cobolparser',
        '--cov-report=html',
        '--cov-report=term',
        '--cov-fail-under=90',
    ]
    
    print("=" * 70)
    print("Running COBOL Sample Tests with Coverage")
    print("=" * 70)
    print()
    
    exit_code = pytest.main(pytest_args)
    
    return exit_code


def run_specific_sample_category(category: str):
    """Run tests for a specific category of samples."""
    
    category_map = {
        'basic': ['test_basic_samples', 'test_figurative_constants', 'test_picture'],
        'files': ['test_file_operations', 'test_sort_merge'],
        'control': ['test_control_flow', 'test_arithmetic'],
        'strings': ['test_string_operations'],
        'ibm': ['test_ibm_extensions'],
        'advanced': ['test_declaratives', 'test_special_names', 'test_report', 
                     'test_communication', 'test_screen'],
        'errors': ['test_error_recovery'],
        'contracts': ['test_sample_api_contracts'],
    }
    
    if category not in category_map:
        print(f"Unknown category: {category}")
        print(f"Available categories: {', '.join(category_map.keys())}")
        return 1
    
    # Run tests matching the category keywords
    pytest_args = [
        'tests/',
        '-v',
        '-k', ' or '.join(category_map[category]),
    ]
    
    print(f"Running tests for category: {category}")
    exit_code = pytest.main(pytest_args)
    
    return exit_code


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == 'coverage':
            exit_code = run_sample_tests_with_coverage()
        elif sys.argv[1] == 'category':
            if len(sys.argv) > 2:
                exit_code = run_specific_sample_category(sys.argv[2])
            else:
                print("Usage: python test_all_samples.py category <category_name>")
                exit_code = 1
        else:
            print("Usage: python test_all_samples.py [coverage|category <name>]")
            exit_code = 1
    else:
        exit_code = run_sample_tests()
    
    sys.exit(exit_code)
