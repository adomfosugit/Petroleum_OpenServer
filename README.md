# petroleum-openserver

Python port of the Jubilee GAP/PROSPER VLP-calculation, IPR-matching and
GAP-validation VBA macros, built on Petroleum Experts' [`openserver`](https://pypi.org/project/openserver/)
OpenServer client (the same package/pattern used in the sample script this
was ported from).

The original macros lived in one big Excel VBA module and drove PROSPER/GAP
through OpenServer while reading/writing a specific worksheet layout
(`Configuration` + a "Validation"-style sheet with `FindCell`/`.Offset(...)`
lookups everywhere). This package keeps the same OpenServer call sequences
and the same worksheet layout convention (via `openpyxl` instead of Excel's
own object model), so an existing workbook can largely keep its layout.

## Requirements

- **Windows**, with Petroleum Experts IPM (PROSPER/GAP) installed and
  licensed - OpenServer, and the `iPT_Utilities` unit-conversion COM
  component, are Windows-only COM servers. None of this can run PROSPER/GAP
  calculations on Linux/macOS.
- Python 3.9+
- `pip install -e .` for the core package; `pip install -e ".[windows]"` to
  add `pywin32` (COM - also used by `pi_data.py` to talk to PI SDK) and
  `pyodbc` (OFM/Access) on the target Windows machine.
- If resolving `PI:...` tags, PI SDK installed and a Python whose bitness
  (32/64-bit) matches that install (see `pi_data.py`).

The pure-logic pieces (unit fallback, the IPR solver, the Excel `FindCell`
helper, and the higher-level orchestration functions with a fake OpenServer
client) import and test fine on Linux/macOS too - see `tests/`.

## Layout

| Module | Ports |
|---|---|
| `petex_client.py` | `Connect`/`Disconnect`/`DoSet`/`DoGet`/`DoCmd` (via `openserver.OpenServer`), plus `DoSlowCmd`, `CheckOsString`, `DoSetNoErr`, `DoGAPFuncFast`, `fOSOpenFile` |
| `units.py` | `iPT_UnitConv` |
| `ipr.py` | The composite IPR module (`GetIprQ`, `GetIprP`, `GetIprAofp`, `IprBinaryChop`, `getResPres`) |
| `excel_io.py` | `FindCell` + the `Range.Offset(...).Value` idiom |
| `gap_naming.py` | `GAPWellName`, `GAPRiserName`, `PROSPERModelinGAP`, `RiserforWell`, `RowinConfig`, `TagColinConfig`, `TagColinConfig_nCol`, `ZoneStatus` |
| `vlp.py` | `VLPCalc_All`, `VLPCalc_SelectedWell`, `VLPCalc` |
| `ipr_matching.py` | `MatchIPR`, `MatchIPR_SelectedWell`, `EstimateResPress` |
| `gap_validation.py` | `RunGAPValidation`, `SetRiserData_GAP`, `SetWellRouting`, `RunGAP_WellValidation_All/_Selected`, `SetWellData_GAP`, `GetWellData_GAP`, `getFlowlineInletJointIndex` |
| `totals.py` | `DeleteMeasuredTotals`, `DeleteAllocatedTotals`, `DeleteTotalRates`, `GetTotalRates` |
| `data_import.py` | `GetData_All`, `ClearAllData`, `GetRiserData`, `GetWellData`, `GetMeasuredTotals`, `GetAllocatedTotals`, `VariableValue`, `GetNumberofZones`, `GetWellRateWCGORandStatus`, `GetICVdPandZoneStatus`, `GetChokedP` |
| `ofm.py` | `OFMValue`, `GetdbFileName` |
| `pi_data.py` | `PIValue`, `GetPiTagAtt`, `GetPiTagVal`, `GetPiTagArr` (PI SDK via `pywin32`) |
| `workflows.py` | A `Workflow` convenience wrapper over the above, mirroring the ribbon-button Subs |

`ShowSummary`/`ShowDetails` (hide/show Excel columns) aren't ported - pure
Excel-UI convenience with no headless-script equivalent.

## Quick start

```python
import openpyxl
from petroleum_openserver import PetexClient, Workflow

wb = openpyxl.load_workbook("Jubilee_Validation.xlsx")

with PetexClient() as client:
    flow = Workflow.from_workbook(client, wb, validation_sheet="Validation", pi_server="MyPIServer")
    flow.get_data()             # pull Configuration/OFM/PI data onto the sheet
    flow.run_gap_validation()   # network-wide GAP solve
    flow.vlp_calc_all()         # PROSPER VLP calc for every well
    flow.match_ipr()            # re-estimate zonal reservoir pressures

wb.save("Jubilee_Validation.xlsx")
```

Or call the module-level functions directly if you don't want the
`Workflow` wrapper - e.g. `from petroleum_openserver.vlp import vlp_calc_all`.

## Assumptions made where the original VBA wasn't fully available

`getResPres`/the IPR module (`ipr.py`) and `PIValue` (`pi_data.py`) are now
direct ports of their real VBA sources. One piece is still a best guess:

- **`iPT_UnitConv` (`units.py`)** - the real conversion is Petex's
  `iPT_Utilities.iPT_UnitConv` COM component; `PetexUnitConverter` calls it
  via `pywin32`, but the exact method name on that COM object wasn't
  available to confirm against (only a VBA wrapper that called back into
  itself was). It tries a handful of likely method names on first use; on a
  machine with IPM installed, confirm the right one with:

  ```python
  import win32com.client
  obj = win32com.client.Dispatch("iPT_Utilities.iPT_UnitConv")
  print([m for m in dir(obj) if not m.startswith("_")])
  ```

  `SimpleUnitConverter` (a small pure-Python fallback for common oilfield
  units) is used by default so the rest of the package is testable without
  Windows/IPM; call `units.set_default_converter(PetexUnitConverter())` to
  switch to the real thing.

`pi_data.pi_value` expects tags written as `PI:Tag:Unit` and a PI server
name (`Workflow(pi_server=...)` / `get_data_all(..., pi_server=...)`) -
resolving one requires PI SDK installed and a matching-bitness Python, since
it goes through `win32com.client.gencache.EnsureDispatch("PISDK.PISDK")`.

A few smaller behavioural notes:

- `VLPCalc_SelectedWell` / `MatchIPR_SelectedWell` / `RunGAP_WellValidation_Selected`
  derived their row from the currently selected Excel cell (`ActiveCell.Row`).
  There's no such concept in a headless script, so their ports
  (`vlp_calc_selected_row`, `match_ipr_selected_row`, `run_gap_well_validation_selected_row`)
  take the (0-based) data-row index as a plain argument instead.
- `TerminateProgram` showed a MsgBox and called `End` (killing the whole
  Excel macro immediately, with no cleanup). Its port, `terminate()`, raises
  `ProgramTerminated` instead - callers decide what to do with it.
- Excel sheet protection (`ActiveSheet.Protect`/`Unprotect`) isn't ported;
  it's meaningless outside interactive Excel.

## Tests

```
pip install -e ".[dev]"
pytest
```

The suite covers the OpenServer-independent logic (unit fallback, the IPR
solver, `FindCell`/`Ref`, the naming/lookup helpers) and exercises the
higher-level orchestration (`vlp_calc`, `set_well_routing`,
`get_flowline_inlet_joint_index`) against a `FakeClient` stand-in for
`PetexClient`, so none of it needs Windows, PROSPER/GAP, or COM to run.
