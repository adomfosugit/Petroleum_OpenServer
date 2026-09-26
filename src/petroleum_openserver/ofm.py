"""Port of `OFMValue` and `GetdbFileName`: reads a value out of the OFM
Microsoft Access database referenced from the Configuration sheet.

Requires Windows, the "Microsoft Access Driver (*.mdb, *.accdb)" ODBC
driver, and `pyodbc` (see the `windows` extra in pyproject.toml).
"""

from __future__ import annotations

import re
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from .excel_io import find_cell, is_numeric
from .exceptions import ProgramTerminated
from .units import ipt_unit_conv

# OFM table/column names are only ever compared against known-good sheet
# headers, but they get interpolated into SQL (Access/DAO doesn't support
# parameterising identifiers), so keep them restricted to plain identifier
# characters.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")


def get_db_file_name(config_ws: Worksheet) -> str:
    """Port of `GetdbFileName` (`Sheets("Configuration").Range("D2")`)."""
    return config_ws["D2"].value


def ofm_value(
    config_ws: Worksheet,
    validation_ws: Worksheet,
    ofm_variable: str,
    reqd_unit: str,
    zone_name: str,
) -> Any:
    """Port of `OFMValue`. `ofm_variable` must be `OFM:TableName:ColumnHeading:Unit`."""
    parts = str(ofm_variable).split(":")
    if len(parts) != 4:
        raise ProgramTerminated(
            f"OFM Variable {ofm_variable} should be configured as OFM:TableName:ColumnHeading:Unit"
        )
    _, table_name, column_name, ofm_unit = parts
    if not _IDENTIFIER_RE.match(table_name) or not _IDENTIFIER_RE.match(column_name):
        raise ProgramTerminated(f"OFM Variable {ofm_variable} has an invalid table/column name")

    selected_date = find_cell(validation_ws, "Date").offset(0, 1).value
    db_file = get_db_file_name(config_ws)

    import pyodbc  # local import: pyodbc + the Access driver are Windows-only

    conn_str = f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_file};"
    with pyodbc.connect(conn_str, autocommit=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT [{column_name}] FROM [{table_name}] WHERE UNIQUEID = ? AND [Date] = ?",
            zone_name,
            selected_date,
        )
        row = cursor.fetchone()

    value: Any = row[0] if row is not None else "-"
    if is_numeric(value) and float(value) >= 0:
        return ipt_unit_conv(ofm_unit, reqd_unit, float(value))
    return "-"
