"""Field roll-up: all exported wells side by side, normalised to the PPRS fiscal figures."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import demo, store
from core.excel_export import month_workbook
from core.pi_client import month_index
from core.rollup import PHASES, all_wells_matrices, normalise
from views import ui

s = ui.settings()
W = ui.wells()
y, m, mk = ui.period()
mode = s["mode"]
idx = month_index(y, m)

exports = store.load_exports(mode, mk)
pprs_all = store.load_pprs(mode)
pprs = pprs_all.reindex(idx) if not pprs_all.empty else pd.DataFrame(index=idx, columns=pprs_all.columns, dtype=float)
pprs_days = int(pprs["oil"].notna().sum()) if "oil" in pprs else 0
mats = all_wells_matrices(exports, list(W["well"]), idx)
norm = normalise(mats, pprs)

n_zones = mats["oil"].shape[1] - 1
alloc_oil = mats["oil"]["Total"].mean()
fiscal_oil = pprs["oil"].mean() if pprs_days else float("nan")
ui.header(
    "Field roll-up",
    f"{ui.period_label()}: gradient match for all wells, normalised to PPRS",
    [("Wells exported", f"{len(exports)} / {len(W)}"), ("Zones", str(n_zones)),
     ("Allocated oil, avg", ui.fmt(alloc_oil, 0, " stb/d")), ("PPRS oil, avg", ui.fmt(fiscal_oil, 0, " stb/d"))],
)

if not exports:
    st.info(f"No wells have been exported for {ui.period_label()} yet. Allocate a well and choose "
            "'Save to field roll-up', or use 'Run several wells' on the overview.")
    st.stop()
if not pprs_days:
    st.warning(f"No PPRS fiscal data for {ui.period_label()}. Add it under the PPRS tab below so the "
               "normalised rates can be calculated.")

phase = st.segmented_control("Phase", list(PHASES), default="oil",
                             format_func=lambda p: PHASES[p][0]) or "oil"
label, unit = PHASES[phase]
colour = ui.PHASE[phase]
fmt_v = ".3f" if phase == "gas" else ",.0f"

c1, c2 = st.columns([3, 2], gap="large")
with c1:
    st.markdown(f"**Daily {label.lower()}: sum of allocated zones against PPRS**")
    fig = go.Figure()
    ui.line(fig, idx, mats[phase]["Total"], "Allocated (sum of zones)", colour, hover_fmt=fmt_v, unit=unit)
    if pprs_days:
        ui.line(fig, idx, norm[phase]["PPRS"], "PPRS fiscal", ui.INK, dash="dash", hover_fmt=fmt_v, unit=unit)
    fig = ui.base_layout(fig, 340, unit)
    if phase == "gas":
        fig.update_yaxes(tickformat=",.1f")
    st.plotly_chart(fig, use_container_width=True)
    if pprs_days:
        ratio = (mats[phase]["Total"] / norm[phase]["PPRS"]).mean()
        st.caption(f"Allocated ÷ PPRS over the month: {ratio:.3f}. Normalisation scales every zone by "
                   f"the day's PPRS ÷ allocated total.")
with c2:
    src = norm[phase] if pprs_days else mats[phase]
    zone_avg = src.drop(columns=[c for c in ("Total", "PPRS") if c in src]).mean()
    by_well = pd.Series({w: zone_avg[[c for c in zone_avg.index if c == w or c.startswith(w + " ")]].sum(min_count=1)
                         for w in exports}).dropna().sort_values()
    st.markdown(f"**Month average by well, {'normalised' if pprs_days else 'allocated'}**")
    bar = go.Figure(go.Bar(
        x=by_well.values, y=by_well.index, orientation="h", marker=dict(color=colour, cornerradius=4),
        hovertemplate=f"%{{y}}<br>%{{x:{fmt_v}}} {unit}<extra></extra>"))
    bar = ui.base_layout(bar, max(340, 19 * len(by_well) + 70), legend=False)
    bar.update_layout(hovermode="closest", bargap=0.3,
                      xaxis=dict(title=unit, tickformat=",.1f" if phase == "gas" else ",.0f", gridcolor="#EEF1F3"),
                      yaxis=dict(title=None, tickformat=None, tickfont=dict(size=11)))
    st.plotly_chart(bar, use_container_width=True)
    st.caption("Zone-level figures are in the tables below.")

t1, t2, t3, t4 = st.tabs(["Allocated", "Normalised", "PPRS", "Exported wells"])
fmt_cols = {c: st.column_config.NumberColumn(format="%.3f" if phase == "gas" else "%.0f") for c in mats[phase].columns}


def show(df):
    v = df.copy()
    v.index = v.index.date
    st.dataframe(v, use_container_width=True, height=440, column_config=fmt_cols)


with t1:
    st.caption("Zone rates as exported from each well (the 'Gradient Match All wells' sheet).")
    show(mats[phase])
with t2:
    st.caption("Each zone's share of the day's allocated total, multiplied by the PPRS figure for that day.")
    show(norm[phase])
with t3:
    st.caption("Daily fiscal totals. Oil uses 'Oil Production', gas uses 'Prod Gas', water uses 'Prod Water'.")
    a, b = st.columns([2, 1])
    with a:
        up = st.file_uploader("Upload PPRS (the workbook's PPRS sheet, or CSV/XLSX with the same headers)",
                              type=["xlsx", "xlsm", "csv"])
        if up is not None and st.button("Add uploaded PPRS"):
            try:
                new = store.parse_pprs_upload(up)
                store.merge_pprs(mode, new)
                st.toast(f"Added {len(new)} PPRS day(s)")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not read the PPRS file: {exc}")
    with b:
        if mode == "demo":
            st.write("")
            if st.button("Fill demo PPRS for this month", use_container_width=True):
                store.merge_pprs(mode, demo.demo_pprs(y, m, list(W["well"])))
                st.rerun()
    labels = {k: v for k, v in store.PPRS_COLUMNS.items()}
    ed = pprs.copy()
    ed.index = ed.index.date
    edited = st.data_editor(ed, use_container_width=True, height=400, key=f"pprs_{mode}_{mk}",
                            column_config={k: st.column_config.NumberColumn(v, format="%.2f") for k, v in labels.items()})
    if not edited.astype(float).equals(ed.astype(float)):
        new = edited.copy()
        new.index = pd.DatetimeIndex(pd.to_datetime(new.index), name="date")
        store.merge_pprs(mode, new.dropna(how="all"))
        st.toast("PPRS saved")
with t4:
    rows = [{"Well": w, "Template": meta.get("template"), "Zones": ", ".join(z["name"] for z in meta.get("zones", [])),
             "Rates": meta.get("source_label", ""), "Saved": meta.get("saved_at", "").replace("T", " ")}
            for w, (_, meta) in exports.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    r1, r2 = st.columns([2, 1])
    drop = r1.selectbox("Remove a well from this month's roll-up", [""] + list(exports))
    if drop and r2.button("Remove", use_container_width=True):
        store.delete_export(mode, mk, drop)
        st.rerun()

st.download_button(
    f"Download {ui.period_label()} workbook", month_workbook(exports, mats, norm, pprs.dropna(how="all")),
    file_name=f"Allocation_{mk}.xlsx", type="primary",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
st.caption("Contains 'Gradient Match All wells', 'Gradient Normalization', 'PPRS' and one zonal sheet per exported well.")
