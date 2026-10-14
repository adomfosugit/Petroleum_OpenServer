"""Month status: where each well stands. Work is done one well at a time on the Well allocation page."""
import streamlit as st

from core import allocation as al
from core import workflow as wf
from views import ui

s = ui.settings()
W = ui.wells()
y, m, mk = ui.period()

if W.empty:
    st.info("No wells loaded yet. Save the Configuration Sheet as CSV to config/wells.csv in the app folder, then refresh.")
    st.stop()

status = wf.status_for(s["mode"], mk, W)
n = len(W)
pending_split = int((status["split"] == "to do").sum())
complete = int((status["exported"] & status["split"].isin(["done", "single zone"])).sum())
ui.header(
    ui.period_label(),
    "Month status",
    [("Wells", str(n)), ("Data pulled", str(int(status["pulled"].sum()))),
     ("Matched", str(int(status["matched"].sum()))), ("In roll-up", f"{complete} / {n}")],
)
if pending_split:
    st.warning(f"{pending_split} multi-zone well(s) are exported but still need their zonal split: "
               + ", ".join(status.loc[status["split"] == "to do", "well"]))

view = status.rename(columns={
    "well": "Well", "template": "Template", "pulled": "Pulled", "matched": "Matched", "exported": "Exported",
    "split": "Zonal split", "nodal_dev": "Nodal dev %", "match_rate": "Days matched %", "source": "Exported rates"})
view["Exported rates"] = view["Exported rates"].map(lambda k: al.SOURCES.get(k, "").split(" (")[0] if k else "")
st.dataframe(
    view, hide_index=True, width="stretch", height=min(38 + 35 * n, 980),
    column_config={
        "Pulled": st.column_config.CheckboxColumn(width="small"),
        "Matched": st.column_config.CheckboxColumn(width="small"),
        "Exported": st.column_config.CheckboxColumn(width="small"),
        "Nodal dev %": st.column_config.NumberColumn(format="%.2f"),
        "Days matched %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
    },
)
st.caption("Open a well on the Well allocation page to pull, match, export and split it.")
