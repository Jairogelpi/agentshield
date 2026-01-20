#!/usr/bin/env python3
"""
SQL Schema Validator
Validates SQL schema files for common issues and security concerns.
"""
import os
import sys
import re
from pathlib import Path

# Patterns that indicate potential issues
FORBIDDEN_PATTERNS = [
    (r'\bDROP\s+TABLE\b', "DROP TABLE - dangerous in production"),
    (r'\bTRUNCATE\b', "TRUNCATE - data loss risk"),
    (r'\bDELETE\s+FROM\s+\w+\s*;', "DELETE without WHERE clause"),
]

# Patterns that should be present in schema files
RECOMMENDED_PATTERNS = [
    (r'CREATE\s+TABLE', "Should have CREATE TABLE statement"),
]

# Security patterns to check
SECURITY_CHECKS = [
    (r'password\s*VARCHAR', "Password should not be stored as plain VARCHAR"),
    (r'api_key\s*VARCHAR(?!\s*\(64\))', "API keys should be stored as hashes (64 chars)"),
]


def validate_sql_file(filepath: Path) -> list:
    """Validate a single SQL file and return list of issues."""
    issues = []
    
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        return [f"Could not read file: {e}"]
    
    # Check for forbidden patterns
    for pattern, message in FORBIDDEN_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"⚠️  {message}")
    
    # Check for security issues (warnings only)
    for pattern, message in SECURITY_CHECKS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"🔒 SECURITY: {message}")
    
    return issues


def main():
    """Main entry point."""
    scripts_dir = Path(__file__).parent
    
    sql_files = list(scripts_dir.glob("*.sql"))
    
    if not sql_files:
        print("No SQL files found in scripts directory")
        return 0
    
    print(f"🔍 Validating {len(sql_files)} SQL files...\n")
    
    all_issues = {}
    has_errors = False
    
    for sql_file in sorted(sql_files):
        issues = validate_sql_file(sql_file)
        if issues:
            all_issues[sql_file.name] = issues
            # Only critical issues cause failure
            if any("⚠️" in issue for issue in issues):
                has_errors = True
    
    # Report results
    if all_issues:
        for filename, issues in all_issues.items():
            print(f"📄 {filename}")
            for issue in issues:
                print(f"   {issue}")
            print()
    
    if has_errors:
        print("❌ Validation failed - critical issues found")
        return 1
    else:
        print(f"✅ All {len(sql_files)} SQL schemas validated successfully")
        return 0


if __name__ == "__main__":
    sys.exit(main())
