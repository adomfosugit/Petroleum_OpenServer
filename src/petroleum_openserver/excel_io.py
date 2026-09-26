"""Port of the VBA `FindCell` function and the `Range.Offset(...).Value` idiom
used throughout the original macros, built on `openpyxl`.

The source workbook module had `Option Compare Text` at the top, which makes
every VBA string comparison (`=`, `Like`) case-insensitive; `find_cell`
matches that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Optional

from openpyxl.worksheet.worksheet import Worksheet

from .exceptions import ProgramTerminated

# The VBA default search range was "A1:IV1000" (old-style: 256 columns, 1000 rows).
DEFAULT_MAX_ROW = 1000
DEFAULT_MAX_COL = 256


@dataclass
class Ref:
    """A single-cell reference that behaves like the VBA `Range` objects this
    code chains `.Offset(...)` calls off of.
    """

    ws: Worksheet
    row: int
    col: int

    def offset(self, row_offset: int = 0, col_offset: int = 0) -> "Ref":
        return Ref(self.ws, self.row + row_offset, self.col + col_offset)

    @property
    def cell(self):
        return self.ws.cell(row=self.row, column=self.col)

    @property
    def value(self) -> Any:
        return self.cell.value

    @value.setter
    def value(self, new_value: Any) -> None:
        self.cell.value = new_value

    def clear_contents(self) -> None:
        self.cell.value = None

    @property
    def is_empty(self) -> bool:
        return self.value is None or self.value == ""


def find_cell(
    ws: Worksheet,
    content: str,
    max_row: int = DEFAULT_MAX_ROW,
    max_col: int = DEFAULT_MAX_COL,
) -> Ref:
    """Port of the VBA `FindCell(SearchSheet, CellContent)` function.

    Scans `ws` (row-major, matching the VBA `For Each SearchCell In SearchRange`
    order closely enough) for a cell whose text equals `content`, case-insensitively.
    Raises `ProgramTerminated` if nothing matches, exactly like the VBA version
    calling `TerminateProgram`.
    """
    target = content.strip().lower()
    for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
        for cell in row:
            value = cell.value
            if isinstance(value, str) and value.strip().lower() == target:
                return Ref(ws, cell.row, cell.column)
    raise ProgramTerminated(
        f"Error: Cell containing text '{content}' on sheet '{ws.title}' not found"
    )


def try_find_cell(
    ws: Worksheet,
    content: str,
    max_row: int = DEFAULT_MAX_ROW,
    max_col: int = DEFAULT_MAX_COL,
) -> Optional[Ref]:
    """Same as `find_cell` but returns None instead of raising."""
    try:
        return find_cell(ws, content, max_row=max_row, max_col=max_col)
    except ProgramTerminated:
        return None


def iter_down(start: Ref) -> Iterator[Ref]:
    """Port of the common VBA pattern:

        Set Cell = FindCell(...).Offset(4, 0)
        Do While IsEmpty(Cell) = False
            ...
            Set Cell = Cell.Offset(1, 0)
        Loop

    Yields `start`, `start.offset(1, 0)`, `start.offset(2, 0)`, ... until an
    empty cell is reached.
    """
    ref = start
    while not ref.is_empty:
        yield ref
        ref = ref.offset(1, 0)


def is_numeric(value: Any) -> bool:
    """Port of VBA `IsNumeric`, close enough for how this codebase uses it
    (numbers and numeric strings are numeric; bool, None, "-", "ERROR", "" are not)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except ValueError:
            return False
    return False


def as_float(value: Any) -> Optional[float]:
    return float(value) if is_numeric(value) else None
