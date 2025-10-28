"""Developer utility commands exposed as CLI entry points."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _run_command(command: Sequence[str]) -> int:
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    return result.returncode


def _run_sequence(commands: Iterable[Sequence[str]]) -> int:
    for command in commands:
        exit_code = _run_command(command)
        if exit_code != 0:
            return exit_code
    return 0


def run_format() -> int:
    """Format the entire project using Ruff."""

    return _run_command([sys.executable, "-m", "ruff", "format", str(PROJECT_ROOT)])


def run_lint() -> int:
    """Run Ruff checks across the repository."""

    return _run_command([sys.executable, "-m", "ruff", "check", str(PROJECT_ROOT)])


def run_typecheck() -> int:
    """Execute mypy with the repository configuration."""

    return _run_command(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(PYPROJECT),
            "src",
            "tests",
        ]
    )


def run_test() -> int:
    """Format, lint, type-check, and run the test suite with coverage."""

    return _run_sequence(
        [
            [sys.executable, "-m", "ruff", "format", str(PROJECT_ROOT)],
            [sys.executable, "-m", "ruff", "check", str(PROJECT_ROOT)],
            [
                sys.executable,
                "-m",
                "mypy",
                "--config-file",
                str(PYPROJECT),
                "src",
                "tests",
            ],
            [sys.executable, "-m", "coverage", "run", "-m", "pytest"],
        ]
    )


def main() -> None:
    """Dispatch helper allowing invocation via ``python -m zistudy_api.tools``."""

    parser = argparse.ArgumentParser(description="ZiStudy developer utilities")
    parser.add_argument(
        "command",
        choices={"format", "lint", "typecheck", "test"},
        help="Utility command to run",
    )
    args = parser.parse_args()

    mapping = {
        "format": run_format,
        "lint": run_lint,
        "typecheck": run_typecheck,
        "test": run_test,
    }
    sys.exit(mapping[args.command]())


if __name__ == "__main__":  # pragma: no cover - module invocation
    main()
