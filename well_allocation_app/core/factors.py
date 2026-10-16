"""Dated factor changes and the audit trail.

The Configuration Sheet holds one liquid / WCT / GOR factor per well. When a factor
has to change part-way through (e.g. a meter recalibration on the 6th), the engineer
records a dated change: it applies from that date onwards, until the next change.
Days before the first change use the Configuration Sheet value.

config/factor_changes.csv   one row per dated change (well, factor, value, effective_from, ...)
config/audit_log.csv        every change made through the app: factor changes, config sheet
                            edits, run resets, with who, when and why
config/history/             a copy of the Configuration Sheet taken before each save
"""
from __future__ import annotations

import getpass
import uuid
from datetime import datetime

import numpy as np
import pandas as pd

from .config import CONFIG_DIR, clean_text

FACTOR_FILE = CONFIG_DIR / "factor_changes.csv"
AUDIT_FILE = CONFIG_DIR / "audit_log.csv"
HISTORY_DIR = CONFIG_DIR / "history"

FACTORS = {"liquid": "liquid_factor", "wct": "wct_factor", "gor": "gor_factor"}   # factor -> config column
FACTOR_LABELS = {"liquid": "Liquid rate factor", "wct": "WCT factor", "gor": "GOR factor"}
CHANGE_COLUMNS = ["id", "well", "factor", "value", "effective_from", "recorded_at", "recorded_by", "reason"]
AUDIT_COLUMNS = ["timestamp", "user", "action", "well", "field", "old", "new", "effective_from", "reason"]


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---- audit ---------------------------------------------------------------------
def log(rows: list[dict]) -> None:
    """Append rows to the audit log (missing fields are left blank)."""
    if not rows:
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([{c: r.get(c, "") for c in AUDIT_COLUMNS} for r in rows], columns=AUDIT_COLUMNS)
    df.to_csv(AUDIT_FILE, mode="a", header=not AUDIT_FILE.exists(), index=False)


def load_audit() -> pd.DataFrame:
    if not AUDIT_FILE.exists():
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    return pd.read_csv(AUDIT_FILE, dtype=str, keep_default_na=False)


# ---- factor changes ---------------------------------------------------------------
def load_changes(well: str | None = None) -> pd.DataFrame:
    if FACTOR_FILE.exists():
        df = pd.read_csv(FACTOR_FILE, dtype=str, keep_default_na=False)
    else:
        df = pd.DataFrame(columns=CHANGE_COLUMNS)
    for c in CHANGE_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[CHANGE_COLUMNS]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["effective_from"] = pd.to_datetime(df["effective_from"], errors="coerce").dt.normalize()
    if well is not None:
        df = df[df["well"] == well]
    return df.sort_values(["well", "factor", "effective_from", "recorded_at"]).reset_index(drop=True)


def _save_changes(df: pd.DataFrame) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out = df[CHANGE_COLUMNS].copy()
    out["effective_from"] = pd.to_datetime(out["effective_from"]).dt.strftime("%Y-%m-%d")
    out.to_csv(FACTOR_FILE, index=False)


def add_change(well: str, factor: str, value: float, effective_from, reason: str, old_value=None,
               user: str | None = None) -> None:
    if factor not in FACTORS:
        raise ValueError(f"Unknown factor {factor!r}")
    if not clean_text(reason):
        raise ValueError("Give a reason for the change.")
    user = user or current_user()
    eff = pd.Timestamp(effective_from).normalize()
    df = load_changes()
    # a second change for the same well, factor and date replaces the first
    df = df[~((df["well"] == well) & (df["factor"] == factor) & (df["effective_from"] == eff))]
    new = {"id": uuid.uuid4().hex[:8], "well": well, "factor": factor, "value": float(value),
           "effective_from": eff, "recorded_at": _now(), "recorded_by": user, "reason": reason.strip()}
    _save_changes(pd.concat([df, pd.DataFrame([new])], ignore_index=True))
    log([{"timestamp": new["recorded_at"], "user": user, "action": "factor change", "well": well,
          "field": FACTOR_LABELS[factor], "old": "" if old_value is None else f"{old_value:g}",
          "new": f"{float(value):g}", "effective_from": eff.strftime("%Y-%m-%d"), "reason": reason.strip()}])


def delete_change(change_id: str, reason: str, user: str | None = None) -> None:
    if not clean_text(reason):
        raise ValueError("Give a reason for removing the change.")
    df = load_changes()
    hit = df[df["id"] == change_id]
    if hit.empty:
        return
    r = hit.iloc[0]
    _save_changes(df[df["id"] != change_id])
    log([{"timestamp": _now(), "user": user or current_user(), "action": "factor change removed",
          "well": r["well"], "field": FACTOR_LABELS.get(r["factor"], r["factor"]), "old": f"{r['value']:g}",
          "new": "", "effective_from": r["effective_from"].strftime("%Y-%m-%d"), "reason": reason.strip()}])


def _base(well_row, col) -> float:
    try:
        v = float(well_row.get(col))
        return 1.0 if np.isnan(v) else v
    except (TypeError, ValueError):
        return 1.0


def daily_factors(well_row, index: pd.DatetimeIndex, changes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Liquid / WCT / GOR factor for each day: the config value, overridden from each dated change onwards."""
    well = clean_text(well_row.get("well"))
    changes = load_changes(well) if changes is None else changes[changes["well"] == well]
    out = pd.DataFrame(index=index)
    for f, col in FACTORS.items():
        s = pd.Series(_base(well_row, col), index=index, dtype=float)
        for _, c in changes[changes["factor"] == f].sort_values("effective_from").iterrows():
            if pd.notna(c["effective_from"]) and pd.notna(c["value"]):
                s[s.index >= c["effective_from"]] = float(c["value"])
        out[f"f_{f}"] = s
    return out


def factor_periods(factors: pd.DataFrame) -> pd.DataFrame:
    """Collapse daily factors into From / To periods where all three stay the same."""
    if factors.empty:
        return pd.DataFrame(columns=["From", "To", "Liquid", "WCT", "GOR"])
    key = factors.round(9).astype(str).agg("|".join, axis=1)
    grp = (key != key.shift()).cumsum()
    rows = []
    for _, seg in factors.groupby(grp):
        rows.append({"From": seg.index[0].date(), "To": seg.index[-1].date(), "Liquid": seg["f_liquid"].iloc[0],
                     "WCT": seg["f_wct"].iloc[0], "GOR": seg["f_gor"].iloc[0]})
    return pd.DataFrame(rows)


# ---- configuration sheet edits -------------------------------------------------------
def diff_wells(old: pd.DataFrame, new: pd.DataFrame, labels: dict[str, str]) -> list[dict]:
    """Cell-level differences between two well tables, keyed by well name."""
    def norm(v):
        if v is None or (isinstance(v, float) and np.isnan(v)) or (v is pd.NA):
            return ""
        if isinstance(v, (int, float, np.floating)):
            return f"{float(v):g}"
        return str(v).strip()

    o = {r["well"]: r for _, r in old.iterrows()}
    n = {r["well"]: r for _, r in new.iterrows()}
    out = []
    for w in n:
        if w not in o:
            out.append({"well": w, "field": "(well)", "old": "", "new": "added"})
            continue
        for c in labels:
            if c == "well":
                continue
            a, b = norm(o[w].get(c)), norm(n[w].get(c))
            if a != b:
                out.append({"well": w, "field": labels[c], "old": a, "new": b})
    for w in o:
        if w not in n:
            out.append({"well": w, "field": "(well)", "old": "present", "new": "removed"})
    return out


def save_config_sheet(new: pd.DataFrame, reason: str, user: str | None = None) -> list[dict]:
    """Save an edited Configuration Sheet: back up the current file, write the new one, log each change."""
    import shutil

    from .config import WELL_COLUMNS, WELLS_CSV, load_wells, normalise_wells, save_wells

    if not clean_text(reason):
        raise ValueError("Give a reason for the change.")
    new = normalise_wells(new)
    if new.empty:
        raise ValueError("The edited sheet has no wells; nothing was saved.")
    if new["well"].duplicated().any():
        dup = ", ".join(sorted(new.loc[new["well"].duplicated(), "well"].unique()))
        raise ValueError(f"Duplicate well name(s): {dup}")
    old = load_wells()
    changes = diff_wells(old, new, {k: v[0] for k, v in WELL_COLUMNS.items()})
    if not changes:
        return []
    ts = _now()
    if WELLS_CSV.exists():
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(WELLS_CSV, HISTORY_DIR / f"wells_{ts.replace(':', '').replace('-', '')}.csv")
    save_wells(new)
    user = user or current_user()
    log([{"timestamp": ts, "user": user, "action": "config sheet edit", "well": c["well"], "field": c["field"],
          "old": c["old"], "new": c["new"], "reason": reason.strip()} for c in changes])
    return changes
