"""Settings, well master data and connection checks (live: PI + PROSPER only)."""
import streamlit as st

from core.config import (NUMERIC_COLS, WELL_COLUMNS, WELLS_CSV, save_settings, save_wells,
                         wells_from_workbook)
from core.pi_client import pi_available
from core.prosper import open_session, openserver_available
from views import ui

MODE = "live"

s = ui.settings()
if s.get("mode") != MODE:
    s["mode"] = MODE
    save_settings(s)
W = ui.wells()
ui.header("Configuration", "PI and PROSPER connections, unit conversions and the well list")

pi_ok, pi_msg = pi_available()
os_ok, os_msg = openserver_available()

tab_c, tab_w, tab_t = st.tabs(["Settings", "Wells", "Test PROSPER"])

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

        if st.form_submit_button("Save settings", type="primary"):
            # PI server, time zone, interval and matching settings keep their saved values.
            s.update(mode=MODE, liquid_conv=lc, gas_conv=gc, pressure_conv=pc)
            save_settings(s)
            st.toast("Settings saved")
            st.rerun()

# ---------------------------------------------------------------- wells
with tab_w:
    if not WELLS_CSV.exists():
        st.warning("These are placeholder tags, not your field's. Import your Allocation workbook below "
                   "(or place your wells.csv in the config folder) to load the real Configuration Sheet.")
    st.markdown('<p class="wa-note">One row per well, the same columns as the workbook\'s Configuration Sheet. '
                'Tags left blank are skipped. Edit in place, then save.</p>', unsafe_allow_html=True)
    cfg = {k: (st.column_config.NumberColumn(label) if k in NUMERIC_COLS else st.column_config.TextColumn(label))
           for k, (label, _) in WELL_COLUMNS.items()}
    cfg["template"] = st.column_config.SelectboxColumn(WELL_COLUMNS["template"][0], options=["Z1", "Z2", "Z3"])
    edited = st.data_editor(W, column_config=cfg, num_rows="dynamic", width="stretch", height=520,
                            hide_index=True, key="wells_editor")
    a, b = st.columns([1, 3])
    if a.button("Save well list", type="primary", width="stretch"):
        save_wells(edited)
        st.toast(f"Saved {len(edited.dropna(subset=['well']))} wells")
        st.rerun()
    with b.expander("Import from an Allocation workbook", expanded=not WELLS_CSV.exists()):
        up = st.file_uploader("Allocation .xlsm / .xlsx", type=["xlsm", "xlsx"])
        if up is not None:
            try:
                new = wells_from_workbook(up)
                st.dataframe(new[["well", "template", "oil_tag", "thp_tag", "bhp_tag", "nodal_string"]],
                             hide_index=True, width="stretch")
                if st.button(f"Replace the well list with these {len(new)} wells"):
                    save_wells(new)
                    st.rerun()
            except Exception as exc:
                st.error(f"Could not read the workbook: {exc}")

# ---------------------------------------------------------------- PROSPER test
with tab_t:
    st.markdown('<p class="wa-note">One gradient calculation, as in <code>calculate_gradient()</code>: '
                'opens the well\'s PROSPER file, sets THP, rate, WCT and GOR, runs '
                '<code>PROSPER.ANL.GRD.CALC()</code> and reads the result string.</p>', unsafe_allow_html=True)
    if not os_ok:
        st.warning(f"PROSPER is not reachable from this computer: {os_msg}")
    if W.empty:
        st.info("Add a well first.")
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
