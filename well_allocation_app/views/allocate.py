"""Well allocation: the engineer works one well at a time.

1 Open well  ->  2 Pull data  ->  3 Gradient match  ->  4 Review and export  ->  5 Zonal split (multi-zone wells only)
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import allocation as al
from core import store
from core import workflow as wf
from core.config import Zone, zones_for
from core.excel_export import well_workbook
from core.pi_client import MEASUREMENTS, read_uploaded
from views import ui

s = ui.settings()
W = ui.wells()
y, m, mk = ui.period()
mode = s["mode"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

if W.empty:
    st.info("No wells loaded yet. Save the Configuration Sheet as CSV to config/wells.csv in the app folder, then refresh.")
    st.stop()


def progress_runner(label):
    bar = st.progress(0.0, text=label)

    def cb(frac, msg):
        bar.progress(min(max(frac, 0.0), 1.0), text=msg)
    return bar, cb


# ================================================================ 1. open well
wells = list(W["well"])
opened = st.session_state.get("open_well")
pick_default = wells.index(opened) if opened in wells else 0

with st.container(border=True):
    ui.step(1, "Open well", done=bool(opened))
    c1, c2, c3 = st.columns([2, 1.2, 3])
    pick = c1.selectbox("Well", wells, index=pick_default, label_visibility="collapsed")
    open_clicked = c2.button("Open well" if pick != opened else "Reopen", type="primary" if pick != opened else "secondary",
                             width="stretch")
    if open_clicked:
        with st.spinner(f"Opening {pick}"):
            try:
                msg = wf.open_well(W[W["well"] == pick].iloc[0], s)
                st.session_state["open_well"] = pick
                st.session_state["open_msg"] = msg
                st.rerun()
            except Exception as exc:
                st.error(f"Could not open {pick}: {exc}")
    if opened and pick != opened:
        c3.markdown(f'<p class="wa-note">{opened} is open. Select <b>Open well</b> to switch to {pick}.</p>',
                    unsafe_allow_html=True)
    elif opened:
        c3.markdown(f'<p class="wa-note">{st.session_state.get("open_msg", "")}</p>', unsafe_allow_html=True)

if not opened:
    st.markdown('<p class="wa-note">Choose a well and open it to start.</p>', unsafe_allow_html=True)
    st.stop()

well = opened
row = W[W["well"] == well].iloc[0]
zones = zones_for(row)
multi = len(zones) > 1
run = store.load_run(mode, mk, well)
exports = store.load_exports(mode, mk)
exp_meta = exports[well][1] if well in exports else None

has_data = run is not None and run["liquid"].notna().any()
has_match = has_data and run["match_bhp"].notna().any()
exported = exp_meta is not None
split_done = exported and exp_meta.get("split_done", True)

prosper_name = Path(row["prosper_file"]).name if row["prosper_file"] else "not set"
ui.header(
    well,
    f"{ui.period_label()} allocation",
    [("Completion", "Multi-zone" if multi else "Single zone"),
     ("Template", row["template"] or "Z1"),
     ("Zones", ", ".join(z.name for z in zones) or "–"),
     ("PROSPER model", prosper_name)],
)
steps = [("Open well", "", True), ("Pull data", "", has_data), ("Gradient match", "", has_match),
         ("Export", "", exported)]
if multi:
    steps.append(("Zonal split", "", bool(split_done)))
ui.rail(steps)


def save(df):
    store.save_run(mode, mk, well, df)


# ================================================================ 2. pull data
with st.container(border=True):
    ui.step(2, "Pull data", done=has_data)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown(
            f'<span class="wa-note">Daily time-weighted averages for {ui.period_label()}, converted with '
            f'liquid ×{s["liquid_conv"]:g}, gas ×{s["gas_conv"]:g} and pressure ×{s["pressure_conv"]:g}. '
            f'Liquid, WCT and GOR then use this well\'s factors (liquid {row["liquid_factor"]:g}, '
            f'WCT {row["wct_factor"]:g}, GOR {row["gor_factor"]:g}).</span>', unsafe_allow_html=True)
        st.caption("Tags: " + ", ".join(f"{k.upper()} {row[col] or 'not set'}" for k, (col, _) in MEASUREMENTS.items()))
    with c2:
        b1, b2 = st.columns(2)
        pull_clicked = b1.button("Pull from PI" if mode == "live" else "Pull demo data",
                                 type="primary" if not has_data else "secondary", width="stretch")
        with b2.popover("Upload a file", width="stretch"):
            st.caption("CSV or Excel with columns date, oil, gas, water, thp, bhp in field units "
                       "(stb/d, MMscf/d, psia).")
            up = st.file_uploader("Daily data", type=["csv", "xlsx"], label_visibility="collapsed")
            if up is not None and st.button("Use this file", width="stretch"):
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
            st.session_state["pull_warnings"] = warns
            st.rerun()
        except Exception as exc:
            bar.empty()
            st.error(f"PI pull failed: {exc}")
    for k, v in st.session_state.pop("pull_warnings", {}).items():
        st.warning(f"{k.upper()}: {v}")

    if has_data:
        x = run.index
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Days with rates", f"{int(run['liquid'].notna().sum())} / {len(run)}")
        k2.metric("Liquid, avg", ui.fmt(run["liquid"].mean(), 0, " stb/d"))
        k3.metric("WCT, avg", ui.fmt(run["wct"].mean(), 1, " %"))
        k4.metric("GOR, avg", ui.fmt(run["gor"].mean(), 0, " scf/stb"))
        a, b = st.columns(2)
        fig = go.Figure()
        ui.line(fig, x, run["oil"], "Oil", ui.PHASE["oil"], unit="stb/d")
        ui.line(fig, x, run["water"], "Water", ui.PHASE["water"], unit="stb/d")
        fig = ui.base_layout(fig, 260, "stb/d")
        fig.update_layout(title=dict(text="MPFM rates", x=0, font=dict(size=14)), margin=dict(t=56))
        a.plotly_chart(fig, width="stretch")
        fig = go.Figure()
        ui.line(fig, x, run["bhp"], "Gauge BHP", ui.PRESS["bhp"], unit="psia")
        ui.line(fig, x, run["thp"], "THP", ui.PRESS["thp"], unit="psia")
        fig = ui.base_layout(fig, 260, "psia")
        fig.update_layout(title=dict(text="Pressures", x=0, font=dict(size=14)), margin=dict(t=56))
        b.plotly_chart(fig, width="stretch")

if not has_data:
    st.stop()

# ================================================================ 3. gradient match
tol_pct = float(s["tolerance"]) * 100
with st.container(border=True):
    ui.step(3, "Gradient match", done=has_match)
    st.markdown(
        f'<span class="wa-note">For each day PROSPER calculates the gradient from THP with the MPFM liquid rate, '
        f'WCT and GOR, reads the pressure at <code>{row["nodal_string"] or "no result string set"}</code>, '
        f'then adjusts the inputs until it matches the gauge BHP within tolerance.</span>', unsafe_allow_html=True)
    o1, o2, o3, o4 = st.columns([2, 1.2, 1.2, 1.6])
    method = o1.segmented_control(
        "Method", ["sequential", "binary_chop"], default=s["match_method"],
        format_func=lambda v: {"sequential": "Rate → GOR → WCT", "binary_chop": "Binary chop on rate"}[v],
    ) or s["match_method"]
    tol_in = o2.number_input("Tolerance %", 0.01, 50.0, tol_pct, 0.5, format="%.2f")
    iters = o3.number_input("Max iterations", 5, 2000, int(s["max_iterations"]), 5)
    o4.write("")
    go_match = o4.button("Run gradient match" if not has_match else "Run again",
                         type="primary" if not has_match else "secondary", width="stretch")
    if go_match:
        bar, cb = progress_runner("Opening PROSPER model")
        try:
            out = wf.gradient_match(run, row, {**s, "match_method": method, "tolerance": tol_in / 100,
                                               "max_iterations": int(iters)}, cb)
            save(out)
            bar.empty()
            st.rerun()
        except Exception as exc:
            bar.empty()
            st.error(f"Gradient match failed: {exc}")

if not has_match:
    st.stop()

# ================================================================ 4. review and export
with st.container(border=True):
    ui.step(4, "Review results and export", done=exported)
    k1, k2, k3, k4 = st.columns(4)
    dev = run["nodal_dev_pct"]
    k1.metric("Nodal deviation, MPFM rates", ui.fmt(dev.mean(), 2, " %"),
              help="Mean of |gauge BHP − PROSPER BHP| / gauge BHP before matching")
    k2.metric(f"Days already within {tol_in:g} %", f"{int((dev <= tol_in).sum())} / {int(dev.notna().sum())}")
    k3.metric("Days matched", f"{int(run['match_ok'].eq(True).sum())} / {int(run['match_bhp'].notna().sum())}")
    ratio = (run["match_liquid"] / run["liquid"]).replace([np.inf, -np.inf], np.nan)
    k4.metric("Matched ÷ MPFM liquid", ui.fmt(ratio.median(), 2, "×"), help="Median over the month")

    x = run.index
    tab_p, tab_r, tab_wg, tab_t = st.tabs(["Pressures", "Liquid rate", "WCT and GOR", "Daily table"])
    with tab_p:
        band = run["bhp"] * tol_in / 100
        fig = go.Figure()
        ui.band(fig, x, run["bhp"] - band, run["bhp"] + band, f"Gauge ±{tol_in:g} %", "rgba(43,92,158,0.12)")
        ui.line(fig, x, run["bhp"], "Gauge BHP", ui.PRESS["bhp"], unit="psia")
        ui.line(fig, x, run["bhp_nodal"], "PROSPER BHP (MPFM rates)", ui.PRESS["nodal"], dash="dot", unit="psia")
        ui.line(fig, x, run["match_bhp"], "PROSPER BHP (matched)", ui.PRESS["match"], unit="psia")
        st.plotly_chart(ui.base_layout(fig, 360, "BHP, psia"), width="stretch")
    with tab_r:
        fig = go.Figure()
        ui.line(fig, x, run["liquid"], "MPFM liquid", ui.PHASE["water"], unit="stb/d")
        ui.line(fig, x, run["match_liquid"], "Matched liquid", ui.PRESS["match"], unit="stb/d")
        if run["manual_liquid"].notna().any():
            ui.line(fig, x, run["manual_liquid"], "Manual liquid", ui.PRESS["thp"], dash="dash", unit="stb/d")
        st.plotly_chart(ui.base_layout(fig, 360, "stb/d"), width="stretch")
    with tab_wg:
        a, b = st.columns(2)
        fig = go.Figure()
        ui.line(fig, x, run["wct"], "MPFM", ui.PHASE["water"], hover_fmt=".1f", unit="%")
        ui.line(fig, x, run["match_wct"], "Matched", ui.PRESS["match"], hover_fmt=".1f", unit="%")
        fig = ui.base_layout(fig, 300, "WCT %")
        fig.update_yaxes(tickformat=".0f")
        fig.update_layout(title=dict(text="Water cut", x=0, font=dict(size=14)), margin=dict(t=56))
        a.plotly_chart(fig, width="stretch")
        fig = go.Figure()
        ui.line(fig, x, run["gor"], "MPFM", ui.PHASE["gas"], unit="scf/stb")
        ui.line(fig, x, run["match_gor"], "Matched", ui.PRESS["match"], unit="scf/stb")
        fig = ui.base_layout(fig, 300, "scf/stb")
        fig.update_layout(title=dict(text="GOR", x=0, font=dict(size=14)), margin=dict(t=56))
        b.plotly_chart(fig, width="stretch")
    with tab_t:
        st.caption("Type a manual liquid rate, WCT or GOR on any day to use it with 'Manual match' below. "
                   "Days left blank use the MPFM values.")
        view = run.copy()
        view.index = view.index.date
        n = st.column_config.NumberColumn
        col_cfg = {
            "oil": n("Oil", format="%.0f"), "gas": n("Gas MMscf/d", format="%.3f"),
            "water": n("Water", format="%.0f"), "thp": n("THP", format="%.0f"), "bhp": n("Gauge BHP", format="%.0f"),
            "liquid": n("Liquid", format="%.0f"), "wct": n("WCT %", format="%.2f"), "gor": n("GOR", format="%.0f"),
            "bhp_nodal": n("Nodal BHP", format="%.0f"), "nodal_dev_pct": n("Nodal dev %", format="%.2f"),
            "match_bhp": n("Matched BHP", format="%.0f"), "match_liquid": n("Matched liquid", format="%.0f"),
            "match_wct": n("Matched WCT", format="%.2f"), "match_gor": n("Matched GOR", format="%.0f"),
            "match_err_pct": n("Match err %", format="%.2f"), "match_phase": st.column_config.TextColumn("Matched on"),
            "match_iters": n("Iter.", format="%d"), "match_ok": st.column_config.CheckboxColumn("Within tol."),
            "manual_liquid": n("Manual liquid", format="%.0f"), "manual_wct": n("Manual WCT", format="%.2f"),
            "manual_gor": n("Manual GOR", format="%.0f"),
        }
        editable = ["manual_liquid", "manual_wct", "manual_gor"]
        edited = st.data_editor(view, column_config=col_cfg, disabled=[c for c in view.columns if c not in editable],
                                width="stretch", height=420, key=f"ed_{mk}_{well}")
        if not edited[editable].astype(float).equals(view[editable].astype(float)):
            upd = run.copy()
            for c in editable:
                upd[c] = pd.to_numeric(edited[c], errors="coerce").values
            save(upd)
            st.toast("Manual values saved")

    st.divider()
    e1, e2 = st.columns([3, 2])
    options = list(al.SOURCES)
    default_src = exp_meta.get("source", s["export_source"]) if exported else s["export_source"]
    src = e1.radio("Rates to export", options, index=options.index(default_src), format_func=lambda k: al.SOURCES[k])
    thr = float(s["auto_threshold_pct"])
    if src == "auto":
        thr = e1.number_input("Deviation limit for MPFM rates, %", 0.1, 100.0, thr, 0.5)
    with e2:
        if multi:
            st.markdown(f'<p class="wa-note">{well} has {len(zones)} zones, so exporting takes you to the '
                        f'zonal split.</p>', unsafe_allow_html=True)
        else:
            st.markdown(f'<p class="wa-note">{well} is a single-zone completion, so the exported rates go '
                        f'straight to the field roll-up.</p>', unsafe_allow_html=True)
        if exported:
            st.caption(f"Last exported {exp_meta.get('saved_at', '').replace('T', ' ')} "
                       f"using {al.SOURCES.get(exp_meta.get('source'), '')}.")
    preview = al.zonal_split(al.build_export(run, src, thr), [])
    show = preview.copy()
    show.index = show.index.date
    show["source"] = show["source"].map({"mpfm": "MPFM", "matched": "Matched", "manual": "Manual"})
    show = show.rename(columns={"liquid": "Liquid", "wct": "WCT %", "gor": "GOR", "bhp_dev_pct": "BHP dev %",
                                "source": "Rates from", "oil": "Oil", "gas": "Gas MMscf/d", "water": "Water"})
    fmt = {c: st.column_config.NumberColumn(format="%.3f" if "Gas" in c else "%.2f" if "%" in c else "%.0f")
           for c in show.columns if c != "Rates from"}
    st.dataframe(show, width="stretch", height=240, column_config=fmt)
    label = ("Export and go to zonal split" if multi else "Export to field roll-up")
    if st.button(label if not exported else f"Export again ({'zonal split will need redoing' if multi else 'replaces the saved rates'})",
                 type="primary" if not exported else "secondary"):
        wf.export_well(run, row, s, mk, src, thr)
        st.toast(f"{well} exported")
        st.rerun()
    if exported and not multi:
        table, meta = store.load_exports(mode, mk)[well]
        st.download_button("Download well sheet", well_workbook(well, table, meta),
                           file_name=f"{well}_{mk}.xlsx", mime=XLSX)

if not multi or not exported:
    st.stop()

# ================================================================ 5. zonal split (multi-zone only)
with st.container(border=True):
    ui.step(5, "Zonal split", done=bool(split_done))
    st.markdown(f'<span class="wa-note">Each zone gets the well\'s oil, gas and water times its factor. Defaults come '
                f'from the well configuration (template {row["template"]}); adjust them here for this month if needed. '
                f'Factors should add up to 1.</span>', unsafe_allow_html=True)
    saved = {z["key"]: z["split"] for z in exp_meta.get("zones", [])} if split_done else {}
    ztab = pd.DataFrame([{"Interval": z.key, "Zone": z.name, "Factor": saved.get(z.key, z.split)} for z in zones])
    c1, c2 = st.columns([2, 3])
    with c1:
        edited = st.data_editor(ztab, hide_index=True, width="stretch", disabled=["Interval", "Zone"],
                                column_config={"Factor": st.column_config.NumberColumn(min_value=0.0, max_value=1.0,
                                                                                       step=0.05, format="%.3f")},
                                key=f"split_{mk}_{well}")
        total = float(edited["Factor"].fillna(0).sum())
        if abs(total - 1) > 1e-6:
            st.warning(f"Factors add up to {total:.3f}, so the zones will not sum to the well total.")
        else:
            st.caption("Factors add up to 1.")
    new_zones = [Zone(z.key, z.name, float(f), z.label) for z, f in zip(zones, edited["Factor"].fillna(0))]
    table, _ = store.load_exports(mode, mk)[well]
    split_preview = al.zonal_split(table[["liquid", "wct", "gor", "bhp_dev_pct", "source"]], new_zones)
    with c2:
        totals = pd.DataFrame([{
            "Zone": z.name,
            "Oil, stb/d": split_preview[f"{z.label}|oil"].mean(),
            "Gas, MMscf/d": split_preview[f"{z.label}|gas"].mean(),
            "Water, stb/d": split_preview[f"{z.label}|water"].mean(),
        } for z in new_zones])
        st.markdown("**Month average by zone**")
        st.dataframe(totals, hide_index=True, width="stretch", column_config={
            "Oil, stb/d": st.column_config.NumberColumn(format="%.0f"),
            "Gas, MMscf/d": st.column_config.NumberColumn(format="%.3f"),
            "Water, stb/d": st.column_config.NumberColumn(format="%.0f")})
    with st.expander("Daily zone rates"):
        zshow = split_preview[[c for c in split_preview.columns if "|" in c]].copy()
        zshow.index = zshow.index.date
        zshow.columns = [c.replace("|", " ") for c in zshow.columns]
        st.dataframe(zshow, width="stretch", height=300)
    a, b, _ = st.columns([1.4, 1.4, 3])
    if a.button("Apply zonal split" if not split_done else "Apply again", type="primary" if not split_done else "secondary",
                width="stretch"):
        wf.apply_zonal_split(mode, mk, well, new_zones)
        st.toast(f"{well} split into {len(new_zones)} zones and added to the field roll-up")
        st.rerun()
    if split_done:
        table, meta = store.load_exports(mode, mk)[well]
        b.download_button("Download well sheet", well_workbook(well, table, meta),
                          file_name=f"{well}_{mk}.xlsx", width="stretch", mime=XLSX)
