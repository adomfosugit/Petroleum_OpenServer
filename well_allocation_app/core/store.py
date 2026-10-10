"""Local storage for monthly runs, exports and PPRS fiscal data.

data/<mode>/runs/<YYYY-MM>/<well>.csv       working table per well (the 'Allocation Worksheet')
data/<mode>/exports/<YYYY-MM>/<well>.csv    zonal sheet per well   (the sheet ExportToTemplateSheet creates)
data/<mode>/exports/<YYYY-MM>/<well>.json   export metadata
data/<mode>/pprs.csv                        daily fiscal totals    (the 'PPRS ' sheet)
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from .allocation import RUN_COLUMNS
from .config import ROOT

DATA = ROOT / "data"

PPRS_COLUMNS = {
    "oil": "Oil Production (stb/d)",
    "export_gas": "Total Export Gas (MMscfd)",
    "flare_gas": "Flare Gas (MMscfd)",
    "fuel_gas": "Fuel Gas (MMscfd)",
    "gi": "GI (MMscfd)",
    "gas": "Prod Gas (MMscfd)",
    "wi": "WI Rate (b/d)",
    "water": "Prod Water (b/d)",
}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def root(mode: str) -> Path:
    p = DATA / ("live" if mode == "live" else "demo")
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---- runs -------------------------------------------------------------------
def run_path(mode, mk, well) -> Path:
    return root(mode) / "runs" / mk / f"{_safe(well)}.csv"


def save_run(mode, mk, well, df: pd.DataFrame) -> None:
    p = run_path(mode, mk, well)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index_label="date")


def load_run(mode, mk, well) -> pd.DataFrame | None:
    p = run_path(mode, mk, well)
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"], index_col="date")
    for c in RUN_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[RUN_COLUMNS]
    for c in RUN_COLUMNS:
        if c not in ("match_phase", "match_ok"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["match_phase"] = df["match_phase"].astype("object")
    df["match_ok"] = df["match_ok"].map(lambda v: str(v).lower() == "true" if pd.notna(v) else pd.NA).astype("object")
    return df


def delete_run(mode, mk, well) -> None:
    run_path(mode, mk, well).unlink(missing_ok=True)


# ---- exports ----------------------------------------------------------------
def export_path(mode, mk, well) -> Path:
    return root(mode) / "exports" / mk / f"{_safe(well)}.csv"


def save_export(mode, mk, well, df: pd.DataFrame, meta: dict) -> None:
    p = export_path(mode, mk, well)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index_label="date")
    meta = {**meta, "saved_at": datetime.now().isoformat(timespec="seconds")}
    p.with_suffix(".json").write_text(json.dumps(meta, indent=2))


def delete_export(mode, mk, well) -> None:
    p = export_path(mode, mk, well)
    p.unlink(missing_ok=True)
    p.with_suffix(".json").unlink(missing_ok=True)


def load_exports(mode, mk) -> dict[str, tuple[pd.DataFrame, dict]]:
    d = root(mode) / "exports" / mk
    out = {}
    if not d.exists():
        return out
    for p in sorted(d.glob("*.csv")):
        meta = json.loads(p.with_suffix(".json").read_text()) if p.with_suffix(".json").exists() else {}
        well = meta.get("well", p.stem)
        out[well] = (pd.read_csv(p, parse_dates=["date"], index_col="date"), meta)
    return out


# ---- PPRS -------------------------------------------------------------------
def load_pprs(mode) -> pd.DataFrame:
    p = root(mode) / "pprs.csv"
    if not p.exists():
        return pd.DataFrame(columns=list(PPRS_COLUMNS), index=pd.DatetimeIndex([], name="date"), dtype=float)
    df = pd.read_csv(p, parse_dates=["date"], index_col="date")
    for c in PPRS_COLUMNS:
        if c not in df.columns:
            df[c] = float("nan")
    return df[list(PPRS_COLUMNS)].sort_index()


def save_pprs(mode, df: pd.DataFrame) -> None:
    p = root(mode) / "pprs.csv"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_csv(p, index_label="date")


def merge_pprs(mode, new: pd.DataFrame) -> pd.DataFrame:
    cur = load_pprs(mode)
    merged = pd.concat([cur[~cur.index.isin(new.index)], new]).sort_index()
    save_pprs(mode, merged)
    return merged


def parse_pprs_upload(file) -> pd.DataFrame:
    """Read a PPRS table (the workbook's 'PPRS ' sheet layout, or plain CSV/XLSX with the same headers)."""
    name = getattr(file, "name", "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        raw = pd.read_excel(file, sheet_name=None, header=None)
        sheet = next((v for k, v in raw.items() if k.strip().upper() == "PPRS"), next(iter(raw.values())))
    else:
        sheet = pd.read_csv(file, header=None)
    # find the header row: the one containing 'Date'
    hdr = next(i for i, row in sheet.iterrows()
               if any(str(v).strip().lower() == "date" for v in row.values))
    df = sheet.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip() for c in sheet.iloc[hdr].values]
    date_col = next(c for c in df.columns if c.lower() == "date")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col)
    df.index = df.index.normalize()
    df.index.name = "date"
    lookup = {v.lower(): k for k, v in PPRS_COLUMNS.items()}
    lookup.update({k: k for k in PPRS_COLUMNS})
    out = pd.DataFrame(index=df.index)
    for c in df.columns:
        key = lookup.get(c.strip().lower())
        if key:
            out[key] = pd.to_numeric(df[c], errors="coerce")
    for c in PPRS_COLUMNS:
        if c not in out:
            out[c] = float("nan")
    return out[list(PPRS_COLUMNS)]
