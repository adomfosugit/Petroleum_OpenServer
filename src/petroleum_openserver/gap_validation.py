"""Port of `RunGAPValidation`, `SetRiserData_GAP`, `SetWellRouting`,
`RunGAP_WellValidation_All/_Selected`, `SetWellData_GAP`, `GetWellData_GAP`
and `getFlowlineInletJointIndex`.
"""

from __future__ import annotations

from typing import Any, Optional

from openpyxl.worksheet.worksheet import Worksheet

from .excel_io import find_cell, is_numeric, iter_down
from .gap_naming import gap_riser_name, gap_well_name, riser_for_well, zone_status
from .petex_client import PetexClient, terminate
from .totals import delete_total_rates, get_total_rates
from .units import ipt_unit_conv

_SKIP_HEADERS = {"none", "nonex", "runcase"}


def run_gap_validation(client: PetexClient, config_ws: Worksheet, ws: Worksheet) -> None:
    """Port of `RunGAPValidation`."""
    model_location = find_cell(config_ws, "GAP Model").offset(0, 1).value
    if not model_location:
        terminate("GAP model location not entered in Configuration.")
    if not client.open_file(model_location, "GAP"):
        terminate()

    client.DoSet("GAP.DOUNITCONV", 0)

    delete_total_rates(ws)
    set_well_routing(client, config_ws, ws)

    n_row = 0
    for _ in iter_down(find_cell(ws, "Riser Name").offset(4, 0)):
        set_riser_data_gap(client, config_ws, ws, n_row)
        n_row += 1

    n_row = 0
    for _ in iter_down(find_cell(ws, "Well Name").offset(4, 0)):
        set_well_data_gap(client, config_ws, ws, n_row)
        n_row += 1

    client.do_slow_cmd("GAP.SOLVENETWORK(0)")

    n_row = 0
    for _ in iter_down(find_cell(ws, "Well Name").offset(4, 0)):
        get_well_data_gap(client, config_ws, ws, n_row)
        n_row += 1

    get_total_rates(client, ws)


def set_riser_data_gap(client: PetexClient, config_ws: Worksheet, ws: Worksheet, n_row: int) -> None:
    """Port of `SetRiserData_GAP(nRow)`."""
    client.DoSet("GAP.DOUNITCONV", 0)

    header = find_cell(ws, "Riser Name")
    os_row = header.offset(1, 0)
    val_row = header.offset(4, 0)

    riser_name = ""
    n_col = 0
    while not os_row.offset(0, n_col).is_empty:
        os_string = os_row.offset(0, n_col).value
        header_text = str(os_row.offset(-1, n_col).value or "").strip().lower()
        if str(os_string).strip().lower() != "none":
            the_val = val_row.offset(n_row, n_col).value
            if the_val is not None and the_val != "-" and str(the_val).strip().lower() != "none":
                if n_col == 0 and header_text == "riser name":
                    if the_val != "":
                        riser_name = gap_riser_name(config_ws, the_val)
                else:
                    if header_text == "riser gas lift":
                        if is_numeric(the_val) and float(the_val) > 0:
                            client.do_slow_cmd(f"GAP.MOD[0].Source[{{{riser_name}_GL}}].UNMASK()")
                        else:
                            client.do_slow_cmd(f"GAP.MOD[0].Source[{{{riser_name}_GL}}].MASK()")
                    resolved = str(os_string).replace("riserName", riser_name[:3])
                    if is_numeric(the_val):
                        the_val = ipt_unit_conv(
                            os_row.offset(2, n_col).value,
                            os_row.offset(1, n_col).value,
                            float(the_val),
                        )
                    client.do_set_no_err(resolved, the_val)
        n_col += 1


def set_well_routing(client: PetexClient, config_ws: Worksheet, ws: Worksheet) -> None:
    """Port of `SetWellRouting`."""
    riser_j03 = riser_for_well(ws, "J03")
    riser_j60 = riser_for_well(ws, "J60")
    riser_j24 = riser_for_well(ws, "J24")
    riser_j51 = riser_for_well(ws, "J51")
    riser_j77 = riser_for_well(ws, "J77")

    if riser_j03 != riser_j60:
        terminate("Check well routings for J03 and J60 as they should be the same")
    if riser_j24 != riser_j51 or riser_j24 != riser_j77 or riser_j51 != riser_j77:
        terminate("Check well routings for J24, J51 and J77 as they should be the same")

    for well_ref in iter_down(find_cell(ws, "Well Name").offset(4, 0)):
        wellname = well_ref.value
        prefix = str(wellname)[:3].upper()
        if prefix in ("J03", "J60"):
            valve_name = "TIM3"
        elif prefix in ("J24", "J51", "J77"):
            valve_name = "TIM1"
        else:
            valve_name = gap_well_name(config_ws, wellname)[:3]

        riser = riser_for_well(ws, wellname)
        if riser == "-":
            terminate(f"Well routing not found for {wellname}")
        elif riser in ("R11", "R14", "R17"):
            client.DoSet(f"GAP.MOD[{{PROD}}].VALVE[{{{valve_name}_a}}].StateValue", 0)
            client.DoSet(f"GAP.MOD[{{PROD}}].VALVE[{{{valve_name}_b}}].StateValue", 1)
        elif riser in ("R10", "R13", "R16"):
            client.DoSet(f"GAP.MOD[{{PROD}}].VALVE[{{{valve_name}_a}}].StateValue", 1)
            client.DoSet(f"GAP.MOD[{{PROD}}].VALVE[{{{valve_name}_b}}].StateValue", 0)
        else:
            terminate(f"Well routing not valid for {wellname}")


def get_flowline_inlet_joint_index(client: PetexClient, wellname: str) -> int:
    """Port of `getFlowlineInletJointIndex`."""
    prefix = str(wellname)[:3]
    joint_count = int(client.DoGet("GAP.MOD[0].JOINT.COUNT"))
    for n in range(joint_count + 1):  # VBA `For n = 0 To Count` includes the endpoint
        connected_fl = client.do_gap_func_fast(
            f"GAP.MOD[0].JOINT[{n}].ISCONNECTEDTO(MOD[0].PIPE[{{{prefix}_fl}}])"
        )
        connected_chk = client.do_gap_func_fast(
            f"GAP.MOD[0].JOINT[{n}].ISCONNECTEDTO(MOD[0].INLGEN[{{{prefix}_chk}}])"
        )
        if connected_fl == 1 and connected_chk == 1:
            return n
    # The VBA function never assigned its return value in this case, which
    # for a Long defaults to 0 - kept as-is rather than "fixed" here.
    return 0


def _clear_outputs(out_os_row, out_val_row, n_row: int) -> None:
    n_col = 0
    while not out_os_row.offset(0, n_col).is_empty:
        header_text = str(out_os_row.offset(0, n_col).value or "").strip().lower()
        if header_text not in _SKIP_HEADERS:
            out_val_row.offset(n_row, n_col).clear_contents()
        n_col += 1


def run_gap_well_validation_all(client: PetexClient, config_ws: Worksheet, ws: Worksheet) -> None:
    """Port of `RunGAP_WellValidation_All`."""
    model_location = find_cell(config_ws, "GAP Model").offset(0, 1).value
    if not model_location:
        terminate("GAP model location not entered in Configuration.")
    if not client.open_file(model_location, "GAP"):
        terminate()

    n_row = 0
    for _ in iter_down(find_cell(ws, "Well Name").offset(4, 0)):
        _run_gap_well_validation(client, config_ws, ws, n_row)
        n_row += 1


def run_gap_well_validation_selected_row(
    client: PetexClient, config_ws: Worksheet, ws: Worksheet, n_row: int
) -> None:
    """Port of `RunGAP_WellValidation_Selected` (row index passed explicitly)."""
    if n_row < 0 or n_row > 500:
        terminate("Error: Selected row out-with limits")

    model_location = find_cell(config_ws, "GAP Model").offset(0, 1).value
    if not model_location:
        terminate("GAP model location not entered in Configuration.")
    if not client.open_file(model_location, "GAP"):
        terminate()

    _run_gap_well_validation(client, config_ws, ws, n_row)


def _run_gap_well_validation(client: PetexClient, config_ws: Worksheet, ws: Worksheet, n_row: int) -> None:
    """Port of the private `RunGAP_WellValidation(nRow)`: isolates a single well
    (temporary wellhead separator, bypassed choke, disabled flowline) so its
    PROSPER-vs-GAP performance can be checked against a fixed WHP, independent
    of the rest of the network.
    """
    client.DoSet("GAP.DOUNITCONV", 0)

    for riser_ref in iter_down(find_cell(ws, "Riser Data").offset(5, 0)):
        riser_sep = gap_riser_name(config_ws, riser_ref.value)
        client.do_slow_cmd(f"GAP.MOD[{{PROD}}].SEP[{{{riser_sep}}}].MASK()")

    inp_header = find_cell(ws, "Well Data")
    inp_os_row = inp_header.offset(2, 0)
    inp_val_row = inp_header.offset(5, 0)
    out_header = find_cell(ws, "Well Outputs")
    out_os_row = out_header.offset(2, 0)
    out_val_row = out_header.offset(5, 0)

    _clear_outputs(out_os_row, out_val_row, n_row)

    wellname: Optional[str] = None
    n_col = 0
    while not inp_os_row.offset(0, n_col).is_empty:
        os_string = inp_os_row.offset(0, n_col).value
        header_text = str(inp_os_row.offset(-1, n_col).value or "").strip()
        header_lower = header_text.lower()
        if str(os_string).strip().lower() != "none":
            the_val = inp_val_row.offset(n_row, n_col).value
            if the_val is not None and the_val != "-" and str(the_val).strip().lower() != "none":
                if n_col <= 1 and header_lower == "well name":
                    if the_val != "":
                        wellname = gap_well_name(config_ws, the_val)
                        if wellname == "-":
                            terminate(f"Well {the_val} is not configured with an associated well in GAP")
                        if client.check_os_string("GAP.MOD[0].SEP[{Dummy_WH}].Label"):
                            client.do_slow_cmd("GAP.DELITEM(MOD[0].SEP[{Dummy_WH}])")
                        client.do_slow_cmd('GAP.NEWITEM("SEP","Dummy_WH","RIGHT",MOD[0].SEP[{R11}])')
                        wh_index = get_flowline_inlet_joint_index(client, wellname)
                        client.do_slow_cmd(
                            f"GAP.LINKITEMS(MOD[0].JOINT[{wh_index}],MOD[0].SEP[{{Dummy_WH}}])"
                        )
                        client.do_slow_cmd(f"GAP.MOD[0].INLGEN[{{{wellname[:3]}_chk}}].BYPASS()")
                        client.do_slow_cmd(f"GAP.MOD[0].PIPE[{{{wellname[:3]}_fl}}].DISABLE()")
                elif header_lower == "status":
                    if the_val == "Open":
                        client.do_slow_cmd(f"GAP.MOD[{{PROD}}].WELL[{{{wellname}}}].UNMASK()")
                    elif the_val == "Closed":
                        client.do_slow_cmd(f"GAP.MOD[{{PROD}}].WELL[{{{wellname}}}].MASK()")
                elif header_lower.startswith("choke"):
                    pass  # Choke dP not used for well validation - WHP is fixed.
                elif header_lower.endswith("icv"):
                    zone = header_text[:2]
                    layer_status = zone_status(ws, zone, n_row)
                    tag = f"GAP.MOD[0].INFLOW[{{{wellname[:3]}_{zone}}}].ISMASKED"
                    if layer_status == "Open" and client.DoGet(tag) == 1:
                        client.do_slow_cmd(
                            f"GAP.MOD[0].INFLOW[{{{wellname[:3]}_{zone}}}].UNMASK()"
                        )
                    elif layer_status == "Closed" and client.DoGet(tag) == 0:
                        client.do_slow_cmd(
                            f"GAP.MOD[0].INFLOW[{{{wellname[:3]}_{zone}}}].MASK()"
                        )
                else:
                    resolved = str(os_string).replace("wellName", wellname[:3])
                    if is_numeric(the_val):
                        the_val = ipt_unit_conv(
                            inp_os_row.offset(2, n_col).value,
                            inp_os_row.offset(1, n_col).value,
                            float(the_val),
                        )
                    elif str(the_val).strip().lower() == "error":
                        terminate(
                            f"Error with {header_text} for well {inp_val_row.offset(n_row, 0).value}. "
                            f"Enter a valid value"
                        )
                    client.do_set_no_err(resolved, the_val)
        n_col += 1

    client.do_slow_cmd("GAP.SOLVENETWORK(0)")

    calc_liq_rate: Any = None
    n_col = 0
    while not out_os_row.offset(0, n_col).is_empty:
        header_text = str(out_os_row.offset(-1, n_col).value or "").strip()
        header_lower = header_text.lower()
        if header_lower not in _SKIP_HEADERS and header_lower != "-":
            resolved = str(out_os_row.offset(0, n_col).value).replace("wellName", wellname[:3])
            if client.check_os_string(resolved):
                the_val = client.DoGet(resolved)
                if is_numeric(the_val):
                    the_val = ipt_unit_conv(
                        out_os_row.offset(1, n_col).value,
                        out_os_row.offset(2, n_col).value,
                        float(the_val),
                    )
                out_val_row.offset(n_row, n_col).value = "-" if is_numeric(the_val) and the_val > 999999 else the_val
            else:
                out_val_row.offset(n_row, n_col).value = "-"
        if header_lower == "liquid rate":
            calc_liq_rate = out_val_row.offset(n_row, n_col).value
        n_col += 1

    n_col = 0
    while not out_os_row.offset(-1, n_col).is_empty:
        header_text = str(out_os_row.offset(-1, n_col).value or "").strip().lower()
        if header_text == "liquid rate error":
            reported_liq_rate = find_cell(ws, "Liquid Rate").offset(4 + n_row, 0).value
            if (
                is_numeric(reported_liq_rate)
                and float(reported_liq_rate) > 0
                and is_numeric(calc_liq_rate)
                and float(calc_liq_rate) > 0
            ):
                out_val_row.offset(n_row, n_col).value = (
                    (float(calc_liq_rate) - float(reported_liq_rate)) * 100 / float(reported_liq_rate)
                )
            else:
                out_val_row.offset(n_row, n_col).value = "-"
        n_col += 1

    # ResetGAP: undo the temporary topology changes, regardless of how the well came out.
    client.do_slow_cmd(f"GAP.MOD[0].INLGEN[{{{wellname[:3]}_chk}}].UNBYPASS()")
    client.do_slow_cmd(f"GAP.MOD[0].PIPE[{{{wellname[:3]}_fl}}].ENABLE()")
    client.do_slow_cmd("GAP.DELITEM(MOD[0].SEP[{Dummy_WH}])")
    for riser_ref in iter_down(find_cell(ws, "Riser Data").offset(5, 0)):
        riser_sep = gap_riser_name(config_ws, riser_ref.value)
        client.do_slow_cmd(f"GAP.MOD[{{PROD}}].SEP[{{{riser_sep}}}].UNMASK()")


def set_well_data_gap(client: PetexClient, config_ws: Worksheet, ws: Worksheet, n_row: int) -> None:
    """Port of the private `SetWellData_GAP(nRow)` (network-wide validation - fixed
    choke dP is used instead of WHP, unlike the standalone `_run_gap_well_validation`).
    """
    inp_header = find_cell(ws, "Well Data")
    inp_os_row = inp_header.offset(2, 0)
    inp_val_row = inp_header.offset(5, 0)
    out_header = find_cell(ws, "GAP Outputs")
    out_os_row = out_header.offset(2, 0)
    out_val_row = out_header.offset(5, 0)

    _clear_outputs(out_os_row, out_val_row, n_row)

    wellname: Optional[str] = None
    n_col = 0
    while not inp_os_row.offset(0, n_col).is_empty:
        os_string = inp_os_row.offset(0, n_col).value
        header_text = str(inp_os_row.offset(-1, n_col).value or "").strip()
        header_lower = header_text.lower()
        if str(os_string).strip().lower() != "none":
            the_val = inp_val_row.offset(n_row, n_col).value
            if the_val is not None and the_val != "-" and str(the_val).strip().lower() != "none":
                if n_col <= 1 and header_lower == "well name":
                    if the_val != "":
                        wellname = gap_well_name(config_ws, the_val)
                        if wellname == "-":
                            terminate(f"Well {the_val} is not configured with an associated well in GAP")
                elif header_lower == "status":
                    if the_val == "Open":
                        client.do_slow_cmd(f"GAP.MOD[0].Well[{{{wellname}}}].UNMASK()")
                        client.do_slow_cmd(f"GAP.MOD[0].INLGEN[{{{wellname[:3]}_chk}}].UNBYPASS()")
                    elif the_val == "Closed":
                        client.do_slow_cmd(f"GAP.MOD[0].Well[{{{wellname}}}].MASK()")
                elif header_lower.endswith("icv"):
                    zone = header_text[:2]
                    layer_status = zone_status(ws, zone, n_row)
                    tag = f"GAP.MOD[0].INFLOW[{{{wellname[:3]}_{zone}}}].ISMASKED"
                    if layer_status == "Open" and client.DoGet(tag) == 1:
                        client.do_slow_cmd(f"GAP.MOD[0].INFLOW[{{{wellname[:3]}_{zone}}}].UNMASK()")
                    elif layer_status == "Closed" and client.DoGet(tag) == 0:
                        client.do_slow_cmd(f"GAP.MOD[0].INFLOW[{{{wellname[:3]}_{zone}}}].MASK()")
                elif header_lower.startswith("whp"):
                    pass  # WHP isn't used network-wide - choke dP drives the model instead.
                else:
                    resolved = str(os_string).replace("wellName", wellname[:3])
                    if is_numeric(the_val):
                        the_val = ipt_unit_conv(
                            inp_os_row.offset(2, n_col).value,
                            inp_os_row.offset(1, n_col).value,
                            float(the_val),
                        )
                    elif str(the_val).strip().lower() == "error":
                        terminate(
                            f"Error with {header_text} for well {inp_val_row.offset(n_row, 0).value}. "
                            f"Enter a valid value"
                        )
                    client.do_set_no_err(resolved, the_val)
        n_col += 1


def get_well_data_gap(client: PetexClient, config_ws: Worksheet, ws: Worksheet, n_row: int) -> None:
    """Port of the private `GetWellData_GAP(nRow)`."""
    inp_val_row = find_cell(ws, "Well Data").offset(5, 0)
    out_header = find_cell(ws, "GAP Outputs")
    out_os_row = out_header.offset(2, 0)
    out_val_row = out_header.offset(5, 0)

    _clear_outputs(out_os_row, out_val_row, n_row)

    wellname = gap_well_name(config_ws, inp_val_row.offset(n_row, 0).value)

    calc_liq_rate: Any = None
    n_col = 0
    while not out_os_row.offset(0, n_col).is_empty:
        header_text = str(out_os_row.offset(-1, n_col).value or "").strip()
        header_lower = header_text.lower()
        if header_lower not in _SKIP_HEADERS and header_lower != "-":
            resolved = str(out_os_row.offset(0, n_col).value).replace("wellName", wellname[:3])
            if client.check_os_string(resolved):
                the_val = client.DoGet(resolved)
                if is_numeric(the_val):
                    the_val = ipt_unit_conv(
                        out_os_row.offset(1, n_col).value,
                        out_os_row.offset(2, n_col).value,
                        float(the_val),
                    )
                out_val_row.offset(n_row, n_col).value = "-" if is_numeric(the_val) and the_val > 999999 else the_val
            else:
                out_val_row.offset(n_row, n_col).value = "-"
        if header_lower == "liquid rate":
            calc_liq_rate = out_val_row.offset(n_row, n_col).value
        n_col += 1

    n_col = 0
    while not out_os_row.offset(-1, n_col).is_empty:
        header_text = str(out_os_row.offset(-1, n_col).value or "").strip().lower()
        if header_text == "liquid rate error":
            reported_liq_rate = find_cell(ws, "Liquid Rate").offset(4 + n_row, 0).value
            if (
                is_numeric(reported_liq_rate)
                and float(reported_liq_rate) > 0
                and is_numeric(calc_liq_rate)
                and float(calc_liq_rate) > 0
            ):
                out_val_row.offset(n_row, n_col).value = (
                    (float(calc_liq_rate) - float(reported_liq_rate)) * 100 / float(reported_liq_rate)
                )
            else:
                out_val_row.offset(n_row, n_col).value = "-"
        n_col += 1
