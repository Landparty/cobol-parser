# Real-World COBOL Program Examples for CALL Statement Testing

## Overview
Added 8 comprehensive real-world COBOL program examples focusing on CALL statement variations and patterns found in production mainframe systems.

## Examples Created

### 1. **call_statements_basic.cbl**
- **Use Case**: Employee payroll processing
- **Features**:
  - Simple static CALL statements
  - Dynamic program names
  - Multiple parameter passing
  - Basic error scenarios

**Key CALL Patterns**:
```cobol
CALL 'CALCPAY' USING WS-SALARY WS-HOURS WS-GROSS-PAY
CALL WS-CALC-TAX-PGM USING WS-GROSS-PAY WS-TAX-AMOUNT
CALL 'RPTGEN' USING WS-EMP-ID WS-EMP-NAME WS-GROSS-PAY
```

### 2. **call_statements_advanced.cbl**
- **Use Case**: Loan calculation system
- **Features**:
  - BY REFERENCE vs BY VALUE parameter passing
  - RETURNING clause
  - ON EXCEPTION/NOT ON EXCEPTION handling
  - Complex financial calculations

**Key CALL Patterns**:
```cobol
CALL 'VALIDATE-LOAN' USING BY REFERENCE WS-PRINCIPAL ... WS-VALID-FLAG
CALL 'CALC-RATE' USING BY VALUE WS-ANNUAL-RATE BY REFERENCE WS-MONTHLY-RATE
CALL 'CALC-PAYMENT' USING ... RETURNING WS-RESULT-CODE ON EXCEPTION ...
```

### 3. **call_inventory_system.cbl**
- **Use Case**: Inventory management
- **Features**:
  - Multiple sequential CALL statements
  - Nested CALL logic
  - Complex exception handling with retries
  - Service directory pattern

**Key CALL Patterns**:
```cobol
CALL WS-DB-PROG-NAME USING WS-TRANSACTION-ID ...
CALL 'INVUPDATE' USING BY REFERENCE WS-ITEM-ID ... RETURNING WS-INVENTORY-VALUE
CALL WS-EMAIL-PROG USING ... IF condition before CALL
```

### 4. **call_banking_system.cbl**
- **Use Case**: Financial transaction processing
- **Features**:
  - Dynamic CALL based on transaction type
  - Complex conditional CALL chains
  - Multiple validation steps with CALL
  - Error recovery patterns

**Key CALL Patterns**:
```cobol
CALL WS-AUTH-SERVICE USING ... ON EXCEPTION ... 
IF condition THEN CALL WS-FRAUD-DETECT ... 
  IF condition THEN CALL WS-LIMIT-CHECK ...
    IF condition THEN CALL WS-POSTING-ENGINE ...
```

### 5. **call_order_processing.cbl**
- **Use Case**: E-commerce order fulfillment
- **Features**:
  - Multiple CALL statements in sequence
  - CALL within PERFORM loops
  - CALL with RETURNING values
  - Complex validation pipelines

**Key CALL Patterns**:
```cobol
CALL WS-VALIDATION-SVC USING BY REFERENCE ... BY REFERENCE ...
PERFORM VARYING WS-LINE-ITEM-COUNT FROM 1 BY 1
  CALL WS-INVENTORY-SVC USING ... BY REFERENCE WS-INVENTORY-OK
END-PERFORM
```

### 6. **call_hr_system.cbl**
- **Use Case**: Human resources management
- **Features**:
  - Service registry pattern
  - Multiple service CALL sequences
  - CALL with complex data structures
  - Benefits and payroll processing

**Key CALL Patterns**:
```cobol
CALL WS-VALIDATION-SVC USING ... BY REFERENCE WS-ELIGIBLE-FLAG
CALL WS-BENEFITS-SVC USING BY REFERENCE ... RETURNING WS-PROCESSED-FLAG
CALL WS-REVIEW-SVC USING BY REFERENCE ... RETURNING WS-RESULT-CODE
```

### 7. **call_insurance_claims.cbl**
- **Use Case**: Insurance claims processing
- **Features**:
  - Retry logic with CALL
  - PERFORM VARYING with nested CALL
  - Multiple exception handlers
  - Complex approval workflows

**Key CALL Patterns**:
```cobol
PERFORM VARYING WS-RETRY-ATTEMPTS FROM 1 BY 1 UNTIL ...
  CALL WS-POLICY-LOOKUP USING ... ON EXCEPTION ... NOT ON EXCEPTION ...
END-PERFORM
CALL WS-FRAUD-CHECK-SVC USING ... BY REFERENCE ... RETURNING ...
```

### 8. **call_manufacturing_production.cbl**
- **Use Case**: Manufacturing production control
- **Features**:
  - CALL in batch processing loops
  - Multiple service coordination
  - Resource allocation
  - Quality control integration

**Key CALL Patterns**:
```cobol
PERFORM VARYING WS-STATION-IDX FROM 1 BY 1 UNTIL ...
  CALL WS-MACHINE-ALLOC USING BY REFERENCE ...
END-PERFORM
CALL WS-PRODUCTION-RUN USING BY REFERENCE ... RETURNING WS-BATCH-ID
```

### 9. **call_telecom_billing.cbl**
- **Use Case**: Telecommunications billing
- **Features**:
  - Sequential rating/charging CALL statements
  - Calculation and validation pipeline
  - Bill generation workflow
  - Discount and tax calculation

**Key CALL Patterns**:
```cobol
CALL WS-USAGE-RETRIEVAL USING ... BY REFERENCE WS-CALL-MINUTES ...
CALL WS-CALL-RATING USING BY REFERENCE ... BY REFERENCE WS-CALL-CHARGES
CALL WS-DISCOUNT-SVC USING ... BY REFERENCE WS-LOYALTY-DISCOUNT ...
```

### 10. **call_edge_cases_advanced.cbl**
- **Use Case**: Advanced CALL patterns and edge cases
- **Features**:
  - Dynamic program names
  - Conditional CALL statements
  - CALL within loops
  - Nested/chained CALL sequences
  - Multiple RETURNING patterns
  - Exception handling variations

**Key CALL Patterns**:
```cobol
CALL WS-CHILD-PROG USING BY VALUE WS-AMOUNT BY REFERENCE WS-RESULT
PERFORM VARYING ... UNTIL ...
  CALL 'BATCH-PROCESSOR' USING ... RETURNING WS-CALC-RESULT
END-PERFORM
CALL WS-PARENT-PROG USING BY REFERENCE ... (nested calls)
```

## CALL Statement Patterns Covered

### Parameter Passing
- ✓ BY REFERENCE (default)
- ✓ BY VALUE
- ✓ Mix of BY REFERENCE and BY VALUE in single CALL
- ✓ Literal values as parameters
- ✓ Variable names as parameters

### CALL Variations
- ✓ Static program names (quoted strings)
- ✓ Dynamic program names (variables)
- ✓ RETURNING clause with various return types
- ✓ ON EXCEPTION / NOT ON EXCEPTION
- ✓ Multiple parameters (5-10 parameters)

### Control Flow
- ✓ CALL in PERFORM VARYING loops
- ✓ CALL in IF conditions
- ✓ Nested CALL chains (multi-level)
- ✓ Conditional CALL execution
- ✓ CALL with PERFORM

### Exception Handling
- ✓ ON EXCEPTION clauses
- ✓ NOT ON EXCEPTION clauses
- ✓ Retry logic with CALL
- ✓ Fallback handlers
- ✓ Error code handling after CALL

### Real-World Scenarios
- ✓ Service registry pattern
- ✓ Validation pipelines
- ✓ Batch processing
- ✓ Transaction processing
- ✓ Multi-step approval workflows
- ✓ Error recovery patterns

## Testing Instructions

### Run Parser on All Examples
```bash
cd cobol-parser
python -m pytest tests/test_all_samples.py -v
```

### Parse Individual Example
```python
from cobolparser import CobolParser

parser = CobolParser()
with open('tests/samples/call_banking_system.cbl', 'r') as f:
    code = f.read()

result = parser.parse(code)
ast = result.ast
calls = ast.get_all_statements_of_type('CallStatement')
print(f"Found {len(calls)} CALL statements")
```

### Validate CALL Extraction
```python
for call_stmt in calls:
    print(f"Program: {call_stmt.called_program}")
    print(f"Parameters: {call_stmt.using_parameters}")
    print(f"Returning: {call_stmt.returning_parameter}")
    print(f"Has Exception Handler: {call_stmt.on_exception is not None}")
```

## Coverage Analysis

These examples should test and reveal:

1. **Missed CALL Statements**: Various CALL patterns that might not be parsed
2. **Parameter Variations**: Different ways parameters are passed
3. **Exception Handling**: Proper capture of ON EXCEPTION clauses
4. **Return Values**: RETURNING clause variations
5. **Dynamic Names**: Variable program names
6. **Complex Scenarios**: Real production patterns

## Next Steps

1. Run parser against all new examples
2. Identify which CALL patterns are being missed
3. Debug parser logic for missed patterns
4. Add unit tests for each pattern type
5. Update parser to handle all variations
6. Verify test coverage for CALL statements
