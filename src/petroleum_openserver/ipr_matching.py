"""Port of `MatchIPR`, `MatchIPR_SelectedWell` and `EstimateResPress`."""

from __future__ import annotations

from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from .excel_io import find_cell, is_numeric
from .ipr import get_res_pres
from .petex_client import terminate

_ZONES = ("UZ", "MZ", "LZ")


def match_ipr(config_ws: Worksheet, ws: Worksheet) -> None:
    """Port of `MatchIPR`: for every well row and every zone, re-estimate the
    zone's reservoir pressure from its measured rate/BHP.
    """
    well_cell = find_cell(ws, "Well Name").offset(4, 0)
    n_row = 0
    while not well_cell.is_empty:
        for uzmzlz in _ZONES:
            estimate_res_press(config_ws, ws, n_row, uzmzlz)
        n_row += 1
        well_cell = well_cell.offset(1, 0)


def match_ipr_selected_row(config_ws: Worksheet, ws: Worksheet, n_row: int) -> None:
    """Port of `MatchIPR_SelectedWell` (row index passed explicitly - see `vlp.vlp_calc_selected_row`)."""
    if n_row < 0 or n_row > 500:
        terminate("Error: Selected row out-with limits")
    for uzmzlz in _ZONES:
        estimate_res_press(config_ws, ws, n_row, uzmzlz)


def _leave_or_flag_error(ws: Worksheet, uzmzlz: str, n_row: int) -> None:
    """Shared tail of `EstimateResPress`'s two "couldn't recalculate" branches:
    keep the existing user-entered reservoir pressure if there is one, else
    flag "ERROR" unless the zone is closed / not producing.
    """
    res_pres_ref = find_cell(ws, f"{uzmzlz} Res. Pres.").offset(4 + n_row, 0)
    if is_numeric(res_pres_ref.value) and float(res_pres_ref.value) > 0:
        return
    icv = find_cell(ws, f"{uzmzlz} ICV").offset(4 + n_row, 0).value
    liq_rate = find_cell(ws, f"{uzmzlz} Liquid Rate").offset(4 + n_row, 0).value
    if (is_numeric(icv) and float(icv) < 1) or liq_rate == 0:
        return
    res_pres_ref.value = "ERROR"


def estimate_res_press(config_ws: Worksheet, ws: Worksheet, n_row: int, uzmzlz: str) -> None:
    """Port of `EstimateResPress(nRow, UZMZLZ)`."""
    pb = find_cell(config_ws, "Bubble Pt").offset(0, 2).value

    liq_rate = find_cell(ws, f"{uzmzlz} Liquid Rate").offset(4 + n_row, 0).value
    pi = find_cell(ws, f"{uzmzlz} PI").offset(4 + n_row, 0).value
    wc = find_cell(ws, f"{uzmzlz} Watercut").offset(4 + n_row, 0).value

    if not (is_numeric(liq_rate) and float(liq_rate) > 0):
        return

    if not (is_numeric(pi) and float(pi) > 0 and is_numeric(wc) and float(wc) >= 0):
        _leave_or_flag_error(ws, uzmzlz, n_row)
        return

    n_zone = find_cell(ws, "Number of Zones").offset(4 + n_row, 0).value

    bhp: Any = "-"
    annulus_bhp = find_cell(ws, f"{uzmzlz} Annulus Pressure").offset(4 + n_row, 0).value
    if is_numeric(annulus_bhp) and float(annulus_bhp) > 0:
        bhp = annulus_bhp
    else:
        tubing_bhp = find_cell(ws, f"{uzmzlz} Tubing Pressure").offset(4 + n_row, 0).value
        if is_numeric(tubing_bhp) and float(tubing_bhp) > 0:
            icv_setting = find_cell(ws, f"{uzmzlz} ICV").offset(4 + n_row, 0).value
            icv_dp = find_cell(ws, f"{uzmzlz} ICV dP").offset(4 + n_row, 0).value
            if is_numeric(icv_dp) and float(icv_dp) == 0:
                bhp = tubing_bhp
            elif is_numeric(icv_setting) and float(icv_setting) == 10:
                bhp = tubing_bhp
            elif n_zone == 1 and not is_numeric(icv_setting) and not is_numeric(icv_dp):
                # Likely a single-zone completion without ICVs.
                bhp = tubing_bhp
            else:
                bhp = "-"
        elif uzmzlz == "UZ":
            # No measured BHP for the upper zone - fall back to the VLP-calculated one.
            prosper_bhp = find_cell(ws, "PROSPER BHP").offset(4 + n_row, 0).value
            bhp = prosper_bhp if is_numeric(prosper_bhp) and float(prosper_bhp) > 0 else "-"
        else:
            bhp = "-"

    if is_numeric(bhp) and float(bhp) > 0:
        res_press = (
            get_res_pres(float(pi), float(pb), float(wc), float(liq_rate), float(bhp) - 14.7, 1000, 10000)
            + 14.7
        )
        find_cell(ws, f"{uzmzlz} Res. Pres.").offset(4 + n_row, 0).value = res_press
    else:
        _leave_or_flag_error(ws, uzmzlz, n_row)
