"""Month overview: where every well stands, and a batch runner for the whole field."""
import streamlit as st

from core import allocation as al
from core import store
from core import workflow as wf
from views import ui

s = ui.settings()
W = ui.wells()
y, m, mk = ui.period()
mode = s["mode"]

status = wf.status_for(mode, mk, W) if not W.empty else None
n = len(W)
ui.header(
    ui.period_label(),
    "Monthly well rate allocation",
    [("Wells configured", str(n)),
     ("Data pulled", str(int(status["pulled"].sum())) if status is not None else "0"),
     ("Gradient matched", str(int(status["matched"].sum())) if status is not None else "0"),
     ("Exported", f"{int(status['exported'].sum())} / {n}" if status is not None else "0")],
)

if W.empty:
    st.info("No wells are configured yet. Import your Allocation workbook on the Configuration page.")
    st.stop()

with st.expander("Run several wells", expanded=not status["exported"].all()):
    st.markdown('<p class="wa-note">Runs the same steps as the well page for each selected well, '
                'one PROSPER model at a time.</p>', unsafe_allow_html=True)
    todo = st.multiselect("Wells", list(W["well"]),
                          default=[w for w, e in zip(status["well"], status["exported"]) if not e])
    steps = st.pills("Steps", ["Pull data", "Nodal + match", "Export"], selection_mode="multi",
                     default=["Pull data", "Nodal + match", "Export"])
    src = st.selectbox("Rates to export", list(al.SOURCES), index=list(al.SOURCES).index(s["export_source"]),
                       format_func=lambda k: al.SOURCES[k])
    if st.button(f"Run {len(todo)} well{'s' if len(todo) != 1 else ''}", type="primary",
                 disabled=not todo or not steps, use_container_width=True):
        bar = st.progress(0.0)
        log = st.container()
        failed = 0
        for i, well in enumerate(todo):
            row = W[W["well"] == well].iloc[0]

            def cb(f, msg, _i=i, _w=well):
                bar.progress((_i + f) / len(todo), text=f"{_w}: {msg}")
            try:
                run = store.load_run(mode, mk, well)
                if "Pull data" in steps or run is None:
                    old = run
                    run, warns = wf.pull(row, y, m, s, lambda f, msg: cb(f * 0.3, msg))
                    if old is not None:
                        for c in ["manual_liquid", "manual_wct", "manual_gor"]:
                            run[c] = old[c].reindex(run.index)
                    for k, v in warns.items():
                        log.warning(f"{well} {k.upper()}: {v}")
                if "Nodal + match" in steps:
                    run = wf.nodal_and_match(run, row, s, lambda f, msg: cb(0.3 + f * 0.65, msg))
                store.save_run(mode, mk, well, run)
                if "Export" in steps:
                    wf.export(run, row, s, mk, src)
            except Exception as exc:
                log.error(f"{well}: {exc}")
                failed += 1
        bar.progress(1.0, text="Done" if not failed else f"Done, {failed} well(s) failed")
        if not failed:
            st.rerun()

st.subheader("Well status")
view = status.rename(columns={
    "well": "Well", "template": "Template", "pulled": "Pulled", "nodal": "Nodal", "matched": "Matched",
    "exported": "Exported", "days": "Days", "nodal_dev": "Mean nodal dev %",
    "match_rate": "Days matched %", "source": "Exported rates"})
view["Exported rates"] = view["Exported rates"].map(lambda k: al.SOURCES.get(k, "").split(" (")[0] if k else "")
st.dataframe(
    view, hide_index=True, use_container_width=True, height=min(38 + 35 * n, 760),
    column_config={
        "Pulled": st.column_config.CheckboxColumn(width="small"),
        "Nodal": st.column_config.CheckboxColumn(width="small"),
        "Matched": st.column_config.CheckboxColumn(width="small"),
        "Exported": st.column_config.CheckboxColumn(width="small"),
        "Mean nodal dev %": st.column_config.NumberColumn(format="%.2f"),
        "Days matched %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
    },
)

