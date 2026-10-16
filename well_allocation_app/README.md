# Well Rate Allocation

A Streamlit app that does what `Allocation.xlsm` does: pulls daily MPFM rates and pressures from PI, runs PROSPER nodal analysis and a gradient match through OpenServer, splits each well's rates across its zones, and normalises the whole field to the PPRS fiscal figures.

```
streamlit run app.py        # or double-click run_app.bat on Windows
```

## Pages

| Page | What it does | Workbook equivalent |
|---|---|---|
| **Well allocation** | One well at a time, in order: open the well (loads its PROSPER model), pull its data from PI (or upload a file), run the gradient match, review the charts and daily table (with manual overrides), export. Multi-zone wells (Z2/Z3) then go to a zonal split step with editable factors; single-zone wells go straight to the roll-up | `Allocation Worksheet`, macros `PullPIAdvCalcDatBelowTags`, `Calculate_BHP_Nodal_analysis`, `Allocate`, `ExportToTemplateSheet`, templates `Z1`/`Z2`/`Z3` |
| **Field roll-up** | All exported zones side by side, PPRS upload/edit, normalisation, reconciliation chart, one-click month workbook | `Gradient Match All wells` + `Import_Gradient_Match*` macros, `Gradient Normalization`, `PPRS` |
| **Month status** | Read-only checklist of every well for the month: pulled, matched, exported, zonal split | — |
| **Configuration** | Demo/live mode, PI server, unit conversions, match tolerance and method, well table (editable, or imported from the `.xlsm`), single gradient test | `Configuration Sheet`, cells C16:C18, R5 |

## The calculations

- **PI pull**: daily time-weighted averages (`summaries(..., "1d", AVERAGE, TIME_WEIGHTED)`) from the 1st of the month to the 1st of the next, times the conversion factor: liquid ×151 (m³/h → stb/d), gas ×0.000848 (Sm³/h → MMscf/d), pressure ×14.5 (bar → psi).
- **Derived**: Liquid = (Oil + Water) × liquid factor; WCT % = Water / (Oil + Water) × 100 × WCT factor; GOR = Gas × 10⁶ / Oil × GOR factor.
- **Nodal analysis**: per day, set `PROSPER.ANL.GRD.Pres/WC/Rate/GOR`, run `PROSPER.ANL.GRD.CALC()`, read the well's result string; deviation = |gauge BHP − PROSPER BHP| / gauge BHP.
- **Gradient match** (default, identical to the `Allocate` macro): scale rate by target/calculated until within tolerance (5 %, max 200 iterations); if not, scale GOR; then WCT (clamped 0–100). An optional binary chop on rate (ported from `OsMatchBinaryChop`) is available.
- **Export**: choose the rates per well: MPFM-derived (what the macro copies, columns L/M/N), gradient-matched, manual, or auto (MPFM where nodal deviation is within a limit, matched elsewhere).
- **Zonal split**: Oil = L × (100 − WCT)/100, Gas = Oil × GOR/10⁶, Water = L × WCT/100, each zone = phase × split factor; zone GOR and WCT (fraction) as on the templates.
- **Normalisation**: zone ÷ sum of all zones that day × PPRS (Oil Production, Prod Gas, Prod Water).

Tests in `tests/` check the derived parameters against row 7 of the workbook and the matcher against a line-by-line transcription of the VBA.

## Live mode (PI + PROSPER)

Run on a Windows machine that has the PI AF SDK and Petex IPM installed:

```
pip install -r requirements.txt
pip install PIconnect pywin32
```

PROSPER is reached through your `openserver` package (`from openserver import OpenServer`) if it is installed, otherwise directly through the `PX32.OpenServer.1` COM object the VBA uses.

**Before running, save the Configuration Sheet as CSV to `config/wells.csv`** (header rows included, starting at the *Well* column, exactly as Excel's *Save As → CSV* writes it). The app only reads this file and never writes to it; to change a well, edit the sheet and save the CSV again. `config/wells.csv` is git-ignored, so tags and model paths never go to GitHub. There is no example well list.

Demo mode (**Configuration → Mode → Demo**) needs nothing beyond `requirements.txt`: it generates rates and uses a simple stand-in well model so the whole flow can be tried anywhere. Demo and live results are kept in separate folders under `data/`.

## Things that differ from the workbook on purpose

While porting, a few spreadsheet issues came up. The app does the evident intent instead:

1. The `Wells_List` name covers `C6:C29`, so J75-P, J76-P, J77-P and J50-P return "Not Found" for their tags and zones. The app uses every row.
2. `Gradient Normalization` divides each zone by column `$BO` of `Gradient Match All wells` (the J76-P MH5/4 column), not the Total column. The app divides by the day's total of all zones, so normalised zones add up to PPRS.
3. Normalisation lines PPRS up by row position; the app matches by date.
4. Template `Z2` takes its lower-zone name from the MZ column (AD, blank for Z2 wells) but its split from LZ (AB). The app uses the LZ name, so those lower zones appear in the roll-up.

## Layout

```
app.py                 navigation and month picker
views/                 the four pages + shared styling
core/config.py         well table and settings (config/wells.csv, config/settings.json)
core/pi_client.py      PIconnect pull
core/prosper.py        OpenServer session and the demo model
core/allocation.py     derive, nodal, gradient match, export, zonal split
core/rollup.py         all-wells matrices and normalisation
core/excel_export.py   per-well sheet and month workbook
core/store.py          data/<mode>/runs, exports, pprs.csv
tools/import_workbook.py   python tools/import_workbook.py Allocation.xlsm
```

## ICV adjustments, dated factors, audit trail and resets

- **ICV positions** (multi-zone wells): *Pull from PI* also pulls each zone's ICV tag (daily average, minimum and maximum, read as-is). A day is flagged when a valve moved within the day, or its average changed from the day before by more than the threshold in *Configuration → Settings → ICV adjustments* (default 0.5). Flags show in Pull data (table, metric and an ICV position chart with adjustment days shaded) and again at the zonal split. ICVs do not change the allocation yet.
- **Dated factor changes**: *Well allocation → Pull data → Factors*. A liquid, WCT or GOR factor change applies from its date onwards; earlier days keep the Configuration Sheet value. The factor used each day is shown in the pulled-data table. Saved runs that no longer match the current factors are flagged with a *Re-apply factors* button (PROSPER results are cleared). Stored in `config/factor_changes.csv`.
- **Configuration Sheet editing**: *Configuration → Configuration Sheet*. Edit, review the changed cells, give a reason and save. The previous sheet is copied to `config/history/` first, and an empty sheet is never written.
- **Audit trail**: *Configuration → Audit trail* lists every factor change, sheet edit and reset with who, when and why (`config/audit_log.csv`, downloadable).
- **Reset runs**: *Configuration → Reset runs* clears the selected month or all months (optionally with exports and zonal splits). The Configuration Sheet, factor changes, PPRS data and the audit trail are kept.

`config/factor_changes.csv`, `config/audit_log.csv` and `config/history/` are git-ignored, like `config/wells.csv`.

## Month-end: next month's Configuration Sheet

*Configuration → Audit trail → Create the Configuration Sheet for <next month>* takes the sheet in force for the selected month, writes in the latest dated factor change for each well and factor up to the end of that month, and saves it as `config/sheets/wells_YYYY-MM.csv`. Each month uses the newest sheet dated on or before it (falling back to `config/wells.csv`), and only dated changes from that sheet's start onwards apply on top. Earlier months keep their own sheet, so re-running them gives the same figures. The carried changes are logged in the audit trail, and the new sheet can be downloaded.
