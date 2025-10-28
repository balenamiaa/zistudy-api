#!/usr/bin/env python3
"""
Script to condense Python source files (excluding venv, tests, etc.) into a single file.
"""

import os
from datetime import datetime
from pathlib import Path


def should_exclude(path: Path) -> bool:
    """
    Check if a path should be excluded from condensing.

    Args:
        path: Path to check

    Returns:
        True if the path should be excluded
    """
    exclude_patterns = [
        ".venv",
        "__pycache__",
        ".git",
        ".pytest_cache",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        "tests",  # Exclude tests
        "alembic/versions",  # Exclude migration files
    ]

    path_str = str(path)
    return any(pattern in path_str for pattern in exclude_patterns)


def condense_python_files(root_dir: str, output_file: str):
    """
    Condense all Python source files into one file.

    Args:
        root_dir: Root directory to search for Python files
        output_file: Path to the output file
    """
    root_path = Path(root_dir)
    all_python_files = sorted(root_path.rglob("*.py"))

    # Filter out excluded directories and the output file itself
    python_files = [
        f for f in all_python_files
        if not should_exclude(f) and f.name != os.path.basename(output_file)
    ]

    with open(output_file, "w", encoding="utf-8") as outfile:
        # Write header
        outfile.write("# Condensed Python Source Files\n")
        outfile.write(f"# Generated: {datetime.now().isoformat()}\n")
        outfile.write(f"# Root directory: {root_dir}\n")
        outfile.write(f"# Total files: {len(python_files)}\n")
        outfile.write("=" * 80 + "\n\n")

        # Write table of contents
        outfile.write("# TABLE OF CONTENTS\n")
        outfile.write("=" * 80 + "\n")
        for i, py_file in enumerate(python_files, 1):
            relative_path = py_file.relative_to(root_path)
            outfile.write(f"{i:3d}. {relative_path}\n")
        outfile.write("\n" + "=" * 80 + "\n\n")

        # Write file contents
        for py_file in python_files:
            relative_path = py_file.relative_to(root_path)

            # Write file separator and header
            outfile.write("\n" + "=" * 80 + "\n")
            outfile.write(f"# FILE: {relative_path}\n")
            outfile.write("=" * 80 + "\n\n")

            try:
                with open(py_file, "r", encoding="utf-8") as infile:
                    content = infile.read()
                    outfile.write(content)

                    # Ensure file ends with newline
                    if content and not content.endswith("\n"):
                        outfile.write("\n")

            except Exception as e:
                outfile.write(f"# ERROR reading file: {e}\n")

            outfile.write("\n")

    print(f"✓ Successfully condensed {len(python_files)} Python files into {output_file}")
    print("\nFiles included:")
    for i, py_file in enumerate(python_files, 1):
        print(f"  {i:3d}. {py_file.relative_to(root_path)}")


if __name__ == "__main__":
    current_dir = "."
    output_path = "condensed_source_code.txt"

    print(f"Condensing Python source files from: {os.path.abspath(current_dir)}")
    print(f"Output file: {os.path.abspath(output_path)}")
    print("Excluding: .venv, tests, __pycache__, alembic/versions, etc.\n")

    condense_python_files(current_dir, output_path)

    file_size = os.path.getsize(output_path)
    print(f"\n✓ Output file size: {file_size:,} bytes ({file_size / 1024:.2f} KB)")
