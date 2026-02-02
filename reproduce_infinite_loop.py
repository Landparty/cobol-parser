
import logging
from pathlib import Path
from cobolparser import parse_cobol

# Configure logging
logging.basicConfig(level=logging.DEBUG)

def test_parse_nc102a():
    file_path = Path("examples/cobol/NC102A.CBL")
    print(f"Reading {file_path}")
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    print("Starting parse...")
    result = parse_cobol(content)
    print(f"Parse finished. Success: {result.success}")

if __name__ == "__main__":
    test_parse_nc102a()
