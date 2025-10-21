# Data Item Parsing Examples

This document shows examples of how data item declarations are parsed into AST nodes.

## Basic Data Item (PIC X)

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME    PIC X(30).
```

### Parsed AST Output
```json
{
  "node_type": "DataItem",
  "level": 1,
  "name": "WS-NAME",
  "picture_clause": {
    "pattern": "X(30)",
    "type": "ALPHANUMERIC",
    "length": 30,
    "usage": "DISPLAY"
  },
  "usage": "DISPLAY",
  "value_clause": null,
  "occurs_clause": null,
  "children": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "storage_size": 30,
    "is_group_item": false,
    "has_children": false
  }
}
```

### Key Properties
- `level`: COBOL level number (01, 05, 10, etc.)
- `name`: Variable name
- `picture_clause`: Picture string and parsed details
- `usage`: Data usage (DISPLAY, COMP, COMP-3, etc.)
- `value_clause`: Initial value if specified
- `occurs_clause`: Array definition if present
- `children`: Subordinate data items (for group items)

## Numeric Data Item (PIC 9)

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COUNTER    PIC 9(5) VALUE 0.
```

### Parsed AST Output
```json
{
  "node_type": "DataItem",
  "level": 1,
  "name": "WS-COUNTER",
  "picture_clause": {
    "pattern": "9(5)",
    "type": "NUMERIC",
    "length": 5,
    "usage": "DISPLAY"
  },
  "usage": "DISPLAY",
  "value_clause": {
    "value": 0,
    "is_literal": true
  },
  "occurs_clause": null,
  "children": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "storage_size": 5,
    "is_group_item": false,
    "has_children": false,
    "has_initial_value": true
  }
}
```

## COMP-3 Packed Decimal (IBM Enterprise)

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT    PIC 9(7)V99 COMP-3.
```

### Parsed AST Output
```json
{
  "node_type": "DataItem",
  "level": 1,
  "name": "WS-AMOUNT",
  "picture_clause": {
    "pattern": "9(7)V99",
    "type": "NUMERIC",
    "length": 9,
    "usage": "COMP-3"
  },
  "usage": "COMP-3",
  "value_clause": null,
  "occurs_clause": null,
  "children": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "storage_size": 5,
    "is_group_item": false,
    "has_children": false,
    "comp3_digits": 9,
    "comp3_bytes": 5
  }
}
```

## Array Definition (OCCURS)

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MONTHS.
           05  WS-MONTH-NAME    PIC X(10) OCCURS 12 TIMES.
```

### Parsed AST Output
```json
{
  "node_type": "DataItem",
  "level": 1,
  "name": "WS-MONTHS",
  "picture_clause": null,
  "usage": "DISPLAY",
  "value_clause": null,
  "occurs_clause": null,
  "children": [
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-MONTH-NAME",
      "picture_clause": {
        "pattern": "X(10)",
        "type": "ALPHANUMERIC",
        "length": 10,
        "usage": "DISPLAY"
      },
      "usage": "DISPLAY",
      "value_clause": null,
      "occurs_clause": {
        "count": 12,
        "is_literal": true,
        "depending_on": null
      },
      "children": [],
      "location": {
        "file": "example.cob",
        "line": 4,
        "column": 12
      },
      "metadata": {
        "storage_size": 120,
        "is_group_item": false,
        "has_children": false,
        "is_array": true,
        "array_size": 12
      }
    }
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "storage_size": 120,
    "is_group_item": true,
    "has_children": true,
    "child_count": 1
  }
}
```

## Group Item with Multiple Fields

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE.
           05  WS-EMP-ID      PIC 9(6) COMP-3.
           05  WS-EMP-NAME    PIC X(30).
           05  WS-EMP-SALARY  PIC 9(7)V99 COMP-3.
```

### Parsed AST Output
```json
{
  "node_type": "DataItem",
  "level": 1,
  "name": "WS-EMPLOYEE",
  "picture_clause": null,
  "usage": "DISPLAY",
  "value_clause": null,
  "occurs_clause": null,
  "children": [
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-EMP-ID",
      "picture_clause": {
        "pattern": "9(6)",
        "type": "NUMERIC",
        "length": 6,
        "usage": "COMP-3"
      },
      "usage": "COMP-3",
      "value_clause": null,
      "occurs_clause": null,
      "children": [],
      "location": {
        "file": "example.cob",
        "line": 4,
        "column": 12
      },
      "metadata": {
        "storage_size": 4,
        "is_group_item": false,
        "has_children": false
      }
    },
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-EMP-NAME",
      "picture_clause": {
        "pattern": "X(30)",
        "type": "ALPHANUMERIC",
        "length": 30,
        "usage": "DISPLAY"
      },
      "usage": "DISPLAY",
      "value_clause": null,
      "occurs_clause": null,
      "children": [],
      "location": {
        "file": "example.cob",
        "line": 5,
        "column": 12
      },
      "metadata": {
        "storage_size": 30,
        "is_group_item": false,
        "has_children": false
      }
    },
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-EMP-SALARY",
      "picture_clause": {
        "pattern": "9(7)V99",
        "type": "NUMERIC",
        "length": 9,
        "usage": "COMP-3"
      },
      "usage": "COMP-3",
      "value_clause": null,
      "occurs_clause": null,
      "children": [],
      "location": {
        "file": "example.cob",
        "line": 6,
        "column": 12
      },
      "metadata": {
        "storage_size": 5,
        "is_group_item": false,
        "has_children": false
      }
    }
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "storage_size": 39,
    "is_group_item": true,
    "has_children": true,
    "child_count": 3
  }
}
```

## Multi-level Data Structure

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMPANY.
           05  WS-DEPT-COUNT    PIC 9(3).
           05  WS-DEPARTMENTS OCCURS 10 TIMES.
               10  WS-DEPT-ID     PIC 9(4).
               10  WS-DEPT-NAME   PIC X(20).
               10  WS-EMPLOYEES OCCURS 50 TIMES.
                   15  WS-EMP-NUM    PIC 9(6).
                   15  WS-EMP-NAME   PIC X(25).
```

### Parsed AST Output
```json
{
  "node_type": "DataItem",
  "level": 1,
  "name": "WS-COMPANY",
  "picture_clause": null,
  "usage": "DISPLAY",
  "value_clause": null,
  "occurs_clause": null,
  "children": [
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-DEPT-COUNT",
      "picture_clause": {
        "pattern": "9(3)",
        "type": "NUMERIC",
        "length": 3,
        "usage": "DISPLAY"
      },
      "usage": "DISPLAY",
      "value_clause": null,
      "occurs_clause": null,
      "children": [],
      "location": {
        "file": "example.cob",
        "line": 4,
        "column": 12
      },
      "metadata": {
        "storage_size": 3,
        "is_group_item": false,
        "has_children": false
      }
    },
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-DEPARTMENTS",
      "picture_clause": null,
      "usage": "DISPLAY",
      "value_clause": null,
      "occurs_clause": {
        "count": 10,
        "is_literal": true,
        "depending_on": null
      },
      "children": [
        {
          "node_type": "DataItem",
          "level": 10,
          "name": "WS-DEPT-ID",
          "picture_clause": {
            "pattern": "9(4)",
            "type": "NUMERIC",
            "length": 4,
            "usage": "DISPLAY"
          },
          "usage": "DISPLAY",
          "value_clause": null,
          "occurs_clause": null,
          "children": [],
          "location": {
            "file": "example.cob",
            "line": 6,
            "column": 16
          },
          "metadata": {
            "storage_size": 4,
            "is_group_item": false,
            "has_children": false
          }
        },
        {
          "node_type": "DataItem",
          "level": 10,
          "name": "WS-DEPT-NAME",
          "picture_clause": {
            "pattern": "X(20)",
            "type": "ALPHANUMERIC",
            "length": 20,
            "usage": "DISPLAY"
          },
          "usage": "DISPLAY",
          "value_clause": null,
          "occurs_clause": null,
          "children": [],
          "location": {
            "file": "example.cob",
            "line": 7,
            "column": 16
          },
          "metadata": {
            "storage_size": 20,
            "is_group_item": false,
            "has_children": false
          }
        },
        {
          "node_type": "DataItem",
          "level": 10,
          "name": "WS-EMPLOYEES",
          "picture_clause": null,
          "usage": "DISPLAY",
          "value_clause": null,
          "occurs_clause": {
            "count": 50,
            "is_literal": true,
            "depending_on": null
          },
          "children": [
            {
              "node_type": "DataItem",
              "level": 15,
              "name": "WS-EMP-NUM",
              "picture_clause": {
                "pattern": "9(6)",
                "type": "NUMERIC",
                "length": 6,
                "usage": "DISPLAY"
              },
              "usage": "DISPLAY",
              "value_clause": null,
              "occurs_clause": null,
              "children": [],
              "location": {
                "file": "example.cob",
                "line": 9,
                "column": 20
              },
              "metadata": {
                "storage_size": 6,
                "is_group_item": false,
                "has_children": false
              }
            },
            {
              "node_type": "DataItem",
              "level": 15,
              "name": "WS-EMP-NAME",
              "picture_clause": {
                "pattern": "X(25)",
                "type": "ALPHANUMERIC",
                "length": 25,
                "usage": "DISPLAY"
              },
              "usage": "DISPLAY",
              "value_clause": null,
              "occurs_clause": null,
              "children": [],
              "location": {
                "file": "example.cob",
                "line": 10,
                "column": 20
              },
              "metadata": {
                "storage_size": 25,
                "is_group_item": false,
                "has_children": false
              }
            }
          ],
          "location": {
            "file": "example.cob",
            "line": 8,
            "column": 16
          },
          "metadata": {
            "storage_size": 1550,
            "is_group_item": true,
            "has_children": true,
            "child_count": 2,
            "is_array": true,
            "array_size": 50
          }
        }
      ],
      "location": {
        "file": "example.cob",
        "line": 5,
        "column": 12
      },
      "metadata": {
        "storage_size": 15740,
        "is_group_item": true,
        "has_children": true,
        "child_count": 3,
        "is_array": true,
        "array_size": 10
      }
    }
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "storage_size": 15743,
    "is_group_item": true,
    "has_children": true,
    "child_count": 2,
    "total_fields": 5,
    "max_depth": 4
  }
}
```

## Usage in Data Analysis

```python
from cobolparser import parse_cobol
from cobolparser.models.data_items import DataItem

def analyze_data_items(cobol_source):
    result = parse_cobol(cobol_source)

    data_info = []
    def analyze_item(item, indent=0):
        info = {
            'level': item.level,
            'name': item.name,
            'usage': item.usage,
            'storage_size': item.calculate_storage_size() if hasattr(item, 'calculate_storage_size') else 0,
            'is_group': len(item.children) > 0,
            'child_count': len(item.children),
            'line': item.location.line
        }

        if item.picture_clause:
            info['picture'] = item.picture_clause.pattern

        if item.occurs_clause:
            info['array_size'] = item.occurs_clause.count

        data_info.append(info)

        for child in item.children:
            analyze_item(child, indent + 1)

    if result.ast:
        data_div = result.ast.get_division_by_name("DATA")
        if data_div:
            ws_section = data_div.get_section_by_name("WORKING-STORAGE")
            if ws_section:
                for item in ws_section.children:
                    analyze_item(item)

    return data_info

# Example output:
# [
#   {'level': 1, 'name': 'WS-NAME', 'usage': 'DISPLAY', 'storage_size': 30, 'is_group': False, 'child_count': 0, 'picture': 'X(30)', 'line': 3},
#   {'level': 1, 'name': 'WS-COUNTER', 'usage': 'DISPLAY', 'storage_size': 5, 'is_group': False, 'child_count': 0, 'picture': '9(5)', 'line': 3},
#   {'level': 1, 'name': 'WS-AMOUNT', 'usage': 'COMP-3', 'storage_size': 5, 'is_group': False, 'child_count': 0, 'picture': '9(7)V99', 'line': 3},
#   {'level': 1, 'name': 'WS-MONTHS', 'usage': 'DISPLAY', 'storage_size': 120, 'is_group': True, 'child_count': 1, 'line': 3},
#   {'level': 5, 'name': 'WS-MONTH-NAME', 'usage': 'DISPLAY', 'storage_size': 120, 'is_group': False, 'child_count': 0, 'picture': 'X(10)', 'array_size': 12, 'line': 4}
# ]
```