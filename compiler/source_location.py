"""Source coordinate objects shared by all compiler phases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A zero-offset, one-based line/column position in source text."""

    line: int
    column: int
    offset: int

    def to_dict(self) -> dict[str, int]:
        return {"line": self.line, "column": self.column, "offset": self.offset}


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A half-open source range [start, end)."""

    start: SourceLocation
    end: SourceLocation

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}

