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
from core import factors as fx
from core.pi_client import ICV_TAGS, MEASUREMENTS, month_index
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


def daily(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Selected run columns with a plain date index, for the daily tables."""
    out = df[cols].copy()
    out.index = out.index.date
    out.index.name = "Date"
    return out


_n = st.column_config.NumberColumn
COL_CFG = {
    "oil": _n("Oil, stb/d", format="%.0f"), "gas": _n("Gas, MMscf/d", format="%.3f"),
    "water": _n("Water, stb/d", format="%.0f"), "thp": _n("THP, psia", format="%.0f"),
    "bhp": _n("Gauge BHP, psia", format="%.0f"), "liquid": _n("Liquid, stb/d", format="%.0f"),
    "wct": _n("WCT %", format="%.2f"), "gor": _n("GOR, scf/stb", format="%.0f"),
    "bhp_nodal": _n("Nodal BHP, psia", format="%.0f"), "nodal_dev_pct": _n("Nodal dev %", format="%.2f"),
    "match_bhp": _n("Matched BHP, psia", format="%.0f"), "match_liquid": _n("Matched liquid", format="%.0f"),
    "match_wct": _n("Matched WCT %", format="%.2f"), "match_gor": _n("Matched GOR", format="%.0f"),
    "match_err_pct": _n("Match err %", format="%.2f"), "match_phase": st.column_config.TextColumn("Matched on"),
    "match_iters": _n("Iterations", format="%d"), "match_ok": st.column_config.CheckboxColumn("Within tol."),
    "manual_liquid": _n("Manual liquid", format="%.0f"), "manual_wct": _n("Manual WCT %", format="%.2f"),
    "manual_gor": _n("Manual GOR", format="%.0f"),
    "f_liquid": _n("Liquid factor", format="%.4g"), "f_wct": _n("WCT factor", format="%.4g"),
    "f_gor": _n("GOR factor", format="%.4g"),
}
PULL_COLS = ["oil", "gas", "water", "f_liquid", "liquid", "f_wct", "wct", "f_gor", "gor", "thp", "bhp"]
CALC_COLS = ["thp", "bhp", "liquid", "wct", "gor", "bhp_nodal", "nodal_dev_pct",
             "match_bhp", "match_liquid", "match_wct", "match_gor", "match_err_pct", "match_phase",
             "match_iters", "match_ok", "manual_liquid", "manual_wct", "manual_gor"]


# ================================================================ 2. pull data
icv_keys = wf.icv_zone_keys(row)
zone_name = {z.key.lower(): z.name for z in zones}
with st.container(border=True):
    ui.step(2, "Pull data", done=has_data)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown(
            f'<span class="wa-note">Daily time-weighted averages for {ui.period_label()}, converted with '
            f'liquid ×{s["liquid_conv"]:g}, gas ×{s["gas_conv"]:g} and pressure ×{s["pressure_conv"]:g}. '
            f'Liquid, WCT and GOR are then multiplied by this well\'s factors for each day '
            f'(Configuration Sheet values, or a dated change; see <b>Factors</b> below).</span>',
            unsafe_allow_html=True)
        tags = [f"{k.upper()} {row[col] or 'not set'}" for k, (col, _) in MEASUREMENTS.items()]
        tags += [f"{z.upper()} ICV {row[ICV_TAGS[z]] or 'not set'}" for z in icv_keys]
        st.caption("Tags: " + ", ".join(tags))
    with c2:
        pull_clicked = st.button("Pull from PI" if not has_data else "Pull from PI again",
                                 type="primary" if not has_data else "secondary", width="stretch")
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

    # ---- factors: config values plus dated changes ----------------------------
    month_days = month_index(y, m)
    fac_month = fx.daily_factors(row, month_days)
    changes = fx.load_changes(well)
    in_month = changes[(changes["effective_from"] >= month_days[0]) & (changes["effective_from"] <= month_days[-1])]
    stale = False
    if has_data:
        cur = run[["f_liquid", "f_wct", "f_gor"]].astype(float)
        stale = not np.allclose(cur.values, fac_month.reindex(run.index).values, equal_nan=False) \
            if cur.notna().all().all() else True
    label = "Factors" + (f"  ·  {len(in_month)} change(s) this month" if len(in_month) else "")
    with st.expander(label, expanded=bool(len(in_month)) or stale):
        st.markdown('<span class="wa-note">The Configuration Sheet factor applies until a dated change; a change '
                    'applies from its date onwards (until the next change). Changes are kept in the audit trail.'
                    '</span>', unsafe_allow_html=True)
        fc1, fc2 = st.columns([2, 3])
        with fc1:
            st.markdown(f"**{ui.period_label()}**")
            st.dataframe(fx.factor_periods(fac_month), hide_index=True, width="stretch", column_config={
                "Liquid": _n(format="%.4g"), "WCT": _n(format="%.4g"), "GOR": _n(format="%.4g")})
        with fc2:
            st.markdown(f"**Dated changes for {well}**")
            if changes.empty:
                st.caption("None. Every day uses the Configuration Sheet factors "
                           f"(liquid {row['liquid_factor']:g}, WCT {row['wct_factor']:g}, GOR {row['gor_factor']:g}).")
            else:
                ch = changes.assign(effective_from=changes["effective_from"].dt.date,
                                    factor=changes["factor"].map(fx.FACTOR_LABELS),
                                    recorded_at=changes["recorded_at"].str.replace("T", " "))
                st.dataframe(ch[["effective_from", "factor", "value", "recorded_by", "recorded_at", "reason"]],
                             hide_index=True, width="stretch", column_config={
                                 "effective_from": st.column_config.DateColumn("From"),
                                 "factor": "Factor", "value": _n("Value", format="%.4g"),
                                 "recorded_by": "By", "recorded_at": "Recorded", "reason": "Reason"})
        with st.form(f"fchg_{well}", clear_on_submit=True):
            f1, f2, f3, f4 = st.columns([1.4, 1, 1.2, 3])
            fac = f1.selectbox("Factor", list(fx.FACTORS), format_func=lambda k: fx.FACTOR_LABELS[k])
            val = f2.number_input("New value", min_value=0.0, value=1.0, step=0.01, format="%.4f")
            eff = f3.date_input("From", value=month_days[0].date(), format="DD/MM/YYYY")
            why = f4.text_input("Reason", placeholder="e.g. MPFM recalibrated")
            if st.form_submit_button("Add factor change", type="primary"):
                try:
                    before = fx.daily_factors(row, pd.DatetimeIndex([pd.Timestamp(eff)]))[f"f_{fac}"].iloc[0]
                    fx.add_change(well, fac, val, eff, why, old_value=before)
                    if has_data:
                        save(wf.refactor(run, row))
                    st.toast(f"{fx.FACTOR_LABELS[fac]} {val:g} from {eff:%d %b %Y} saved"
                             + (". Run PROSPER again for the new figures." if has_match else ""))
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if not changes.empty:
            r1, r2, r3 = st.columns([2.4, 3, 1.2])
            opts = {r["id"]: f"{r['effective_from']:%d %b %Y} · {fx.FACTOR_LABELS[r['factor']]} {r['value']:g}"
                    for _, r in changes.iterrows()}
            rid = r1.selectbox("Remove a change", list(opts), format_func=opts.get, key=f"rm_{well}")
            rwhy = r2.text_input("Reason for removing", key=f"rmwhy_{well}")
            r3.write("")
            if r3.button("Remove", key=f"rmbtn_{well}", width="stretch"):
                try:
                    fx.delete_change(rid, rwhy)
                    if has_data:
                        save(wf.refactor(run, row))
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    if stale:
        w1, w2 = st.columns([4, 1.3])
        w1.warning("The saved figures for this month were derived with different factors from the ones that now "
                   "apply (a dated change or a Configuration Sheet edit). Re-apply them to update liquid, WCT and "
                   "GOR; PROSPER results will be cleared.")
        if w2.button("Re-apply factors", type="primary", width="stretch"):
            save(wf.refactor(run, row))
            st.rerun()

    if has_data:
        x = run.index
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Days with rates", f"{int(run['liquid'].notna().sum())} / {len(run)}")
        k2.metric("Liquid, avg", ui.fmt(run["liquid"].mean(), 0, " stb/d"))
        k3.metric("WCT, avg", ui.fmt(run["wct"].mean(), 1, " %"))
        k4.metric("GOR, avg", ui.fmt(run["gor"].mean(), 0, " scf/stb"))
        st.markdown("**Pulled data, daily**")
        st.dataframe(daily(run, PULL_COLS), column_config=COL_CFG, width="stretch", height=320)
        if st.toggle("Show plots", key=f"plots_pull_{mk}_{well}"):
            a, g, b = st.columns(3)
            fig = go.Figure()
            ui.line(fig, x, run["oil"], "Oil", ui.PHASE["oil"], unit="stb/d")
            ui.line(fig, x, run["water"], "Water", ui.PHASE["water"], unit="stb/d")
            fig = ui.base_layout(fig, 260, "stb/d")
            fig.update_layout(title=dict(text="MPFM rates", x=0, font=dict(size=14)), margin=dict(t=56))
            a.plotly_chart(fig, width="stretch")
            fig = go.Figure()
            ui.line(fig, x, run["gor"], "GOR", ui.PHASE["gas"], unit="scf/stb")
            fig = ui.base_layout(fig, 260, "scf/stb", legend=False)
            fig.update_layout(title=dict(text="GOR", x=0, font=dict(size=14)), margin=dict(t=56))
            g.plotly_chart(fig, width="stretch")
            fig = go.Figure()
            ui.line(fig, x, run["bhp"], "Gauge BHP", ui.PRESS["bhp"], unit="psia")
            ui.line(fig, x, run["thp"], "THP", ui.PRESS["thp"], unit="psia")
            fig = ui.base_layout(fig, 260, "psia")
            fig.update_layout(title=dict(text="Pressures", x=0, font=dict(size=14)), margin=dict(t=56))
            b.plotly_chart(fig, width="stretch")

        # ---- ICV positions (multi-zone wells) ----------------------------------
        if icv_keys:
            st.divider()
            st.markdown("**ICV positions**")
            have_icv = [z for z in icv_keys if run[f"icv_{z}"].notna().any()]
            flagged = run["icv_moved"].dropna()
            if not have_icv:
                st.info("No ICV positions for this month. Check the ICV tags in the Configuration Sheet, then "
                        "pull again.")
            else:
                i1, i2 = st.columns([1, 3])
                i1.metric("Days with ICV adjustments", f"{len(flagged)}")
                if len(flagged):
                    i2.warning("ICV adjusted on " + "; ".join(f"{d:%d %b} ({v})" for d, v in flagged.items())
                               + ". Check the zonal split factors for the days after each adjustment.")
                else:
                    i2.success(f"No ICV adjustments in {ui.period_label()} "
                               f"(threshold {float(s.get('icv_move_threshold', 0.5)):g}).")
                icv_cols, icv_cfg = [], {"icv_moved": st.column_config.TextColumn("Adjusted")}
                for z in have_icv:
                    nm = ui.zone_label(z, zone_name.get(z, ""))
                    icv_cols += [f"icv_{z}", f"icv_{z}_min", f"icv_{z}_max"]
                    icv_cfg[f"icv_{z}"] = _n(f"{nm} avg", format="%.2f")
                    icv_cfg[f"icv_{z}_min"] = _n(f"{z.upper()} min", format="%.2f")
                    icv_cfg[f"icv_{z}_max"] = _n(f"{z.upper()} max", format="%.2f")
                icv_tab = daily(run, icv_cols + ["icv_moved"])
                icv_tab["icv_moved"] = icv_tab["icv_moved"].fillna("")
                st.dataframe(icv_tab, column_config=icv_cfg, width="stretch", height=280)
                if st.toggle("Show ICV plot", value=True, key=f"plots_icv_{mk}_{well}"):
                    st.plotly_chart(ui.icv_chart(run, have_icv, zone_name), width="stretch")

if not has_data:
    st.stop()

# ================================================================ 3. gradient match (manual for now)
tol_pct = float(s["tolerance"]) * 100
with st.container(border=True):
    ui.step(3, "Gradient match", done=has_match)
    st.markdown(
        f'<span class="wa-note"><b>Manual method.</b> For each day PROSPER runs the gradient from THP with the '
        f'figures below and reads the pressure at <code>{row["nodal_string"] or "no result string set"}</code>. '
        f'Type your own liquid rate, WCT or GOR on any day to run those instead; blank cells use the MPFM figures. '
        f'Adjust and run again until the calculated BHP sits on the gauge BHP. '
        f'Automatic matching will be added later.</span>', unsafe_allow_html=True)

    inp = daily(run, ["thp", "bhp", "liquid", "wct", "gor", "manual_liquid", "manual_wct", "manual_gor"])
    inp_cfg = {**COL_CFG,
               "liquid": _n("MPFM liquid, stb/d", format="%.0f"), "wct": _n("MPFM WCT %", format="%.2f"),
               "gor": _n("MPFM GOR, scf/stb", format="%.0f"),
               "manual_liquid": _n("Your liquid, stb/d", format="%.0f", min_value=0.0),
               "manual_wct": _n("Your WCT %", format="%.2f", min_value=0.0, max_value=100.0),
               "manual_gor": _n("Your GOR, scf/stb", format="%.0f", min_value=0.0)}
    editable = ["manual_liquid", "manual_wct", "manual_gor"]
    st.markdown("**Figures to run**")
    edited = st.data_editor(inp, column_config=inp_cfg, disabled=[c for c in inp.columns if c not in editable],
                            width="stretch", height=320, key=f"inp_{mk}_{well}")
    if not edited[editable].astype(float).equals(inp[editable].astype(float)):
        upd = run.copy()
        for c in editable:
            upd[c] = pd.to_numeric(edited[c], errors="coerce").values
        save(upd)
        run = upd
        st.toast("Figures saved. Run PROSPER to update the results.")

    o1, o2, o3 = st.columns([1.2, 1.2, 3])
    tol_in = o1.number_input("Tolerance %", 0.01, 50.0, tol_pct, 0.5, format="%.2f",
                             help="Days whose calculated BHP is within this of the gauge BHP are flagged as matched.")
    o2.write("")
    go_run = o2.button("Run Prosper Nodal Match" if not has_match else "Run Prosper Nodal Match again",
                       type="primary" if not has_match else "secondary", width="stretch")
    n_edit = int(run[editable].notna().any(axis=1).sum())
    o3.write("")
    o3.caption(f"{n_edit} day(s) with your own figures; the rest run on MPFM figures.")
    if go_run:
        bar, cb = progress_runner("Opening PROSPER model")
        try:
            out = wf.manual_match(run, row, {**s, "tolerance": tol_in / 100}, cb)
            save(out)
            bar.empty()
            st.rerun()
        except Exception as exc:
            bar.empty()
            st.error(f"PROSPER run failed: {exc}")

    if has_match:
        st.markdown("**Results**")
        k3, k4 = st.columns(2)
        err = run["match_err_pct"]
     
        k3.metric(f"Days within {tol_in:g} %", f"{int((err <= tol_in).sum())} / {int(err.notna().sum())}")
        k4.metric("Max deviation", ui.fmt(err.max(), 2, " %"))
        res = daily(run, ["thp", "match_liquid", "match_wct", "match_gor", "match_phase",
                          "bhp", "match_bhp", "match_err_pct", "bhp_nodal", "nodal_dev_pct"])
        res["match_ok"] = (run["match_err_pct"] <= tol_in).where(run["match_err_pct"].notna()).values
        res_cfg = {**COL_CFG,
                   "match_liquid": _n("Liquid run, stb/d", format="%.0f"), "match_wct": _n("WCT run %", format="%.2f"),
                   "match_gor": _n("GOR run, scf/stb", format="%.0f"),
                   "match_phase": st.column_config.TextColumn("Figures"),
                   "match_bhp": _n("PROSPER BHP, psia", format="%.0f"), "match_err_pct": _n("Deviation %", format="%.2f"),
                   "bhp_nodal": _n("PROSPER BHP (MPFM), psia", format="%.0f"),
                   "nodal_dev_pct": _n("Deviation (MPFM) %", format="%.2f")}
        st.dataframe(res, column_config=res_cfg, width="stretch", height=320)

        x = run.index
        band = run["bhp"] * tol_in / 100
        fig = go.Figure()
        ui.band(fig, x, run["bhp"] - band, run["bhp"] + band, f"Gauge ±{tol_in:g} %", "rgba(43,92,158,0.12)")
        ui.line(fig, x, run["bhp"], "Gauge BHP (actual)", ui.PRESS["bhp"], unit="psia")
        ui.line(fig, x, run["match_bhp"], "PROSPER BHP (figures run)", ui.PRESS["match"], unit="psia")
        if run["match_phase"].eq("manual").any():
            ui.line(fig, x, run["bhp_nodal"], "PROSPER BHP (MPFM figures)", ui.PRESS["nodal"], dash="dot", unit="psia")
        fig = ui.base_layout(fig, 380, "BHP, psia")
        fig.update_layout(title=dict(text="Calculated vs actual BHP", x=0, font=dict(size=14)), margin=dict(t=56))
        st.plotly_chart(fig, width="stretch")

if not has_match:
    st.stop()

# ================================================================ 4. review and export
with st.container(border=True):
    ui.step(4, "Review and export", done=exported)
    e1, e2 = st.columns([3, 2])
    options = ["mpfm"]
    default_src = exp_meta.get("source", s["export_source"]) if exported else s["export_source"]
    default_src = default_src if default_src in options else "matched"
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
    show["source"] = show["source"].map({"mpfm": "MPFM", "matched": "PROSPER run", "manual": "Manual"})
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
closed_max = float(s.get("icv_closed_max", 2.0))
icv_run = run[[c for c in run.columns if c.startswith("icv_")]]
have_icv = any(run[f"icv_{z.key.lower()}"].notna().any() for z in zones if f"icv_{z.key.lower()}" in run.columns)
with st.container(border=True):
    ui.step(5, "Zonal split", done=bool(split_done))
    st.markdown(f'<span class="wa-note">Each zone gets the well\'s oil, gas and water times its factor. Defaults come '
                f'from the well configuration (template {row["template"]}); adjust them here for this month if needed. '
                f'Factors should add up to 1. On any day a zone\'s ICV reads at or below <b>{closed_max:g}</b> '
                f'(closed), that zone gets no rate and the open zones\' factors are prorated to 100 %.</span>',
                unsafe_allow_html=True)
    icv_flags = run["icv_moved"].dropna()
    if len(icv_flags):
        st.warning("ICV adjustments this month: " + "; ".join(f"{d:%d %b} ({v})" for d, v in icv_flags.items())
                   + ". Check the factors below still hold after each adjustment.")
    if not have_icv:
        st.info("No ICV positions for this month, so every zone is treated as open. Pull from PI again to read the "
                "ICVs.")
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
            st.warning(f"Factors add up to {total:.3f}, so the zones will not sum to the well total on days with "
                       "every ICV open.")
        else:
            st.caption("Factors add up to 1.")
    new_zones = [Zone(z.key, z.name, float(f), z.label) for z, f in zip(zones, edited["Factor"].fillna(0))]
    table, _ = store.load_exports(mode, mk)[well]
    split_preview = al.zonal_split(table[["liquid", "wct", "gor", "bhp_dev_pct", "source"]], new_zones,
                                   icv_run, closed_max)
    with c2:
        totals = pd.DataFrame([{
            "Zone": z.name,
            "Days closed": int(split_preview["icv_closed"].fillna("").str.split(", ").map(lambda v: z.key in v).sum()),
            "Avg factor": split_preview[f"{z.label}|factor"].mean(),
            "Oil, stb/d": split_preview[f"{z.label}|oil"].mean(),
            "Gas, MMscf/d": split_preview[f"{z.label}|gas"].mean(),
            "Water, stb/d": split_preview[f"{z.label}|water"].mean(),
        } for z in new_zones])
        st.markdown("**Month average by zone**")
        st.dataframe(totals, hide_index=True, width="stretch", column_config={
            "Avg factor": st.column_config.NumberColumn(format="%.3f"),
            "Oil, stb/d": st.column_config.NumberColumn(format="%.0f"),
            "Gas, MMscf/d": st.column_config.NumberColumn(format="%.3f"),
            "Water, stb/d": st.column_config.NumberColumn(format="%.0f")})

    closed_days = split_preview["icv_closed"].dropna()
    notes = split_preview["icv_note"].dropna()
    if len(closed_days):
        runs_txt = []
        grp = (closed_days != closed_days.shift()).cumsum()
        for _, seg in closed_days.groupby(grp):
            d0, d1 = seg.index[0], seg.index[-1]
            span = f"{d0:%d %b}" if d0 == d1 else f"{d0:%d}–{d1:%d %b}"
            runs_txt.append(f"{seg.iloc[0]} closed {span}")
        st.info("ICV closed (position ≤ " + f"{closed_max:g}): " + "; ".join(runs_txt)
                + ". Those zones get no rate on those days and the open zones' factors are prorated to 100 %.")
    if len(notes):
        st.warning("; ".join(f"{d:%d %b}: {v}" for d, v in notes.items()))

    with st.expander("Daily zone factors and ICV positions", expanded=bool(len(closed_days))):
        fcols = []
        fcfg = {"icv_closed": st.column_config.TextColumn("Closed")}
        for z in new_zones:
            nm = ui.zone_label(z.key.lower(), z.name)
            fcols += [f"{z.label}|icv", f"{z.label}|factor"]
            fcfg[f"{z.label}|icv"] = st.column_config.NumberColumn(f"{nm} ICV", format="%.2f")
            fcfg[f"{z.label}|factor"] = st.column_config.NumberColumn(f"{nm} factor", format="%.3f")
        ftab = split_preview[fcols + ["icv_closed"]].copy()
        ftab["icv_closed"] = ftab["icv_closed"].fillna("")
        ftab.index = ftab.index.date
        ftab.index.name = "Date"
        st.dataframe(ftab, column_config=fcfg, width="stretch", height=300)
    with st.expander("Daily zone rates"):
        zshow = split_preview[[c for c in split_preview.columns
                               if "|" in c and not c.endswith(("|factor", "|icv"))]].copy()
        zshow.index = zshow.index.date
        zshow.columns = [c.replace("|", " ") for c in zshow.columns]
        st.dataframe(zshow, width="stretch", height=300)
    a, b, _ = st.columns([1.4, 1.4, 3])
    if a.button("Apply zonal split" if not split_done else "Apply again", type="primary" if not split_done else "secondary",
                width="stretch"):
        wf.apply_zonal_split(mode, mk, well, new_zones, closed_max)
        st.toast(f"{well} split into {len(new_zones)} zones and added to the field roll-up")
        st.rerun()
    if split_done:
        table, meta = store.load_exports(mode, mk)[well]
        b.download_button("Download well sheet", well_workbook(well, table, meta),
                          file_name=f"{well}_{mk}.xlsx", width="stretch", mime=XLSX)
