"""Port of `GetData_All`, `ClearAllData`, `GetRiserData`, `GetWellData`,
`GetMeasuredTotals`, `GetAllocatedTotals`, `PopulateRiserandWellnamesfromConfigtoValidation`,
`GetNumberofZones`, `VariableValue`, `GetWellRateWCGORandStatus`,
`GetICVdPandZoneStatus` and `GetChokedP`.

Unlike `gap_validation.py`/`vlp.py`, none of this talks to OpenServer - it
only pulls data from the Configuration sheet, the OFM database and a PI
System (via `pi_data.py`) into the validation sheet, and computes the
handful of columns the original sheet worked out itself (well liquid
rate/WC/GOR/status, choke dP, ICV dP, zone counts).
"""

from __future__ import annotations

import warnings
from typing import Any, Optional

from openpyxl.worksheet.worksheet import Worksheet

from .excel_io import Ref, find_cell, is_numeric, iter_down
from .exceptions import ProgramTerminated
from .gap_naming import row_in_config, tag_col_in_config, tag_col_in_config_ncol, zone_status
from .ofm import ofm_value
from .petex_client import terminate
from .pi_data import pi_value
from .totals import delete_allocated_totals, delete_measured_totals, delete_total_rates
from .units import ipt_unit_conv

_ZONES = ("UZ", "MZ", "LZ")


def variable_value(
    config_ws: Worksheet,
    validation_ws: Worksheet,
    pi_server: Optional[str],
    variable_tag: Any,
    required_unit: str,
    zone_name: str = "",
) -> Any:
    """Port of `VariableValue`."""
    if variable_tag is None:
        return "-"
    text = str(variable_tag)
    if ":" in text:
        source = text.split(":", 1)[0].strip().upper()
        if source == "OFM":
            return ofm_value(config_ws, validation_ws, text, required_unit, zone_name)
        if source == "PI":
            if pi_server is None:
                raise ProgramTerminated(f"No PI server configured to resolve {text}")
            selected_date = find_cell(validation_ws, "Date").offset(0, 1).value
            return pi_value(text, required_unit, pi_server, selected_date, ipt_unit_conv)
        return variable_tag
    return variable_tag


def _clear_block(start: Ref, n_rows: int, n_cols: int) -> None:
    for r in range(n_rows):
        for c in range(n_cols):
            start.offset(r, c).clear_contents()


def clear_all_data(ws: Worksheet) -> None:
    """Port of `ClearAllData` (sheet protection toggling is dropped - not
    meaningful outside of interactive Excel)."""
    _clear_block(find_cell(ws, "Riser Name").offset(4, 0), 500, 3)
    _clear_block(find_cell(ws, "Well Name").offset(4, 0), 500, 130)  # A:DZ
    delete_measured_totals(ws)
    delete_allocated_totals(ws)
    delete_total_rates(ws)


def populate_riser_and_well_names_from_config_to_validation(
    config_ws: Worksheet, validation_ws: Worksheet
) -> None:
    """Port of `PopulateRiserandWellnamesfromConfigtoValidation`."""
    for header in ("Riser Name", "Well Name"):
        val_ref = find_cell(validation_ws, header).offset(4, 0)
        cfg_ref = find_cell(config_ws, header).offset(2, 0)
        while not cfg_ref.is_empty:
            val_ref.value = cfg_ref.value
            val_ref = val_ref.offset(1, 0)
            cfg_ref = cfg_ref.offset(1, 0)


def get_number_of_zones(config_ws: Worksheet, validation_ws: Worksheet, n_row: int) -> None:
    """Port of `GetNumberofZones`."""
    config_row = row_in_config(validation_ws, config_ws, n_row, "Well")
    n_zone = 0
    for header in ("OFM UZ Name", "OFM MZ Name", "OFM LZ Name"):
        value = find_cell(config_ws, header).offset(2 + config_row, 0).value
        if value is not None and value != "":
            n_zone += 1
    find_cell(validation_ws, "Number of Zones").offset(4 + n_row, 0).value = n_zone


def get_riser_data(
    config_ws: Worksheet, validation_ws: Worksheet, pi_server: Optional[str], n_row: int
) -> None:
    """Port of `GetRiserData`."""
    config_row = row_in_config(validation_ws, config_ws, n_row, "Riser")
    config_riser_ref = find_cell(config_ws, "Riser Name").offset(2 + config_row, 0)
    header_ref = find_cell(validation_ws, "Riser Name")

    val_col_ref = header_ref.offset(0, 1)
    n_col = 1
    while not val_col_ref.is_empty:
        reqd_unit = val_col_ref.offset(3, 0).value
        config_col = tag_col_in_config(validation_ws, config_ws, n_col, "Riser")

        temp: Any = None
        if config_col is not None:
            variable_tag = config_riser_ref.offset(0, config_col).value
            zone_name = "FPSO" if val_col_ref.value == "Riser Gas Lift" else ""
            temp = variable_value(config_ws, validation_ws, pi_server, variable_tag, reqd_unit, zone_name)

        if temp is not None:
            header_ref.offset(4 + n_row, n_col).value = temp
        n_col += 1
        val_col_ref = val_col_ref.offset(0, 1)


def _zonal_rate(
    config_ws: Worksheet,
    validation_ws: Worksheet,
    config_well_ref: Ref,
    pi_server: Optional[str],
    uzmzlz: str,
    rate_label: str,
    unit: str,
    zone_name: str,
) -> Any:
    column_name = f"{uzmzlz} {rate_label}"
    col = tag_col_in_config_ncol(config_ws, column_name)
    if col is None:
        warnings.warn(f"{column_name} column in Configuration heading not found")
        return "-"
    variable_tag = config_well_ref.offset(0, col).value
    value = variable_value(config_ws, validation_ws, pi_server, variable_tag, unit, zone_name)
    return value if is_numeric(value) else "-"


def _calculated_well_column(
    config_ws: Worksheet,
    validation_ws: Worksheet,
    config_well_ref: Ref,
    pi_server: Optional[str],
    col_header: str,
    zone_name: str,
) -> Any:
    """The "not defined in Configuration hence a calculated value" branch of `GetWellData`."""
    uzmzlz = col_header[:2]

    if col_header.endswith("Liquid Rate") and uzmzlz in _ZONES:
        if not zone_name:
            return "-"
        oil_rate = _zonal_rate(config_ws, validation_ws, config_well_ref, pi_server, uzmzlz, "Oil Rate", "stb/d", zone_name)
        wat_rate = _zonal_rate(config_ws, validation_ws, config_well_ref, pi_server, uzmzlz, "Water Rate", "stb/d", zone_name)
        if oil_rate == "-" or wat_rate == "-":
            return "-"
        return float(oil_rate) + float(wat_rate)

    if col_header.endswith("Watercut") and uzmzlz in _ZONES:
        if not zone_name:
            return "-"
        oil_rate = _zonal_rate(config_ws, validation_ws, config_well_ref, pi_server, uzmzlz, "Oil Rate", "stb/d", zone_name)
        wat_rate = _zonal_rate(config_ws, validation_ws, config_well_ref, pi_server, uzmzlz, "Water Rate", "stb/d", zone_name)
        if oil_rate == "-" or wat_rate == "-":
            return "-"
        total = float(oil_rate) + float(wat_rate)
        return float(wat_rate) * 100 / total if total > 0 else "-"

    if col_header.endswith("GOR") and uzmzlz in _ZONES:
        if not zone_name:
            return "-"
        oil_rate = _zonal_rate(config_ws, validation_ws, config_well_ref, pi_server, uzmzlz, "Oil Rate", "stb/d", zone_name)
        gas_rate = _zonal_rate(config_ws, validation_ws, config_well_ref, pi_server, uzmzlz, "Gas Rate", "mmscf/d", zone_name)
        if oil_rate == "-" or gas_rate == "-":
            return "-"
        oil_rate, gas_rate = float(oil_rate), float(gas_rate)
        return gas_rate * 1_000_000 / oil_rate if oil_rate > 0 and gas_rate > 0 else "-"

    # Status, Number of Zones, Choke dP, Liquid Rate, Watercut, GOR (well-level),
    # UZ/MZ/LZ IPR dP Offset and UZ/MZ/LZ ICV dP are all filled in later by
    # get_number_of_zones / get_well_rate_wc_gor_and_status / get_choke_dp /
    # get_icv_dp_and_zone_status, or (IPR dP Offset) by vlp.vlp_calc.
    return "-"


def get_well_data(
    config_ws: Worksheet, validation_ws: Worksheet, pi_server: Optional[str], n_row: int
) -> None:
    """Port of `GetWellData`."""
    config_row = row_in_config(validation_ws, config_ws, n_row, "Well")
    config_well_ref = find_cell(config_ws, "Well Name").offset(2 + config_row, 0)
    header_ref = find_cell(validation_ws, "Well Name")

    val_col_ref = header_ref.offset(0, 1)
    n_col = 1
    while not val_col_ref.is_empty:
        col_header = str(val_col_ref.value)
        zone_name = ""
        if col_header[:2] == "UZ":
            zone_name = config_well_ref.offset(0, 2).value or ""
        elif col_header[:2] == "MZ":
            zone_name = config_well_ref.offset(0, 3).value or ""
        elif col_header[:2] == "LZ":
            zone_name = config_well_ref.offset(0, 4).value or ""

        reqd_unit = val_col_ref.offset(3, 0).value
        config_col = tag_col_in_config(validation_ws, config_ws, n_col, "Well")

        if config_col is not None:
            variable_tag = config_well_ref.offset(0, config_col).value
            temp = variable_value(config_ws, validation_ws, pi_server, variable_tag, reqd_unit, zone_name)
        else:
            temp = _calculated_well_column(config_ws, validation_ws, config_well_ref, pi_server, col_header, zone_name)

        header_ref.offset(4 + n_row, n_col).value = temp
        n_col += 1
        val_col_ref = val_col_ref.offset(0, 1)

    get_number_of_zones(config_ws, validation_ws, n_row)
    get_well_rate_wc_gor_and_status(validation_ws, n_row)
    get_choke_dp(validation_ws, n_row)
    get_icv_dp_and_zone_status(validation_ws, n_row)


def get_well_rate_wc_gor_and_status(ws: Worksheet, n_row: int) -> None:
    """Port of `GetWellRateWCGORandStatus`."""
    well_liq_rate = well_oil_rate = well_gas_rate = 0.0
    for uzmzlz in _ZONES:
        zone_liq_rate = find_cell(ws, f"{uzmzlz} Liquid Rate").offset(4 + n_row, 0).value
        if is_numeric(zone_liq_rate) and float(zone_liq_rate) > 10:
            wc = float(find_cell(ws, f"{uzmzlz} Watercut").offset(4 + n_row, 0).value)
            gor = float(find_cell(ws, f"{uzmzlz} GOR").offset(4 + n_row, 0).value)
            zone_oil_rate = float(zone_liq_rate) * (100 - wc) / 100
            zone_gas_rate = gor * zone_oil_rate / 1_000_000
            zone_wat_rate = float(zone_liq_rate) * wc / 100
        else:
            zone_oil_rate = zone_gas_rate = zone_wat_rate = 0.0

        well_liq_rate += zone_oil_rate + zone_wat_rate
        well_oil_rate += zone_oil_rate
        well_gas_rate += zone_gas_rate

    find_cell(ws, "Liquid Rate").offset(4 + n_row, 0).value = well_liq_rate
    if well_liq_rate > 0:
        well_wc: Any = (well_liq_rate - well_oil_rate) * 100 / well_liq_rate
        well_gor: Any = well_gas_rate * 1_000_000 / well_oil_rate if well_oil_rate > 0 else "-"
    else:
        well_wc = "-"
        well_gor = "-"
    find_cell(ws, "Watercut").offset(4 + n_row, 0).value = well_wc
    find_cell(ws, "GOR").offset(4 + n_row, 0).value = well_gor
    find_cell(ws, "Status").offset(4 + n_row, 0).value = "Open" if well_liq_rate > 0 else "Closed"


def _flag_if_invalid(ws: Worksheet, header: str, n_row: int, *, positive: bool = False, non_negative: bool = False) -> None:
    ref = find_cell(ws, header).offset(4 + n_row, 0)
    value = ref.value
    if not is_numeric(value):
        ref.value = "ERROR"
        return
    numeric_value = float(value)
    if positive and not numeric_value > 0:
        ref.value = "ERROR"
    elif non_negative and not numeric_value >= 0:
        ref.value = "ERROR"


def get_icv_dp_and_zone_status(ws: Worksheet, n_row: int) -> None:
    """Port of `GetICVdPandZoneStatus`."""
    well_status = find_cell(ws, "Status").offset(4 + n_row, 0).value
    n_zones = find_cell(ws, "Number of Zones").offset(4 + n_row, 0).value

    if is_numeric(n_zones) and float(n_zones) > 1:
        for uzmzlz in _ZONES:
            status = zone_status(ws, uzmzlz, n_row)
            icv_dp: Any = "-"

            if status == "Open":
                icv_setting = find_cell(ws, f"{uzmzlz} ICV").offset(4 + n_row, 0).value
                annulus_press = find_cell(ws, f"{uzmzlz} Annulus Pressure").offset(4 + n_row, 0).value
                tubing_press = find_cell(ws, f"{uzmzlz} Tubing Pressure").offset(4 + n_row, 0).value

                if is_numeric(annulus_press) and float(annulus_press) > 0:
                    if is_numeric(tubing_press) and float(tubing_press) > 0:
                        annulus_press, tubing_press = float(annulus_press), float(tubing_press)
                        icv_dp = annulus_press - tubing_press if annulus_press > tubing_press else 0
                    elif is_numeric(icv_setting):
                        icv_dp = 0 if float(icv_setting) > 9 else "ERROR"
                elif is_numeric(icv_setting):
                    if float(icv_setting) > 9:
                        icv_dp = 0
                    else:
                        # There are records where no rate has been allocated to the
                        # well even though its ICVs are open; assume it's closed.
                        icv_dp = "-" if well_status != "Open" else "ERROR"

                find_cell(ws, f"{uzmzlz} ICV dP").offset(4 + n_row, 0).value = icv_dp
                _flag_if_invalid(ws, f"{uzmzlz} PI", n_row, positive=True)
                _flag_if_invalid(ws, f"{uzmzlz} Watercut", n_row, non_negative=True)
                _flag_if_invalid(ws, f"{uzmzlz} GOR", n_row, positive=True)
            else:
                find_cell(ws, f"{uzmzlz} ICV dP").offset(4 + n_row, 0).value = icv_dp
    elif n_zones == 1:
        find_cell(ws, "UZ ICV dP").offset(4 + n_row, 0).value = "-"
        if well_status == "Open":
            _flag_if_invalid(ws, "UZ PI", n_row, positive=True)
            _flag_if_invalid(ws, "UZ Watercut", n_row, non_negative=True)
            _flag_if_invalid(ws, "UZ GOR", n_row, positive=True)
    else:
        wellname = find_cell(ws, "Well Name").offset(4 + n_row, 0).value
        terminate(f"Number of zones is not valid for the well {wellname}")


def get_choke_dp(ws: Worksheet, n_row: int) -> None:
    """Port of `GetChokedP`."""
    well_status = find_cell(ws, "Status").offset(4 + n_row, 0).value
    choke_dp: Any = "-"
    if well_status == "Open":
        whp = find_cell(ws, "WHP").offset(4 + n_row, 0).value
        flp = find_cell(ws, "FLP").offset(4 + n_row, 0).value
        if is_numeric(whp) and float(whp) > 0:
            if is_numeric(flp) and float(flp) > 0:
                whp, flp = float(whp), float(flp)
                choke_dp = whp - flp if whp > flp else 0
            else:
                choke_dp = "ERROR"
        else:
            choke_dp = "ERROR"
    find_cell(ws, "Choke dP").offset(4 + n_row, 0).value = choke_dp


def _sum_misc_tags(
    config_ws: Worksheet, validation_ws: Worksheet, pi_server: Optional[str], base_ref: Ref
) -> Any:
    total = 0.0
    for i in range(5):
        variable_tag = base_ref.offset(i, 2).value
        reqd_unit = base_ref.offset(i, 3).value
        value = variable_value(config_ws, validation_ws, pi_server, variable_tag, reqd_unit)
        if not is_numeric(value):
            return "ERROR"
        total += float(value)
    return total


def get_measured_totals(
    config_ws: Worksheet, validation_ws: Worksheet, pi_server: Optional[str] = None
) -> None:
    """Port of `GetMeasuredTotals`."""
    total_ref = find_cell(validation_ws, "Total Oil Rate")
    misc_tags = find_cell(config_ws, "Misc Tags").offset(2, 1)

    total_ref.offset(2, 0).value = _sum_misc_tags(config_ws, validation_ws, pi_server, misc_tags)
    total_ref.offset(2, 1).value = _sum_misc_tags(
        config_ws, validation_ws, pi_server, misc_tags.offset(5, 0)
    )
    total_ref.offset(2, 2).value = _sum_misc_tags(
        config_ws, validation_ws, pi_server, misc_tags.offset(10, 0)
    )


def get_allocated_totals(ws: Worksheet) -> None:
    """Port of `GetAllocatedTotals`."""
    total_oil = total_gas = total_wat = 0.0
    n_row = 0
    for _ in iter_down(find_cell(ws, "Well Name").offset(4, 0)):
        liq_rate = find_cell(ws, "Liquid Rate").offset(4 + n_row, 0).value
        wc = find_cell(ws, "Watercut").offset(4 + n_row, 0).value
        gor = find_cell(ws, "GOR").offset(4 + n_row, 0).value
        liq_rate = float(liq_rate) if is_numeric(liq_rate) else 0.0
        wc = float(wc) if is_numeric(wc) else 0.0
        gor = float(gor) if is_numeric(gor) else 0.0

        if liq_rate == 0 or gor == 0:
            oil_rate = gas_rate = wat_rate = 0.0
        else:
            oil_rate = liq_rate * (1 - wc / 100)
            gas_rate = oil_rate * gor / 1_000_000
            wat_rate = liq_rate * (wc / 100)

        total_oil += oil_rate
        total_gas += gas_rate
        total_wat += wat_rate
        n_row += 1

    total_ref = find_cell(ws, "Total Oil Rate")
    total_ref.offset(3, 0).value = total_oil
    total_ref.offset(3, 1).value = total_gas
    total_ref.offset(3, 2).value = total_wat


def get_data_all(
    config_ws: Worksheet, validation_ws: Worksheet, pi_server: Optional[str] = None
) -> None:
    """Port of `GetData_All`. The original's "this clears everything, proceed?"
    confirmation MsgBox is the caller's responsibility, not this function's."""
    clear_all_data(validation_ws)
    populate_riser_and_well_names_from_config_to_validation(config_ws, validation_ws)

    n_row = 0
    for _ in iter_down(find_cell(validation_ws, "Riser Name").offset(4, 0)):
        get_riser_data(config_ws, validation_ws, pi_server, n_row)
        n_row += 1

    n_row = 0
    for _ in iter_down(find_cell(validation_ws, "Well Name").offset(4, 0)):
        get_well_data(config_ws, validation_ws, pi_server, n_row)
        n_row += 1

    get_measured_totals(config_ws, validation_ws, pi_server)
    get_allocated_totals(validation_ws)
