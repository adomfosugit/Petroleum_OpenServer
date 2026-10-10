"""One well-month through the whole chain. Used by the per-well page and the batch runner."""
from __future__ import annotations

import pandas as pd

from . import allocation as al
from . import demo, store
from .config import zones_for
from .pi_client import month_index, pull_well_month
from .prosper import open_session


def pull(well_row, year, month, settings, progress=None):
    if settings["mode"] == "live":
        raw, warnings = pull_well_month(well_row, year, month, settings, progress)
    else:
        raw, warnings = demo.demo_pull(well_row, year, month), {}
    run = al.empty_run(month_index(year, month))
    for c in raw.columns:
        run[c] = raw[c]
    return al.derive_parameters(run, well_row), warnings


def nodal(run, well_row, settings, progress=None):
    with open_session(settings["mode"], well_row, settings.get("show_prosper", False)) as model:
        return al.run_nodal_analysis(run, model, well_row["nodal_string"], progress)


def match(run, well_row, settings, progress=None):
    with open_session(settings["mode"], well_row, settings.get("show_prosper", False)) as model:
        return al.run_gradient_match(run, model, well_row["nodal_string"], settings, progress)


def nodal_and_match(run, well_row, settings, progress=None):
    """Both PROSPER steps on one opened file (saves re-opening the model)."""
    with open_session(settings["mode"], well_row, settings.get("show_prosper", False)) as model:
        run = al.run_nodal_analysis(run, model, well_row["nodal_string"],
                                    (lambda f, m: progress(f * 0.3, m)) if progress else None)
        return al.run_gradient_match(run, model, well_row["nodal_string"], settings,
                                     (lambda f, m: progress(0.3 + f * 0.7, m)) if progress else None)


def export(run, well_row, settings, mk, source=None):
    source = source or settings.get("export_source", "mpfm")
    zones = zones_for(well_row)
    exp = al.build_export(run, source, float(settings.get("auto_threshold_pct", 5.0)))
    table = al.zonal_split(exp, zones)
    meta = {
        "well": well_row["well"],
        "template": well_row.get("template") or "Z1",
        "source": source,
        "source_label": al.SOURCES[source],
        "zones": [{"key": z.key, "name": z.name, "split": z.split, "label": z.label} for z in zones],
    }
    store.save_export(settings["mode"], mk, well_row["well"], table, meta)
    return table, meta


def status_for(mode, mk, wells: pd.DataFrame) -> pd.DataFrame:
    exports = store.load_exports(mode, mk)
    rows = []
    for _, w in wells.iterrows():
        run = store.load_run(mode, mk, w["well"])
        has = run is not None
        rows.append({
            "well": w["well"],
            "template": w["template"] or "Z1",
            "pulled": has and run["bhp"].notna().any(),
            "nodal": has and run["bhp_nodal"].notna().any(),
            "matched": has and run["match_bhp"].notna().any(),
            "exported": w["well"] in exports,
            "days": int(run["liquid"].notna().sum()) if has else 0,
            "nodal_dev": float(run["nodal_dev_pct"].mean()) if has and run["nodal_dev_pct"].notna().any() else None,
            "match_rate": float(run["match_ok"].eq(True).mean() * 100) if has and run["match_bhp"].notna().any() else None,
            "source": exports[w["well"]][1].get("source") if w["well"] in exports else None,
        })
    return pd.DataFrame(rows)
