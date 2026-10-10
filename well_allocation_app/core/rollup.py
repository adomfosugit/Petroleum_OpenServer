"""Field roll-up.

all_wells_matrices  macros Import_Gradient_Match / _Gas / _Water -> 'Gradient Match All wells'
normalise           'Gradient Normalization': zone share of the day's total x PPRS fiscal figure
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PHASES = {"oil": ("Oil", "stb/d"), "gas": ("Gas", "MMscf/d"), "water": ("Water", "stb/d")}
PPRS_FOR_PHASE = {"oil": "oil", "gas": "gas", "water": "water"}


def all_wells_matrices(exports: dict, well_order: list[str], index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """One date x zone table per phase, columns ordered like the well configuration, plus a Total column."""
    out = {}
    for phase in PHASES:
        cols = {}
        for well in well_order + [w for w in exports if w not in well_order]:
            if well not in exports:
                continue
            df, _ = exports[well]
            for c in df.columns:
                if c.endswith(f"|{phase}"):
                    cols[c.split("|")[0]] = pd.to_numeric(df[c], errors="coerce").reindex(index)
        m = pd.DataFrame(cols, index=index)
        m["Total"] = m.sum(axis=1, min_count=1)
        out[phase] = m
    return out


def normalise(matrices: dict[str, pd.DataFrame], pprs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """zone_normalised = zone_rate / sum(all zones that day) x PPRS fiscal rate that day.

    The day's PPRS row is matched by date (the workbook lines rows up by position).
    """
    out = {}
    for phase, m in matrices.items():
        zones = m.drop(columns="Total")
        fiscal = pprs[PPRS_FOR_PHASE[phase]].reindex(m.index) if not pprs.empty else pd.Series(np.nan, index=m.index)
        with np.errstate(divide="ignore", invalid="ignore"):
            share = zones.div(m["Total"], axis=0)
        n = share.mul(fiscal, axis=0)
        n["Total"] = n.sum(axis=1, min_count=1)
        n["PPRS"] = fiscal
        out[phase] = n.replace([np.inf, -np.inf], np.nan)
    return out
