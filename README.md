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
  add `pywin32` (COM) and `pyodbc` (OFM/Access) on the target Windows
  machine; `pip install -e ".[pi]"` if using `PIWebAPIClient`.

The pure-logic pieces (unit fallback, the IPR solver, the Excel `FindCell`
helper, and the higher-level orchestration functions with a fake OpenServer
client) import and test fine on Linux/macOS too - see `tests/`.

## Layout

| Module | Ports |
|---|---|
| `petex_client.py` | `Connect`/`Disconnect`/`DoSet`/`DoGet`/`DoCmd` (via `openserver.OpenServer`), plus `DoSlowCmd`, `CheckOsString`, `DoSetNoErr`, `DoGAPFuncFast`, `fOSOpenFile` |
| `units.py` | `iPT_UnitConv` |
| `ipr.py` | `getResPres` |
| `excel_io.py` | `FindCell` + the `Range.Offset(...).Value` idiom |
| `gap_naming.py` | `GAPWellName`, `GAPRiserName`, `PROSPERModelinGAP`, `RiserforWell`, `RowinConfig`, `TagColinConfig`, `TagColinConfig_nCol`, `ZoneStatus` |
| `vlp.py` | `VLPCalc_All`, `VLPCalc_SelectedWell`, `VLPCalc` |
| `ipr_matching.py` | `MatchIPR`, `MatchIPR_SelectedWell`, `EstimateResPress` |
| `gap_validation.py` | `RunGAPValidation`, `SetRiserData_GAP`, `SetWellRouting`, `RunGAP_WellValidation_All/_Selected`, `SetWellData_GAP`, `GetWellData_GAP`, `getFlowlineInletJointIndex` |
| `totals.py` | `DeleteMeasuredTotals`, `DeleteAllocatedTotals`, `DeleteTotalRates`, `GetTotalRates` |
| `data_import.py` | `GetData_All`, `ClearAllData`, `GetRiserData`, `GetWellData`, `GetMeasuredTotals`, `GetAllocatedTotals`, `VariableValue`, `GetNumberofZones`, `GetWellRateWCGORandStatus`, `GetICVdPandZoneStatus`, `GetChokedP` |
| `ofm.py` | `OFMValue`, `GetdbFileName` |
| `pi_client.py` | Stands in for the (not-pasted) `PIValue` |
| `workflows.py` | A `Workflow` convenience wrapper over the above, mirroring the ribbon-button Subs |

`ShowSummary`/`ShowDetails` (hide/show Excel columns) aren't ported - pure
Excel-UI convenience with no headless-script equivalent.

## Quick start

```python
import openpyxl
from petroleum_openserver import PetexClient, Workflow

wb = openpyxl.load_workbook("Jubilee_Validation.xlsx")

with PetexClient() as client:
    flow = Workflow.from_workbook(client, wb, validation_sheet="Validation")
    flow.get_data()             # pull Configuration/OFM data onto the sheet
    flow.run_gap_validation()   # network-wide GAP solve
    flow.vlp_calc_all()         # PROSPER VLP calc for every well
    flow.match_ipr()            # re-estimate zonal reservoir pressures

wb.save("Jubilee_Validation.xlsx")
```

Or call the module-level functions directly if you don't want the
`Workflow` wrapper - e.g. `from petroleum_openserver.vlp import vlp_calc_all`.

## Assumptions made where the original VBA wasn't fully available

Three pieces the pasted VBA *referenced* but didn't *define* had to be
reconstructed rather than transcribed. If you have the original source for
any of these, prefer porting it directly over what's here:

1. **`getResPres` (`ipr.py`)** - reconstructed as the standard combined
   PI/Vogel IPR (Vogel 1968), with the oil fraction (from water cut)
   following Vogel below the bubble point and the water fraction staying
   linear, solved for reservoir pressure by bisection. Verify this matches
   your reservoir engineering standard before trusting the numbers.

2. **`iPT_UnitConv` (`units.py`)** - the real conversion is Petex's
   `iPT_Utilities.iPT_UnitConv` COM component; `PetexUnitConverter` calls it
   via `pywin32`, but the exact method name on that COM object wasn't in the
   pasted VBA (only a wrapper that called back into itself). It tries a
   handful of likely method names on first use; on a machine with IPM
   installed, confirm the right one with:

   ```python
   import win32com.client
   obj = win32com.client.Dispatch("iPT_Utilities.iPT_UnitConv")
   print([m for m in dir(obj) if not m.startswith("_")])
   ```

   `SimpleUnitConverter` (a small pure-Python fallback for common oilfield
   units) is used by default so the rest of the package is testable without
   Windows/IPM; call `units.set_default_converter(PetexUnitConverter())` to
   switch to the real thing.

3. **`PIValue` (`pi_client.py`)** - not part of the pasted VBA at all (only
   the call site `PIValue(VariableTag, RequiredUnit)` was). `pi_client.py`
   provides a `PIClient` protocol and a PI Web API-based implementation
   assuming tags are written as `PI:<TagPath>[:<Unit>]`; confirm that
   convention against your actual Configuration sheet, or implement
   `PIClient` against PI SDK/AF SDK if that's what your site uses instead.

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
