"""Allocate one well for the selected month: pull, nodal analysis, gradient match, export."""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import allocation as al
from core import store
from core import workflow as wf
from core.config import zones_for
from core.excel_export import well_workbook
from core.pi_client import MEASUREMENTS, read_uploaded
from views import ui

s = ui.settings()
W = ui.wells()
y, m, mk = ui.period()
mode = s["mode"]

if W.empty:
    st.info("No wells are configured yet. Add them on the Configuration page, or import your Allocation workbook there.")
    st.stop()

top = st.columns([2, 5])
well = top[0].selectbox("Well", list(W["well"]), key="well_pick")
row = W[W["well"] == well].iloc[0]
zones = zones_for(row)
run = store.load_run(mode, mk, well)
exports = store.load_exports(mode, mk)
exported = well in exports

has_data = run is not None and run["liquid"].notna().any()
has_nodal = has_data and run["bhp_nodal"].notna().any()
has_match = has_data and run["match_bhp"].notna().any()

prosper_name = Path(row["prosper_file"]).name if row["prosper_file"] else "not set"
ui.header(
    well,
    f"{ui.period_label()} allocation",
    [("Template", row["template"] or "Z1"),
     ("Zones", ", ".join(z.name for z in zones) or "–"),
     ("Days with rates", str(int(run["liquid"].notna().sum())) if has_data else "0"),
     ("PROSPER model", prosper_name)],
)
ui.rail([
    ("Pull data", "PI daily averages", has_data),
    ("Nodal analysis", "BHP from MPFM rates", has_nodal),
    ("Gradient match", "rates that honour the gauge", has_match),
    ("Export", "zonal sheet for roll-up", exported),
])


def progress_runner(label):
    bar = st.progress(0.0, text=label)

    def cb(frac, msg):
        bar.progress(min(max(frac, 0.0), 1.0), text=msg)
    return bar, cb


def save(df):
    store.save_run(mode, mk, well, df)


# ---------------------------------------------------------------- 1. pull
with st.container(border=True):
    st.subheader("Pull daily data")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown(
            f'<span class="wa-note">Time-weighted daily averages from {ui.period_label()}, '
            f'converted with liquid ×{s["liquid_conv"]:g}, gas ×{s["gas_conv"]:g}, pressure ×{s["pressure_conv"]:g}. '
            f'Liquid, WCT and GOR are then derived with this well\'s factors '
            f'(liquid {row["liquid_factor"]:g}, WCT {row["wct_factor"]:g}, GOR {row["gor_factor"]:g}).</span>',
            unsafe_allow_html=True)
        tags = {k: row[col] or "not set" for k, (col, _) in MEASUREMENTS.items()}
        st.caption("Tags: " + ", ".join(f"{k.upper()} {v}" for k, v in tags.items()))
    with c2:
        label = "Pull from PI" if mode == "live" else "Generate demo data"
        b1, b2 = st.columns(2)
        pull_clicked = b1.button(label, type="primary", use_container_width=True)
        with b2.popover("Upload a file", use_container_width=True):
            st.caption("CSV or Excel with columns date, oil, gas, water, thp, bhp in field units "
                       "(stb/d, MMscf/d, psia).")
            up = st.file_uploader("Daily data", type=["csv", "xlsx"], label_visibility="collapsed")
            if up is not None and st.button("Use this file", use_container_width=True):
                try:
                    raw = read_uploaded(up, y, m)
                    new = al.empty_run(raw.index)
                    for c in raw.columns:
                        new[c] = raw[c]
                    save(al.derive_parameters(new, row))
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not read the file: {exc}")
    if pull_clicked:
        bar, cb = progress_runner("Connecting to PI")
        try:
            new, warns = wf.pull(row, y, m, s, cb)
            if run is not None:  # keep manual entries on a re-pull
                for c in ["manual_liquid", "manual_wct", "manual_gor"]:
                    new[c] = run[c].reindex(new.index)
            save(new)
            bar.empty()
            for k, v in warns.items():
                st.warning(f"{k.upper()}: {v}")
            st.toast("Data pulled")
            st.rerun()
        except Exception as exc:
            bar.empty()
            st.error(f"PI pull failed: {exc}")

if not has_data:
    st.markdown('<p class="wa-note">Pull or upload this month\'s data to start.</p>', unsafe_allow_html=True)
    st.stop()

# ---------------------------------------------------------------- 2 + 3. PROSPER
tol_pct = float(s["tolerance"]) * 100
with st.container(border=True):
    st.subheader("Nodal analysis and gradient match")
    st.markdown(
        f'<span class="wa-note">PROSPER gradient from THP with the day\'s liquid rate, WCT and GOR, read at '
        f'<code>{row["nodal_string"] or "no result string set"}</code>. The match then adjusts rate, then GOR, '
        f'then WCT until the calculated pressure is within the tolerance of the gauge BHP.</span>',
        unsafe_allow_html=True)
    o1, o2, o3, o4 = st.columns([2, 1.2, 1.2, 2.4])
    method = o1.segmented_control(
        "Match method", ["sequential", "binary_chop"], default=s["match_method"],
        format_func=lambda v: {"sequential": "Rate → GOR → WCT", "binary_chop": "Binary chop on rate"}[v],
    ) or s["match_method"]
    tol_in = o2.number_input("Tolerance %", 0.01, 50.0, tol_pct, 0.5, format="%.2f")
    iters = o3.number_input("Max iterations", 5, 2000, int(s["max_iterations"]), 5)
    run_s = {**s, "match_method": method, "tolerance": tol_in / 100, "max_iterations": int(iters)}
    with o4:
        st.write("")
        bc1, bc2, bc3 = st.columns(3)
        do_nodal = bc1.button("Nodal", use_container_width=True, help="Calculate_BHP_Nodal_analysis")
        do_match = bc2.button("Match", use_container_width=True, help="Allocate (gradient match)")
        do_both = bc3.button("Run both", type="primary", use_container_width=True)
    if do_nodal or do_match or do_both:
        bar, cb = progress_runner("Opening PROSPER model")
        try:
            if do_both:
                out = wf.nodal_and_match(run, row, run_s, cb)
            elif do_nodal:
                out = wf.nodal(run, row, run_s, cb)
            else:
                out = wf.match(run, row, run_s, cb)
            save(out)
            bar.empty()
            st.toast("PROSPER run complete")
            st.rerun()
        except Exception as exc:
            bar.empty()
            st.error(f"PROSPER run failed: {exc}")

    k1, k2, k3, k4 = st.columns(4)
    dev = run["nodal_dev_pct"]
    k1.metric("Mean nodal deviation", ui.fmt(dev.mean(), 2, " %") if has_nodal else "–",
              help="|gauge BHP − PROSPER BHP| / gauge BHP, using MPFM rates")
    k2.metric(f"Days within {tol_in:g} %", f"{int((dev <= tol_in).sum())} / {int(dev.notna().sum())}" if has_nodal else "–")
    ok = run["match_ok"].eq(True)
    k3.metric("Days matched", f"{int(ok.sum())} / {int(run['match_bhp'].notna().sum())}" if has_match else "–")
    if has_match:
        ratio = (run["match_liquid"] / run["liquid"]).replace([np.inf, -np.inf], np.nan)
        k4.metric("Matched ÷ MPFM liquid", ui.fmt(ratio.median(), 2, "×"), help="Median over the month")
    else:
        k4.metric("Matched ÷ MPFM liquid", "–")

# ---------------------------------------------------------------- review
x = run.index
tab_p, tab_r, tab_wg, tab_t = st.tabs(["Pressures", "Liquid rate", "WCT and GOR", "Daily table"])
with tab_p:
    band = run["bhp"] * float(s["tolerance"])
    fig = go.Figure()
    ui.band(fig, x, run["bhp"] - band, run["bhp"] + band, f"Gauge ±{tol_pct:g} %", "rgba(43,92,158,0.12)")
    ui.line(fig, x, run["bhp"], "Gauge BHP", ui.PRESS["bhp"], unit="psia")
    if has_nodal:
        ui.line(fig, x, run["bhp_nodal"], "PROSPER BHP (MPFM rates)", ui.PRESS["nodal"], dash="dot", unit="psia")
    if has_match:
        ui.line(fig, x, run["match_bhp"], "PROSPER BHP (matched)", ui.PRESS["match"], unit="psia")
    st.plotly_chart(ui.base_layout(fig, 360, "BHP, psia"), use_container_width=True)
    fig = go.Figure()
    ui.line(fig, x, run["thp"], "THP", ui.PRESS["thp"], unit="psia")
    fig = ui.base_layout(fig, 200, "THP, psia", legend=False)
    fig.update_layout(title=dict(text="Tubing head pressure", x=0, font=dict(size=14)), margin=dict(t=36))
    st.plotly_chart(fig, use_container_width=True)
with tab_r:
    fig = go.Figure()
    ui.line(fig, x, run["liquid"], "MPFM liquid", ui.PHASE["water"], unit="stb/d")
    if has_match:
        ui.line(fig, x, run["match_liquid"], "Matched liquid", ui.PRESS["match"], unit="stb/d")
    if run["manual_liquid"].notna().any():
        ui.line(fig, x, run["manual_liquid"], "Manual liquid", ui.PRESS["thp"], dash="dash", unit="stb/d")
    st.plotly_chart(ui.base_layout(fig, 360, "stb/d"), use_container_width=True)
with tab_wg:
    a, b = st.columns(2)
    fig = go.Figure()
    ui.line(fig, x, run["wct"], "MPFM", ui.PHASE["water"], hover_fmt=".1f", unit="%")
    if has_match:
        ui.line(fig, x, run["match_wct"], "Matched", ui.PRESS["match"], hover_fmt=".1f", unit="%")
    fig = ui.base_layout(fig, 300, "WCT %")
    fig.update_yaxes(tickformat=".0f")
    fig.update_layout(title=dict(text="Water cut", x=0, font=dict(size=14)))
    a.plotly_chart(fig, use_container_width=True)
    fig = go.Figure()
    ui.line(fig, x, run["gor"], "MPFM", ui.PHASE["gas"], unit="scf/stb")
    if has_match:
        ui.line(fig, x, run["match_gor"], "Matched", ui.PRESS["match"], unit="scf/stb")
    fig = ui.base_layout(fig, 300, "scf/stb")
    fig.update_layout(title=dict(text="GOR", x=0, font=dict(size=14)))
    b.plotly_chart(fig, use_container_width=True)
with tab_t:
    st.caption("Type a manual liquid rate, WCT or GOR on any day to use it when exporting with 'Manual match'. "
               "Days left blank fall back to the MPFM values.")
    view = run.copy()
    view.index = view.index.date
    col_cfg = {
        "oil": st.column_config.NumberColumn("Oil", format="%.0f"),
        "gas": st.column_config.NumberColumn("Gas MMscf/d", format="%.3f"),
        "water": st.column_config.NumberColumn("Water", format="%.0f"),
        "thp": st.column_config.NumberColumn("THP", format="%.0f"),
        "bhp": st.column_config.NumberColumn("Gauge BHP", format="%.0f"),
        "liquid": st.column_config.NumberColumn("Liquid", format="%.0f"),
        "wct": st.column_config.NumberColumn("WCT %", format="%.2f"),
        "gor": st.column_config.NumberColumn("GOR", format="%.0f"),
        "bhp_nodal": st.column_config.NumberColumn("Nodal BHP", format="%.0f"),
        "nodal_dev_pct": st.column_config.NumberColumn("Nodal dev %", format="%.2f"),
        "match_bhp": st.column_config.NumberColumn("Matched BHP", format="%.0f"),
        "match_liquid": st.column_config.NumberColumn("Matched liquid", format="%.0f"),
        "match_wct": st.column_config.NumberColumn("Matched WCT", format="%.2f"),
        "match_gor": st.column_config.NumberColumn("Matched GOR", format="%.0f"),
        "match_err_pct": st.column_config.NumberColumn("Match err %", format="%.2f"),
        "match_phase": st.column_config.TextColumn("Matched on"),
        "match_iters": st.column_config.NumberColumn("Iter.", format="%d"),
        "match_ok": st.column_config.CheckboxColumn("Within tol."),
        "manual_liquid": st.column_config.NumberColumn("Manual liquid", format="%.0f"),
        "manual_wct": st.column_config.NumberColumn("Manual WCT", format="%.2f"),
        "manual_gor": st.column_config.NumberColumn("Manual GOR", format="%.0f"),
    }
    editable = ["manual_liquid", "manual_wct", "manual_gor"]
    edited = st.data_editor(view, column_config=col_cfg, disabled=[c for c in view.columns if c not in editable],
                            use_container_width=True, height=420, key=f"ed_{mk}_{well}")
    changed = not edited[editable].astype(float).equals(view[editable].astype(float))
    if changed:
        upd = run.copy()
        for c in editable:
            upd[c] = pd.to_numeric(edited[c], errors="coerce").values
        save(upd)
        st.toast("Manual values saved")

# ---------------------------------------------------------------- 4. export
with st.container(border=True):
    st.subheader("Export to the field roll-up")
    e1, e2 = st.columns([3, 2])
    options = list(al.SOURCES)
    default_src = exports[well][1].get("source", s["export_source"]) if exported else s["export_source"]
    src = e1.radio("Rates to export", options, index=options.index(default_src),
                   format_func=lambda k: al.SOURCES[k], horizontal=False)
    thr = float(s["auto_threshold_pct"])
    if src == "auto":
        thr = e1.number_input("Deviation limit for MPFM rates, %", 0.1, 100.0, thr, 0.5)
    if src in ("matched", "auto") and not has_match:
        e1.warning("Run the gradient match first; days without a match fall back to MPFM in auto mode only.")
    exp = al.build_export(run, src, thr)
    table = al.zonal_split(exp, zones)
    with e2:
        st.markdown("**Zone split**")
        st.dataframe(pd.DataFrame([{"Zone": z.name, "Interval": z.key, "Factor": z.split} for z in zones]),
                     hide_index=True, use_container_width=True)
        if exported:
            st.caption(f"Last saved {exports[well][1].get('saved_at', '').replace('T', ' ')} "
                       f"using {al.SOURCES.get(exports[well][1].get('source'), '')}.")
    show = table.copy()
    show.index = show.index.date
    names = {"liquid": "Liquid", "wct": "WCT %", "gor": "GOR", "bhp_dev_pct": "BHP dev %", "source": "Rates from",
             "oil": "Oil", "gas": "Gas MMscf/d", "water": "Water"}
    show["source"] = show["source"].map({"mpfm": "MPFM", "matched": "Matched", "manual": "Manual"})
    show = show.rename(columns=lambda c: names.get(c, c.replace("|", " ").replace(" wct", " WCT").replace(" gor", " GOR")))
    fmt = {c: st.column_config.NumberColumn(format="%.3f" if ("Gas" in c or c.endswith(" gas") or c.endswith("WCT"))
                                            else "%.2f" if "%" in c else "%.0f")
           for c in show.columns if c != "Rates from"}
    st.dataframe(show, use_container_width=True, height=260, column_config=fmt)
    a, b, _ = st.columns([1.3, 1.3, 3])
    if a.button("Save to field roll-up", type="primary", use_container_width=True):
        wf.export(run, row, {**s, "auto_threshold_pct": thr}, mk, src)
        st.toast(f"{well} saved to the {ui.period_label()} roll-up")
        st.rerun()
    meta = {"template": row["template"] or "Z1", "source_label": al.SOURCES[src],
            "zones": [{"key": z.key, "name": z.name, "split": z.split, "label": z.label} for z in zones]}
    b.download_button("Download well sheet", well_workbook(well, table, meta),
                      file_name=f"{well}_{mk}.xlsx", use_container_width=True,
                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

