# Spec (Delta): AST Node Hierarchy

## Overview

Phase 5 established AST node hierarchy with factory validation. Phase 6 testing reveals need for enhanced validation and metadata tracking. This delta spec ensures proper node structure validation and source location tracking across all parser changes.

## Changes Required

### R1: Enhanced Validation
- Node type validation: all nodes have proper node_type
- Required field validation: factory enforces required fields per node type
- Type checking: field values match expected types (string, int, list, dict)
- Hierarchy validation: parent-child relationships properly established
- No behavioral changes to node classes

### R2: Metadata Tracking
- All nodes include location information (file, line, column)
- Location info preserved through continuation lines
- Error messages include source location
- Metadata available for IDE features (goto definition, hover, etc.)

### R3: Node Structure Validation
- EVALUATE statement: proper WHEN clause hierarchy
- PERFORM statement: VARYING clause structure
- IF statement: condition and body relationships
- All statement types validated

### R4: Backward Compatibility
- Existing node interfaces unchanged
- `to_dict()` method behavior unchanged
- All existing tests still pass
- JSON serialization compatible

## Acceptance Criteria

- [ ] Node validation enhanced in ASTNodeFactory
- [ ] test_evaluate_variants_sample passes (EVALUATE hierarchy correct)
- [ ] All statement node tests pass
- [ ] Metadata tracking validated in all critical paths
- [ ] No regressions in existing node tests
- [ ] JSON serialization still compatible

## Files Modified

- `cobolparser/core/ast_factory.py` - Enhanced validation
- `cobolparser/models/ast_base.py` - ASTNode class validation
- `cobolparser/models/statements.py` - Node structure validation tests

## Related Specs

- `evaluate-statement-hardening` (EVALUATE node validation)
- `statement-parser-coverage` (all statement nodes)
- `division-parser-coverage` (all division nodes)

## Validation Coverage

- Every node type has validation tests
- Location tracking tested for all nodes
- Parent-child relationships validated
- Metadata availability confirmed
