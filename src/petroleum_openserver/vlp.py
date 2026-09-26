"""Port of `VLPCalc_All`, `VLPCalc_SelectedWell` and `VLPCalc`."""

from __future__ import annotations

from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from .excel_io import find_cell, is_numeric
from .gap_naming import gap_well_name, prosper_model_in_gap
from .petex_client import PetexClient, terminate
from .units import ipt_unit_conv


def vlp_calc_all(client: PetexClient, config_ws: Worksheet, validation_ws: Worksheet) -> None:
    """Port of `VLPCalc_All`."""
    model_location = find_cell(config_ws, "GAP Model").offset(0, 1).value
    if not model_location:
        terminate("GAP model location not entered in Configuration.")
    if not client.open_file(model_location, "GAP"):
        terminate()

    well_cell = find_cell(validation_ws, "Well Name").offset(4, 0)
    n_row = 0
    while not well_cell.is_empty:
        wellname = well_cell.value
        # `gap_well_name` already raises ProgramTerminated when the well isn't
        # mapped, so - unlike the VBA - there's no reachable "-" branch to check here.
        gap_well = gap_well_name(config_ws, wellname)
        prosper_model = prosper_model_in_gap(client, gap_well)
        if not client.open_file(prosper_model, "PROSPER"):
            terminate()
        vlp_calc(client, validation_ws, n_row)
        n_row += 1
        well_cell = well_cell.offset(1, 0)


def vlp_calc_selected_row(
    client: PetexClient, config_ws: Worksheet, validation_ws: Worksheet, n_row: int
) -> None:
    """Port of `VLPCalc_SelectedWell`.

    The VBA version derived `nRow` from the currently selected Excel cell; a
    headless script has no such selection, so the caller passes the
    (0-based) data-row index directly instead.
    """
    if n_row < 0 or n_row > 500:
        terminate("Error: Selected row out-with limits")

    model_location = find_cell(config_ws, "GAP Model").offset(0, 1).value
    if not model_location:
        terminate("GAP model location not entered in Configuration.")
    if not client.open_file(model_location, "GAP"):
        terminate()

    wellname = find_cell(validation_ws, "Well Name").offset(4 + n_row, 0).value
    gap_well = gap_well_name(config_ws, wellname)
    prosper_model = prosper_model_in_gap(client, gap_well)
    if not client.open_file(prosper_model, "PROSPER"):
        terminate()
    vlp_calc(client, validation_ws, n_row)


def vlp_calc(client: PetexClient, ws: Worksheet, n_row: int) -> None:
    """Port of `VLPCalc(nRow)`: runs a PROSPER VLP calculation for one well row
    and writes back the calculated BHP and IPR dP offset(s).
    """
    whp = find_cell(ws, "WHP").offset(4 + n_row, 0).value
    wc = find_cell(ws, "Watercut").offset(4 + n_row, 0).value
    gor = find_cell(ws, "GOR").offset(4 + n_row, 0).value
    liq_rate = find_cell(ws, "Liquid Rate").offset(4 + n_row, 0).value
    meas_uz_tbg_press = find_cell(ws, "UZ Tubing Pressure").offset(4 + n_row, 0).value

    calc_uz_tbg_press: Any = "-"
    ipr_dp_offset: Any = "-"

    if is_numeric(whp) and is_numeric(wc) and is_numeric(gor) and is_numeric(liq_rate):
        whp_v, wc_v, gor_v, liq_rate_v = float(whp), float(wc), float(gor), float(liq_rate)
        if whp_v > 0 and wc_v >= 0 and gor_v > 0 and liq_rate_v > 0:
            client.DoSet("PROSPER.DOUNITCONV", 0)
            client.DoSet("PROSPER.ANL.VLP.Sens.SensDB.Clear", "")
            client.DoSet("PROSPER.ANL.VLP.FirstNode", 0)
            client.DoSet("PROSPER.ANL.VLP.LastNode", 9999)
            client.DoSet("PROSPER.ANL.VLP.RateMethod", 1)
            client.DoSet("PROSPER.ANL.VLP.RATES [$]", "")

            client.DoSet(
                "PROSPER.ANL.VLP.Pres",
                ipt_unit_conv(
                    find_cell(ws, "WHP").offset(3, 0).value,
                    find_cell(ws, "WHP").offset(2, 0).value,
                    whp_v,
                ),
            )
            client.DoSet(
                "PROSPER.ANL.VLP.WC",
                ipt_unit_conv(
                    find_cell(ws, "Watercut").offset(3, 0).value,
                    find_cell(ws, "Watercut").offset(2, 0).value,
                    wc_v,
                ),
            )
            client.DoSet(
                "PROSPER.ANL.VLP.GORVAL",
                ipt_unit_conv(
                    find_cell(ws, "GOR").offset(3, 0).value,
                    find_cell(ws, "GOR").offset(2, 0).value,
                    gor_v,
                ),
            )
            client.DoSet(
                "PROSPER.ANL.VLP.Rates[0]",
                ipt_unit_conv(
                    find_cell(ws, "Liquid Rate").offset(3, 0).value,
                    find_cell(ws, "Liquid Rate").offset(2, 0).value,
                    liq_rate_v,
                ),
            )

            client.do_slow_cmd("PROSPER.ANL.VLP.CALC")

            calc_uz_tbg_press = client.DoGet("PROSPER.OUT.VLP.RES[0][0].PRES")

            if is_numeric(meas_uz_tbg_press) and float(meas_uz_tbg_press) > 0:
                meas_field = ipt_unit_conv(
                    find_cell(ws, "UZ Tubing Pressure").offset(3, 0).value,
                    find_cell(ws, "UZ Tubing Pressure").offset(2, 0).value,
                    float(meas_uz_tbg_press),
                )
                ipr_dp_offset = calc_uz_tbg_press - meas_field
            else:
                ipr_dp_offset = 0
        else:
            calc_uz_tbg_press = "-"
            ipr_dp_offset = "-"
    else:
        calc_uz_tbg_press = "-"
        ipr_dp_offset = "-"

    if is_numeric(calc_uz_tbg_press) and float(calc_uz_tbg_press) > 0:
        calc_uz_tbg_press = ipt_unit_conv(
            find_cell(ws, "PROSPER BHP").offset(2, 0).value,
            find_cell(ws, "PROSPER BHP").offset(3, 0).value,
            float(calc_uz_tbg_press),
        )

    find_cell(ws, "PROSPER BHP").offset(4 + n_row, 0).value = calc_uz_tbg_press
    find_cell(ws, "IPR dP Offset").offset(4 + n_row, 0).value = ipr_dp_offset
    if calc_uz_tbg_press != "-":
        if not is_numeric(meas_uz_tbg_press) or float(meas_uz_tbg_press) < 0:
            find_cell(ws, "IPR dP Offset").offset(4 + n_row, 1).value = (
                "Upper gauge pressure not available for VLP comparison"
            )

    n_zones = find_cell(ws, "Number of Zones").offset(4 + n_row, 0).value
    if n_zones == 1:
        find_cell(ws, "UZ IPR dP Offset").offset(4 + n_row, 0).value = ipr_dp_offset
    elif n_zones == 2:
        find_cell(ws, "UZ IPR dP Offset").offset(4 + n_row, 0).value = ipr_dp_offset
        find_cell(ws, "LZ IPR dP Offset").offset(4 + n_row, 0).value = ipr_dp_offset
    elif n_zones == 3:
        find_cell(ws, "UZ IPR dP Offset").offset(4 + n_row, 0).value = ipr_dp_offset
        find_cell(ws, "MZ IPR dP Offset").offset(4 + n_row, 0).value = ipr_dp_offset
        find_cell(ws, "LZ IPR dP Offset").offset(4 + n_row, 0).value = ipr_dp_offset
