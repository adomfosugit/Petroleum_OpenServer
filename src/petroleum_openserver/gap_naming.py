"""Port of the well/riser name-mapping helpers: `GAPWellName`, `GAPRiserName`,
`PROSPERModelinGAP`, `RiserforWell`, `RowinConfig`, `TagColinConfig`,
`TagColinConfig_nCol`, `ZoneStatus`.

These all operate on either the "Configuration" worksheet (the mapping from
the field's own well/riser names to the names used inside the GAP model) or
whichever "Validation"-style worksheet is currently active, plus - for
`prosper_model_in_gap` - a live GAP OpenServer session. Rather than relying
on Excel's implicit `ActiveSheet`, every function here takes the worksheet(s)
it needs explicitly.
"""

from __future__ import annotations

from typing import Optional

from openpyxl.worksheet.worksheet import Worksheet

from .excel_io import find_cell, is_numeric
from .exceptions import ProgramTerminated
from .petex_client import PetexClient


def gap_well_name(config_ws: Worksheet, wellname: str) -> str:
    """Port of `GAPWellName`."""
    target = wellname.strip().lower()
    ref = find_cell(config_ws, "Well Name").offset(2, 0)
    while not ref.is_empty:
        if str(ref.value).strip().lower() == target:
            return ref.offset(0, 1).value
        ref = ref.offset(1, 0)
    raise ProgramTerminated(f"Well {wellname} not in GAP as per Configuration")


def gap_riser_name(config_ws: Worksheet, riser_name: str) -> str:
    """Port of `GAPRiserName`."""
    target = riser_name.strip().lower()
    ref = find_cell(config_ws, "Riser Name").offset(2, 0)
    while not ref.is_empty:
        if str(ref.value).strip().lower() == target:
            return ref.offset(0, 1).value
        ref = ref.offset(1, 0)
    raise ProgramTerminated(f"Riser {riser_name} not in GAP as per Configuration")


def prosper_model_in_gap(client: PetexClient, wellname: str) -> str:
    """Port of `PROSPERModelinGAP`: looks up the PROSPER model file path attached
    to `wellname` inside the currently open GAP model.
    """
    well_count = int(client.DoGet("GAP.MOD[{PROD}].WELL.Count"))
    target = wellname.strip().lower()
    for i in range(well_count):
        label = client.DoGet(f"GAP.MOD[{{PROD}}].WELL[{i}].Label")
        if str(label).strip().lower() == target:
            model = client.DoGet(f"GAP.MOD[{{PROD}}].WELL[{i}].File")
            if model:
                return str(model)
            break
    raise ProgramTerminated(f"PROSPER Model not available in GAP for the well {wellname}")


def riser_for_well(validation_ws: Worksheet, wellname: str) -> str:
    """Port of `RiserforWell`: reads the riser routing recorded next to `wellname`
    on the validation sheet, matching on the first 3 characters like the VBA did.
    """
    prefix = wellname[:3].strip().lower()
    ref = find_cell(validation_ws, "Well Name").offset(4, 0)
    while not ref.is_empty:
        if str(ref.value)[:3].strip().lower() == prefix:
            return ref.offset(0, 1).value
        ref = ref.offset(1, 0)
    return "-"


def row_in_config(
    validation_ws: Worksheet,
    config_ws: Worksheet,
    row_in_validation: int,
    riser_or_well: str,
) -> int:
    """Port of `RowinConfig`."""
    if riser_or_well == "Riser":
        header = "Riser Name"
    elif riser_or_well == "Well":
        header = "Well Name"
    else:
        raise ValueError("riser_or_well must be 'Riser' or 'Well'")

    val_ref = find_cell(validation_ws, header).offset(4 + row_in_validation, 0)
    cfg_ref = find_cell(config_ws, header).offset(2, 0)
    target = str(val_ref.value).strip().lower() if val_ref.value is not None else None

    n_row = 0
    ref = cfg_ref
    while not ref.is_empty:
        if str(ref.value).strip().lower() == target:
            return n_row
        n_row += 1
        ref = ref.offset(1, 0)
    raise ProgramTerminated(f"{riser_or_well} {val_ref.value} does not exist in Configuration.")


def tag_col_in_config(
    validation_ws: Worksheet,
    config_ws: Worksheet,
    tag_col_in_validation: int,
    riser_or_well: str,
) -> Optional[int]:
    """Port of `TagColinConfig`. Returns None where the VBA used the 9999 sentinel
    (heading not present in Configuration - i.e. probably a calculated column)."""
    if riser_or_well == "Riser":
        header = "Riser Name"
    elif riser_or_well == "Well":
        header = "Well Name"
    else:
        raise ValueError("riser_or_well must be 'Riser' or 'Well'")

    val_header_ref = find_cell(validation_ws, header)
    cfg_header_ref = find_cell(config_ws, header)
    target_value = val_header_ref.offset(0, tag_col_in_validation).value
    target = str(target_value).strip().lower() if target_value is not None else None

    n_col = 0
    ref = cfg_header_ref
    while not ref.is_empty:
        if str(ref.value).strip().lower() == target:
            return n_col
        n_col += 1
        ref = ref.offset(0, 1)
    return None


def tag_col_in_config_ncol(config_ws: Worksheet, column_name: str) -> Optional[int]:
    """Port of `TagColinConfig_nCol`: looks up a well-related column by name
    directly (used to pull zonal oil/water/gas rate columns that aren't part
    of the Validation sheet layout). Returns None instead of the 9999 sentinel.
    """
    target = column_name.strip().lower()
    n_col = 0
    ref = find_cell(config_ws, "Well Name")
    while not ref.is_empty:
        if str(ref.value).strip().lower() == target:
            return n_col
        n_col += 1
        ref = ref.offset(0, 1)
    return None


def zone_status(validation_ws: Worksheet, uzmzlz: str, n_row: int) -> str:
    """Port of `ZoneStatus`: "Open"/"Closed" based on ICV setting and zone liquid
    rate, or "-" if the ICV setting itself isn't numeric.
    """
    icv_setting = find_cell(validation_ws, f"{uzmzlz} ICV").offset(4 + n_row, 0).value
    zone_liq_rate = find_cell(validation_ws, f"{uzmzlz} Liquid Rate").offset(4 + n_row, 0).value
    if is_numeric(icv_setting):
        if float(icv_setting) >= 1 and is_numeric(zone_liq_rate) and float(zone_liq_rate) > 0:
            return "Open"
        return "Closed"
    return "-"
