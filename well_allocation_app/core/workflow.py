"""The steps an engineer takes on one well, in order.

open_well -> pull -> gradient_match -> export_well -> (multi-zone only) apply_zonal_split
"""
from __future__ import annotations

import pandas as pd

from . import allocation as al
from . import demo, store
from .config import Zone, zones_for
from .pi_client import month_index, pull_well_month
from .prosper import open_session


def is_multi_zone(well_row) -> bool:
    return len(zones_for(well_row)) > 1


def open_well(well_row, settings) -> str:
    """Load the well's PROSPER model so the engineer can see it opens. Returns a short status line."""
    if settings["mode"] != "live":
        return "Demo mode: stand-in well model, no PROSPER file opened."
    with open_session("live", well_row, show=True):
        pass
    return f"PROSPER model loaded: {well_row['prosper_file']}"


def icv_zone_keys(well_row) -> list[str]:
    """Zones whose ICV positions are pulled: every zone of a multi-zone well (none for single-zone)."""
    zones = zones_for(well_row)
    return [z.key.lower() for z in zones] if len(zones) > 1 else []


def pull(well_row, year, month, settings, progress=None):
    icv = icv_zone_keys(well_row)
    if settings["mode"] == "live":
        raw, warnings = pull_well_month(well_row, year, month, settings, progress, icv_zones=icv)
    else:
        raw, warnings = demo.demo_pull(well_row, year, month, icv_zones=icv), {}
    run = al.empty_run(month_index(year, month))
    for c in raw.columns:
        run[c] = raw[c]
    run = al.derive_parameters(run, well_row)
    if icv:
        run = al.flag_icv_moves(run, icv, float(settings.get("icv_move_threshold", 0.5)))
    return run, warnings


def refactor(run, well_row):
    """Re-derive liquid / WCT / GOR after a factor change, without pulling PI again.
    PROSPER results are cleared because they were run on the old figures."""
    return al.clear_results(al.derive_parameters(run, well_row))


def manual_match(run, well_row, settings, progress=None):
    """Run PROSPER once per day on the figures (manual where typed, else MPFM) on one opened model."""
    with open_session(settings["mode"], well_row, settings.get("show_prosper", False)) as model:
        return al.run_manual_match(run, model, well_row["nodal_string"], float(settings["tolerance"]), progress)


def gradient_match(run, well_row, settings, progress=None):
    """Nodal BHP with the MPFM rates, then the gradient match, on one opened model."""
    with open_session(settings["mode"], well_row, settings.get("show_prosper", False)) as model:
        run = al.run_nodal_analysis(run, model, well_row["nodal_string"],
                                    (lambda f, m: progress(f * 0.3, m)) if progress else None)
        return al.run_gradient_match(run, model, well_row["nodal_string"], settings,
                                     (lambda f, m: progress(0.3 + f * 0.7, m)) if progress else None)


def _zone_meta(zones: list[Zone]) -> list[dict]:
    return [{"key": z.key, "name": z.name, "split": z.split, "label": z.label} for z in zones]


def export_well(run, well_row, settings, mk, source, auto_threshold_pct):
    """Save the well's daily rates. A single-zone well is complete here; a multi-zone well waits for its split."""
    zones = zones_for(well_row)
    base = al.zonal_split(al.build_export(run, source, auto_threshold_pct), [])
    single = len(zones) <= 1
    table = al.zonal_split(base[["liquid", "wct", "gor", "bhp_dev_pct", "source"]], zones) if single else base
    meta = {
        "well": well_row["well"],
        "template": well_row.get("template") or "Z1",
        "source": source,
        "source_label": al.SOURCES[source],
        "zones": _zone_meta(zones),
        "split_done": single,
    }
    store.save_export(settings["mode"], mk, well_row["well"], table, meta)
    return table, meta


def apply_zonal_split(mode, mk, well, zones: list[Zone], closed_max: float | None = None):
    """Split the exported well rates across its zones with the given factors. With closed_max, a zone whose
    ICV reads at or below it on a day gets no rate that day and the open zones' factors are prorated to 100 %."""
    exports = store.load_exports(mode, mk)
    if well not in exports:
        raise ValueError(f"Export {well} before splitting it.")
    table, meta = exports[well]
    base = table[["liquid", "wct", "gor", "bhp_dev_pct", "source"]]
    run = store.load_run(mode, mk, well) if closed_max is not None else None
    icv = run[[c for c in run.columns if c.startswith("icv_")]] if run is not None else None
    out = al.zonal_split(base, zones, icv, closed_max)
    closed_days = int(out["icv_closed"].notna().sum()) if "icv_closed" in out else 0
    meta = {**meta, "zones": _zone_meta(zones), "split_done": True,
            "icv_closed_max": closed_max, "icv_closed_days": closed_days}
    store.save_export(mode, mk, well, out, meta)
    return out, meta


def status_for(mode, mk, wells: pd.DataFrame) -> pd.DataFrame:
    exports = store.load_exports(mode, mk)
    rows = []
    for _, w in wells.iterrows():
        run = store.load_run(mode, mk, w["well"])
        has = run is not None
        meta = exports[w["well"]][1] if w["well"] in exports else {}
        multi = is_multi_zone(w)
        rows.append({
            "well": w["well"],
            "template": w["template"] or "Z1",
            "pulled": has and run["bhp"].notna().any(),
            "matched": has and run["match_bhp"].notna().any(),
            "exported": bool(meta),
            "split": ("done" if meta.get("split_done", True) else "to do" if meta else "") if multi else "single zone",
            "nodal_dev": float(run["nodal_dev_pct"].mean()) if has and run["nodal_dev_pct"].notna().any() else None,
            "match_rate": float(run["match_ok"].eq(True).mean() * 100) if has and run["match_bhp"].notna().any() else None,
            "source": meta.get("source"),
        })
    return pd.DataFrame(rows)
