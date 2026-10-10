"""Allocation calculations, ported from Allocation.xlsm.

derive_parameters      'Allocation Worksheet' columns L, M, N
run_nodal_analysis     macro Calculate_BHP_Nodal_analysis -> column AB, deviation column X
run_gradient_match     macro Allocate -> columns Q, T, U, V
match_binary_chop      function OsMatchBinaryChop (optional alternative solver)
build_export           macro ExportToTemplateSheet -> template columns B:F
zonal_split            formulas on templates Z1 / Z2 / Z3, columns G:Y
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Zone
from .prosper import is_finite

RUN_COLUMNS = [
    "oil", "gas", "water", "thp", "bhp",                  # PI (field units)
    "liquid", "wct", "gor",                                # derived (MPFM)
    "bhp_nodal", "nodal_dev_pct",                          # nodal analysis
    "match_bhp", "match_liquid", "match_wct", "match_gor",  # gradient match
    "match_err_pct", "match_phase", "match_iters", "match_ok",
    "manual_liquid", "manual_wct", "manual_gor",          # manual match
]


def empty_run(index: pd.DatetimeIndex) -> pd.DataFrame:
    df = pd.DataFrame(index=index, columns=RUN_COLUMNS, dtype="float64")
    df["match_phase"] = df["match_phase"].astype("object")
    df["match_ok"] = df["match_ok"].astype("object")
    return df


def derive_parameters(run: pd.DataFrame, well_row: pd.Series) -> pd.DataFrame:
    """Liquid = (Oil + Water) x factor;  WCT % = Water/(Oil+Water) x 100 x factor;  GOR = Gas x 1e6 / Oil x factor."""
    run = run.copy()
    lf = _num(well_row.get("liquid_factor"), 1.0)
    wf = _num(well_row.get("wct_factor"), 1.0)
    gf = _num(well_row.get("gor_factor"), 1.0)
    oil, gas, water = run["oil"].astype(float), run["gas"].astype(float), run["water"].astype(float)
    liq = oil + water
    with np.errstate(divide="ignore", invalid="ignore"):
        run["liquid"] = liq * lf
        run["wct"] = (water / liq * 100.0) * wf
        run["gor"] = (gas * 1e6 / oil) * gf
    return run.replace([np.inf, -np.inf], np.nan)


def _num(v, default):
    try:
        v = float(v)
        return default if np.isnan(v) else v
    except (TypeError, ValueError):
        return default


def run_nodal_analysis(run: pd.DataFrame, model, result_string: str, progress=None) -> pd.DataFrame:
    """For each day: THP, WCT, liquid rate, GOR -> PROSPER gradient -> BHP at the gauge node."""
    run = run.copy()
    n = len(run)
    for i, (d, r) in enumerate(run.iterrows()):
        if progress:
            progress(i / max(n, 1), f"Nodal analysis {d:%d %b}")
        if not is_finite(r.thp, r.liquid, r.wct, r.gor):
            run.at[d, "bhp_nodal"] = np.nan
            continue
        run.at[d, "bhp_nodal"] = model.gradient(r.thp, r.liquid, r.wct, r.gor, result_string)
    with np.errstate(divide="ignore", invalid="ignore"):
        run["nodal_dev_pct"] = (run["bhp"] - run["bhp_nodal"]).abs() / run["bhp"] * 100.0
    if progress:
        progress(1.0, "Nodal analysis done")
    return run.replace([np.inf, -np.inf], np.nan)


@dataclass
class MatchResult:
    liquid: float
    wct: float
    gor: float
    bhp: float
    err_pct: float
    phase: str
    iterations: int
    converged: bool


def match_sequential(f, target, rate, wct, gor, tol=0.05, max_iter=200) -> MatchResult:
    """The Allocate macro, step for step.

    Phase 1 scales the liquid rate by target/calculated; if that does not get
    within tolerance in max_iter steps, phase 2 scales GOR (keeping the last
    rate), then phase 3 scales WCT (keeping the last rate and GOR).
    f(rate, wct, gor) -> calculated pressure.
    """
    total = 0
    calc = float("nan")
    phases = [("rate", "liquid"), ("gor", "gor"), ("wct", "wct")]
    guess = {"liquid": float(rate), "wct": float(wct), "gor": float(gor)}
    for phase, key in phases:
        for _ in range(max_iter):
            calc = f(guess["liquid"], guess["wct"], guess["gor"])
            total += 1
            err = abs((calc - target) / target)
            if err <= tol:
                return MatchResult(guess["liquid"], guess["wct"], guess["gor"], calc, err * 100, phase, total, True)
            if not np.isfinite(calc) or calc == 0:
                break
            guess[key] *= target / calc
            if key == "liquid" and guess[key] <= 0:
                guess[key] = 1.0
            if key == "gor" and guess[key] < 0:
                guess[key] = 0.0
            if key == "wct":
                guess[key] = min(max(guess[key], 0.0), 100.0)
    err = abs((calc - target) / target) * 100 if np.isfinite(calc) else float("nan")
    return MatchResult(guess["liquid"], guess["wct"], guess["gor"], calc, err, "none", total, False)


def match_binary_chop(f, target, rate, wct, gor, tol=0.05, max_iter=200,
                      min_frac=0.1, max_frac=3.0) -> MatchResult:
    """OsMatchBinaryChop applied to the liquid rate between min_frac x and max_frac x the MPFM rate."""
    lo_in, hi_in = max(rate * min_frac, 1.0), max(rate * max_frac, 2.0)

    def err_of(q):
        c = f(q, wct, gor)
        return (c - target) / target, c

    e_min, c_min = err_of(lo_in)
    e_max, c_max = err_of(hi_in)
    n = 2
    if np.sign(e_min) == np.sign(e_max):
        q, e, c = (lo_in, e_min, c_min) if abs(e_min) < abs(e_max) else (hi_in, e_max, c_max)
        return MatchResult(q, wct, gor, c, abs(e) * 100, "no solution in bounds", n, abs(e) <= tol)
    # orient so that the 'lo' input gives negative error
    (lo, e_lo), (hi, e_hi) = ((lo_in, e_min), (hi_in, e_max)) if e_min < 0 else ((hi_in, e_max), (lo_in, e_min))
    q, e, c = lo, e_lo, c_min
    while n < max_iter:
        q = (lo + hi) / 2
        e, c = err_of(q)
        n += 1
        if abs(e) < tol:
            return MatchResult(q, wct, gor, c, abs(e) * 100, "rate", n, True)
        if e <= 0:
            lo, e_lo = q, e
        else:
            hi, e_hi = q, e
    q = hi if abs(e_hi) < abs(e_lo) else lo
    e, c = err_of(q)
    return MatchResult(q, wct, gor, c, abs(e) * 100, "max iterations", n + 1, False)


def run_gradient_match(run: pd.DataFrame, model, result_string: str, settings: dict,
                       progress=None) -> pd.DataFrame:
    """Match the PROSPER gradient to the measured BHP gauge pressure, day by day."""
    run = run.copy()
    tol = float(settings.get("tolerance", 0.05))
    max_iter = int(settings.get("max_iterations", 200))
    method = settings.get("match_method", "sequential")
    n = len(run)
    for i, (d, r) in enumerate(run.iterrows()):
        if progress:
            progress(i / max(n, 1), f"Gradient match {d:%d %b}")
        if not is_finite(r.bhp, r.thp, r.liquid, r.wct, r.gor) or r.bhp <= 0:
            for c in ["match_bhp", "match_liquid", "match_wct", "match_gor", "match_err_pct", "match_iters"]:
                run.at[d, c] = np.nan
            run.at[d, "match_phase"] = "skipped (missing data)"
            run.at[d, "match_ok"] = False
            continue

        def f(q, w, g, _thp=r.thp):
            return model.gradient(_thp, q, w, g, result_string)

        if method == "binary_chop":
            res = match_binary_chop(f, r.bhp, r.liquid, r.wct, r.gor, tol, max_iter,
                                    float(settings.get("chop_min_frac", 0.1)),
                                    float(settings.get("chop_max_frac", 3.0)))
        else:
            res = match_sequential(f, r.bhp, r.liquid, r.wct, r.gor, tol, max_iter)
        run.at[d, "match_bhp"] = res.bhp
        run.at[d, "match_liquid"] = res.liquid
        run.at[d, "match_wct"] = res.wct
        run.at[d, "match_gor"] = res.gor
        run.at[d, "match_err_pct"] = res.err_pct
        run.at[d, "match_phase"] = res.phase
        run.at[d, "match_iters"] = res.iterations
        run.at[d, "match_ok"] = res.converged
    if progress:
        progress(1.0, "Gradient match done")
    return run


SOURCES = {
    "mpfm": "MPFM-derived (as the workbook exports)",
    "matched": "Gradient-matched",
    "manual": "Manual match",
    "auto": "Auto: MPFM within deviation limit, otherwise matched",
}


def build_export(run: pd.DataFrame, source: str, auto_threshold_pct: float = 5.0) -> pd.DataFrame:
    """Rows for the zonal template sheet: Date, Liquid, WCT, GOR, BHP % deviation (+ which source was used)."""
    out = pd.DataFrame(index=run.index)
    mpfm = run[["liquid", "wct", "gor"]].astype(float)
    matched = run[["match_liquid", "match_wct", "match_gor"]].astype(float).set_axis(mpfm.columns, axis=1)
    manual = run[["manual_liquid", "manual_wct", "manual_gor"]].astype(float).set_axis(mpfm.columns, axis=1)
    dev_mpfm = run["nodal_dev_pct"].astype(float)
    dev_match = run["match_err_pct"].astype(float)

    if source == "matched":
        pick = pd.Series("matched", index=run.index)
    elif source == "manual":
        pick = pd.Series("manual", index=run.index)
    elif source == "auto":
        use_mpfm = dev_mpfm.le(auto_threshold_pct) | matched["liquid"].isna()
        pick = pd.Series(np.where(use_mpfm, "mpfm", "matched"), index=run.index)
    else:
        pick = pd.Series("mpfm", index=run.index)
    # a manual value always falls back to MPFM where it was left blank
    manual_blank = manual["liquid"].isna()
    pick = pick.mask((pick == "manual") & manual_blank, "mpfm")

    frames = {"mpfm": mpfm, "matched": matched, "manual": manual}
    vals = pd.DataFrame(index=run.index, columns=mpfm.columns, dtype=float)
    for name, frame in frames.items():
        m = pick == name
        vals.loc[m] = frame.loc[m].values
    out["liquid"] = vals["liquid"]
    out["wct"] = vals["wct"]
    out["gor"] = vals["gor"]
    out["bhp_dev_pct"] = np.where(pick == "matched", dev_match, np.where(pick == "mpfm", dev_mpfm, np.nan))
    out["source"] = pick
    return out


def zonal_split(export: pd.DataFrame, zones: list[Zone]) -> pd.DataFrame:
    """Template formulas: oil, gas and water from liquid/WCT/GOR, then each zone = phase x split factor."""
    df = export.copy()
    liq, wct, gor = df["liquid"].astype(float), df["wct"].astype(float), df["gor"].astype(float)
    df["oil"] = liq * (100 - wct) / 100
    df["gas"] = df["oil"] * gor / 1e6
    df["water"] = liq * wct / 100
    for z in zones:
        p = z.label
        df[f"{p}|oil"] = df["oil"] * z.split
        df[f"{p}|water"] = df["water"] * z.split
        df[f"{p}|gas"] = df["gas"] * z.split
        with np.errstate(divide="ignore", invalid="ignore"):
            df[f"{p}|gor"] = df[f"{p}|gas"] * 1e6 / df[f"{p}|oil"]
            df[f"{p}|wct"] = df[f"{p}|water"] / (df[f"{p}|oil"] + df[f"{p}|water"])
    return df.replace([np.inf, -np.inf], np.nan)
