"""Settings, well master data and connection checks (live: PI + PROSPER only)."""
from datetime import datetime

import pandas as pd
import streamlit as st

from core import factors as fx
from core import store
from core.config import NUMERIC_COLS, WELL_COLUMNS, WELLS_CSV, normalise_wells, save_settings
from core.pi_client import pi_available
from core.prosper import open_session, openserver_available
from views import ui

MODE = "live"

s = ui.settings()
if s.get("mode") != MODE:
    s["mode"] = MODE
    save_settings(s)
W = ui.wells()
ui.header("Configuration", "Connections, unit conversions, the Configuration Sheet, the audit trail and run resets")

pi_ok, pi_msg = pi_available()
os_ok, os_msg = openserver_available()

tab_c, tab_w, tab_a, tab_r, tab_t = st.tabs(["Settings", "Configuration Sheet", "Audit trail", "Reset runs",
                                              "Test PROSPER"])

# ---------------------------------------------------------------- settings
with tab_c:
    st.subheader("Connections")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown(f"**PI Data Archive** &nbsp; {'🟢' if pi_ok else '🔴'}")
        st.caption(pi_msg)
        st.caption(f"Server: {s['pi_server'] or 'default'} · Time zone: {s['timezone']} · Interval: {s['pi_interval']}")
        if st.button("Test PI connection", disabled=not pi_ok):
            try:
                import PIconnect as PI
                with (PI.PIServer(server=s["pi_server"]) if s["pi_server"] else PI.PIServer()) as srv:
                    st.success(f"Connected to {srv.server_name}")
            except Exception as exc:
                st.error(f"Could not connect: {exc}")
    with c2.container(border=True):
        st.markdown(f"**PROSPER (OpenServer)** &nbsp; {'🟢' if os_ok else '🔴'}")
        st.caption(os_msg)
        st.caption("Run a single gradient calculation on the Test PROSPER tab.")

    with st.form("settings"):
        st.subheader("Unit conversion applied to PI values")
        c1, c2, c3 = st.columns(3)
        lc = c1.number_input("Liquid (oil and water)", value=float(s["liquid_conv"]), format="%.4f",
                             help="Workbook cell C16. 151 converts m³/h to stb/d.")
        gc = c2.number_input("Gas", value=float(s["gas_conv"]), format="%.6f",
                             help="Workbook cell C17. 0.000848 converts Sm³/h to MMscf/d.")
        pc = c3.number_input("Pressure", value=float(s["pressure_conv"]), format="%.3f",
                             help="Workbook cell C18. 14.5 converts bar to psi.")

        st.subheader("ICV adjustments")
        c1, _, _ = st.columns(3)
        it = c1.number_input("Position change that counts as an adjustment", min_value=0.0,
                             value=float(s.get("icv_move_threshold", 0.5)), step=0.1, format="%.2f",
                             help="A day is flagged when a zone's ICV moved by more than this within the day, "
                                  "or its daily average changed by more than this from the day before. "
                                  "Applies from the next pull.")

        if st.form_submit_button("Save settings", type="primary"):
            # PI server, time zone, interval and matching settings keep their saved values.
            s.update(mode=MODE, liquid_conv=lc, gas_conv=gc, pressure_conv=pc, icv_move_threshold=it)
            save_settings(s)
            st.toast("Settings saved")
            st.rerun()

# ---------------------------------------------------------------- configuration sheet
with tab_w:
    if not WELLS_CSV.exists():
        st.info(f"No Configuration Sheet found. Save the sheet as CSV (header rows included) to\n\n"
                f"`{WELLS_CSV}`\n\nthen refresh this page.")
    elif W.empty:
        st.error(f"`{WELLS_CSV.name}` was found but no wells could be read from it. Check it is the Configuration "
                 "Sheet saved as CSV, starting at the Well column.")
    else:
        mod = datetime.fromtimestamp(WELLS_CSV.stat().st_mtime).strftime("%d %b %Y %H:%M")
        st.markdown(f'<p class="wa-note">{len(W)} wells read from <code>{WELLS_CSV}</code> (saved {mod}). '
                    'Edit cells in place, then review and save below. Every save keeps a copy of the previous '
                    'sheet and records each changed cell in the audit trail. A factor edited here applies to '
                    '<b>every date</b>; to change a factor from a given date onwards, use <b>Factors</b> on the '
                    'Well allocation page.</p>', unsafe_allow_html=True)
        ver = st.session_state.setdefault("cfg_ver", 0)
        cfg = {k: (st.column_config.NumberColumn(label) if k in NUMERIC_COLS else st.column_config.TextColumn(label))
               for k, (label, _) in WELL_COLUMNS.items()}
        cfg["well"] = st.column_config.TextColumn(WELL_COLUMNS["well"][0], required=True)
        cfg["template"] = st.column_config.SelectboxColumn(WELL_COLUMNS["template"][0], options=["Z1", "Z2", "Z3"])
        edited = st.data_editor(W, column_config=cfg, num_rows="dynamic", width="stretch", height=480,
                                hide_index=True, key=f"cfg_editor_{ver}")
        changes = fx.diff_wells(W, normalise_wells(edited), {k: v[0] for k, v in WELL_COLUMNS.items()})
        d1, d2 = st.columns([3, 1])
        d2.download_button("Download sheet (CSV)", W.rename(columns={k: v[0] for k, v in WELL_COLUMNS.items()})
                           .to_csv(index=False).encode(), file_name="configuration_sheet.csv", mime="text/csv",
                           width="stretch")
        if not changes:
            d1.caption("No unsaved edits.")
        else:
            with st.container(border=True):
                st.markdown(f"**{len(changes)} unsaved change(s)**")
                st.dataframe(pd.DataFrame(changes).rename(columns={"well": "Well", "field": "Column",
                                                                   "old": "Was", "new": "Now"}),
                             hide_index=True, width="stretch", height=min(38 + 35 * len(changes), 260))
                r1, r2, r3 = st.columns([4, 1.4, 1])
                why = r1.text_input("Reason for the change", key=f"cfg_why_{ver}",
                                    placeholder="e.g. new BHP gauge tag after workover")
                r2.write("")
                if r2.button("Save Configuration Sheet", type="primary", width="stretch"):
                    try:
                        done = fx.save_config_sheet(edited, why)
                        st.session_state["cfg_ver"] = ver + 1
                        st.toast(f"Configuration Sheet saved: {len(done)} change(s) logged")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                r3.write("")
                if r3.button("Discard", width="stretch"):
                    st.session_state["cfg_ver"] = ver + 1
                    st.rerun()

# ---------------------------------------------------------------- audit trail
with tab_a:
    log = fx.load_audit()
    st.markdown('<p class="wa-note">Every change made in the app: Configuration Sheet edits, dated factor '
                'changes and run resets, with who made it, when and why. Copies of the Configuration Sheet '
                f'before each save are kept in <code>{fx.HISTORY_DIR}</code>.</p>', unsafe_allow_html=True)
    if log.empty:
        st.info("No changes recorded yet.")
    else:
        f1, f2, f3 = st.columns([1.5, 1.5, 1])
        acts = f1.multiselect("Action", sorted(log["action"].unique()))
        wls = f2.multiselect("Well", sorted(log["well"].unique()))
        view = log.iloc[::-1]
        if acts:
            view = view[view["action"].isin(acts)]
        if wls:
            view = view[view["well"].isin(wls)]
        f3.write("")
        f3.download_button("Download audit trail", log.to_csv(index=False).encode(), file_name="audit_log.csv",
                           mime="text/csv", width="stretch")
        view = view.assign(timestamp=view["timestamp"].str.replace("T", " "))
        st.dataframe(view, hide_index=True, width="stretch", height=min(38 + 35 * len(view), 520), column_config={
            "timestamp": "When", "user": "Who", "action": "Action", "well": "Well", "field": "What",
            "old": "Was", "new": "Now", "effective_from": "Effective from", "reason": "Reason"})

# ---------------------------------------------------------------- reset runs
with tab_r:
    y, m, mk = ui.period()
    st.markdown('<p class="wa-note">Clears saved work so wells can be pulled and run again from scratch. '
                'The Configuration Sheet, dated factor changes, fiscal (PPRS) data and the audit trail are kept.'
                '</p>', unsafe_allow_html=True)
    month_label = f"{ui.period_label()} only"
    scope = "month" if st.radio("Clear", [month_label, "All months"], horizontal=True) == month_label else "all"
    with_exp = st.checkbox("Also clear exports and zonal splits (the field reconciliation for those months)",
                           value=True)
    n = store.count_saved(MODE, mk if scope == "month" else None)
    st.caption(f"Saved now: {n['runs']} well run(s), {n['exports']} export(s).")
    c1, c2, c3 = st.columns([3, 1.6, 1.2])
    why = c1.text_input("Reason", key="reset_why", placeholder="e.g. re-run after PI backfill")
    rv = st.session_state.setdefault("reset_ver", 0)
    sure = c2.checkbox("I understand this can't be undone", key=f"reset_sure_{rv}")
    c3.write("")
    if c3.button("Clear runs", type="primary", disabled=not (sure and why.strip()), width="stretch"):
        done = store.clear_runs(MODE, mk if scope == "month" else None, with_exp, why)
        st.session_state.pop("open_well", None)
        st.session_state["reset_ver"] = rv + 1
        st.toast(f"Cleared {done['runs']} run(s) and {done['exports']} export(s)")
        st.rerun()

# ---------------------------------------------------------------- PROSPER test
with tab_t:
    st.markdown('<p class="wa-note">One gradient calculation, as in <code>calculate_gradient()</code>: '
                'opens the well\'s PROSPER file, sets THP, rate, WCT and GOR, runs '
                '<code>PROSPER.ANL.GRD.CALC()</code> and reads the result string.</p>', unsafe_allow_html=True)
    if not os_ok:
        st.warning(f"PROSPER is not reachable from this computer: {os_msg}")
    if W.empty:
        st.info("No wells loaded: see the Wells tab.")
    else:
        with st.form("grd"):
            c = st.columns(5)
            w = c[0].selectbox("Well", list(W["well"]))
            thp = c[1].number_input("THP, psia", 0.0, 20000.0, 1500.0)
            q = c[2].number_input("Liquid rate, stb/d", 0.0, 100000.0, 10000.0)
            wc = c[3].number_input("WCT, %", 0.0, 100.0, 30.0)
            gor = c[4].number_input("GOR, scf/stb", 0.0, 100000.0, 1500.0)
            run = st.form_submit_button("Calculate", type="primary", disabled=not os_ok)
        if run:
            row = W[W["well"] == w].iloc[0]
            try:
                with st.spinner("Running PROSPER"):
                    with open_session(MODE, row, s["show_prosper"]) as model:
                        val = model.gradient(thp, q, wc, gor, row["nodal_string"])
                st.metric(f"{row['nodal_string'] or 'Result'}", f"{val:,.1f} psia")
            except Exception as exc:
                st.error(f"PROSPER call failed: {exc}")
