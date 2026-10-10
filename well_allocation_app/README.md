# Well Rate Allocation

A Streamlit app that does what `Allocation.xlsm` does: pulls daily MPFM rates and pressures from PI, runs PROSPER nodal analysis and a gradient match through OpenServer, splits each well's rates across its zones, and normalises the whole field to the PPRS fiscal figures.

```
streamlit run app.py        # or double-click run_app.bat on Windows
```

## Pages

| Page | What it does | Workbook equivalent |
|---|---|---|
| **Month overview** | Status of every well for the month; batch run of pull → nodal + match → export for selected wells | — |
| **Allocate a well** | Pull PI data (or upload a file), derive liquid/WCT/GOR, run nodal analysis and gradient match, review charts, enter manual matches, export the zonal sheet | `Allocation Worksheet`, macros `PullPIAdvCalcDatBelowTags`, `Calculate_BHP_Nodal_analysis`, `Allocate`, `ExportToTemplateSheet`, templates `Z1`/`Z2`/`Z3` |
| **Field roll-up** | All exported zones side by side, PPRS upload/edit, normalisation, reconciliation chart, one-click month workbook | `Gradient Match All wells` + `Import_Gradient_Match*` macros, `Gradient Normalization`, `PPRS` |
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

PROSPER is reached through your `openserver` package (`from openserver import OpenServer`) if it is installed, otherwise directly through the `PX32.OpenServer.1` COM object the VBA uses. Then load your real well list: **Configuration → Wells → Import from an Allocation workbook** (or `python tools/import_workbook.py Allocation.xlsm`). It is saved to `config/wells.csv`, which is git-ignored; until then the app uses `config/wells.example.csv`, which has the field's wells, zones and splits but placeholder tag names and model paths. Finally switch **Configuration → Mode** to *Live*.

Demo mode needs nothing beyond `requirements.txt`: it generates rates and uses a simple stand-in well model so the whole flow can be tried anywhere. Demo and live results are kept in separate folders under `data/`.

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
core/config.py         well table and settings (config/wells.csv or wells.example.csv, config/settings.json)
core/pi_client.py      PIconnect pull
core/prosper.py        OpenServer session and the demo model
core/allocation.py     derive, nodal, gradient match, export, zonal split
core/rollup.py         all-wells matrices and normalisation
core/excel_export.py   per-well sheet and month workbook
core/store.py          data/<mode>/runs, exports, pprs.csv
tools/import_workbook.py   python tools/import_workbook.py Allocation.xlsm
```
