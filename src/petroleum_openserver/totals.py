"""Port of `DeleteMeasuredTotals`, `DeleteAllocatedTotals`, `DeleteTotalRates` and `GetTotalRates`.

All four are anchored on the "Total Oil Rate" header cell, with the three
adjacent columns being oil/gas/water rate and the three rows below it being
measured / allocated / GAP-calculated totals (offsets 2, 3, 4 respectively).
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from .excel_io import find_cell
from .petex_client import PetexClient


def delete_measured_totals(ws: Worksheet) -> None:
    cell = find_cell(ws, "Total Oil Rate")
    for col in range(3):
        cell.offset(2, col).value = ""


def delete_allocated_totals(ws: Worksheet) -> None:
    cell = find_cell(ws, "Total Oil Rate")
    for col in range(3):
        cell.offset(3, col).value = ""


def delete_total_rates(ws: Worksheet) -> None:
    cell = find_cell(ws, "Total Oil Rate")
    for col in range(3):
        cell.offset(4, col).value = ""


def get_total_rates(client: PetexClient, ws: Worksheet) -> None:
    cell = find_cell(ws, "Total Oil Rate")
    cell.offset(4, 0).value = client.DoGet("GAP.MOD[{PROD}].GROUP[{Jubilee}].SolverResults[0].OilRate")
    cell.offset(4, 1).value = client.DoGet("GAP.MOD[{PROD}].GROUP[{Jubilee}].SolverResults[0].GasRate")
    cell.offset(4, 2).value = client.DoGet("GAP.MOD[{PROD}].GROUP[{Jubilee}].SolverResults[0].WatRate")
