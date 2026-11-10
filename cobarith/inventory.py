"""Inventory of CardDemo programs and the arithmetic statements they contain."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import DATA_DIR
from .data import parse_data
from .source import Library, source_tokens
from .stmt import Statement, parse_statements

__all__ = ["Inventory", "inventory"]


@dataclass
class Inventory:
    """Programs in stable order, all their statements, and unresolved copybooks."""

    programs: list[str]
    statements: list[Statement]
    missing_copybooks: set[str]


def _program_files(root: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".cbl":
            found.append((path.stem.upper(), path))
    return sorted(found, key=lambda entry: (entry[0], str(entry[1])))


def inventory(root: str | Path = DATA_DIR) -> Inventory:
    """Parse every ``.cbl`` program under *root*, upper-casing program names."""

    root = Path(root)
    entries = _program_files(root) if root.is_dir() else []
    programs: list[str] = []
    statements: list[Statement] = []
    missing: set[str] = set()

    for program, path in entries:
        programs.append(program)
        library = Library(root)
        tokens = source_tokens(path, library)
        statements.extend(parse_statements(tokens, program, parse_data(tokens), path.name))
        missing.update(library.missing)

    return Inventory(programs, statements, missing)
