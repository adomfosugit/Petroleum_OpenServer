"""Well rate allocation: PI data, PROSPER gradient matching and zonal export.

Run with:  streamlit run app.py
"""
import calendar
from pathlib import Path

import streamlit as st

from views import ui

st.set_page_config(page_title="Well Allocation", page_icon="🛢️", layout="wide")
ui.inject_css()

if "year" not in st.session_state:
    st.session_state["year"], st.session_state["month"] = ui.default_period()

VIEWS = Path(__file__).parent / "views"
pages = [
    st.Page(str(VIEWS / "allocate.py"), title="Well allocation", icon=":material/oil_barrel:", default=True),
    st.Page(str(VIEWS / "field.py"), title="Field roll-up", icon=":material/stacked_line_chart:"),
    st.Page(str(VIEWS / "overview.py"), title="Month status", icon=":material/checklist:"),
    st.Page(str(VIEWS / "configure.py"), title="Configuration", icon=":material/tune:"),
]

with st.sidebar:
    st.markdown("### Allocation month")
    c1, c2 = st.columns([3, 2])
    c1.selectbox("Month", range(1, 13), format_func=lambda m: calendar.month_name[m], key="month")
    c2.number_input("Year", min_value=2010, max_value=2100, step=1, key="year")
    s = ui.settings()
    st.markdown(ui.mode_chip(s["mode"]), unsafe_allow_html=True)
    if s["mode"] == "demo":
        st.caption("Synthetic rates and a stand-in well model. Switch to live on the Configuration page.")

st.navigation(pages, position="sidebar").run()
