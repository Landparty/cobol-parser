#!/usr/bin/env python3
"""Analyze coverage data for Phase 3 planning."""

import json

with open('coverage.json') as f:
    data = json.load(f)

# Check structure
print("Keys in totals:", data['totals'].keys())
print("\nTotal coverage data:", data['totals'])
