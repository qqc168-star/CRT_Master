#!/usr/bin/env python3

"""
CRT Self Check v0.1
"""

from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIRS = [
    "docs",
    "scripts",
    "raw",
    "metadata",
    "evidence",
    "ledger",
    "logs",
    "qa",
    "tests",
]

REQUIRED_FILES = [
    ".gitignore",
    "README.md",
    "requirements.txt",
]


def check_path(path):
    return "PASS" if path.exists() else "FAIL"


def main():
    print("=" * 50)
    print("CRT Self Check v0.1")
    print("=" * 50)

    print(f"Python : {platform.python_version()}")
    print()

    print("Directories")
    for d in REQUIRED_DIRS:
        print(f"{check_path(ROOT / d):5}  {d}")

    print()
    print("Files")
    for f in REQUIRED_FILES:
        print(f"{check_path(ROOT / f):5}  {f}")

    print()
    print("=" * 50)
    print("Self Check Finished")
    print("=" * 50)


if __name__ == "__main__":
    main()
