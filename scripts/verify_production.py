import ast
import os
import sys


def check_syntax(file_path):
    try:
        # Use utf-8-sig to handle BOM (common in Windows) automatically
        with open(file_path, encoding="utf-8-sig") as f:
            source = f.read()

        # Parse the source code into an AST node.
        # This checks for valid Python syntax (indentation, matching parenthesis, etc.)
        # but does not try to import missing libraries.
        ast.parse(source)
        # print(f"Valid: {os.path.basename(file_path)}")
        return True
    except SyntaxError as e:
        # Stdout safe message (ASCII only)
        print(f"[X] Syntax Error in {os.path.basename(file_path)}: Line {e.lineno}")

        # Log file message (Full detail + UTF8)
        msg = f"❌ Syntax Error in {file_path}:\n   Line {e.lineno}: {e.msg}\n"
        with open("verification_errors.txt", "a", encoding="utf-8") as log:
            log.write(msg)
        return False
    except Exception as e:
        print(f"[!] Could not read {os.path.basename(file_path)}: {e}")

        msg = f"⚠️ Could not read {file_path}: {e}\n"
        with open("verification_errors.txt", "a", encoding="utf-8") as log:
            log.write(msg)
        return False


# Scan the 'app' directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
errors = 0
checked_files = 0

print(f"🔍 Scanning python files in {project_root} for syntax errors (Static Analysis)...")

for root, dirs, files in os.walk(project_root):
    for file in files:
        if file.endswith(".py"):
            full_path = os.path.join(root, file)
            checked_files += 1
            if not check_syntax(full_path):
                errors += 1

if checked_files == 0:
    print("⚠️ No Python files found to check.")
    sys.exit(1)

if errors == 0:
    print(f"✅ Success! Scanned {checked_files} files. No syntax errors found.")
    sys.exit(0)
else:
    print(f"❌ Verification Failed. Found {errors} files with syntax errors.")
    sys.exit(1)
