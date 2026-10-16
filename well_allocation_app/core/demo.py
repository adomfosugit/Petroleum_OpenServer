"""Synthetic data so the app can be explored without PI or PROSPER.

Everything produced here lives under data/demo and is labelled as demo in the UI.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .pi_client import month_index
from .prosper import DemoProsper


def _rng(*parts) -> np.random.Generator:
    seed = int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)
    return np.random.default_rng(seed)


def _truth(well: str, idx: pd.DatetimeIndex):
    rng = _rng("truth", well, idx[0].strftime("%Y-%m"))
    n = len(idx)
    q0 = rng.uniform(3000, 11000)
    w0 = rng.uniform(2, 35)
    g0 = rng.uniform(950, 1500)
    t = np.arange(n)
    q = q0 * (1 - 0.004 * t) * (1 + rng.normal(0, 0.02, n))
    w = np.clip(w0 + 0.08 * t + rng.normal(0, 0.4, n), 0, 95)
    g = g0 * (1 + rng.normal(0, 0.02, n))
    thp = rng.uniform(1100, 1300) + rng.normal(0, 12, n)
    return q, w, g, thp, rng


def demo_icv(well: str, idx: pd.DatetimeIndex, zone_keys) -> pd.DataFrame:
    """ICV positions 0-10: mostly steady, with one adjustment day on one zone (moves within that day)."""
    rng = _rng("icv", well, idx[0].strftime("%Y-%m"))
    out = pd.DataFrame(index=idx)
    moved = rng.choice(list(zone_keys)) if zone_keys else None
    day = int(rng.integers(5, len(idx) - 5))
    for z in zone_keys:
        pos = np.full(len(idx), float(rng.choice([4, 6, 8, 10])))
        lo, hi = pos.copy(), pos.copy()
        if z == moved:
            new = max(0.0, pos[0] - float(rng.choice([2, 4])))
            frac = rng.uniform(0.3, 0.7)            # time-weighted share of the move day at the old position
            lo[day], hi[day] = new, pos[0]
            pos[day] = pos[0] * frac + new * (1 - frac)
            pos[day + 1:], lo[day + 1:], hi[day + 1:] = new, new, new
        out[f"icv_{z}"], out[f"icv_{z}_min"], out[f"icv_{z}_max"] = pos, lo, hi
    return out


def demo_pull(well_row: pd.Series, year: int, month: int, icv_zones=()) -> pd.DataFrame:
    """Daily oil/gas/water (MPFM, with a meter bias), THP and BHP for one well-month."""
    idx = month_index(year, month)
    well = well_row["well"]
    q, w, g, thp, rng = _truth(well, idx)
    model = DemoProsper(well=well)
    bhp = np.array([model.gradient(thp[i], q[i], w[i], g[i]) for i in range(len(idx))])
    bhp *= 1 + rng.normal(0, 0.006, len(idx))
    bias = rng.uniform(0.82, 1.15)
    q_m = q * bias * (1 + rng.normal(0, 0.015, len(idx)))
    oil = q_m * (1 - w / 100)
    water = q_m * w / 100
    gas = oil * g * rng.uniform(0.95, 1.05) / 1e6
    df = pd.DataFrame({"oil": oil, "gas": gas, "water": water, "thp": thp, "bhp": bhp}, index=idx)
    # a couple of gauge dropouts so the app's gap handling is visible
    if rng.random() < 0.5:
        df.iloc[rng.integers(3, len(idx) - 3), [3, 4]] = np.nan
    if icv_zones:
        df = df.join(demo_icv(well, idx, list(icv_zones)))
    return df


def demo_pprs(year: int, month: int, wells: list[str]) -> pd.DataFrame:
    """Fiscal totals close to the sum of the wells' true rates."""
    idx = month_index(year, month)
    oil = np.zeros(len(idx))
    gas = np.zeros(len(idx))
    water = np.zeros(len(idx))
    for well in wells:
        q, w, g, _, _ = _truth(well, idx)
        oil += q * (1 - w / 100)
        water += q * w / 100
        gas += q * (1 - w / 100) * g / 1e6
    rng = _rng("pprs", year, month)
    n = len(idx)
    df = pd.DataFrame(index=idx)
    df["oil"] = oil * (1 + rng.normal(0, 0.01, n))
    df["gas"] = gas * (1 + rng.normal(0, 0.015, n))
    df["export_gas"] = df["gas"] * 0.55
    df["flare_gas"] = df["gas"] * 0.04
    df["fuel_gas"] = df["gas"] * 0.07
    df["gi"] = df["gas"] * 0.34
    df["water"] = water * (1 + rng.normal(0, 0.01, n))
    df["wi"] = df["oil"] * 4.5
    return df
