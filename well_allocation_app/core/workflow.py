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


def pull(well_row, year, month, settings, progress=None):
    if settings["mode"] == "live":
        raw, warnings = pull_well_month(well_row, year, month, settings, progress)
    else:
        raw, warnings = demo.demo_pull(well_row, year, month), {}
    run = al.empty_run(month_index(year, month))
    for c in raw.columns:
        run[c] = raw[c]
    return al.derive_parameters(run, well_row), warnings


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


def apply_zonal_split(mode, mk, well, zones: list[Zone]):
    """Split the exported well rates across its zones with the given factors."""
    exports = store.load_exports(mode, mk)
    if well not in exports:
        raise ValueError(f"Export {well} before splitting it.")
    table, meta = exports[well]
    base = table[["liquid", "wct", "gor", "bhp_dev_pct", "source"]]
    out = al.zonal_split(base, zones)
    meta = {**meta, "zones": _zone_meta(zones), "split_done": True}
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
