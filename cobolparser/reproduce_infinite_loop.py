
import logging
import sys
from pathlib import Path

# Add parent directory to path to import cobolparser package
sys.path.append(str(Path(__file__).parent.parent))

from cobolparser import parse_cobol

# Configure logging
logging.basicConfig(level=logging.WARNING)


def test_parse_files():
    files = [
        "NC101A.CBL", "NC102A.CBL", "NC103A.CBL", "NC104A.CBL", "NC105A.CBL",
        "NC106A.CBL", "NC107A.CBL", "NC108M.CBL"
    ]
    for filename in files:
        file_path = Path(f"../examples/cobol/{filename}")
        print(f"[{filename}] Reading...")
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except FileNotFoundError:
            print(f"[{filename}] File not found")
            continue

        print(f"[{filename}] Starting parse...")
        try:
            result = parse_cobol(content)
            print(f"[{filename}] Parse finished. Success: {result.success}")
        except Exception as e:
            print(f"[{filename}] Exception: {e}")

if __name__ == "__main__":
    test_parse_files()

