# Spec: Fixed-Format Detection Improvement

## Overview

Fixed-format COBOL uses strict column positions (sequence 1-6, area A 8-11, area B 12-72). Auto-detection logic must robustly distinguish fixed-format from free-format COBOL.

## Requirements

### R1: Fixed-Format Column Detection
- Detect presence of sequence numbers (columns 1-6)
- Detect area A/B indicators
- Detect fixed-column alignment patterns
- Use heuristics: multiple lines with patterns in expected regions

### R2: Free-Format Fall-back
- If no fixed-format indicators found, treat as free-format
- No false positives (must not misidentify free-format as fixed)
- No false negatives (must detect valid fixed-format)

### R3: Explicit Parameter Support
- `preprocess_fixed=True`: force fixed-format interpretation
- `preprocess_fixed=False`: force free-format interpretation
- `preprocess_fixed=None` (default): auto-detect

### R4: Test File Handling
- Handle missing test files gracefully (create default test fixture or skip)
- IX103A.CBL: classic fixed-format IBM COBOL program
- Document test file requirements

### R5: Backward Compatibility
- Existing code using implicit fixed-format still works
- No change to parser API
- Detection heuristics don't affect valid programs

## Acceptance Criteria

- [ ] `test_fixed_format_auto_detection` passes
- [ ] Fixed-format programs detected correctly
- [ ] Free-format programs not misidentified as fixed
- [ ] Explicit `preprocess_fixed` parameter respected
- [ ] Test files available or handled gracefully
- [ ] Existing tests still pass (no regressions)

## Related Components

- `cobolparser/lexer.py` - Tokenization with format awareness
- `cobolparser/parser.py` - Format auto-detection logic
- Preprocessing pipeline (copybook expansion)

## Test Files

- `tests/samples/IX103A.CBL` - Fixed-format test program (IBM COBOL)
- Detection heuristics validated with diverse programs

## Dependencies

- Phase 6.1: Root cause analysis (diagnoses detection issue)
- Lexer infrastructure (token position tracking)
