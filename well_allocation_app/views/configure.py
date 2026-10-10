"""Settings, well master data and connection checks."""
import streamlit as st

from core import allocation as al
from core.config import NUMERIC_COLS, WELL_COLUMNS, save_settings, save_wells, wells_from_workbook
from core.pi_client import pi_available
from core.prosper import open_session, openserver_available
from views import ui

s = ui.settings()
W = ui.wells()
ui.header("Configuration", "Connections, conversion factors, matching defaults and the well list")

pi_ok, pi_msg = pi_available()
os_ok, os_msg = openserver_available()

tab_c, tab_w, tab_t = st.tabs(["Settings", "Wells", "Test PROSPER"])

with tab_c:
    with st.form("settings"):
        st.subheader("Data source")
        mode = st.radio("Mode", ["demo", "live"], index=["demo", "live"].index(s["mode"]), horizontal=True,
                        format_func=lambda v: {"demo": "Demo: synthetic data and a stand-in well model",
                                               "live": "Live: PI and PROSPER on this computer"}[v])
        st.caption(f"PI: {pi_msg}.  PROSPER: {os_msg}.  Demo and live results are stored separately.")
        c1, c2, c3 = st.columns(3)
        pi_server = c1.text_input("PI server", s["pi_server"], help="Leave blank to use the default PI server")
        tz = c2.text_input("Time zone", s["timezone"])
        interval = c3.text_input("Summary interval", s["pi_interval"], help="1d gives the workbook's daily averages")

        st.subheader("Unit conversion applied to PI values")
        c1, c2, c3 = st.columns(3)
        lc = c1.number_input("Liquid (oil and water)", value=float(s["liquid_conv"]), format="%.4f",
                             help="Workbook cell C16. 151 converts m³/h to stb/d.")
        gc = c2.number_input("Gas", value=float(s["gas_conv"]), format="%.6f",
                             help="Workbook cell C17. 0.000848 converts Sm³/h to MMscf/d.")
        pc = c3.number_input("Pressure", value=float(s["pressure_conv"]), format="%.3f",
                             help="Workbook cell C18. 14.5 converts bar to psi.")

        st.subheader("Gradient match")
        c1, c2, c3 = st.columns(3)
        tol = c1.number_input("Tolerance %", 0.01, 50.0, float(s["tolerance"]) * 100, 0.5,
                              help="Workbook cell R5 (0.05 = 5 %)")
        mi = c2.number_input("Max iterations per phase", 5, 5000, int(s["max_iterations"]), 5)
        meth = c3.selectbox("Method", ["sequential", "binary_chop"],
                            index=["sequential", "binary_chop"].index(s["match_method"]),
                            format_func=lambda v: {"sequential": "Rate → GOR → WCT (workbook)",
                                                   "binary_chop": "Binary chop on rate"}[v])
        c1, c2, c3 = st.columns(3)
        cmin = c1.number_input("Binary chop lower bound, × MPFM rate", 0.01, 1.0, float(s["chop_min_frac"]), 0.05)
        cmax = c2.number_input("Binary chop upper bound, × MPFM rate", 1.0, 20.0, float(s["chop_max_frac"]), 0.25)
        show = c3.checkbox("Show the PROSPER window while running", bool(s["show_prosper"]))

        st.subheader("Export")
        c1, c2 = st.columns([2, 1])
        src = c1.selectbox("Default rates to export", list(al.SOURCES),
                           index=list(al.SOURCES).index(s["export_source"]), format_func=lambda k: al.SOURCES[k])
        thr = c2.number_input("Auto: MPFM deviation limit %", 0.1, 100.0, float(s["auto_threshold_pct"]), 0.5)
        if st.form_submit_button("Save settings", type="primary"):
            s.update(mode=mode, pi_server=pi_server.strip(), timezone=tz.strip(), pi_interval=interval.strip(),
                     liquid_conv=lc, gas_conv=gc, pressure_conv=pc, tolerance=tol / 100, max_iterations=int(mi),
                     match_method=meth, chop_min_frac=cmin, chop_max_frac=cmax, show_prosper=show,
                     export_source=src, auto_threshold_pct=thr)
            save_settings(s)
            st.toast("Settings saved")
            st.rerun()

    if s["mode"] == "live":
        if st.button("Test PI connection", disabled=not pi_ok):
            try:
                import PIconnect as PI
                with (PI.PIServer(server=s["pi_server"]) if s["pi_server"] else PI.PIServer()) as srv:
                    st.success(f"Connected to {srv.server_name}")
            except Exception as exc:
                st.error(f"Could not connect: {exc}")

with tab_w:
    st.markdown('<p class="wa-note">One row per well, the same columns as the workbook\'s Configuration Sheet. '
                'Tags left blank are skipped. Edit in place, then save.</p>', unsafe_allow_html=True)
    cfg = {k: (st.column_config.NumberColumn(label) if k in NUMERIC_COLS else st.column_config.TextColumn(label))
           for k, (label, _) in WELL_COLUMNS.items()}
    cfg["template"] = st.column_config.SelectboxColumn(WELL_COLUMNS["template"][0], options=["Z1", "Z2", "Z3"])
    edited = st.data_editor(W, column_config=cfg, num_rows="dynamic", use_container_width=True, height=520,
                            hide_index=True, key="wells_editor")
    a, b = st.columns([1, 3])
    if a.button("Save well list", type="primary", use_container_width=True):
        save_wells(edited)
        st.toast(f"Saved {len(edited.dropna(subset=['well']))} wells")
        st.rerun()
    with b.expander("Import from an Allocation workbook"):
        up = st.file_uploader("Allocation .xlsm / .xlsx", type=["xlsm", "xlsx"])
        if up is not None:
            try:
                new = wells_from_workbook(up)
                st.dataframe(new[["well", "template", "oil_tag", "thp_tag", "bhp_tag", "nodal_string"]],
                             hide_index=True, use_container_width=True)
                if st.button(f"Replace the well list with these {len(new)} wells"):
                    save_wells(new)
                    st.rerun()
            except Exception as exc:
                st.error(f"Could not read the workbook: {exc}")

with tab_t:
    st.markdown('<p class="wa-note">One gradient calculation, as in <code>calculate_gradient()</code>: '
                'opens the well\'s PROSPER file, sets THP, rate, WCT and GOR, runs '
                '<code>PROSPER.ANL.GRD.CALC()</code> and reads the result string.</p>', unsafe_allow_html=True)
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
            go_ = st.form_submit_button("Calculate", type="primary")
        if go_:
            row = W[W["well"] == w].iloc[0]
            try:
                with st.spinner("Running PROSPER"):
                    with open_session(s["mode"], row, s["show_prosper"]) as model:
                        val = model.gradient(thp, q, wc, gor, row["nodal_string"])
                st.metric(f"{row['nodal_string'] or 'Result'}", f"{val:,.1f} psia")
                if s["mode"] == "demo":
                    st.caption("Demo mode: this is the stand-in model, not PROSPER.")
            except Exception as exc:
                st.error(f"PROSPER call failed: {exc}")
